"""내전 티어표 초안 검증. 실행: python tests/test_tiers.py"""
import csv
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import engine  # noqa: E402
import stats  # noqa: E402
import tiers  # noqa: E402

BASELINE_SOURCE = os.path.join(HERE, "baseline", "matches_r103.csv")


def _rows():
    rows, issues = engine.load_matches(BASELINE_SOURCE)
    assert not [i for i in issues if i.level == "error"], issues
    return engine.fill_round_meta(rows)


def test_tier_sizes_sum_and_shape():
    for n in (1, 2, 5, 10, 23, 40, 91):
        sizes = tiers.tier_sizes(n)
        assert sum(sizes) == n and len(sizes) == 5 and all(s >= 0 for s in sizes), (n, sizes)
    assert tiers.tier_sizes(23) == [3, 5, 7, 5, 3]
    assert tiers.tier_sizes(100) == [13, 22, 30, 22, 13]


def test_baseline_last_six_rounds():
    """고정 기준값의 마지막 6라운드(예전 번호 98~103)로 만든 초안의 구조와 확실한 사례."""
    table = tiers.build_tiers(_rows(), 98)
    assert len(table) == 23
    assert [sum(1 for r in table if r["Tier"] == t) for t in range(1, 6)] == [3, 5, 7, 5, 3]
    by = {r["Nickname"]: r for r in table}
    assert by["gukbab2"]["Tier"] == 1, "모든 지표 1위 선수는 T1이어야 함"
    assert by["coldetu"]["Tier"] == 5, "ELO와 성과가 모두 최하위권인 선수는 T5여야 함"
    assert by["gukbab2"]["Status"] == "확정후보", "구간 경기가 2경기여도 전체 60경기라 근거가 충분함"
    assert by["Iluv_phrolova"]["Status"] == "임시" and by["bond0822"]["Status"] == "임시", "구간 2경기 이하이고 전체 10경기 미만이면 임시"
    assert by["Archyaki"]["Status"] == "확정후보"
    # 지표가 크게 엇갈리는 선수는 사람이 확인하도록 표시되어야 한다
    assert "확인필요" in by["Eris_NIx"]["Flag"] and "확인필요" in by["onxzor"]["Flag"]
    assert not by["gukbab2"]["Flag"]
    # 정렬: 티어 번호가 줄어들지 않는 순서
    tiers_in_order = [r["Tier"] for r in table]
    assert tiers_in_order == sorted(tiers_in_order)


def test_deterministic_and_row_order_independent():
    rows = _rows()
    a = tiers.build_tiers(rows, 98)
    b = tiers.build_tiers(list(reversed(rows)), 98)
    assert a == b


def test_window_only_players_included():
    table = tiers.build_tiers(_rows(), 98)
    names = {r["Nickname"] for r in table}
    rows = _rows()
    assert names == {r.nickname for r in rows if r.round >= 98 and r.winning_team in (1, 2)}
    assert tiers.build_tiers(rows, 9999) == []


def test_csv_written_and_protected_from_overwrite():
    table = tiers.build_tiers(_rows(), 98)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "sub", "t.csv")
        assert tiers.write_csv(path, table)
        with open(path, newline="", encoding="utf-8-sig") as f:
            got = list(csv.DictReader(f))
        assert len(got) == 23 and list(got[0].keys()) == tiers.HEADERS
        # 사람이 고친 내용을 지키기 위해 기본은 덮어쓰지 않는다
        open(path, "a", encoding="utf-8").write("# 사람이 고침\n")
        assert not tiers.write_csv(path, table)
        assert "# 사람이 고침" in open(path, encoding="utf-8").read()
        assert tiers.write_csv(path, table, force=True)


def test_cli_smoke():
    import subprocess
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tiers.py"), "--source", BASELINE_SOURCE, "--since", "98"],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0 and "T1" in r.stdout and "gukbab2" in r.stdout and "[임시]" in r.stdout, r.stderr
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tiers.py"), "--source", BASELINE_SOURCE, "--since", "9999"],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 1


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print(f"PASS {name}")
        except Exception:
            failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
