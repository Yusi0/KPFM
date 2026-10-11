"""KPFM 스크림 ELO 계산 엔진.

원본(data/source/matches.csv) 하나만 읽어서 처음부터 순서대로 계산한다.
부분 재계산이나 누적값 갱신이 없으므로 수정/삭제 후에도 항상 같은 입력이면 같은 결과가 나온다.
DB, 입력 메뉴, 파일 쓰기와는 무관하다 (그건 build.py).
"""
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field

REQUIRED_HEADERS = ["Round", "Nickname", "Team", "Kills", "Deaths", "Winning Team"]
OPTIONAL_HEADERS = ["Map", "Mode", "Team1 Score", "Team2 Score", "Player Score"]
SOURCE_HEADERS = ["Round", "Nickname", "Team", "Kills", "Deaths", "Map", "Winning Team",
                  "Mode", "Team1 Score", "Team2 Score", "Player Score"]

START_ELO = 1500

TIER_NAMES = [
    "Copper 3", "Copper 2", "Copper 1",
    "Bronze 3", "Bronze 2", "Bronze 1",
    "Silver 3", "Silver 2", "Silver 1",
    "Gold 3", "Gold 2", "Gold 1",
    "Platinum 3", "Platinum 2", "Platinum 1",
    "Diamond 3", "Diamond 2", "Diamond 1",
    "Champion",
]


# --------------------------------------------------------------------------- 규칙 (공식)

def calculate_tier(elo):
    """ELO 점수에 따라 100점 단위로 티어 이름 반환 (1500~1599 = Gold 3)"""
    tier_index = (elo - START_ELO) // 100 + 9
    return TIER_NAMES[max(0, min(tier_index, len(TIER_NAMES) - 1))]


def legacy_v1(player_elo, opponent_avg_elo, result, kills, deaths, player_total_matches,
              k_normal=30, kill_weight=0.2, death_weight=0.07, initial_k_factor=50, initial_matches_threshold=5):
    """기존 elo.py의 calculate_elo와 동일한 공식 (result: 1 승, 0 패). 1~현재 라운드의 기준 규칙."""
    if player_total_matches <= initial_matches_threshold:
        base_k = initial_k_factor
    else:
        base_k = k_normal / (1 + (player_total_matches - initial_matches_threshold) / 20)
        base_k = max(base_k, k_normal / 2)

    expected_result = 1 / (1 + 10 ** ((opponent_avg_elo - player_elo) / 200))
    win_loss_numeric_factor = 1 if result == 1 else -1
    elo_change_match_outcome = base_k * win_loss_numeric_factor * (1.5 - expected_result)

    performance_score = (kills * kill_weight) - (deaths * death_weight)
    if result == 0:
        performance_score *= 0.5

    new_elo = player_elo + elo_change_match_outcome + performance_score
    return max(0, int(round(new_elo)))


# (적용 시작 라운드, 규칙 함수). 라운드가 커질수록 아래 항목이 위 항목을 대체한다.
# 점수/모드 반영 규칙이 정해지면 여기에 (N, new_rule)만 추가하면 N라운드부터 적용된다.
RULESET = [(1, legacy_v1)]


def rule_for_round(round_num, ruleset=None):
    ruleset = ruleset or RULESET
    chosen = ruleset[0][1]
    for start, fn in ruleset:
        if round_num >= start:
            chosen = fn
    return chosen


# --------------------------------------------------------------------------- 읽기/검증

@dataclass
class Row:
    round: int
    nickname: str
    team: int
    kills: int
    deaths: int
    map: str = None
    winning_team: int = 0
    mode: str = None
    team1_score: int = None
    team2_score: int = None
    player_score: int = None
    line: int = 0  # 원본 CSV 줄 번호 (오류 안내용)


@dataclass
class Issue:
    level: str   # "error" 또는 "warning"
    message: str
    round: int = None


def normalize_mode(text):
    text = (text or "").strip().lower()
    return text or None


