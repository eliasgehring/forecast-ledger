import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from forecast_ledger.checkpoint_ledger import (
    CheckpointStatus,
    create_checkpoint_record,
    initialize_checkpoint_ledger,
    load_checkpoint_records,
)
from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import MarketSnapshot
from forecast_ledger.snapshot_store import (
    SnapshotConflictError,
    initialize_snapshot_store,
    load_market_snapshots,
    record_market_snapshot,
)

OBSERVED_AT = datetime(
    2026,
    8,
    7,
    11,
    0,
    tzinfo=UTC,
)

SCHEDULED_AT = datetime(
    2026,
    8,
    7,
    16,
    0,
    tzinfo=UTC,
)


def make_snapshot(
    yes_bid: float = 0.40,
    yes_ask: float = 0.44,
) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id="snapshot-1",
        market_id="market-1",
        observed_at=OBSERVED_AT,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=None,
        no_ask=None,
    )


def setup_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    initialize_checkpoint_ledger(connection)
    initialize_snapshot_store(connection)

    create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=SCHEDULED_AT,
        window_start=SCHEDULED_AT - timedelta(hours=6),
        window_end=SCHEDULED_AT + timedelta(hours=6),
        status=CheckpointStatus.PENDING,
        created_at=OBSERVED_AT,
    )

    return connection


def test_snapshot_is_persisted_and_checkpoint_advances() -> None:
    connection = setup_connection()

    created = record_market_snapshot(
        connection=connection,
        snapshot=make_snapshot(),
        checkpoint=Checkpoint.DAYS_7,
        raw_yes_book={"bids": [], "asks": []},
        raw_no_book=None,
        no_book_error="NO diagnostic unavailable",
    )

    stored = load_market_snapshots(connection)
    checkpoint = load_checkpoint_records(connection)[0]

    assert created is True
    assert len(stored) == 1
    assert stored[0].snapshot.market_probability == pytest.approx(0.42)
    assert stored[0].raw_no_book is None
    assert checkpoint.status == CheckpointStatus.SNAPSHOT_RECORDED


def test_identical_snapshot_write_is_idempotent() -> None:
    connection = setup_connection()

    kwargs = {
        "connection": connection,
        "snapshot": make_snapshot(),
        "checkpoint": Checkpoint.DAYS_7,
        "raw_yes_book": {"bids": [], "asks": []},
        "raw_no_book": None,
        "no_book_error": None,
    }

    assert record_market_snapshot(**kwargs) is True
    assert record_market_snapshot(**kwargs) is False


def test_different_second_snapshot_is_rejected() -> None:
    connection = setup_connection()

    record_market_snapshot(
        connection=connection,
        snapshot=make_snapshot(),
        checkpoint=Checkpoint.DAYS_7,
        raw_yes_book={"book": "first"},
        raw_no_book=None,
        no_book_error=None,
    )

    with pytest.raises(
        SnapshotConflictError,
        match="different snapshot",
    ):
        record_market_snapshot(
            connection=connection,
            snapshot=MarketSnapshot(
                snapshot_id="snapshot-2",
                market_id="market-1",
                observed_at=OBSERVED_AT,
                yes_bid=0.41,
                yes_ask=0.45,
            ),
            checkpoint=Checkpoint.DAYS_7,
            raw_yes_book={"book": "second"},
            raw_no_book=None,
            no_book_error=None,
        )


def test_snapshot_requires_existing_checkpoint() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_checkpoint_ledger(connection)
    initialize_snapshot_store(connection)

    with pytest.raises(
        ValueError,
        match="Checkpoint must exist",
    ):
        record_market_snapshot(
            connection=connection,
            snapshot=make_snapshot(),
            checkpoint=Checkpoint.DAYS_7,
            raw_yes_book={},
            raw_no_book=None,
            no_book_error=None,
        )
