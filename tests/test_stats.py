"""유저 통계 검증. 실행: python tests/test_stats.py"""
import collections
import csv
import io
import os
import subprocess
import sys
import traceback
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import engine  # noqa: E402
import stats  # noqa: E402

BASELINE_SOURCE = os.path.join(HERE, "baseline", "matches_r103.csv")
BASELINE_PLAYERS = os.path.join(HERE, "baseline", "players_r103.csv")


LEGACY = [(1, engine.legacy_v1)]  # 고정 기준값은 기존 공식 결과


def _players():
    return stats.load_players(BASELINE_SOURCE, LEGACY)


def test_parse_separators():
    expected = ["a", "b", "c"]
    for text in ("a b c", "a,b,c", "a, b, c", "a ,b ,c", "  a,  b   c  ", "a，b，c", "a,,b,\tc,"):
        assert stats.parse_names(text) == expected, text
    assert stats.parse_names("A a A") == ["A"], "대소문자 다른 중복은 한 번만"
    assert stats.parse_names("") == [] and stats.parse_names(" , ") == []


def test_rows_match_old_system_calculation():
    """예전 display_user_statistics와 같은 계산이어야 한다 (기준값: 기존 시스템이 계산해 둔 선수별 합계)."""
    old = {}
    with open(BASELINE_PLAYERS, newline="", encoding="utf-8-sig") as f:
        for nickname, kills, deaths, wins, losses, total, elo, tier in list(csv.reader(f))[1:]:
            kills, deaths, wins, losses, total, elo = map(int, (kills, deaths, wins, losses, total, elo))
            kdr = round(kills / max(1, deaths), 2)
            win_rate = round((wins / max(1, total)) * 100, 1) if total > 0 else 0.0
            kpm = round(kills / max(1, total), 1) if total > 0 else 0.0
            old[nickname] = [nickname, kills, deaths, kdr, wins, losses, win_rate, kpm, elo, tier if total > 5 else "Unranked"]
    new = {p.nickname: stats.stat_row(p) for p in _players().values()}
    assert new == old


def test_resolve_case_insensitive_and_all():
    players = _players()
    found, missing = stats.resolve(["GUKBAB2", "axaeny"], players)
    assert sorted(p.nickname for p in found) == ["Axaeny", "gukbab2"] and not missing
    found, _ = stats.resolve(["all"], players)
    assert len(found) == len(players)
    found, _ = stats.resolve(["ALL", "x"], players)
    assert len(found) == len(players)
    found, _ = stats.resolve(["gukbab2", "GUKBAB2", "gukbab2"], players)
    assert len(found) == 1, "같은 선수를 여러 번 입력해도 한 번만"


def test_missing_names_reported_with_suggestions():
    players = _players()
    found, missing = stats.resolve(["gukbab2", "Axaen", "Eris_Nlx", "zzzzzzzz"], players)
    assert [p.nickname for p in found] == ["gukbab2"]
    assert "Axaeny" in missing["Axaen"]
    assert "Eris_NIx" in missing["Eris_Nlx"], "I/l 헷갈리는 닉네임을 추천해야 함"
    assert missing["zzzzzzzz"] == []


def test_sorted_by_elo_desc():
    rows = [stats.stat_row(p) for p in stats.sort_players(_players().values())]
    elos = [r[8] for r in rows]
    assert elos == sorted(elos, reverse=True)


def test_cli_end_to_end():
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    run = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "stats.py"), "--source", BASELINE_SOURCE, *a], capture_output=True, text=True, encoding="utf-8", env=env)
    for args in (["gukbab2", "Axaeny"], ["gukbab2,Axaeny"], ["gukbab2, Axaeny"], ["gukbab2 ,", "Axaeny"]):
        r = run(*args)
        assert r.returncode == 0, (args, r.stdout, r.stderr)
        assert "gukbab2" in r.stdout and "Axaeny" in r.stdout and "Nickname" in r.stdout, args
        assert r.stdout.index("gukbab2") < r.stdout.index("Axaeny"), "ELO 순서(gukbab2 2120 > Axaeny 1945)"
    r = run("gukbab2", "nobody")
    assert r.returncode == 2 and "gukbab2" in r.stdout and "nobody" in r.stdout
    r = run("nobody")
    assert r.returncode == 1
    r = run("all")
    assert r.returncode == 0 and r.stdout.count("\n") > 90


def test_window_stats_match_manual_count():
    """구간 통계(--since)가 기준 데이터를 직접 센 값과 같고, 구간 시작 전 대비 ELO 변화가 맞아야 한다."""
    since = 98  # 고정 기준값(예전 번호)의 마지막 6라운드 = 현재 번호의 93~98라운드
    rows, _ = engine.load_matches(BASELINE_SOURCE)
    engine.fill_round_meta(rows)
    win = stats.window_stats(rows, since, LEGACY)
    manual = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for r in rows:
        if r.round >= since and r.winning_team in (1, 2):
            m = manual[r.nickname]
            m[0] += 1; m[1] += r.team == r.winning_team; m[2] += r.team != r.winning_team; m[3] += r.kills; m[4] += r.deaths
    assert {n: [w.games, w.wins, w.losses, w.kills, w.deaths] for n, w in win.items()} == {n: list(v) for n, v in manual.items()}
    now = engine.compute(rows, LEGACY).players
    before = engine.compute([r for r in rows if r.round < since], LEGACY).players
    for n, w in win.items():
        assert w.elo == now[n].elo and w.total == now[n].total
        assert w.elo_before == (before[n].elo if n in before else 1500), n
    assert len(win) == 23  # 기준 데이터의 마지막 6라운드에 참여한 선수
    # 같은 계산이 CLI에서도 되는지
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "stats.py"), "--source", BASELINE_SOURCE, "--since", str(since), "all"],
                       capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    assert r.returncode == 0 and "구간 기록" in r.stdout and "dELO" in r.stdout and "Nickname" in r.stdout, r.stderr
    bad = subprocess.run([sys.executable, os.path.join(ROOT, "stats.py"), "--source", BASELINE_SOURCE, "--since", "9999", "all"],
                         capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    assert bad.returncode == 1


def test_stops_on_corrupt_source():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "m.csv")
        open(p, "w", encoding="utf-8-sig").write("Round,Nickname,Team,Kills,Deaths,Winning Team\n1,a,1,x,2,1\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert stats.load_players(p) is None
        assert "오류" in buf.getvalue()


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
