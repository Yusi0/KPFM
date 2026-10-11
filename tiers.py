"""내전용 밸런스/무기 제한 티어표 초안을 만든다. 공식 ELO/랭킹과는 별개의 운영용 임시 자료이다.

    python tiers.py --since 93                          초안을 화면에 표시
    python tiers.py --since 93 --out data/tiers/naejeon_tiers.csv   CSV로 저장 (이미 있으면 --force 필요, 사람이 고친 내용 보호)

기준 (설명 가능하게 단순하게 고정)
- 구간(--since 이후) 기록에 나온 선수만 대상.
- 종합 순위 = (현재 ELO 순위 + 구간 성과 순위) / 2.   ELO는 승패와 누적 기록, 성과는 라운드 평균 대비 킬/데스(0.2*킬 - 0.07*데스)의 경기당 평균.
- 티어는 종합 순위를 13% / 22% / 30% / 22% / 13% 비율로 자른다 (T1이 최상위, 제한이 가장 엄격).
- 전체 5경기 이하이거나, 구간 경기가 2 이하이면서 전체도 10경기 미만이면 "임시". ELO 순위와 성과 순위가 크게 어긋나면 "확인필요".
- 이 결과는 출발점이다. 사람이 보고 Tier 열을 직접 고치는 것을 전제로 한다.
"""
import argparse
import collections
import csv
import os
import sys

import engine
import stats

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(HERE, "data", "source", "matches.csv")
TIER_SHARES = [0.13, 0.22, 0.30, 0.22, 0.13]
PROVISIONAL_TOTAL = 5      # 전체 이 경기 수 이하는 아직 배치 구간
PROVISIONAL_WINDOW = 2     # 구간 경기수가 이 이하이고
ESTABLISHED_TOTAL = 10     # 전체 경기수도 이 미만이면 표본 부족 (오래 뛴 선수는 구간 경기가 적어도 근거가 충분함)
MISMATCH_FRACTION = 0.33   # 두 순위가 이 비율(대상 인원 대비) 이상 벌어지면 확인필요
HEADERS = ["Tier", "Nickname", "Status", "Flag", "Games", "Total", "W", "L", "K", "D", "KDR",
           "PerfPerGame", "ELO", "EloRank", "PerfRank", "Composite", "Note"]


def tier_sizes(count, shares=TIER_SHARES):
    """인원을 비율대로 나눈 티어별 인원수 (합이 인원과 같고, 큰 소수부터 올림)."""
    raw = [count * s for s in shares]
    sizes = [int(x) for x in raw]
    order = sorted(range(len(shares)), key=lambda i: -(raw[i] - sizes[i]))
    for i in order[: count - sum(sizes)]:
        sizes[i] += 1
    return sizes


def window_performance(rows, since):
    """선수별 '라운드 평균 대비 성과'의 경기당 평균. rule_v2의 성과항과 같은 정의."""
    by_round = collections.defaultdict(list)
    for r in rows:
        if r.round >= since and r.winning_team in (1, 2):
            by_round[r.round].append(r)
    perf = collections.defaultdict(list)
    for group in by_round.values():
        raw = lambda r: 0.2 * r.kills - 0.07 * r.deaths
        mean = sum(raw(r) for r in group) / len(group)
        for r in group:
            perf[r.nickname].append(raw(r) - mean)
    return {n: sum(v) / len(v) for n, v in perf.items()}


def build_tiers(rows, since, ruleset=None):
    window = stats.window_stats(rows, since, ruleset)
    if not window:
        return []
    perf = window_performance(rows, since)
    kdr = {n: w.kills / max(1, w.deaths) for n, w in window.items()}
    # 동점은 K/D, 닉네임 순으로 풀어 결과가 항상 같게 한다
    elo_rank = {n: i + 1 for i, n in enumerate(sorted(window, key=lambda n: (-window[n].elo, -kdr[n], n)))}
    perf_rank = {n: i + 1 for i, n in enumerate(sorted(window, key=lambda n: (-perf[n], -kdr[n], n)))}
    composite = {n: (elo_rank[n] + perf_rank[n]) / 2 for n in window}
    order = sorted(window, key=lambda n: (composite[n], elo_rank[n], n))
    sizes = tier_sizes(len(order))
    tier_of, i = {}, 0
    for t, size in enumerate(sizes, start=1):
        for n in order[i:i + size]:
            tier_of[n] = t
        i += size

    gap_limit = MISMATCH_FRACTION * len(order)
    result = []
    for n in order:
        w = window[n]
        provisional = w.total <= PROVISIONAL_TOTAL or (w.games <= PROVISIONAL_WINDOW and w.total < ESTABLISHED_TOTAL)
        mismatch = abs(elo_rank[n] - perf_rank[n]) >= gap_limit
        result.append({
            "Tier": tier_of[n], "Nickname": n,
            "Status": "임시" if provisional else "확정후보",
            "Flag": "확인필요(ELO와 성과 순위 차이 큼)" if mismatch else "",
            "Games": w.games, "Total": w.total, "W": w.wins, "L": w.losses, "K": w.kills, "D": w.deaths,
            "KDR": round(kdr[n], 2), "PerfPerGame": round(perf[n], 2), "ELO": w.elo,
            "EloRank": elo_rank[n], "PerfRank": perf_rank[n], "Composite": composite[n], "Note": "",
        })
    return result


def write_csv(path, table, force=False):
    if os.path.exists(path) and not force:
        print(f"⚠ {path}가 이미 있습니다. 사람이 고친 내용을 지킬 수 있도록 덮어쓰지 않았습니다. (덮어쓰려면 --force)")
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(table)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="내전 티어표 초안 (공식 ELO와 별개의 운영용 자료)")
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--since", type=int, required=True, metavar="라운드", help="이 라운드 이후(포함) 기록에 나온 선수만 대상")
    ap.add_argument("--out", help="CSV로 저장할 경로")
    ap.add_argument("--force", action="store_true", help="--out 파일이 있어도 덮어씀")
    args = ap.parse_args(argv)

    rows = stats.load_rows(args.source)
    if rows is None:
        return 1
    table = build_tiers(rows, args.since)
    if not table:
        print(f"⚠ {args.since}라운드 이후 기록이 없습니다.")
        return 1
    sizes = tier_sizes(len(table))
    print(f"[내전 티어 초안] {args.since}라운드 이후 {len(table)}명, 티어별 인원 {sizes} (T1 = 최상위, 제한 가장 엄격)")
    cur = None
    for r in table:
        if r["Tier"] != cur:
            cur = r["Tier"]
            print(f"\n  T{cur}")
        mark = "  [임시]" if r["Status"] == "임시" else ""
        mark += "  [확인필요]" if r["Flag"] else ""
        print(f"    {r['Nickname']:22s} {r['Games']}/{r['Total']}경기 KDR {r['KDR']:.2f}  성과 {r['PerfPerGame']:+.2f}  ELO {r['ELO']}{mark}")
    if args.out:
        if write_csv(args.out, table, args.force):
            print(f"\n✅ 저장: {args.out}  (Tier 열을 직접 고쳐서 쓰세요)")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
