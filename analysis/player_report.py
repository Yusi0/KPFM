"""한 선수의 ELO가 어떻게 쌓였는지 기존 공식과 현재 공식으로 나란히 본다.

    python analysis/player_report.py sy5254 [원본.csv]

① 기본 기록 ② 경기 수에 따른 ELO 궤적(두 공식) ③ ELO가 오른 이유(승패 점수 합 / 성과 점수 합)
④ 시기별 실력(성장했는가) ⑤ 경기를 많이 한 선수들과의 비교 (ELO가 실력인지 경기 수인지)
"""
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import engine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 2:
    sys.exit("사용법: python analysis/player_report.py 닉네임 [원본.csv]")
NICK = sys.argv[1]
SOURCE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "source", "matches.csv")
rows = engine.fill_round_meta(engine.load_matches(SOURCE)[0])
by_round = collections.defaultdict(list)
for r in rows:
    if r.winning_team in (1, 2):
        by_round[r.round].append(r)
if NICK not in {r.nickname for r in rows}:
    sys.exit(f"'{NICK}' 기록이 없습니다.")

SYSTEMS = {"기존 공식": [(1, engine.legacy_v1)], "현재 공식": engine.RULESET}
RAW = lambda r: 0.2 * r.kills - 0.07 * r.deaths


def replay(ruleset):
    """공식 하나로 전체를 계산하고, 대상 선수의 경기별 상세(라운드, 직전 ELO, 직후 ELO, 승패 점수, 성과 점수)를 돌려준다."""
    res = engine.compute(rows, ruleset)
    hist = collections.defaultdict(dict)
    for rnd, nick, *_x, elo in res.history:
        hist[rnd][nick] = elo
    last, games, detail = {}, collections.Counter(), []
    legacy = ruleset[0][1] is engine.legacy_v1
    for rnd in sorted(by_round):
        g = by_round[rnd]
        pre = {r.nickname: last.get(r.nickname, 1500) for r in g}
        avg = {t: np.mean([pre[r.nickname] for r in g if r.team == t]) for t in (1, 2)}
        mean_raw = np.mean([RAW(r) for r in g])
        for r in g:
            if r.nickname == NICK:
                win = r.team == r.winning_team
                n = games[NICK]
                K = engine.k_factor(n)
                if legacy:
                    E = 1 / (1 + 10 ** ((avg[3 - r.team] - pre[NICK]) / 200))
                    outcome = K * (1 if win else -1) * (1.5 - E)
                    perf = RAW(r) * (1 if win else 0.5)
                else:
                    E = 1 / (1 + 10 ** ((avg[3 - r.team] - avg[r.team]) / 400))
                    outcome = K * engine.V2_K_MULTIPLIER * ((1 if win else 0) - E)
                    perf = (RAW(r) - mean_raw) * engine.V2_PERF_WEIGHT
                detail.append(dict(round=rnd, win=win, kills=r.kills, deaths=r.deaths, pre=pre[NICK], post=hist[rnd][NICK],
                                   outcome=outcome, perf=perf, rel=RAW(r) - mean_raw, n=n + 1, mode=r.mode))
        for r in g:
            last[r.nickname] = hist[rnd][r.nickname]
            games[r.nickname] += 1
    return res, detail


results = {name: replay(rs) for name, rs in SYSTEMS.items()}
old_res, old_d = results["기존 공식"]
new_res, new_d = results["현재 공식"]
d = new_d
W = sum(x["win"] for x in d); G = len(d)
K_ = sum(x["kills"] for x in d); D_ = sum(x["deaths"] for x in d)
rank_games = sorted(((p.total, n) for n, p in new_res.players.items()), reverse=True)
print(f"{NICK}: {G}경기 ({W}승 {G - W}패, 승률 {W / G:.0%}), K/D {K_}/{D_} = {K_ / max(1, D_):.2f}, 경기 수 {[n for _, n in rank_games].index(NICK) + 1}위/{len(rank_games)}명")
print(f"  기존 공식 최종 ELO {old_res.players[NICK].elo}  →  현재 공식 최종 ELO {new_res.players[NICK].elo}  ({new_res.players[NICK].elo - old_res.players[NICK].elo:+d})")

print("\n② ELO 궤적 (경기 수별)")
print(f"  {'경기':>4s} {'라운드':>5s} {'기존 ELO':>8s} {'현재 ELO':>8s}")
marks = sorted({1, 5, 10, 20, 30, 40, 50, 60, 70, G})
for m in marks:
    if m <= G:
        print(f"  {m:4d} {old_d[m - 1]['round']:5d} {old_d[m - 1]['post']:8d} {new_d[m - 1]['post']:8d}")