def load_matches(path):
    """원본 CSV를 읽어 (rows, issues)를 돌려준다. 형식 오류가 있으면 해당 줄을 issues(error)에 담는다."""
    issues, rows = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = [h.strip() for h in next(reader, [])]
        missing = [h for h in REQUIRED_HEADERS if h not in headers]
        if missing:
            return [], [Issue("error", f"필수 열이 없습니다: {', '.join(missing)} (찾은 열: {', '.join(headers)})")]
        idx = {h: headers.index(h) for h in headers}

        def cell(row, name):
            if name not in idx or idx[name] >= len(row):
                return None
            return row[idx[name]].strip() or None

        def int_cell(row, name, required=False):
            v = cell(row, name)
            if v is None:
                if required:
                    raise ValueError(f"'{name}' 값이 비어 있습니다")
                return None
            try:
                return int(v)
            except ValueError:
                raise ValueError(f"'{name}' 값 '{v}'은(는) 정수가 아닙니다")

        for line_no, row in enumerate(reader, start=2):
            if not any(c.strip() for c in row):
                continue
            try:
                nick = cell(row, "Nickname")
                if not nick:
                    raise ValueError("'Nickname' 값이 비어 있습니다")
                rows.append(Row(
                    round=int_cell(row, "Round", True), nickname=nick,
                    team=int_cell(row, "Team", True), kills=int_cell(row, "Kills", True),
                    deaths=int_cell(row, "Deaths", True), winning_team=int_cell(row, "Winning Team", True),
                    map=cell(row, "Map"), mode=normalize_mode(cell(row, "Mode")),
                    team1_score=int_cell(row, "Team1 Score"), team2_score=int_cell(row, "Team2 Score"),
                    player_score=int_cell(row, "Player Score"), line=line_no))
            except ValueError as e:
                issues.append(Issue("error", f"{line_no}번째 줄: {e}: {row}"))
    return rows, issues


def fill_round_meta(rows):
    """라운드의 모드/팀 점수는 한 행에만 써도 같은 라운드 전체에 채운다 (직접 편집 편의)."""
    by_round = defaultdict(list)
    for r in rows:
        by_round[r.round].append(r)
    for group in by_round.values():
        mode = next((r.mode for r in group if r.mode), None)
        t1 = next((r.team1_score for r in group if r.team1_score is not None), None)
        t2 = next((r.team2_score for r in group if r.team2_score is not None), None)
        for r in group:
            r.mode = r.mode or mode
            if r.team1_score is None: r.team1_score = t1
            if r.team2_score is None: r.team2_score = t2
    return rows


def _lookalike_key(nick):
    return nick.lower().replace("i", "l").replace("1", "l").replace("0", "o")


def validate(rows):
    """원본 데이터 검증. error가 있으면 계산하지 않는다. warning은 확인용이다."""
    issues = []
    by_round = defaultdict(list)
    for r in rows:
        by_round[r.round].append(r)

    for rnd, group in sorted(by_round.items()):
        if rnd < 1:
            issues.append(Issue("error", f"라운드 번호는 1 이상이어야 합니다: {rnd}", rnd))
        for r in group:
            if r.team not in (1, 2):
                issues.append(Issue("error", f"{r.line}번째 줄: Team은 1 또는 2여야 합니다 ({r.nickname}: {r.team})", rnd))
            if r.winning_team not in (0, 1, 2):
                issues.append(Issue("error", f"{r.line}번째 줄: Winning Team은 0, 1, 2 중 하나여야 합니다 ({r.winning_team})", rnd))
            if r.kills < 0 or r.deaths < 0:
                issues.append(Issue("error", f"{r.line}번째 줄: 킬/데스는 음수일 수 없습니다 ({r.nickname})", rnd))
            if r.mode and "," in r.mode:
                issues.append(Issue("error", f"{r.line}번째 줄: 모드 이름에 쉼표를 쓸 수 없습니다 ({r.mode})", rnd))
            if r.map and "," in r.map:
                issues.append(Issue("error", f"{r.line}번째 줄: 맵 이름에 쉼표를 쓸 수 없습니다 ({r.map})", rnd))
            if "," in r.nickname:
                issues.append(Issue("error", f"{r.line}번째 줄: 닉네임에 쉼표를 쓸 수 없습니다 ({r.nickname})", rnd))
        dups = [n for n, c in Counter(r.nickname for r in group).items() if c > 1]
        if dups:
            issues.append(Issue("error", f"같은 라운드에 닉네임이 중복되었습니다: {', '.join(dups)}", rnd))
        if len({r.winning_team for r in group}) > 1:
            issues.append(Issue("error", f"승리 팀이 서로 다릅니다: {sorted({r.winning_team for r in group})}", rnd))
        for label, attr in (("모드", "mode"), ("1팀 점수", "team1_score"), ("2팀 점수", "team2_score")):
            values = {getattr(r, attr) for r in group if getattr(r, attr) is not None}
            if len(values) > 1:
                issues.append(Issue("error", f"{label}가 서로 다릅니다: {sorted(values, key=str)}", rnd))
        has1 = any(r.team1_score is not None for r in group)
        has2 = any(r.team2_score is not None for r in group)
        if has1 != has2:
            issues.append(Issue("error", "팀 점수는 1팀과 2팀 둘 다 있어야 합니다", rnd))

    # 경고: 점수 방향, 팀 인원
    for rnd, group in sorted(by_round.items()):
        t1 = next((r.team1_score for r in group if r.team1_score is not None), None)
        t2 = next((r.team2_score for r in group if r.team2_score is not None), None)
        w = group[0].winning_team
        if w in (1, 2) and t1 is not None and t2 is not None and t1 != t2 and (1 if t1 > t2 else 2) != w:
            issues.append(Issue("warning", f"점수 {t1}:{t2}인데 승리 팀이 {w}팀입니다", rnd))
        n1, n2 = sum(r.team == 1 for r in group), sum(r.team == 2 for r in group)
        if abs(n1 - n2) > 1:
            issues.append(Issue("warning", f"팀 인원 차이가 큽니다 ({n1}v{n2})", rnd))

    # 경고: 헷갈리는 닉네임 (I/l/1, O/0) - 같은 사람이 철자만 다르게 들어간 경우를 잡는다
    seen = defaultdict(set)
    for r in rows:
        seen[_lookalike_key(r.nickname)].add(r.nickname)
    for names in seen.values():
        if len(names) > 1:
            issues.append(Issue("warning", f"비슷한 닉네임이 있습니다 (같은 사람인지 확인): {', '.join(sorted(names))}"))
    return issues


