"""원본(data/source/matches.csv)에서 웹용 CSV를 만든다.

    python build.py                 검증 후 out/ 폴더에 lboard.csv, match.csv, aftercalc.csv 생성 (웹에는 영향 없음)
    python build.py --check         검증만 한다 (파일을 만들지 않음)
    python build.py --publish       웹이 읽는 이 폴더의 lboard.csv, match.csv, aftercalc.csv를 갱신
    python build.py --push          --publish 후 변경 내용을 확인받고 git add/commit/push까지 한다
"""
import argparse
import csv
import os
import subprocess
import sys

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(HERE, "data", "source", "matches.csv")
DEFAULT_OUT = os.path.join(HERE, "out")
WEB_FILES = ("lboard.csv", "match.csv", "aftercalc.csv")


def _cell(v):
    return "" if v is None else v


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def leaderboard_rows(result):
    ordered = sorted(result.players.values(), key=lambda p: (-p.elo, -p.total, p.nickname))
    return [(i, p.nickname, p.kills, p.deaths, p.wins, p.losses, p.total, p.elo, p.tier)
            for i, p in enumerate(ordered, start=1)]


def match_rows(rows):
    ordered = sorted(rows, key=lambda r: (r.round, r.team, r.nickname))
    return [(r.round, r.nickname, r.team, r.kills, r.deaths, r.winning_team, _cell(r.map), _cell(r.mode),
             _cell(r.team1_score), _cell(r.team2_score), _cell(r.player_score)) for r in ordered]


def aftercalc_rows(result):
    return sorted(((rnd, nick, elo) for rnd, nick, _k, _d, _kdr, elo in result.history), key=lambda x: (x[0], x[1]))


def write_web_csvs(directory, rows, result):
    os.makedirs(directory, exist_ok=True)
    _write_csv(os.path.join(directory, "lboard.csv"),
               ["Rank", "Nickname", "Kills", "Deaths", "Wins", "Losses", "Total", "ELO", "Tier"], leaderboard_rows(result))
    _write_csv(os.path.join(directory, "match.csv"),
               ["Round", "Nickname", "Team", "Kills", "Deaths", "Winning Team", "Map", "Mode",
                "Team1 Score", "Team2 Score", "Player Score"], match_rows(rows))
    _write_csv(os.path.join(directory, "aftercalc.csv"), ["Round", "Nickname", "ELO"], aftercalc_rows(result))


def read_previous_elos(path):
    """이전 lboard.csv에서 {닉네임: (ELO, 경기 수)}를 읽는다. 없으면 빈 dict."""
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {r["Nickname"]: (int(r["ELO"]), int(r["Total"])) for r in csv.DictReader(f)}


def print_diff(previous, result, label):
    if not previous:
        print(f"(비교할 {label}이 없습니다)")
        return
    now = {n: (p.elo, p.total) for n, p in result.players.items()}
    added = sorted(set(now) - set(previous))
    removed = sorted(set(previous) - set(now))
    changed = sorted(((n, previous[n][0], now[n][0]) for n in now if n in previous and previous[n][0] != now[n][0]),
                     key=lambda x: -abs(x[2] - x[1]))
    print(f"\n[{label} 대비] ELO 변경 {len(changed)}명, 새 선수 {len(added)}명, 사라진 선수 {len(removed)}명")
    for n, a, b in changed[:30]:
        print(f"  {n:24s} {a:5d} -> {b:5d} ({b - a:+d})")
    if len(changed) > 30:
        print(f"  ... 외 {len(changed) - 30}명")
    if added: print("  새 선수:", ", ".join(added[:20]))
    if removed: print("  사라진 선수:", ", ".join(removed[:20]))


GIT_PATHS = ["data/source/matches.csv", *WEB_FILES]


def _git(*args):
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")


