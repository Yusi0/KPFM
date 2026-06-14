import sqlite3
import os
import csv
from tabulate import tabulate
from datetime import datetime
from colorama import Fore, Style, init
import matplotlib.pyplot as plt
import platform
from matplotlib import rc

# Initialize Colorama
init(autoreset=True)

# 한글 폰트 설정
if platform.system() == "Darwin":  # macOS
    rc('font', family='AppleGothic')
elif platform.system() == "Windows":  # Windows
    rc('font', family='Malgun Gothic')
else:  # Linux
    rc('font', family='NanumGothic')

# 마이너스 기호 깨짐 방지
plt.rcParams['axes.unicode_minus'] = False

# 데이터베이스 경로 설정
DB_PATH = "./data/elo/db/data.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# 테이블 초기화 함수
def initialize_tables():
    """리더보드와 매치 테이블 생성"""
    cur.execute('''
    CREATE TABLE IF NOT EXISTS leaderboard (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nickname TEXT UNIQUE,
        kills INTEGER DEFAULT 0,
        deaths INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0,
        elo INTEGER DEFAULT 1500,
        tier TEXT DEFAULT 'Unranked'
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        round INTEGER,
        nickname TEXT,
        team INTEGER,
        kills INTEGER,
        deaths INTEGER,
        map TEXT DEFAULT NULL,
        winning_team INTEGER DEFAULT NULL, 
        FOREIGN KEY(nickname) REFERENCES leaderboard(nickname) ON DELETE CASCADE ON UPDATE CASCADE,
        UNIQUE(round, nickname)
    )
    ''')
    # winning_team in matches table indicates the team number (1 or 2) that won that specific round.

    cur.execute('''
    CREATE TABLE IF NOT EXISTS aftercalc (
        ac_id INTEGER PRIMARY KEY AUTOINCREMENT,
        round INTEGER,
        nickname TEXT,
        total_kills_at_round INTEGER, -- Kills up to and including this round
        total_deaths_at_round INTEGER, -- Deaths up to and including this round
        kdr_at_round REAL,            -- Overall KDR after this round
        elo_after_round INTEGER,      -- ELO after this round
        FOREIGN KEY(nickname) REFERENCES leaderboard(nickname) ON DELETE CASCADE ON UPDATE CASCADE,
        UNIQUE (round, nickname)
    )
    ''')
    con.commit()

def alter_matches_table():
    """matches 테이블에 'winning_team' 및 'map' 열 추가 (이미 존재하면 무시)"""
    try:
        cur.execute("PRAGMA table_info(matches);")
        columns = [row[1] for row in cur.fetchall()]
        altered = False
        if "map" not in columns:
            cur.execute("ALTER TABLE matches ADD COLUMN map TEXT DEFAULT NULL")
            print("✅ 'map' 열이 matches 테이블에 추가되었습니다.")
            altered = True
        if "winning_team" not in columns: # Added this check as well
            cur.execute("ALTER TABLE matches ADD COLUMN winning_team INTEGER DEFAULT NULL")
            print("✅ 'winning_team' 열이 matches 테이블에 추가되었습니다.")
            altered = True
        
        if altered:
            con.commit()
        # else:
        #     print("ℹ️ matches 테이블 구조가 최신입니다.")

    except sqlite3.OperationalError as e:
        print(f"⚠ 테이블 변경 중 오류 발생: {e}")
    
def get_round_number():
    """라운드 번호를 결정하는 함수 (이전 라운드 확인 및 선택)"""
    cur.execute('SELECT MAX(round) FROM matches')
    latest_round = cur.fetchone()[0]

    if latest_round is None:
        print("⚠ 현재 라운드 데이터가 없습니다. 이번 라운드는 첫 라운드가 됩니다.")
        return 1

    while True:
        user_choice = input(f"이전 데이터에 이어서 작성하시겠습니까? (최근 라운드: {latest_round}) [y/n]: ").strip().lower()
        if user_choice == 'y':
            new_round = latest_round + 1
            print(f"✅ 새로운 라운드는 {new_round}로 설정됩니다.")
            return new_round
        elif user_choice == 'n':
            while True:
                try:
                    round_number_input = int(input(">> 새로운 라운드 번호를 입력하세요: "))
                    if round_number_input <= latest_round:
                        print(f"⚠ 이전 라운드 번호 ({latest_round})보다 큰 숫자를 입력하세요.")
                    else:
                        return round_number_input
                except ValueError:
                    print("⚠ 잘못된 입력입니다. 숫자를 입력해 주세요.")
        else:
            print("⚠ 잘못된 선택입니다. 'y' 또는 'n'을 입력해 주세요.")
    
