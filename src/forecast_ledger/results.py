from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from statistics import fmean

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.metrics import (
    brier_score,
    directional_accuracy,
    log_loss,
)
from forecast_ledger.registry import PROTOCOL_VERSION


@dataclass(frozen=True)
class ScoredCheckpoint:
    market_id: str
    question: str
    checkpoint: Checkpoint
    outcome_yes: bool

    market_probability: float
    direct_probability: float
    structured_probability: float
    market_aware_probability: float

    market_brier: float
    direct_brier: float
    structured_brier: float
    market_aware_brier: float

    market_log_loss: float
    direct_log_loss: float
    structured_log_loss: float
    market_aware_log_loss: float

    market_directional_accuracy: bool | None
    direct_directional_accuracy: bool | None
    structured_directional_accuracy: bool | None
    market_aware_directional_accuracy: bool | None

    structured_advantage: float
    market_information_advantage: float


@dataclass(frozen=True)
class ResultsSummary:
    n: int

    mean_market_brier: float | None
    mean_direct_brier: float | None
    mean_structured_brier: float | None
    mean_market_aware_brier: float | None

    mean_structured_advantage: float | None
    mean_market_information_advantage: float | None


def load_scored_checkpoints(
    connection: sqlite3.Connection,
    checkpoint: Checkpoint | None = None,
    protocol_version: str = PROTOCOL_VERSION,
) -> tuple[ScoredCheckpoint, ...]:
    checkpoint_value = (
        None
        if checkpoint is None
        else checkpoint.value
    )

    rows = connection.execute(
        """
        WITH forecast_summary AS (
            SELECT
                market_id,
                checkpoint,
                protocol_version,

                COUNT(*) AS forecast_count,
                COUNT(DISTINCT condition)
                    AS condition_count,
                COUNT(DISTINCT packet_id)
                    AS packet_count,
                COUNT(DISTINCT snapshot_id)
                    AS snapshot_count,
                COUNT(DISTINCT model)
                    AS model_count,

                MIN(snapshot_id)
                    AS snapshot_id,

                MAX(
                    CASE
                        WHEN condition = 'B_direct'
                        THEN probability_yes
                    END
                ) AS direct_probability,

                MAX(
                    CASE
                        WHEN condition =
                            'C_structured_independent'
                        THEN probability_yes
                    END
                ) AS structured_probability,

                MAX(
                    CASE
                        WHEN condition =
                            'D_structured_market_aware'
                        THEN probability_yes
                    END
                ) AS market_aware_probability

            FROM forecasts

            WHERE protocol_version = ?

            GROUP BY
                market_id,
                checkpoint,
                protocol_version
        )

        SELECT
            fs.market_id,
            tm.question,
            fs.checkpoint,
            mr.outcome_yes,

            ms.yes_bid,
            ms.yes_ask,

            fs.direct_probability,
            fs.structured_probability,
            fs.market_aware_probability

        FROM forecast_summary AS fs

        JOIN market_resolutions AS mr
          ON mr.market_id = fs.market_id
         AND mr.protocol_version =
             fs.protocol_version

        JOIN tracked_markets AS tm
          ON tm.market_id = fs.market_id
         AND tm.protocol_version =
             fs.protocol_version

        JOIN market_snapshots AS ms
          ON ms.snapshot_id = fs.snapshot_id
         AND ms.market_id = fs.market_id
         AND ms.checkpoint = fs.checkpoint
         AND ms.protocol_version =
             fs.protocol_version

        WHERE fs.forecast_count = 3
          AND fs.condition_count = 3
          AND fs.packet_count = 1
          AND fs.snapshot_count = 1
          AND fs.model_count = 1

          AND fs.direct_probability
              IS NOT NULL
          AND fs.structured_probability
              IS NOT NULL
          AND fs.market_aware_probability
              IS NOT NULL

          AND mr.resolution_status
              IN (
                  'resolved_yes',
                  'resolved_no'
              )

          AND (
              ? IS NULL
              OR fs.checkpoint = ?
          )

        ORDER BY
            fs.checkpoint,
            fs.market_id
        """,
        (
            protocol_version,
            checkpoint_value,
            checkpoint_value,
        ),
    ).fetchall()

    scored = []

    for row in rows:
        outcome_yes = bool(row[3])

        market_probability = (
            float(row[4])
            + float(row[5])
        ) / 2.0

        direct_probability = float(
            row[6]
        )
        structured_probability = float(
            row[7]
        )
        market_aware_probability = float(
            row[8]
        )

        market_brier = brier_score(
            market_probability,
            outcome_yes,
        )
        direct_brier = brier_score(
            direct_probability,
            outcome_yes,
        )
        structured_brier = brier_score(
            structured_probability,
            outcome_yes,
        )
        market_aware_brier = brier_score(
            market_aware_probability,
            outcome_yes,
        )

        scored.append(
            ScoredCheckpoint(
                market_id=row[0],
                question=row[1],
                checkpoint=Checkpoint(
                    row[2]
                ),
                outcome_yes=outcome_yes,
                market_probability=(
                    market_probability
                ),
                direct_probability=(
                    direct_probability
                ),
                structured_probability=(
                    structured_probability
                ),
                market_aware_probability=(
                    market_aware_probability
                ),
                market_brier=market_brier,
                direct_brier=direct_brier,
                structured_brier=(
                    structured_brier
                ),
                market_aware_brier=(
                    market_aware_brier
                ),
                market_log_loss=log_loss(
                    market_probability,
                    outcome_yes,
                ),
                direct_log_loss=log_loss(
                    direct_probability,
                    outcome_yes,
                ),
                structured_log_loss=log_loss(
                    structured_probability,
                    outcome_yes,
                ),
                market_aware_log_loss=log_loss(
                    market_aware_probability,
                    outcome_yes,
                ),
                market_directional_accuracy=(
                    directional_accuracy(
                        market_probability,
                        outcome_yes,
                    )
                ),
                direct_directional_accuracy=(
                    directional_accuracy(
                        direct_probability,
                        outcome_yes,
                    )
                ),
                structured_directional_accuracy=(
                    directional_accuracy(
                        structured_probability,
                        outcome_yes,
                    )
                ),
                market_aware_directional_accuracy=(
                    directional_accuracy(
                        market_aware_probability,
                        outcome_yes,
                    )
                ),
                structured_advantage=(
                    direct_brier
                    - structured_brier
                ),
                market_information_advantage=(
                    structured_brier
                    - market_aware_brier
                ),
            )
        )

    return tuple(scored)


