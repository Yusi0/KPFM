"""유저 통계 조회. 항상 원본(data/source/matches.csv)에서 바로 계산하므로 최신이다.

    python stats.py gukbab2 Axaeny          띄어쓰기로 구분
    python stats.py gukbab2,Axaeny          쉼표로 구분
    python stats.py "gukbab2, Axaeny" sy5254  쉼표+공백, 섞어 써도 됨
    python stats.py all                     전체 (ELO 순)
    python stats.py                         닉네임을 물어봄
    python stats.py all --since 93          93라운드 이후 기록만 따로 집계 (구간 통계)
"""
import argparse
import difflib
import os
import re
import sys
from dataclasses import dataclass

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(HERE, "data", "source", "matches.csv")
HEADERS = ["Nickname", "K", "D", "KDR", "W", "L", "WR%", "KPR", "ELO", "Tier"]
PLACEMENT_GAMES = 5  # 이 경기 수 이하는 티어를 Unranked로 표시 (배치 기간)
WINDOW_HEADERS = ["Nickname", "G", "W", "L", "K", "D", "KDR", "WR%", "KPR", "ELO", "dELO", "Total"]


def parse_names(text):
    """공백, 쉼표, 쉼표+공백(전각 쉼표 포함)을 모두 구분자로 본다. 중복은 처음 한 번만 남긴다."""
    seen, names = set(), []
    for token in re.split(r"[,\s，]+", text or ""):
        if token and token.lower() not in seen:
            seen.add(token.lower())
            names.append(token)
    return names


def _lookalike(name):
    return name.lower().replace("i", "l").replace("1", "l").replace("0", "o")


def resolve(names, players):
    """입력 닉네임을 실제 선수와 맞춘다 (대소문자 무시). 반환: (찾은 선수 목록, {못 찾은 입력: [비슷한 닉네임]})"""
    if any(n.lower() == "all" for n in names):
        return list(players.values()), {}
    by_lower = {}
    for p in players.values():
        by_lower.setdefault(p.nickname.lower(), []).append(p)
    found, missing, picked = [], {}, set()
    for n in names:
        candidates = by_lower.get(n.lower())
        if candidates:
            exact = [p for p in candidates if p.nickname == n]
            for p in (exact or candidates):
                if p.nickname not in picked:
                    picked.add(p.nickname)
                    found.append(p)
        else:
            close = difflib.get_close_matches(n.lower(), list(by_lower), n=3, cutoff=0.6)
            close += [p.nickname.lower() for p in players.values()
                      if _lookalike(p.nickname) == _lookalike(n) and p.nickname.lower() not in close]
            missing[n] = [by_lower[c][0].nickname for c in close[:3]]
    return found, missing


def stat_row(p):
    """한 선수의 표시용 행. 계산 규칙은 예전 elo.py의 display_user_statistics와 같다."""
    kdr = round(p.kills / max(1, p.deaths), 2)
    win_rate = round(p.wins / max(1, p.total) * 100, 1) if p.total > 0 else 0.0
    kpr = round(p.kills / max(1, p.total), 1) if p.total > 0 else 0.0
    tier = p.tier if p.total > PLACEMENT_GAMES else "Unranked"
    return [p.nickname, p.kills, p.deaths, kdr, p.wins, p.losses, win_rate, kpr, p.elo, tier]


def sort_players(players):
    return sorted(players, key=lambda p: (-p.elo, -p.total, p.nickname))


def render(rows, headers=None):
    headers = headers or HEADERS
    try:
        from tabulate import tabulate
        return tabulate(rows, headers=headers, tablefmt="pretty")
    except ImportError:  # tabulate가 없어도 동작
        widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
        line = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths))
        return "\n".join([line(headers), *(line(r) for r in rows)])


def load_rows(source):
    """검증을 통과한 원본 행을 돌려준다. 오류가 있으면 안내하고 None."""
    rows, issues = engine.load_matches(source)
    if not any(i.level == "error" for i in issues):
        engine.fill_round_meta(rows)
        issues += engine.validate(rows)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        for i in errors:
            print(f"오류 - {'라운드 ' + str(i.round) + ': ' if i.round is not None else ''}{i.message}")
        print("⛔ 원본에 오류가 있어 통계를 계산하지 않았습니다. python build.py --check 로 확인하세요.")
        return None
    return rows


