"""Exploratory profiling for the SupeRR Selector Phase 1 datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


DATASET_FILES = {
    "ball_by_ball": "ball_by_ball.csv",
    "matches": "matches.csv",
    "competitions": "competitions.csv",
    "teams": "teams.csv",
    "playing_eleven": "playing_eleven.csv",
    "competition_team_player_mapping": "competition_team_player_mapping.csv",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_data_dir(root: Path | None = None) -> Path:
    """Prefer data/; allow workspace-root CSVs when all six are there."""
    root = root or project_root()
    candidates = (root / "data", root)
    for candidate in candidates:
        if all((candidate / filename).is_file() for filename in DATASET_FILES.values()):
            return candidate

    expected = ", ".join(DATASET_FILES.values())
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Could not find all required CSV files ({expected}) in: {checked}"
    )


def load_datasets(data_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    directory = data_dir or resolve_data_dir()
    missing = [
        filename
        for filename in DATASET_FILES.values()
        if not (directory / filename).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing required CSV files in {directory}: {', '.join(missing)}"
        )
    return {
        name: pd.read_csv(directory / filename, low_memory=False)
        for name, filename in DATASET_FILES.items()
    }


def profile_dataset(frame: pd.DataFrame) -> dict[str, Any]:
    columns = []
    for name in frame.columns:
        series = frame[name]
        columns.append(
            {
                "name": name,
                "dtype": str(series.dtype),
                "missing": int(series.isna().sum()),
                "missing_pct": (
                    float(series.isna().mean() * 100) if len(frame) else 0.0
                ),
                "distinct": int(series.nunique(dropna=True)),
            }
        )

    unique_columns = [
        name
        for name in frame.columns
        if frame[name].notna().all() and frame[name].is_unique
    ]
    return {
        "rows": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": columns,
        "exact_duplicate_rows": int(frame.duplicated().sum()),
        "non_null_unique_columns": unique_columns,
        "sample_records": frame.head(3).to_dict(orient="records"),
    }


def profile_datasets(
    datasets: dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    return {name: profile_dataset(frame) for name, frame in datasets.items()}


def main() -> None:
    data_dir = resolve_data_dir()
    datasets = load_datasets(data_dir)
    print(f"Data directory: {data_dir}")
    for name, profile in profile_datasets(datasets).items():
        print(
            f"\n{name}: {profile['rows']:,} rows x "
            f"{profile['column_count']} columns; "
            f"{profile['exact_duplicate_rows']:,} exact duplicate rows"
        )
        print("Columns (name: dtype, missing, distinct):")
        for column in profile["columns"]:
            print(
                f"  {column['name']}: {column['dtype']}, "
                f"missing={column['missing']:,}, "
                f"distinct={column['distinct']:,}"
            )
        print("Sample records:")
        for sample in profile["sample_records"]:
            print(f"  {sample}")


if __name__ == "__main__":
    main()
