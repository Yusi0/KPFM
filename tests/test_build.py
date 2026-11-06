"""build.py의 안전한 파일 쓰기 검증. 실행: python tests/test_build.py

엑셀이나 OneDrive 동기화가 파일을 잡고 있을 때 웹용 CSV 3개가 서로 안 맞는 상태로 남지 않는지 확인한다.
"""
import os
import stat
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import build  # noqa: E402


def _make(tmp, **files):
    paths = {}
    for name, text in files.items():
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        paths[name] = p
    return paths


def _read(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return f.read()


def test_writes_all_files():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = os.path.join(tmp, "a.csv"), os.path.join(tmp, "b.csv")
        build.write_all_or_nothing({a: "x\r\n1\r\n", b: "y\r\n2\r\n"}, retries=1, wait=0)
        assert _read(a) == "x\r\n1\r\n" and _read(b) == "y\r\n2\r\n"
        # 한글과 줄바꿈이 그대로 (BOM 포함 UTF-8, \r\n 유지)
        raw = open(a, "rb").read()
        assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw


def test_locked_file_changes_nothing():
    """하나라도 잠겨 있으면 다른 파일도 쓰지 않고 FileLockedError."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _make(tmp, **{"lboard.csv": "old-l", "match.csv": "old-m", "aftercalc.csv": "old-a"})
        os.chmod(p["match.csv"], stat.S_IREAD)       # 다른 프로그램이 잡고 있는 것과 같은 효과 (쓰기 거부)
        try:
            try:
                build.write_all_or_nothing({p["lboard.csv"]: "new-l", p["match.csv"]: "new-m", p["aftercalc.csv"]: "new-a"}, retries=2, wait=0)
                assert False, "FileLockedError가 나야 함"
            except build.FileLockedError as e:
                assert "match.csv" in str(e) and "lboard.csv" not in str(e)
            assert _read(p["lboard.csv"]) == "old-l" and _read(p["match.csv"]) == "old-m" and _read(p["aftercalc.csv"]) == "old-a"
        finally:
            os.chmod(p["match.csv"], stat.S_IWRITE | stat.S_IREAD)


def test_failure_in_the_middle_is_rolled_back():
    """사전 확인을 통과한 뒤 쓰는 도중 실패해도 이미 쓴 파일을 원래대로 되돌린다 (새로 만든 파일은 지움)."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _make(tmp, **{"one.csv": "old-1", "two.csv": "old-2"})
        three = os.path.join(tmp, "three.csv")      # 아직 없는 파일
        real = build._write_text
        calls = []

        def flaky(path, text):
            calls.append(path)
            if len(calls) == 3:
                raise OSError("쓰는 도중 실패")
            real(path, text)

        build._write_text = flaky
        try:
            try:
                build.write_all_or_nothing({p["one.csv"]: "new-1", p["two.csv"]: "new-2", three: "new-3"}, retries=1, wait=0)
                assert False, "예외가 그대로 올라와야 함"
            except OSError as e:
                assert "쓰는 도중" in str(e)
        finally:
            build._write_text = real
        assert _read(p["one.csv"]) == "old-1" and _read(p["two.csv"]) == "old-2"
        assert not os.path.exists(three)


def test_main_does_not_commit_or_push_when_locked():
    """--push에서 파일이 잠겨 있으면 안내만 하고 git 작업은 하지 않는다."""
    called = []
    real_write, real_git = build.write_web_csvs, build.git_publish

    def locked(*a, **k):
        raise build.FileLockedError("다른 프로그램이 사용 중이라 쓸 수 없습니다: match.csv")

    build.write_web_csvs = locked
    build.git_publish = lambda *a, **k: called.append("git") or 0
    try:
        code = build.main(["--push", "--yes"])
    finally:
        build.write_web_csvs, build.git_publish = real_write, real_git
    assert code == 1 and not called


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