@dataclass
class WindowStat:
    """지정한 라운드 이후만 집계한 한 선수의 기록. ELO는 전체 기록 기준의 현재 값이고, dELO는 구간 시작 전 대비 변화."""
    nickname: str
    games: int = 0
    wins: int = 0
    losses: int = 0
    kills: int = 0
    deaths: int = 0
    elo: int = 1500
    elo_before: int = 1500
    total: int = 0   # 전체 경기 수 (적을수록 아직 배치 구간이라 ELO가 불안정)


def window_stats(rows, since, ruleset=None):
    """since 라운드 이후(포함) 기록만 선수별로 집계한다. 승리 팀이 0인 라운드(무승부/취소)는 제외."""
    now = engine.compute(rows, ruleset).players
    before = engine.compute([r for r in rows if r.round < since], ruleset).players
    stats = {}
    for r in rows:
        if r.round < since or r.winning_team not in (1, 2):
            continue
        w = stats.setdefault(r.nickname, WindowStat(r.nickname, elo=now[r.nickname].elo, total=now[r.nickname].total,
                                                    elo_before=before[r.nickname].elo if r.nickname in before else engine.START_ELO))
        w.games += 1
        w.wins += 1 if r.team == r.winning_team else 0
        w.losses += 0 if r.team == r.winning_team else 1
        w.kills += r.kills
        w.deaths += r.deaths
    return stats


def window_row(w):
    kdr = round(w.kills / max(1, w.deaths), 2)
    win_rate = round(w.wins / max(1, w.games) * 100, 1)
    kpr = round(w.kills / max(1, w.games), 1)
    return [w.nickname, w.games, w.wins, w.losses, w.kills, w.deaths, kdr, win_rate, kpr, w.elo, w.elo - w.elo_before, w.total]


def load_players(source, ruleset=None):
    rows = load_rows(source)
    if rows is None:
        return None
    return engine.compute(rows, ruleset).players


def main(argv=None):
    ap = argparse.ArgumentParser(description="유저 통계 조회 (닉네임은 공백/쉼표/쉼표+공백으로 구분, 'all'은 전체)")
    ap.add_argument("names", nargs="*", help="닉네임들")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="원본 CSV (기본: data/source/matches.csv)")
    ap.add_argument("--since", type=int, metavar="라운드", help="이 라운드 이후(포함) 기록만 집계 (구간 통계)")
    args = ap.parse_args(argv)

    text = " ".join(args.names)
    if not text.strip():
        text = input(">> 통계를 확인할 닉네임(공백 또는 쉼표로 구분, 전부 보려면 'all'): ")
    names = parse_names(text)
    if not names:
        print("⚠ 닉네임을 입력해주세요.")
        return 1

    if args.since is not None:
        rows = load_rows(args.source)
        if rows is None:
            return 1
        players = window_stats(rows, args.since)
        if not players:
            print(f"⚠ {args.since}라운드 이후 기록이 없습니다.")
            return 1
        found, missing = resolve(names, players)
        for n, close in missing.items():
            hint = f" (혹시: {', '.join(close)})" if close else ""
            print(f"⚠ '{n}'은(는) {args.since}라운드 이후 기록이 없습니다.{hint}")
        if not found:
            return 1
        found.sort(key=lambda w: (-w.elo, w.nickname))
        print(f"[{args.since}라운드 이후 구간 기록] G=구간 경기수, ELO=현재 전체 ELO, dELO=구간 시작 전 대비 변화, Total=전체 경기수")
        print(render([window_row(w) for w in found], WINDOW_HEADERS))
        return 0 if not missing else 2

    players = load_players(args.source)
    if players is None:
        return 1
    found, missing = resolve(names, players)
    for n, close in missing.items():
        hint = f" (혹시: {', '.join(close)})" if close else ""
        print(f"⚠ '{n}'을(를) 찾을 수 없습니다.{hint}")
    if not found:
        return 1
    print(render([stat_row(p) for p in sort_players(found)]))
    return 0 if not missing else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
