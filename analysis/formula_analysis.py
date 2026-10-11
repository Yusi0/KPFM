"""ELO 공식 후보 비교 분석. 103라운드 고정 데이터(tests/baseline/matches_r103.csv)로 여러 공식을 같은 라운드에 처음부터 걸어가며(walk-forward) 비교한다.

    python analysis/formula_analysis.py                          # 고정 데이터(정리 전 103라운드)
    python analysis/formula_analysis.py data/source/matches.csv  # 현재 원본(정리 후)

읽는 법
- 승패 예측력: 매 라운드 시작 시점의 팀 평균 ELO로 승자를 맞췄을 때 정확도와 log loss (동전 던지기 = 0.693, 낮을수록 좋음).
  공식 간 차이는 라운드 단위 부트스트랩 95% 구간으로 본다. 구간이 0을 포함하면 "구분 불가"다.
- 시스템 성질: 라운드당 전체 ELO 순변화(0에 가까워야 인플레이션이 없음), 10경기 이상 선수의 평균/표준편차, 현재 공식과의 순위 상관.
- 이 스크립트의 후보 공식(A~N)은 분석용이다. 실제 공식은 engine.py에 있다.
- 새 라운드가 쌓이면 BASELINE을 data/source/matches.csv 로 바꿔 다시 돌려서 결론이 바뀌는지 본다.
"""
import collections
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import engine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASELINE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "baseline", "matches_r103.csv")  # 인자로 다른 CSV 지정 가능: python analysis/formula_analysis.py data/source/matches.csv

rows = engine.fill_round_meta(engine.load_matches(BASELINE)[0])
by_round = collections.defaultdict(list)
for r in rows: by_round[r.round].append(r)
ROUNDS = sorted(by_round)

# ---------------------------------------------------------------- 공식 변형
def k_legacy(total, k_normal=30, k_init=50, thr=5):
    if total <= thr: return k_init
    return max(k_normal / (1 + (total - thr) / 20), k_normal / 2)

def make_rule(scale=200, outcome="legacy", perf=1.0, kfn=k_legacy, kill_w=0.2, death_w=0.07, team_based=False, center=False):
    def rule(elo, opp, res, kills, deaths, total, own=None, pm=None):
        K = kfn(total)
        me = own if (team_based and own is not None) else elo
        E = 1 / (1 + 10 ** ((opp - me) / scale))
        if outcome == "legacy":
            o = K * (1 if res == 1 else -1) * (1.5 - E)
        else:                                   # 표준 ELO
            o = K * (res - E)
        raw = kills * kill_w - deaths * death_w
        if center and pm is not None:
            p = (raw - pm) * perf          # 라운드 평균을 빼서 성과항이 전체 합에 영향을 주지 않게 함
        else:
            p = raw * (0.5 if res == 0 else 1.0) * perf
        return max(0, int(round(elo + o + p)))
    return rule

VARIANTS = {
    "A 현재(legacy)":                       make_rule(200, "legacy", 1.0),
    "B 결과항만 표준식, 성과항 유지":         make_rule(200, "standard", 1.0),
    "C 현재에서 성과항 제거":                make_rule(200, "legacy", 0.0),
    "D 표준식 s=200, 성과항 없음":           make_rule(200, "standard", 0.0),
    "E 표준식 s=400, 성과항 없음":           make_rule(400, "standard", 0.0),
    "F 표준식 s=400, 성과항 0.5배":          make_rule(400, "standard", 0.5),
    "G 표준식 s=400, 성과항 1배":            make_rule(400, "standard", 1.0),
    "H 표준식 s=400, K=24 고정, 성과 없음":   make_rule(400, "standard", 0.0, kfn=lambda t: 24),
    "I 팀 기준 E, 표준식 s=400, 성과 1배":    make_rule(400, "standard", 1.0, team_based=True),
    "J 팀 기준 E, 표준식 s=400, 성과 0.5배":  make_rule(400, "standard", 0.5, team_based=True),
    "K 팀 기준 E, 표준식 s=400, 성과 없음":   make_rule(400, "standard", 0.0, team_based=True),
    "L 현재 모양(1.5-E), 팀 기준 E, s=200":   make_rule(200, "legacy", 1.0, team_based=True),
    "M 팀 기준 E, 표준식 s=400, 성과 보정 1배": make_rule(400, "standard", 1.0, team_based=True, center=True),
    "N 팀 기준 E, 표준식 s=400, 성과 보정 2배": make_rule(400, "standard", 2.0, team_based=True, center=True),
}

