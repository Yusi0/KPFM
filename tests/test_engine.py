"""엔진 검증. 실행: python tests/test_engine.py

합격 기준: 103라운드 시점의 원본(tests/baseline/matches_r103.csv)으로 계산한 결과가,
기존 시스템(elo.py + DB)이 계산해 둔 정답(tests/baseline/*.csv)과 정확히 같아야 한다.
기준 파일은 고정본이라 실제 원본(data/source/matches.csv)이 이후 바뀌어도 이 테스트는 영향을 받지 않는다.
"""
import collections
import csv
import functools
import os
import random
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import build  # noqa: E402
import engine  # noqa: E402
import reference_elo  # noqa: E402

BASE = os.path.join(HERE, "baseline")
BASELINE_SOURCE = os.path.join(BASE, "matches_r103.csv")
LIVE_SOURCE = os.path.join(ROOT, "data", "source", "matches.csv")
LEGACY = [(1, engine.legacy_v1)]  # 고정 기준값(기존 시스템 결과)은 기존 공식으로만 재현된다


def _load(path):
    rows, issues = engine.load_matches(path)
    assert not [i for i in issues if i.level == "error"], issues
    return engine.fill_round_meta(rows)


def _baseline_rows():
    return _load(BASELINE_SOURCE)


def _read(name):
    with open(os.path.join(BASE, name), newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))[1:]


# ------------------------------------------------------------------ 합격 기준: 기존 시스템 재현

def test_formula_identical_to_reference():
    rnd = random.Random(1)
    for _ in range(20000):
        elo, opp = rnd.randint(900, 2300), rnd.uniform(900, 2300)
        res, k, d, tot = rnd.randint(0, 1), rnd.randint(0, 60), rnd.randint(0, 60), rnd.randint(0, 120)
        assert engine.legacy_v1(elo, opp, res, k, d, tot) == reference_elo.calculate_elo(elo, opp, res, k, d, tot, 0), (elo, opp, res, k, d, tot)
    for elo in range(0, 3300, 7):
        assert engine.calculate_tier(elo) == reference_elo.calculate_tier(elo), elo


def test_reproduces_baseline_exactly():
    result = engine.compute(_baseline_rows(), LEGACY)
    expected = {r[0]: tuple(r[1:]) for r in _read("players_r103.csv")}
    mine = {n: tuple(str(x) for x in (p.kills, p.deaths, p.wins, p.losses, p.total, p.elo, p.tier)) for n, p in result.players.items()}
    assert set(expected) == set(mine), set(expected) ^ set(mine)
    bad = [n for n in expected if expected[n] != mine[n]]
    assert not bad, [(n, expected[n], mine[n]) for n in bad[:5]]

    ac = sorted(tuple(str(x) for x in h) for h in result.history)
    assert ac == sorted(tuple(r) for r in _read("aftercalc_r103.csv")), "aftercalc 불일치"
    assert len(ac) == 931 and len(mine) == 92


def test_web_csvs_match_baseline():
    rows = _baseline_rows()
    result = engine.compute(rows, LEGACY)
    with tempfile.TemporaryDirectory() as tmp:
        build.write_web_csvs(tmp, rows, result)
        read = lambda name: list(csv.reader(open(os.path.join(tmp, name), encoding="utf-8-sig")))

        lb = read("lboard.csv")
        assert lb[0] == ["Rank", "Nickname", "Kills", "Deaths", "Wins", "Losses", "Total", "ELO", "Tier"]
        assert {r[1]: r[2:] for r in lb[1:]} == {r[0]: r[1:] for r in _read("players_r103.csv")}
        elos = [int(r[7]) for r in lb[1:]]
        assert elos == sorted(elos, reverse=True), "순위가 ELO 내림차순이 아님"
        assert [int(r[0]) for r in lb[1:]] == list(range(1, len(lb)))

        ac = read("aftercalc.csv")
        assert ac[0] == ["Round", "Nickname", "ELO"]
        assert sorted((r[0], r[1], r[2]) for r in ac[1:]) == sorted((r[0], r[1], r[5]) for r in _read("aftercalc_r103.csv"))

        mt = read("match.csv")
        assert mt[0] == ["Round", "Nickname", "Team", "Kills", "Deaths", "Winning Team", "Map", "Mode", "Team1 Score", "Team2 Score", "Player Score"]
        assert sorted(tuple(r) for r in mt[1:]) == sorted(tuple(r) for r in _read("matches_filled_r103.csv")), "match.csv 불일치 (모드/점수 채움 포함)"

        # 웹이 split(',')로 읽으므로 모든 행의 필드 수가 헤더와 같아야 한다
        for name in ("lboard.csv", "match.csv", "aftercalc.csv"):
            text = open(os.path.join(tmp, name), encoding="utf-8-sig").read().strip().split("\n")
            n = len(text[0].split(","))
            assert all(len(line.split(",")) == n for line in text), name


