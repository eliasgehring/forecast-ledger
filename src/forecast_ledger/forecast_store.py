from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.forecasting import (
    FORECAST_MODEL,
    FORECAST_REASONING_EFFORT,
    ForecastAnalysis,
    ForecastCondition,
    analysis_to_json,
    prompt_version_for_condition,
)
from forecast_ledger.registry import PROTOCOL_VERSION


class ForecastConflictError(RuntimeError):
    pass


class ForecastAttemptStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


RETRYABLE_ERROR_TYPES = {
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "ForecastOutputError",
}


@dataclass(frozen=True)
class ForecastAttempt:
    market_id: str
    checkpoint: Checkpoint
    protocol_version: str
    condition: ForecastCondition
    attempt_number: int
    packet_id: str
    snapshot_id: str
    model: str
    reasoning_effort: str
    prompt_version: str
    prompt_sha256: str
    requested_at: datetime
    completed_at: datetime | None
    response_id: str | None
    status: ForecastAttemptStatus
    error_type: str | None
    error_message: str | None
    raw_output: str | None
    protocol_commit: str
    code_commit: str


@dataclass(frozen=True)
class StoredForecast:
    forecast_id: str
    market_id: str
    checkpoint: Checkpoint
    protocol_version: str
    condition: ForecastCondition
    packet_id: str
    snapshot_id: str
    model: str
    reasoning_effort: str
    prompt_version: str
    prompt_sha256: str
    attempt_number: int
    response_id: str
    probability_yes: float
    parsed_output_json: str
    forecast_created_at: datetime
    protocol_commit: str
    code_commit: str


