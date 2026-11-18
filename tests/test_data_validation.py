import pandas as pd

from src.data_validation import (
    candidate_key_results,
    cricket_quality_checks,
    relationship_checks,
)


def test_candidate_key_results_detects_duplicate_composite_key():
    datasets = {
        "ball_by_ball": pd.DataFrame(
            {
                "match_id": [1, 1],
                "innings": [1, 1],
                "overid": [1, 1],
                "over_ball_num": [1, 1],
                "innings_ball_num": [1, 2],
            }
        ),
        "matches": pd.DataFrame({"match_id": [1]}),
        "competitions": pd.DataFrame({"comp_id": [1]}),
        "teams": pd.DataFrame({"comp_id": [1], "team_id": [1]}),
        "playing_eleven": pd.DataFrame(
            {"match_id": [1], "team_id": [1], "player_id": [1]}
        ),
        "competition_team_player_mapping": pd.DataFrame(
            {"comp_id": [1], "team_id": [1], "player_id": [1]}
        ),
    }

    results = candidate_key_results(datasets)

    assert results["ball_by_ball"][0]["unique"] is False
    assert results["ball_by_ball"][0]["duplicate_rows"] == 2
    assert results["ball_by_ball"][1]["unique"] is True


def test_cricket_quality_checks_flag_malformed_wicket_and_extras():
    ball = pd.DataFrame(
        {
            "match_id": [1, 1],
            "innings": [1, 1],
            "overid": [1, 1],
            "over_ball_num": [1, 7],
            "innings_ball_num": [1, 2],
            "is_wicket": [True, False],
            "dismissal_type_id": [1, None],
            "dismissal_type": ["Caught", None],
            "dismissed_player_id": [None, 42],
            "extras_type": [None, None],
            "extras1_runs": [0, 0],
            "extras_2_runs": [0, 1],
            "is_four": [False, False],
            "is_six": [False, False],
            "runs": [0, 0],
        }
    )
    matches = pd.DataFrame(
        {"match_id": [1], "comp_id": [10], "result": ["Team A Won"]}
    )
    competitions = pd.DataFrame(
        {"comp_id": [10], "match_format": ["T20I"], "season": ["2025"]}
    )

    result = cricket_quality_checks(ball, matches, competitions)

    assert result["delivery_numbering"]["over_ball_num_above_6_rows"] == 1
    assert result["extras"]["nonzero_runs_without_type_rows"] == 1
    assert result["wickets"]["wicket_without_dismissed_player_id"] == 1
    assert result["wickets"]["dismissed_player_id_without_wicket_flag"] == 1


def test_relationship_checks_count_unmatched_playing_eleven_rows():
    datasets = {
        "ball_by_ball": pd.DataFrame(
            {
                "match_id": [1],
                "batting_team_id": [10],
                "bowling_team_id": [20],
                "striker_id": [100],
                "non_striker_id": [101],
                "bowler_id": [102],
                "dismissed_player_id": [None],
            }
        ),
        "matches": pd.DataFrame(
            {
                "match_id": [1],
                "comp_id": [5],
                "home_team_id": [10],
                "away_team_id": [20],
                "home_team": ["Home"],
                "away_team": ["Away"],
                "home_team_captain_id": [100],
                "away_team_captain_id": [101],
                "toss_win_team_id": [10],
                "win_team_id": [20],
                "man_of_the_match": [100],
            }
        ),
        "competitions": pd.DataFrame({"comp_id": [5]}),
        "teams": pd.DataFrame(
            {
                "comp_id": [5, 5],
                "team_id": [10, 20],
                "team_name": ["Home", "Away"],
            }
        ),
        "playing_eleven": pd.DataFrame(
            {"match_id": [1], "team_id": [10], "player_id": [999]}
        ),
        "competition_team_player_mapping": pd.DataFrame(
            {
                "comp_id": [5, 5, 5],
                "team_id": [10, 10, 20],
                "player_id": [100, 101, 102],
                "player_name": ["A", "B", "C"],
            }
        ),
    }

    checks = relationship_checks(datasets)
    unmatched_players = next(
        check
        for check in checks
        if check["name"] == "playing_eleven player -> mapping by competition and team"
    )

    assert unmatched_players["unmatched_count"] == 1
    assert unmatched_players["unmatched_row_count"] == 1
    assert unmatched_players["examples"] == [[5, 10, 999]]
