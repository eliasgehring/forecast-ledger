from datetime import UTC, datetime

import pytest

from forecast_ledger.domain import (
    EvidenceItem,
    EvidencePacket,
    Market,
    MarketSnapshot,
    TimestampQuality,
)
from forecast_ledger.validation import (
    validate_evidence_for_cutoff,
    validate_evidence_packet,
)

CUTOFF = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)


def make_market() -> Market:
    return Market(
        market_id="market-1",
        question="Will example event happen?",
        resolution_rules="Resolves YES if the event happens before the deadline.",
        close_time=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        yes_token_id="yes-1",
        no_token_id="no-1",
    )


def make_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id="snapshot-1",
        market_id="market-1",
        observed_at=CUTOFF,
        yes_bid=0.60,
        yes_ask=0.64,
        no_bid=0.35,
        no_ask=0.39,
    )


def make_evidence(
    evidence_id: str = "evidence-1",
    published_at: datetime = datetime(2026, 8, 7, 7, 30, tzinfo=UTC),
    timestamp_quality: TimestampQuality = TimestampQuality.VERIFIED,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_url="https://example.com/article",
        source_name="Example News",
        title="Example event develops",
        published_at=published_at,
        retrieved_at=datetime(2026, 8, 7, 8, 5, tzinfo=UTC),
        excerpt="Relevant evidence about the event.",
        timestamp_quality=timestamp_quality,
    )


def make_packet(
    evidence_ids: tuple[str, ...] = ("evidence-1",),
    information_cutoff: datetime = CUTOFF,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id="packet-1",
        market_id="market-1",
        snapshot_id="snapshot-1",
        information_cutoff=information_cutoff,
        evidence_ids=evidence_ids,
        retrieval_model="retrieval-model",
        retrieval_prompt_version="retrieval-v1",
        created_at=datetime(2026, 8, 7, 8, 6, tzinfo=UTC),
    )


def test_valid_packet_passes_validation() -> None:
    validate_evidence_packet(
        packet=make_packet(),
        market=make_market(),
        snapshot=make_snapshot(),
        evidence_items=[make_evidence()],
    )


def test_future_evidence_is_rejected() -> None:
    future_evidence = make_evidence(
        published_at=datetime(2026, 8, 7, 8, 1, tzinfo=UTC),
    )

    with pytest.raises(
        ValueError,
        match="published after the information cutoff",
    ):
        validate_evidence_for_cutoff(
            evidence=future_evidence,
            information_cutoff=CUTOFF,
        )


def test_unknown_timestamp_quality_is_rejected() -> None:
    evidence = make_evidence(
        timestamp_quality=TimestampQuality.UNKNOWN,
    )

    with pytest.raises(
        ValueError,
        match="unknown timestamp quality",
    ):
        validate_evidence_for_cutoff(
            evidence=evidence,
            information_cutoff=CUTOFF,
        )


def test_packet_cutoff_must_equal_snapshot_time() -> None:
    wrong_cutoff = datetime(2026, 8, 7, 7, 59, tzinfo=UTC)

    with pytest.raises(
        ValueError,
        match="information_cutoff to equal snapshot.observed_at",
    ):
        validate_evidence_packet(
            packet=make_packet(information_cutoff=wrong_cutoff),
            market=make_market(),
            snapshot=make_snapshot(),
            evidence_items=[make_evidence()],
        )


def test_packet_evidence_ids_must_match_items() -> None:
    with pytest.raises(
        ValueError,
        match="must exactly match",
    ):
        validate_evidence_packet(
            packet=make_packet(evidence_ids=("evidence-2",)),
            market=make_market(),
            snapshot=make_snapshot(),
            evidence_items=[make_evidence()],
        )


def test_zero_evidence_packet_is_valid() -> None:
    validate_evidence_packet(
        packet=make_packet(evidence_ids=()),
        market=make_market(),
        snapshot=make_snapshot(),
        evidence_items=[],
    )
