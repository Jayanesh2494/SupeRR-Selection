"""Pressure-context analysis and reproducible player leaderboards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__:
    from .data_exploration import load_datasets, resolve_data_dir
else:
    from data_exploration import load_datasets, resolve_data_dir


PRESSURE_QUANTILE = 0.75
MIN_PRESSURE_BALLS = 60
MIN_BASELINE_BALLS = 120
MIN_PRESSURE_MATCHES = 3
MIN_MATCH_BALLS_FOR_CONSISTENCY = 6
SHRINKAGE_BALLS = 60
BOOTSTRAP_SAMPLES = 500
BOOTSTRAP_SEED = 20261114
STANDARD_T20_BALLS = 120
NON_BOWLER_EXTRAS = {"byes", "legbyes", "penalty"}
ILLEGAL_DELIVERY_TYPES = {"wide", "overstep"}
BOWLER_CREDITED_DISMISSALS = {
    "bowled",
    "caught",
    "hit wicket",
    "lbw",
    "stump",
}


def _require_columns(
    frame: pd.DataFrame, columns: set[str], dataset_name: str
) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns: {', '.join(missing)}"
        )


def _string_values(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.casefold().fillna("")


def _selected_competitions(competitions: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        competitions, {"comp_id", "comp_name", "match_format"}, "competitions"
    )
    ipl = competitions["comp_name"].astype("string").str.fullmatch(
        r"IPL \d{4}", case=False, na=False
    )
    t20i = _string_values(competitions["match_format"]).eq("t20i")
    return competitions.loc[ipl | t20i].copy()


def classify_pressure(deliveries: pd.DataFrame) -> pd.DataFrame:
    """Classify high-demand batting chases and high-leverage bowling chases."""
    required = {
        "match_format",
        "required_run_rate",
        "wickets_lost",
        "balls_remaining",
        "innings_balls",
    }
    _require_columns(deliveries, required, "chase deliveries")
    if deliveries.empty:
        raise ValueError("No eligible chase deliveries are available to classify.")

    frame = deliveries.copy()
    frame["required_rate_percentile"] = np.nan
    for _, indices in frame.groupby("match_format", sort=False).groups.items():
        frame.loc[indices, "required_rate_percentile"] = frame.loc[
            indices, "required_run_rate"
        ].rank(method="average", pct=True)

    elapsed_fraction = (
        1 - frame["balls_remaining"] / frame["innings_balls"]
    ).clip(0, 1)
    wickets_lost_fraction = (frame["wickets_lost"] / 10).clip(0, 1)
    frame["batting_pressure_index"] = (
        0.60 * frame["required_rate_percentile"]
        + 0.25 * wickets_lost_fraction
        + 0.15 * elapsed_fraction
    )
    frame["bowling_pressure_index"] = (
        0.50 * (1 - frame["required_rate_percentile"])
        + 0.30 * (1 - wickets_lost_fraction)
        + 0.20 * elapsed_fraction
    )

    batting_cutoffs = frame.groupby("match_format")[
        "batting_pressure_index"
    ].transform(lambda values: values.quantile(PRESSURE_QUANTILE))
    bowling_cutoffs = frame.groupby("match_format")[
        "bowling_pressure_index"
    ].transform(lambda values: values.quantile(PRESSURE_QUANTILE))
    frame["batting_under_pressure"] = (
        frame["batting_pressure_index"] >= batting_cutoffs
    )
    frame["bowling_under_pressure"] = (
        frame["bowling_pressure_index"] >= bowling_cutoffs
    )
    return frame


def build_chase_deliveries(
    datasets: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build second-innings delivery states without changing source tables."""
    missing_datasets = {
        "ball_by_ball",
        "matches",
        "competitions",
    } - set(datasets)
    if missing_datasets:
        raise ValueError(
            "Missing datasets: " + ", ".join(sorted(missing_datasets))
        )

    ball = datasets["ball_by_ball"].copy()
    matches = datasets["matches"].copy()
    competitions = _selected_competitions(datasets["competitions"])
    _require_columns(
        ball,
        {
            "match_id",
            "innings",
            "innings_ball_num",
            "runs",
            "extras1_runs",
            "extras_2_runs",
            "extras_type",
            "is_wicket",
            "batting_team_id",
            "striker_id",
            "bowler_id",
            "dismissal_type",
        },
        "ball_by_ball",
    )
    _require_columns(
        matches,
        {
            "match_id",
            "comp_id",
            "revised_target",
            "second_inn_revised_overs",
            "result",
            "win_team_id",
        },
        "matches",
    )
    if competitions["comp_id"].duplicated().any():
        raise ValueError("competitions.comp_id must be unique for this analysis.")
    if matches["match_id"].duplicated().any():
        raise ValueError("matches.match_id must be unique for this analysis.")

    eligible_matches = matches.merge(
        competitions[["comp_id", "match_format", "comp_name"]],
        on="comp_id",
        how="inner",
        validate="many_to_one",
    )
    ball["extras_type_normalized"] = _string_values(ball["extras_type"])
    ball["is_legal_ball"] = ~ball["extras_type_normalized"].isin(
        ILLEGAL_DELIVERY_TYPES
    )
    ball["batter_faced_ball"] = ~ball["extras_type_normalized"].eq("wide")
    ball["is_wicket"] = ball["is_wicket"].fillna(False).astype(bool)
    ball["total_team_runs"] = (
        ball["runs"].fillna(0)
        + ball["extras1_runs"].fillna(0)
        + ball["extras_2_runs"].fillna(0)
    )
    ball["bowler_conceded_runs"] = ball["runs"].fillna(0) + (
        ball[["extras1_runs", "extras_2_runs"]].fillna(0).sum(axis=1)
        * ~ball["extras_type_normalized"].isin(NON_BOWLER_EXTRAS)
    )
    dismissal_types = _string_values(ball["dismissal_type"])
    ball["bowler_credited_wicket"] = dismissal_types.isin(
        BOWLER_CREDITED_DISMISSALS
    )

    innings_scores = (
        ball.loc[ball["innings"].isin([1, 2])]
        .groupby(["match_id", "innings"])["total_team_runs"]
        .sum()
        .unstack("innings")
        .rename(columns={1: "first_innings_runs", 2: "second_innings_runs"})
    )
    for column in ("first_innings_runs", "second_innings_runs"):
        if column not in innings_scores:
            innings_scores[column] = np.nan

    candidate = eligible_matches.merge(
        innings_scores, left_on="match_id", right_index=True, how="left"
    )
    candidate["target"] = candidate["revised_target"].copy()
    derived_target = candidate["revised_target"].isna()
    candidate.loc[derived_target, "target"] = (
        candidate.loc[derived_target, "first_innings_runs"] + 1
    )
    candidate["innings_balls"] = candidate[
        "second_inn_revised_overs"
    ].fillna(STANDARD_T20_BALLS)

    supplied_budgets = candidate["second_inn_revised_overs"].dropna()
    invalid_budgets = supplied_budgets[
        (supplied_budgets <= 0) | (supplied_budgets % 6 != 0)
    ]
    if not invalid_budgets.empty:
        raise ValueError(
            "second_inn_revised_overs contains values not interpretable as "
            f"positive six-ball multiples: {invalid_budgets.head(5).tolist()}"
        )
    if (candidate["innings_balls"] <= 0).any():
        raise ValueError("Innings ball limits must be positive.")

    excluded: dict[str, int] = {}

    def keep(rows: pd.Series, reason: str) -> None:
        nonlocal candidate
        excluded[reason] = int((~rows).sum())
        candidate = candidate.loc[rows].copy()

    keep(candidate["first_innings_runs"].notna(), "missing_first_innings")
    keep(candidate["second_innings_runs"].notna(), "missing_second_innings")
    keep(candidate["win_team_id"].notna(), "missing_winner")
    result_text = _string_values(candidate["result"])
    keep(
        ~result_text.str.contains(r"abandoned|no result", regex=True),
        "abandoned_or_no_result",
    )
    keep(candidate["target"].notna() & (candidate["target"] > 0), "missing_target")
    result_text = _string_values(candidate["result"])
    dls_without_target = result_text.str.contains(r"d/l|dls", regex=True) & (
        candidate["revised_target"].isna()
    )
    keep(~dls_without_target, "revised_target_missing_for_dls")

    match_ids = set(candidate["match_id"])
    chase = ball.loc[
        (ball["innings"] == 2) & ball["match_id"].isin(match_ids)
    ].copy()
    chase = chase.merge(
        candidate[
            [
                "match_id",
                "comp_id",
                "match_format",
                "target",
                "innings_balls",
                "revised_target",
            ]
        ],
        on="match_id",
        how="inner",
        validate="many_to_one",
    )
    chase = chase.sort_values(
        ["match_id", "innings_ball_num"], kind="stable"
    ).reset_index(drop=True)
    groups = chase.groupby("match_id", sort=False)
    chase["runs_before"] = groups["total_team_runs"].cumsum() - chase[
        "total_team_runs"
    ]
    chase["wickets_lost"] = (
        groups["is_wicket"].cumsum().astype(int) - chase["is_wicket"].astype(int)
    )
    chase["legal_balls_bowled"] = (
        groups["is_legal_ball"].cumsum().astype(int)
        - chase["is_legal_ball"].astype(int)
    )
    chase["balls_remaining"] = (
        chase["innings_balls"] - chase["legal_balls_bowled"]
    )
    chase["runs_required"] = chase["target"] - chase["runs_before"]
    chase["required_run_rate"] = (
        chase["runs_required"] * 6 / chase["balls_remaining"].where(
            chase["balls_remaining"] > 0
        )
    )
    already_reached_target = chase["runs_required"] <= 0
    innings_quota_exhausted = chase["balls_remaining"] <= 0
    invalid_state = already_reached_target | innings_quota_exhausted

    innings_teams = (
        ball.loc[ball["innings"].isin([1, 2])]
        .groupby(["match_id", "innings"])["batting_team_id"]
        .first()
        .unstack("innings")
        .rename(columns={1: "first_innings_team_id", 2: "second_innings_team_id"})
    )
    outcome_check = candidate.merge(
        innings_teams, left_on="match_id", right_index=True, how="left"
    )
    second_innings_win = outcome_check["win_team_id"].eq(
        outcome_check["second_innings_team_id"]
    )
    first_innings_win = outcome_check["win_team_id"].eq(
        outcome_check["first_innings_team_id"]
    )
    target_outcome_consistent = (
        second_innings_win
        & outcome_check["second_innings_runs"].ge(outcome_check["target"])
    ) | (
        first_innings_win
        & outcome_check["second_innings_runs"].lt(outcome_check["target"])
    )
    diagnostics = {
        "source_match_rows": int(len(matches)),
        "selected_competitions": competitions[
            ["comp_id", "comp_name", "match_format"]
        ].to_dict("records"),
        "selected_competition_match_rows": int(len(eligible_matches)),
        "eligible_chase_matches": int(len(candidate)),
        "excluded_matches_by_reason": excluded,
        "chase_delivery_rows_before_state_filter": int(len(chase)),
        "chase_delivery_rows_excluded_after_target_or_quota": int(
            invalid_state.sum()
        ),
        "chase_delivery_rows_after_target": int(already_reached_target.sum()),
        "matches_with_delivery_rows_after_target": int(
            chase.loc[already_reached_target, "match_id"].nunique()
        ),
        "after_target_examples": chase.loc[
            already_reached_target,
            [
                "match_id",
                "innings_ball_num",
                "runs_before",
                "target",
                "balls_remaining",
            ],
        ]
        .head(10)
        .to_dict("records"),
        "chase_delivery_rows_after_innings_quota": int(
            innings_quota_exhausted.sum()
        ),
        "matches_with_delivery_rows_after_innings_quota": int(
            chase.loc[innings_quota_exhausted, "match_id"].nunique()
        ),
        "after_innings_quota_examples": chase.loc[
            innings_quota_exhausted,
            [
                "match_id",
                "innings_ball_num",
                "legal_balls_bowled",
                "innings_balls",
                "extras_type",
            ],
        ]
        .head(10)
        .to_dict("records"),
        "chase_delivery_rows_used": int((~invalid_state).sum()),
        "target_and_winner_consistency": {
            "matches_checked": int(len(outcome_check)),
            "consistent_matches": int(target_outcome_consistent.sum()),
            "inconsistent_matches": int((~target_outcome_consistent).sum()),
            "inconsistent_examples": outcome_check.loc[
                ~target_outcome_consistent,
                [
                    "match_id",
                    "win_team_id",
                    "first_innings_team_id",
                    "second_innings_team_id",
                    "first_innings_runs",
                    "second_innings_runs",
                    "target",
                ],
            ]
            .head(10)
            .to_dict("records"),
        },
        "score_definition": (
            "team runs per delivery = runs + extras1_runs + extras_2_runs"
        ),
        "revised_second_innings_limits_are_six_ball_multiples": bool(
            supplied_budgets.empty or (supplied_budgets % 6 == 0).all()
        ),
    }
    chase = chase.loc[~invalid_state].copy()
    if chase.empty:
        raise ValueError("No valid second-innings chase deliveries remain.")
    chase = classify_pressure(chase)
    pressure_summaries = {}
    for pressure_col in ("batting_under_pressure", "bowling_under_pressure"):
        pressure_summaries[pressure_col] = {
            str(fmt): {
                "pressure_rows": int(
                    group[pressure_col].sum()
                ),
                "eligible_rows": int(len(group)),
                "cutoff": float(
                    group[
                        "batting_pressure_index"
                        if pressure_col == "batting_under_pressure"
                        else "bowling_pressure_index"
                    ].quantile(PRESSURE_QUANTILE)
                ),
            }
            for fmt, group in chase.groupby("match_format")
        }
    diagnostics["pressure_classification"] = pressure_summaries
    return chase, diagnostics


