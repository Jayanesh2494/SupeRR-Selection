import json

import pandas as pd

from src.dashboard import build_dashboard_html, build_dashboard_payload


def test_dashboard_html_embeds_data_safely():
    html = build_dashboard_html({"player": "</script><script>alert(1)</script>"})

    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html
    assert "SupeRR Selector" in html


def test_dashboard_payload_contains_phase_splits_and_dataset_inventory():
    chase = pd.DataFrame(
        {
            "match_id": [1, 1],
            "comp_id": [1, 1],
            "match_format": ["T20", "T20"],
            "innings_ball_num": [1, 2],
            "legal_balls_bowled": [0, 1],
            "innings_balls": [120, 120],
            "batting_under_pressure": [True, False],
            "bowling_under_pressure": [True, False],
            "batter_faced_ball": [True, True],
            "striker_id": [1, 1],
            "bowler_id": [2, 2],
            "batting_team_id": [20, 20],
            "bowling_team_id": [10, 10],
            "runs": [1, 1],
            "total_team_runs": [2, 1],
            "is_four": [False, False],
            "is_six": [False, False],
            "is_wicket": [True, False],
            "is_legal_ball": [True, True],
            "bowler_conceded_runs": [2, 1],
            "bowler_credited_wicket": [True, False],
            "target": [10, 10],
            "runs_before": [0, 2],
            "runs_required": [10, 8],
            "balls_remaining": [120, 119],
            "wickets_lost": [0, 1],
            "required_run_rate": [0.5, 0.41],
        }
    )
    empty_rankings = pd.DataFrame({"player_id": pd.Series(dtype=int)})
    result = {
        "chase_deliveries": chase,
        "diagnostics": {
            "eligible_chase_matches": 2,
            "target_and_winner_consistency": {
                "consistent_matches": 2,
                "matches_checked": 2,
            },
            "matches_with_delivery_rows_after_target": 0,
            "matches_with_delivery_rows_after_innings_quota": 0,
            "excluded_matches_by_reason": {},
        },
        "batter_leaderboard": empty_rankings,
        "batter_top10": empty_rankings,
        "bowler_leaderboard": empty_rankings,
        "bowler_top10": empty_rankings,
    }
    datasets = {
        "ball_by_ball": pd.DataFrame(
            {
                "match_id": [1, 1],
                "runs": [2, 1],
                "extras1_runs": [0, 1],
                "extras_2_runs": [0, 0],
                "extras_type": [None, None],
                "innings": [1, 2],
                "overid": [1, 1],
                "over_ball_num": [1, 1],
                "innings_ball_num": [1, 1],
                "batting_team_id": [10, 20],
                "bowling_team_id": [20, 10],
                "striker_id": [2, 1],
                "non_striker_id": [1, 2],
                "bowler_id": [1, 2],
                "dismissed_player_id": [None, 1],
                "is_wicket": [False, True],
                "dismissal_type_id": [None, 1],
                "dismissal_type": [None, "Caught"],
                "is_four": [False, False],
                "is_six": [False, False],
            }
        ),
        "matches": pd.DataFrame(
            {
                "match_id": [1],
                "comp_id": [1],
                "home_team_id": [10],
                "away_team_id": [20],
                "home_team": ["Home"],
                "away_team": ["Away"],
                "home_team_captain_id": [None],
                "away_team_captain_id": [None],
                "toss_win_team_id": [10],
                "win_team_id": [20],
                "man_of_the_match": [0],
                "result": ["Away won"],
                "match_date": ["2025-01-01"],
            }
        ),
        "competitions": pd.DataFrame(
            {
                "comp_id": [1],
                "comp_name": ["IPL 2025"],
                "match_format": ["T20"],
                "season": ["2025"],
            }
        ),
        "teams": pd.DataFrame(
            {
                "comp_id": [1, 1],
                "team_id": [10, 20],
                "team_name": ["Home", "Away"],
            }
        ),
        "playing_eleven": pd.DataFrame(
        {
            "match_id": [1, 1],
            "team_id": [20, 10],
            "player_id": [1, 2],
            "is_played": [True, True],
        }
        ),
        "competition_team_player_mapping": pd.DataFrame(
        {
            "comp_id": [1, 1],
            "team_id": [20, 10],
            "player_id": [1, 2],
            "player_name": ["Batter", "Bowler"],
        }
        ),
    }

    payload = build_dashboard_payload(result, datasets)

    assert payload["datasets"]["ball_by_ball"]["rows"] == 2
    assert payload["formats"]["T20"]["matches"] == 1
    assert payload["pressure_by_phase"]["T20"]["Early"][
        "batting_pressure_deliveries"
    ] == 1
    assert len(payload["players"]) == 2
    batter = next(player for player in payload["players"] if player["player_id"] == 1)
    bowler = next(player for player in payload["players"] if player["player_id"] == 2)
    assert batter["batting"]["runs"] == 1
    assert batter["batting"]["pressure_runs"] == 1
    assert batter["match_records"][0]["pressure_batting_run_share"] == 0.5
    assert bowler["bowling"]["wickets"] == 1
    assert bowler["bowling"]["pressure_wickets"] == 1
    assert json.dumps(payload, allow_nan=False)
