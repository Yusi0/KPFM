"""공식을 바꿨을 때 무엇이 어떻게 달라지는지 보여주는 변경표. 기존 공식(legacy_v1)을 전 구간에 적용한 결과와 현재 기본 규칙(engine.RULESET)을 비교한다.

    python analysis/formula_change_report.py [원본.csv]

출력: ① 평균/표준편차 ② TOP10 변화 ③ 티어 분포 변화 ④ 가장 많이 오른/내린 선수 ⑤ 배치(5경기 이하) 선수 변동 ⑥ 다른 K 배율과의 비교
(랭킹 대상 = 6경기 이상. 5경기 이하는 배치중으로 보고 따로 본다.)
"""
import collections
import functools
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import engine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SOURCE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "source", "matches.csv")
RANKED_MIN = 6   # 6경기부터 정식 랭킹/티어
rows = engine.fill_round_meta(engine.load_matches(SOURCE)[0])
old = engine.compute(rows, [(1, engine.legacy_v1)]).players
new = engine.compute(rows).players
names = sorted(new)
ranked = [n for n in names if new[n].total >= RANKED_MIN]
placement = [n for n in names if new[n].total < RANKED_MIN]


def top(players, pool, k=10):
    return sorted(pool, key=lambda n: (-players[n].elo, n))[:k]


def stat(players, pool):
    v = np.array([players[n].elo for n in pool])
    return f"평균 {v.mean():.0f}, 표준편차 {v.std():.0f}, 범위 {v.min():.0f}~{v.max():.0f}"


print(f"원본: {SOURCE}\n선수 {len(names)}명 (랭킹 대상 {RANKED_MIN}경기 이상 {len(ranked)}명, 배치중 {len(placement)}명), 라운드 {len({r.round for r in rows})}개\n")

print("① 전체 ELO 분포")
print(f"  전체 {len(names)}명        기존: {stat(old, names)}\n                         변경: {stat(new, names)}")
print(f"  랭킹 대상 {len(ranked)}명   기존: {stat(old, ranked)}\n                         변경: {stat(new, ranked)}")

print(f"\n② TOP10 (랭킹 대상 {RANKED_MIN}경기 이상)")
t_old, t_new = top(old, ranked), top(new, ranked)
rank_old = {n: i + 1 for i, n in enumerate(sorted(ranked, key=lambda n: (-old[n].elo, n)))}
print(f"  {'순위':>3s} {'변경 후':22s} {'ELO':>12s} {'기존 순위':>8s}")
for i, n in enumerate(t_new, start=1):
    print(f"  {i:3d} {n:22s} {old[n].elo:5d}→{new[n].elo:<5d} {rank_old[n]:8d}위")
left = [n for n in t_old if n not in t_new]
print(f"  겹침 {len(set(t_old) & set(t_new))}/10. TOP10에서 빠진 선수: " + (", ".join(f"{n}({rank_old[n]}위→{sorted(ranked, key=lambda x: (-new[x].elo, x)).index(n) + 1}위)" for n in left) or "없음"))

print("\n③ 티어 분포 (랭킹 대상)")
order = engine.TIER_NAMES
co, cn = collections.Counter(old[n].tier for n in ranked), collections.Counter(new[n].tier for n in ranked)
print(f"  {'티어':12s} {'기존':>4s} {'변경':>4s}")
for t in reversed(order):
    if co[t] or cn[t]:
        print(f"  {t:12s} {co[t]:4d} {cn[t]:4d}")
moved = [(n, old[n].tier, new[n].tier) for n in ranked if old[n].tier != new[n].tier]
up = sum(1 for n in ranked if new[n].elo > old[n].elo)
tier_idx = {t: i for i, t in enumerate(order)}
print(f"  티어가 바뀐 선수 {len(moved)}/{len(ranked)}명 (올라간 사람 {sum(tier_idx[b] > tier_idx[a] for _, a, b in moved)}, 내려간 사람 {sum(tier_idx[b] < tier_idx[a] for _, a, b in moved)}), "
      f"한 단계 이내 {sum(abs(tier_idx[b] - tier_idx[a]) <= 1 for _, a, b in moved)}명")

diff = sorted(names, key=lambda n: new[n].elo - old[n].elo)
print("\n④ 가장 많이 내린 / 오른 선수 (전체)")
print("  내림:", ", ".join(f"{n} {old[n].elo}→{new[n].elo}({new[n].elo - old[n].elo:+d}, {new[n].total}경기)" for n in diff[:10]))
print("  오름:", ", ".join(f"{n} {old[n].elo}→{new[n].elo}({new[n].elo - old[n].elo:+d}, {new[n].total}경기)" for n in diff[::-1][:10]))

print(f"\n⑤ 배치중(5경기 이하) {len(placement)}명")
d = np.array([new[n].elo - old[n].elo for n in placement])
d_r = np.array([new[n].elo - old[n].elo for n in ranked])
print(f"  평균 변화 {d.mean():+.0f}, 평균 |변화| {np.abs(d).mean():.0f}, 최대 {d.min():+d} ~ {d.max():+d}   (랭킹 대상은 평균 {d_r.mean():+.0f}, 평균 |변화| {np.abs(d_r).mean():.0f})")
print("  1500에서 얼마나 떨어져 있나: 기존 평균 |ELO-1500| " f"{np.mean([abs(old[n].elo - 1500) for n in placement]):.0f} → 변경 {np.mean([abs(new[n].elo - 1500) for n in placement]):.0f}")
by_g = collections.defaultdict(list)
for n in placement:
    by_g[new[n].total].append(new[n].elo - old[n].elo)
print("  경기 수별 평균 변화:", ", ".join(f"{g}경기 {np.mean(v):+.0f}({len(v)}명)" for g, v in sorted(by_g.items())))

print("\n⑥ 다른 K 배율과의 비교 (성과 x2 고정, 랭킹 대상)")
print(f"  {'K 배율':>6s} {'평균 변동폭/경기':>14s} {'평균':>6s} {'SD':>5s} {'TOP10 겹침(현재안)':>16s}")
base_top = set(t_new)
for m in (1.0, 1.25, 1.5, 2.0):
    res = engine.compute(rows, [(1, functools.partial(engine.rule_v2, k_multiplier=m, perf_weight=2.0))])
    pl = res.players
    hist = collections.defaultdict(list)
    last = {}
    swings = []
    for rnd, nick, *_x, elo in res.history:
        swings.append(abs(elo - last.get(nick, 1500))); last[nick] = elo
    v = np.array([pl[n].elo for n in ranked])
    tag = "  ← 현재" if m == engine.V2_K_MULTIPLIER else ""
    print(f"  {m:6.2f} {np.mean(swings):14.1f} {v.mean():6.0f} {v.std():5.0f} {len(set(top(pl, ranked)) & base_top):10d}/10{tag}")
