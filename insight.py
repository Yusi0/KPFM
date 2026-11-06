"""선수별 한 줄 설명(인사이트) 생성.

상대 강도를 여러 겹으로 보정한 성적을 계산하고, 정해진 규칙과 문장 틀로 문장을 만든다.
같은 데이터면 항상 같은 문장이 나온다 (AI가 쓰지 않음).

    python insight.py                 전체 선수의 문장과 근거 숫자를 표로 출력
    python insight.py a_Yusi0 gukbab2 해당 선수만 출력

build.py가 insight.csv를 만들 때도 이 모듈을 쓴다. 웹이 단순히 쉼표로 줄을 나누므로 문장에는 쉼표를 쓰지 않는다.
"""
import math
import os
import statistics as st
import sys
from collections import defaultdict

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(HERE, "data", "source", "matches.csv")

# 기준값은 여기서만 고친다.
CONFIG = {
    "placement_games": 5,    # 이 경기 수 이하는 판단을 보류하는 문장만 쓴다
    "ridge": 3.0,            # 경기 수가 적은 선수를 평균 쪽으로 당기는 세기 (가상의 평균 경기 수)
    "gap_min_games": 10,     # 순위 차이를 말하려면 필요한 경기 수 (적으면 보정값이 불안정)
    "adj_good": 1.15,        # 보정값이 이 이상이면 '상대에 비해 성적이 좋다'
    "adj_bad": 0.87,         # 이 이하이면 '상대에 비해 성적이 낮다'
    "rank_gap": 8,           # ELO 순위와 보정 순위가 이만큼 이상 차이나면 '다르다'고 말함
    "opp_delta": 60,         # 상대 평균 ELO가 리그 평균과 이만큼 이상 차이나면 언급
    "mate_theta": 0.15,      # 팀원 강도 추정값이 이만큼 이상 낮으면(약하면) 언급
    "mate_winrate": 0.55,    # '약한 팀원에도 이김'을 말하려면 필요한 승률
    "trend_games": 5,        # 최근 몇 경기의 ELO 변화를 볼지
    "trend_delta": 40,       # 그 변화가 이만큼 이상이면 언급
    "iterations": 300,
}


def build_records(rows):
    """(선수 -> 경기별 기록) 목록. 승리 팀이 1/2가 아닌 라운드는 제외한다 (engine.compute와 같은 규칙)."""
    by_round = defaultdict(list)
    for r in rows:
        by_round[r.round].append(r)
    recs = defaultdict(list)
    for rnd in sorted(by_round):
        group = by_round[rnd]
        winner = group[0].winning_team
        if winner not in (1, 2):
            continue
        for r in group:
            opp = [x.nickname for x in group if x.team != r.team]
            mates = [x.nickname for x in group if x.team == r.team and x is not r]
            if not opp:
                continue
            perf = math.log((r.kills + 1) / (r.deaths + 1))
            recs[r.nickname].append({"round": rnd, "opp": opp, "mates": mates, "perf": perf, "win": r.team == winner})
    return recs


def adjusted_ratings(recs, ridge, iterations):
    """상대 강도를 빼고 본 개인 성적 (킬/데스 로그비).

    성적 = 내 실력 - 상대 평균 실력 이라고 보고 모든 선수를 한꺼번에 푼다. 상대의 실력도 그 상대의 상대로
    검증되므로 (전파) 한 겹이 아니라 전체 연결을 따라 정해진다. 경기 수가 적으면 평균(0) 쪽으로 당긴다.
    """
    players = list(recs)
    theta = {p: 0.0 for p in players}
    for _ in range(iterations):
        new = {}
        for p in players:
            total = sum(g["perf"] + st.mean(theta[o] for o in g["opp"] if o in theta) for g in recs[p])
            new[p] = total / (len(recs[p]) + ridge)
        center = st.mean(new.values())
        theta = {p: v - center for p, v in new.items()}
    return theta


def compute_insights(rows, result, config=None):
    cfg = dict(CONFIG, **(config or {}))
    recs = build_records(rows)
    elo = {n: p.elo for n, p in result.players.items()}
    theta = adjusted_ratings(recs, cfg["ridge"], cfg["iterations"]) if recs else {}
    # 기준: 모든 (선수, 경기)의 상대 평균 ELO. 경기를 많이 한 선수들의 몫이 그대로 반영된 '보통의 상대 강도'
    league = st.mean(st.mean(elo[o] for o in g["opp"]) for gs in recs.values() for g in gs) if recs else 1500.0

    # 순위 비교는 정식 순위가 붙는 선수끼리만 (6경기 이상)
    qualified = [p for p in recs if len(recs[p]) > cfg["placement_games"]]
    elo_rank = {p: i for i, p in enumerate(sorted(qualified, key=lambda p: -elo[p]), start=1)}
    adj_rank = {p: i for i, p in enumerate(sorted(qualified, key=lambda p: -theta[p]), start=1)}

    history = defaultdict(list)
    for rnd, nick, _k, _d, _kdr, e in result.history:
        history[nick].append((rnd, e))

    out = {}
    for p, games in recs.items():
        n = len(games)
        opp_avg = st.mean(st.mean(elo[o] for o in g["opp"]) for g in games)
        opp_delta = opp_avg - league
        mate_theta = st.mean(st.mean(theta[m] for m in g["mates"]) for g in games if g["mates"]) \
            if any(g["mates"] for g in games) else 0.0
        win_rate = sum(g["win"] for g in games) / n
        hist = [e for _r, e in sorted(history[p])]
        k = cfg["trend_games"]
        trend = hist[-1] - hist[-k - 1] if len(hist) > k else (hist[-1] - 1500 if hist else 0)
        gap = (elo_rank[p] - adj_rank[p]) if p in elo_rank else None
        out[p] = {
            "games": n, "adj": round(math.exp(theta[p]), 2), "opp_avg": round(opp_avg), "opp_delta": round(opp_delta), "theta": round(theta[p], 3),
            "elo_rank": elo_rank.get(p), "adj_rank": adj_rank.get(p), "gap": gap,
            "trend": trend, "text": sentence(n, opp_avg, opp_delta, gap, mate_theta, win_rate, trend, cfg, math.exp(theta[p])),
        }
    return out


