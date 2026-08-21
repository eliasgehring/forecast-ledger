from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from forecast_ledger.dashboard_data import (
    load_checkpoint_status_counts,
    load_included_pipeline_rows,
    open_read_only_connection,
)
from forecast_ledger.results import (
    load_primary_results,
)

DEFAULT_DB = Path(
    "data/forecast_ledger.db"
)


@dataclass(frozen=True)
class OperationsStatus:
    tracked_markets: int

    checkpoint_statuses: dict[str, int]

    included_checkpoints: int
    matched_checkpoints: int
    blocked_checkpoints: int
    interrupted_checkpoints: int
    partial_forecasts: int

    primary_included: int
    primary_matched: int
    primary_resolved_scored: int

    unique_included_markets: int
    included_event_clusters: int


def load_operations_status(
    db_path: str | Path,
) -> OperationsStatus:
    connection = open_read_only_connection(
        db_path
    )

    try:
        tracked_markets = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM tracked_markets
                WHERE protocol_version = 'v0.2'
                """
            ).fetchone()[0]
        )

        _, primary_summary = (
            load_primary_results(
                connection
            )
        )
    finally:
        connection.close()

    pipeline_rows = (
        load_included_pipeline_rows(
            db_path
        )
    )

    status_counts = Counter(
        row["pipeline_status"]
        for row in pipeline_rows
    )

    primary_rows = [
        row
        for row in pipeline_rows
        if row["checkpoint"] == "7d"
    ]

    primary_counts = Counter(
        row["pipeline_status"]
        for row in primary_rows
    )

    checkpoint_statuses = {
        str(row["status"]): int(
            row["count"]
        )
        for row in (
            load_checkpoint_status_counts(
                db_path
            )
        )
    }

    unique_markets = {
        row["market_id"]
        for row in pipeline_rows
    }

    event_clusters = {
        row["event_id"]
        for row in pipeline_rows
        if row.get("event_id")
    }

    return OperationsStatus(
        tracked_markets=tracked_markets,
        checkpoint_statuses=(
            checkpoint_statuses
        ),
        included_checkpoints=len(
            pipeline_rows
        ),
        matched_checkpoints=(
            status_counts["matched"]
        ),
        blocked_checkpoints=(
            status_counts["blocked"]
        ),
        interrupted_checkpoints=(
            status_counts["interrupted"]
        ),
        partial_forecasts=(
            status_counts[
                "partial_forecast"
            ]
        ),
        primary_included=len(
            primary_rows
        ),
        primary_matched=(
            primary_counts["matched"]
        ),
        primary_resolved_scored=(
            primary_summary.n
        ),
        unique_included_markets=len(
            unique_markets
        ),
        included_event_clusters=len(
            event_clusters
        ),
    )


def print_status(
    status: OperationsStatus,
) -> None:
    print(
        "FORECAST LEDGER OPERATIONS"
    )
    print("=" * 72)

    print(
        f"tracked markets:          "
        f"{status.tracked_markets}"
    )

    print(
        f"included checkpoints:     "
        f"{status.included_checkpoints}"
    )

    print(
        f"unique included markets:  "
        f"{status.unique_included_markets}"
    )

    print(
        f"included event clusters:  "
        f"{status.included_event_clusters}"
    )

    print()
    print("PIPELINE")
    print("-" * 72)

    print(
        f"matched:                  "
        f"{status.matched_checkpoints}"
    )

    print(
        f"blocked:                  "
        f"{status.blocked_checkpoints}"
    )

    print(
        f"interrupted:              "
        f"{status.interrupted_checkpoints}"
    )

    print(
        f"partial forecast:         "
        f"{status.partial_forecasts}"
    )

    print()
    print("PRIMARY 7D")
    print("-" * 72)

    print(
        f"included:                 "
        f"{status.primary_included}"
    )

    print(
        f"matched:                  "
        f"{status.primary_matched}"
    )

    print(
        f"resolved + scored:        "
        f"{status.primary_resolved_scored}"
    )

    print()
    print("CHECKPOINT LEDGER")
    print("-" * 72)

    for name, count in sorted(
        status.checkpoint_statuses.items()
    ):
        print(
            f"{name:28} {count}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
    )

    args = parser.parse_args()

    status = load_operations_status(
        args.db
    )

    print_status(status)


if __name__ == "__main__":
    main()
