import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import require_timezone_aware
from forecast_ledger.registry import PROTOCOL_VERSION


class SemanticDecision(str, Enum):
    INCLUDED = "included"
    EXCLUDED_DUPLICATE = "excluded_duplicate"
    EXCLUDED_AMBIGUOUS = "excluded_ambiguous"
    EXCLUDED_EFFECTIVELY_RESOLVED = "excluded_effectively_resolved"
    EXCLUDED_CATEGORY = "excluded_category"


@dataclass(frozen=True)
class SemanticReview:
    market_id: str
    checkpoint: Checkpoint
    protocol_version: str
    decision: SemanticDecision
    reason: str
    reviewed_at: datetime


def initialize_semantic_reviews(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_reviews (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            PRIMARY KEY (
                market_id,
                checkpoint,
                protocol_version
            )
        )
        """
    )
    connection.commit()


def record_semantic_review(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    decision: SemanticDecision,
    reason: str,
    reviewed_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    require_timezone_aware(reviewed_at, "reviewed_at")

    existing = connection.execute(
        """
        SELECT decision, reason
        FROM semantic_reviews
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    incoming = (
        decision.value,
        reason,
    )

    if existing is not None:
        if existing == incoming:
            return False

        raise RuntimeError(
            "Semantic review already exists with a different decision."
        )

    connection.execute(
        """
        INSERT INTO semantic_reviews (
            market_id,
            checkpoint,
            protocol_version,
            decision,
            reason,
            reviewed_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            decision.value,
            reason,
            reviewed_at.isoformat(),
        ),
    )
    connection.commit()

    return True


def load_semantic_reviews(
    connection: sqlite3.Connection,
) -> tuple[SemanticReview, ...]:
    rows = connection.execute(
        """
        SELECT
            market_id,
            checkpoint,
            protocol_version,
            decision,
            reason,
            reviewed_at
        FROM semantic_reviews
        ORDER BY market_id, checkpoint
        """
    ).fetchall()

    return tuple(
        SemanticReview(
            market_id=row[0],
            checkpoint=Checkpoint(row[1]),
            protocol_version=row[2],
            decision=SemanticDecision(row[3]),
            reason=row[4],
            reviewed_at=datetime.fromisoformat(row[5]),
        )
        for row in rows
    )
