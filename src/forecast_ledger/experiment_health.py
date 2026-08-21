from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PRIMARY_CHECKPOINT = "7d"

KNOWN_STATUSES = (
    "matched",
    "blocked",
    "interrupted",
    "partial_forecast",
)


@dataclass(frozen=True)
class PipelineSlice:
    checkpoints: int
    unique_markets: int
    event_clusters: int

    matched: int
    blocked: int
    interrupted: int
    partial_forecast: int
    other: int


@dataclass(frozen=True)
class CountByName:
    name: str
    count: int


@dataclass(frozen=True)
class NonMatchedCheckpoint:
    market_id: str
    checkpoint: str
    question: str

    pipeline_status: str

    retrieval_status: str | None
    retrieval_attempt_number: int | None
    retrieval_error_type: str | None

    has_valid_packet: bool
    condition_count: int


@dataclass(frozen=True)
class ExperimentHealth:
    overall: PipelineSlice
    primary_7d: PipelineSlice

    primary_resolved_scored: int

    retrieval_failure_types: tuple[
        CountByName,
        ...,
    ]

    nonmatched_checkpoints: tuple[
        NonMatchedCheckpoint,
        ...,
    ]


def _summarize_slice(
    rows: Sequence[Mapping[str, Any]],
) -> PipelineSlice:
    status_counts = Counter(
        str(
            row.get(
                "pipeline_status",
                "",
            )
        )
        for row in rows
    )

    known_count = sum(
        status_counts.get(
            status,
            0,
        )
        for status in KNOWN_STATUSES
    )

    market_ids = {
        str(row["market_id"])
        for row in rows
        if row.get("market_id")
    }

    event_ids = {
        str(row["event_id"])
        for row in rows
        if row.get("event_id")
    }

    return PipelineSlice(
        checkpoints=len(rows),
        unique_markets=len(
            market_ids
        ),
        event_clusters=len(
            event_ids
        ),
        matched=status_counts.get(
            "matched",
            0,
        ),
        blocked=status_counts.get(
            "blocked",
            0,
        ),
        interrupted=status_counts.get(
            "interrupted",
            0,
        ),
        partial_forecast=(
            status_counts.get(
                "partial_forecast",
                0,
            )
        ),
        other=(
            len(rows)
            - known_count
        ),
    )


def summarize_experiment_health(
    rows: Sequence[
        Mapping[str, Any]
    ],
    *,
    primary_resolved_scored: int,
) -> ExperimentHealth:
    all_rows = tuple(rows)

    primary_rows = tuple(
        row
        for row in all_rows
        if row.get(
            "checkpoint"
        )
        == PRIMARY_CHECKPOINT
    )

    overall = _summarize_slice(
        all_rows
    )

    primary = _summarize_slice(
        primary_rows
    )

    if primary_resolved_scored < 0:
        raise ValueError(
            "Resolved scored count "
            "cannot be negative."
        )

    if (
        primary_resolved_scored
        > primary.matched
    ):
        raise ValueError(
            "Resolved scored primary "
            "checkpoints cannot exceed "
            "matched primary checkpoints."
        )

    error_counts = Counter(
        (
            row.get(
                "retrieval_error_type"
            )
            or "UnknownRetrievalError"
        )
        for row in all_rows
        if row.get(
            "retrieval_status"
        )
        == "failed"
    )

    retrieval_failure_types = tuple(
        CountByName(
            name=str(name),
            count=count,
        )
        for name, count in sorted(
            error_counts.items(),
            key=lambda item: (
                -item[1],
                str(item[0]),
            ),
        )
    )

    checkpoint_order = {
        "1d": 1,
        "3d": 3,
        "7d": 7,
        "14d": 14,
    }

    nonmatched = []

    for row in all_rows:
        if (
            row.get(
                "pipeline_status"
            )
            == "matched"
        ):
            continue

        attempt_number = row.get(
            "retrieval_attempt_number"
        )

        nonmatched.append(
            NonMatchedCheckpoint(
                market_id=str(
                    row.get(
                        "market_id",
                        "",
                    )
                ),
                checkpoint=str(
                    row.get(
                        "checkpoint",
                        "",
                    )
                ),
                question=str(
                    row.get(
                        "question",
                        "",
                    )
                ),
                pipeline_status=str(
                    row.get(
                        "pipeline_status",
                        "",
                    )
                ),
                retrieval_status=(
                    None
                    if row.get(
                        "retrieval_status"
                    )
                    is None
                    else str(
                        row.get(
                            "retrieval_status"
                        )
                    )
                ),
                retrieval_attempt_number=(
                    None
                    if attempt_number
                    is None
                    else int(
                        attempt_number
                    )
                ),
                retrieval_error_type=(
                    None
                    if row.get(
                        "retrieval_error_type"
                    )
                    is None
                    else str(
                        row.get(
                            "retrieval_error_type"
                        )
                    )
                ),
                has_valid_packet=bool(
                    row.get(
                        "has_valid_packet"
                    )
                ),
                condition_count=int(
                    row.get(
                        "condition_count"
                    )
                    or 0
                ),
            )
        )

    nonmatched.sort(
        key=lambda row: (
            checkpoint_order.get(
                row.checkpoint,
                99,
            ),
            row.market_id,
        )
    )

    return ExperimentHealth(
        overall=overall,
        primary_7d=primary,
        primary_resolved_scored=(
            primary_resolved_scored
        ),
        retrieval_failure_types=(
            retrieval_failure_types
        ),
        nonmatched_checkpoints=tuple(
            nonmatched
        ),
    )