def _modeled_players(
    mapping: pd.DataFrame, competitions: pd.DataFrame
) -> pd.DataFrame:
    _require_columns(
        mapping, {"comp_id", "player_id", "player_name"}, "player mapping"
    )
    selected_ids = set(competitions["comp_id"])
    names = mapping.loc[mapping["comp_id"].isin(selected_ids)].copy()
    names["player_name"] = names["player_name"].astype("string").str.strip()
    names = names.loc[names["player_name"].notna() & names["player_name"].ne("")]
    return (
        names.groupby("player_id")["player_name"]
        .agg(lambda values: values.value_counts().sort_values(ascending=False).index[0])
        .rename("player_name")
        .reset_index()
    )


def _metric_by_format(
    deliveries: pd.DataFrame,
    player_column: str,
    pressure_column: str,
    exposure_column: str,
    metric_columns: dict[str, str],
) -> pd.DataFrame:
    valid = deliveries.loc[
        deliveries[exposure_column].gt(0)
        | deliveries[list(metric_columns.values())].ne(0).any(axis=1)
    ].copy()
    grouped = (
        valid.groupby([player_column, "match_format", pressure_column], dropna=True)
        .agg(
            **{
                "exposure": (exposure_column, "sum"),
                **{
                    output: (source, "sum")
                    for output, source in metric_columns.items()
                },
                "delivery_rows": ("match_id", "size"),
                "matches": ("match_id", "nunique"),
            }
        )
    )
    if grouped.empty:
        return pd.DataFrame()
    pressure = grouped.loc[
        grouped.index.get_level_values(pressure_column) == True
    ].droplevel(pressure_column)
    baseline = grouped.loc[
        grouped.index.get_level_values(pressure_column) == False
    ].droplevel(pressure_column)
    result = pressure.add_suffix("_pressure").join(
        baseline.add_suffix("_baseline"), how="outer"
    )
    return result.fillna(0).reset_index()


