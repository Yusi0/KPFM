"""원본(data/source/matches.csv)에서 웹용 CSV를 만든다.

    python build.py                 검증 후 out/ 폴더에 lboard.csv, match.csv, aftercalc.csv 생성 (웹에는 영향 없음)
    python build.py --check         검증만 한다 (파일을 만들지 않음)
    python build.py --publish       웹이 읽는 이 폴더의 lboard.csv, match.csv, aftercalc.csv를 갱신
    python build.py --write-db X.db 기존 elo.py 분석 메뉴용 sqlite를 새로 만든다 (이미 있으면 --force 필요)
"""
import argparse
import csv
import os
import sqlite3
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


def write_db(path, rows, result):
    """기존 elo.py 분석 메뉴(통계, 차트, 팀 밸런스 등)가 읽는 sqlite를 새로 만든다. 원본에서 언제든 재생성 가능한 산출물이다."""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript('''
    CREATE TABLE leaderboard (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nickname TEXT UNIQUE, kills INTEGER DEFAULT 0, deaths INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, total INTEGER DEFAULT 0, elo INTEGER DEFAULT 1500, tier TEXT DEFAULT 'Unranked');
    CREATE TABLE matches (
        match_id INTEGER PRIMARY KEY AUTOINCREMENT, round INTEGER, nickname TEXT, team INTEGER, kills INTEGER, deaths INTEGER,
        map TEXT DEFAULT NULL, winning_team INTEGER DEFAULT NULL, mode TEXT DEFAULT NULL, team1_score INTEGER DEFAULT NULL,
        team2_score INTEGER DEFAULT NULL, player_score INTEGER DEFAULT NULL,
        FOREIGN KEY(nickname) REFERENCES leaderboard(nickname) ON DELETE CASCADE ON UPDATE CASCADE, UNIQUE(round, nickname));
    CREATE TABLE aftercalc (
        ac_id INTEGER PRIMARY KEY AUTOINCREMENT, round INTEGER, nickname TEXT, total_kills_at_round INTEGER,
        total_deaths_at_round INTEGER, kdr_at_round REAL, elo_after_round INTEGER,
        FOREIGN KEY(nickname) REFERENCES leaderboard(nickname) ON DELETE CASCADE ON UPDATE CASCADE, UNIQUE (round, nickname));
    ''')
    first_seen = []
    for r in sorted(rows, key=lambda r: (r.round, r.team, r.nickname)):
        if r.nickname not in first_seen:
            first_seen.append(r.nickname)
    for n in first_seen:
        p = result.players[n]
        cur.execute("INSERT INTO leaderboard (nickname, kills, deaths, wins, losses, total, elo, tier) VALUES (?,?,?,?,?,?,?,?)",
                    (n, p.kills, p.deaths, p.wins, p.losses, p.total, p.elo, p.tier))
    for r in sorted(rows, key=lambda r: (r.round, r.team, r.nickname)):
        cur.execute("INSERT INTO matches (round, nickname, team, kills, deaths, map, winning_team, mode, team1_score, team2_score, player_score)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (r.round, r.nickname, r.team, r.kills, r.deaths, r.map, r.winning_team, r.mode, r.team1_score, r.team2_score, r.player_score))
    for h in sorted(result.history, key=lambda x: (x[0], x[1])):
        cur.execute("INSERT INTO aftercalc (round, nickname, total_kills_at_round, total_deaths_at_round, kdr_at_round, elo_after_round)"
                    " VALUES (?,?,?,?,?,?)", h)
    con.commit()
    con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="원본 matches.csv에서 웹용 CSV를 만든다")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="원본 CSV (기본: data/source/matches.csv)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="결과 폴더 (기본: out/)")
    ap.add_argument("--check", action="store_true", help="검증만 하고 파일은 만들지 않음")
    ap.add_argument("--publish", action="store_true", help="웹이 읽는 이 폴더의 CSV 3개를 갱신")
    ap.add_argument("--strict", action="store_true", help="경고도 오류로 취급")
    ap.add_argument("--write-db", metavar="PATH", help="elo.py 분석 메뉴용 sqlite 생성")
    ap.add_argument("--force", action="store_true", help="--write-db 대상 파일이 있어도 덮어씀")
    args = ap.parse_args(argv)

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

    target_dir = HERE if args.publish else args.out
    print_diff(read_previous_elos(os.path.join(target_dir, "lboard.csv")), result,
               "현재 웹용 lboard.csv" if args.publish else "이전 결과")
    write_web_csvs(target_dir, rows, result)
    print(f"\n✅ {', '.join(WEB_FILES)} 생성: {target_dir}")

    if args.write_db:
        if os.path.exists(args.write_db) and not args.force:
            print(f"⚠ {args.write_db}가 이미 있습니다. 덮어쓰려면 --force를 쓰세요.")
            return 1
        if os.path.exists(args.write_db):
            os.remove(args.write_db)
        os.makedirs(os.path.dirname(os.path.abspath(args.write_db)), exist_ok=True)
        write_db(args.write_db, rows, result)
        print(f"✅ sqlite 생성: {args.write_db}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