def git_publish(message, assume_yes):
    """원본 + 웹용 CSV 3개만 커밋하고 푸시한다. 다른 파일은 건드리지 않는다. 반환: 종료 코드."""
    try:
        status = _git("status", "--porcelain", "--", *GIT_PATHS)
    except FileNotFoundError:
        print("⚠ 'git' 명령어를 찾을 수 없습니다. Git이 설치되어 있는지 확인해주세요.")
        return 1
    if status.returncode != 0:
        print(f"⚠ git 상태를 확인하지 못했습니다: {status.stderr.strip()}")
        return 1
    changed = [line for line in status.stdout.splitlines() if line.strip()]
    if not changed:
        print("\nℹ️ 원본과 웹용 CSV에 변경이 없어 커밋할 내용이 없습니다. 푸시하지 않았습니다.")
        return 0
    print("\n변경된 파일:")
    for line in changed:
        print("  ", line)
    if not assume_yes and input(f"\n>> 커밋 메시지 '{message}'로 커밋하고 푸시할까요? [y/n]: ").strip().lower() != "y":
        print("⛔ 푸시하지 않았습니다. (CSV는 이미 갱신되어 있습니다)")
        return 0

    for step in (["add", "--", *GIT_PATHS], ["commit", "-m", message, "--", *GIT_PATHS]):
        r = _git(*step)
        if r.returncode != 0:
            print(f"⚠ git {step[0]} 실패:\n{(r.stdout + r.stderr).strip()}")
            return 1
    print("✅ 커밋 완료")
    r = _git("push")
    if r.returncode != 0:
        print(f"⚠ 푸시 실패 (커밋은 로컬에 남아 있습니다):\n{r.stderr.strip()}")
        return 1
    print("✅ 푸시 성공! 라이브 사이트에 수 분 내에 반영됩니다.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="원본 matches.csv에서 웹용 CSV를 만든다")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="원본 CSV (기본: data/source/matches.csv)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="결과 폴더 (기본: out/)")
    ap.add_argument("--check", action="store_true", help="검증만 하고 파일은 만들지 않음")
    ap.add_argument("--publish", action="store_true", help="웹이 읽는 이 폴더의 CSV 3개를 갱신")
    ap.add_argument("--push", action="store_true", help="--publish 후 git add/commit/push (확인 후 진행)")
    ap.add_argument("--yes", action="store_true", help="--push 확인 질문 없이 진행")
    ap.add_argument("-m", "--message", help="--push 커밋 메시지 (기본: 자동 생성)")
    ap.add_argument("--strict", action="store_true", help="경고도 오류로 취급")
    args = ap.parse_args(argv)
    if args.push:
        args.publish = True

    rows, issues = engine.load_matches(args.source)
    if not any(i.level == "error" for i in issues):
        engine.fill_round_meta(rows)
        issues += engine.validate(rows)

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    for i in errors + warnings:
        where = f"라운드 {i.round}: " if i.round is not None else ""
        print(f"{'오류' if i.level == 'error' else '경고'} - {where}{i.message}")
    if errors or (args.strict and warnings):
        print(f"\n⛔ 오류 {len(errors)}건, 경고 {len(warnings)}건. 아무 파일도 만들지 않았습니다.")
        return 1

    result = engine.compute(rows)
    rounds = len({r.round for r in rows})
    print(f"\n✅ 검증 통과: {rounds}개 라운드, {len(rows)}행, 선수 {len(result.players)}명"
          f" (경고 {len(warnings)}건, 계산 제외 라운드 {len(result.skipped_rounds)}개 {result.skipped_rounds[:10] or ''})")
    if args.check:
        return 0

    if args.push and os.path.abspath(args.source) != os.path.abspath(DEFAULT_SOURCE):
        print("⚠ --push는 기본 원본(data/source/matches.csv)에서만 쓸 수 있습니다.")
        return 1
    target_dir = HERE if args.publish else args.out
    print_diff(read_previous_elos(os.path.join(target_dir, "lboard.csv")), result,
               "현재 웹용 lboard.csv" if args.publish else "이전 결과")
    write_web_csvs(target_dir, rows, result)
    print(f"\n✅ {', '.join(WEB_FILES)} 생성: {target_dir}")

    if args.push:
        last_round = max(r.round for r in rows)
        return git_publish(args.message or f"data: 리더보드 갱신 (라운드 {last_round}까지)", args.yes)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
