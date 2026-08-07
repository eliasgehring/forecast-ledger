import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import require_timezone_aware
from forecast_ledger.registry import PROTOCOL_VERSION


class RetrievalAttemptStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class RetrievalAttempt:
    market_id: str
    checkpoint: Checkpoint
    protocol_version: str
    attempt_number: int
    model: str
    prompt_version: str
    requested_at: datetime
    completed_at: datetime | None
    response_id: str | None
    status: RetrievalAttemptStatus
    error_type: str | None
    error_message: str | None
    raw_output: str | None


def initialize_retrieval_store(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS retrieval_attempts (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            completed_at TEXT,
            response_id TEXT,
            status TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            raw_output TEXT,
            PRIMARY KEY (
                market_id,
                checkpoint,
                protocol_version,
                attempt_number
            )
        )
        """
    )
    connection.commit()


def start_retrieval_attempt(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    attempt_number: int,
    model: str,
    prompt_version: str,
    requested_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> None:
    require_timezone_aware(
        requested_at,
        "requested_at",
    )

    if attempt_number not in {1, 2, 3}:
        raise ValueError(
            "Retrieval attempt number must be 1, 2, or 3."
        )

    connection.execute(
        """
        INSERT INTO retrieval_attempts (
            market_id,
            checkpoint,
            protocol_version,
            attempt_number,
            model,
            prompt_version,
            requested_at,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            attempt_number,
            model,
            prompt_version,
            requested_at.isoformat(),
            RetrievalAttemptStatus.STARTED.value,
        ),
    )
    connection.commit()


def finish_retrieval_attempt_success(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    attempt_number: int,
    completed_at: datetime,
    response_id: str,
    raw_output: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> None:
    require_timezone_aware(
        completed_at,
        "completed_at",
    )

    cursor = connection.execute(
        """
        UPDATE retrieval_attempts
        SET
            completed_at = ?,
            response_id = ?,
            status = ?,
            raw_output = ?
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND attempt_number = ?
          AND status = ?
        """,
        (
            completed_at.isoformat(),
            response_id,
            RetrievalAttemptStatus.SUCCEEDED.value,
            raw_output,
            market_id,
            checkpoint.value,
            protocol_version,
            attempt_number,
            RetrievalAttemptStatus.STARTED.value,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Expected exactly one started retrieval attempt."
        )

    connection.commit()


def finish_retrieval_attempt_failure(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    attempt_number: int,
    completed_at: datetime,
    error_type: str,
    error_message: str,
    response_id: str | None = None,
    raw_output: str | None = None,
    protocol_version: str = PROTOCOL_VERSION,
) -> None:
    require_timezone_aware(
        completed_at,
        "completed_at",
    )

    cursor = connection.execute(
        """
        UPDATE retrieval_attempts
        SET
            completed_at = ?,
            response_id = ?,
            status = ?,
            error_type = ?,
            error_message = ?,
            raw_output = ?
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND attempt_number = ?
          AND status = ?
        """,
        (
            completed_at.isoformat(),
            response_id,
            RetrievalAttemptStatus.FAILED.value,
            error_type,
            error_message,
            raw_output,
            market_id,
            checkpoint.value,
            protocol_version,
            attempt_number,
            RetrievalAttemptStatus.STARTED.value,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            "Expected exactly one started retrieval attempt."
        )

    connection.commit()


def load_retrieval_attempts(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    protocol_version: str = PROTOCOL_VERSION,
) -> tuple[RetrievalAttempt, ...]:
    rows = connection.execute(
        """
        SELECT
            market_id,
            checkpoint,
            protocol_version,
            attempt_number,
            model,
            prompt_version,
            requested_at,
            completed_at,
            response_id,
            status,
            error_type,
            error_message,
            raw_output
        FROM retrieval_attempts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        ORDER BY attempt_number
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchall()

    return tuple(
        RetrievalAttempt(
            market_id=row[0],
            checkpoint=Checkpoint(row[1]),
            protocol_version=row[2],
            attempt_number=row[3],
            model=row[4],
            prompt_version=row[5],
            requested_at=datetime.fromisoformat(row[6]),
            completed_at=(
                None
                if row[7] is None
                else datetime.fromisoformat(row[7])
            ),
            response_id=row[8],
            status=RetrievalAttemptStatus(row[9]),
            error_type=row[10],
            error_message=row[11],
            raw_output=row[12],
        )
        for row in rows
    )
