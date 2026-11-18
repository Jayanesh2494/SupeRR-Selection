import pandas as pd

from src.pressure_analysis import (
    build_chase_deliveries,
    classify_pressure,
    rank_batters,
    rank_bowlers,
)


def test_classify_pressure_marks_top_quartile_separately():
    deliveries = pd.DataFrame(
        {
            "match_format": ["IPL"] * 8,
            "required_run_rate": list(range(1, 9)),
            "wickets_lost": [0] * 8,
            "balls_remaining": list(range(120, 40, -10)),
            "innings_balls": [120] * 8,
        }
    )

    classified = classify_pressure(deliveries)

    assert classified["batting_under_pressure"].sum() == 2
    assert classified["bowling_under_pressure"].sum() == 2
    assert classified.loc[7, "batting_under_pressure"]
    assert classified.loc[0, "bowling_under_pressure"]


def test_build_chase_deliveries_uses_score_and_excludes_unusable_dls():
    competitions = pd.DataFrame(
        {
            "comp_id": [1, 2],
            "comp_name": ["IPL 2025", "Other T20"],
            "match_format": ["T20", "T20"],
        }
    )
    matches = pd.DataFrame(
        {
            "match_id": [10, 11],
            "comp_id": [1, 1],
            "revised_target": [None, None],
            "second_inn_revised_overs": [6, 6],
            "result": ["Team B Won by 1 wicket", "DLS result"],
            "win_team_id": [20, 20],
        }
    )
    rows = []
    for match_id in (10, 11):
        for innings, team in ((1, 10), (2, 20)):
            for ball_number in range(1, 4):
                rows.append(
                    {
                        "match_id": match_id,
                        "innings": innings,
                        "innings_ball_num": ball_number,
                        "runs": 2 if innings == 1 else 3,
                        "extras1_runs": 0,
                        "extras_2_runs": 0,
                        "extras_type": None,
                        "is_wicket": False,
                        "batting_team_id": team,
                        "striker_id": team,
                        "bowler_id": 10 if innings == 2 else 20,
                        "dismissal_type": None,
                    }
                )
    ball = pd.DataFrame(rows)

    chase, diagnostics = build_chase_deliveries(
        {
            "ball_by_ball": ball,
            "matches": matches,
            "competitions": competitions,
        }
    )

    assert chase["match_id"].unique().tolist() == [10]
    assert chase["target"].eq(7).all()
    assert diagnostics["eligible_chase_matches"] == 1
    assert diagnostics["target_and_winner_consistency"][
        "consistent_matches"
    ] == 1
    assert diagnostics["excluded_matches_by_reason"][
        "revised_target_missing_for_dls"
    ] == 1


def test_rankings_compare_each_player_with_their_own_baseline():
    rows = []
    for player_id in (10, 20):
        for is_pressure, count, match_count in (
            (True, 60, 4),
            (False, 120, 6),
        ):
            runs_per_delivery = (
                2 if player_id == 10 and is_pressure else 1
            )
            conceded_runs = (
                0.5
                if player_id == 10 and is_pressure
                else 1.5
                if player_id == 20 and is_pressure
                else 1
            )
            for offset in range(count):
                rows.append(
                    {
                        "match_id": player_id * 100 + (offset % match_count),
                        "match_format": "IPL",
                        "striker_id": player_id,
                        "bowler_id": player_id,
                        "runs": runs_per_delivery,
                        "batter_faced_ball": True,
                        "is_legal_ball": True,
                        "batting_under_pressure": is_pressure,
                        "bowling_under_pressure": is_pressure,
                        "bowler_conceded_runs": conceded_runs,
                        "bowler_credited_wicket": (
                            player_id == 10 and is_pressure and offset % 10 == 0
                        ),
                    }
                )
    deliveries = pd.DataFrame(rows)
    names = pd.DataFrame(
        {
            "player_id": [10, 20],
            "player_name": ["Player Ten", "Player Twenty"],
        }
    )

    batter_leaderboard, batter_top10 = rank_batters(deliveries, names)
    bowler_leaderboard, bowler_top10 = rank_bowlers(deliveries, names)

    assert batter_leaderboard.iloc[0]["player_name"] == "Player Ten"
    assert batter_leaderboard.iloc[0]["reliability_adjusted_score"] == 50
    assert batter_top10.iloc[0]["bootstrap_95_ci_low_sr_change"] <= batter_top10.iloc[
        0
    ]["bootstrap_95_ci_high_sr_change"]
    assert bowler_leaderboard.iloc[0]["player_name"] == "Player Ten"
    assert len(bowler_top10) == 2