def initialize_forecast_store(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_attempts (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            condition TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            packet_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            model TEXT NOT NULL,
            reasoning_effort TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            prompt_sha256 TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            completed_at TEXT,
            response_id TEXT,
            status TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            raw_output TEXT,
            protocol_commit TEXT NOT NULL,
            code_commit TEXT NOT NULL,
            PRIMARY KEY (
                market_id,
                checkpoint,
                protocol_version,
                condition,
                attempt_number
            )
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecasts (
            forecast_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            condition TEXT NOT NULL,
            packet_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            model TEXT NOT NULL,
            reasoning_effort TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            prompt_sha256 TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            response_id TEXT NOT NULL,
            probability_yes REAL NOT NULL,
            parsed_output_json TEXT NOT NULL,
            forecast_created_at TEXT NOT NULL,
            protocol_commit TEXT NOT NULL,
            code_commit TEXT NOT NULL,
            UNIQUE (
                market_id,
                checkpoint,
                protocol_version,
                condition,
                model
            )
        )
        """
    )

    connection.commit()


def _validate_probability(
    probability_yes: float,
) -> None:
    if not 0.0 <= probability_yes <= 1.0:
        raise ValueError(
            "probability_yes must be between 0 and 1."
        )


def _validate_valid_packet(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    packet_id: str,
    snapshot_id: str,
    protocol_version: str,
) -> None:
    row = connection.execute(
        """
        SELECT
            p.market_id,
            p.checkpoint,
            p.protocol_version,
            p.snapshot_id,
            v.status
        FROM evidence_packets AS p
        JOIN evidence_packet_validations AS v
          ON v.packet_id = p.packet_id
        WHERE p.packet_id = ?
        """,
        (packet_id,),
    ).fetchone()

    expected = (
        market_id,
        checkpoint.value,
        protocol_version,
        snapshot_id,
        "valid",
    )

    if row != expected:
        raise ValueError(
            "Forecast requires the matching VALID frozen evidence packet."
        )


def _validate_attempt_configuration(
    condition: ForecastCondition,
    model: str,
    reasoning_effort: str,
    prompt_version: str,
) -> None:
    if model != FORECAST_MODEL:
        raise ValueError(
            "Forecast attempt uses the wrong model snapshot."
        )

    if reasoning_effort != FORECAST_REASONING_EFFORT:
        raise ValueError(
            "Forecast attempt uses the wrong reasoning effort."
        )

    expected_prompt_version = prompt_version_for_condition(
        condition
    )

    if prompt_version != expected_prompt_version:
        raise ValueError(
            "Forecast attempt uses the wrong prompt version."
        )


def _load_previous_attempts(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    condition: ForecastCondition,
    protocol_version: str,
) -> tuple[tuple, ...]:
    return tuple(
        connection.execute(
            """
            SELECT
                attempt_number,
                status,
                error_type
            FROM forecast_attempts
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
              AND condition = ?
            ORDER BY attempt_number
            """,
            (
                market_id,
                checkpoint.value,
                protocol_version,
                condition.value,
            ),
        ).fetchall()
    )


def start_forecast_attempt(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    condition: ForecastCondition,
    attempt_number: int,
    packet_id: str,
    snapshot_id: str,
    model: str,
    reasoning_effort: str,
    prompt_version: str,
    prompt_sha256: str,
    requested_at: datetime,
    protocol_commit: str,
    code_commit: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> None:
    if attempt_number not in {1, 2, 3}:
        raise ValueError(
            "Forecast attempt number must be 1, 2, or 3."
        )

    _validate_attempt_configuration(
        condition=condition,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_version=prompt_version,
    )

    _validate_valid_packet(
        connection=connection,
        market_id=market_id,
        checkpoint=checkpoint,
        packet_id=packet_id,
        snapshot_id=snapshot_id,
        protocol_version=protocol_version,
    )

    existing_forecast = connection.execute(
        """
        SELECT forecast_id
        FROM forecasts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND condition = ?
          AND model = ?
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
            model,
        ),
    ).fetchone()

    if existing_forecast is not None:
        raise ForecastConflictError(
            "A scored forecast already exists for this condition."
        )

    previous_attempts = _load_previous_attempts(
        connection=connection,
        market_id=market_id,
        checkpoint=checkpoint,
        condition=condition,
        protocol_version=protocol_version,
    )

    if attempt_number == 1:
        if previous_attempts:
            raise ForecastConflictError(
                "Attempt 1 already exists."
            )
    else:
        if len(previous_attempts) != attempt_number - 1:
            raise ValueError(
                "Forecast retries must be sequential."
            )

        previous_number, previous_status, previous_error_type = (
            previous_attempts[-1]
        )

        if previous_number != attempt_number - 1:
            raise ValueError(
                "Forecast retry sequence is inconsistent."
            )

        if previous_status != ForecastAttemptStatus.FAILED.value:
            raise ValueError(
                "A retry requires the previous attempt to have failed."
            )

        if previous_error_type not in RETRYABLE_ERROR_TYPES:
            raise ValueError(
                "Previous failure is not retryable under the protocol."
            )

    connection.execute(
        """
        INSERT INTO forecast_attempts (
            market_id,
            checkpoint,
            protocol_version,
            condition,
            attempt_number,
            packet_id,
            snapshot_id,
            model,
            reasoning_effort,
            prompt_version,
            prompt_sha256,
            requested_at,
            completed_at,
            response_id,
            status,
            error_type,
            error_message,
            raw_output,
            protocol_commit,
            code_commit
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, ?, ?)
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
            attempt_number,
            packet_id,
            snapshot_id,
            model,
            reasoning_effort,
            prompt_version,
            prompt_sha256,
            requested_at.isoformat(),
            ForecastAttemptStatus.STARTED.value,
            protocol_commit,
            code_commit,
        ),
    )

    connection.commit()


def _finish_attempt(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    condition: ForecastCondition,
    attempt_number: int,
    completed_at: datetime,
    status: ForecastAttemptStatus,
    response_id: str | None,
    raw_output: str | None,
    error_type: str | None,
    error_message: str | None,
    protocol_version: str,
) -> None:
    row = connection.execute(
        """
        SELECT status
        FROM forecast_attempts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND condition = ?
          AND attempt_number = ?
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
            attempt_number,
        ),
    ).fetchone()

    if row is None:
        raise ValueError(
            "Forecast attempt does not exist."
        )

    if row[0] != ForecastAttemptStatus.STARTED.value:
        raise ForecastConflictError(
            "Forecast attempt is already finalized."
        )

    connection.execute(
        """
        UPDATE forecast_attempts
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
          AND condition = ?
          AND attempt_number = ?
        """,
        (
            completed_at.isoformat(),
            response_id,
            status.value,
            error_type,
            error_message,
            raw_output,
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
            attempt_number,
        ),
    )

    connection.commit()