# ---------------------------------------------------------------- walk-forward
def run(rule):
    st = collections.defaultdict(lambda: [1500, 0])   # elo, games
    preds, per_player = [], []
    for rnd in ROUNDS:
        g = by_round[rnd]; w = g[0].winning_team
        if w not in (1, 2): continue
        pre = {r.nickname: st[r.nickname][0] for r in g}
        team = {1: [r for r in g if r.team == 1], 2: [r for r in g if r.team == 2]}
        avg = {t: sum(pre[r.nickname] for r in rs) / len(rs) for t, rs in team.items()}
        pm = sum(r.kills * 0.2 - r.deaths * 0.07 for r in g) / len(g)
        preds.append((rnd, avg[1], avg[2], 1 if w == 1 else 0, len(team[1]), len(team[2]), g))
        for t in (1, 2):
            for r in team[t]:
                s = st[r.nickname]; res = 1 if w == t else 0
                new = rule(pre[r.nickname], avg[3 - t], res, r.kills, r.deaths, s[1], own=avg[t], pm=pm)
                per_player.append((rnd, r.nickname, t, res, pre[r.nickname], new, s[1], r.kills, r.deaths, avg[3 - t]))
                s[0] = new; s[1] += 1
    return preds, per_player, {n: v[0] for n, v in st.items()}

def logloss(preds, s, start=0):
    ll = []
    for (rnd, r1, r2, y, *_), in [(p,) for p in preds if p[0] >= start]:
        p = 1 / (1 + 10 ** ((r2 - r1) / s)); p = min(max(p, 1e-9), 1 - 1e-9)
        ll.append(-(y * math.log(p) + (1 - y) * math.log(1 - p)))
    return np.array(ll)

def acc(preds, start=0):
    a = [((p[1] > p[2]) == (p[3] == 1)) for p in preds if p[0] >= start and p[1] != p[2]]
    return np.mean(a), len(a)

SCALES = [50, 75, 100, 150, 200, 300, 400, 600, 800, 1200]
out = {}
for name, rule in VARIANTS.items():
    preds, pp, final = run(rule); out[name] = (preds, pp, final)

print("=" * 90)
print("1) 승패 예측력 (walk-forward: 매 라운드 시작 시점 팀 평균 ELO로 승자를 맞춤)")
print("   동전 던지기 log loss = 0.6931 / 라운드 수:", len(out["A 현재(legacy)"][0]))
for start in (1, 21):
    print(f"\n   [라운드 {start} 이후]")
    print(f"   {'공식':36s} {'정확도':>8s} {'최적 s':>7s} {'logloss(최적)':>14s} {'logloss(s=200)':>15s} {'logloss(s=400)':>15s}")
    for name, (preds, pp, final) in out.items():
        best = min(SCALES, key=lambda s: logloss(preds, s, start).mean())
        a, n = acc(preds, start)
        print(f"   {name:36s} {a:8.3f} {best:7d} {logloss(preds,best,start).mean():14.4f} {logloss(preds,200,start).mean():15.4f} {logloss(preds,400,start).mean():15.4f}")

print("\n" + "=" * 90)
print("2) 현재 공식 대비 로그손실 차이 (음수 = 변형이 더 잘 맞춤), 라운드 단위 부트스트랩 95% 구간, 각자 최적 s")
base_preds = out["A 현재(legacy)"][0]
rng = np.random.default_rng(0)
base_best = min(SCALES, key=lambda s: logloss(base_preds, s, 1).mean())
base_ll = logloss(base_preds, base_best, 1)
for name, (preds, pp, final) in out.items():
    if name.startswith("A"): continue
    best = min(SCALES, key=lambda s: logloss(preds, s, 1).mean())
    d = logloss(preds, best, 1) - base_ll
    boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"   {name:36s} 차이 {d.mean():+.4f}   95% [{lo:+.4f}, {hi:+.4f}]   {'(유의)' if lo > 0 or hi < 0 else '(구분 불가)'}")

