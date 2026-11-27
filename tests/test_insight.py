"""선수별 한 줄 설명(insight.py) 검증. 실행: python tests/test_insight.py"""
import math
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import engine  # noqa: E402
import insight  # noqa: E402

BASELINE_SOURCE = os.path.join(HERE, "baseline", "matches_r103.csv")


def _load():
    rows, issues = engine.load_matches(BASELINE_SOURCE)
    assert not [i for i in issues if i.level == "error"], issues
    engine.fill_round_meta(rows)
    result = engine.compute(rows)
    return rows, result, insight.compute_insights(rows, result)


def test_every_player_gets_text_without_commas():
    rows, result, ins = _load()
    assert set(ins) == set(result.players)
    for name, d in ins.items():
        assert d["text"] and "," not in d["text"], (name, d["text"])


def test_placement_players_get_hold_back_sentence_only():
    _rows, _result, ins = _load()
    for name, d in ins.items():
        if d["games"] <= insight.CONFIG["placement_games"]:
            assert d["text"].startswith(f"아직 {d['games']}경기라 판단하기 어렵습니다."), (name, d["text"])
            assert d["elo_rank"] is None and d["gap"] is None


def test_adjusted_values_are_centered_and_sane():
    _rows, _result, ins = _load()
    thetas = [math.log(d["adj"]) for d in ins.values()]
    assert abs(sum(thetas) / len(thetas)) < 0.05  # 평균이 1.00 근처
    assert all(0.3 < d["adj"] < 3.5 for d in ins.values())


def test_adjusted_rating_is_converged_and_deterministic():
    rows, result, _ins = _load()
    recs = insight.build_records(rows)
    a = insight.adjusted_ratings(recs, 3.0, 300)
    b = insight.adjusted_ratings(recs, 3.0, 1000)
    assert max(abs(a[p] - b[p]) for p in a) < 1e-6  # 300번이면 충분히 수렴
    assert insight.compute_insights(rows, result) == insight.compute_insights(rows, result)


def test_more_kills_means_higher_adjusted_value():
    """같은 상대라면 킬/데스가 더 좋은 선수의 보정값이 더 높아야 한다."""
    rows = [
        engine.Row(round=r, nickname=n, team=t, kills=k, deaths=d, winning_team=1, map="m", mode="tdm",
                   team1_score=None, team2_score=None, player_score=None, line=0)
        for r in (1, 2, 3)
        for n, t, k, d in (("a", 1, 30, 10), ("b", 1, 20, 20), ("c", 2, 20, 20), ("d", 2, 10, 30))
    ]
    theta = insight.adjusted_ratings(insight.build_records(rows), 3.0, 300)
    assert theta["a"] > theta["b"] > theta["d"] and theta["a"] > theta["c"] > theta["d"]


def test_adjusted_trend_ends_at_final_value_and_covers_every_game():
    rows, _result, ins = _load()
    trend = insight.compute_adj_trend(rows)
    assert set(trend) == set(ins)
    for name, series in trend.items():
        assert len(series) == ins[name]["games"], name
        assert series[-1][1] == ins[name]["adj"], (name, series[-1], ins[name]["adj"])  # 마지막 점 = 현재 보정값
        rounds = [r for r, _ in series]
        assert rounds == sorted(rounds)
        assert all(0.1 < a < 5 for _, a in series)


def test_season_adjusted_values_use_only_that_seasons_games():
    rows, _result, ins = _load()
    out = insight.season_insight_rows(rows)
    games = {}
    for sid, name, n, adj, text in out:
        games[(sid, name)] = n
        assert 0.1 < float(adj) < 5
        assert text and "," not in text
    for name, d in ins.items():  # 시즌별 경기 수를 더하면 전체 경기 수
        assert sum(n for (s, p), n in games.items() if p == name) == d["games"], name


def test_each_season_starts_its_own_elo():
    rows, _result, _ins = _load()
    parts = dict(insight.season_parts(rows))
    assert set(parts) == {1, 2}
    assert sum(len(p) for p in parts.values()) == len(rows)
    # 시즌 1은 합산 계산의 앞부분과 같고, 시즌 2는 이전 기록 없이 1500에서 시작한다
    combined = engine.compute(rows)
    s1 = engine.compute(parts[1])
    assert [h for h in combined.history if h[0] <= 92] == s1.history
    first = min(r.round for r in parts[2])
    opening = engine.compute([r for r in rows if r.round == first])
    assert [h for h in engine.compute(parts[2]).history if h[0] == first] == opening.history
    assert {r[:3] for r in insight.season_trend_rows(rows)} >= {(2, r.nickname, r.round) for r in parts[2] if r.winning_team in (1, 2)}


def test_josa_by_last_digit():
    assert insight._ro(1443) == "으로" and insight._ro(1678) == "로" and insight._ro(1490) == "으로"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"실패: {name}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    sys.exit(1 if failed else 0)
