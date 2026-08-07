import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from forecast_ledger.checkpoint_ledger import (
    CheckpointStatus,
    create_checkpoint_record,
    initialize_checkpoint_ledger,
)
from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import (
    EvidenceItem,
    EvidencePacket,
    MarketSnapshot,
    TimestampQuality,
)
from forecast_ledger.evidence_store import (
    EvidenceConflictError,
    initialize_evidence_store,
    load_evidence_items_for_packet,
    record_evidence_packet,
)
from forecast_ledger.snapshot_store import (
    initialize_snapshot_store,
    record_market_snapshot,
)

CUTOFF = datetime(
    2026,
    8,
    7,
    11,
    0,
    tzinfo=UTC,
)

SCHEDULED = datetime(
    2026,
    8,
    7,
    16,
    0,
    tzinfo=UTC,
)


def setup_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    initialize_checkpoint_ledger(connection)
    initialize_snapshot_store(connection)
    initialize_evidence_store(connection)

    create_checkpoint_record(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=SCHEDULED,
        window_start=SCHEDULED - timedelta(hours=6),
        window_end=SCHEDULED + timedelta(hours=6),
        status=CheckpointStatus.PENDING,
        created_at=CUTOFF,
    )

    snapshot = MarketSnapshot(
        snapshot_id="snapshot-1",
        market_id="market-1",
        observed_at=CUTOFF,
        yes_bid=0.40,
        yes_ask=0.44,
    )

    record_market_snapshot(
        connection=connection,
        snapshot=snapshot,
        checkpoint=Checkpoint.DAYS_7,
        raw_yes_book={"book": "yes"},
        raw_no_book=None,
        no_book_error=None,
    )

    return connection


def make_item(
    evidence_id: str = "evidence-1",
    published_at: datetime | None = None,
    retrieved_at: datetime | None = None,
) -> EvidenceItem:
    if published_at is None:
        published_at = CUTOFF - timedelta(hours=2)

    if retrieved_at is None:
        retrieved_at = CUTOFF + timedelta(minutes=1)

    return EvidenceItem(
        evidence_id=evidence_id,
        source_url="https://example.com/article",
        source_name="Example",
        title="Example article",
        published_at=published_at,
        retrieved_at=retrieved_at,
        excerpt="Relevant evidence.",
        timestamp_quality=TimestampQuality.VERIFIED,
    )


def make_packet(
    evidence_ids: tuple[str, ...],
    packet_id: str = "packet-1",
    cutoff: datetime = CUTOFF,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=packet_id,
        market_id="market-1",
        snapshot_id="snapshot-1",
        information_cutoff=cutoff,
        evidence_ids=evidence_ids,
        retrieval_model="retrieval-model",
        retrieval_prompt_version="retrieval-v1",
        created_at=CUTOFF + timedelta(minutes=2),
    )


def test_evidence_packet_is_persisted_in_order() -> None:
    connection = setup_connection()

    first = make_item("evidence-1")
    second = make_item("evidence-2")

    packet = make_packet(
        ("evidence-1", "evidence-2")
    )

    created = record_evidence_packet(
        connection=connection,
        packet=packet,
        checkpoint=Checkpoint.DAYS_7,
        evidence_items=(first, second),
    )

    stored = load_evidence_items_for_packet(
        connection,
        "packet-1",
    )

    assert created is True
    assert tuple(item.evidence_id for item in stored) == (
        "evidence-1",
        "evidence-2",
    )


def test_zero_evidence_packet_is_valid() -> None:
    connection = setup_connection()

    packet = make_packet(())

    created = record_evidence_packet(
        connection=connection,
        packet=packet,
        checkpoint=Checkpoint.DAYS_7,
        evidence_items=(),
    )

    assert created is True
    assert load_evidence_items_for_packet(
        connection,
        "packet-1",
    ) == ()


def test_future_published_evidence_is_rejected() -> None:
    connection = setup_connection()

    item = make_item(
        published_at=CUTOFF + timedelta(seconds=1)
    )

    packet = make_packet(("evidence-1",))

    with pytest.raises(
        ValueError,
        match="published",
    ):
        record_evidence_packet(
            connection=connection,
            packet=packet,
            checkpoint=Checkpoint.DAYS_7,
            evidence_items=(item,),
        )


def test_retrieval_cannot_predate_cutoff() -> None:
    connection = setup_connection()

    item = make_item(
        retrieved_at=CUTOFF - timedelta(seconds=1)
    )

    packet = make_packet(("evidence-1",))

    with pytest.raises(
        ValueError,
        match="retrieved_at cannot precede",
    ):
        record_evidence_packet(
            connection=connection,
            packet=packet,
            checkpoint=Checkpoint.DAYS_7,
            evidence_items=(item,),
        )


def test_packet_cutoff_must_equal_snapshot() -> None:
    connection = setup_connection()

    packet = make_packet(
        (),
        cutoff=CUTOFF + timedelta(seconds=1),
    )

    with pytest.raises(
        ValueError,
        match="cutoff must equal snapshot",
    ):
        record_evidence_packet(
            connection=connection,
            packet=packet,
            checkpoint=Checkpoint.DAYS_7,
            evidence_items=(),
        )


def test_evidence_packet_is_immutable() -> None:
    connection = setup_connection()

    packet = make_packet(())

    assert record_evidence_packet(
        connection=connection,
        packet=packet,
        checkpoint=Checkpoint.DAYS_7,
        evidence_items=(),
    )

    different_packet = make_packet(
        (),
        packet_id="packet-2",
    )

    with pytest.raises(
        EvidenceConflictError,
        match="different evidence packet",
    ):
        record_evidence_packet(
            connection=connection,
            packet=different_packet,
            checkpoint=Checkpoint.DAYS_7,
            evidence_items=(),
        )