print("\n" + "=" * 90)
print("3) 현재 공식(A)의 성질")
preds, pp, final = out["A 현재(legacy)"]
# 항 분해
K_ = lambda t: k_legacy(t)
outc, perf, delta_total = [], [], []
sign_loss, sign_win = [], []
for (rnd, n, t, res, pre, new, games, k, d, opp) in pp:
    E = 1 / (1 + 10 ** ((opp - pre) / 200)); K = K_(games)
    o = K * (1 if res else -1) * (1.5 - E)
    p = (k * 0.2 - d * 0.07) * (0.5 if res == 0 else 1)
    outc.append(o); perf.append(p); delta_total.append(new - pre)
    (sign_win if res else sign_loss).append((E, o, p, k, d))
outc, perf, dt = map(np.array, (outc, perf, delta_total))
print(f"   선수-라운드 {len(dt)}건. 평균 변화 {dt.mean():+.2f}, 결과항 평균 {outc.mean():+.2f}, 성과항 평균 {perf.mean():+.2f}")
print(f"   |결과항| 평균 {np.abs(outc).mean():.2f}  vs  |성과항| 평균 {np.abs(perf).mean():.2f}  → 성과항 비중 {np.abs(perf).mean()/(np.abs(perf).mean()+np.abs(outc).mean()):.0%}")
win_perf = np.mean([x[2] for x in sign_win]); loss_perf = np.mean([x[2] for x in sign_loss])
print(f"   성과항 평균: 승리 팀 {win_perf:+.2f}, 패배 팀 {loss_perf:+.2f} (승패와 같은 방향으로 이중 반영되는지)")
# 제로섬
round_net = collections.defaultdict(float)
for (rnd, n, t, res, pre, new, games, k, d, opp) in pp: round_net[rnd] += new - pre
nets = np.array(list(round_net.values()))
print(f"   라운드별 전체 ELO 순변화: 평균 {nets.mean():+.1f}, 표준편차 {nets.std():.1f}, 양수 라운드 {np.mean(nets>0):.0%}  (표준 ELO는 0에 가까워야 함)")
cur = np.array(list(final.values())); games_final = collections.Counter(r.nickname for r in rows)
active = np.array([final[n] for n in final if games_final[n] >= 10])
print(f"   최종 ELO: 전체 평균 {cur.mean():.0f} (시작 1500), 10경기 이상 {len(active)}명 평균 {active.mean():.0f}, 표준편차 {active.std():.0f}")
# 결과항 비대칭: E 구간별
print("\n   기대승률 E(s=200) 구간별, 결과항만의 평균 변화 (표준 ELO 대비)")
print(f"   {'E 구간':12s} {'승리시 현재':>11s} {'승리시 표준':>11s} {'패배시 현재':>11s} {'패배시 표준':>11s}   건수(승/패)")
bins = [(0, .25), (.25, .4), (.4, .6), (.6, .75), (.75, 1.01)]
for lo, hi in bins:
    w = [x for x in sign_win if lo <= x[0] < hi]; l = [x for x in sign_loss if lo <= x[0] < hi]
    f = lambda xs, std, win: np.mean([ (K_(5) if False else 1) * 0 for _ in xs]) if not xs else None
    # K=30 기준 대표값으로 비교
    Ew = np.mean([x[0] for x in w]) if w else float("nan"); El = np.mean([x[0] for x in l]) if l else float("nan")
    print(f"   {lo:.2f}~{min(hi,1):.2f}    {30*(1.5-Ew):+11.1f} {30*(1-Ew):+11.1f} {-30*(1.5-El):+11.1f} {-30*El:+11.1f}   {len(w)}/{len(l)}")
print("   (K=30 가정. 패배 열: 현재식은 기대승률이 낮을수록 더 많이 깎이고, 표준식은 반대)")

