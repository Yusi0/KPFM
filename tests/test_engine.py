"""엔진 검증. 실행: python tests/test_engine.py (pytest가 있으면 pytest tests 도 가능)

합격 기준: 원본 matches.csv로 새 엔진이 계산한 결과가 기존 시스템(elo.py + data.db)의 결과와 정확히 같아야 한다.
"""
import ast
import csv
import os
import random
import sqlite3
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import build  # noqa: E402
import engine  # noqa: E402

SOURCE = os.path.join(ROOT, "data", "source", "matches.csv")
DB_PATH = os.path.join(ROOT, "data", "elo", "db", "data.db")
OLD_ELO_PY = os.path.join(ROOT, "elo.py")


def _rows():
    rows, issues = engine.load_matches(SOURCE)
    assert not [i for i in issues if i.level == "error"], issues
    return engine.fill_round_meta(rows)


def _db():
    assert os.path.exists(DB_PATH), "기존 DB가 없어 재현 테스트를 할 수 없습니다"
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _old_calculate_elo():
    """기존 elo.py의 calculate_elo/calculate_tier를 import 없이(DB 연결 없이) 소스에서 꺼낸다."""
    tree = ast.parse(open(OLD_ELO_PY, encoding="utf-8").read())
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("calculate_elo", "calculate_tier"):
            exec(compile(ast.Module([node], []), "elo.py", "exec"), ns)
    return ns["calculate_elo"], ns["calculate_tier"]


# ------------------------------------------------------------------ 합격 기준: 기존 시스템 재현

def test_formula_identical_to_old_calculate_elo():
    old, old_tier = _old_calculate_elo()
    rnd = random.Random(1)
    for _ in range(20000):
        elo, opp = rnd.randint(900, 2300), rnd.uniform(900, 2300)
        res, k, d, tot = rnd.randint(0, 1), rnd.randint(0, 60), rnd.randint(0, 60), rnd.randint(0, 120)
        assert engine.legacy_v1(elo, opp, res, k, d, tot) == old(elo, opp, res, k, d, tot, 0), (elo, opp, res, k, d, tot)
    for elo in range(0, 3300, 7):
        assert engine.calculate_tier(elo) == old_tier(elo), elo


def test_reproduces_database_exactly():
    rows = _rows()
    result = engine.compute(rows)
    con = _db()
    lb = {r[0]: r[1:] for r in con.execute("SELECT nickname, kills, deaths, wins, losses, total, elo, tier FROM leaderboard")}
    mine = {n: (p.kills, p.deaths, p.wins, p.losses, p.total, p.elo, p.tier) for n, p in result.players.items()}
    assert set(lb) == set(mine), (set(lb) ^ set(mine))
    bad = [n for n in lb if lb[n] != mine[n]]
    assert not bad, [(n, lb[n], mine[n]) for n in bad[:5]]

    ac = sorted(con.execute("SELECT round, nickname, total_kills_at_round, total_deaths_at_round, kdr_at_round, elo_after_round FROM aftercalc"))
    assert sorted(result.history) == ac, "aftercalc 불일치"
    assert len(ac) == 931, len(ac)


def test_web_csvs_match_database():
    rows = _rows()
    result = engine.compute(rows)
    con = _db()
    with tempfile.TemporaryDirectory() as tmp:
        build.write_web_csvs(tmp, rows, result)
        read = lambda name: list(csv.reader(open(os.path.join(tmp, name), encoding="utf-8-sig")))

        lb = read("lboard.csv")
        assert lb[0] == ["Rank", "Nickname", "Kills", "Deaths", "Wins", "Losses", "Total", "ELO", "Tier"]
        db_lb = {r[0]: [str(x) for x in r[1:]] for r in con.execute("SELECT nickname, kills, deaths, wins, losses, total, elo, tier FROM leaderboard")}
        assert {r[1]: r[2:] for r in lb[1:]} == db_lb
        elos = [int(r[7]) for r in lb[1:]]
        assert elos == sorted(elos, reverse=True), "순위가 ELO 내림차순이 아님"
        assert [int(r[0]) for r in lb[1:]] == list(range(1, len(lb)))

        ac = read("aftercalc.csv")
        assert ac[0] == ["Round", "Nickname", "ELO"]
        db_ac = sorted((str(r), n, str(e)) for r, n, e in con.execute("SELECT round, nickname, elo_after_round FROM aftercalc"))
        assert sorted(tuple(r) for r in ac[1:]) == db_ac

        mt = read("match.csv")
        assert mt[0] == ["Round", "Nickname", "Team", "Kills", "Deaths", "Winning Team", "Map", "Mode", "Team1 Score", "Team2 Score", "Player Score"]
        db_m = sorted(tuple("" if v is None else str(v) for v in r) for r in con.execute(
            "SELECT round, nickname, team, kills, deaths, winning_team, map, mode, team1_score, team2_score, player_score FROM matches"))
        assert sorted(tuple(r) for r in mt[1:]) == db_m, "match.csv가 DB와 다름 (모드/점수 채움 포함)"
        # 웹이 split(',')로 읽으므로 모든 행의 필드 수가 헤더와 같아야 한다
        for name in ("lboard.csv", "match.csv", "aftercalc.csv"):
            text = open(os.path.join(tmp, name), encoding="utf-8-sig").read().strip().split("\n")
            n = len(text[0].split(","))
            assert all(len(line.split(",")) == n for line in text), name


