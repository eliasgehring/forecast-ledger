from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from forecast_ledger.domain import require_timezone_aware
from forecast_ledger.registry import PROTOCOL_VERSION


class ResolutionStatus(str, Enum):
    PENDING = "pending"
    RESOLVED_YES = "resolved_yes"
    RESOLVED_NO = "resolved_no"
    INVALID = "invalid"
    CANCELLED = "cancelled"
    AMBIGUOUS = "ambiguous"


class ResolutionConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolutionRecord:
    market_id: str
    protocol_version: str
    outcome_yes: bool | None
    resolved_at: datetime
    resolution_source: str
    resolution_status: ResolutionStatus
    retrieved_at: datetime


def initialize_resolution_store(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_resolutions (
            market_id TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            outcome_yes INTEGER,
            resolved_at TEXT NOT NULL,
            resolution_source TEXT NOT NULL,
            resolution_status TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,

            PRIMARY KEY (
                market_id,
                protocol_version
            ),

            CHECK (
                outcome_yes IS NULL
                OR outcome_yes IN (0, 1)
            )
        )
        """
    )
    connection.commit()


def _validate_resolution_semantics(
    outcome_yes: bool | None,
    resolution_status: ResolutionStatus,
) -> None:
    if resolution_status == ResolutionStatus.PENDING:
        raise ValueError(
            "Pending resolution is represented by absence "
            "of a terminal resolution record."
        )

    if resolution_status == ResolutionStatus.RESOLVED_YES:
        if outcome_yes is not True:
            raise ValueError(
                "resolved_yes requires outcome_yes=True."
            )
        return

    if resolution_status == ResolutionStatus.RESOLVED_NO:
        if outcome_yes is not False:
            raise ValueError(
                "resolved_no requires outcome_yes=False."
            )
        return

    if outcome_yes is not None:
        raise ValueError(
            "Invalid, cancelled, and ambiguous resolutions "
            "must not contain a binary outcome."
        )


def record_resolution(
    connection: sqlite3.Connection,
    market_id: str,
    outcome_yes: bool | None,
    resolved_at: datetime,
    resolution_source: str,
    resolution_status: ResolutionStatus,
    retrieved_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    require_timezone_aware(
        resolved_at,
        "resolved_at",
    )
    require_timezone_aware(
        retrieved_at,
        "retrieved_at",
    )

    if not market_id.strip():
        raise ValueError(
            "market_id cannot be empty."
        )

    if not resolution_source.strip():
        raise ValueError(
            "resolution_source cannot be empty."
        )

    if retrieved_at < resolved_at:
        raise ValueError(
            "retrieved_at cannot be before resolved_at."
        )

    _validate_resolution_semantics(
        outcome_yes=outcome_yes,
        resolution_status=resolution_status,
    )

    market_exists = connection.execute(
        """
        SELECT 1
        FROM tracked_markets
        WHERE market_id = ?
          AND protocol_version = ?
        """,
        (
            market_id,
            protocol_version,
        ),
    ).fetchone()

    if market_exists is None:
        raise ValueError(
            "Cannot record a resolution for an "
            "untracked market."
        )

    incoming = (
        None
        if outcome_yes is None
        else int(outcome_yes),
        resolved_at.isoformat(),
        resolution_source.strip(),
        resolution_status.value,
        retrieved_at.isoformat(),
    )

    existing = connection.execute(
        """
        SELECT
            outcome_yes,
            resolved_at,
            resolution_source,
            resolution_status,
            retrieved_at
        FROM market_resolutions
        WHERE market_id = ?
          AND protocol_version = ?
        """,
        (
            market_id,
            protocol_version,
        ),
    ).fetchone()

    if existing is not None:
        if existing == incoming:
            return False

        raise ResolutionConflictError(
            "Terminal market resolution is immutable."
        )

    connection.execute(
        """
        INSERT INTO market_resolutions (
            market_id,
            protocol_version,
            outcome_yes,
            resolved_at,
            resolution_source,
            resolution_status,
            retrieved_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_id,
            protocol_version,
            *incoming,
        ),
    )

    connection.commit()

    return True


def load_resolution(
    connection: sqlite3.Connection,
    market_id: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> ResolutionRecord | None:
    row = connection.execute(
        """
        SELECT
            market_id,
            protocol_version,
            outcome_yes,
            resolved_at,
            resolution_source,
            resolution_status,
            retrieved_at
        FROM market_resolutions
        WHERE market_id = ?
          AND protocol_version = ?
        """,
        (
            market_id,
            protocol_version,
        ),
    ).fetchone()

    if row is None:
        return None

    return ResolutionRecord(
        market_id=row[0],
        protocol_version=row[1],
        outcome_yes=(
            None
            if row[2] is None
            else bool(row[2])
        ),
        resolved_at=datetime.fromisoformat(
            row[3]
        ),
        resolution_source=row[4],
        resolution_status=ResolutionStatus(
            row[5]
        ),
        retrieved_at=datetime.fromisoformat(
            row[6]
        ),
    )


def load_resolutions(
    connection: sqlite3.Connection,
    protocol_version: str = PROTOCOL_VERSION,
) -> tuple[ResolutionRecord, ...]:
    rows = connection.execute(
        """
        SELECT
            market_id
        FROM market_resolutions
        WHERE protocol_version = ?
        ORDER BY market_id
        """,
        (protocol_version,),
    ).fetchall()

    return tuple(
        resolution
        for row in rows
        if (
            resolution := load_resolution(
                connection=connection,
                market_id=row[0],
                protocol_version=protocol_version,
            )
        )
        is not None
    )
