import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from forecast_ledger.resolution_store import (
    ResolutionConflictError,
    ResolutionStatus,
    initialize_resolution_store,
    load_resolution,
    record_resolution,
)

RESOLVED_AT = datetime(
    2026,
    8,
    14,
    20,
    tzinfo=UTC,
)

RETRIEVED_AT = (
    RESOLVED_AT
    + timedelta(minutes=5)
)


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    connection.execute(
        """
        CREATE TABLE tracked_markets (
            market_id TEXT NOT NULL,
            protocol_version TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        INSERT INTO tracked_markets
        VALUES ('m1', 'v0.2')
        """
    )

    initialize_resolution_store(
        connection
    )

    return connection


def test_records_resolved_yes() -> None:
    connection = make_connection()

    created = record_resolution(
        connection=connection,
        market_id="m1",
        outcome_yes=True,
        resolved_at=RESOLVED_AT,
        resolution_source=(
            "https://example.com/resolution"
        ),
        resolution_status=(
            ResolutionStatus.RESOLVED_YES
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert created is True

    resolution = load_resolution(
        connection,
        "m1",
    )

    assert resolution is not None
    assert resolution.outcome_yes is True
    assert (
        resolution.resolution_status
        == ResolutionStatus.RESOLVED_YES
    )


def test_resolved_no_requires_false_outcome() -> None:
    connection = make_connection()

    with pytest.raises(
        ValueError,
        match="outcome_yes=False",
    ):
        record_resolution(
            connection=connection,
            market_id="m1",
            outcome_yes=True,
            resolved_at=RESOLVED_AT,
            resolution_source="source",
            resolution_status=(
                ResolutionStatus.RESOLVED_NO
            ),
            retrieved_at=RETRIEVED_AT,
        )


def test_invalid_resolution_has_no_binary_outcome() -> None:
    connection = make_connection()

    record_resolution(
        connection=connection,
        market_id="m1",
        outcome_yes=None,
        resolved_at=RESOLVED_AT,
        resolution_source="source",
        resolution_status=(
            ResolutionStatus.INVALID
        ),
        retrieved_at=RETRIEVED_AT,
    )

    resolution = load_resolution(
        connection,
        "m1",
    )

    assert resolution is not None
    assert resolution.outcome_yes is None


def test_pending_is_represented_by_absence() -> None:
    connection = make_connection()

    with pytest.raises(
        ValueError,
        match="absence",
    ):
        record_resolution(
            connection=connection,
            market_id="m1",
            outcome_yes=None,
            resolved_at=RESOLVED_AT,
            resolution_source="source",
            resolution_status=(
                ResolutionStatus.PENDING
            ),
            retrieved_at=RETRIEVED_AT,
        )


def test_terminal_resolution_is_immutable() -> None:
    connection = make_connection()

    kwargs = dict(
        connection=connection,
        market_id="m1",
        outcome_yes=True,
        resolved_at=RESOLVED_AT,
        resolution_source="source",
        resolution_status=(
            ResolutionStatus.RESOLVED_YES
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert record_resolution(**kwargs) is True
    assert record_resolution(**kwargs) is False

    with pytest.raises(
        ResolutionConflictError
    ):
        record_resolution(
            connection=connection,
            market_id="m1",
            outcome_yes=False,
            resolved_at=RESOLVED_AT,
            resolution_source="source",
            resolution_status=(
                ResolutionStatus.RESOLVED_NO
            ),
            retrieved_at=RETRIEVED_AT,
        )


def test_untracked_market_cannot_be_resolved() -> None:
    connection = make_connection()

    with pytest.raises(
        ValueError,
        match="untracked",
    ):
        record_resolution(
            connection=connection,
            market_id="unknown",
            outcome_yes=True,
            resolved_at=RESOLVED_AT,
            resolution_source="source",
            resolution_status=(
                ResolutionStatus.RESOLVED_YES
            ),
            retrieved_at=RETRIEVED_AT,
        )


def test_retrieval_cannot_predate_resolution() -> None:
    connection = make_connection()

    with pytest.raises(
        ValueError,
        match="before resolved_at",
    ):
        record_resolution(
            connection=connection,
            market_id="m1",
            outcome_yes=True,
            resolved_at=RESOLVED_AT,
            resolution_source="source",
            resolution_status=(
                ResolutionStatus.RESOLVED_YES
            ),
            retrieved_at=(
                RESOLVED_AT
                - timedelta(seconds=1)
            ),
        )
