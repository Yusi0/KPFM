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
            assert d["text"].startswith(f"아직 {d['games']}경기라 평가하기엔 이릅니다."), (name, d["text"])
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
