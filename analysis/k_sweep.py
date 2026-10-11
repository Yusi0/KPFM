"""새 규칙(rule_v2)을 첫 라운드부터 적용했을 때 K 배율과 성과 비중에 따른 결과를 비교한다.

    python analysis/k_sweep.py [원본.csv]

- 변동 크기: 한 경기에서 ELO가 평균 몇 점 움직이는가 (기존 공식과 비교)
- ELO 폭: 10경기 이상 선수의 표준편차와 최소~최대 (티어가 얼마나 퍼지는가)
- 순위상관 / TOP10: 기존 공식 결과와 순위가 얼마나 같은가
- 정확도 / log loss: 매 라운드 시작 시점의 팀 평균 ELO로 승자를 맞춘 결과 (라운드 21 이후, 동전 던지기 = 0.693)
"""
import collections
import functools
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import engine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SOURCE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "source", "matches.csv")
rows = engine.fill_round_meta(engine.load_matches(SOURCE)[0])
by_round = collections.defaultdict(list)
for r in rows:
    by_round[r.round].append(r)
games = collections.Counter(r.nickname for r in rows if r.winning_team in (1, 2))
active = sorted(n for n in games if games[n] >= 10)


def run(rule):
    res = engine.compute(rows, [(1, rule)])
    last, deltas, pre_by_round = {}, [], {}
    hist = collections.defaultdict(list)
    for rnd, nick, *_rest, elo in res.history:
        hist[rnd].append((nick, elo))
    for rnd in sorted(by_round):
        if rnd not in hist:
            continue
        pre_by_round[rnd] = {r.nickname: last.get(r.nickname, 1500) for r in by_round[rnd]}
        for nick, elo in hist[rnd]:
            deltas.append(abs(elo - last.get(nick, 1500)))
            last[nick] = elo
    return res, np.array(deltas), pre_by_round


def predict(pre_by_round, scale, start=21):
    ll, hit = [], []
    for rnd, pre in pre_by_round.items():
        if rnd < start:
            continue
        g = by_round[rnd]
        t1 = [pre[r.nickname] for r in g if r.team == 1]; t2 = [pre[r.nickname] for r in g if r.team == 2]
        if not t1 or not t2:
            continue
        a, b = sum(t1) / len(t1), sum(t2) / len(t2)
        p = min(max(1 / (1 + 10 ** ((b - a) / scale)), 1e-9), 1 - 1e-9)
        y = 1 if g[0].winning_team == 1 else 0
        ll.append(-(y * math.log(p) + (1 - y) * math.log(1 - p)))
        if a != b:
            hit.append((a > b) == (y == 1))
    return float(np.mean(hit)), float(np.mean(ll))


def ranks(res):
    order = sorted(active, key=lambda n: -res.players[n].elo)
    return {n: i for i, n in enumerate(order)}


base_res, base_delta, base_pre = run(engine.legacy_v1)
rk_base = ranks(base_res)


def row(label, res, delta, pre):
    vals = np.array([res.players[n].elo for n in active])
    rk = ranks(res)
    a = np.array([rk_base[n] for n in active]); b = np.array([rk[n] for n in active])
    best = min((200, 300, 400), key=lambda s: predict(pre, s)[1])
    acc, ll = predict(pre, best)
    top = len({n for n in active if rk_base[n] < 10} & {n for n in active if rk[n] < 10})
    print(f"{label:34s} {delta.mean():6.1f} {vals.mean():6.0f} {vals.std():5.0f} {vals.min():5.0f}~{vals.max():<5.0f} "
          f"{np.corrcoef(a, b)[0, 1]:6.2f} {top:4d}/10 {acc:6.3f} {ll:7.4f} (s={best})")


print(f"원본: {SOURCE}\n라운드 {len(by_round)}개, 10경기 이상 {len(active)}명\n")
print(f"{'공식':34s} {'평균|변동|':>6s} {'평균':>6s} {'SD':>5s} {'최소~최대':>11s} {'순위상관':>6s} {'TOP10':>7s} {'정확도':>6s} {'logloss':>7s}")
row("기존 공식(legacy_v1) 전 구간", base_res, base_delta, base_pre)
for perf in (1.0, 2.0):
    for m in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        rule = functools.partial(engine.rule_v2, k_multiplier=m, perf_weight=perf)
        res, delta, pre = run(rule)
        row(f"v2 전 구간, K×{m:.1f}, 성과×{perf:.0f}", res, delta, pre)
    print()

print("티어 분포 (10경기 이상 선수)")
tiers = engine.TIER_NAMES
def dist(res):
    c = collections.Counter(res.players[n].tier for n in active)
    return " ".join(f"{t.split()[0][:2]}{t.split()[1] if ' ' in t else ''}:{c[t]}" for t in tiers if c[t])
print("  기존                :", dist(base_res))
for m, perf in ((1.0, 1.0), (2.0, 1.0), (3.0, 1.0), (3.0, 2.0)):
    res, *_ = run(functools.partial(engine.rule_v2, k_multiplier=m, perf_weight=perf))
    print(f"  v2 K×{m:.1f} 성과×{perf:.0f}    :", dist(res))
