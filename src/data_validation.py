"""Relationship and cricket data-quality checks for Phase 1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

if __package__:
    from .data_exploration import (
        DATASET_FILES,
        load_datasets,
        profile_datasets,
        resolve_data_dir,
    )
else:
    from data_exploration import (
        DATASET_FILES,
        load_datasets,
        profile_datasets,
        resolve_data_dir,
    )


CANDIDATE_PRIMARY_KEYS = {
    "ball_by_ball": [
        ("match_id", "innings", "overid", "over_ball_num"),
        ("match_id", "innings", "innings_ball_num"),
    ],
    "matches": [("match_id",)],
    "competitions": [("comp_id",)],
    "teams": [("comp_id", "team_id")],
    "playing_eleven": [("match_id", "team_id", "player_id")],
    "competition_team_player_mapping": [
        ("comp_id", "team_id", "player_id")
    ],
}


FOREIGN_KEY_CANDIDATES = {
    "ball_by_ball": [
        "match_id -> matches.match_id",
        "batting_team_id / bowling_team_id -> match home/away team IDs",
        "striker_id / non_striker_id / bowler_id / dismissed_player_id -> "
        "competition_team_player_mapping by competition and player",
    ],
    "matches": [
        "comp_id -> competitions.comp_id",
        "home_team_id / away_team_id / toss_win_team_id / win_team_id -> "
        "teams by comp_id and team_id",
        "home_team_captain_id / away_team_captain_id / man_of_the_match -> "
        "competition_team_player_mapping by comp_id and player_id",
    ],
    "competitions": [],
    "teams": [
        "comp_id -> competitions.comp_id",
        "(comp_id, team_id) -> competition_team_player_mapping",
    ],
    "playing_eleven": [
        "match_id -> matches.match_id",
        "(match_id, team_id) -> match home/away team IDs",
        "(match competition, team_id, player_id) -> "
        "competition_team_player_mapping",
    ],
    "competition_team_player_mapping": [
        "comp_id -> competitions.comp_id",
        "(comp_id, team_id) -> teams",
    ],
}


def _require_columns(
    datasets: dict[str, pd.DataFrame],
    required: dict[str, Iterable[str]],
) -> None:
    errors = []
    for dataset_name, columns in required.items():
        if dataset_name not in datasets:
            errors.append(f"missing dataset {dataset_name}")
            continue
        missing = sorted(set(columns) - set(datasets[dataset_name].columns))
        if missing:
            errors.append(f"{dataset_name}: missing columns {', '.join(missing)}")
    if errors:
        raise ValueError("Invalid dataset schemas: " + "; ".join(errors))


def _tuple_set(frame: pd.DataFrame, columns: list[str]) -> set[tuple[Any, ...]]:
    values = frame[columns].dropna().drop_duplicates()
    return {tuple(row) for row in values.itertuples(index=False, name=None)}


def _unmatched(
    source: pd.DataFrame,
    source_columns: list[str],
    target: pd.DataFrame,
    target_columns: list[str],
) -> dict[str, Any]:
    source_values = source[source_columns].dropna()
    target_values = _tuple_set(target, target_columns)
    missing_rows = [
        tuple(row)
        for row in source_values.itertuples(index=False, name=None)
        if tuple(row) not in target_values
    ]
    missing = list(dict.fromkeys(missing_rows))
    return {
        "unmatched_count": len(missing),
        "unmatched_row_count": len(missing_rows),
        "examples": [list(value) for value in missing[:10]],
    }


def candidate_key_results(
    datasets: dict[str, pd.DataFrame],
) -> dict[str, list[dict[str, Any]]]:
    results: dict[str, list[dict[str, Any]]] = {}
    for dataset_name, candidates in CANDIDATE_PRIMARY_KEYS.items():
        frame = datasets[dataset_name]
        results[dataset_name] = []
        for key in candidates:
            if not set(key).issubset(frame.columns):
                continue
            results[dataset_name].append(
                {
                    "columns": list(key),
                    "duplicate_rows": int(
                        frame.duplicated(list(key), keep=False).sum()
                    ),
                    "null_rows": int(frame[list(key)].isna().any(axis=1).sum()),
                    "unique": bool(
                        frame[list(key)].notna().all(axis=1).all()
                        and not frame.duplicated(list(key)).any()
                    ),
                }
            )
    return results


def relationship_checks(
    datasets: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    _require_columns(
        datasets,
        {
            "ball_by_ball": [
                "match_id",
                "batting_team_id",
                "bowling_team_id",
                "striker_id",
                "non_striker_id",
                "bowler_id",
                "dismissed_player_id",
            ],
            "matches": [
                "match_id",
                "comp_id",
                "home_team_id",
                "away_team_id",
                "home_team",
                "away_team",
                "home_team_captain_id",
                "away_team_captain_id",
                "toss_win_team_id",
                "win_team_id",
                "man_of_the_match",
            ],
            "competitions": ["comp_id"],
            "teams": ["comp_id", "team_id", "team_name"],
            "playing_eleven": ["match_id", "team_id", "player_id"],
            "competition_team_player_mapping": [
                "comp_id",
                "team_id",
                "player_id",
                "player_name",
            ],
        },
    )
    ball = datasets["ball_by_ball"]
    matches = datasets["matches"]
    competitions = datasets["competitions"]
    teams = datasets["teams"]
    playing = datasets["playing_eleven"]
    mapping = datasets["competition_team_player_mapping"]
    checks: list[dict[str, Any]] = []

    def add(name: str, values: dict[str, Any]) -> None:
        checks.append({"name": name, **values})

    add(
        "ball_by_ball.match_id -> matches.match_id",
        _unmatched(ball, ["match_id"], matches, ["match_id"]),
    )
    add(
        "matches.match_id with no ball-by-ball records",
        _unmatched(matches, ["match_id"], ball, ["match_id"]),
    )
    add(
        "matches.comp_id -> competitions.comp_id",
        _unmatched(matches, ["comp_id"], competitions, ["comp_id"]),
    )
    add(
        "teams.comp_id -> competitions.comp_id",
        _unmatched(teams, ["comp_id"], competitions, ["comp_id"]),
    )
    add(
        "mapping.comp_id -> competitions.comp_id",
        _unmatched(mapping, ["comp_id"], competitions, ["comp_id"]),
    )
    add(
        "mapping.(comp_id, team_id) -> teams",
        _unmatched(
            mapping,
            ["comp_id", "team_id"],
            teams,
            ["comp_id", "team_id"],
        ),
    )
    add(
        "teams.(comp_id, team_id) -> mapping",
        _unmatched(
            teams,
            ["comp_id", "team_id"],
            mapping,
            ["comp_id", "team_id"],
        ),
    )

    match_comp = matches[["match_id", "comp_id"]]
    team_pairs = teams[["comp_id", "team_id"]]
    valid_team_pairs = _tuple_set(team_pairs, ["comp_id", "team_id"])
    for side in ("home", "away"):
        source = matches[["comp_id", f"{side}_team_id"]].rename(
            columns={f"{side}_team_id": "team_id"}
        )
        add(
            f"matches.{side}_team_id -> teams by competition",
            {
                "unmatched_count": sum(
                    tuple(row) not in valid_team_pairs
                    for row in source.dropna().drop_duplicates().itertuples(
                        index=False, name=None
                    )
                ),
                "examples": [
                    list(row)
                    for row in source.dropna()
                    .drop_duplicates()
                    .itertuples(index=False, name=None)
                    if tuple(row) not in valid_team_pairs
                ][:10],
            },
        )

    team_names = teams.set_index(["comp_id", "team_id"])["team_name"].to_dict()
    for side in ("home", "away"):
        name_col = f"{side}_team"
        id_col = f"{side}_team_id"
        mismatch = []
        for row in matches[["match_id", "comp_id", id_col, name_col]].itertuples(
            index=False
        ):
            expected = team_names.get((row.comp_id, getattr(row, id_col)))
            if expected is not None and str(expected).strip().casefold() != str(
                getattr(row, name_col)
            ).strip().casefold():
                mismatch.append(
                    [
                        row.match_id,
                        row.comp_id,
                        getattr(row, id_col),
                        getattr(row, name_col),
                        expected,
                    ]
                )
        add(
            f"matches.{name_col} agrees with team ID",
            {"unmatched_count": len(mismatch), "examples": mismatch[:10]},
        )

    add(
        "playing_eleven.match_id -> matches.match_id",
        _unmatched(playing, ["match_id"], matches, ["match_id"]),
    )
    playing_matches = playing.merge(
        match_comp, on="match_id", how="left", validate="many_to_one"
    )
    match_teams = matches[["match_id", "home_team_id", "away_team_id"]]
    playing_match_teams = playing_matches.merge(
        match_teams, on="match_id", how="left", validate="many_to_one"
    )
    team_mismatch = playing_match_teams[
        (playing_match_teams["team_id"] != playing_match_teams["home_team_id"])
        & (playing_match_teams["team_id"] != playing_match_teams["away_team_id"])
    ]
    add(
        "playing_eleven.team_id -> match home/away team",
        {
            "unmatched_count": int(len(team_mismatch)),
            "examples": team_mismatch[
                ["match_id", "team_id", "home_team_id", "away_team_id"]
            ]
            .drop_duplicates()
            .head(10)
            .values.tolist(),
        },
    )

    playing_players = playing_matches[["comp_id", "team_id", "player_id"]]
    add(
        "playing_eleven player -> mapping by competition and team",
        _unmatched(
            playing_players,
            ["comp_id", "team_id", "player_id"],
            mapping,
            ["comp_id", "team_id", "player_id"],
        ),
    )

    ball_comp = ball[["match_id"]].merge(
        match_comp, on="match_id", how="left", validate="many_to_one"
    )
    for role in (
        "striker_id",
        "non_striker_id",
        "bowler_id",
        "dismissed_player_id",
    ):
        player_values = ball_comp[["comp_id"]].copy()
        player_values["player_id"] = ball[role].to_numpy()
        add(
            f"ball_by_ball.{role} -> mapping by competition",
            _unmatched(
                player_values,
                ["comp_id", "player_id"],
                mapping,
                ["comp_id", "player_id"],
            ),
        )

    for column in (
        "home_team_captain_id",
        "away_team_captain_id",
        "man_of_the_match",
    ):
        people = matches[["comp_id", column]].dropna().copy()
        people = people[people[column] != 0].rename(
            columns={column: "player_id"}
        )
        add(
            f"matches.{column} -> mapping by competition",
            _unmatched(
                people,
                ["comp_id", "player_id"],
                mapping,
                ["comp_id", "player_id"],
            ),
        )
    for column in ("toss_win_team_id", "win_team_id"):
        source = matches[["comp_id", column]].dropna().rename(
            columns={column: "team_id"}
        )
        add(
            f"matches.{column} -> teams by competition",
            _unmatched(
                source,
                ["comp_id", "team_id"],
                teams,
                ["comp_id", "team_id"],
            ),
        )

    ball_team_pairs = ball[
        ["match_id", "batting_team_id", "bowling_team_id"]
    ].drop_duplicates()
    ball_match_teams = ball_team_pairs.merge(
        match_teams, on="match_id", how="left", validate="many_to_one"
    )
    invalid_ball_teams = ball_match_teams[
        ~(
            (
                ball_match_teams["batting_team_id"]
                == ball_match_teams["home_team_id"]
            )
            & (
                ball_match_teams["bowling_team_id"]
                == ball_match_teams["away_team_id"]
            )
            | (
                ball_match_teams["batting_team_id"]
                == ball_match_teams["away_team_id"]
            )
            & (
                ball_match_teams["bowling_team_id"]
                == ball_match_teams["home_team_id"]
            )
        )
    ]
    add(
        "ball_by_ball batting/bowling teams are the match teams",
        {
            "unmatched_count": int(len(invalid_ball_teams)),
            "examples": invalid_ball_teams.head(10).values.tolist(),
        },
    )
    return checks


def cricket_quality_checks(
    ball: pd.DataFrame,
    matches: pd.DataFrame,
    competitions: pd.DataFrame,
    mapping: pd.DataFrame | None = None,
) -> dict[str, Any]:
    _require_columns(
        {
            "ball_by_ball": ball,
            "matches": matches,
            "competitions": competitions,
        },
        {
            "ball_by_ball": [
                "match_id",
                "innings",
                "overid",
                "over_ball_num",
                "innings_ball_num",
                "is_wicket",
                "dismissal_type_id",
                "dismissal_type",
                "dismissed_player_id",
                "extras_type",
                "extras1_runs",
                "extras_2_runs",
                "is_four",
                "is_six",
                "runs",
            ],
            "matches": ["match_id", "comp_id", "result"],
            "competitions": ["comp_id", "match_format", "season"],
        },
    )
    checks: dict[str, Any] = {}
    checks["innings_counts"] = {
        str(int(key)): int(value)
        for key, value in ball["innings"].value_counts().sort_index().items()
    }
    per_match_innings = ball.groupby("match_id")["innings"].agg(
        lambda values: set(values)
    )
    missing_standard_innings = [
        int(match_id)
        for match_id, innings in per_match_innings.items()
        if not {1, 2}.issubset(innings)
    ]
    checks["matches_missing_innings_1_or_2"] = {
        "count": len(missing_standard_innings),
        "examples": missing_standard_innings[:10],
    }
    no_ball_matches = matches.loc[
        ~matches["match_id"].isin(ball["match_id"]), ["match_id", "result"]
    ]
    checks["matches_without_ball_by_ball"] = {
        "count": int(len(no_ball_matches)),
        "result_counts": {
            str(key): int(value)
            for key, value in no_ball_matches["result"]
            .value_counts(dropna=False)
            .items()
        },
        "examples": no_ball_matches.head(10).to_dict("records"),
    }
    checks["innings_above_2"] = {
        "row_count": int((ball["innings"] > 2).sum()),
        "match_count": int(ball.loc[ball["innings"] > 2, "match_id"].nunique()),
        "innings_values": sorted(
            int(value) for value in ball.loc[ball["innings"] > 2, "innings"].unique()
        ),
    }

    delivery_key = ["match_id", "innings", "overid", "over_ball_num"]
    innings_sequence_key = ["match_id", "innings", "innings_ball_num"]
    checks["delivery_numbering"] = {
        "candidate_key_duplicate_rows": int(
            ball.duplicated(delivery_key, keep=False).sum()
        ),
        "innings_sequence_duplicate_rows": int(
            ball.duplicated(innings_sequence_key, keep=False).sum()
        ),
        "over_ball_num_min": int(ball["over_ball_num"].min()),
        "over_ball_num_max": int(ball["over_ball_num"].max()),
        "over_ball_num_above_6_rows": int((ball["over_ball_num"] > 6).sum()),
        "over_ball_num_above_6_examples": ball.loc[
            ball["over_ball_num"] > 6,
            ["match_id", "innings", "overid", "over_ball_num", "extras_type"],
        ]
        .head(10)
        .to_dict("records"),
        "overid_min": int(ball["overid"].min()),
        "overid_max": int(ball["overid"].max()),
    }

    extras_present = ball["extras_type"].notna()
    extras_numeric = ball[["extras1_runs", "extras_2_runs"]].fillna(0).sum(axis=1)
    checks["extras"] = {
        "types": {
            str(key): int(value)
            for key, value in ball["extras_type"].value_counts(
                dropna=False
            ).items()
        },
        "nonzero_runs_without_type_rows": int(
            ((~extras_present) & (extras_numeric > 0)).sum()
        ),
        "nonzero_runs_without_type_examples": ball.loc[
            (~extras_present) & (extras_numeric > 0),
            [
                "match_id",
                "innings",
                "overid",
                "over_ball_num",
                "extras1_runs",
                "extras_2_runs",
            ],
        ]
        .head(10)
        .to_dict("records"),
        "type_present_but_numeric_fields_zero_rows": int(
            (extras_present & (extras_numeric == 0)).sum()
        ),
        "type_present_but_numeric_fields_zero_examples": ball.loc[
            extras_present & (extras_numeric == 0),
            [
                "match_id",
                "innings",
                "overid",
                "over_ball_num",
                "extras_type",
                "extras1_runs",
                "extras_2_runs",
            ],
        ]
        .head(10)
        .to_dict("records"),
        "negative_extras_rows": int(
            (
                (ball["extras1_runs"] < 0)
                | (ball["extras_2_runs"] < 0)
            ).sum()
        ),
    }

    wicket_flag = ball["is_wicket"].fillna(False).astype(bool)
    dismissal_id_present = ball["dismissal_type_id"].notna()
    dismissed_id_present = ball["dismissed_player_id"].notna()
    checks["wickets"] = {
        "wicket_rows": int(wicket_flag.sum()),
        "wicket_without_dismissal_type_id": int(
            (wicket_flag & ~dismissal_id_present).sum()
        ),
        "dismissal_type_id_without_wicket_flag": int(
            (~wicket_flag & dismissal_id_present).sum()
        ),
        "wicket_without_dismissed_player_id": int(
            (wicket_flag & ~dismissed_id_present).sum()
        ),
        "dismissed_player_id_without_wicket_flag": int(
            (~wicket_flag & dismissed_id_present).sum()
        ),
        "dismissed_player_id_without_wicket_examples": ball.loc[
            (~wicket_flag) & dismissed_id_present,
            [
                "match_id",
                "innings",
                "overid",
                "over_ball_num",
                "dismissed_player_id",
            ],
        ]
        .head(10)
        .to_dict("records"),
        "wicket_without_dismissed_player_examples": ball.loc[
            wicket_flag & ~dismissed_id_present,
            ["match_id", "innings", "overid", "over_ball_num", "dismissal_type"],
        ]
        .head(10)
        .to_dict("records"),
    }

    checks["boundary_flags"] = {
        "four_and_six_both_true": int((ball["is_four"] & ball["is_six"]).sum()),
        "is_four_but_runs_not_4": int(
            (ball["is_four"] & (ball["runs"] != 4)).sum()
        ),
        "is_six_but_runs_not_6": int(
            (ball["is_six"] & (ball["runs"] != 6)).sum()
        ),
    }

    joined = matches[["match_id", "comp_id", "result"]].merge(
        competitions[["comp_id", "match_format", "season"]],
        on="comp_id",
        how="left",
        validate="many_to_one",
    )
    checks["formats"] = {
        "competition_counts": {
            str(key): int(value)
            for key, value in competitions["match_format"]
            .value_counts(dropna=False)
            .items()
        },
        "match_counts": {
            str(key): int(value)
            for key, value in joined["match_format"]
            .value_counts(dropna=False)
            .items()
        },
        "seasons": sorted(
            str(value) for value in competitions["season"].dropna().unique()
        ),
    }
    if mapping is not None:
        _require_columns(
            {"competition_team_player_mapping": mapping},
            {
                "competition_team_player_mapping": [
                    "comp_id",
                    "player_id",
                    "player_name",
                ]
            },
        )
        player_names = mapping.drop_duplicates(["comp_id", "player_id"]).set_index(
            ["comp_id", "player_id"]
        )["player_name"].to_dict()
        name_checks = {}
        ball_competitions = ball[["match_id"]].merge(
            matches[["match_id", "comp_id"]],
            on="match_id",
            how="left",
            validate="many_to_one",
        )
        for player_id_column, player_name_column in (
            ("striker_id", "striker_name"),
            ("non_striker_id", "non_striker_name"),
            ("bowler_id", "bowler_name"),
        ):
            if not {
                player_id_column,
                player_name_column,
            }.issubset(ball.columns):
                continue
            observed = ball_competitions[["comp_id"]].copy()
            observed["player_id"] = ball[player_id_column].to_numpy()
            observed["observed_name"] = ball[player_name_column].to_numpy()
            observed = observed.drop_duplicates()
            observed["mapped_name"] = [
                player_names.get((comp_id, player_id))
                for comp_id, player_id in observed[
                    ["comp_id", "player_id"]
                ].itertuples(index=False, name=None)
            ]
            mismatch = observed[
                observed["mapped_name"].notna()
                & observed["observed_name"]
                .astype(str)
                .str.strip()
                .str.casefold()
                .ne(
                    observed["mapped_name"]
                    .astype(str)
                    .str.strip()
                    .str.casefold()
                )
            ]
            name_checks[player_name_column] = {
                "mismatch_count": int(len(mismatch)),
                "examples": mismatch.head(10).to_dict("records"),
            }
        checks["player_name_consistency"] = name_checks
    return checks


def validate_datasets(datasets: dict[str, pd.DataFrame]) -> dict[str, Any]:
    missing_datasets = sorted(set(DATASET_FILES) - set(datasets))
    if missing_datasets:
        raise ValueError(
            "Missing datasets: " + ", ".join(missing_datasets)
        )
    return {
        "candidate_keys": candidate_key_results(datasets),
        "relationships": relationship_checks(datasets),
        "cricket_quality": cricket_quality_checks(
            datasets["ball_by_ball"],
            datasets["matches"],
            datasets["competitions"],
            datasets["competition_team_player_mapping"],
        ),
    }


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def build_report(
    datasets: dict[str, pd.DataFrame],
    validation: dict[str, Any],
    data_dir: Path,
) -> str:
    profiles = profile_datasets(datasets)
    sections = [
        "# SupeRR Selector Season 2 — Phase 1 Data Exploration and Validation",
        "",
        f"**Source directory:** `{data_dir}`  ",
        f"**Datasets loaded:** {len(datasets)}  ",
        "**Scope:** schema profiling, joins, and data-quality checks only. No source CSVs were modified; no player rankings or pressure labels were created.",
        "",
        "## Dataset relationship diagram",
        "",
        "```mermaid",
        "erDiagram",
        "    COMPETITIONS ||--o{ MATCHES : comp_id",
        "    COMPETITIONS ||--o{ TEAMS : comp_id",
        "    COMPETITIONS ||--o{ COMPETITION_TEAM_PLAYER_MAPPING : comp_id",
        "    TEAMS ||--o{ COMPETITION_TEAM_PLAYER_MAPPING : comp_id_team_id",
        "    MATCHES ||--o{ BALL_BY_BALL : match_id",
        "    MATCHES ||--o{ PLAYING_ELEVEN : match_id",
        "    COMPETITION_TEAM_PLAYER_MAPPING ||--o{ BALL_BY_BALL : player_ids_by_competition",
        "    COMPETITION_TEAM_PLAYER_MAPPING ||--o{ PLAYING_ELEVEN : player_id_by_match_competition_team",
        "```",
        "",
        "The diagram shows candidate relationships, not enforced database constraints. `teams` is competition-scoped, so use `(comp_id, team_id)` rather than `team_id` alone. `playing_eleven` needs `matches` to obtain `comp_id` before checking its composite player mapping.",
        "",
        "## Dataset profiles",
        "",
    ]
    for name, profile in profiles.items():
        sections.extend(
            [
                f"### `{DATASET_FILES[name]}`",
                "",
                f"- Shape: **{profile['rows']:,} rows × {profile['column_count']} columns**",
                f"- Exact duplicate records: **{profile['exact_duplicate_rows']:,}**",
                f"- Individually unique, non-null columns: "
                f"{', '.join(f'`{x}`' for x in profile['non_null_unique_columns']) or 'none'}",
                f"- Candidate primary keys tested: "
                f"{', '.join('(' + ', '.join(f'`{col}`' for col in key['columns']) + ') ' + ('unique' if key['unique'] else 'not unique') for key in validation['candidate_keys'][name]) or 'none applicable'}",
                "- Candidate foreign keys:",
            ]
        )
        fk = FOREIGN_KEY_CANDIDATES[name]
        sections.extend([f"  - {item}" for item in fk] or ["  - None identified."])
        schema_rows = [
            [
                column["name"],
                column["dtype"],
                column["missing"],
                f"{column['missing_pct']:.2f}%",
                column["distinct"],
            ]
            for column in profile["columns"]
        ]
        sections.extend(
            [
                "",
                _markdown_table(
                    ["Column", "Inferred dtype", "Missing", "Missing %", "Distinct"],
                    schema_rows,
                ),
                "",
                "Sample records (first three):",
                "",
                "```json",
                json.dumps(profile["sample_records"], ensure_ascii=False, indent=2, default=str),
                "```",
                "",
            ]
        )

    sections.extend(["## Relationship validation", ""])
    rel_rows = [
        [
            check["name"],
            (
                f"{check['unmatched_count']} / "
                f"{check.get('unmatched_row_count', check['unmatched_count'])}"
            ),
            json.dumps(check["examples"], default=str),
        ]
        for check in validation["relationships"]
    ]
    sections.extend(
        [
            _markdown_table(
                [
                    "Join / consistency check",
                    "Unmatched distinct keys / source rows",
                    "Examples",
                ],
                rel_rows,
            ),
            "",
            "An unmatched match with no ball-by-ball data is not automatically an error; its match result is shown in the cricket checks. The five `teams` competition/team pairs absent from the mapping table can reflect mapping coverage gaps; they are retained and reported.",
            "",
            "## Cricket data validation",
            "",
        ]
    )
    quality = validation["cricket_quality"]
    qrows: list[list[Any]] = [
        ["Innings row counts", json.dumps(quality["innings_counts"])],
        ["Matches missing innings 1 or 2", json.dumps(quality["matches_missing_innings_1_or_2"])],
        ["Rows / matches with innings > 2", json.dumps(quality["innings_above_2"])],
        ["Delivery numbering", json.dumps(quality["delivery_numbering"])],
        ["Extras checks", json.dumps(quality["extras"])],
        ["Wicket checks", json.dumps(quality["wickets"])],
        ["Boundary flag checks", json.dumps(quality["boundary_flags"])],
        ["Batter/bowler name checks", json.dumps(quality.get("player_name_consistency", {}))],
        ["Matches without ball data", json.dumps(quality["matches_without_ball_by_ball"])],
        ["Competition formats and seasons", json.dumps(quality["formats"])],
    ]
    sections.extend(
        [
            _markdown_table(["Area", "Observed results"], qrows),
            "",
            "### Interpretation notes",
            "",
            "- `over_ball_num` exceeds 6 in some rows. The field’s exact numbering semantics are not documented in these files, so these rows are flagged for source clarification rather than dropped or automatically treated as invalid.",
            "- Innings numbered 3 or 4 may represent super overs or other extra innings; that interpretation is plausible but cannot be proven from these columns alone.",
            "- `runs`, `extras1_runs`, and `extras_2_runs` are reported as distinct observed fields. The implementation does not assume that `runs` is the total including extras.",
            "- A zero `man_of_the_match` value is treated as a sentinel and excluded from player foreign-key checks; that interpretation should be confirmed with the data provider.",
            "- No records are deleted or rewritten. Missingness and anomalous records remain visible in the report.",
            "",
            "## Assumptions and limitations",
            "",
            "- Candidate keys and relationships are validated by observed IDs and uniqueness; CSVs do not declare database constraints.",
            "- Candidate player mapping is scoped to the competition. Batter, bowler, dismissal, captain, and player-of-the-match IDs are checked against the available mapping table.",
            "- `data/` is preferred when it contains all six inputs. For this workspace, the six CSVs were found at the workspace root and the scripts use that location as a fallback.",
            "- The reported dtypes are pandas inference from the input CSVs, not an authoritative source schema.",
            "- Phase 1 does not calculate player rankings or classify pressure situations.",
            "",
        ]
    )
    return "\n".join(sections)


def write_report(
    datasets: dict[str, pd.DataFrame],
    validation: dict[str, Any],
    report_path: Path | None = None,
    data_dir: Path | None = None,
) -> Path:
    root = Path(__file__).resolve().parents[1]
    target = report_path or root / "reports" / "phase1_report.md"
    source_dir = data_dir or resolve_data_dir(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        build_report(datasets, validation, source_dir),
        encoding="utf-8",
    )
    return target


def main() -> None:
    data_dir = resolve_data_dir()
    datasets = load_datasets(data_dir)
    validation = validate_datasets(datasets)
    report_path = write_report(datasets, validation, data_dir=data_dir)
    print(f"Validation report: {report_path}")
    for check in validation["relationships"]:
        print(
            f"{check['name']}: {check['unmatched_count']} unmatched; "
            f"examples={check['examples'][:3]}"
        )
    print("Cricket quality checks:")
    print(json.dumps(validation["cricket_quality"], indent=2, default=str))


if __name__ == "__main__":
    main()