# ------------------------------------------------------------------ 구조적 성질 (이전 시스템의 버그가 구조적으로 안 생기는지)

def test_row_order_does_not_matter():
    rows = _baseline_rows()
    base = engine.compute(rows, LEGACY)
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    other = engine.compute(shuffled, LEGACY)
    assert {n: p.elo for n, p in base.players.items()} == {n: p.elo for n, p in other.players.items()}
    assert sorted(base.history) == sorted(other.history)


def test_edit_in_middle_equals_fresh_compute():
    """중간 라운드를 고치거나 지워도, 결과는 수정된 원본을 처음부터 계산한 것과 같다 (부분 재계산이 없으므로 성립해야 함)."""
    rows = _baseline_rows()
    victim = next(r for r in rows if r.round == 60)
    deleted = [r for r in rows if r is not victim]
    edited = [engine.Row(**{**r.__dict__, "kills": r.kills + 9}) if r.round == 30 and r.nickname == rows[0].nickname else r for r in rows]
    for variant in (deleted, edited):
        a = engine.compute(variant)
        b = engine.compute([engine.Row(**r.__dict__) for r in variant])
        assert {n: p.elo for n, p in a.players.items()} == {n: p.elo for n, p in b.players.items()}
    # 수정한 라운드 이전은 전혀 변하지 않는다
    base, after = engine.compute(rows), engine.compute(deleted)
    early = lambda res: sorted(h for h in res.history if h[0] < 60)
    assert early(base) == early(after)


def test_ruleset_applies_only_from_start_round():
    rows = _baseline_rows()
    base = engine.compute(rows, LEGACY)

    def harsher(elo, opp, res, k, d, total, ctx=None):
        return engine.legacy_v1(elo, opp, res, k, d, total) + 1

    new = engine.compute(rows, ruleset=[(1, engine.legacy_v1), (101, harsher)])
    before = lambda res: sorted(h for h in res.history if h[0] <= 100)
    assert before(base) == before(new), "새 규칙이 시작 라운드 이전에 영향을 줌"
    assert sorted(h for h in base.history if h[0] >= 101) != sorted(h for h in new.history if h[0] >= 101)


def test_draw_rounds_are_ignored():
    rows = _baseline_rows()
    extra = [engine.Row(round=500, nickname=n, team=t, kills=5, deaths=5, winning_team=0)
             for n, t in (("DrawA", 1), ("DrawB", 2))]
    a, b = engine.compute(rows), engine.compute(rows + extra)
    assert {n: p.elo for n, p in a.players.items()} == {n: p.elo for n, p in b.players.items() if n in a.players}
    assert b.skipped_rounds == [500]
    assert b.players["DrawA"].total == 0 and b.players["DrawA"].elo == 1500


# ------------------------------------------------------------------ 새 규칙 (rule_v2, 99라운드부터)

# 공식의 구조를 손으로 검증하기 쉬운 기본 배율(K x1, 성과 x1). 현재 기본값(K x1.5, 성과 x2)은 아래 별도 테스트에서 고정한다.
BASE_V2 = functools.partial(engine.rule_v2, k_multiplier=1.0, perf_weight=1.0)


def _ctx(own, opp, rows):
    return engine.RoundContext(round=1, own_avg=own, opp_avg=opp, rows=rows)


