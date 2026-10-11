"""기존 elo.py의 공식 원문 (삭제 전 보관). 새 엔진 공식이 이것과 같은지 비교하는 기준이다. 수정하지 말 것."""


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