print("\n" + "=" * 90)
print("4) 예측 보정 (현재 공식 A의 ELO, 최적 s로 예측한 팀1 승률 vs 실제)")
bs = min(SCALES, key=lambda s: logloss(preds, s, 11).mean())
cal = collections.defaultdict(list)
for p in preds:
    if p[0] < 11: continue
    pr = 1 / (1 + 10 ** ((p[2] - p[1]) / bs)); cal[min(int(pr * 5), 4)].append((pr, p[3]))
print(f"   s={bs}, 라운드 11 이후")
for b in sorted(cal):
    xs = cal[b]; print(f"   예측 {np.mean([x[0] for x in xs]):.2f}  실제 {np.mean([x[1] for x in xs]):.2f}  ({len(xs)}라운드)")

print("\n" + "=" * 90)
print("5) 팀 인원 차이 / 점수 신호")
un = [p for p in preds if p[4] != p[5]]
bigger_wins = np.mean([ (p[3] == 1) == (p[4] > p[5]) for p in un]) if un else float("nan")
print(f"   인원이 다른 라운드 {len(un)}개 중 인원 많은 팀이 이긴 비율 {bigger_wins:.2f}")
sc = []
for p in preds:
    g = p[6]; t1 = next((r.team1_score for r in g if r.team1_score is not None), None); t2 = next((r.team2_score for r in g if r.team2_score is not None), None)
    if t1 is not None and t2 is not None and t1 + t2 > 0:
        sc.append((p[0], p[1] - p[2], t1 / (t1 + t2) - 0.5, g[0].mode, p[3]))
print(f"   팀 점수가 있는 라운드 {len(sc)}개 (모드별: {dict(collections.Counter(s[3] for s in sc))})")
if len(sc) > 5:
    x = np.array([s[1] for s in sc]); y = np.array([s[2] for s in sc])
    r = np.corrcoef(x, y)[0, 1]
    boots = []
    for _ in range(4000):
        i = rng.integers(0, len(x), len(x))
        if x[i].std() and y[i].std(): boots.append(np.corrcoef(x[i], y[i])[0, 1])
    print(f"   ELO 격차 vs 점유율-0.5 상관 {r:+.2f}  95% [{np.percentile(boots,2.5):+.2f}, {np.percentile(boots,97.5):+.2f}]")
    agree = np.mean([(s[2] > 0) == (s[4] == 1) for s in sc if s[2] != 0])
    print(f"   점수 우세 팀이 실제 승리 팀과 같은 비율 {agree:.2f}")
    margins = np.array([abs(s[2]) for s in sc]); print(f"   접전도 |점유율-0.5| 분포: 중앙값 {np.median(margins):.3f}, 90% {np.percentile(margins,90):.3f}, 최대 {margins.max():.3f}")

print()
print("=" * 90)
print("6) 공식별 ELO 시스템 성질 (10경기 이상 선수 기준)")
games = collections.Counter(r.nickname for r in rows if r.winning_team in (1, 2))
act = sorted(n for n in games if games[n] >= 10)
def ranks(d):
    order = sorted(act, key=lambda n: -d[n]); return {n: i for i, n in enumerate(order)}
baseA = out["A 현재(legacy)"][2]; rkA = ranks(baseA)
print(f"   {'공식':38s} {'라운드순변화':>9s} {'평균':>6s} {'표준편차':>8s} {'최소~최대':>11s} {'순위상관':>8s} {'TOP10 겹침':>10s} {'평균 순위이동':>12s}")
for name, (preds, pp, final) in out.items():
    net = collections.defaultdict(float)
    for (rnd, n, t, res, pre, new, g, k, d, opp) in pp: net[rnd] += new - pre
    vals = np.array([final[n] for n in act]); rk = ranks(final)
    a = np.array([rkA[n] for n in act]); b = np.array([rk[n] for n in act])
    sp = np.corrcoef(a, b)[0, 1]
    top = len({n for n in act if rkA[n] < 10} & {n for n in act if rk[n] < 10})
    print(f"   {name:38s} {np.mean(list(net.values())):+9.1f} {vals.mean():6.0f} {vals.std():8.0f} {vals.min():5.0f}~{vals.max():<5.0f} {sp:8.2f} {top:7d}/10 {np.abs(a-b).mean():12.1f}")
print(f"   (대상 {len(act)}명)")