def finish_forecast_attempt_success(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    condition: ForecastCondition,
    attempt_number: int,
    completed_at: datetime,
    response_id: str,
    raw_output: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> None:
    _finish_attempt(
        connection=connection,
        market_id=market_id,
        checkpoint=checkpoint,
        condition=condition,
        attempt_number=attempt_number,
        completed_at=completed_at,
        status=ForecastAttemptStatus.SUCCEEDED,
        response_id=response_id,
        raw_output=raw_output,
        error_type=None,
        error_message=None,
        protocol_version=protocol_version,
    )


def finish_forecast_attempt_failure(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    condition: ForecastCondition,
    attempt_number: int,
    completed_at: datetime,
    error_type: str,
    error_message: str,
    response_id: str | None = None,
    raw_output: str | None = None,
    protocol_version: str = PROTOCOL_VERSION,
) -> None:
    _finish_attempt(
        connection=connection,
        market_id=market_id,
        checkpoint=checkpoint,
        condition=condition,
        attempt_number=attempt_number,
        completed_at=completed_at,
        status=ForecastAttemptStatus.FAILED,
        response_id=response_id,
        raw_output=raw_output,
        error_type=error_type,
        error_message=error_message,
        protocol_version=protocol_version,
    )


def record_forecast(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    condition: ForecastCondition,
    packet_id: str,
    snapshot_id: str,
    model: str,
    reasoning_effort: str,
    prompt_version: str,
    prompt_sha256: str,
    attempt_number: int,
    response_id: str,
    analysis: ForecastAnalysis,
    forecast_created_at: datetime,
    protocol_commit: str,
    code_commit: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> str:
    _validate_attempt_configuration(
        condition=condition,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_version=prompt_version,
    )

    _validate_valid_packet(
        connection=connection,
        market_id=market_id,
        checkpoint=checkpoint,
        packet_id=packet_id,
        snapshot_id=snapshot_id,
        protocol_version=protocol_version,
    )

    if analysis.condition != condition:
        raise ValueError(
            "Parsed forecast condition does not match stored condition."
        )

    _validate_probability(
        analysis.probability_yes
    )

    attempt = connection.execute(
        """
        SELECT
            packet_id,
            snapshot_id,
            model,
            reasoning_effort,
            prompt_version,
            prompt_sha256,
            response_id,
            status,
            protocol_commit,
            code_commit
        FROM forecast_attempts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND condition = ?
          AND attempt_number = ?
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
            attempt_number,
        ),
    ).fetchone()

    expected_attempt = (
        packet_id,
        snapshot_id,
        model,
        reasoning_effort,
        prompt_version,
        prompt_sha256,
        response_id,
        ForecastAttemptStatus.SUCCEEDED.value,
        protocol_commit,
        code_commit,
    )

    if attempt != expected_attempt:
        raise ValueError(
            "Forecast record does not match its successful attempt."
        )

    parsed_output_json = analysis_to_json(
        analysis
    )

    forecast_material = (
        f"{protocol_version}|"
        f"{market_id}|"
        f"{checkpoint.value}|"
        f"{condition.value}|"
        f"{model}|"
        f"{response_id}"
    )

    forecast_id = hashlib.sha256(
        forecast_material.encode("utf-8")
    ).hexdigest()

    existing = connection.execute(
        """
        SELECT
            forecast_id,
            packet_id,
            snapshot_id,
            prompt_sha256,
            attempt_number,
            response_id,
            probability_yes,
            parsed_output_json,
            protocol_commit,
            code_commit
        FROM forecasts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND condition = ?
          AND model = ?
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
            model,
        ),
    ).fetchone()

    incoming = (
        forecast_id,
        packet_id,
        snapshot_id,
        prompt_sha256,
        attempt_number,
        response_id,
        analysis.probability_yes,
        parsed_output_json,
        protocol_commit,
        code_commit,
    )

    if existing is not None:
        if existing != incoming:
            raise ForecastConflictError(
                "A different scored forecast already exists."
            )

        return forecast_id

    connection.execute(
        """
        INSERT INTO forecasts (
            forecast_id,
            market_id,
            checkpoint,
            protocol_version,
            condition,
            packet_id,
            snapshot_id,
            model,
            reasoning_effort,
            prompt_version,
            prompt_sha256,
            attempt_number,
            response_id,
            probability_yes,
            parsed_output_json,
            forecast_created_at,
            protocol_commit,
            code_commit
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            forecast_id,
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
            packet_id,
            snapshot_id,
            model,
            reasoning_effort,
            prompt_version,
            prompt_sha256,
            attempt_number,
            response_id,
            analysis.probability_yes,
            parsed_output_json,
            forecast_created_at.isoformat(),
            protocol_commit,
            code_commit,
        ),
    )

    connection.commit()

    return forecast_id


def load_forecast_attempts(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    condition: ForecastCondition,
    protocol_version: str = PROTOCOL_VERSION,
) -> tuple[ForecastAttempt, ...]:
    rows = connection.execute(
        """
        SELECT
            market_id,
            checkpoint,
            protocol_version,
            condition,
            attempt_number,
            packet_id,
            snapshot_id,
            model,
            reasoning_effort,
            prompt_version,
            prompt_sha256,
            requested_at,
            completed_at,
            response_id,
            status,
            error_type,
            error_message,
            raw_output,
            protocol_commit,
            code_commit
        FROM forecast_attempts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND condition = ?
        ORDER BY attempt_number
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            condition.value,
        ),
    ).fetchall()

    return tuple(
        ForecastAttempt(
            market_id=row[0],
            checkpoint=Checkpoint(row[1]),
            protocol_version=row[2],
            condition=ForecastCondition(row[3]),
            attempt_number=row[4],
            packet_id=row[5],
            snapshot_id=row[6],
            model=row[7],
            reasoning_effort=row[8],
            prompt_version=row[9],
            prompt_sha256=row[10],
            requested_at=datetime.fromisoformat(row[11]),
            completed_at=(
                None
                if row[12] is None
                else datetime.fromisoformat(row[12])
            ),
            response_id=row[13],
            status=ForecastAttemptStatus(row[14]),
            error_type=row[15],
            error_message=row[16],
            raw_output=row[17],
            protocol_commit=row[18],
            code_commit=row[19],
        )
        for row in rows
    )