print("\n③ ELO가 오른 이유: 경기마다 더해진 점수의 합")
for name, dd in (("기존 공식", old_d), ("현재 공식", new_d)):
    o, p = sum(x["outcome"] for x in dd), sum(x["perf"] for x in dd)
    print(f"  {name}: 승패 점수 합 {o:+7.0f} (경기당 {o / G:+.1f}) + 성과 점수 합 {p:+7.0f} (경기당 {p / G:+.1f}) = {o + p:+.0f}   (시작 1500 → {dd[-1]['post']})")
pos = sum(1 for x in old_d if x["perf"] > 0)
print(f"  기존 공식의 성과 점수는 승패와 관계없이 킬을 올리면 항상 +입니다. 이 선수는 {G}경기 중 {pos}경기에서 +였고 평균 {np.mean([x['perf'] for x in old_d]):+.1f}점이었습니다.")
print(f"  현재 공식은 그 라운드 평균을 빼므로 '남들보다 잘한 만큼'만 반영됩니다. 이 선수의 라운드 평균 대비 성과는 경기당 {np.mean([x['rel'] for x in new_d]):+.2f} (킬 0.2점 단위 보정 전 값)")

print("\n④ 시기별 실력 (성장했는가): 10경기씩 묶음")
print(f"  {'구간':>9s} {'승-패':>6s} {'승률':>5s} {'K/D':>5s} {'킬/경기':>6s} {'라운드평균대비':>9s}")
for s in range(0, G, 10):
    c = d[s:s + 10]
    w = sum(x["win"] for x in c); k = sum(x["kills"] for x in c); dth = sum(x["deaths"] for x in c)
    print(f"  {s + 1:3d}~{s + len(c):<4d} {w:2d}-{len(c) - w:<3d} {w / len(c):5.0%} {k / max(1, dth):5.2f} {k / len(c):6.1f} {np.mean([x['rel'] for x in c]):+9.2f}")
half = G // 2
print(f"  전반 {half}경기 K/D {sum(x['kills'] for x in d[:half]) / max(1, sum(x['deaths'] for x in d[:half])):.2f}, 승률 {np.mean([x['win'] for x in d[:half]]):.0%}"
      f"  →  후반 {G - half}경기 K/D {sum(x['kills'] for x in d[half:]) / max(1, sum(x['deaths'] for x in d[half:])):.2f}, 승률 {np.mean([x['win'] for x in d[half:]]):.0%}")

print("\n⑤ 경기를 많이 한 선수 비교 (20경기 이상)")
games_all = {n: p.total for n, p in new_res.players.items()}
perf_all = collections.defaultdict(list)
wins = collections.Counter()
kd = collections.defaultdict(lambda: [0, 0])
for rnd, g in by_round.items():
    m = np.mean([RAW(r) for r in g])
    for r in g:
        perf_all[r.nickname].append(RAW(r) - m)
        wins[r.nickname] += r.team == r.winning_team
        kd[r.nickname][0] += r.kills; kd[r.nickname][1] += r.deaths
pool = sorted([n for n, t in games_all.items() if t >= 20], key=lambda n: -old_res.players[n].elo)
print(f"  {'선수':20s} {'경기':>4s} {'승률':>5s} {'K/D':>5s} {'성과/경기':>8s} {'기존ELO':>7s} {'현재ELO':>7s}")
for n in pool:
    mark = "  ◀" if n == NICK else ""
    print(f"  {n:20s} {games_all[n]:4d} {wins[n] / games_all[n]:5.0%} {kd[n][0] / max(1, kd[n][1]):5.2f} {np.mean(perf_all[n]):+8.2f} {old_res.players[n].elo:7d} {new_res.players[n].elo:7d}{mark}")

def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return np.corrcoef(ra, rb)[0, 1]
ranked = [n for n, t in games_all.items() if t >= 6]
gm = [games_all[n] for n in ranked]
pf = [np.mean(perf_all[n]) for n in ranked]
print(f"\n  랭킹 대상 {len(ranked)}명에서 ELO와의 순위상관:")
print(f"    경기 수와   기존 {spearman([old_res.players[n].elo for n in ranked], gm):+.2f} / 현재 {spearman([new_res.players[n].elo for n in ranked], gm):+.2f}")
print(f"    성과/경기와 기존 {spearman([old_res.players[n].elo for n in ranked], pf):+.2f} / 현재 {spearman([new_res.players[n].elo for n in ranked], pf):+.2f}")