# --------------------------------------------------------------------------- 계산

@dataclass
class Player:
    nickname: str
    elo: int = START_ELO
    kills: int = 0
    deaths: int = 0
    wins: int = 0
    losses: int = 0

    @property
    def total(self):
        return self.wins + self.losses

    @property
    def tier(self):
        return calculate_tier(self.elo)


@dataclass
class Result:
    players: dict = field(default_factory=dict)   # nickname -> Player
    history: list = field(default_factory=list)   # (round, nickname, cum_kills, cum_deaths, kdr, elo_after)
    skipped_rounds: list = field(default_factory=list)  # 무승부/취소(승리 팀 0)로 계산에서 제외된 라운드


def compute(rows, ruleset=None):
    """모든 라운드를 번호 순서대로 처음부터 계산한다.

    - 같은 라운드의 모든 선수는 그 라운드 시작 시점의 ELO로 상대 팀 평균과 비교한다.
    - 승리 팀이 0인 라운드(무승부/취소)는 ELO, 승패, 킬/데스, 경기 수에 반영하지 않는다.
    - 선수의 경기 수는 이전 라운드까지의 승+패 합이다 (K-factor 계산에 사용).
    """
    result = Result()
    players = result.players
    for r in rows:  # 무승부 라운드에만 나오는 선수도 명단에는 둔다
        players.setdefault(r.nickname, Player(r.nickname))

    by_round = defaultdict(list)
    for r in rows:
        by_round[r.round].append(r)

    cum = defaultdict(lambda: [0, 0])
    for rnd in sorted(by_round):
        group = by_round[rnd]
        winner = group[0].winning_team
        if winner not in (1, 2):
            result.skipped_rounds.append(rnd)
            continue

        rule = rule_for_round(rnd, ruleset)
        pre = {r.nickname: players[r.nickname].elo for r in group}
        team = {1: [r for r in group if r.team == 1], 2: [r for r in group if r.team == 2]}
        avg = {t: (sum(pre[r.nickname] for r in rs) / len(rs) if rs else START_ELO) for t, rs in team.items()}

        for t in (1, 2):
            for r in team[t]:
                p = players[r.nickname]
                outcome = 1 if winner == t else 0
                p.elo = rule(pre[r.nickname], avg[3 - t], outcome, r.kills, r.deaths, p.total)
                p.kills += r.kills
                p.deaths += r.deaths
                p.wins += outcome
                p.losses += 1 - outcome
                cum[r.nickname][0] += r.kills
                cum[r.nickname][1] += r.deaths
                ck, cd = cum[r.nickname]
                result.history.append((rnd, r.nickname, ck, cd, round(ck / max(1, cd), 2), p.elo))
    return result