def test_v2_hand_computed_example():
    """직접 손으로 계산한 값과 일치해야 한다. 모두 1500, K=50, E=0.5 → 승리 팀 +25, 패배 팀 -25 에 성과 보정."""
    mk = lambda n, t, k, d: engine.Row(round=1, nickname=n, team=t, kills=k, deaths=d, winning_team=1)
    rows = [mk("p1", 1, 10, 5), mk("p2", 1, 20, 10), mk("p3", 2, 10, 10), mk("p4", 2, 5, 15)]
    res = engine.compute(rows, [(1, BASE_V2)])
    # 성과 raw: p1 1.65, p2 3.30, p3 1.30, p4 -0.05 → 평균 1.55
    assert {n: p.elo for n, p in res.players.items()} == {"p1": 1525, "p2": 1527, "p3": 1475, "p4": 1473}


def test_v2_teammates_share_outcome_term():
    """같은 팀 선수는 (경기 수가 같고 성과가 같다면) 같은 결과항을 받는다. 개인 ELO가 달라도 약한 선수가 과하게 흔들리지 않음."""
    rows = [engine.Row(round=1, nickname=f"x{i}", team=1 + i % 2, kills=10, deaths=10, winning_team=1) for i in range(4)]
    # 선수마다 ELO가 다르게 만들기 위해 앞선 라운드를 하나 더 둔다 (모든 규칙 동일하게 v2)
    warm = [engine.Row(round=0, nickname="x0", team=1, kills=40, deaths=0, winning_team=1),
            engine.Row(round=0, nickname="x1", team=2, kills=0, deaths=40, winning_team=1)]
    res0 = engine.compute(warm, [(0, engine.rule_v2)])
    before = {n: p.elo for n, p in res0.players.items()}
    res1 = engine.compute(warm + rows, [(0, engine.rule_v2)])
    # 같은 팀 내 두 선수(x0, x2)의 변화량 차이는 K 차이(경기 수)로만 생긴다: x0은 1경기 뒤라 K가 같은 50 → 결과항 동일
    d0 = res1.players["x0"].elo - before["x0"]; d2 = res1.players["x2"].elo - 1500
    assert d0 == d2, (d0, d2)


def test_v2_loss_costs_favorite_more_than_underdog():
    """표준 ELO의 성질: 지는 경우 기대승률이 높았던(강한) 팀이 더 많이 잃는다. (기존 공식은 반대였음)"""
    rows = [engine.Row(round=1, nickname=f"q{i}", team=1, kills=10, deaths=10, winning_team=2) for i in range(2)]
    same = lambda: _ctx(0, 0, rows)  # 성과가 모두 같아 성과항은 0
    fav = BASE_V2(1700, 1500, 0, 10, 10, 20, ctx=engine.RoundContext(1, 1700, 1500, rows))
    dog = BASE_V2(1500, 1700, 0, 10, 10, 20, ctx=engine.RoundContext(1, 1500, 1700, rows))
    assert 1700 - fav > 1500 - dog > 0, (1700 - fav, 1500 - dog)
    # 이기는 경우는 반대: 약한 팀이 이기면 더 많이 얻는다
    fav_w = BASE_V2(1700, 1500, 1, 10, 10, 20, ctx=engine.RoundContext(1, 1700, 1500, rows))
    dog_w = BASE_V2(1500, 1700, 1, 10, 10, 20, ctx=engine.RoundContext(1, 1500, 1700, rows))
    assert dog_w - 1500 > fav_w - 1700 > 0


