from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import (
    Market,
    MarketSnapshot,
    require_timezone_aware,
)
from forecast_ledger.eligibility import (
    evaluate_checkpoint_eligibility,
)
from forecast_ledger.registry import PROTOCOL_VERSION


class EligibilityConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredEligibilityDecision:
    market_id: str
    checkpoint: Checkpoint
    protocol_version: str
    snapshot_id: str
    eligible_for_review: bool
    rejection_reasons: tuple[str, ...]
    evaluated_at: datetime


def initialize_eligibility_store(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_eligibility (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            eligible_for_review INTEGER NOT NULL,
            rejection_reasons_json TEXT NOT NULL,
            evaluated_at TEXT NOT NULL,

            PRIMARY KEY (
                market_id,
                checkpoint,
                protocol_version
            )
        )
        """
    )

    connection.commit()


def _validate_snapshot_is_persisted(
    connection: sqlite3.Connection,
    market: Market,
    snapshot: MarketSnapshot,
    checkpoint: Checkpoint,
    protocol_version: str,
) -> None:
    row = connection.execute(
        """
        SELECT snapshot_id
        FROM market_snapshots
        WHERE snapshot_id = ?
          AND market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        """,
        (
            snapshot.snapshot_id,
            market.market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    if row is None:
        raise ValueError(
            "Machine eligibility requires the matching "
            "persisted market snapshot."
        )


def record_machine_eligibility(
    connection: sqlite3.Connection,
    market: Market,
    snapshot: MarketSnapshot,
    checkpoint: Checkpoint,
    evaluated_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    require_timezone_aware(
        evaluated_at,
        "evaluated_at",
    )

    if evaluated_at < snapshot.observed_at:
        raise ValueError(
            "Eligibility cannot be evaluated before "
            "the market snapshot was observed."
        )

    _validate_snapshot_is_persisted(
        connection=connection,
        market=market,
        snapshot=snapshot,
        checkpoint=checkpoint,
        protocol_version=protocol_version,
    )

    result = evaluate_checkpoint_eligibility(
        market=market,
        snapshot=snapshot,
    )

    reasons_json = json.dumps(
        list(result.rejection_reasons),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    incoming_identity = (
        snapshot.snapshot_id,
        int(result.eligible_for_review),
        reasons_json,
    )

    existing = connection.execute(
        """
        SELECT
            snapshot_id,
            eligible_for_review,
            rejection_reasons_json
        FROM machine_eligibility
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        """,
        (
            market.market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    if existing is not None:
        if existing != incoming_identity:
            raise EligibilityConflictError(
                "Stored machine eligibility differs from "
                "the decision derived from this snapshot."
            )

        return False

    connection.execute(
        """
        INSERT INTO machine_eligibility (
            market_id,
            checkpoint,
            protocol_version,
            snapshot_id,
            eligible_for_review,
            rejection_reasons_json,
            evaluated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market.market_id,
            checkpoint.value,
            protocol_version,
            snapshot.snapshot_id,
            int(result.eligible_for_review),
            reasons_json,
            evaluated_at.isoformat(),
        ),
    )

    connection.commit()

    return True


def load_machine_eligibility(
    connection: sqlite3.Connection,
    protocol_version: str = PROTOCOL_VERSION,
) -> tuple[StoredEligibilityDecision, ...]:
    rows = connection.execute(
        """
        SELECT
            market_id,
            checkpoint,
            protocol_version,
            snapshot_id,
            eligible_for_review,
            rejection_reasons_json,
            evaluated_at
        FROM machine_eligibility
        WHERE protocol_version = ?
        ORDER BY
            evaluated_at,
            market_id,
            checkpoint
        """,
        (protocol_version,),
    ).fetchall()

    return tuple(
        StoredEligibilityDecision(
            market_id=row[0],
            checkpoint=Checkpoint(row[1]),
            protocol_version=row[2],
            snapshot_id=row[3],
            eligible_for_review=bool(row[4]),
            rejection_reasons=tuple(
                json.loads(row[5])
            ),
            evaluated_at=datetime.fromisoformat(
                row[6]
            ),
        )
        for row in rows
    )