def _confidence_interval(
    match_metrics: pd.DataFrame,
    baseline_rate: float,
    rate_scale: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    if match_metrics.empty:
        return (float("nan"), float("nan"))
    runs = match_metrics["metric_runs"].to_numpy(dtype=float)
    exposure = match_metrics["metric_exposure"].to_numpy(dtype=float)
    sample_count = len(match_metrics)
    draws = rng.integers(0, sample_count, size=(BOOTSTRAP_SAMPLES, sample_count))
    sampled_runs = runs[draws].sum(axis=1)
    sampled_exposure = exposure[draws].sum(axis=1)
    rates = sampled_runs / sampled_exposure * rate_scale
    deltas = rates - baseline_rate if rate_scale == 100 else baseline_rate - rates
    lower, upper = np.quantile(deltas, [0.025, 0.975])
    return float(lower), float(upper)


def rank_batters(
    deliveries: pd.DataFrame, player_names: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    batting = deliveries.loc[deliveries["batter_faced_ball"]].copy()
    batting["player_id"] = batting["striker_id"]
    batting["exposure"] = 1
    metrics = _metric_by_format(
        batting,
        "player_id",
        "batting_under_pressure",
        "exposure",
        {"runs": "runs"},
    )
    if metrics.empty:
        return pd.DataFrame(), pd.DataFrame()
    metrics["pressure_sr"] = (
        metrics["runs_pressure"] / metrics["exposure_pressure"] * 100
    )
    metrics["baseline_sr"] = (
        metrics["runs_baseline"] / metrics["exposure_baseline"] * 100
    )
    metrics["sr_delta"] = metrics["pressure_sr"] - metrics["baseline_sr"]
    metrics["shrinkage"] = metrics["exposure_pressure"] / (
        metrics["exposure_pressure"] + SHRINKAGE_BALLS
    )
    metrics["adjusted_sr_delta"] = metrics["sr_delta"] * metrics["shrinkage"]

    valid_formats = metrics.loc[
        metrics["exposure_pressure"].gt(0)
        & metrics["exposure_baseline"].gt(0)
    ].copy()
    summary = (
        valid_formats.assign(
            weighted_pressure_runs=lambda frame: frame["runs_pressure"],
            weighted_baseline_sr=lambda frame: (
                frame["baseline_sr"] * frame["exposure_pressure"]
            ),
            weighted_pressure_sr=lambda frame: (
                frame["pressure_sr"] * frame["exposure_pressure"]
            ),
            weighted_adjusted_delta=lambda frame: (
                frame["adjusted_sr_delta"] * frame["exposure_pressure"]
            ),
        )
        .groupby("player_id")
        .agg(
            pressure_balls=("exposure_pressure", "sum"),
            baseline_balls=("exposure_baseline", "sum"),
            pressure_runs=("runs_pressure", "sum"),
            baseline_runs=("runs_baseline", "sum"),
            adjusted_delta_numerator=("weighted_adjusted_delta", "sum"),
            pressure_sr_numerator=("weighted_pressure_sr", "sum"),
            baseline_sr_numerator=("weighted_baseline_sr", "sum"),
        )
    )
    summary["pressure_strike_rate"] = (
        summary["pressure_sr_numerator"] / summary["pressure_balls"]
    )
    summary["baseline_strike_rate"] = (
        summary["baseline_sr_numerator"] / summary["pressure_balls"]
    )
    summary["strike_rate_change"] = (
        summary["pressure_strike_rate"] - summary["baseline_strike_rate"]
    )
    summary["reliability_adjusted_score"] = (
        summary["adjusted_delta_numerator"] / summary["pressure_balls"]
    )
    summary["pressure_matches"] = 0
    match_metrics = (
        batting.loc[batting["batting_under_pressure"]]
        .groupby(["striker_id", "match_format", "match_id"])
        .agg(metric_runs=("runs", "sum"), metric_exposure=("exposure", "sum"))
        .reset_index()
    )
    match_metrics = match_metrics.loc[match_metrics["metric_exposure"] > 0]
    match_valid = match_metrics.merge(
        valid_formats[["player_id", "match_format", "baseline_sr"]],
        left_on=["striker_id", "match_format"],
        right_on=["player_id", "match_format"],
        how="inner",
        validate="many_to_one",
    )
    pressure_match_counts = match_valid.groupby("striker_id")["match_id"].nunique()
    summary["pressure_matches"] = pressure_match_counts.reindex(
        summary.index
    ).fillna(0)
    consistency_rows = match_valid.loc[
        match_valid["metric_exposure"] >= MIN_MATCH_BALLS_FOR_CONSISTENCY
    ].copy()
    consistency_rows["match_sr"] = (
        consistency_rows["metric_runs"] / consistency_rows["metric_exposure"] * 100
    )
    consistency = consistency_rows.assign(
        above_baseline=lambda frame: frame["match_sr"] >= frame["baseline_sr"]
    ).groupby("striker_id")["above_baseline"].mean()
    summary["pressure_match_consistency"] = consistency.reindex(summary.index)
    names = player_names.set_index("player_id")["player_name"]
    summary["player_name"] = names.reindex(summary.index)
    eligible = summary.loc[
        summary["pressure_balls"].ge(MIN_PRESSURE_BALLS)
        & summary["baseline_balls"].ge(MIN_BASELINE_BALLS)
        & summary["pressure_matches"].ge(MIN_PRESSURE_MATCHES)
    ].copy()
    eligible = eligible.sort_values(
        [
            "reliability_adjusted_score",
            "pressure_balls",
            "player_name",
        ],
        ascending=[False, False, True],
        kind="stable",
        na_position="last",
    )
    eligible.insert(0, "rank", range(1, len(eligible) + 1))

    top = eligible.head(10).copy()
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    intervals: dict[int, tuple[float, float]] = {}
    for player_id in top.index:
        sample = match_valid.loc[
            match_valid["striker_id"] == player_id
        ].groupby("match_id")[["metric_runs", "metric_exposure"]].sum()
        intervals[player_id] = _confidence_interval(
            sample,
            float(summary.loc[player_id, "baseline_strike_rate"]),
            100,
            rng,
        )
    top["bootstrap_95_ci_low_sr_change"] = [
        intervals[player_id][0] for player_id in top.index
    ]
    top["bootstrap_95_ci_high_sr_change"] = [
        intervals[player_id][1] for player_id in top.index
    ]
    return eligible.reset_index(), top.reset_index()


def rank_bowlers(
    deliveries: pd.DataFrame, player_names: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    bowlers = deliveries.copy()
    bowlers["player_id"] = bowlers["bowler_id"]
    bowlers["exposure"] = bowlers["is_legal_ball"].astype(int)
    metrics = _metric_by_format(
        bowlers,
        "player_id",
        "bowling_under_pressure",
        "exposure",
        {
            "conceded_runs": "bowler_conceded_runs",
            "credited_wickets": "bowler_credited_wicket",
        },
    )
    if metrics.empty:
        return pd.DataFrame(), pd.DataFrame()
    metrics["pressure_economy"] = (
        metrics["conceded_runs_pressure"] / metrics["exposure_pressure"] * 6
    ).where(metrics["exposure_pressure"] > 0)
    metrics["baseline_economy"] = (
        metrics["conceded_runs_baseline"] / metrics["exposure_baseline"] * 6
    ).where(metrics["exposure_baseline"] > 0)
    metrics["economy_improvement"] = (
        metrics["baseline_economy"] - metrics["pressure_economy"]
    )
    metrics["pressure_wickets_per_24"] = (
        metrics["credited_wickets_pressure"] / metrics["exposure_pressure"] * 24
    ).where(metrics["exposure_pressure"] > 0)
    metrics["baseline_wickets_per_24"] = (
        metrics["credited_wickets_baseline"] / metrics["exposure_baseline"] * 24
    ).where(metrics["exposure_baseline"] > 0)
    metrics["wickets_per_24_improvement"] = (
        metrics["pressure_wickets_per_24"] - metrics["baseline_wickets_per_24"]
    )
    metrics["shrinkage"] = metrics["exposure_pressure"] / (
        metrics["exposure_pressure"] + SHRINKAGE_BALLS
    )
    metrics["adjusted_economy_improvement"] = (
        metrics["economy_improvement"] * metrics["shrinkage"]
    )
    metrics["adjusted_wicket_improvement"] = (
        metrics["wickets_per_24_improvement"] * metrics["shrinkage"]
    )
    valid_formats = metrics.loc[
        metrics["exposure_pressure"].gt(0)
        & metrics["exposure_baseline"].gt(0)
    ].copy()
    for value in (
        "adjusted_economy_improvement",
        "adjusted_wicket_improvement",
        "pressure_economy",
        "baseline_economy",
        "pressure_wickets_per_24",
        "baseline_wickets_per_24",
    ):
        valid_formats[f"weighted_{value}"] = (
            valid_formats[value] * valid_formats["exposure_pressure"]
        )
    summary = valid_formats.groupby("player_id").agg(
        pressure_balls=("exposure_pressure", "sum"),
        baseline_balls=("exposure_baseline", "sum"),
        pressure_conceded_runs=("conceded_runs_pressure", "sum"),
        baseline_conceded_runs=("conceded_runs_baseline", "sum"),
        pressure_wickets=("credited_wickets_pressure", "sum"),
        baseline_wickets=("credited_wickets_baseline", "sum"),
        adjusted_economy_numerator=("weighted_adjusted_economy_improvement", "sum"),
        adjusted_wickets_numerator=("weighted_adjusted_wicket_improvement", "sum"),
        pressure_economy_numerator=("weighted_pressure_economy", "sum"),
        baseline_economy_numerator=("weighted_baseline_economy", "sum"),
        pressure_wickets_per_24_numerator=("weighted_pressure_wickets_per_24", "sum"),
        baseline_wickets_per_24_numerator=("weighted_baseline_wickets_per_24", "sum"),
    )
    summary["pressure_economy"] = (
        summary["pressure_economy_numerator"] / summary["pressure_balls"]
    )
    summary["baseline_economy"] = (
        summary["baseline_economy_numerator"] / summary["pressure_balls"]
    )
    summary["economy_improvement"] = (
        summary["baseline_economy"] - summary["pressure_economy"]
    )
    summary["pressure_wickets_per_24"] = (
        summary["pressure_wickets_per_24_numerator"] / summary["pressure_balls"]
    )
    summary["baseline_wickets_per_24"] = (
        summary["baseline_wickets_per_24_numerator"] / summary["pressure_balls"]
    )
    summary["wickets_per_24_improvement"] = (
        summary["pressure_wickets_per_24"]
        - summary["baseline_wickets_per_24"]
    )
    summary["adjusted_economy_improvement"] = (
        summary["adjusted_economy_numerator"] / summary["pressure_balls"]
    )
    summary["adjusted_wickets_per_24_improvement"] = (
        summary["adjusted_wickets_numerator"] / summary["pressure_balls"]
    )

    pressure_matches = (
        bowlers.loc[bowlers["bowling_under_pressure"]]
        .groupby(["bowler_id", "match_format", "match_id"])
        .agg(
            metric_runs=("bowler_conceded_runs", "sum"),
            metric_exposure=("exposure", "sum"),
        )
        .reset_index()
    )
    pressure_matches = pressure_matches.loc[
        pressure_matches["metric_exposure"] > 0
    ]
    match_valid = pressure_matches.merge(
        valid_formats[
            ["player_id", "match_format", "baseline_economy"]
        ],
        left_on=["bowler_id", "match_format"],
        right_on=["player_id", "match_format"],
        how="inner",
        validate="many_to_one",
    )
    match_counts = match_valid.groupby("bowler_id")["match_id"].nunique()
    summary["pressure_matches"] = match_counts.reindex(summary.index).fillna(0)
    consistency_rows = match_valid.loc[
        match_valid["metric_exposure"] >= MIN_MATCH_BALLS_FOR_CONSISTENCY
    ].copy()
    consistency_rows["match_economy"] = (
        consistency_rows["metric_runs"] / consistency_rows["metric_exposure"] * 6
    )
    consistency = consistency_rows.assign(
        better_economy=lambda frame: (
            frame["match_economy"] <= frame["baseline_economy"]
        )
    ).groupby("bowler_id")["better_economy"].mean()
    summary["pressure_match_consistency"] = consistency.reindex(summary.index)
    names = player_names.set_index("player_id")["player_name"]
    summary["player_name"] = names.reindex(summary.index)
    eligible = summary.loc[
        summary["pressure_balls"].ge(MIN_PRESSURE_BALLS)
        & summary["baseline_balls"].ge(MIN_BASELINE_BALLS)
        & summary["pressure_matches"].ge(MIN_PRESSURE_MATCHES)
    ].copy()
    for source, target in (
        ("adjusted_economy_improvement", "economy_z"),
        ("adjusted_wickets_per_24_improvement", "wickets_z"),
    ):
        standard_deviation = eligible[source].std(ddof=0)
        if pd.isna(standard_deviation) or standard_deviation == 0:
            eligible[target] = 0.0
        else:
            eligible[target] = (
                eligible[source] - eligible[source].mean()
            ) / standard_deviation
    eligible["bowling_score"] = (
        eligible["economy_z"] + eligible["wickets_z"]
    ) / 2
    eligible = eligible.sort_values(
        ["bowling_score", "pressure_balls", "player_name"],
        ascending=[False, False, True],
        kind="stable",
        na_position="last",
    )
    eligible.insert(0, "rank", range(1, len(eligible) + 1))

    top = eligible.head(10).copy()
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    econ_intervals: dict[int, tuple[float, float]] = {}
    for player_id in top.index:
        sample = match_valid.loc[
            match_valid["bowler_id"] == player_id
        ].groupby("match_id")[["metric_runs", "metric_exposure"]].sum()
        econ_intervals[player_id] = _confidence_interval(
            sample,
            float(summary.loc[player_id, "baseline_economy"]),
            6,
            rng,
        )
    top["bootstrap_95_ci_low_economy_improvement"] = [
        econ_intervals[player_id][0] for player_id in top.index
    ]
    top["bootstrap_95_ci_high_economy_improvement"] = [
        econ_intervals[player_id][1] for player_id in top.index
    ]
    return eligible.reset_index(), top.reset_index()


def _markdown_table(
    headers: list[str], rows: list[list[Any]], digits: int = 2
) -> str:
    def render(value: Any) -> str:
        if isinstance(value, (float, np.floating)):
            text = f"{value:.{digits}f}"
        else:
            text = str(value)
        return text.replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(render(value) for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _top_table(
    frame: pd.DataFrame, columns: list[tuple[str, str]]
) -> str:
    return _markdown_table(
        ["Rank", "Player", *[heading for heading, _ in columns]],
        [
            [
                row["rank"],
                row["player_name"],
                *[row[column] for _, column in columns],
            ]
            for row in frame.to_dict("records")
        ],
    )


def build_methodology_report(
    batter_top10: pd.DataFrame,
    bowler_top10: pd.DataFrame,
    batters: pd.DataFrame,
    bowlers: pd.DataFrame,
    diagnostics: dict[str, Any],
) -> str:
    diagnostics_text = json.dumps(diagnostics, indent=2, default=str)
    return "\n".join(
        [
            "# SupeRR Selector Season 2 — Phase 2 Pressure Analysis",
            "",
            "## Scope and reproducibility",
            "",
            "This phase builds a chase-context pressure classification, compares each player with their own non-pressure chase baseline, and generates the top-10 batter and bowler leaderboards from the supplied data. Run `python src/pressure_analysis.py` from the project root to regenerate the CSVs and this report. Source CSVs are read-only inputs.",
            "",
            "The player pool includes competitions whose format is `T20I` and competitions named exactly `IPL YYYY`. Other `T20` competitions are excluded to match the challenge scope. Main second innings are used; first-innings, super-over, abandoned, no-result, and matches without an observed winner are not used in rankings.",
            "",
            "## Pressure definition",
            "",
            "Pressure is measured only in a live second-innings chase. At the start of each delivery, the pipeline calculates runs required, legal balls remaining, wickets already lost, and required run rate. The default innings budget is 120 legal balls; the supplied `second_inn_revised_overs` values are treated as legal-ball limits because all observed non-null values are positive multiples of six (30–114).",
            "",
            "The chase target is `revised_target` when supplied; otherwise it is first-innings team runs plus one. First-innings team runs are calculated as `runs + extras1_runs + extras_2_runs` per delivery. Matches labelled D/L or DLS without an explicit revised target are excluded. Wide and `Overstep` deliveries do not consume a legal ball; all other observed extras types are treated as legal, since the files do not provide a separate legal-ball flag.",
            "",
            f"The explicit or derived target was checked against the observed winner and second-innings total: **{diagnostics['target_and_winner_consistency']['consistent_matches']} of {diagnostics['target_and_winner_consistency']['matches_checked']} eligible matches agreed**. Rows after the chase target was already reached or the innings ball quota was exhausted are excluded from pressure-state modeling and counted in diagnostics; source records are retained.",
            "",
            "Required-run-rate percentile is calculated within each format (IPL or T20I). The batting-pressure index is **0.60 × required-rate percentile + 0.25 × wickets lost / 10 + 0.15 × innings elapsed fraction**. The bowling-pressure index is **0.50 × (1 − required-rate percentile) + 0.30 × (1 − wickets lost / 10) + 0.20 × innings elapsed fraction**. The top quartile of each index within each format is labelled pressure. The separate indices reflect high chase demand for batters and a late, viable chase threat for defending bowlers. Delivery-level threshold values and counts are recorded in the report diagnostics.",
            "",
            "## Performance comparison and eligibility",
            "",
            "Only batter-striker events and bowler-assigned events in second innings are measured. Batter strike rate is batter runs per batter-faced ball × 100; wides are not balls faced, while no-balls are. Batter ranking uses the pressure-minus-baseline strike-rate change, shrunk toward zero by `pressure balls / (pressure balls + 60)`. The pressure baseline consists of the same player's non-pressure chase deliveries in the same format.",
            "",
            "Bowler runs conceded are batter runs plus recorded extras, excluding byes, legbyes, and penalty extras. Economy is conceded runs per legal ball × 6. The supplied `Overstep` label is treated as a no-ball and is excluded from legal-ball counts. Credited wickets include Caught, Bowled, LBW, Stump, and Hit Wicket; run-outs and other non-bowler dismissals are excluded. Each format-specific economy improvement (baseline economy minus pressure economy) and wicket-rate improvement (pressure minus baseline credited wickets per 24 legal balls) is shrunk by the same exposure formula. If a player appears in both formats, their format-specific changes are averaged weighted by pressure balls, so each comparison uses their own baseline in that format.",
            "",
            f"Eligibility requires at least {MIN_PRESSURE_BALLS} pressure balls, {MIN_BASELINE_BALLS} baseline balls, and {MIN_PRESSURE_MATCHES} pressure matches with a usable same-format baseline. Batter rank is descending reliability-adjusted strike-rate change. Bowler rank is descending average of the population z-scores for the two shrunk improvements (equal weights). These scores compare players in this eligible cohort; a positive change means better performance than that player's baseline. The `consistent match share` is calculated over pressure matches with at least {MIN_MATCH_BALLS_FOR_CONSISTENCY} role-specific balls: the share where the player's pressure strike rate is at least their same-format baseline (batters) or pressure economy is no higher than baseline (bowlers).",
            "",
            "Top-10 uncertainty intervals are 95% percentile bootstrap intervals from 500 resamples of the player's pressure matches, with a fixed seed; the baseline is held fixed. Batter intervals show strike-rate change, and bowler intervals show economy improvement. They are descriptive and do not account for uncertainty in the baseline or pressure thresholds.",
            "",
            "## Top 10 batters",
            "",
            _top_table(
                batter_top10,
                [
                    ("Adjusted SR change", "reliability_adjusted_score"),
                    ("Pressure SR", "pressure_strike_rate"),
                    ("Baseline SR", "baseline_strike_rate"),
                    ("Pressure balls", "pressure_balls"),
                    ("Pressure matches", "pressure_matches"),
                    ("Consistent match share", "pressure_match_consistency"),
                    ("95% CI low", "bootstrap_95_ci_low_sr_change"),
                    ("95% CI high", "bootstrap_95_ci_high_sr_change"),
                ],
            ),
            "",
            "## Top 10 bowlers",
            "",
            _top_table(
                bowler_top10,
                [
                    ("Bowling score (z)", "bowling_score"),
                    ("Pressure economy", "pressure_economy"),
                    ("Baseline economy", "baseline_economy"),
                    ("Economy improvement", "economy_improvement"),
                    ("Wicket improvement / 24 balls", "wickets_per_24_improvement"),
                    ("Pressure balls", "pressure_balls"),
                    ("Pressure matches", "pressure_matches"),
                    ("Consistent match share", "pressure_match_consistency"),
                    ("95% CI low econ", "bootstrap_95_ci_low_economy_improvement"),
                    ("95% CI high econ", "bootstrap_95_ci_high_economy_improvement"),
                ],
            ),
            "",
            "## Cohort and data diagnostics",
            "",
            f"- Eligible batter cohort: **{len(batters)}**; eligible bowler cohort: **{len(bowlers)}**.",
            f"- Requested top-10 returned: **{len(batter_top10)} batters** and **{len(bowler_top10)} bowlers**. If fewer than 10 meet the pre-set eligibility thresholds, the lists remain shorter rather than lowering the bar after seeing results.",
            "- The full eligible tables are saved separately as CSVs for auditability.",
            "",
            "```json",
            diagnostics_text,
            "```",
            "",
            "## Limitations",
            "",
            "- This definition is chase-only. It does not label first-innings situations, batter-vs-bowler matchups, required-rate trajectory, match win probability, pitch conditions, or opponent strength.",
            "- Pressure labels are relative to the observed cohort's top quartile in each format, not a universal cricket threshold. The index coefficients and 75th-percentile cutoff are modeling choices, not official rules.",
            "- Innings termination and legal-ball semantics are inferred from the CSVs. Only `wide` and `Overstep` are explicitly treated as illegal deliveries; two rows have extras without an extras type and remain included under the documented default.",
            "- Names are sourced from the competition-team-player mapping. If one player ID has aliases, the most frequent mapped name is displayed; source IDs remain the analytical key.",
            "- Batter strike rate does not reward not-out survival, and bowler scores weight economy and credited wickets equally after standardization. The minimum exposure and shrinkage reduce, but do not remove, small-sample and selection effects.",
            "- Bootstrap intervals resample pressure matches but hold the baseline and pressure cutoff fixed. They should not be read as proof of causality or as a complete uncertainty estimate.",
            "- A player's top-10 rank is conditional on the supplied data, chosen pressure definition, eligibility thresholds, and scoring formula; it is not a forecast of future performance.",
            "",
        ]
    )


def run_analysis(
    data_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    data_directory = data_dir or resolve_data_dir()
    datasets = load_datasets(data_directory)
    chase, diagnostics = build_chase_deliveries(datasets)
    competitions = _selected_competitions(datasets["competitions"])
    player_names = _modeled_players(
        datasets["competition_team_player_mapping"], competitions
    )
    batter_leaderboard, batter_top10 = rank_batters(chase, player_names)
    bowler_leaderboard, bowler_top10 = rank_bowlers(chase, player_names)
    output = output_dir or Path(__file__).resolve().parents[1] / "reports"
    output.mkdir(parents=True, exist_ok=True)

    outputs = {
        "phase2_batter_leaderboard.csv": batter_leaderboard,
        "phase2_batter_top10.csv": batter_top10,
        "phase2_bowler_leaderboard.csv": bowler_leaderboard,
        "phase2_bowler_top10.csv": bowler_top10,
    }
    for filename, frame in outputs.items():
        frame.to_csv(output / filename, index=False)
    report = build_methodology_report(
        batter_top10,
        bowler_top10,
        batter_leaderboard,
        bowler_leaderboard,
        diagnostics,
    )
    (output / "phase2_methodology_report.md").write_text(
        report, encoding="utf-8"
    )
    diagnostics["output_directory"] = str(output)
    return {
        "chase_deliveries": chase,
        "diagnostics": diagnostics,
        "batter_leaderboard": batter_leaderboard,
        "batter_top10": batter_top10,
        "bowler_leaderboard": bowler_leaderboard,
        "bowler_top10": bowler_top10,
        "report_path": output / "phase2_methodology_report.md",
    }


def main() -> None:
    result = run_analysis()
    print(f"Methodology report: {result['report_path']}")
    print(
        f"Eligible player counts: {len(result['batter_leaderboard'])} batters, "
        f"{len(result['bowler_leaderboard'])} bowlers"
    )
    print("\nTop 10 batters:")
    print(
        result["batter_top10"][
            [
                "rank",
                "player_name",
                "reliability_adjusted_score",
                "pressure_balls",
                "pressure_matches",
            ]
        ].to_string(index=False)
    )
    print("\nTop 10 bowlers:")
    print(
        result["bowler_top10"][
            [
                "rank",
                "player_name",
                "bowling_score",
                "pressure_balls",
                "pressure_matches",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