def export_match_results_to_csv():
    """매치 결과 데이터를 CSV로 저장 (승리 팀 포함)"""
    directory = "./exported_data"
    os.makedirs(directory, exist_ok=True)

    filename = os.path.join(directory, f"match_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    cur.execute('SELECT round, nickname, team, kills, deaths, map, winning_team FROM matches ORDER BY round, team, nickname')
    rows = cur.fetchall()

    if not rows:
        print("⚠ 매치 데이터가 없습니다. CSV로 저장할 내용이 없습니다.")
        return

    with open(filename, mode='w', newline='', encoding='utf-8-sig') as file: # utf-8-sig for Excel
        writer = csv.writer(file)
        writer.writerow(["Round", "Nickname", "Team", "Kills", "Deaths", "Map", "Winning Team"])
        writer.writerows(rows)

    print(f"✅ 매치 결과 데이터가 CSV로 저장되었습니다: {filename}")
    

def export_aftercalc_to_csv():
    """aftercalc 테이블에서 round, nickname, elo 데이터를 CSV로 저장"""
    directory = "./exported_data"
    os.makedirs(directory, exist_ok=True)

    filename = os.path.join(directory, f"aftercalc_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    try:
        cur.execute("SELECT round, nickname, total_kills_at_round, total_deaths_at_round, kdr_at_round, elo_after_round FROM aftercalc ORDER BY round, nickname")
        rows = cur.fetchall()

        if not rows:
            print("⚠ aftercalc 테이블에 데이터가 없습니다.")
            return

        with open(filename, mode='w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            writer.writerow(["Round", "Nickname", "Total Kills at Round", "Total Deaths at Round", "KDR at Round", "ELO After Round"])
            writer.writerows(rows)

        print(f"✅ aftercalc 데이터가 CSV로 저장되었습니다: {filename}")
    except sqlite3.Error as e:
        print(f"⚠ aftercalc 데이터를 추출하는 중 오류가 발생했습니다: {e}")
    
def export_leaderboard_to_csv(round_number_tag=None):
    """모든 데이터를 CSV로 저장"""
    directory = "./exported_data"
    os.makedirs(directory, exist_ok=True)

    tag_suffix = f"_{round_number_tag}" if round_number_tag else ""
    filename = os.path.join(directory, f"lboard{tag_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    
    cur.execute('SELECT nickname, kills, deaths, wins, losses, total, elo, tier FROM leaderboard ORDER BY elo DESC')
    rows = cur.fetchall()

    if not rows:
        print("⚠ 리더보드 데이터가 없습니다. CSV로 저장할 내용이 없습니다.")
        return

    leaderboard_with_rank = [(rank + 1, *row) for rank, row in enumerate(rows)]

    with open(filename, mode='w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(["Rank", "Nickname", "Kills", "Deaths", "Wins", "Losses", "Total Games", "ELO", "Tier"])
        writer.writerows(leaderboard_with_rank)

    print(f"✅ 리더보드 데이터가 CSV로 저장되었습니다: {filename}")

def export_leaderboard_to_spreadsheet():
    """시트용 리더보드 내보내기"""
    directory = "./exported_data"
    os.makedirs(directory, exist_ok=True)

    filename = os.path.join(directory, f"spreadsheet_leaderboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    cur.execute('SELECT nickname, kills, deaths, wins, losses, total, elo FROM leaderboard ORDER BY elo DESC')
    rows = cur.fetchall()

    if not rows:
        print("⚠ 리더보드 데이터가 없습니다. 스프레드시트로 내보낼 내용이 없습니다.")
        return

    spreadsheet_data = []
    for rank, (nickname, kills, deaths, wins, losses, total, elo) in enumerate(rows, start=1):
        kdr = round(kills / max(1, deaths), 2)
        wr = round((wins / max(1, total)) * 100) if total > 0 else 0
        spreadsheet_data.append([rank, nickname, kdr, wr, total, elo])

    with open(filename, mode='w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(["Rank", "Nickname", "KDR", "WR", "Total Games", "ELO"])
        writer.writerows(spreadsheet_data)

    print(f"✅ 스프레드시트용 리더보드 데이터가 저장되었습니다: {filename}")
    
def calculate_tier(elo):
    """ELO 점수에 따라 100점 단위로 티어 이름 반환"""
    base_elo = 1500
    tier_names = [
        "Copper 3", "Copper 2", "Copper 1",
        "Bronze 3", "Bronze 2", "Bronze 1",
        "Silver 3", "Silver 2", "Silver 1",
        "Gold 3", "Gold 2", "Gold 1",
        "Platinum 3", "Platinum 2", "Platinum 1",
        "Diamond 3", "Diamond 2", "Diamond 1",
        "Champion"
    ]
    # Gold 3 is index 9, corresponding to base_elo (1500-1599 range)
    tier_index = (elo - base_elo) // 100 + 9 
    tier_index = max(0, min(tier_index, len(tier_names) - 1))
    return tier_names[tier_index]

def calculate_elo(player_elo, opponent_avg_elo, result, kills, deaths, player_total_matches, player_wins, 
                  k_normal=30, kill_weight=0.2, death_weight=0.07, initial_k_factor=50, initial_matches_threshold=5):
    """ELO 점수 계산 (result: 1 for win, 0 for loss)"""
    
    # K-factor adjustment based on number of matches played
    if player_total_matches <= initial_matches_threshold:
        base_k = initial_k_factor
    else:
        # K-factor decays as more matches are played, adjust divisor for desired decay rate
        base_k = k_normal / (1 + (player_total_matches - initial_matches_threshold) / 20) 
        base_k = max(base_k, k_normal / 2) # Ensure K doesn't drop too low, e.g., half of normal K

    # Expected result (probability of winning against opponent_avg_elo)
    # Sensitivity: 200 means ELO difference of 200 gives ~0.76 win prob for higher ELO.
    # 400 (standard) means ELO diff of 400 gives ~0.91 win prob.
    expected_result = 1 / (1 + 10 ** ((opponent_avg_elo - player_elo) / 200)) 

    # ELO change from win/loss
    # Using custom formula from original script: win_loss_factor * (1.5 - expected_result)
    # win_loss_factor is 1 for win, -1 for loss. result is 1 for win, 0 for loss.
    # If result = 1 (win): 1 * (1.5 - expected_result)
    # If result = 0 (loss): -1 * (1.5 - expected_result)
    # This logic is preserved from original script.
    # A more standard ELO change would be: base_k * (result - expected_result)
    win_loss_numeric_factor = 1 if result == 1 else -1
    elo_change_match_outcome = base_k * win_loss_numeric_factor * (1.5 - expected_result)
    
    # Performance score (KDA bonus/penalty)
    # Ensure deaths is at least 1 for KDA calculation part to avoid division by zero if KDA was used directly
    # Here, it's weighted difference, so deaths=0 is fine.
    performance_score = (kills * kill_weight) - (deaths * death_weight)
    if result == 0:  # Loss
        performance_score *= 0.5  # Dampen performance impact on a loss

    new_elo = player_elo + elo_change_match_outcome + performance_score
    return max(0, int(round(new_elo))) # ELO non-negative, rounded

import plotly.graph_objects as go

def plot_trend_analysis(nickname):
    """유저의 라운드별 누적 KDR, 평균 KDR, ELO 변화량(0 중심), 원래 ELO를 포함한 그래프"""
    cur.execute('''
        SELECT round, total_kills_at_round, total_deaths_at_round, kdr_at_round, elo_after_round 
        FROM aftercalc 
        WHERE nickname=? ORDER BY round ASC
    ''', (nickname,))
    aftercalc_data = cur.fetchall()

    if not aftercalc_data:
        print(f"⚠ 유저 '{nickname}'의 aftercalc 데이터가 부족합니다.")
        return

    original_rounds = [row[0] for row in aftercalc_data]
    # total_kills_at_round and total_deaths_at_round are cumulative up to that round
    # To get per-match kills/deaths for average KDR calculation:
    match_kills = []
    match_deaths = []
    prev_total_k, prev_total_d = 0, 0
    for row in aftercalc_data:
        current_total_k, current_total_d = row[1], row[2]
        match_kills.append(current_total_k - prev_total_k)
        match_deaths.append(current_total_d - prev_total_d)
        prev_total_k, prev_total_d = current_total_k, current_total_d
    
    cumulative_kdrs = [row[3] for row in aftercalc_data] # This is overall KDR
    elos = [row[4] for row in aftercalc_data]
    
    continuous_rounds = list(range(1, len(original_rounds) + 1))

    # Average of per-match KDRs
    per_match_kdrs = [round(k / max(1, d), 2) for k, d in zip(match_kills, match_deaths)]
    average_of_match_kdrs = [round(sum(per_match_kdrs[:i+1]) / (i+1), 2) for i in range(len(per_match_kdrs))]


    # ELO 변화량 (change from previous round's ELO)
    elo_changes = [elos[0] - 1500] # Change from default ELO for the first game
    elo_changes.extend([elos[i] - elos[i - 1] for i in range(1, len(elos))])


    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=continuous_rounds, y=elo_changes, mode='lines+markers', name='ELO 변화량 (라운드별)',
        line=dict(color='purple'), marker=dict(size=8), yaxis='y2',
        hovertemplate='참여 경기 수: %{x}<br>ELO 변화량: %{y:+}<extra></extra>'
    ))
    fig.add_trace(go.Scatter(
        x=continuous_rounds, y=elos, mode='lines+markers', name='ELO (누적)',
        line=dict(color='green'), marker=dict(size=8), yaxis='y3',
        hovertemplate='참여 경기 수: %{x}<br>ELO: %{y}<extra></extra>'
    ))
    fig.add_trace(go.Scatter(
        x=continuous_rounds, y=cumulative_kdrs, mode='lines+markers', name='누적 KDR (전체)',
        line=dict(color='blue'), marker=dict(size=8),
        hovertemplate='참여 경기 수: %{x}<br>누적 KDR: %{y:.2f}<extra></extra>'
    ))
    fig.add_trace(go.Scatter(
        x=continuous_rounds, y=average_of_match_kdrs, mode='lines+markers', name='평균 KDR (라운드별 KDR의 평균)',
        line=dict(color='tomato', dash='dot'), marker=dict(size=8),
        hovertemplate='참여 경기 수: %{x}<br>평균 KDR: %{y:.2f}<extra></extra>'
    ))

    min_elo_val = min(elos) if elos else 1450
    max_elo_val = max(elos) if elos else 1550
    
    fig.update_layout(
        title=f"{nickname}의 트렌드 분석 (DB 라운드: {', '.join(map(str, original_rounds))})",
        xaxis=dict(title='참여 경기 수 (순서)', tickvals=continuous_rounds, ticktext=[str(r) for r in continuous_rounds]),
        yaxis=dict(title='KDR 값', showgrid=True),
        yaxis2=dict(title='ELO 변화량', overlaying='y', side='right', range=[-80, 80], zeroline=True, zerolinewidth=2, zerolinecolor='gray'),
        yaxis3=dict(title='ELO 값', overlaying='y', side='left', anchor='free', position=0.05, range=[min_elo_val - 50, max_elo_val + 50]),
        legend=dict(title="데이터 시리즈"),
        hovermode='x unified'
    )
    fig.show()
        
def plot_elo_scatter():
    """유저 데이터 산점도 출력"""
    cur.execute("SELECT nickname, elo, total, kills, deaths FROM leaderboard WHERE total > 0") # Only show players with games
    players = cur.fetchall()

    if not players:
        print("⚠ 리더보드 데이터가 없습니다. 산점도를 생성할 수 없습니다.")
        return  

    nicknames = [player[0] for player in players]
    elos = [player[1] for player in players]
    total_matches = [player[2] for player in players]
    kdrs = [round(player[3] / max(1, player[4]), 2) for player in players]

    # Normalize KDRs for color mapping, handle edge case of all KDRs being same
    min_kdr, max_kdr = min(kdrs), max(kdrs)
    if min_kdr == max_kdr:
        normalized_kdrs = [0.5] * len(kdrs) # All same color
    else:
        normalized_kdrs = [(kdr - min_kdr) / (max_kdr - min_kdr) for kdr in kdrs]
    
    cmap = plt.get_cmap("coolwarm")
    colors = [cmap(norm_kdr) for norm_kdr in normalized_kdrs]

    plt.figure(figsize=(14, 10))
    scatter = plt.scatter(elos, total_matches, c=colors, s=70, edgecolors="k", alpha=0.8)
    
    # Colorbar
    cbar = plt.colorbar(scatter, label="KDR", orientation="vertical")
    cbar.set_ticks([0, 0.5, 1]) # Min, Mid, Max
    cbar.set_ticklabels([f"{min_kdr:.2f}", f"{(min_kdr + max_kdr) / 2:.2f}", f"{max_kdr:.2f}"])


    plt.title("ELO vs Total Matches (색상: KDR)", fontsize=16)
    plt.xlabel("ELO", fontsize=12)
    plt.ylabel("Total Matches", fontsize=12)
    plt.grid(alpha=0.3)
    
    for i, nickname in enumerate(nicknames):
        plt.text(elos[i] + 5, total_matches[i], nickname, fontsize=7, ha="left") # Adjusted offset

    plt.tight_layout()
    plt.show()

def check_tier_change(nickname, old_elo, new_elo):
    """티어 변경 시 알림."""
    old_tier = calculate_tier(old_elo)
    new_tier = calculate_tier(new_elo)

    if old_tier != new_tier:
        print(f"🎉 {Fore.CYAN}{nickname}{Style.RESET_ALL}의 티어가 변경되었습니다: {Fore.YELLOW}{old_tier}{Style.RESET_ALL} → {Fore.GREEN}{new_tier}{Style.RESET_ALL}")

def check_achievement(nickname, kdr, wr, total_games):
    """특정 성취를 확인."""
    if total_games >= 10: # Only check for established players
        if kdr >= 2.0:
            print(f"🏆 {Fore.MAGENTA}{nickname}{Style.RESET_ALL}이(가) KDR {kdr:.2f} (2.0 이상)을 달성했습니다!")
        if wr >= 80:
            print(f"🔥 {Fore.MAGENTA}{nickname}{Style.RESET_ALL}이(가) 승률 {wr:.1f}% (80% 이상)을 달성했습니다!")

def update_player_stats(nickname, new_elo, wins, losses, total_matches, current_kills, current_deaths):
    """리더보드의 플레이어 통계 및 ELO 업데이트, 티어 변경 및 업적 확인"""
    cur.execute("SELECT elo FROM leaderboard WHERE nickname=?", (nickname,))
    res = cur.fetchone()
    old_elo = res[0] if res else 1500 # Default if somehow not found (should exist)

    tier = calculate_tier(new_elo)
    cur.execute(
        '''
        UPDATE leaderboard 
        SET elo=?, wins=?, losses=?, total=?, tier=?, kills=?, deaths=?
        WHERE nickname=?
        ''',
        (new_elo, wins, losses, total_matches, tier, current_kills, current_deaths, nickname)
    )
    # Achievements and tier changes check
    if total_matches > 0 : # Only check if there are games
        kdr = round(current_kills / max(1, current_deaths), 2)
        wr = round((wins / total_matches) * 100, 1)
        check_tier_change(nickname, old_elo, new_elo)
        check_achievement(nickname, kdr, wr, total_matches)


def update_team_elo(team1_data, team2_data, winning_team_num, round_num):
    """
    팀 ELO 업데이트 및 leaderboard 테이블의 ELO 기록.
    teamX_data is a list of (nickname, kills_in_match, deaths_in_match)
    winning_team_num is 1 or 2.
    Returns a list of tuples: (nickname, new_elo, kills_in_match, deaths_in_match) for aftercalc.
    """
    updated_elo_for_aftercalc = []

    # Fetch current ELOs and stats for all players involved from leaderboard
    # This ELO is their ELO *before* this match.
    player_current_stats = {}
    all_players_in_match = [p[0] for p in team1_data] + [p[0] for p in team2_data]
    for p_nick in all_players_in_match:
        cur.execute("SELECT elo, wins, losses, total, kills, deaths FROM leaderboard WHERE nickname=?", (p_nick,))
        # Default values if player is somehow not in leaderboard (should be added by insert_match_result)
        player_current_stats[p_nick] = cur.fetchone() or (1500, 0, 0, 0, 0, 0)

    # Calculate average ELO for each team based on their pre-match ELOs
    team1_avg_elo = sum(player_current_stats[p[0]][0] for p in team1_data) / len(team1_data) if team1_data else 1500
    team2_avg_elo = sum(player_current_stats[p[0]][0] for p in team2_data) / len(team2_data) if team2_data else 1500

    # Process Team 1
    for nickname, kills_match, deaths_match in team1_data:
        current_elo, wins, losses, total_games, total_kills, total_deaths = player_current_stats[nickname]
        result_for_player = 1 if winning_team_num == 1 else 0
        
        new_elo = calculate_elo(current_elo, team2_avg_elo, result_for_player, kills_match, deaths_match, total_games, wins)
        
        wins += result_for_player
        losses += (1 - result_for_player)
        total_games += 1
        # Kills/Deaths for leaderboard are updated by insert_match_result initially,
        # and then by update_leaderboard_kills_deaths during edits/deletions.
        # Here, we pass the existing total_kills, total_deaths as they are aggregates.
        # The specific match K/D are handled by insert_match_result adding to these totals.
        # Or, if recalculating, these totals are also recalculated summatively.
        # For clarity, let `update_player_stats` handle K/D too. It expects current totals.
        # `insert_match_result` already updates K/D. This might be redundant if not careful.
        # Let `update_player_stats` handle the `leaderboard` update.
        update_player_stats(nickname, new_elo, wins, losses, total_games, total_kills + kills_match, total_deaths + deaths_match)
        updated_elo_for_aftercalc.append((nickname, new_elo, kills_match, deaths_match))

    # Process Team 2
    for nickname, kills_match, deaths_match in team2_data:
        current_elo, wins, losses, total_games, total_kills, total_deaths = player_current_stats[nickname]
        result_for_player = 1 if winning_team_num == 2 else 0

        new_elo = calculate_elo(current_elo, team1_avg_elo, result_for_player, kills_match, deaths_match, total_games, wins)
        
        wins += result_for_player
        losses += (1 - result_for_player)
        total_games += 1
        update_player_stats(nickname, new_elo, wins, losses, total_games, total_kills + kills_match, total_deaths + deaths_match)
        updated_elo_for_aftercalc.append((nickname, new_elo, kills_match, deaths_match))
    
    con.commit()
    return updated_elo_for_aftercalc
    
def get_tier_distribution():
    """리더보드에서 티어별 유저 분포를 가져옵니다."""
    cur.execute('SELECT tier, COUNT(*) as count FROM leaderboard WHERE total > 5 GROUP BY tier ORDER BY tier') # Only ranked players
    data = cur.fetchall()

    if not data:
        print("⚠ 리더보드에 랭크된 유저(6판 이상) 데이터가 없습니다.")
        return None

    tiers, counts = zip(*data)
    return tiers, counts

def plot_tier_distribution():
    """티어별 유저 분포를 정렬된 순서와 색상으로 시각화"""
    tier_order = [
        "Copper 3", "Copper 2", "Copper 1", "Bronze 3", "Bronze 2", "Bronze 1",
        "Silver 3", "Silver 2", "Silver 1", "Gold 3", "Gold 2", "Gold 1",
        "Platinum 3", "Platinum 2", "Platinum 1", "Diamond 3", "Diamond 2", "Diamond 1",
        "Champion"
    ]
    tier_colors_map = {
        "Copper": "saddlebrown", "Bronze": "rosybrown", "Silver": "silver", "Gold": "gold",
        "Platinum": "deepskyblue", "Diamond": "mediumpurple", "Champion": "crimson"
    }

    data = get_tier_distribution()
    if not data: return

    tiers_from_db, counts_from_db = data
    tier_dict = dict(zip(tiers_from_db, counts_from_db))
    
    # Filter tier_order to only include tiers present in the data or ensure all are plotted
    plot_tiers = [t for t in tier_order if tier_dict.get(t, 0) > 0] # Only plot tiers with users
    if not plot_tiers: # If all counts are 0 for some reason for standard tiers
        print("⚠ 모든 티어의 유저 수가 0입니다. 분포도를 그릴 수 없습니다.")
        return
        
    plot_counts = [tier_dict.get(t, 0) for t in plot_tiers]
    plot_colors = [tier_colors_map[t.split()[0]] for t in plot_tiers]

    plt.figure(figsize=(12, 7))
    bars = plt.bar(plot_tiers, plot_counts, color=plot_colors, edgecolor="black")
    plt.title("티어별 유저 분포 (6판 이상 플레이어)", fontsize=16)
    plt.xlabel("티어", fontsize=12)
    plt.ylabel("유저 수", fontsize=12)
    plt.xticks(rotation=45, ha="right")
    plt.grid(axis='y', linestyle="--", alpha=0.7)
    
    for bar in bars:
        yval = bar.get_height()
        if yval > 0:
            plt.text(bar.get_x() + bar.get_width()/2.0, yval + 0.05, int(yval), ha='center', va='bottom')

    plt.tight_layout()
    plt.show()
        
def balance_teams_prompt():
    """팀 밸런스 구성"""
    print(">> 팀 밸런스를 위한 닉네임을 입력하세요 (띄어쓰기로 구분):")
    nicknames_input = input("> 닉네임들: ").strip()
    if not nicknames_input:
        print("⚠ 닉네임을 입력해주세요.")
        return
    nicknames = nicknames_input.split()
    balance_teams(nicknames)


def balance_teams(nicknames):
    """주어진 닉네임 목록을 바탕으로 팀 밸런스 추천."""
    players = []
    for nickname in nicknames:
        cur.execute("SELECT nickname, elo FROM leaderboard WHERE nickname=?", (nickname,))
        result = cur.fetchone()
        players.append(result if result else (nickname, 1500)) # Default ELO if not found

    players.sort(key=lambda x: x[1], reverse=True) # Sort by ELO descending

    team1, team2 = [], []
    elo_team1, elo_team2 = 0, 0

    # Snake draft for balancing
    for i, player in enumerate(players):
        if i % 2 == 0: # 0, 2, 4...
            if len(team1) <= len(team2) : # Try to keep team sizes even first
                 team1.append(player)
                 elo_team1 += player[1]
            else: # if team1 is larger (e.g. odd number of players, last one goes to smaller team)
                 team2.append(player)
                 elo_team2 += player[1]
        else: # 1, 3, 5...
            if len(team2) <= len(team1):
                team2.append(player)
                elo_team2 += player[1]
            else:
                team1.append(player)
                elo_team1 += player[1]
    
    avg_elo1 = elo_team1 / len(team1) if team1 else 0
    avg_elo2 = elo_team2 / len(team2) if team2 else 0

    print(Fore.CYAN + ">> 추천 팀 구성:" + Style.RESET_ALL)
    print(f"   팀 1 (평균 ELO: {avg_elo1:.0f}): {', '.join([f'{p[0]} ({p[1]})' for p in team1])}")
    print(f"   팀 2 (평균 ELO: {avg_elo2:.0f}): {', '.join([f'{p[0]} ({p[1]})' for p in team2])}")
    predict_winrate([p[0] for p in team1], [p[0] for p in team2])


def update_aftercalc_table(round_number, elo_data_for_round):
    """
    매치별 데이터를 기반으로 aftercalc 테이블 업데이트.
    elo_data_for_round is list of (nickname, elo_after_this_round, kills_in_this_round, deaths_in_this_round)
    """
    try:
        for nickname, new_elo, kills_this_round, deaths_this_round in elo_data_for_round:
            # Get cumulative kills/deaths *before* this round for this player
            cur.execute('''
                SELECT total_kills_at_round, total_deaths_at_round 
                FROM aftercalc 
                WHERE nickname=? AND round < ? 
                ORDER BY round DESC LIMIT 1
            ''', (nickname, round_number))
            prev_cumulative_data = cur.fetchone()

            prev_total_kills = prev_cumulative_data[0] if prev_cumulative_data else 0
            prev_total_deaths = prev_cumulative_data[1] if prev_cumulative_data else 0

            # New cumulative totals *after* this round
            current_total_kills = prev_total_kills + kills_this_round
            current_total_deaths = prev_total_deaths + deaths_this_round
            
            current_kdr = round(current_total_kills / max(1, current_total_deaths), 2)

            cur.execute('''
            INSERT OR REPLACE INTO aftercalc 
                (round, nickname, total_kills_at_round, total_deaths_at_round, kdr_at_round, elo_after_round)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (round_number, nickname, current_total_kills, current_total_deaths, current_kdr, new_elo))
        con.commit()
    except sqlite3.Error as e:
        print(f"⚠ aftercalc 테이블 업데이트 중 오류 발생 (라운드 {round_number}): {e}")


def predict_winrate(team1_nicks, team2_nicks):
    """두 팀의 닉네임 목록을 바탕으로 승률 예측."""
    def get_avg_team_elo(nicks_list):
        if not nicks_list: return 1500
        total_elo = 0
        actual_players = 0
        for nick in nicks_list:
            cur.execute("SELECT elo FROM leaderboard WHERE nickname=?", (nick,))
            res = cur.fetchone()
            if res:
                total_elo += res[0]
                actual_players +=1
            else: # Should not happen if players are added correctly
                print(f"⚠ '{nick}'을 리더보드에서 찾을 수 없습니다. 기본 ELO 1500으로 가정합니다.")
                total_elo += 1500 
                actual_players +=1
        return total_elo / actual_players if actual_players > 0 else 1500

    team1_avg_elo = get_avg_team_elo(team1_nicks)
    team2_avg_elo = get_avg_team_elo(team2_nicks)

    # Standard ELO win probability formula
    prob_team1_wins = 1 / (1 + 10 ** ((team2_avg_elo - team1_avg_elo) / 400)) # Using 400 for prediction sensitivity
    
    print(Fore.GREEN + ">> 예상 승률:" + Style.RESET_ALL)
    print(f"   1팀 ({', '.join(team1_nicks) if team1_nicks else 'N/A'}): {prob_team1_wins*100:.2f}% (평균 ELO: {team1_avg_elo:.0f})")
    print(f"   2팀 ({', '.join(team2_nicks) if team2_nicks else 'N/A'}): {(1-prob_team1_wins)*100:.2f}% (평균 ELO: {team2_avg_elo:.0f})")


def reset_leaderboard():
    """리더보드와 매치 데이터를 초기화"""
    confirm = input(Fore.RED + "⚠ 경고: 모든 리더보드, 매치, ELO 기록 데이터가 삭제됩니다. 계속하시겠습니까? (yes/no): " + Style.RESET_ALL).strip().lower()
    if confirm == "yes":
        cur.execute('DELETE FROM leaderboard')
        cur.execute('DELETE FROM matches')
        cur.execute('DELETE FROM aftercalc')
        con.commit()
        
        # VACUUM in a separate connection context as recommended
        # though for file-based DBs, it might not be strictly necessary to close and reopen.
        # For safety and to release locks if any:
        con.close()
        temp_con = sqlite3.connect(DB_PATH)
        temp_con.execute('VACUUM')
        temp_con.commit()
        temp_con.close()
        # Re-establish main connection
        globals()['con'] = sqlite3.connect(DB_PATH)
        globals()['cur'] = globals()['con'].cursor()
        
        print(Fore.GREEN + "✅ 데이터베이스가 성공적으로 초기화되었습니다." + Style.RESET_ALL)
        initialize_tables() # Recreate tables if they were somehow dropped by a manual operation, though DELETE doesn't drop.
    else:
        print(Fore.YELLOW + "⚠ 초기화가 취소되었습니다." + Style.RESET_ALL)

def display_user_statistics():
    """입력된 유저 리더보드 출력"""
    nicknames_input = input(">> 통계를 확인할 닉네임(띄어쓰기로 구분, 전부 보려면 'all'): ").strip()
    
    if not nicknames_input:
        print("⚠ 닉네임을 입력해주세요.")
        return

    query_nicknames = nicknames_input.split()
    
    data_to_display = []
    placeholders = ','.join('?' * len(query_nicknames))

    if "all" in query_nicknames or "All" in query_nicknames or "ALL" in query_nicknames :
         cur.execute("SELECT nickname, kills, deaths, wins, losses, total, elo, tier FROM leaderboard ORDER BY elo DESC")
    else:
        cur.execute(f"SELECT nickname, kills, deaths, wins, losses, total, elo, tier FROM leaderboard WHERE nickname IN ({placeholders}) ORDER BY elo DESC", query_nicknames)
    
    results = cur.fetchall()

    if not results:
        print(f"⚠ 입력된 닉네임에 대한 데이터를 찾을 수 없습니다: {', '.join(query_nicknames)}")
        return

    for nickname, kills, deaths, wins, losses, total, elo, tier in results:
        kdr = round(kills / max(1, deaths), 2)
        win_rate = round((wins / max(1, total)) * 100, 1) if total > 0 else 0.0
        kills_per_match = round(kills / max(1, total), 1) if total > 0 else 0.0
        data_to_display.append([nickname, kills, deaths, kdr, wins, losses, win_rate, kills_per_match, elo, tier if total > 5 else "Unranked"])

    if not data_to_display:
        print("⚠ 통계를 출력할 유저 데이터가 없습니다.")
        return

    # No need to sort again if 'all' as query already sorts by ELO
    # if "all" not in query_nicknames:
    # data_to_display.sort(key=lambda x: x[-2], reverse=True) # Sort by ELO

    headers = ["Nickname", "K", "D", "KDR", "W", "L", "WR%", "KPR", "ELO", "Tier"]
    print(tabulate(data_to_display, headers=headers, tablefmt="pretty"))


def insert_match_result(round_number, team_num, nickname, kills, deaths, map_name, winning_team_for_round):
    """매치 결과를 데이터베이스에 삽입. winning_team_for_round is for the whole round."""
    try:
        # Add player to leaderboard if not exists, or update K/D if they do
        # Note: ELO, Wins, Losses, Total, Tier are updated by update_team_elo
        cur.execute("SELECT id, kills, deaths FROM leaderboard WHERE nickname=?", (nickname,))
        player_record = cur.fetchone()
        if not player_record:
            cur.execute(
                "INSERT INTO leaderboard (nickname, kills, deaths, elo, tier) VALUES (?, ?, ?, ?, ?)",
                (nickname, kills, deaths, 1500, calculate_tier(1500)) # Initial K/D, rest default or calculated
            )
        else:
            # This K/D update might be contentious if update_team_elo also does it.
            # Let's ensure K/D in leaderboard is a sum from all matches.
            # The definitive K/D update will happen in update_leaderboard_based_on_all_matches
            # or summatively in update_team_elo. For now, this simply ensures match K/D is added.
            # This will be overwritten by recalculate_elo_and_aftercalc_from_round.
            # This is complex. Simpler: leaderboard K/D is ONLY updated by a master sum.
            # Let's assume insert_match_result does NOT update leaderboard K/D directly.
            # update_team_elo will handle the summation for the current match.
            pass # Leaderboard K/D update handled by update_team_elo

        # Insert match details
        cur.execute(
            '''
            INSERT OR IGNORE INTO matches (round, nickname, team, kills, deaths, map, winning_team) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (round_number, nickname, team_num, kills, deaths, map_name, winning_team_for_round)
        )
        con.commit()
    except sqlite3.IntegrityError:
         print(f"⚠ 라운드 {round_number}의 '{nickname}' 데이터가 이미 존재하거나 다른 제약 조건 위반. 건너뜁니다.")
    except sqlite3.Error as e: 
        print(f"⚠ {nickname} 데이터 삽입 중 오류 발생: {e}")
            
def print_leaderboard():
    """터미널에 리더보드 출력"""
    # Recalculate all summary stats in leaderboard from matches table to ensure consistency
    # This is a heavy operation to do every time print_leaderboard is called.
    # Ideally, leaderboard is kept consistent by other operations.
    # For now, let's trust leaderboard is mostly up-to-date.

    cur.execute('SELECT nickname, kills, deaths, wins, losses, total, elo, tier FROM leaderboard ORDER BY elo DESC')
    rows = cur.fetchall()

    if not rows:
        print("⚠ 리더보드가 비어 있습니다.")
        return

    ranked_data, unranked_data = [], []
    # For calculating averages of ranked players
    avg_stats = {'kills': 0, 'deaths': 0, 'kdr': 0, 'wins': 0, 'losses': 0, 'wr': 0, 'kpr': 0, 'elo': 0, 'count': 0}

    for nick, k, d, w, l, total_games, elo, tier_str in rows:
        if total_games == 0: continue # Skip players with no games

        kdr = round(k / max(1, d), 2)
        wr = round((w / total_games) * 100, 1) if total_games > 0 else 0.0
        kpr = round(k / total_games, 1) if total_games > 0 else 0.0
        
        display_tier = tier_str
        if total_games <= 5: # Placement matches
            display_tier = Fore.YELLOW + "배치중" + Style.RESET_ALL + f" ({total_games}/5)"
            unranked_data.append([nick, k, d, kdr, w, l, wr, kpr, elo if total_games == 5 else "???", display_tier])
        else:
            ranked_data.append([nick, k, d, kdr, w, l, wr, kpr, elo, display_tier])
            avg_stats['kills'] += k
            avg_stats['deaths'] += d
            avg_stats['kdr'] += kdr
            avg_stats['wins'] += w
            avg_stats['losses'] += l
            avg_stats['wr'] += wr
            avg_stats['kpr'] += kpr
            avg_stats['elo'] += elo
            avg_stats['count'] += 1
            
    # Sort unranked by ELO as well, or by games played
    unranked_data.sort(key=lambda x: x[-2] if isinstance(x[-2], int) else -1, reverse=True) # Sort by ELO if available

    headers = ["닉네임", "킬", "데스", "KDR", "승", "패", "승률%", "판당킬", "ELO", "티어"]
    
    print(Fore.GREEN + "\n--- 리더보드 (랭크) ---" + Style.RESET_ALL)
    if ranked_data:
        print(tabulate(ranked_data, headers=headers, tablefmt="pretty"))
    else:
        print("랭크된 플레이어가 없습니다 (6판 이상).")

    if avg_stats['count'] > 0:
        avg_row = [
            Fore.CYAN+"평균"+Style.RESET_ALL,
            f"{avg_stats['kills']/avg_stats['count']:.1f}", f"{avg_stats['deaths']/avg_stats['count']:.1f}",
            f"{avg_stats['kdr']/avg_stats['count']:.2f}", f"{avg_stats['wins']/avg_stats['count']:.1f}",
            f"{avg_stats['losses']/avg_stats['count']:.1f}", f"{avg_stats['wr']/avg_stats['count']:.1f}",
            f"{avg_stats['kpr']/avg_stats['count']:.1f}", f"{avg_stats['elo']/avg_stats['count']:.0f}", "N/A"
        ]
        print(tabulate([avg_row], tablefmt="pretty"))


    if unranked_data:
        print(Fore.YELLOW + "\n--- 리더보드 (배치중) ---" + Style.RESET_ALL)
        print(tabulate(unranked_data, headers=headers, tablefmt="pretty"))
    
    print("-" * 80)


def update_leaderboard_player_summary(nickname):
    """특정 플레이어의 leaderboard 테이블 K/D/W/L/Total을 matches 기록 기준으로 재계산합니다."""
    cur.execute("SELECT SUM(kills), SUM(deaths) FROM matches WHERE nickname=?", (nickname,))
    kd_res = cur.fetchone()
    total_kills = kd_res[0] or 0
    total_deaths = kd_res[1] or 0

    # Wins and Losses need to be counted carefully from matches
    # A player wins if their team is the winning_team for that round
    cur.execute("""
        SELECT m.team, m.winning_team 
        FROM matches m
        WHERE m.nickname = ?
    """, (nickname,))
    player_matches_results = cur.fetchall()

    wins = 0
    losses = 0
    for team, winning_team_for_round in player_matches_results:
        if team == winning_team_for_round:
            wins += 1
        else:
            losses += 1
    
    total_games = len(player_matches_results)

    cur.execute("""
        UPDATE leaderboard 
        SET kills=?, deaths=?, wins=?, losses=?, total=?
        WHERE nickname=?
    """, (total_kills, total_deaths, wins, losses, total_games, nickname))
    con.commit()
    # print(f"✅ {nickname}의 리더보드 요약 정보가 업데이트되었습니다.")


def recalculate_elo_and_aftercalc_from_round(start_round_num):
    """
    지정된 라운드부터 ELO 및 aftercalc 기록을 다시 계산합니다.
    leaderboard 테이블은 이 과정에서 각 라운드 후의 최신 ELO로 계속 업데이트됩니다.
    """
    print(f"🔄 지정된 라운드 {start_round_num}부터 ELO 및 경기 기록 재계산을 시작합니다...")

    # 1. ELO를 start_round_num 이전 상태로 되돌립니다.
    # 모든 플레이어의 ELO를 start_round_num-1 시점의 aftercalc 값으로 설정하거나,
    # start_round_num이 1이면 1500으로 초기화합니다.
    cur.execute("SELECT DISTINCT nickname FROM matches WHERE round >= ?", (start_round_num,))
    all_involved_nicknames = [row[0] for row in cur.fetchall()]

    for nick in all_involved_nicknames:
        if start_round_num == 1:
            # Reset K/D/W/L/Total as well, as we are recalculating from scratch for this player
            cur.execute("UPDATE leaderboard SET elo=?, kills=0, deaths=0, wins=0, losses=0, total=0, tier=? WHERE nickname=?", 
                        (1500, calculate_tier(1500), nick))
        else:
            # Get ELO from aftercalc at round (start_round_num - 1)
            cur.execute("""
                SELECT elo_after_round, total_kills_at_round, total_deaths_at_round 
                FROM aftercalc 
                WHERE nickname=? AND round=?
            """, (nick, start_round_num - 1))
            prev_ac_data = cur.fetchone()
            if prev_ac_data:
                # Also need to update W/L/Total in leaderboard to match this state
                # This requires summing wins/losses from matches up to start_round_num - 1
                update_leaderboard_player_summary(nick) # This sums all matches, then ELO would be taken from prev_ac_data
                cur.execute("UPDATE leaderboard SET elo=?, tier=? WHERE nickname=?", 
                            (prev_ac_data[0], calculate_tier(prev_ac_data[0]), nick))

            else: # No record in aftercalc before this round, assume new player or reset
                cur.execute("UPDATE leaderboard SET elo=?, kills=0, deaths=0, wins=0, losses=0, total=0, tier=? WHERE nickname=?", 
                            (1500, calculate_tier(1500), nick))
        # Delete potentially outdated aftercalc entries from start_round_num onwards for this player
        cur.execute("DELETE FROM aftercalc WHERE nickname=? AND round >= ?", (nick, start_round_num))
    con.commit()


    # 2. start_round_num부터 마지막 라운드까지 순차적으로 재계산
    cur.execute("SELECT MAX(round) FROM matches")
    max_round = cur.fetchone()[0]
    if max_round is None or max_round < start_round_num:
        print("ℹ️ 재계산할 라운드가 없습니다.")
        # Ensure leaderboard reflects correct totals if only future rounds were deleted
        for nick in all_involved_nicknames: update_leaderboard_player_summary(nick)
        return

    for current_r_num in range(start_round_num, max_round + 1):
        print(f"🔄 라운드 {current_r_num} 재계산 중...")
        cur.execute("SELECT nickname, team, kills, deaths, map, winning_team FROM matches WHERE round=?", (current_r_num,))
        match_entries = cur.fetchall()
        if not match_entries:
            print(f"Warning: 라운드 {current_r_num}에 매치 데이터가 없습니다. 건너뜁니다.")
            continue

        # Assuming winning_team is consistent for all entries in a round, take from first.
        # And map name.
        round_winning_team = match_entries[0][5]
        # round_map = match_entries[0][4] # map can be used if needed by other functions

        team1_data_for_recalc = [] # list of (nickname, kills, deaths)
        team2_data_for_recalc = []

        for m_nick, m_team, m_kills, m_deaths, _, _ in match_entries:
            if m_team == 1:
                team1_data_for_recalc.append((m_nick, m_kills, m_deaths))
            elif m_team == 2:
                team2_data_for_recalc.append((m_nick, m_kills, m_deaths))
        
        if not team1_data_for_recalc and not team2_data_for_recalc:
             print(f"Warning: 라운드 {current_r_num}에 팀 데이터가 없습니다. 건너뜁니다.")
             continue

        # update_team_elo uses leaderboard ELOs as pre-match ELOs.
        # Leaderboard is updated iteratively, so it's correct for current_r_num.
        # It also updates leaderboard K/D/W/L/Total by adding current match stats.
        updated_elo_info_for_ac = update_team_elo(team1_data_for_recalc, team2_data_for_recalc, round_winning_team, current_r_num)
        
        # update_aftercalc_table uses this info and previous aftercalc state to build new aftercalc entry.
        update_aftercalc_table(current_r_num, updated_elo_info_for_ac)
    
    print(Fore.GREEN + "✅ ELO 및 경기 기록 재계산이 완료되었습니다." + Style.RESET_ALL)
    # Final summary update for all players involved to be absolutely sure.
    cur.execute("SELECT DISTINCT nickname FROM leaderboard")
    all_lb_nicknames = [row[0] for row in cur.fetchall()]
    for nick in all_lb_nicknames:
        update_leaderboard_player_summary(nick) # This syncs K/D/W/L/Total from matches table.
                                                # ELO and Tier remain as per last recalc.


def delete_match_result(round_number, nickname):
    """특정 매치 데이터를 삭제하고, 해당 플레이어의 leaderboard 요약을 업데이트한 후, ELO 재계산을 트리거합니다."""
    cur.execute("SELECT * FROM matches WHERE round=? AND nickname=?", (round_number, nickname))
    match_to_delete = cur.fetchone()

    if not match_to_delete:
        print(f"⚠ 라운드 {round_number}의 {nickname} 데이터를 찾을 수 없습니다.")
        return

    confirm = input(f"❓ {nickname}의 라운드 {round_number} 데이터를 삭제하시겠습니까? 이 작업은 ELO 재계산을 유발합니다. (y/n): ").strip().lower()
    if confirm != 'y':
        print("⛔ 삭제가 취소되었습니다.")
        return

    # Delete from matches and aftercalc
    cur.execute('DELETE FROM matches WHERE round=? AND nickname=?', (round_number, nickname))
    cur.execute('DELETE FROM aftercalc WHERE round=? AND nickname=?', (round_number, nickname)) # Clean current player's specific entry
    con.commit()
    print(f"✅ {nickname}의 라운드 {round_number} 매치 기록이 삭제되었습니다.")
    
    # Update this specific player's summary stats (K/D/W/L/Total) in leaderboard based on remaining matches
    update_leaderboard_player_summary(nickname)
    
    # Trigger recalculation from the affected round onwards
    # This will re-evaluate ELOs for all players from this round forward based on the new state of 'matches'
    recalculate_elo_and_aftercalc_from_round(round_number)
    print(f"✅ 라운드 {round_number}부터 ELO 재계산이 완료되었습니다.")


def import_matches_from_csv(file_name_param):
    """CSV 파일로 매치 데이터 불러오기"""
    file_name = file_name_param.strip('\'"')
    file_path = os.path.normpath(os.path.join(os.getcwd(), file_name)) # Normalize path

    if not os.path.exists(file_path):
        print(f"⚠ 파일 '{file_path}'이(가) 존재하지 않습니다.")
        return

    # Determine the starting round for ELO recalculation:
    # It should be the minimum round number present in the CSV.
    min_round_in_csv = float('inf')
    
    # First pass to find min_round_in_csv and validate structure
    temp_matches_to_insert = []
    try:
        with open(file_path, mode='r', newline='', encoding='utf-8-sig') as file: # Use utf-8-sig
            reader = csv.reader(file)
            headers = next(reader)
            expected_headers_min = ["Round", "Nickname", "Team", "Kills", "Deaths", "Winning Team"]
            # Check if all required headers are present
            if not all(h in headers for h in expected_headers_min):
                print(f"⚠ CSV 파일 헤더가 올바르지 않습니다. 필수 헤더: {', '.join(expected_headers_min)}")
                print(f"   찾은 헤더: {', '.join(headers)}")
                return

            has_map_col = "Map" in headers
            
            for i, row in enumerate(reader, 1):
                try:
                    map_name = None
                    if has_map_col:
                        # Ensure correct unpacking based on actual columns in CSV
                        # Find indices of required columns
                        round_idx = headers.index("Round")
                        nick_idx = headers.index("Nickname")
                        team_idx = headers.index("Team")
                        kills_idx = headers.index("Kills")
                        deaths_idx = headers.index("Deaths")
                        win_idx = headers.index("Winning Team")
                        map_idx = headers.index("Map")

                        round_val = int(row[round_idx])
                        nick_val = row[nick_idx].strip()
                        team_val = int(row[team_idx])
                        kills_val = int(row[kills_idx])
                        deaths_val = int(row[deaths_idx])
                        winning_team_val = int(row[win_idx])
                        map_name = row[map_idx].strip() if row[map_idx] else None
                    else: # No map column
                        round_val, nick_val_raw, team_val_raw, kills_val_raw, deaths_val_raw, winning_team_val_raw = row[:6]
                        round_val = int(round_val)
                        nick_val = nick_val_raw.strip()
                        team_val, kills_val, deaths_val, winning_team_val = map(int, [team_val_raw, kills_val_raw, deaths_val_raw, winning_team_val_raw])

                    min_round_in_csv = min(min_round_in_csv, round_val)
                    temp_matches_to_insert.append((round_val, nick_val, team_val, kills_val, deaths_val, map_name, winning_team_val))
                except (ValueError, IndexError) as e:
                    print(f"⚠ CSV 파일의 {i+1}번째 줄 처리 중 오류 (데이터 형식 또는 누락된 열): {row} - {e}")
                    return # Stop import on error
    except Exception as e:
        print(f"⚠ CSV 파일 읽기 중 오류: {e}")
        return

    if min_round_in_csv == float('inf'):
        print("⚠ CSV 파일에 데이터가 없거나 라운드 번호를 읽을 수 없습니다.")
        return

    # Insert data into matches table (INSERT OR REPLACE to overwrite if exists for that round/player)
    # This is crucial if re-importing data.
    for r_num, nick, team, kills, deaths, map_name, winning_team in temp_matches_to_insert:
        # Add player to leaderboard if not exists
        cur.execute("INSERT OR IGNORE INTO leaderboard (nickname) VALUES (?)", (nick,))
        
        cur.execute("""
            INSERT OR REPLACE INTO matches (round, nickname, team, kills, deaths, map, winning_team)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (r_num, nick, team, kills, deaths, map_name, winning_team))
    con.commit()
    
    print(f"✅ CSV에서 {len(temp_matches_to_insert)}개의 매치 기록을 matches 테이블에 삽입/업데이트했습니다.")
    
    # Recalculate ELO from the earliest round found in the CSV
    recalculate_elo_and_aftercalc_from_round(min_round_in_csv)
    
    print(Fore.GREEN + "✅ CSV 데이터 가져오기 및 ELO 재계산이 완료되었습니다." + Style.RESET_ALL)


def handle_winning_team_input_and_process_round(team1_player_data, team2_player_data, current_round_num, current_map_name):
    """승리 팀을 입력받고 해당 라운드 처리. teamX_player_data: list of (nick, kills, deaths)"""
    if not team1_player_data and not team2_player_data:
        print("⚠ 양 팀 모두 플레이어가 없어 라운드를 처리할 수 없습니다.")
        return

    while True:
        try:
            winning_team_choice = int(input(f">> 라운드 {current_round_num}의 승리 팀을 입력하세요 (1 또는 2, 무승부/취소는 0): "))
            if winning_team_choice not in [0, 1, 2]:
                raise ValueError("승리 팀은 1, 2 또는 0이어야 합니다.")
            break
        except ValueError as e:
            print(f"⚠ 잘못된 입력입니다. {e}")

    if winning_team_choice == 0:
        print(f"ℹ️ 라운드 {current_round_num}은 무승부 또는 취소로 처리되어 ELO 변경이 없습니다.")
        # Insert match records with winning_team = 0 (or NULL if preferred for draw)
        for nick, k, d in team1_player_data:
            insert_match_result(current_round_num, 1, nick, k, d, current_map_name, 0)
        for nick, k, d in team2_player_data:
            insert_match_result(current_round_num, 2, nick, k, d, current_map_name, 0)
        con.commit()
        print_leaderboard() # Show updated K/D counts
        return

    # Insert individual match results for all players with the determined winning team
    for nick, k, d in team1_player_data:
        insert_match_result(current_round_num, 1, nick, k, d, current_map_name, winning_team_choice)
    for nick, k, d in team2_player_data:
        insert_match_result(current_round_num, 2, nick, k, d, current_map_name, winning_team_choice)
    
    # Update ELOs for the round
    # update_team_elo will use leaderboard ELOs (pre-this-round state) and update them.
    updated_elo_data = update_team_elo(team1_player_data, team2_player_data, winning_team_choice, current_round_num)
    
    # Update aftercalc table for this round
    update_aftercalc_table(current_round_num, updated_elo_data)
    
    print(Fore.GREEN + f"✅ 라운드 {current_round_num} 데이터 처리 및 ELO 업데이트 완료." + Style.RESET_ALL)
    print_leaderboard()


def handle_exit():
    """Exit 명령을 처리하여 프로그램 종료"""
    print(Fore.RED + ">> 프로그램을 종료합니다." + Style.RESET_ALL)
    con.close()
    exit()

def handle_editing():
    """데이터 수정 (매치 K/D) 후 ELO 재계산"""
    print(">> 수정할 라운드와 닉네임을 입력하세요 (예: 1 Yusi0). 'b' 입력 시 메인 메뉴로 돌아갑니다.")
    user_input = input(">> : ").strip()
    if user_input.lower() == "b":
        return

    try:
        round_num_str, nickname_edit = user_input.split()
        round_to_edit = int(round_num_str)
    except ValueError:
        print("⚠ 잘못된 형식입니다. '라운드번호 닉네임' 형식으로 입력하세요.")
        return

    cur.execute("SELECT kills, deaths, team FROM matches WHERE round=? AND nickname=?", (round_to_edit, nickname_edit))
    match_data = cur.fetchone()

    if not match_data:
        print(f"⚠ 라운드 {round_to_edit}의 {nickname_edit} 데이터를 찾을 수 없습니다.")
        return

    current_kills, current_deaths, team_of_player = match_data
    print(f">> {nickname_edit} (팀 {team_of_player}) - 현재 킬: {current_kills}, 데스: {current_deaths}")
    
    try:
        new_kills_str, new_deaths_str = input(">> 새로운 킬과 데스를 입력하세요 (예: 15 5): ").split()
        new_kills = int(new_kills_str)
        new_deaths = int(new_deaths_str)
        if new_kills < 0 or new_deaths < 0:
            raise ValueError("킬/데스는 음수일 수 없습니다.")
    except ValueError as e:
        print(f"⚠ 잘못된 입력입니다: {e}")
        return

    # Update the specific match entry
    cur.execute("UPDATE matches SET kills=?, deaths=? WHERE round=? AND nickname=?", 
                (new_kills, new_deaths, round_to_edit, nickname_edit))
    con.commit()
    print(f"✅ {nickname_edit}의 라운드 {round_to_edit} 기록이 K:{new_kills}, D:{new_deaths} (으)로 수정되었습니다.")

    # After editing a match, K/D for the player in leaderboard summary needs update
    update_leaderboard_player_summary(nickname_edit)
    
    # Winning team might have changed, or just to be sure, re-confirm.
    # Fetch current winning_team for the round to offer as default
    cur.execute("SELECT winning_team FROM matches WHERE round=? LIMIT 1", (round_to_edit,))
    current_winning_team_res = cur.fetchone()
    default_winning_team = current_winning_team_res[0] if current_winning_team_res else "미설정"

    while True:
        try:
            new_winning_team_str = input(f">> 라운드 {round_to_edit}의 승리 팀을 다시 입력하세요 (현재: {default_winning_team}, 1 또는 2): ").strip()
            if not new_winning_team_str: # User pressed Enter, keep current
                if isinstance(default_winning_team, int) and default_winning_team in [1,2]:
                    new_winning_team = default_winning_team
                    break
                else:
                    print("⚠ 현재 승리팀이 유효하지 않습니다. 다시 입력해주세요.")
                    continue

            new_winning_team = int(new_winning_team_str)
            if new_winning_team not in [1, 2]:
                raise ValueError("승리 팀은 1 또는 2여야 합니다.")
            break
        except ValueError as e:
            print(f"⚠ 잘못된 입력: {e}")

    # Update winning_team for ALL entries in that round in matches table
    cur.execute("UPDATE matches SET winning_team=? WHERE round=?", (new_winning_team, round_to_edit))
    con.commit()
    print(f"✅ 라운드 {round_to_edit}의 승리 팀이 {new_winning_team}팀으로 설정(재확인)되었습니다.")

    # Critical: Recalculate ELOs from this round onwards
    recalculate_elo_and_aftercalc_from_round(round_to_edit)


def handle_data_menu():
    """데이터 메뉴 핸들링"""
    sub_menu = {
        '1': handle_data_input,
        '2': handle_editing,
        '3': handle_data_deletion_prompt,
    }
    execute_menu(sub_menu, "데이터 관리 메뉴")

def handle_load_export_menu():
    """로드/내보내기 메뉴 핸들링"""
    def import_csv_wrapper():
        """CSV 파일에서 매치 데이터 불러오기 (기존 데이터 덮어쓰기 및 ELO 재계산)"""
        fname = input(">> 불러올 CSV 파일 이름을 입력하세요 (예: match_results.csv): ").strip()
        if fname: import_matches_from_csv(fname)
        else: print("⚠ 파일 이름이 입력되지 않았습니다.")

    def export_all_wrapper():
        """모든 주요 데이터 (리더보드, 매치 결과, ELO 기록)를 CSV로 내보내기"""
        print("🔄 모든 데이터 내보내기 시작...")
        export_leaderboard_to_csv() # No tag, uses current datetime
        export_match_results_to_csv()
        export_aftercalc_to_csv()
        export_leaderboard_to_spreadsheet() # Spreadsheet specific format
        print(Fore.GREEN + "✅ 모든 데이터 내보내기가 완료되었습니다." + Style.RESET_ALL)

    sub_menu = {
        '1': import_csv_wrapper,
        '2': export_leaderboard_to_csv, # Just leaderboard
        '3': export_match_results_to_csv, # Just match results
        '4': export_aftercalc_to_csv, # Just aftercalc history
        '5': export_leaderboard_to_spreadsheet, # Spreadsheet format
        '6': export_all_wrapper, # All of the above
    }
    execute_menu(sub_menu, "데이터 가져오기/내보내기 메뉴")

def handle_analysis_tools_menu():
    """분석 도구 메뉴 핸들링"""
    sub_menu = {
        '1': plot_elo_scatter,
        '2': balance_teams_prompt,
        '3': analyze_trend_prompt,
        '4': display_user_statistics, # Now supports 'all'
        '5': plot_tier_distribution,
        '6': print_leaderboard, # Standard leaderboard print
    }
    execute_menu(sub_menu, "분석 및 조회 도구 메뉴")


def execute_menu(menu_dict, menu_name):
    """공통 메뉴 실행 함수"""
    print(Fore.CYAN + f"\n--- {menu_name} ---" + Style.RESET_ALL)
    for key, func_or_tuple in menu_dict.items():
        # func_or_tuple can be a function or (function, "description override")
        if isinstance(func_or_tuple, tuple):
            func, docstring = func_or_tuple
        else:
            func = func_or_tuple
            docstring = func.__doc__.strip().split('\n')[0] if func.__doc__ else "설명 없음"
        print(f"  {key}. {docstring}")
    print(f"  b. 뒤로가기 / 메인 메뉴로")

    while True:
        choice = input(f"{menu_name} 번호 입력: ").strip().lower()
        if choice == 'b':
            break
        if choice in menu_dict:
            action = menu_dict[choice]
            if isinstance(action, tuple):
                action[0]() # Call the function
            else:
                action()
            # After action, re-display sub-menu options unless it was 'b'
            if choice != 'b': # Should always be true here due to outer if
                print(Fore.CYAN + f"\n--- {menu_name} (계속) ---" + Style.RESET_ALL)
                for key, func_or_tuple in menu_dict.items():
                    if isinstance(func_or_tuple, tuple):
                        _, docstring = func_or_tuple
                    else:
                        docstring = func_or_tuple.__doc__.strip().split('\n')[0] if func_or_tuple.__doc__ else "설명 없음"
                    print(f"  {key}. {docstring}")
                print(f"  b. 뒤로가기 / 메인 메뉴로")

        else:
            print("⚠ 잘못된 선택입니다. 올바른 번호를 입력해 주세요.")

def handle_data_input():
    """신규 라운드 데이터 입력"""
    print(">> 라운드 입력을 시작합니다.")
    current_round_num = get_round_number()
    
    map_name_input = input(f">> 라운드 {current_round_num}의 맵 이름을 입력하세요 (건너뛰려면 Enter): ").strip()
    current_map_name = map_name_input if map_name_input else None

    team1_players, team2_players = [], [] # Stores (nickname, kills, deaths)

    for team_num_loop in [1, 2]:
        print(Fore.CYAN + f"\n>> {team_num_loop}팀 유저 정보를 입력하세요." + Style.RESET_ALL)
        print("   형식: 이름 킬 데스 (예: Yusi0 10 5)")
        print("   이 팀 입력 완료 시 'next' 또는 'n' 입력 (1팀의 경우).")
        print("   모든 입력 완료 시 'done' 또는 'd' 입력 (2팀의 경우 또는 1팀만 있을 경우).")
        
        while True:
            user_entry = input(f"({team_num_loop}팀) > ").strip()
            if user_entry.lower() in ['exit_program']: handle_exit() # Allow full exit

            if user_entry.lower() in ['next', 'n']:
                if team_num_loop == 1: break # Move to team 2 input
                else: print("⚠ 이미 2팀 입력 중입니다. 완료하려면 'done'을 입력하세요.")
            elif user_entry.lower() in ['done', 'd']:
                # Mark this team's input as done, and proceed to finalize round if both teams are done.
                # This outer loop structure handles moving from team 1 to team 2.
                # If 'done' is hit for team 1, it will still go to team 2 loop (which can then be 'done' immediately).
                # This implies 'done' is primarily for finishing team 2 input.
                if team_num_loop == 1 and not team2_players: # if 'done' on team 1 and team 2 is empty
                     pass # Will proceed to team 2 loop, which can be 'done' immediately
                elif team_num_loop == 2:
                    handle_winning_team_input_and_process_round(team1_players, team2_players, current_round_num, current_map_name)
                    return # Finish data input process
                break # Break from player input loop for current team
            
            try:
                name, k_str, d_str = user_entry.split()
                k, d = int(k_str), int(d_str)
                if k < 0 or d < 0: raise ValueError("킬/데스는 음수일 수 없습니다.")
                
                player_data_tuple = (name, k, d)
                if team_num_loop == 1:
                    team1_players.append(player_data_tuple)
                else: # team_num_loop == 2
                    team2_players.append(player_data_tuple)
                print(f"   {name} ({k}K/{d}D) 추가됨.")
            except ValueError:
                print("⚠ 잘못된 형식 또는 값입니다. '이름 킬 데스' 형식으로, 킬/데스는 양의 정수로 입력하세요.")
            except Exception as e:
                print(f"⚠ 예상치 못한 오류: {e}")
        
        if user_entry.lower() in ['done', 'd'] and team_num_loop == 1: # if user typed done for team1
             if not team2_players: # if team2 is empty (e.g. user wants to input team2 now or skip)
                 print(Fore.CYAN + "\n>> 1팀 입력 완료. 2팀 입력을 시작하거나 'done'으로 즉시 라운드 종료." + Style.RESET_ALL)
                 continue # go to team 2 input loop
             else: # team2 already has players (e.g. came back to edit team1) - this case is less likely with current flow
                 handle_winning_team_input_and_process_round(team1_players, team2_players, current_round_num, current_map_name)
                 return

    # This point is reached if 'next' was used for team 1, and team 2 input loop finished (e.g. by 'done')
    handle_winning_team_input_and_process_round(team1_players, team2_players, current_round_num, current_map_name)


def handle_data_deletion_prompt():
    """매치 데이터 삭제 (특정 플레이어의 특정 라운드 기록) 후 ELO 재계산"""
    print(">> 삭제할 라운드 번호와 _닉네임_을 입력하세요 (예: 1 Yusi0). 'b' 입력 시 메인 메뉴.")
    entry = input("> ").strip()
    if entry.lower() == 'b': return

    try:
        round_str, nick_del = entry.split()
        round_to_del = int(round_str)
        delete_match_result(round_to_del, nick_del)
    except ValueError:
        print("⚠ 올바른 형식 ('라운드번호 닉네임')으로 입력해 주세요.")
    except Exception as e:
        print(f"⚠ 데이터 삭제 중 오류: {e}")


def analyze_trend_prompt():
    """트렌드 분석 실행"""
    nickname = input(">> 트렌드를 분석할 닉네임을 입력하세요: ").strip()
    if nickname:
        plot_trend_analysis(nickname)
    else:
        print("⚠ 닉네임이 입력되지 않았습니다.")

# 메인 함수
def main():
    initialize_tables()
    alter_matches_table() # Ensure schema is up-to-date

    main_menu_actions = {
        'd': ("데이터 관리 (입력, 수정, 삭제)", handle_data_menu),
        'l': ("데이터 가져오기/내보내기 (CSV)", handle_load_export_menu),
        'a': ("분석 및 조회 도구", handle_analysis_tools_menu), # 'f' for function changed to 'a' for analysis
        'reset': ("[주의] 전체 데이터 초기화", reset_leaderboard),
        'exit': ("프로그램 종료", handle_exit)
    }

    first_run_display = True
    while True:
        if first_run_display:
            print(Fore.MAGENTA + "\n--- ELO 레이팅 시스템 메인 메뉴 ---" + Style.RESET_ALL)
            for cmd_key, (desc, _) in main_menu_actions.items():
                print(f"  {cmd_key:<8} - {desc}")
            first_run_display = False

        user_cmd = input("\n>> 메인 메뉴 명령어 입력: ").strip().lower()

        if user_cmd in main_menu_actions:
            desc, action_func = main_menu_actions[user_cmd]
            print(f"\n-- {desc} 실행 --")
            action_func()
            first_run_display = True # Show main menu again after action
        else:
            print(Fore.RED + "(!) 잘못된 명령어입니다. 다시 시도해주세요." + Style.RESET_ALL)
            # Optionally re-display menu options on bad command
            # first_run_display = True 

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n" + Fore.RED + "⌨️ 사용자에 의해 프로그램이 중단되었습니다." + Style.RESET_ALL)
    finally:
        if con: # Ensure connection is closed if it exists
            con.close()