def test_v2_pinned_numbers_for_sensitivity_and_k():
    """민감도(400)와 K 스케줄이 바뀌면 잡히도록 정확한 값을 고정한다. 경기 수 20 → K = 30/(1+15/20) = 17.14.
    1700 vs 1500 (E = 0.7597): 강한 팀이 지면 -13.02 → 1687, 약한 팀이 지면 E = 0.2403 → -4.12 → 1496.
    (민감도가 200이면 각각 1684, 1498이 되어 이 테스트가 실패한다)"""
    rows = [engine.Row(round=1, nickname=f"q{i}", team=1, kills=10, deaths=10, winning_team=2) for i in range(2)]
    fav = BASE_V2(1700, 1500, 0, 10, 10, 20, ctx=engine.RoundContext(1, 1700, 1500, rows))
    dog = BASE_V2(1500, 1700, 0, 10, 10, 20, ctx=engine.RoundContext(1, 1500, 1700, rows))
    assert (fav, dog) == (1687, 1496), (fav, dog)
    win_fav = BASE_V2(1700, 1500, 1, 10, 10, 20, ctx=engine.RoundContext(1, 1700, 1500, rows))
    win_dog = BASE_V2(1500, 1700, 1, 10, 10, 20, ctx=engine.RoundContext(1, 1500, 1700, rows))
    assert (win_fav, win_dog) == (1704, 1513), (win_fav, win_dog)   # +4.12, +13.02
    assert engine.k_factor(0) == 50 and engine.k_factor(5) == 50 and abs(engine.k_factor(20) - 17.142857) < 1e-5 and engine.k_factor(1000) == 15


def test_v2_performance_is_zero_sum_within_round():
    """성과항은 라운드 평균을 빼므로, 모두 같은 성과면 성과항이 0이고 아니면 합이 0이다."""
    rows = [engine.Row(round=1, nickname=f"z{i}", team=1 + i % 2, kills=10 + i, deaths=10, winning_team=1) for i in range(6)]
    raws = [r.kills * 0.2 - r.deaths * 0.07 for r in rows]
    mean = sum(raws) / len(raws)
    assert abs(sum(x - mean for x in raws)) < 1e-9
    same = [engine.Row(round=1, nickname="a", team=1, kills=7, deaths=3, winning_team=1), engine.Row(round=1, nickname="b", team=2, kills=7, deaths=3, winning_team=1)]
    a = BASE_V2(1500, 1500, 1, 7, 3, 0, ctx=engine.RoundContext(1, 1500, 1500, same))
    assert a == 1500 + 25, a  # K=50, E=0.5 → +25, 성과 보정 0


def test_v2_has_no_inflation_over_history():
    """기존 공식은 라운드마다 전체 ELO가 평균 +25 이상 늘지만, 새 규칙은 0에 가까워야 한다 (고정 데이터에 처음부터 적용해 비교)."""
    rows = _baseline_rows()

    def mean_net(ruleset):
        res = engine.compute(rows, ruleset)
        last, net = {}, collections.defaultdict(float)
        for rnd, nick, _k, _d, _kdr, elo in res.history:
            net[rnd] += elo - last.get(nick, 1500)
            last[nick] = elo
        return sum(net.values()) / len(net)

    legacy, v2 = mean_net(LEGACY), mean_net([(1, engine.rule_v2)])
    assert legacy > 20, legacy
    assert abs(v2) < 3, v2


def test_v2_requires_context_and_handles_draws():
    try:
        engine.rule_v2(1500, 1500, 1, 1, 1, 0)
        assert False, "ctx 없이 호출되면 안 됨"
    except ValueError:
        pass
    rows = [engine.Row(round=500, nickname=n, team=t, kills=5, deaths=5, winning_team=0) for n, t in (("DrawA", 1), ("DrawB", 2))]
    res = engine.compute(rows, [(1, engine.rule_v2)])
    assert res.skipped_rounds == [500] and res.players["DrawA"].elo == 1500


def test_v2_defaults_are_k_1_5_and_perf_2():
    assert engine.V2_K_MULTIPLIER == 1.5 and engine.V2_PERF_WEIGHT == 2.0
    assert engine.RULESET == [(1, engine.rule_v2)], "현재는 첫 라운드부터 새 규칙을 쓴다"
    assert engine.rule_for_round(1) is engine.rule_v2 and engine.rule_for_round(98) is engine.rule_v2


