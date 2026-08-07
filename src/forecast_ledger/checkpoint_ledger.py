import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import require_timezone_aware
from forecast_ledger.registry import PROTOCOL_VERSION


class CheckpointStatus(str, Enum):
    STARTED = "started"
    CHECKPOINT_UNAVAILABLE = "checkpoint_unavailable"


@dataclass(frozen=True)
class CheckpointRecord:
    market_id: str
    checkpoint: Checkpoint
    protocol_version: str
    scheduled_at: datetime
    window_start: datetime
    window_end: datetime
    status: CheckpointStatus
    created_at: datetime


def initialize_checkpoint_ledger(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoint_records (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (
                market_id,
                checkpoint,
                protocol_version
            )
        )
        """
    )
    connection.commit()


def create_checkpoint_record(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    scheduled_at: datetime,
    window_start: datetime,
    window_end: datetime,
    status: CheckpointStatus,
    created_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    require_timezone_aware(scheduled_at, "scheduled_at")
    require_timezone_aware(window_start, "window_start")
    require_timezone_aware(window_end, "window_end")
    require_timezone_aware(created_at, "created_at")

    if window_start > scheduled_at:
        raise ValueError(
            "window_start cannot be after scheduled_at."
        )

    if scheduled_at > window_end:
        raise ValueError(
            "scheduled_at cannot be after window_end."
        )

    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO checkpoint_records (
            market_id,
            checkpoint,
            protocol_version,
            scheduled_at,
            window_start,
            window_end,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            scheduled_at.isoformat(),
            window_start.isoformat(),
            window_end.isoformat(),
            status.value,
            created_at.isoformat(),
        ),
    )
    connection.commit()

    return cursor.rowcount == 1


def checkpoint_exists(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM checkpoint_records
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

    return row is not None


def load_checkpoint_records(
    connection: sqlite3.Connection,
) -> tuple[CheckpointRecord, ...]:
    rows = connection.execute(
        """
        SELECT
            market_id,
            checkpoint,
            protocol_version,
            scheduled_at,
            window_start,
            window_end,
            status,
            created_at
        FROM checkpoint_records
        ORDER BY market_id, scheduled_at
        """
    ).fetchall()

    return tuple(
        CheckpointRecord(
            market_id=row[0],
            checkpoint=Checkpoint(row[1]),
            protocol_version=row[2],
            scheduled_at=datetime.fromisoformat(row[3]),
            window_start=datetime.fromisoformat(row[4]),
            window_end=datetime.fromisoformat(row[5]),
            status=CheckpointStatus(row[6]),
            created_at=datetime.fromisoformat(row[7]),
        )
        for row in rows
    )