def test_write_db_roundtrip_equals_existing_db():
    rows = _rows()
    result = engine.compute(rows)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.db")
        build.write_db(path, rows, result)
        new, old = sqlite3.connect(path), _db()
        for q in ("SELECT nickname, kills, deaths, wins, losses, total, elo, tier FROM leaderboard ORDER BY nickname",
                  "SELECT round, nickname, team, kills, deaths, map, winning_team, mode, team1_score, team2_score, player_score FROM matches ORDER BY round, nickname",
                  "SELECT round, nickname, total_kills_at_round, total_deaths_at_round, kdr_at_round, elo_after_round FROM aftercalc ORDER BY round, nickname"):
            assert new.execute(q).fetchall() == old.execute(q).fetchall(), q
        new.close()


# ------------------------------------------------------------------ 구조적 성질 (이전 시스템의 버그가 구조적으로 안 생기는지)

def test_row_order_does_not_matter():
    rows = _rows()
    base = engine.compute(rows)
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    other = engine.compute(shuffled)
    assert {n: p.elo for n, p in base.players.items()} == {n: p.elo for n, p in other.players.items()}
    assert sorted(base.history) == sorted(other.history)


def test_edit_in_middle_equals_fresh_compute():
    """중간 라운드를 고치거나 지워도, 결과는 수정된 원본을 처음부터 계산한 것과 같다 (부분 재계산이 없으므로 당연히 성립해야 함)."""
    rows = _rows()
    victim = next(r for r in rows if r.round == 60)
    edited = [r for r in rows if r is not victim]            # 삭제
    edited2 = [engine.Row(**{**r.__dict__, "kills": r.kills + 9}) if r.round == 30 and r.nickname == rows[0].nickname else r for r in rows]
    for variant in (edited, edited2):
        a = engine.compute(variant)
        b = engine.compute([engine.Row(**r.__dict__) for r in variant])
        assert {n: p.elo for n, p in a.players.items()} == {n: p.elo for n, p in b.players.items()}
    # 그리고 수정된 라운드 이전은 전혀 변하지 않는다
    base = engine.compute(rows)
    after = engine.compute(edited)
    early = lambda res: sorted(h for h in res.history if h[0] < 60)
    assert early(base) == early(after)


def test_ruleset_applies_only_from_start_round():
    rows = _rows()
    base = engine.compute(rows)

    def harsher(elo, opp, res, k, d, total):
        return engine.legacy_v1(elo, opp, res, k, d, total) + 1

    new = engine.compute(rows, ruleset=[(1, engine.legacy_v1), (101, harsher)])
    before = lambda res: sorted(h for h in res.history if h[0] <= 100)
    assert before(base) == before(new), "새 규칙이 시작 라운드 이전에 영향을 줌"
    assert sorted(h for h in base.history if h[0] >= 101) != sorted(h for h in new.history if h[0] >= 101)


def test_draw_rounds_are_ignored():
    rows = _rows()
    extra = [engine.Row(round=500, nickname=n, team=t, kills=5, deaths=5, winning_team=0)
             for n, t in (("DrawA", 1), ("DrawB", 2))]
    a, b = engine.compute(rows), engine.compute(rows + extra)
    assert {n: p.elo for n, p in a.players.items()} == {n: p.elo for n, p in b.players.items() if n in a.players}
    assert b.skipped_rounds == [500]
    assert b.players["DrawA"].total == 0 and b.players["DrawA"].elo == 1500


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


def test_source_file_is_clean():
    rows = _rows()
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
