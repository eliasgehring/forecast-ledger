import sqlite3
from datetime import UTC, datetime

import pytest

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.forecast_store import (
    ForecastConflictError,
    finish_forecast_attempt_failure,
    finish_forecast_attempt_success,
    initialize_forecast_store,
    record_forecast,
    start_forecast_attempt,
)
from forecast_ledger.forecasting import (
    FORECAST_MODEL,
    FORECAST_REASONING_EFFORT,
    ForecastAnalysis,
    ForecastCondition,
    prompt_version_for_condition,
)

MARKET_ID = "m1"
CHECKPOINT = Checkpoint.DAYS_14
PACKET_ID = "packet1"
SNAPSHOT_ID = "snapshot1"
PROTOCOL_COMMIT = "protocolcommit"
CODE_COMMIT = "codecommit"
PROMPT_HASH = "a" * 64


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    connection.execute(
        """
        CREATE TABLE evidence_packets (
            packet_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            snapshot_id TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE evidence_packet_validations (
            packet_id TEXT PRIMARY KEY,
            status TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        INSERT INTO evidence_packets (
            packet_id,
            market_id,
            checkpoint,
            protocol_version,
            snapshot_id
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            PACKET_ID,
            MARKET_ID,
            CHECKPOINT.value,
            "v0.2",
            SNAPSHOT_ID,
        ),
    )

    connection.execute(
        """
        INSERT INTO evidence_packet_validations (
            packet_id,
            status
        )
        VALUES (?, 'valid')
        """,
        (PACKET_ID,),
    )

    initialize_forecast_store(connection)

    return connection


def start_attempt(
    connection: sqlite3.Connection,
    condition: ForecastCondition,
    attempt_number: int = 1,
) -> None:
    start_forecast_attempt(
        connection=connection,
        market_id=MARKET_ID,
        checkpoint=CHECKPOINT,
        condition=condition,
        attempt_number=attempt_number,
        packet_id=PACKET_ID,
        snapshot_id=SNAPSHOT_ID,
        model=FORECAST_MODEL,
        reasoning_effort=FORECAST_REASONING_EFFORT,
        prompt_version=prompt_version_for_condition(
            condition
        ),
        prompt_sha256=PROMPT_HASH,
        requested_at=datetime.now(UTC),
        protocol_commit=PROTOCOL_COMMIT,
        code_commit=CODE_COMMIT,
    )


def test_invalid_packet_cannot_start_forecast() -> None:
    connection = make_connection()

    connection.execute(
        """
        UPDATE evidence_packet_validations
        SET status = 'invalid'
        """
    )

    with pytest.raises(ValueError):
        start_attempt(
            connection,
            ForecastCondition.DIRECT,
        )


def test_non_retryable_failure_blocks_retry() -> None:
    connection = make_connection()
    condition = ForecastCondition.DIRECT

    start_attempt(connection, condition)

    finish_forecast_attempt_failure(
        connection=connection,
        market_id=MARKET_ID,
        checkpoint=CHECKPOINT,
        condition=condition,
        attempt_number=1,
        completed_at=datetime.now(UTC),
        error_type="AuthenticationError",
        error_message="401",
    )

    with pytest.raises(ValueError):
        start_attempt(
            connection,
            condition,
            attempt_number=2,
        )


def test_retryable_schema_failure_allows_retry() -> None:
    connection = make_connection()
    condition = ForecastCondition.DIRECT

    start_attempt(connection, condition)

    finish_forecast_attempt_failure(
        connection=connection,
        market_id=MARKET_ID,
        checkpoint=CHECKPOINT,
        condition=condition,
        attempt_number=1,
        completed_at=datetime.now(UTC),
        error_type="ForecastOutputError",
        error_message="Bad JSON",
    )

    start_attempt(
        connection,
        condition,
        attempt_number=2,
    )


def test_successful_forecast_is_immutable() -> None:
    connection = make_connection()
    condition = ForecastCondition.DIRECT

    start_attempt(connection, condition)

    finish_forecast_attempt_success(
        connection=connection,
        market_id=MARKET_ID,
        checkpoint=CHECKPOINT,
        condition=condition,
        attempt_number=1,
        completed_at=datetime.now(UTC),
        response_id="resp1",
        raw_output='{"probability_yes":0.4}',
    )

    analysis = ForecastAnalysis(
        condition=condition,
        probability_yes=0.4,
    )

    forecast_id = record_forecast(
        connection=connection,
        market_id=MARKET_ID,
        checkpoint=CHECKPOINT,
        condition=condition,
        packet_id=PACKET_ID,
        snapshot_id=SNAPSHOT_ID,
        model=FORECAST_MODEL,
        reasoning_effort=FORECAST_REASONING_EFFORT,
        prompt_version=prompt_version_for_condition(
            condition
        ),
        prompt_sha256=PROMPT_HASH,
        attempt_number=1,
        response_id="resp1",
        analysis=analysis,
        forecast_created_at=datetime.now(UTC),
        protocol_commit=PROTOCOL_COMMIT,
        code_commit=CODE_COMMIT,
    )

    same_id = record_forecast(
        connection=connection,
        market_id=MARKET_ID,
        checkpoint=CHECKPOINT,
        condition=condition,
        packet_id=PACKET_ID,
        snapshot_id=SNAPSHOT_ID,
        model=FORECAST_MODEL,
        reasoning_effort=FORECAST_REASONING_EFFORT,
        prompt_version=prompt_version_for_condition(
            condition
        ),
        prompt_sha256=PROMPT_HASH,
        attempt_number=1,
        response_id="resp1",
        analysis=analysis,
        forecast_created_at=datetime.now(UTC),
        protocol_commit=PROTOCOL_COMMIT,
        code_commit=CODE_COMMIT,
    )

    assert same_id == forecast_id

    with pytest.raises(ForecastConflictError):
        start_attempt(
            connection,
            condition,
            attempt_number=1,
        )
