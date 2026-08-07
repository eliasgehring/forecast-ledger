import sqlite3
from datetime import UTC, datetime

import pytest

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.retrieval_store import (
    RetrievalAttemptStatus,
    finish_retrieval_attempt_failure,
    finish_retrieval_attempt_success,
    initialize_retrieval_store,
    load_retrieval_attempts,
    start_retrieval_attempt,
)

REQUESTED_AT = datetime(
    2026,
    8,
    7,
    11,
    20,
    tzinfo=UTC,
)

COMPLETED_AT = datetime(
    2026,
    8,
    7,
    11,
    21,
    tzinfo=UTC,
)


def test_successful_retrieval_attempt_is_auditable() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_retrieval_store(connection)

    start_retrieval_attempt(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        attempt_number=1,
        model="retrieval-model",
        prompt_version="retrieval-v1",
        requested_at=REQUESTED_AT,
    )

    finish_retrieval_attempt_success(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        attempt_number=1,
        completed_at=COMPLETED_AT,
        response_id="resp-1",
        raw_output='{"evidence":[]}',
    )

    attempt = load_retrieval_attempts(
        connection,
        "market-1",
        Checkpoint.DAYS_7,
    )[0]

    assert attempt.status == RetrievalAttemptStatus.SUCCEEDED
    assert attempt.response_id == "resp-1"
    assert attempt.raw_output == '{"evidence":[]}'


def test_failed_retrieval_attempt_is_preserved() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_retrieval_store(connection)

    start_retrieval_attempt(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        attempt_number=1,
        model="retrieval-model",
        prompt_version="retrieval-v1",
        requested_at=REQUESTED_AT,
    )

    finish_retrieval_attempt_failure(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        attempt_number=1,
        completed_at=COMPLETED_AT,
        error_type="TimeoutError",
        error_message="Timed out.",
    )

    attempt = load_retrieval_attempts(
        connection,
        "market-1",
        Checkpoint.DAYS_7,
    )[0]

    assert attempt.status == RetrievalAttemptStatus.FAILED
    assert attempt.error_type == "TimeoutError"


def test_attempt_number_is_limited_to_protocol_maximum() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_retrieval_store(connection)

    with pytest.raises(
        ValueError,
        match="1, 2, or 3",
    ):
        start_retrieval_attempt(
            connection=connection,
            market_id="market-1",
            checkpoint=Checkpoint.DAYS_7,
            attempt_number=4,
            model="retrieval-model",
            prompt_version="retrieval-v1",
            requested_at=REQUESTED_AT,
        )


def test_same_attempt_number_cannot_be_created_twice() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_retrieval_store(connection)

    kwargs = {
        "connection": connection,
        "market_id": "market-1",
        "checkpoint": Checkpoint.DAYS_7,
        "attempt_number": 1,
        "model": "retrieval-model",
        "prompt_version": "retrieval-v1",
        "requested_at": REQUESTED_AT,
    }

    start_retrieval_attempt(**kwargs)

    with pytest.raises(sqlite3.IntegrityError):
        start_retrieval_attempt(**kwargs)
