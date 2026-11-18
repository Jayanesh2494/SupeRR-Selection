"""Build a self-contained interactive analytics dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__:
    from .data_exploration import load_datasets, profile_datasets, resolve_data_dir
    from .data_validation import validate_datasets
    from .pressure_analysis import (
        _modeled_players,
        _selected_competitions,
        rank_batters,
        rank_bowlers,
        run_analysis,
    )
else:
    from data_exploration import load_datasets, profile_datasets, resolve_data_dir
    from data_validation import validate_datasets
    from pressure_analysis import (
        _modeled_players,
        _selected_competitions,
        rank_batters,
        rank_bowlers,
        run_analysis,
    )


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _clean_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    if pd.isna(value):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _clean_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _phase_pressure(chase: pd.DataFrame) -> dict[str, Any]:
    frame = chase.copy()
    elapsed = frame["legal_balls_bowled"] / frame["innings_balls"]
    frame["innings_phase"] = np.select(
        [elapsed < 0.30, elapsed < 0.75],
        ["Early", "Middle"],
        default="Late",
    )
    result: dict[str, Any] = {}
    for (match_format, phase), group in frame.groupby(
        ["match_format", "innings_phase"], sort=False
    ):
        result.setdefault(str(match_format), {})[str(phase)] = {
            "deliveries": int(len(group)),
            "batting_pressure_deliveries": int(
                group["batting_under_pressure"].sum()
            ),
            "bowling_pressure_deliveries": int(
                group["bowling_under_pressure"].sum()
            ),
            "batting_pressure_share": float(
                group["batting_under_pressure"].mean()
            ),
            "bowling_pressure_share": float(
                group["bowling_under_pressure"].mean()
            ),
        }
    return result


def _player_pressure_baselines(chase: pd.DataFrame) -> dict[int, dict[str, dict[str, Any]]]:
    batting = chase.loc[chase["batter_faced_ball"]].copy()
    batting_cohorts = (
        batting.groupby(
            ["striker_id", "match_format", "batting_under_pressure"],
            as_index=False,
        )
        .agg(
            runs=("runs", "sum"),
            balls=("batter_faced_ball", "sum"),
            matches=("match_id", "nunique"),
        )
    )
    bowling = chase.copy()
    bowling["legal_exposure"] = bowling["is_legal_ball"].astype(int)
    bowling_cohorts = (
        bowling.groupby(
            ["bowler_id", "match_format", "bowling_under_pressure"],
            as_index=False,
        )
        .agg(
            conceded=("bowler_conceded_runs", "sum"),
            wickets=("bowler_credited_wicket", "sum"),
            balls=("legal_exposure", "sum"),
            matches=("match_id", "nunique"),
        )
    )
    result: dict[int, dict[str, dict[str, Any]]] = {}
    for role, frame, player_col, rate_source, wicket_source in (
        ("batting", batting_cohorts, "striker_id", "runs", None),
        ("bowling", bowling_cohorts, "bowler_id", "conceded", "wickets"),
    ):
        for player_id, player_rows in frame.groupby(player_col):
            eligible_formats = []
            for match_format, format_rows in player_rows.groupby("match_format"):
                pressure = format_rows.loc[
                    format_rows[
                        "batting_under_pressure"
                        if role == "batting"
                        else "bowling_under_pressure"
                    ]
                ]
                baseline = format_rows.loc[
                    ~format_rows[
                        "batting_under_pressure"
                        if role == "batting"
                        else "bowling_under_pressure"
                    ]
                ]
                if (
                    pressure.empty
                    or baseline.empty
                    or pressure["balls"].sum() <= 0
                    or baseline["balls"].sum() <= 0
                ):
                    continue
                pressure_balls = float(pressure["balls"].sum())
                baseline_balls = float(baseline["balls"].sum())
                pressure_rate = float(pressure[rate_source].sum()) / pressure_balls
                baseline_rate = float(baseline[rate_source].sum()) / baseline_balls
                scale = 100 if role == "batting" else 6
                rate_delta = (
                    pressure_rate - baseline_rate
                    if role == "batting"
                    else baseline_rate - pressure_rate
                ) * scale
                pressure_wickets_per_24 = (
                    float(pressure[wicket_source].sum()) / pressure_balls * 24
                    if wicket_source
                    else None
                )
                baseline_wickets_per_24 = (
                    float(baseline[wicket_source].sum()) / baseline_balls * 24
                    if wicket_source
                    else None
                )
                eligible_formats.append(
                    {
                        "format": str(match_format),
                        "pressure_balls": pressure_balls,
                        "baseline_balls": baseline_balls,
                        "pressure_rate": pressure_rate * scale,
                        "baseline_rate": baseline_rate * scale,
                        "raw_rate_change": rate_delta,
                        "adjusted_rate_change": rate_delta
                        * pressure_balls
                        / (pressure_balls + 60),
                        "pressure_matches": int(pressure["matches"].sum()),
                        "pressure_runs": (
                            int(pressure[rate_source].sum())
                            if role == "batting"
                            else None
                        ),
                        "pressure_conceded": (
                            int(pressure[rate_source].sum())
                            if role == "bowling"
                            else None
                        ),
                        "pressure_wickets": (
                            int(pressure[wicket_source].sum())
                            if wicket_source
                            else None
                        ),
                        "pressure_wickets_per_24": pressure_wickets_per_24,
                        "baseline_wickets_per_24": baseline_wickets_per_24,
                        "wickets_per_24_change": (
                            pressure_wickets_per_24 - baseline_wickets_per_24
                            if wicket_source
                            else None
                        ),
                    }
                )
            if not eligible_formats:
                continue
            pressure_balls = sum(item["pressure_balls"] for item in eligible_formats)
            player_summary: dict[str, Any] = {
                "pressure_balls": int(pressure_balls),
                "baseline_balls": int(
                    sum(item["baseline_balls"] for item in eligible_formats)
                ),
                "pressure_matches": int(
                    sum(item["pressure_matches"] for item in eligible_formats)
                ),
                "pressure_rate": float(
                    sum(
                        item["pressure_rate"] * item["pressure_balls"]
                        for item in eligible_formats
                    )
                    / pressure_balls
                ),
                "baseline_rate": float(
                    sum(
                        item["baseline_rate"] * item["pressure_balls"]
                        for item in eligible_formats
                    )
                    / pressure_balls
                ),
                "raw_rate_change": float(
                    sum(
                        item["raw_rate_change"] * item["pressure_balls"]
                        for item in eligible_formats
                    )
                    / pressure_balls
                ),
                "adjusted_rate_change": float(
                    sum(
                        item["adjusted_rate_change"] * item["pressure_balls"]
                        for item in eligible_formats
                    )
                    / pressure_balls
                ),
                "by_format": eligible_formats,
            }
            if role == "batting":
                player_summary["pressure_runs"] = sum(
                    int(item["pressure_runs"] or 0) for item in eligible_formats
                )
            else:
                player_summary["pressure_conceded"] = sum(
                    int(item["pressure_conceded"] or 0)
                    for item in eligible_formats
                )
                player_summary["pressure_wickets"] = sum(
                    int(item["pressure_wickets"] or 0) for item in eligible_formats
                )
                player_summary["wickets_per_24_change"] = float(
                    sum(
                        item["wickets_per_24_change"] * item["pressure_balls"]
                        for item in eligible_formats
                    )
                    / pressure_balls
                )
            result.setdefault(int(player_id), {})[role] = player_summary
    return result


def _player_profiles(
    datasets: dict[str, pd.DataFrame],
    chase: pd.DataFrame,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    competitions = _selected_competitions(datasets["competitions"])
    comp_ids = set(competitions["comp_id"])
    competition_matches = datasets["matches"].merge(
        competitions[
            ["comp_id", "comp_name", "match_format", "season"]
        ],
        on="comp_id",
        how="inner",
        validate="many_to_one",
    )
    match_columns = [
        "match_id",
        "comp_id",
        "comp_name",
        "match_format",
        "season",
        "match_date",
        "home_team_id",
        "home_team",
        "away_team_id",
        "away_team",
        "win_team_id",
        "result",
    ]
    matches = competition_matches[match_columns].drop_duplicates("match_id")
    ball = datasets["ball_by_ball"].merge(
        matches, on="match_id", how="inner", validate="many_to_one"
    )
    ball["extras_normalized"] = (
        ball["extras_type"].astype("string").str.strip().str.casefold().fillna("")
    )
    ball["legal_ball"] = ~ball["extras_normalized"].isin({"wide", "overstep"})
    ball["batter_faced"] = ~ball["extras_normalized"].eq("wide")
    ball["team_runs"] = (
        ball["runs"].fillna(0)
        + ball["extras1_runs"].fillna(0)
        + ball["extras_2_runs"].fillna(0)
    )
    ball["bowler_runs"] = ball["runs"].fillna(0) + (
        ball[["extras1_runs", "extras_2_runs"]].fillna(0).sum(axis=1)
        * ~ball["extras_normalized"].isin({"byes", "legbyes", "penalty"})
    )
    ball["is_wicket"] = ball["is_wicket"].fillna(False).astype(bool)
    dismissal = (
        ball["dismissal_type"].astype("string").str.strip().str.casefold().fillna("")
    )
    ball["credited_wicket"] = dismissal.isin(
        {"bowled", "caught", "hit wicket", "lbw", "stump"}
    )
    stats_innings = ball.loc[ball["innings"].isin([1, 2])].copy()

    batting = (
        stats_innings.groupby(
            ["match_id", "comp_id", "striker_id", "batting_team_id"],
            as_index=False,
        )
        .agg(
            batting_runs=("runs", "sum"),
            batting_balls=("batter_faced", "sum"),
            fours=("is_four", "sum"),
            sixes=("is_six", "sum"),
            batting_rows=("runs", "size"),
            batting_innings=("innings", "nunique"),
        )
        .rename(columns={"striker_id": "player_id", "batting_team_id": "team_id"})
    )
    batting["batting_strike_rate"] = (
        batting["batting_runs"] / batting["batting_balls"].replace(0, np.nan) * 100
    )
    batting_outs = (
        stats_innings.loc[stats_innings["dismissed_player_id"].notna()]
        .groupby(["match_id", "comp_id", "dismissed_player_id"], as_index=False)
        .size()
        .rename(
            columns={
                "dismissed_player_id": "player_id",
                "size": "batting_dismissals",
            }
        )
    )
    batting = batting.merge(
        batting_outs,
        on=["match_id", "comp_id", "player_id"],
        how="left",
        validate="one_to_one",
    )
    batting["batting_dismissals"] = batting["batting_dismissals"].fillna(0)

    bowling = (
        stats_innings.groupby(
            ["match_id", "comp_id", "bowler_id", "bowling_team_id"],
            as_index=False,
        )
        .agg(
            bowling_balls=("legal_ball", "sum"),
            bowling_conceded=("bowler_runs", "sum"),
            bowling_wickets=("credited_wicket", "sum"),
            bowling_rows=("runs", "size"),
        )
        .rename(columns={"bowler_id": "player_id", "bowling_team_id": "team_id"})
    )
    bowling["bowling_economy"] = (
        bowling["bowling_conceded"]
        / bowling["bowling_balls"].replace(0, np.nan)
        * 6
    )

    selected_mapping = datasets["competition_team_player_mapping"].loc[
        datasets["competition_team_player_mapping"]["comp_id"].isin(comp_ids)
    ].copy()
    names = _modeled_players(
        datasets["competition_team_player_mapping"], competitions
    ).set_index("player_id")["player_name"]

    player_ids = set(selected_mapping["player_id"].dropna().astype(int))
    for role in ("striker_id", "non_striker_id", "bowler_id", "dismissed_player_id"):
        player_ids.update(ball[role].dropna().astype(int))
    xi = datasets["playing_eleven"].merge(
        matches[["match_id", "comp_id", "match_format", "season"]],
        on="match_id",
        how="inner",
        validate="many_to_one",
    )
    xi = xi.loc[xi["is_played"].fillna(False).astype(bool)]
    player_ids.update(xi["player_id"].dropna().astype(int))
    if not player_ids:
        return []

    appearances = pd.concat(
        [
            batting[["match_id", "comp_id", "player_id", "team_id"]],
            bowling[["match_id", "comp_id", "player_id", "team_id"]],
            xi[["match_id", "comp_id", "player_id", "team_id"]],
        ],
        ignore_index=True,
    ).drop_duplicates(["match_id", "comp_id", "player_id", "team_id"])
    appearances = appearances.merge(
        matches[
            [
                "match_id",
                "comp_id",
                "comp_name",
                "match_format",
                "season",
                "match_date",
                "home_team_id",
                "home_team",
                "away_team_id",
                "away_team",
                "win_team_id",
                "result",
            ]
        ],
        on=["match_id", "comp_id"],
        how="left",
        validate="many_to_one",
    )
    appearances["team_name"] = np.where(
        appearances["team_id"].eq(appearances["home_team_id"]),
        appearances["home_team"],
        np.where(
            appearances["team_id"].eq(appearances["away_team_id"]),
            appearances["away_team"],
            "Team ID " + appearances["team_id"].astype("string"),
        ),
    )
    appearances["opponent"] = np.where(
        appearances["team_id"].eq(appearances["home_team_id"]),
        appearances["away_team"],
        np.where(
            appearances["team_id"].eq(appearances["away_team_id"]),
            appearances["home_team"],
            "Unknown",
        ),
    )
    appearances["won_match"] = appearances["team_id"].eq(
        appearances["win_team_id"]
    )
    appearances = appearances.merge(
        batting,
        on=["match_id", "comp_id", "player_id", "team_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        bowling,
        on=["match_id", "comp_id", "player_id", "team_id"],
        how="left",
        validate="one_to_one",
    )

    chase_match = chase[
        [
            "match_id",
            "comp_id",
            "match_format",
            "innings_ball_num",
            "batting_team_id",
            "bowling_team_id",
            "striker_id",
            "bowler_id",
            "total_team_runs",
            "runs",
            "batter_faced_ball",
            "is_legal_ball",
            "is_wicket",
            "is_four",
            "is_six",
            "bowler_conceded_runs",
            "bowler_credited_wicket",
            "batting_under_pressure",
            "bowling_under_pressure",
            "target",
            "runs_before",
            "runs_required",
            "balls_remaining",
            "wickets_lost",
            "required_run_rate",
        ]
    ]
    batting_pressure_rows = chase_match.loc[
        chase_match["batting_under_pressure"]
    ].copy()
    batting_team_totals = (
        batting_pressure_rows.groupby(
            ["match_id", "batting_team_id"], as_index=False
        )
        .agg(
            batting_pressure_team_runs=("total_team_runs", "sum"),
            batting_pressure_team_wickets=("is_wicket", "sum"),
        )
        .rename(columns={"batting_team_id": "team_id"})
    )
    batting_pressure = (
        batting_pressure_rows.groupby(
            ["match_id", "comp_id", "striker_id", "batting_team_id"],
            as_index=False,
        )
        .agg(
            batting_pressure_runs=("runs", "sum"),
            batting_pressure_balls=("batter_faced_ball", "sum"),
            batting_pressure_fours=("is_four", "sum"),
            batting_pressure_sixes=("is_six", "sum"),
            batting_pressure_rows=("runs", "size"),
            peak_required_rate=("required_run_rate", "max"),
            peak_runs_required=("runs_required", "max"),
            minimum_balls_remaining=("balls_remaining", "min"),
            maximum_wickets_lost=("wickets_lost", "max"),
        )
        .rename(columns={"striker_id": "player_id", "batting_team_id": "team_id"})
    )
    batting_pressure["batting_pressure_strike_rate"] = (
        batting_pressure["batting_pressure_runs"]
        / batting_pressure["batting_pressure_balls"].replace(0, np.nan)
        * 100
    )
    batting_pressure = batting_pressure.merge(
        batting_team_totals,
        on=["match_id", "team_id"],
        how="left",
        validate="many_to_one",
    )
    batting_pressure["share_of_pressure_team_runs"] = (
        batting_pressure["batting_pressure_runs"]
        / batting_pressure["batting_pressure_team_runs"].replace(0, np.nan)
    )

    bowling_pressure_rows = chase_match.loc[
        chase_match["bowling_under_pressure"]
    ].copy()
    bowling_team_totals = (
        bowling_pressure_rows.groupby(
            ["match_id", "bowling_team_id"], as_index=False
        )
        .agg(
            opposition_pressure_runs=("total_team_runs", "sum"),
            opposition_pressure_wickets=("is_wicket", "sum"),
        )
        .rename(columns={"bowling_team_id": "team_id"})
    )
    bowling_pressure = (
        bowling_pressure_rows.groupby(
            ["match_id", "comp_id", "bowler_id", "bowling_team_id"],
            as_index=False,
        )
        .agg(
            bowling_pressure_balls=("is_legal_ball", "sum"),
            bowling_pressure_conceded=("bowler_conceded_runs", "sum"),
            bowling_pressure_wickets=("bowler_credited_wicket", "sum"),
            bowling_pressure_rows=("bowler_id", "size"),
            peak_required_rate_faced=("required_run_rate", "max"),
            maximum_wickets_lost=("wickets_lost", "max"),
            minimum_balls_remaining=("balls_remaining", "min"),
        )
        .rename(columns={"bowler_id": "player_id", "bowling_team_id": "team_id"})
    )
    bowling_pressure["bowling_pressure_economy"] = (
        bowling_pressure["bowling_pressure_conceded"]
        / bowling_pressure["bowling_pressure_balls"].replace(0, np.nan)
        * 6
    )
    bowling_pressure = bowling_pressure.merge(
        bowling_team_totals,
        on=["match_id", "team_id"],
        how="left",
        validate="many_to_one",
    )
    bowling_pressure["share_of_pressure_opposition_wickets"] = (
        bowling_pressure["bowling_pressure_wickets"]
        / bowling_pressure["opposition_pressure_wickets"].replace(0, np.nan)
    )
    bowling_pressure["share_of_pressure_opposition_runs_conceded"] = (
        bowling_pressure["bowling_pressure_conceded"]
        / bowling_pressure["opposition_pressure_runs"].replace(0, np.nan)
    )

    appearances = appearances.merge(
        batting_pressure,
        on=["match_id", "comp_id", "player_id", "team_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        bowling_pressure,
        on=["match_id", "comp_id", "player_id", "team_id"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_bowling"),
    )
    numeric_columns = [
        "batting_runs",
        "batting_balls",
        "fours",
        "sixes",
        "batting_rows",
        "batting_innings",
        "batting_dismissals",
        "bowling_balls",
        "bowling_conceded",
        "bowling_wickets",
        "bowling_rows",
        "batting_pressure_runs",
        "batting_pressure_balls",
        "batting_pressure_fours",
        "batting_pressure_sixes",
        "batting_pressure_rows",
        "bowling_pressure_balls",
        "bowling_pressure_conceded",
        "bowling_pressure_wickets",
        "bowling_pressure_rows",
    ]
    appearances[numeric_columns] = appearances[numeric_columns].fillna(0)
    appearances["batting_strike_rate"] = (
        appearances["batting_runs"]
        / appearances["batting_balls"].replace(0, np.nan)
        * 100
    )
    appearances["bowling_economy"] = (
        appearances["bowling_conceded"]
        / appearances["bowling_balls"].replace(0, np.nan)
        * 6
    )
    appearances["batting_pressure_strike_rate"] = (
        appearances["batting_pressure_runs"]
        / appearances["batting_pressure_balls"].replace(0, np.nan)
        * 100
    )
    appearances["bowling_pressure_economy"] = (
        appearances["bowling_pressure_conceded"]
        / appearances["bowling_pressure_balls"].replace(0, np.nan)
        * 6
    )
    appearances["batting_run_contribution"] = (
        appearances["batting_runs"] / appearances["team_runs"]
        if "team_runs" in appearances
        else np.nan
    )

    batting_team_match_totals = (
        stats_innings.groupby(
            ["match_id", "comp_id", "batting_team_id"], as_index=False
        )
        .agg(team_runs=("team_runs", "sum"))
        .rename(columns={"batting_team_id": "team_id"})
    )
    appearances = appearances.merge(
        batting_team_match_totals,
        on=["match_id", "comp_id", "team_id"],
        how="left",
        validate="many_to_one",
    )
    appearances["batting_run_contribution"] = (
        appearances["batting_runs"] / appearances["team_runs"].replace(0, np.nan)
    )
    appearances["bowling_pressure_run_contribution"] = (
        appearances["bowling_pressure_conceded"]
        / appearances["opposition_pressure_runs"].replace(0, np.nan)
    )

    pressure_baselines = _player_pressure_baselines(chase)
    player_rows: list[dict[str, Any]] = []
    batter_rank = result["batter_leaderboard"].set_index("player_id")
    bowler_rank = result["bowler_leaderboard"].set_index("player_id")
    for player_id in sorted(player_ids):
        player_matches = appearances.loc[
            appearances["player_id"] == player_id
        ].sort_values(["match_date", "match_id"], ascending=[False, False])
        player_batting = player_matches.loc[player_matches["batting_rows"] > 0]
        player_bowling = player_matches.loc[player_matches["bowling_rows"] > 0]
        career_batting_balls = float(player_matches["batting_balls"].sum())
        career_bowling_balls = float(player_matches["bowling_balls"].sum())
        career_batting_runs = float(player_matches["batting_runs"].sum())
        career_bowling_runs = float(player_matches["bowling_conceded"].sum())
        career_batting = {
            "innings": int(player_batting["match_id"].nunique()),
            "runs": int(career_batting_runs),
            "balls": int(career_batting_balls),
            "strike_rate": (
                career_batting_runs / career_batting_balls * 100
                if career_batting_balls
                else None
            ),
            "fours": int(player_matches["fours"].sum()),
            "sixes": int(player_matches["sixes"].sum()),
            "dismissals": int(player_matches["batting_dismissals"].sum()),
            "team_run_share": (
                float(
                    player_matches["batting_runs"].sum()
                    / player_matches["team_runs"].sum()
                )
                if player_matches["team_runs"].sum()
                else None
            ),
        }
        career_bowling = {
            "innings": int(player_bowling["match_id"].nunique()),
            "legal_balls": int(career_bowling_balls),
            "overs": (
                f"{int(career_bowling_balls // 6)}."
                f"{int(career_bowling_balls % 6)}"
            ),
            "conceded": int(career_bowling_runs),
            "wickets": int(player_matches["bowling_wickets"].sum()),
            "economy": (
                career_bowling_runs / career_bowling_balls * 6
                if career_bowling_balls
                else None
            ),
        }

        def summarize(group: pd.DataFrame) -> list[dict[str, Any]]:
            summaries = []
            for (match_format, season), season_rows in group.groupby(
                ["match_format", "season"], dropna=False, sort=False
            ):
                batting_runs = float(season_rows["batting_runs"].sum())
                batting_balls = float(season_rows["batting_balls"].sum())
                bowling_runs = float(season_rows["bowling_conceded"].sum())
                bowling_balls = float(season_rows["bowling_balls"].sum())
                summaries.append(
                    {
                        "format": str(match_format),
                        "season": str(season),
                        "matches": int(season_rows["match_id"].nunique()),
                        "batting_innings": int(
                            season_rows.loc[
                                season_rows["batting_rows"] > 0, "match_id"
                            ].nunique()
                        ),
                        "runs": int(batting_runs),
                        "balls_faced": int(batting_balls),
                        "strike_rate": (
                            batting_runs / batting_balls * 100
                            if batting_balls
                            else None
                        ),
                        "fours": int(season_rows["fours"].sum()),
                        "sixes": int(season_rows["sixes"].sum()),
                        "dismissals": int(
                            season_rows["batting_dismissals"].sum()
                        ),
                        "bowling_innings": int(
                            season_rows.loc[
                                season_rows["bowling_rows"] > 0, "match_id"
                            ].nunique()
                        ),
                        "bowling_legal_balls": int(bowling_balls),
                        "bowling_overs": (
                            f"{int(bowling_balls // 6)}."
                            f"{int(bowling_balls % 6)}"
                        ),
                        "conceded": int(bowling_runs),
                        "wickets": int(season_rows["bowling_wickets"].sum()),
                        "economy": (
                            bowling_runs / bowling_balls * 6
                            if bowling_balls
                            else None
                        ),
                        "team_run_share": (
                            float(
                                season_rows["batting_runs"].sum()
                                / season_rows["team_runs"].sum()
                            )
                            if season_rows["team_runs"].sum()
                            else None
                        ),
                    }
                )
            return sorted(
                summaries,
                key=lambda row: (row["format"], row["season"]),
                reverse=True,
            )

        pressure_batting = player_matches.loc[
            player_matches["batting_pressure_rows"] > 0
        ]
        pressure_bowling = player_matches.loc[
            player_matches["bowling_pressure_rows"] > 0
        ]
        batting_pressure_runs = float(
            pressure_batting["batting_pressure_runs"].sum()
        )
        batting_pressure_balls = float(
            pressure_batting["batting_pressure_balls"].sum()
        )
        bowling_pressure_balls = float(
            pressure_bowling["bowling_pressure_balls"].sum()
        )
        bowling_pressure_conceded = float(
            pressure_bowling["bowling_pressure_conceded"].sum()
        )
        batter_rank_row = (
            batter_rank.loc[player_id].to_dict()
            if player_id in batter_rank.index
            else {}
        )
        bowler_rank_row = (
            bowler_rank.loc[player_id].to_dict()
            if player_id in bowler_rank.index
            else {}
        )
        player_pressure = pressure_baselines.get(player_id, {})
        batter_pressure_baseline = player_pressure.get("batting", {})
        bowler_pressure_baseline = player_pressure.get("bowling", {})

        def match_record(row: pd.Series) -> dict[str, Any]:
            return {
                "date": str(row["match_date"]),
                "match_id": int(row["match_id"]),
                "competition": str(row["comp_name"]),
                "format": str(row["match_format"]),
                "season": str(row["season"]),
                "team": str(row["team_name"]),
                "opponent": str(row["opponent"]),
                "result": str(row["result"]),
                "won": bool(row["won_match"]),
                "batting_runs": int(row["batting_runs"]),
                "batting_balls": int(row["batting_balls"]),
                "batting_strike_rate": _clean_value(row["batting_strike_rate"]),
                "fours": int(row["fours"]),
                "sixes": int(row["sixes"]),
                "dismissals": int(row["batting_dismissals"]),
                "batting_run_contribution": _clean_value(
                    row["batting_run_contribution"]
                ),
                "bowling_overs": (
                    f"{int(row['bowling_balls'] // 6)}."
                    f"{int(row['bowling_balls'] % 6)}"
                ),
                "bowling_legal_balls": int(row["bowling_balls"]),
                "bowling_conceded": int(row["bowling_conceded"]),
                "bowling_wickets": int(row["bowling_wickets"]),
                "bowling_economy": _clean_value(row["bowling_economy"]),
                "pressure_batting_runs": int(row["batting_pressure_runs"]),
                "pressure_batting_balls": int(row["batting_pressure_balls"]),
                "pressure_batting_strike_rate": _clean_value(
                    row["batting_pressure_strike_rate"]
                ),
                "pressure_team_batter_runs": _clean_value(
                    row["batting_pressure_team_runs"]
                ),
                "pressure_batting_run_share": _clean_value(
                    row["share_of_pressure_team_runs"]
                ),
                "pressure_batting_wickets_lost": _clean_value(
                    row["batting_pressure_team_wickets"]
                ),
                "pressure_bowling_balls": int(row["bowling_pressure_balls"]),
                "pressure_bowling_conceded": int(
                    row["bowling_pressure_conceded"]
                ),
                "pressure_bowling_wickets": int(
                    row["bowling_pressure_wickets"]
                ),
                "pressure_bowling_economy": _clean_value(
                    row["bowling_pressure_economy"]
                ),
                "pressure_opposition_runs": _clean_value(
                    row["opposition_pressure_runs"]
                ),
                "pressure_opposition_wickets": _clean_value(
                    row["opposition_pressure_wickets"]
                ),
                "pressure_wicket_share": _clean_value(
                    row["share_of_pressure_opposition_wickets"]
                ),
                "pressure_conceded_run_share": _clean_value(
                    row["share_of_pressure_opposition_runs_conceded"]
                ),
            }

        raw_name = names.get(player_id)
        player_rows.append(
            {
                "player_id": int(player_id),
                "player_name": str(raw_name)
                if raw_name is not None
                else f"Unmapped player ID {player_id}",
                "mapped_name": raw_name is not None,
                "matches": int(player_matches["match_id"].nunique()),
                "teams": sorted(
                    str(value)
                    for value in player_matches["team_name"].dropna().unique()
                ),
                "formats": sorted(
                    str(value)
                    for value in player_matches["match_format"].dropna().unique()
                ),
                "first_match": (
                    str(player_matches["match_date"].min())
                    if not player_matches.empty
                    else None
                ),
                "last_match": (
                    str(player_matches["match_date"].max())
                    if not player_matches.empty
                    else None
                ),
                "batting": {
                    **career_batting,
                    "pressure_runs": int(batting_pressure_runs),
                    "pressure_balls": int(batting_pressure_balls),
                    "pressure_strike_rate": (
                        batting_pressure_runs / batting_pressure_balls * 100
                        if batting_pressure_balls
                        else None
                    ),
                    "pressure_matches": int(
                        pressure_batting["match_id"].nunique()
                    ),
                    "baseline_balls": batter_pressure_baseline.get(
                        "baseline_balls", 0
                    ),
                    "pressure_baseline_rate": _clean_value(
                        batter_pressure_baseline.get("baseline_rate")
                    ),
                    "pressure_rate_change": _clean_value(
                        batter_pressure_baseline.get("raw_rate_change")
                    ),
                    "pressure_adjusted_rate_change": _clean_value(
                        batter_pressure_baseline.get("adjusted_rate_change")
                    ),
                    "pressure_by_format": _clean_value(
                        batter_pressure_baseline.get("by_format", [])
                    ),
                    "pressure_team_run_share": (
                        float(
                            pressure_batting["batting_pressure_runs"].sum()
                            / pressure_batting[
                                "batting_pressure_team_runs"
                            ].sum()
                        )
                        if pressure_batting[
                            "batting_pressure_team_runs"
                        ].sum()
                        else None
                    ),
                    "rank": (
                        int(batter_rank_row["rank"])
                        if batter_rank_row
                        else None
                    ),
                    "baseline_strike_rate": _clean_value(
                        batter_rank_row.get("baseline_strike_rate")
                    ),
                    "adjusted_strike_rate_change": _clean_value(
                        batter_rank_row.get("reliability_adjusted_score")
                    ),
                    "pressure_match_consistency": _clean_value(
                        batter_rank_row.get("pressure_match_consistency")
                    ),
                },
                "bowling": {
                    **career_bowling,
                    "pressure_balls": int(bowling_pressure_balls),
                    "pressure_overs": (
                        f"{int(bowling_pressure_balls // 6)}."
                        f"{int(bowling_pressure_balls % 6)}"
                    ),
                    "pressure_conceded": int(bowling_pressure_conceded),
                    "pressure_wickets": int(
                        pressure_bowling["bowling_pressure_wickets"].sum()
                    ),
                    "pressure_economy": (
                        bowling_pressure_conceded
                        / bowling_pressure_balls
                        * 6
                        if bowling_pressure_balls
                        else None
                    ),
                    "pressure_matches": int(
                        pressure_bowling["match_id"].nunique()
                    ),
                    "baseline_balls": bowler_pressure_baseline.get(
                        "baseline_balls", 0
                    ),
                    "pressure_baseline_economy": _clean_value(
                        bowler_pressure_baseline.get("baseline_rate")
                    ),
                    "pressure_economy_improvement": _clean_value(
                        bowler_pressure_baseline.get("raw_rate_change")
                    ),
                    "pressure_adjusted_economy_improvement": _clean_value(
                        bowler_pressure_baseline.get("adjusted_rate_change")
                    ),
                    "pressure_wicket_rate_improvement": _clean_value(
                        bowler_pressure_baseline.get("wickets_per_24_change")
                    ),
                    "pressure_by_format": _clean_value(
                        bowler_pressure_baseline.get("by_format", [])
                    ),
                    "pressure_wicket_share": (
                        float(
                            pressure_bowling["bowling_pressure_wickets"].sum()
                            / pressure_bowling[
                                "opposition_pressure_wickets"
                            ].sum()
                        )
                        if pressure_bowling[
                            "opposition_pressure_wickets"
                        ].sum()
                        else None
                    ),
                    "pressure_conceded_run_share": (
                        float(
                            pressure_bowling[
                                "bowling_pressure_conceded"
                            ].sum()
                            / pressure_bowling[
                                "opposition_pressure_runs"
                            ].sum()
                        )
                        if pressure_bowling[
                            "opposition_pressure_runs"
                        ].sum()
                        else None
                    ),
                    "rank": (
                        int(bowler_rank_row["rank"])
                        if bowler_rank_row
                        else None
                    ),
                    "baseline_economy": _clean_value(
                        bowler_rank_row.get("baseline_economy")
                    ),
                    "economy_improvement": _clean_value(
                        bowler_rank_row.get("economy_improvement")
                    ),
                    "wickets_per_24_improvement": _clean_value(
                        bowler_rank_row.get("wickets_per_24_improvement")
                    ),
                    "bowling_score": _clean_value(
                        bowler_rank_row.get("bowling_score")
                    ),
                    "pressure_match_consistency": _clean_value(
                        bowler_rank_row.get("pressure_match_consistency")
                    ),
                },
                "seasons": summarize(player_matches),
                "match_records": [
                    match_record(row)
                    for _, row in player_matches.iterrows()
                ],
            }
        )
    return player_rows


def build_dashboard_payload(
    result: dict[str, Any], datasets: dict[str, pd.DataFrame]
) -> dict[str, Any]:
    chase = result["chase_deliveries"]
    competitions = _selected_competitions(datasets["competitions"])
    player_names = _modeled_players(
        datasets["competition_team_player_mapping"], competitions
    )
    by_format: dict[str, Any] = {}
    for match_format in sorted(chase["match_format"].dropna().unique()):
        subset = chase.loc[chase["match_format"] == match_format]
        batter_all, batter_top = rank_batters(subset, player_names)
        bowler_all, bowler_top = rank_bowlers(subset, player_names)
        by_format[str(match_format)] = {
            "batters": _records(batter_all),
            "batters_top10": _records(batter_top),
            "bowlers": _records(bowler_all),
            "bowlers_top10": _records(bowler_top),
            "matches": int(subset["match_id"].nunique()),
            "deliveries": int(len(subset)),
        }

    profiles = _player_profiles(datasets, chase, result)
    phase1 = validate_datasets(datasets)
    return {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "diagnostics": _clean_value(result["diagnostics"]),
        "datasets": {
            name: {
                "rows": profile["rows"],
                "columns": profile["column_count"],
                "missing_cells": sum(
                    column["missing"] for column in profile["columns"]
                ),
                "duplicate_rows": profile["exact_duplicate_rows"],
            }
            for name, profile in profile_datasets(datasets).items()
        },
        "relationships": _clean_value(phase1["relationships"]),
        "pressure_by_phase": _clean_value(_phase_pressure(chase)),
        "players": _clean_value(profiles),
        "global": {
            "batters": _records(result["batter_leaderboard"]),
            "batters_top10": _records(result["batter_top10"]),
            "bowlers": _records(result["bowler_leaderboard"]),
            "bowlers_top10": _records(result["bowler_top10"]),
            "matches": int(chase["match_id"].nunique()),
            "deliveries": int(len(chase)),
        },
        "formats": by_format,
    }


def build_dashboard_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _DASHBOARD_TEMPLATE.replace("__DASHBOARD_DATA__", data)


def write_dashboard(
    payload: dict[str, Any], output_path: Path | None = None
) -> Path:
    target = output_path or Path(__file__).resolve().parents[1] / "reports" / "dashboard.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_dashboard_html(payload), encoding="utf-8")
    return target


def main() -> None:
    data_dir = resolve_data_dir()
    datasets = load_datasets(data_dir)
    result = run_analysis(data_dir=data_dir)
    payload = build_dashboard_payload(result, datasets)
    dashboard = write_dashboard(payload)
    print(f"Dashboard: {dashboard}")
    print(
        f"Includes {payload['global']['matches']:,} matches, "
        f"{payload['global']['deliveries']:,} chase deliveries, "
        f"{len(payload['global']['batters']):,} eligible batters, and "
        f"{len(payload['global']['bowlers']):,} eligible bowlers."
    )


_DASHBOARD_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#101916">
<title>SupeRR Selector | Pressure Analytics</title>
<style>
:root{color-scheme:dark;--bg:#101916;--panel:#17231e;--panel2:#1d2b24;--line:#2c4035;--text:#eef4e9;--muted:#a9baaa;--lime:#c8f169;--mint:#65ddae;--orange:#ffb86b;--red:#ff8a7a;--blue:#8dc8ff;--shadow:0 12px 36px #07100c66}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 82% -15%,#354d3a 0,transparent 35%),var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select{font:inherit}button{cursor:pointer}.shell{max-width:1440px;margin:auto;padding:28px 34px 60px}.masthead{display:flex;align-items:center;justify-content:space-between;gap:22px;border-bottom:1px solid var(--line);padding-bottom:25px}.brand{display:flex;align-items:center;gap:14px}.brand-mark{width:44px;height:44px;border-radius:14px;background:var(--lime);color:#152018;display:grid;place-items:center;font-weight:950;font-size:19px;box-shadow:0 0 34px #c8f16944}.eyebrow{text-transform:uppercase;letter-spacing:.16em;color:var(--mint);font-size:11px;font-weight:800}.brand h1{font-size:19px;line-height:1.2;margin:3px 0 0}.header-right{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.pill{border:1px solid var(--line);background:#101a15aa;padding:8px 12px;border-radius:999px;color:var(--muted);font-size:12px}.hero{padding:32px 0 23px;display:grid;grid-template-columns:1fr auto;align-items:end;gap:24px}.hero h2{font-size:clamp(28px,4vw,47px);letter-spacing:-.04em;line-height:1.06;margin:8px 0 10px;max-width:820px}.hero p{color:var(--muted);max-width:760px;margin:0}.hero-callout{padding:15px 19px;background:linear-gradient(135deg,#26372b,#1b2a23);border:1px solid var(--line);border-radius:16px;min-width:220px}.hero-callout strong{display:block;color:var(--lime);font-size:19px}.hero-callout span{font-size:12px;color:var(--muted)}.nav{display:flex;gap:8px;overflow:auto;border-bottom:1px solid var(--line);margin:9px 0 22px}.nav button{white-space:nowrap;border:0;border-bottom:2px solid transparent;padding:12px 15px;background:none;color:var(--muted);font-weight:750}.nav button.active{border-color:var(--lime);color:var(--lime)}.view{display:none}.view.active{display:block}.grid{display:grid;gap:16px}.kpis{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:18px}.card{background:linear-gradient(145deg,#19251f,#152019);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:var(--shadow)}.kpi-label{color:var(--muted);font-size:12px;font-weight:700}.kpi-value{font-size:32px;font-weight:850;letter-spacing:-.04em;margin:4px 0}.kpi-note{font-size:12px;color:#90a194}.two-col{grid-template-columns:repeat(2,minmax(0,1fr));margin:16px 0}.three-col{grid-template-columns:repeat(3,minmax(0,1fr))}.card h3{margin:0 0 4px;font-size:16px}.sub{color:var(--muted);font-size:12px;margin:0 0 17px}.bar-list{display:grid;gap:11px}.bar-row{display:grid;grid-template-columns:minmax(90px,145px) 1fr 72px;gap:11px;align-items:center;font-size:12px}.bar-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#dce7da}.bar-track{height:10px;background:#29392e;border-radius:20px;overflow:hidden}.bar-fill{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--mint),var(--lime));min-width:2px}.bar-fill.orange{background:linear-gradient(90deg,#ff9e59,#ffe080)}.bar-value{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}.chart-legend{display:flex;gap:15px;flex-wrap:wrap;color:var(--muted);font-size:11px;margin:10px 0}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}.scatter-wrap{width:100%;overflow:hidden}.scatter-wrap svg{display:block;width:100%;height:auto}.scatter-label{fill:#9eb0a1;font-size:11px}.scatter-grid{stroke:#314338;stroke-width:1}.scatter-diagonal{stroke:#829688;stroke-dasharray:5 5;opacity:.7}.point{stroke:#142019;stroke-width:1.5}.point.top{stroke:#fff;stroke-width:2}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:15px}.toolbar input,.toolbar select{background:#121c16;border:1px solid var(--line);color:var(--text);border-radius:10px;padding:10px 12px;outline:none}.toolbar input{min-width:210px;flex:1}.toolbar select{min-width:135px}.button{border:1px solid var(--line);border-radius:10px;padding:9px 13px;background:#25342a;color:var(--text);font-weight:700;text-decoration:none}.button:hover{border-color:var(--lime);color:var(--lime)}.table-wrap{overflow:auto;max-height:650px;border:1px solid var(--line);border-radius:12px}table{width:100%;border-collapse:collapse;min-width:800px}th,td{padding:10px 12px;text-align:right;border-bottom:1px solid #293a30;white-space:nowrap;font-variant-numeric:tabular-nums}th{position:sticky;top:0;background:#202e25;color:#cad7c9;font-size:11px;text-transform:uppercase;letter-spacing:.07em;cursor:pointer;z-index:1}td{font-size:12px;color:#e2ebdf}td:first-child,th:first-child{text-align:left}td.name,th.name{text-align:left}tbody tr:hover{background:#25362b}.rank{color:var(--lime);font-weight:850}.badge{display:inline-block;padding:3px 8px;border-radius:999px;background:#263a2d;color:var(--mint);font-size:10px;font-weight:800}.section-head{display:flex;justify-content:space-between;align-items:end;gap:16px;margin:8px 0 16px}.section-head h2{margin:0;font-size:24px}.method{max-width:900px}.method h3{margin-top:24px;color:var(--lime)}.method p,.method li{color:#c4d1c4}.method code{color:var(--mint);background:#142019;padding:2px 5px;border-radius:5px}.quality-list{display:grid;gap:10px}.quality-item{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;border-bottom:1px solid var(--line);padding:10px 0}.quality-item span{color:var(--muted)}.quality-item strong{color:var(--orange);text-align:right}.file-list{display:grid;gap:8px}.file-link{display:flex;justify-content:space-between;align-items:center;text-decoration:none;color:var(--text);border:1px solid var(--line);background:#121c16;border-radius:10px;padding:11px 13px}.file-link:hover{border-color:var(--lime)}.empty{color:var(--muted);padding:24px;text-align:center}.table-caption{color:var(--muted);font-size:12px;margin:8px 0 12px}.footer{border-top:1px solid var(--line);margin-top:35px;padding-top:16px;color:#839487;font-size:11px;display:flex;justify-content:space-between;gap:15px}.alert{padding:12px 14px;border:1px solid #674b30;background:#35291d;color:#ffd9a8;border-radius:12px;font-size:12px;margin-bottom:14px}.profile-hero{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap}.profile-hero h2{margin:5px 0;font-size:30px}.profile-meta{color:var(--muted);font-size:13px}.profile-kpis{grid-template-columns:repeat(4,minmax(0,1fr));margin:15px 0}.role-card{min-height:180px}.role-card .kpi-value{font-size:26px}.profile-selector{min-width:min(420px,100%);flex:1}.profile-selector select{width:100%;min-width:240px}.profile-block-title{display:flex;justify-content:space-between;align-items:center;gap:12px}.profile-block-title h3{margin:0}.pressure-positive{color:var(--lime)}.pressure-negative{color:var(--orange)}.record-result{max-width:220px;overflow:hidden;text-overflow:ellipsis;text-align:left!important}.profile-note{font-size:12px;color:var(--muted);line-height:1.55}.player-search{max-width:340px}
@media(max-width:900px){.shell{padding:20px 18px 40px}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{grid-template-columns:1fr}.hero-callout{max-width:280px}.three-col{grid-template-columns:1fr}}@media(max-width:620px){.two-col{grid-template-columns:1fr}.header-right{display:none}.shell{padding:15px 12px 30px}.kpi-value{font-size:25px}.card{padding:15px}.bar-row{grid-template-columns:90px 1fr 62px;gap:7px}.footer{display:block}.toolbar input{min-width:100%}}
@media(max-width:900px){.profile-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.profile-kpis{grid-template-columns:1fr 1fr}.profile-hero h2{font-size:24px}}
</style>
</head>
<body>
<main class="shell">
  <header class="masthead">
    <div class="brand"><div class="brand-mark">SR</div><div><div class="eyebrow">SupeRR Selector · Season 2</div><h1>Pressure Analytics</h1></div></div>
    <div class="header-right"><span class="pill">IPL + T20I</span><span class="pill" id="updated"></span></div>
  </header>
  <section class="hero">
    <div><div class="eyebrow">Phase 2 · Decision support</div><h2>Who performs when the chase gets tight?</h2><p>Explore pressure performance against each player's own baseline, inspect the evidence behind the rankings, and download the complete analysis.</p></div>
    <div class="hero-callout"><strong>Pressure ≠ reputation</strong><span>Rankings are derived from supplied ball-by-ball records and explicit eligibility rules.</span></div>
  </section>
  <nav class="nav" aria-label="Dashboard sections">
    <button class="active" data-view="overview">Overview</button>
    <button data-view="batters">Batters</button>
    <button data-view="bowlers">Bowlers</button>
    <button data-view="players">Player explorer</button>
    <button data-view="quality">Data &amp; methodology</button>
  </nav>
  <section class="view active" id="overview">
    <div class="grid kpis" id="kpis"></div>
    <div class="grid two-col">
      <article class="card"><h3>Top pressure batters</h3><p class="sub">Reliability-adjusted strike-rate improvement vs. personal baseline</p><div class="bar-list" id="batter-bars"></div></article>
      <article class="card"><h3>Top pressure bowlers</h3><p class="sub">Equal-weight standardized economy and wicket-rate improvement</p><div class="bar-list" id="bowler-bars"></div></article>
    </div>
    <div class="grid two-col">
      <article class="card"><h3>Batter: pressure vs. baseline</h3><p class="sub">Each point is an eligible player; below the diagonal means a higher pressure strike rate.</p><div class="chart-legend"><span><i class="dot" style="background:var(--lime)"></i>Top 10</span><span><i class="dot" style="background:var(--blue)"></i>Other eligible players</span></div><div class="scatter-wrap" id="batter-scatter"></div></article>
      <article class="card"><h3>Bowler: pressure vs. baseline</h3><p class="sub">Above the diagonal means lower pressure economy; lower is better.</p><div class="chart-legend"><span><i class="dot" style="background:var(--orange)"></i>Top 10</span><span><i class="dot" style="background:var(--blue)"></i>Other eligible players</span></div><div class="scatter-wrap" id="bowler-scatter"></div></article>
    </div>
    <article class="card"><h3>Where pressure appears in the chase</h3><p class="sub">Share of modeled delivery states labelled pressure in each phase (early &lt;30%, middle 30–75%, late ≥75% of innings balls used).</p><div class="toolbar"><select id="phase-format"><option value="All">All formats</option></select></div><div class="grid two-col"><div><div class="eyebrow">Batting pressure</div><div class="bar-list" id="phase-bat"></div></div><div><div class="eyebrow">Bowling pressure</div><div class="bar-list" id="phase-bowl"></div></div></div></article>
  </section>
  <section class="view" id="batters">
    <div class="section-head"><div><div class="eyebrow">Scoring under pressure</div><h2>Batter leaderboard</h2></div><span class="badge" id="batter-count"></span></div>
    <div class="grid two-col">
      <article class="card"><h3>Pressure strike rate by player</h3><p class="sub">Top 10 for the selected format.</p><div class="bar-list" id="batter-format-bars"></div></article>
      <article class="card"><h3>Personal baseline comparison</h3><p class="sub">Pressure and baseline strike rate for the selected format.</p><div class="scatter-wrap" id="batter-format-scatter"></div></article>
    </div>
    <div class="toolbar"><select id="batter-format"></select><input id="batter-search" type="search" placeholder="Search batter name"><button class="button" id="download-batters">Download filtered CSV</button></div>
    <p class="table-caption">Click a column heading to sort. Eligibility requires 60 pressure balls, 120 baseline balls, and 3 pressure matches.</p><div class="table-wrap" id="batter-table"></div>
  </section>
  <section class="view" id="bowlers">
    <div class="section-head"><div><div class="eyebrow">Run control + wickets</div><h2>Bowler leaderboard</h2></div><span class="badge" id="bowler-count"></span></div>
    <div class="grid two-col">
      <article class="card"><h3>Pressure economy improvement</h3><p class="sub">Positive values indicate lower economy than the player's baseline.</p><div class="bar-list" id="bowler-format-bars"></div></article>
      <article class="card"><h3>Pressure economy by player</h3><p class="sub">Above the diagonal is lower pressure economy (better); top 10 are highlighted.</p><div class="scatter-wrap" id="bowler-format-scatter"></div></article>
    </div>
    <div class="toolbar"><select id="bowler-format"></select><input id="bowler-search" type="search" placeholder="Search bowler name"><button class="button" id="download-bowlers">Download filtered CSV</button></div>
    <p class="table-caption">Bowling score averages two cohort-standardized, sample-size-shrunk improvements.</p><div class="table-wrap" id="bowler-table"></div>
  </section>
  <section class="view" id="players">
    <div class="section-head"><div><div class="eyebrow">Every player in the supplied IPL + T20I records</div><h2>Player explorer</h2></div><span class="badge" id="player-count"></span></div>
    <div class="toolbar">
      <input id="player-search" class="player-search" type="search" list="player-options" placeholder="Search any player name or ID">
      <datalist id="player-options"></datalist>
      <select id="player-select" class="profile-selector" aria-label="Select a player"></select>
      <select id="player-format" aria-label="Filter player match records"><option value="All">All formats</option></select>
      <button class="button" id="download-player-records">Download match records</button>
      <button class="button" id="download-player-profile">Download player profile JSON</button>
    </div>
    <div id="player-profile"><div class="card empty">Select a player to inspect career stats, pressure performance, team contribution, and match-by-match records.</div></div>
  </section>
  <section class="view" id="quality">
    <div class="section-head"><div><div class="eyebrow">Trust, traceability, caveats</div><h2>Data &amp; methodology</h2></div></div>
    <div class="grid two-col">
      <article class="card"><h3>Dataset inventory</h3><p class="sub">Source CSVs read during the analysis; originals are not modified.</p><div class="quality-list" id="dataset-list"></div></article>
      <article class="card"><h3>Join integrity</h3><p class="sub">Unmatched key counts are checks, not silent row deletions.</p><div class="quality-list" id="relationship-list"></div></article>
    </div>
    <div class="grid two-col">
      <article class="card"><h3>Analysis coverage</h3><div class="quality-list" id="diagnostic-list"></div></article>
      <article class="card"><h3>Reports &amp; data downloads</h3><p class="sub">The dashboard works offline; links below open or download the generated files.</p><div class="file-list" id="file-list"></div></article>
    </div>
    <article class="card method" style="margin-top:16px"><h3>How to read the rankings</h3>
      <p><b>Pressure context.</b> Only live second-innings chases are modeled. Separate batting and bowling pressure indices combine required-run-rate percentile, wickets lost, and innings progress; the highest quartile in each format is labelled pressure.</p>
      <p><b>Batters.</b> Strike rate under pressure is compared with the same player's non-pressure chase baseline in each format. The adjusted change is shrunk toward zero for smaller pressure samples.</p>
      <p><b>Bowlers.</b> Economy and credited wickets are measured per legal ball, with byes, legbyes, and penalty extras excluded from bowler-conceded runs. Rankings equally weight standardized, shrunk economy improvement and wicket-rate improvement.</p>
      <p><b>Eligibility.</b> At least 60 pressure balls, 120 baseline balls, and 3 pressure matches with a usable same-format baseline. Top-10 confidence intervals bootstrap pressure matches, holding the baseline fixed.</p>
      <h3>Important limitations</h3>
      <ul><li>This is a chase-only model; first-innings pressure, venue, pitch, opposition strength, and win-probability context are not modeled.</li><li>Pressure cutoffs are cohort-relative. The 75th-percentile cutoff, index weights, and exposure thresholds are explicit modeling choices.</li><li>Delivery legality and revised innings length are inferred from the CSV labels. Source rows after target completion or innings quota are excluded from state modeling but are preserved in the files.</li><li>Bootstrap intervals do not include baseline or threshold uncertainty; this is descriptive analysis, not a causal or future-performance claim.</li></ul>
      <h3>Regenerate</h3><p>From the project directory run <code>python src/dashboard.py</code>. This rebuilds the ranking CSVs, methodology report, and this standalone dashboard. Open <code>reports/dashboard.html</code> in a browser; no server or external libraries are required.</p>
    </article>
  </section>
  <footer class="footer"><span>SupeRR Selector · Season 2 · Analytics workbench</span><span id="footer-source"></span></footer>
</main>
<script id="dashboard-data" type="application/json">__DASHBOARD_DATA__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("dashboard-data").textContent);
const $=id=>document.getElementById(id);
const fmt=(value,digits=1)=>value==null||!Number.isFinite(Number(value))?"—":Number(value).toLocaleString(undefined,{maximumFractionDigits:digits,minimumFractionDigits:0});
const pct=(value)=>value==null?"—":`${fmt(Number(value)*100,0)}%`;
const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const selectedFormat=id=>$(id).value||"All";
const rankings=(kind,format)=>{
 if(format==="All") return DATA.global[kind];
 return DATA.formats[format]?.[kind]||[];
};
const topRankings=(kind,format)=>{
 if(format==="All") return DATA.global[`${kind}_top10`];
 return DATA.formats[format]?.[`${kind}_top10`]||[];
};
function fillFormatSelect(select){
 if(!Array.from(select.options).some(option=>option.value==="All")){const all=document.createElement("option");all.value="All";all.textContent="All formats";select.add(all,0)}
 for(const name of Object.keys(DATA.formats)){const option=document.createElement("option");option.value=name;option.textContent=name==="T20"?"IPL (T20)":name;select.append(option)}
}
function makeKpi(label,value,note){
 const card=document.createElement("article");card.className="card";
 const a=document.createElement("div");a.className="kpi-label";a.textContent=label;
 const b=document.createElement("div");b.className="kpi-value";b.textContent=value;
 const c=document.createElement("div");c.className="kpi-note";c.textContent=note;
 card.append(a,b,c);return card
}
function renderKpis(){
 const d=DATA.diagnostics;
 const items=[
  ["Eligible chases",fmt(d.eligible_chase_matches,0),"Winner + target verified"],
  ["Modeled delivery states",fmt(DATA.global.deliveries,0),"After target / innings end"],
  ["Eligible batters",fmt(DATA.global.batters.length,0),"Minimum exposure applied"],
  ["Eligible bowlers",fmt(DATA.global.bowlers.length,0),"Minimum exposure applied"]
 ];
 $("kpis").replaceChildren(...items.map(([a,b,c])=>makeKpi(a,b,c)));
 $("updated").textContent=`Generated ${new Date(DATA.generated_at).toLocaleString()}`;
 $("footer-source").textContent=`${fmt(DATA.global.matches,0)} matches · ${fmt(DATA.global.deliveries,0)} deliveries`;
}
function renderBars(containerId,rows,labelKey,valueKey,color=""){
 const container=$(containerId);container.replaceChildren();
 if(!rows.length){container.textContent="No eligible records for this selection.";container.className="empty";return}
 container.className="bar-list";
 const vals=rows.map(row=>Number(row[valueKey]||0)),max=Math.max(...vals.map(Math.abs),1);
 for(const row of rows){
  const line=document.createElement("div");line.className="bar-row";
  const name=document.createElement("span");name.className="bar-name";name.textContent=row[labelKey]??"Unknown";
  const track=document.createElement("div");track.className="bar-track";
  const fill=document.createElement("div");fill.className=`bar-fill ${color}`;fill.style.width=`${Math.max(1,Math.min(100,Math.abs(Number(row[valueKey]||0))/max*100))}%`;track.append(fill);
  const value=document.createElement("span");value.className="bar-value";value.textContent=fmt(row[valueKey],1);
  line.append(name,track,value);container.append(line)
 }
}
function renderScatter(containerId,rows,xKey,yKey,topRows,reverse=false){
 const container=$(containerId);container.replaceChildren();
 if(!rows.length){container.textContent="No eligible records for this selection.";container.className="empty";return}
 container.className="scatter-wrap";
 const width=540,height=330,pad={left:54,right:22,top:18,bottom:48};
 const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
 svg.setAttribute("viewBox",`0 0 ${width} ${height}`);svg.setAttribute("role","img");
 svg.setAttribute("aria-label",`${xKey} versus ${yKey}`);
 const nums=rows.flatMap(r=>[Number(r[xKey]),Number(r[yKey])]).filter(Number.isFinite);
 if(!nums.length){container.textContent="Metrics unavailable.";return}
 let min=Math.min(...nums),max=Math.max(...nums);if(min===max){min-=1;max+=1}
 const gap=(max-min)*.08;min-=gap;max+=gap;
 const x=v=>pad.left+(Number(v)-min)/(max-min)*(width-pad.left-pad.right);
 const y=v=>height-pad.bottom-(Number(v)-min)/(max-min)*(height-pad.top-pad.bottom);
 for(let i=0;i<5;i++){
  const value=min+(max-min)*i/4;
  const line=document.createElementNS(svg.namespaceURI,"line");line.setAttribute("x1",pad.left);line.setAttribute("x2",width-pad.right);line.setAttribute("y1",y(value));line.setAttribute("y2",y(value));line.setAttribute("class","scatter-grid");svg.append(line);
  const label=document.createElementNS(svg.namespaceURI,"text");label.setAttribute("x",pad.left-8);label.setAttribute("y",y(value)+4);label.setAttribute("text-anchor","end");label.setAttribute("class","scatter-label");label.textContent=fmt(value,0);svg.append(label)
 }
 const diagonal=document.createElementNS(svg.namespaceURI,"line");diagonal.setAttribute("x1",x(min));diagonal.setAttribute("x2",x(max));diagonal.setAttribute("y1",y(min));diagonal.setAttribute("y2",y(max));diagonal.setAttribute("class","scatter-diagonal");svg.append(diagonal);
 const tops=new Set(topRows.map(r=>String(r.player_id)));
 for(const row of rows){
  const xv=Number(row[xKey]),yv=Number(row[yKey]);if(!Number.isFinite(xv)||!Number.isFinite(yv))continue;
  const point=document.createElementNS(svg.namespaceURI,"circle");point.setAttribute("cx",x(xv));point.setAttribute("cy",y(yv));point.setAttribute("r",tops.has(String(row.player_id))?"5":"3.5");point.setAttribute("class",`point${tops.has(String(row.player_id))?" top":""}`);point.setAttribute("fill",tops.has(String(row.player_id))?(reverse?"#ffb86b":"#c8f169"):"#8dc8ff");
  const title=document.createElementNS(svg.namespaceURI,"title");title.textContent=`${row.player_name}: pressure ${fmt(row[xKey],1)}, baseline ${fmt(row[yKey],1)}`;point.append(title);svg.append(point)
 }
 const xLabel=document.createElementNS(svg.namespaceURI,"text");xLabel.setAttribute("x",(pad.left+width-pad.right)/2);xLabel.setAttribute("y",height-9);xLabel.setAttribute("text-anchor","middle");xLabel.setAttribute("class","scatter-label");xLabel.textContent=reverse?"Pressure economy (lower is better)":"Pressure strike rate";svg.append(xLabel);
 const yLabel=document.createElementNS(svg.namespaceURI,"text");yLabel.setAttribute("transform",`translate(14 ${(height-pad.bottom+pad.top)/2}) rotate(-90)`);yLabel.setAttribute("text-anchor","middle");yLabel.setAttribute("class","scatter-label");yLabel.textContent=reverse?"Baseline economy":"Baseline strike rate";svg.append(yLabel);
 container.append(svg)
}
function table(containerId,rows,columns,kind,search=""){
 const root=$(containerId);root.replaceChildren();
 const query=search.trim().toLocaleLowerCase();
 const filtered=rows.filter(row=>String(row.player_name||"").toLocaleLowerCase().includes(query));
 if(!filtered.length){root.textContent="No players match this filter.";root.className="empty";return filtered}
 const wrapper=document.createElement("table"),thead=document.createElement("thead"),tr=document.createElement("tr");
 for(const [key,label] of columns){
  const th=document.createElement("th");th.textContent=label;if(key==="player_name"||key==="rank")th.className="name";
  th.addEventListener("click",()=>{const dir=th.dataset.dir==="asc"?"desc":"asc";for(const h of tr.children)delete h.dataset.dir;th.dataset.dir=dir;const sorted=[...filtered].sort((a,b)=>{const av=a[key],bv=b[key];if(av==null)return 1;if(bv==null)return -1;const compare=typeof av==="number"&&typeof bv==="number"?av-bv:String(av).localeCompare(String(bv));return dir==="asc"?compare:-compare});table(containerId,sorted,columns,kind,query)});
  tr.append(th)
 }
 thead.append(tr);const tbody=document.createElement("tbody");
 for(const row of filtered){const line=document.createElement("tr");for(const [key] of columns){const cell=document.createElement("td");if(key==="player_name")cell.className="name";if(key==="rank")cell.className="rank";const value=row[key];cell.textContent=key==="pressure_match_consistency"?pct(value):key==="player_name"?String(value??"—"):fmt(value,key.includes("score")||key.includes("change")||key.includes("improvement")?2:1);line.append(cell)}tbody.append(line)}
 wrapper.append(thead,tbody);root.append(wrapper);return filtered
}
const BAT_COLUMNS=[["rank","Rank"],["player_name","Player"],["reliability_adjusted_score","Adjusted SR change"],["pressure_strike_rate","Pressure SR"],["baseline_strike_rate","Baseline SR"],["strike_rate_change","Raw SR change"],["pressure_balls","Pressure balls"],["baseline_balls","Baseline balls"],["pressure_matches","Pressure matches"],["pressure_match_consistency","Consistent match share"]];
const BOWL_COLUMNS=[["rank","Rank"],["player_name","Player"],["bowling_score","Bowling score (z)"],["pressure_economy","Pressure econ."],["baseline_economy","Baseline econ."],["economy_improvement","Econ. improvement"],["wickets_per_24_improvement","Wickets / 24-ball change"],["pressure_balls","Pressure balls"],["baseline_balls","Baseline balls"],["pressure_matches","Pressure matches"],["pressure_match_consistency","Consistent match share"]];
function renderBatter(format=selectedFormat("batter-format")){
 const rows=rankings("batters",format),top=topRankings("batters",format);
 $("batter-count").textContent=`${fmt(rows.length,0)} eligible`;
 renderBars("batter-format-bars",top.slice(0,10),"player_name","pressure_strike_rate");
 renderScatter("batter-format-scatter",rows,"pressure_strike_rate","baseline_strike_rate",top);
 const filtered=table("batter-table",rows,BAT_COLUMNS,"batter",$("batter-search").value);
 $("download-batters").onclick=()=>downloadCsv(filtered,BAT_COLUMNS,"batter_leaderboard.csv")
}
function renderBowler(format=selectedFormat("bowler-format")){
 const rows=rankings("bowlers",format),top=topRankings("bowlers",format);
 $("bowler-count").textContent=`${fmt(rows.length,0)} eligible`;
 renderBars("bowler-format-bars",top.slice(0,10),"player_name","economy_improvement","orange");
 renderScatter("bowler-format-scatter",rows,"pressure_economy","baseline_economy",top,true);
 const filtered=table("bowler-table",rows,BOWL_COLUMNS,"bowler",$("bowler-search").value);
 $("download-bowlers").onclick=()=>downloadCsv(filtered,BOWL_COLUMNS,"bowler_leaderboard.csv")
}
function downloadCsv(rows,columns,filename){
 const csv=[columns.map(([,label])=>label).join(","),...rows.map(row=>columns.map(([key])=>{const value=key==="pressure_match_consistency"&&row[key]!=null?Number(row[key]).toFixed(4):row[key];return `"${String(value??"").replace(/"/g,'""')}"`}).join(","))].join("\r\n");
 const link=document.createElement("a");link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));link.download=filename;link.click();URL.revokeObjectURL(link.href)
}
function renderPhase(format=selectedFormat("phase-format")){
 const phases=["Early","Middle","Late"],formats=format==="All"?Object.keys(DATA.pressure_by_phase):[format];
 const results=phases.map(phase=>{const groups=formats.map(name=>DATA.pressure_by_phase[name]?.[phase]).filter(Boolean);if(!groups.length)return null;const count=groups.reduce((a,g)=>a+g.deliveries,0);return {phase,bat:groups.reduce((a,g)=>a+g.batting_pressure_deliveries,0)/count,bowl:groups.reduce((a,g)=>a+g.bowling_pressure_deliveries,0)/count}}).filter(Boolean);
 renderBars("phase-bat",results.map(r=>({name:r.phase,value:r.bat})),"name","value");
 renderBars("phase-bowl",results.map(r=>({name:r.phase,value:r.bowl})),"name","value","orange");
 for(const container of [$("phase-bat"),$("phase-bowl")])for(const value of container.querySelectorAll(".bar-value"))value.textContent=pct(Number(value.textContent))
}
const profilePlayers=DATA.players||[];
let visiblePlayerRecords=[];
function profileCell(value,key){
 if(value==null)return "—";
 if(key.includes("share")||key.includes("contribution")||key.includes("consistency"))return pct(value);
 if(key==="date")return String(value).slice(0,10);
 return fmt(value,key.includes("rate")||key.includes("economy")||key.includes("improvement")?2:1)
}
function buildProfileTable(containerId,rows,columns){
 const root=$(containerId);root.replaceChildren();
 if(!rows.length){root.className="empty";root.textContent="No records for the selected filter.";return}
 root.className="table-wrap";
 const table=document.createElement("table"),head=document.createElement("thead"),headRow=document.createElement("tr");
 for(const [,label] of columns){const th=document.createElement("th");th.textContent=label;headRow.append(th)}
 head.append(headRow);const body=document.createElement("tbody");
 for(const row of rows){const tr=document.createElement("tr");for(const [key] of columns){const td=document.createElement("td");td.textContent=profileCell(row[key],key);if(key==="result")td.className="record-result";tr.append(td)}body.append(tr)}
 table.append(head,body);root.append(table)
}
function appendProfileMetric(container,label,value,note){
 const card=document.createElement("article");card.className="card role-card";
 const title=document.createElement("div");title.className="kpi-label";title.textContent=label;
 const main=document.createElement("div");main.className="kpi-value";main.textContent=value;
 const detail=document.createElement("div");detail.className="kpi-note";detail.textContent=note;
 card.append(title,main,detail);container.append(card)
}
function makeProfileCard(title,description,metrics){
 const card=document.createElement("article");card.className="card";
 const heading=document.createElement("h3");heading.textContent=title;
 const sub=document.createElement("p");sub.className="sub";sub.textContent=description;
 const list=document.createElement("div");list.className="quality-list";
 for(const [label,value] of metrics){const line=document.createElement("div");line.className="quality-item";const a=document.createElement("span");a.textContent=label;const b=document.createElement("strong");b.textContent=value;line.append(a,b);list.append(line)}
 card.append(heading,sub,list);return card
}
function profileTableColumns(rows,columns,containerId){
 buildProfileTable(containerId,rows,columns)
}
function renderPlayerProfile(){
 const player=profilePlayers.find(item=>String(item.player_id)===$("player-select").value);
 const root=$("player-profile");root.replaceChildren();
 if(!player){root.className="card empty";root.textContent="No player is available for this selection.";return}
 root.className="";
 const header=document.createElement("article");header.className="card profile-hero";
 const identity=document.createElement("div");
 const eyebrow=document.createElement("div");eyebrow.className="eyebrow";eyebrow.textContent=`Player ID ${player.player_id}${player.mapped_name?"":" · mapping name unavailable"}`;
 const name=document.createElement("h2");name.textContent=player.player_name;
 const meta=document.createElement("div");meta.className="profile-meta";meta.textContent=`${fmt(player.matches,0)} match appearances · ${player.teams.join(", ")||"No team appearance records"} · ${player.formats.join(", ")||"No format"} · ${player.first_match||"—"} to ${player.last_match||"—"}`;
 identity.append(eyebrow,name,meta);
 const selectButton=document.createElement("button");selectButton.className="button";selectButton.textContent="Share / copy player ID";selectButton.addEventListener("click",async()=>{try{await navigator.clipboard.writeText(String(player.player_id));selectButton.textContent="Player ID copied"}catch{selectButton.textContent=`Player ID ${player.player_id}`}});
 header.append(identity,selectButton);root.append(header);

 const kpis=document.createElement("div");kpis.className="grid profile-kpis";
 appendProfileMetric(kpis,"Career runs",fmt(player.batting.runs,0),`${fmt(player.batting.innings,0)} batting appearances · SR ${fmt(player.batting.strike_rate,1)}`);
 appendProfileMetric(kpis,"Career boundaries",`${fmt(player.batting.fours,0)} fours · ${fmt(player.batting.sixes,0)} sixes`,`${pct(player.batting.team_run_share)} of recorded team runs while batting`);
 appendProfileMetric(kpis,"Career bowling",`${fmt(player.bowling.wickets,0)} wickets`,`${player.bowling.overs} overs · ${fmt(player.bowling.economy,2)} economy`);
 appendProfileMetric(kpis,"Pressure involvement",`${fmt(player.batting.pressure_matches+player.bowling.pressure_matches,0)} role-match records`,`${fmt(player.batting.pressure_runs,0)} batting runs · ${fmt(player.bowling.pressure_wickets,0)} credited bowling wickets`);
 root.append(kpis);

 const roles=document.createElement("div");roles.className="grid two-col";
 const batterChange=player.batting.pressure_rate_change;
 roles.append(
  makeProfileCard("Batting under pressure","High-demand chase deliveries when this player was on strike.",[
   ["Pressure runs / balls",`${fmt(player.batting.pressure_runs,0)} / ${fmt(player.batting.pressure_balls,0)}`],
   ["Pressure strike rate",fmt(player.batting.pressure_strike_rate,2)],
   ["Same-format non-pressure baseline",fmt(player.batting.pressure_baseline_rate,2)],
   ["Pressure SR change",batterChange==null?"Insufficient paired pressure/baseline sample":`${batterChange>=0?"+":""}${fmt(batterChange,2)}`],
   ["Reliability-adjusted change",player.batting.pressure_adjusted_rate_change==null?"Not available":fmt(player.batting.pressure_adjusted_rate_change,2)],
   ["Pressure chase matches",fmt(player.batting.pressure_matches,0)],
   ["Share of team runs during batting-pressure deliveries",pct(player.batting.pressure_team_run_share)],
   ["Pressure rank",player.batting.rank?`#${player.batting.rank} among eligible batters`:"Not eligible for the ranked cohort"]
  ]),
  makeProfileCard("Bowling under pressure","High-leverage chase deliveries when this player was bowling.",[
   ["Pressure wickets (credited)",fmt(player.bowling.pressure_wickets,0)],
   ["Pressure overs / legal balls",`${player.bowling.pressure_overs} / ${fmt(player.bowling.pressure_balls,0)}`],
   ["Pressure economy",fmt(player.bowling.pressure_economy,2)],
   ["Same-format non-pressure baseline",fmt(player.bowling.pressure_baseline_economy,2)],
   ["Economy improvement",player.bowling.pressure_economy_improvement==null?"Insufficient paired pressure/baseline sample":`${player.bowling.pressure_economy_improvement>=0?"+":""}${fmt(player.bowling.pressure_economy_improvement,2)}`],
   ["Wicket-rate change per 24 balls",player.bowling.pressure_wicket_rate_improvement==null?"—":`${player.bowling.pressure_wicket_rate_improvement>=0?"+":""}${fmt(player.bowling.pressure_wicket_rate_improvement,2)}`],
   ["Share of opponent wickets during bowling-pressure deliveries",pct(player.bowling.pressure_wicket_share)],
   ["Share of opponent pressure runs conceded",pct(player.bowling.pressure_conceded_run_share)],
   ["Pressure rank",player.bowling.rank?`#${player.bowling.rank} among eligible bowlers`:"Not eligible for the ranked cohort"]
  ])
 );
 root.append(roles);

 const seasonCard=document.createElement("article");seasonCard.className="card";
 const seasonHead=document.createElement("div");seasonHead.className="profile-block-title";
 const seasonTitle=document.createElement("h3");seasonTitle.textContent="Season and format records";
 const seasonNote=document.createElement("span");seasonNote.className="badge";seasonNote.textContent=`${player.seasons.length} season-format rows`;
 seasonHead.append(seasonTitle,seasonNote);seasonCard.append(seasonHead);
 const seasonColumns=[["format","Format"],["season","Season"],["matches","Matches"],["runs","Runs"],["balls_faced","Balls faced"],["strike_rate","Strike rate"],["fours","4s"],["sixes","6s"],["dismissals","Dismissals"],["bowling_overs","Overs"],["conceded","Conceded"],["wickets","Wickets"],["economy","Economy"],["team_run_share","Team run share"]];
 const seasonWrap=document.createElement("div");seasonWrap.id="player-season-table";seasonWrap.style.marginTop="14px";seasonCard.append(seasonWrap);root.append(seasonCard);
 profileTableColumns(player.seasons,seasonColumns,"player-season-table");

 const recordsCard=document.createElement("article");recordsCard.className="card";recordsCard.style.marginTop="16px";
 const recordsHeader=document.createElement("div");recordsHeader.className="profile-block-title";
 const recordsTitle=document.createElement("h3");recordsTitle.textContent="Match-by-match record";
 const recordsCount=document.createElement("span");recordsCount.className="badge";recordsCount.textContent=`${fmt(player.match_records.length,0)} appearance records`;
 recordsHeader.append(recordsTitle,recordsCount);
 const recordCaption=document.createElement("p");recordCaption.className="profile-note";recordCaption.textContent="Pressure contribution is evaluated only on deliveries classified as pressure for that player's role. A blank indicates the player had no delivery or no denominator for that statistic in the selected match.";
 const recordsWrap=document.createElement("div");recordsWrap.id="player-match-table";recordsWrap.style.marginTop="12px";
 recordsCard.append(recordsHeader,recordCaption,recordsWrap);root.append(recordsCard);
 renderPlayerMatches(player);
}
function renderPlayerMatches(player=profilePlayers.find(item=>String(item.player_id)===$("player-select").value)){
 if(!player)return;
 const format=selectedFormat("player-format");
 visiblePlayerRecords=player.match_records.filter(row=>format==="All"||row.format===format);
 const columns=[
  ["date","Date"],["competition","Competition"],["team","Team"],["opponent","Opponent"],["won","Won"],
  ["batting_runs","Runs"],["batting_balls","Balls"],["batting_strike_rate","SR"],["fours","4s"],["sixes","6s"],["dismissals","Out"],
  ["batting_run_contribution","Team run share"],["pressure_batting_runs","Pressure runs"],["pressure_batting_strike_rate","Pressure SR"],["pressure_batting_run_share","Pressure team-run share"],
  ["bowling_overs","Overs"],["bowling_conceded","Conceded"],["bowling_wickets","Wkts"],["bowling_economy","Econ."],
  ["pressure_bowling_wickets","Pressure wkts"],["pressure_bowling_economy","Pressure econ."],["pressure_wicket_share","Pressure wicket share"],["result","Result"]
 ];
 $("player-count").textContent=`${fmt(profilePlayers.length,0)} players · ${fmt(visiblePlayerRecords.length,0)} match records`;
 buildProfileTable("player-match-table",visiblePlayerRecords,columns)
}
function populatePlayerSelector(query=""){
 const select=$("player-select"),previous=select.value;
 const needle=query.trim().toLocaleLowerCase();
 const filtered=profilePlayers.filter(player=>!needle||String(player.player_name).toLocaleLowerCase().includes(needle)||String(player.player_id).includes(needle));
 const exact=filtered.find(player=>String(player.player_id)===needle||String(player.player_name).toLocaleLowerCase()===needle);
 select.replaceChildren();
 for(const player of filtered){const option=document.createElement("option");option.value=String(player.player_id);option.textContent=`${player.player_name} · ID ${player.player_id} · ${player.matches} matches`;select.append(option)}
 const selected=(exact&&String(exact.player_id))||(filtered.some(player=>String(player.player_id)===previous)?previous:(filtered[0]?String(filtered[0].player_id):""));
 if(selected)select.value=selected;
 if(!filtered.length){const option=document.createElement("option");option.value="";option.textContent="No matching player";select.append(option)}
 $("player-count").textContent=`${fmt(profilePlayers.length,0)} players · ${fmt(filtered.length,0)} matches search`;
 $("player-options").replaceChildren(...filtered.slice(0,200).map(player=>{const option=document.createElement("option");option.value=player.player_name;option.label=`ID ${player.player_id} · ${player.matches} matches`;return option}));
}
function downloadObject(data,filename,mime){
 const link=document.createElement("a");link.href=URL.createObjectURL(new Blob([data],{type:mime}));link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)
}
function exportPlayerRecords(){
 const columns=[
  ["date","date"],["match_id","match_id"],["format","format"],["season","season"],["competition","competition"],["team","team"],["opponent","opponent"],["won","won"],["result","result"],
  ["batting_runs","batting_runs"],["batting_balls","batting_balls"],["batting_strike_rate","batting_strike_rate"],["fours","fours"],["sixes","sixes"],["dismissals","dismissals"],["batting_run_contribution","batting_run_contribution"],
  ["pressure_batting_runs","pressure_batting_runs"],["pressure_batting_balls","pressure_batting_balls"],["pressure_batting_strike_rate","pressure_batting_strike_rate"],["pressure_batting_run_share","pressure_batting_run_share"],
  ["bowling_legal_balls","bowling_legal_balls"],["bowling_conceded","bowling_conceded"],["bowling_wickets","bowling_wickets"],["bowling_economy","bowling_economy"],
  ["pressure_bowling_balls","pressure_bowling_balls"],["pressure_bowling_conceded","pressure_bowling_conceded"],["pressure_bowling_wickets","pressure_bowling_wickets"],["pressure_bowling_economy","pressure_bowling_economy"],["pressure_wicket_share","pressure_wicket_share"]
 ];
 downloadCsv(visiblePlayerRecords,columns,`player_${$("player-select").value}_match_records.csv`)
}
function initPlayerExplorer(){
 fillFormatSelect($("player-format"));
 populatePlayerSelector();
 $("player-search").addEventListener("input",()=>{populatePlayerSelector($("player-search").value);renderPlayerProfile()});
 $("player-search").addEventListener("change",()=>{populatePlayerSelector($("player-search").value);renderPlayerProfile()});
 $("player-select").addEventListener("change",()=>{const player=profilePlayers.find(item=>String(item.player_id)===$("player-select").value);if(player)$("player-search").value=player.player_name;renderPlayerProfile()});
 $("player-format").addEventListener("change",()=>renderPlayerMatches());
 $("download-player-records").addEventListener("click",exportPlayerRecords);
 $("download-player-profile").addEventListener("click",()=>{const player=profilePlayers.find(item=>String(item.player_id)===$("player-select").value);if(player)downloadObject(JSON.stringify(player,null,2),`player_${player.player_id}_profile.json`,"application/json")});
 renderPlayerProfile()
}
function addQuality(){
 const datasetList=$("dataset-list");
 for(const [name,item] of Object.entries(DATA.datasets)){const line=document.createElement("div");line.className="quality-item";const label=document.createElement("span");label.textContent=name.replaceAll("_"," ");const value=document.createElement("strong");value.textContent=`${fmt(item.rows,0)} rows · ${fmt(item.columns,0)} cols · ${fmt(item.missing_cells,0)} missing`;line.append(label,value);datasetList.append(line)}
 const list=$("relationship-list");
 const notable=DATA.relationships.filter(item=>item.unmatched_count>0);
 const healthy=DATA.relationships.length-notable.length;
 const ok=document.createElement("div");ok.className="quality-item";ok.innerHTML=`<span>Checks with no unmatched records</span><strong style="color:var(--mint)">${healthy}</strong>`;list.append(ok);
 for(const check of notable){const line=document.createElement("div");line.className="quality-item";const label=document.createElement("span");label.textContent=check.name;const value=document.createElement("strong");value.textContent=`${fmt(check.unmatched_count,0)} unmatched`;line.append(label,value);list.append(line)}
 const d=DATA.diagnostics,diag=$("diagnostic-list");
 const facts=[
  ["Eligible chase matches",d.eligible_chase_matches],
  ["Target/winner checks",`${d.target_and_winner_consistency.consistent_matches}/${d.target_and_winner_consistency.matches_checked} consistent`],
  ["Matches with rows after target",d.matches_with_delivery_rows_after_target],
  ["Matches with rows after innings quota",d.matches_with_delivery_rows_after_innings_quota],
  ["Excluded matches (reasons)",Object.values(d.excluded_matches_by_reason).reduce((a,b)=>a+b,0)]
 ];
 for(const [label,value] of facts){const line=document.createElement("div");line.className="quality-item";const a=document.createElement("span");a.textContent=label;const b=document.createElement("strong");b.textContent=typeof value==="number"?fmt(value,0):String(value);line.append(a,b);diag.append(line)}
 const files=[
  ["Methodology report","phase2_methodology_report.md"],
  ["Phase 1 exploration report","phase1_report.md"],
  ["Top 10 batters (CSV)","phase2_batter_top10.csv"],
  ["Top 10 bowlers (CSV)","phase2_bowler_top10.csv"],
  ["Full batter leaderboard (CSV)","phase2_batter_leaderboard.csv"],
  ["Full bowler leaderboard (CSV)","phase2_bowler_leaderboard.csv"]
 ];
 const box=$("file-list");
 for(const [label,href] of files){const link=document.createElement("a");link.className="file-link";link.href=href;link.textContent=label;const hint=document.createElement("span");hint.className="badge";hint.textContent=href.endsWith(".csv")?"CSV":"Open";link.append(hint);box.append(link)}
}
document.querySelectorAll(".nav button").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll(".nav button").forEach(item=>item.classList.toggle("active",item===button));document.querySelectorAll(".view").forEach(view=>view.classList.toggle("active",view.id===button.dataset.view))}));
for(const id of ["batter-format","bowler-format","phase-format"])fillFormatSelect($(id));
$("batter-format").addEventListener("change",()=>renderBatter());$("bowler-format").addEventListener("change",()=>renderBowler());$("phase-format").addEventListener("change",()=>renderPhase());
$("batter-search").addEventListener("input",()=>renderBatter());$("bowler-search").addEventListener("input",()=>renderBowler());
renderKpis();
renderBars("batter-bars",DATA.global.batters_top10.slice(0,10),"player_name","reliability_adjusted_score");
renderBars("bowler-bars",DATA.global.bowlers_top10.slice(0,10),"player_name","bowling_score","orange");
renderScatter("batter-scatter",DATA.global.batters,"pressure_strike_rate","baseline_strike_rate",DATA.global.batters_top10);
renderScatter("bowler-scatter",DATA.global.bowlers,"pressure_economy","baseline_economy",DATA.global.bowlers_top10,true);
renderBatter();renderBowler();renderPhase();initPlayerExplorer();addQuality();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