def summarize_scored_checkpoints(
    rows: tuple[ScoredCheckpoint, ...],
) -> ResultsSummary:
    if not rows:
        return ResultsSummary(
            n=0,
            mean_market_brier=None,
            mean_direct_brier=None,
            mean_structured_brier=None,
            mean_market_aware_brier=None,
            mean_structured_advantage=None,
            mean_market_information_advantage=None,
        )

    return ResultsSummary(
        n=len(rows),
        mean_market_brier=fmean(
            row.market_brier
            for row in rows
        ),
        mean_direct_brier=fmean(
            row.direct_brier
            for row in rows
        ),
        mean_structured_brier=fmean(
            row.structured_brier
            for row in rows
        ),
        mean_market_aware_brier=fmean(
            row.market_aware_brier
            for row in rows
        ),
        mean_structured_advantage=fmean(
            row.structured_advantage
            for row in rows
        ),
        mean_market_information_advantage=fmean(
            row.market_information_advantage
            for row in rows
        ),
    )


def load_primary_results(
    connection: sqlite3.Connection,
    protocol_version: str = PROTOCOL_VERSION,
) -> tuple[
    tuple[ScoredCheckpoint, ...],
    ResultsSummary,
]:
    rows = load_scored_checkpoints(
        connection=connection,
        checkpoint=Checkpoint.DAYS_7,
        protocol_version=protocol_version,
    )

    return (
        rows,
        summarize_scored_checkpoints(
            rows
        ),
    )