def test_v2_defaults_hand_computed_example():
    """현재 기본값 손계산: 모두 1500, 첫 경기라 K = 50 x 1.5 = 75, E = 0.5 → 결과항 +-37.5.
    성과(raw): p1 1.65, p2 3.30, p3 1.30, p4 -0.05, 평균 1.55 → x2: +0.2, +3.5, -0.5, -3.2"""
    mk = lambda n, t, k, d: engine.Row(round=1, nickname=n, team=t, kills=k, deaths=d, winning_team=1)
    rows = [mk("p1", 1, 10, 5), mk("p2", 1, 20, 10), mk("p3", 2, 10, 10), mk("p4", 2, 5, 15)]
    res = engine.compute(rows)   # 기본 규칙
    assert {n: p.elo for n, p in res.players.items()} == {"p1": 1538, "p2": 1541, "p3": 1462, "p4": 1459}


def test_v2_defaults_pinned_numbers():
    """경기 수 20 → K = 17.14 x 1.5 = 25.71. 1700 vs 1500 (E = 0.7597).
    강한 팀이 지면 -19.54 → 1680, 약한 팀이 지면 -6.18 → 1494. 이기면 각각 +6.18 → 1706, +19.54 → 1520."""
    rows = [engine.Row(round=1, nickname=f"q{i}", team=1, kills=10, deaths=10, winning_team=2) for i in range(2)]
    c = lambda own, opp: engine.RoundContext(1, own, opp, rows)
    assert engine.rule_v2(1700, 1500, 0, 10, 10, 20, ctx=c(1700, 1500)) == 1680
    assert engine.rule_v2(1500, 1700, 0, 10, 10, 20, ctx=c(1500, 1700)) == 1494
    assert engine.rule_v2(1700, 1500, 1, 10, 10, 20, ctx=c(1700, 1500)) == 1706
    assert engine.rule_v2(1500, 1700, 1, 10, 10, 20, ctx=c(1500, 1700)) == 1520
    # 첫 5경기는 K가 75, 이후 하한은 22.5 → 같은 조건에서 변동이 더 큼
    first = engine.rule_v2(1500, 1500, 1, 10, 10, 0, ctx=c(1500, 1500)) - 1500
    veteran = engine.rule_v2(1500, 1500, 1, 10, 10, 1000, ctx=c(1500, 1500)) - 1500
    assert first == 38 and veteran == 11, (first, veteran)   # 37.5 → 38, 22.5 x 0.5 = 11.25 → 11


def test_default_compute_equals_explicit_v2_and_differs_from_legacy():
    rows = [r for r in _baseline_rows() if r.round <= 98]
    default, explicit, legacy = engine.compute(rows), engine.compute(rows, [(1, engine.rule_v2)]), engine.compute(rows, LEGACY)
    assert sorted(default.history) == sorted(explicit.history)
    assert sorted(default.history) != sorted(legacy.history)


# ------------------------------------------------------------------ 검증 규칙

def _issues(rows):
    return engine.validate(engine.fill_round_meta(rows))


def _mk(rnd, nick, team, win=1, **kw):
    return engine.Row(round=rnd, nickname=nick, team=team, kills=1, deaths=1, winning_team=win, line=2, **kw)


def test_validation_catches_hand_edit_mistakes():
    base = [_mk(1, "a", 1), _mk(1, "b", 2)]
    assert not [i for i in _issues(base) if i.level == "error"]
    cases = {
        "중복 닉네임": base + [_mk(1, "a", 2)],
        "팀 값": [_mk(1, "a", 3), _mk(1, "b", 2)],
        "승리 팀 불일치": [_mk(1, "a", 1, win=1), _mk(1, "b", 2, win=2)],
        "모드 충돌": [_mk(1, "a", 1, mode="tdm"), _mk(1, "b", 2, mode="hp")],
        "점수 충돌": [_mk(1, "a", 1, team1_score=1, team2_score=2), _mk(1, "b", 2, team1_score=3, team2_score=2)],
        "한쪽 점수만": [_mk(1, "a", 1, team1_score=1), _mk(1, "b", 2)],
        "쉼표 모드": [_mk(1, "a", 1, mode="a,b"), _mk(1, "b", 2)],
        "승리팀 범위": [_mk(1, "a", 1, win=5), _mk(1, "b", 2, win=5)],
    }
    for label, rows in cases.items():
        assert [i for i in _issues(rows) if i.level == "error"], f"오류를 못 잡음: {label}"