def _ro(number):
    """숫자 뒤 조사: 받침이 있게 읽히는 끝자리(0 3 6)는 '으로', 나머지는 '로'."""
    return "으로" if str(number)[-1] in "036" else "로"


def sentence(n, opp_avg, opp_delta, gap, mate_theta, win_rate, trend, cfg, adj=1.0):
    """해당하는 조각 중 우선순위가 높은 두 개를 문장으로 만든다. 쉼표는 쓰지 않는다."""
    opp = round(opp_avg)
    if n <= cfg["placement_games"]:
        if opp_delta >= cfg["opp_delta"]:
            tail = f"지금까지 만난 상대는 평균 ELO {opp}{_ro(opp)} 보통보다 강한 편이어서 KDR과 승률은 낮게 나왔을 수 있습니다."
        elif opp_delta <= -cfg["opp_delta"]:
            tail = f"지금까지 만난 상대는 평균 ELO {opp}{_ro(opp)} 보통보다 약한 편이어서 KDR과 승률은 후하게 나왔을 수 있습니다."
        else:
            tail = "지금까지 만난 상대는 보통 수준이었습니다."
        return f"아직 {n}경기라 평가하기엔 이릅니다. {tail}"

    parts = []
    if gap is not None and n >= cfg["gap_min_games"]:
        if gap >= cfg["rank_gap"]:
            parts.append("상대 강도를 감안하면 ELO 순위보다 성적이 좋은 편입니다.")
        elif gap <= -cfg["rank_gap"]:
            parts.append("상대 강도를 감안하면 ELO 순위만큼의 성적은 아닌 편입니다.")
    # 상대 강도는 선수 자신의 수준(보정값)과 함께 읽어야 뜻이 정해진다
    good, bad = adj >= cfg["adj_good"], adj <= cfg["adj_bad"]
    if opp_delta >= cfg["opp_delta"]:
        head = f"평균 ELO {opp}{_ro(opp)} 보통보다 강한 상대와 많이 붙"
        if good:
            parts.append(f"{head}었는데도 성적이 좋았습니다.")
        elif bad:
            parts.append(f"{head}었고 성적은 평균 이하입니다.")
        else:
            parts.append(f"{head}어서 KDR과 승률이 낮게 나왔을 수 있습니다.")
    elif opp_delta <= -cfg["opp_delta"]:
        head = f"평균 ELO {opp}{_ro(opp)} 보통보다 약한 상대와 많이 붙"
        if good:
            parts.append(f"{head}었지만 상대 강도를 빼도 성적이 좋습니다.")
        elif bad:
            parts.append(f"{head}었는데도 성적은 평균 이하입니다.")
        else:
            parts.append(f"{head}어서 KDR과 승률이 후하게 나왔을 수 있습니다.")
    if mate_theta <= -cfg["mate_theta"] and win_rate >= cfg["mate_winrate"]:
        parts.append("팀원이 약한 경기에서도 승률이 높습니다.")
    if trend >= cfg["trend_delta"]:
        parts.append(f"최근 {cfg['trend_games']}경기에서 ELO가 {trend} 올랐습니다.")
    elif trend <= -cfg["trend_delta"]:
        parts.append(f"최근 {cfg['trend_games']}경기에서 ELO가 {abs(trend)} 내려갔습니다.")
    text = " ".join(parts[:2]) or "상대 강도를 감안해도 ELO 순위와 성적이 대체로 맞습니다."
    assert "," not in text
    return text


def insight_rows(result, insights):
    """insight.csv 한 줄 = (선수, 경기 수, 보정값, 보정 순위, 상대 평균 ELO, 문장). ELO 순."""
    ordered = sorted(insights, key=lambda n: (-result.players[n].elo, n))
    return [(n, insights[n]["games"], f"{insights[n]['adj']:.2f}", insights[n]["adj_rank"] or "",
             insights[n]["opp_avg"], insights[n]["text"]) for n in ordered]


def load(source=DEFAULT_SOURCE):
    rows, issues = engine.load_matches(source)
    if any(i.level == "error" for i in issues):
        raise SystemExit("원본 CSV에 오류가 있습니다. python build.py --check 로 확인하세요.")
    engine.fill_round_meta(rows)
    result = engine.compute(rows)
    return rows, result, compute_insights(rows, result)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    rows, result, ins = load()
    names = [n for n in argv if n in ins] or sorted(ins, key=lambda p: -result.players[p].elo)
    for p in names:
        d = ins[p]
        print(f"{p:<18} G{d['games']:<3} ELO {result.players[p].elo:<5} 상대 {d['opp_avg']} ({d['opp_delta']:+}) "
              f"보정 {d['adj']:.2f} 순위 {d['elo_rank']}→{d['adj_rank']} 추세 {d['trend']:+}")
        print(f"    {d['text']}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
