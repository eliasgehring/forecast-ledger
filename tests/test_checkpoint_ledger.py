import sqlite3
from datetime import UTC, datetime, timedelta

from forecast_ledger.checkpoint_ledger import (
    CheckpointStatus,
    checkpoint_exists,
    create_checkpoint_record,
    initialize_checkpoint_ledger,
    load_checkpoint_records,
)
from forecast_ledger.checkpoints import Checkpoint

SCHEDULED_AT = datetime(
    2026,
    8,
    7,
    16,
    0,
    tzinfo=UTC,
)

WINDOW_START = SCHEDULED_AT - timedelta(hours=6)
WINDOW_END = SCHEDULED_AT + timedelta(hours=6)

CREATED_AT = datetime(
    2026,
    8,
    7,
    11,
    0,
    tzinfo=UTC,
)


def test_create_checkpoint_record() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_checkpoint_ledger(connection)

    created = create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=SCHEDULED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=CheckpointStatus.PENDING,
        created_at=CREATED_AT,
    )

    records = load_checkpoint_records(connection)

    assert created is True
    assert len(records) == 1
    assert records[0].market_id == "market-1"
    assert records[0].checkpoint == Checkpoint.DAYS_7
    assert records[0].status == CheckpointStatus.PENDING


def test_same_market_checkpoint_is_idempotent() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_checkpoint_ledger(connection)

    first = create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=SCHEDULED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=CheckpointStatus.PENDING,
        created_at=CREATED_AT,
    )

    second = create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=SCHEDULED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=CheckpointStatus.PENDING,
        created_at=CREATED_AT,
    )

    assert first is True
    assert second is False
    assert len(load_checkpoint_records(connection)) == 1


def test_different_checkpoints_are_distinct() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_checkpoint_ledger(connection)

    create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_14,
        scheduled_at=SCHEDULED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=CheckpointStatus.PENDING,
        created_at=CREATED_AT,
    )

    create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=SCHEDULED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=CheckpointStatus.PENDING,
        created_at=CREATED_AT,
    )

    assert len(load_checkpoint_records(connection)) == 2


def test_checkpoint_exists() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_checkpoint_ledger(connection)

    create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=SCHEDULED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=CheckpointStatus.PENDING,
        created_at=CREATED_AT,
    )

    assert checkpoint_exists(
        connection,
        "market-1",
        Checkpoint.DAYS_7,
    )

    assert not checkpoint_exists(
        connection,
        "market-1",
        Checkpoint.DAYS_3,
    )


def test_unavailable_checkpoint_is_persisted() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_checkpoint_ledger(connection)

    create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_14,
        scheduled_at=SCHEDULED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=CheckpointStatus.CHECKPOINT_UNAVAILABLE,
        created_at=CREATED_AT,
    )

    record = load_checkpoint_records(connection)[0]

    assert (
        record.status
        == CheckpointStatus.CHECKPOINT_UNAVAILABLE
    )