def test_validation_warnings():
    rows = [_mk(1, "Eris_NIx", 1, win=1, team1_score=10, team2_score=50), _mk(1, "Eris_Nlx", 2, win=1)]
    msgs = " ".join(i.message for i in _issues(rows) if i.level == "warning")
    assert "비슷한 닉네임" in msgs and "점수 10:50" in msgs


def test_duplicate_round_warning():
    def rnd(n, kills=10):
        return [engine.Row(round=n, nickname=f"p{i}", team=1 + i % 2, kills=kills + i, deaths=5, winning_team=1, line=2) for i in range(6)]
    msgs = lambda rows: " ".join(i.message for i in _issues(rows) if i.level == "warning")
    assert "거의 같습니다" in msgs(rnd(1) + rnd(2)), "같은 기록의 두 라운드를 못 잡음"
    assert "거의 같습니다" not in msgs(rnd(1) + rnd(2, kills=30)), "다른 기록인데 경고함"
    near = rnd(2); near[0] = engine.Row(round=2, nickname="typo", team=1, kills=10, deaths=5, winning_team=1, line=2)
    assert "거의 같습니다" in msgs(rnd(1) + near), "닉네임 1개만 다른 복사본을 못 잡음 (5/6 동일)"


def test_known_duplicate_rounds_in_baseline_are_flagged():
    """실제 원본에 있는 중복 의심 라운드 쌍(5·8, 50·66, 93·95)이 경고로 잡혀야 한다."""
    text = " ".join(i.message for i in engine.validate(_baseline_rows()) if i.level == "warning")
    for a, b in ((5, 8), (50, 66), (93, 95)):
        assert f"라운드 {a}와 {b}의 기록이 거의 같습니다" in text, (a, b)


def test_split_nickname_warning():
    msgs = lambda rows: " ".join(i.message for i in _issues(rows) if i.level == "warning")
    a = [_mk(1, "river091211070822", 1), _mk(1, "x", 2), _mk(2, "river0912110708", 1), _mk(2, "y", 2)]
    assert "같은 사람인지 확인" in msgs(a), "철자만 다른 닉네임(함께 나온 적 없음)을 못 잡음"
    b = [_mk(1, "river091211070822", 1), _mk(1, "river0912110708", 2)]
    assert "같은 사람인지 확인" not in msgs(b), "같은 라운드에 함께 나온 두 닉네임은 다른 사람이므로 경고하면 안 됨"
    assert "같은 사람인지 확인" in " ".join(i.message for i in engine.validate(_baseline_rows()) if i.level == "warning"), "고정 데이터의 river 분리를 못 잡음"


def test_fill_down_within_round():
    rows = [_mk(1, "a", 1, mode="TDM"), _mk(1, "b", 2, team1_score=3), _mk(1, "c", 2, team2_score=4)]
    engine.fill_round_meta(rows)
    assert {(r.mode, r.team1_score, r.team2_score) for r in rows} == {("TDM", 3, 4)}


def test_load_reports_bad_lines():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "m.csv")
        open(p, "w", encoding="utf-8-sig").write("Round,Nickname,Team,Kills,Deaths,Winning Team\n1,a,1,x,2,1\n1,b,2,3,4,1\n")
        rows, issues = engine.load_matches(p)
        assert len(rows) == 1 and len(issues) == 1 and "정수가 아닙니다" in issues[0].message
        open(p, "w", encoding="utf-8-sig").write("Round,Nickname\n1,a\n")
        _rows_, issues = engine.load_matches(p)
        assert "필수 열" in issues[0].message


def test_live_source_is_clean():
    """실제 원본(data/source/matches.csv)에 오류가 없어야 한다. 새 라운드를 넣은 뒤 오류가 생기면 여기서 잡힌다."""
    rows = _load(LIVE_SOURCE)
    errors = [i for i in engine.validate(rows) if i.level == "error"]
    assert not errors, errors


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
