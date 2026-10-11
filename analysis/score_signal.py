"""점수(개인 점수 / 팀 점수)가 승패나 K/D와 별개의 정보를 담고 있는지 본다.

    python analysis/score_signal.py

- 개인 점수는 모드마다 단위가 다르므로 라운드 안에서 표준화(z-score)해서 비교한다.
- 승패 구분력은 AUC(0.5 = 동전 던지기, 1.0 = 완벽)로 본다. 신뢰구간은 라운드 단위 부트스트랩.
- 데이터가 늘면 다시 돌려서 결론이 바뀌는지 본다. (표본: data/source/matches.csv 에서 점수가 있는 라운드만)
"""
import collections
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402

SOURCE = os.path.join(ROOT, "data", "source", "matches.csv")
rng = np.random.default_rng(0)


def zscore(values):
    a = np.array(values, dtype=float)
    return (a - a.mean()) / a.std() if a.std() > 0 else a * 0


def auc(score, label):
    """label=1 인 쪽이 더 높은 점수를 받을 확률 (동점은 절반)"""
    score, label = np.asarray(score), np.asarray(label)
    pos, neg = score[label == 1], score[label == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    diff = pos[:, None] - neg[None, :]
    return ((diff > 0).sum() + 0.5 * (diff == 0).sum()) / diff.size


def main():
    rows, issues = engine.load_matches(SOURCE)
    assert not [i for i in issues if i.level == "error"], issues
    engine.fill_round_meta(rows)

    by_round = collections.defaultdict(list)
    for r in rows:
        if r.player_score is not None and r.winning_team in (1, 2):
            by_round[r.round].append(r)
    by_round = {k: v for k, v in by_round.items() if len(v) >= 6}
    print(f"개인 점수가 있는 라운드 {len(by_round)}개, 선수-라운드 {sum(len(v) for v in by_round.values())}행")

    # 1) 모드별 개인 점수 단위
    print("\n[모드별 개인 점수 범위] (단위가 모드마다 다름 → 라운드 안에서 표준화해서 비교)")
    modes = collections.defaultdict(list)
    for rnd, g in by_round.items():
        modes[g[0].mode or "(모드 없음)"].append(rnd)
    for m, rnds in sorted(modes.items(), key=lambda x: -len(x[1])):
        vals = [r.player_score for rnd in rnds for r in by_round[rnd]]
        print(f"   {m:10s} 라운드 {len(rnds):2d}개  점수 중앙값 {int(np.median(vals)):6d}  범위 {min(vals)}~{max(vals)}")

    # 2) 라운드 내 표준화 후, 선수별 지표
    recs = []  # (round, win, z_score, z_kills, z_deaths, z_kd)
    for rnd, g in by_round.items():
        zs = zscore([r.player_score for r in g]); zk = zscore([r.kills for r in g]); zd = zscore([r.deaths for r in g])
        zkd = zscore([r.kills - r.deaths for r in g])
        for r, a, b, c, d in zip(g, zs, zk, zd, zkd):
            recs.append((rnd, 1 if r.team == r.winning_team else 0, a, b, c, d, r.mode))
    R = np.array([x[:6] for x in recs], dtype=float)
    rounds = sorted(by_round)

    print("\n[개인 점수와 K/D의 관계] (라운드 내 z-점수 상관)")
    print(f"   점수~킬 {np.corrcoef(R[:,2], R[:,3])[0,1]:+.2f}   점수~데스 {np.corrcoef(R[:,2], R[:,4])[0,1]:+.2f}   점수~(킬-데스) {np.corrcoef(R[:,2], R[:,5])[0,1]:+.2f}")
    X = np.column_stack([R[:, 3], R[:, 4], np.ones(len(R))])
    beta, *_ = np.linalg.lstsq(X, R[:, 2], rcond=None)
    resid = R[:, 2] - X @ beta
    r2 = 1 - resid.var() / R[:, 2].var()
    print(f"   킬/데스로 개인 점수를 설명하는 정도 R² = {r2:.2f}  → 나머지 {1-r2:.0%}는 K/D로 설명 안 되는 몫(목표 플레이 등)")
    print(f"   그 설명 안 되는 몫(잔차)과 승패의 상관 {np.corrcoef(resid, R[:,1])[0,1]:+.2f}")

    # 3) 승패 구분력 (AUC) + 라운드 부트스트랩
    def boot(fn):
        vals = []
        for _ in range(2000):
            pick = rng.choice(rounds, len(rounds))
            idx = np.concatenate([np.where(R[:, 0] == p)[0] for p in pick])
            vals.append(fn(R[idx]))
        return np.percentile(vals, [2.5, 97.5])

    candidates = {
        "개인 점수 (z)":           lambda M: auc(M[:, 2], M[:, 1]),
        "킬 (z)":                  lambda M: auc(M[:, 3], M[:, 1]),
        "킬-데스 (z)":             lambda M: auc(M[:, 5], M[:, 1]),
        "킬-데스 + 개인 점수 평균": lambda M: auc((M[:, 5] + M[:, 2]) / 2, M[:, 1]),
    }
    print("\n[같은 라운드 선수 중 승리 팀 선수를 얼마나 구분하는가] AUC (0.5=동전, 1.0=완벽)")
    for name, fn in candidates.items():
        lo, hi = boot(fn)
        print(f"   {name:24s} {fn(R):.3f}   95% [{lo:.3f}, {hi:.3f}]")
    d_lo, d_hi = None, None
    diffs = []
    for _ in range(2000):
        pick = rng.choice(rounds, len(rounds))
        idx = np.concatenate([np.where(R[:, 0] == p)[0] for p in pick])
        M = R[idx]
        diffs.append(auc((M[:, 5] + M[:, 2]) / 2, M[:, 1]) - auc(M[:, 5], M[:, 1]))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    print(f"   개인 점수를 K/D에 더했을 때의 AUC 변화 {np.mean(diffs):+.3f}  95% [{lo:+.3f}, {hi:+.3f}]  ({'유의' if lo > 0 or hi < 0 else '구분 불가'})")

    # 4) 팀 점수 접전도 (참고)
    print("\n[팀 점수 접전도] 점유율 s1/(s1+s2)")
    shares = []
    for rnd in sorted({r.round for r in rows}):
        g = [r for r in rows if r.round == rnd]
        t1, t2 = g[0].team1_score, g[0].team2_score
        if t1 is not None and t2 is not None and t1 + t2 > 0:
            shares.append((rnd, g[0].mode, abs(t1 / (t1 + t2) - 0.5)))
    if shares:
        m = np.array([s[2] for s in shares])
        print(f"   라운드 {len(shares)}개  |점유율-0.5| 중앙값 {np.median(m):.3f}, 90% {np.percentile(m, 90):.3f}, 최대 {m.max():.3f}")
        by_mode = collections.defaultdict(list)
        for _r, mode, v in shares: by_mode[mode].append(v)
        for mode, v in sorted(by_mode.items(), key=lambda x: -len(x[1])):
            print(f"   {str(mode):8s} {len(v):2d}개  중앙값 {np.median(v):.3f}  최대 {max(v):.3f}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
