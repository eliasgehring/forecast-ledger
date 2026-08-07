from datetime import UTC, datetime

import pytest

from forecast_ledger.domain import EvidenceItem, EvidencePacket, TimestampQuality


def test_evidence_item_preserves_provenance() -> None:
    item = EvidenceItem(
        evidence_id="evidence-1",
        source_url="https://example.com/article",
        source_name="Example News",
        title="Example event develops",
        published_at=datetime(2026, 8, 7, 7, 30, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 7, 8, 5, tzinfo=UTC),
        excerpt="The event is expected to occur before the stated deadline.",
        timestamp_quality=TimestampQuality.VERIFIED,
    )

    assert item.evidence_id == "evidence-1"
    assert item.timestamp_quality is TimestampQuality.VERIFIED


def test_evidence_item_rejects_naive_publication_time() -> None:
    naive_time = datetime(2026, 8, 7, 7, 30, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(ValueError, match="published_at must be timezone-aware"):
        EvidenceItem(
            evidence_id="evidence-1",
            source_url="https://example.com/article",
            source_name="Example News",
            title="Example event develops",
            published_at=naive_time,
            retrieved_at=datetime(2026, 8, 7, 8, 5, tzinfo=UTC),
            excerpt="Relevant evidence.",
            timestamp_quality=TimestampQuality.VERIFIED,
        )


def test_evidence_packet_accepts_zero_evidence_items() -> None:
    packet = EvidencePacket(
        packet_id="packet-1",
        market_id="market-1",
        snapshot_id="snapshot-1",
        information_cutoff=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
        evidence_ids=(),
        retrieval_model="retrieval-model",
        retrieval_prompt_version="retrieval-v1",
        created_at=datetime(2026, 8, 7, 8, 5, tzinfo=UTC),
    )

    assert packet.evidence_ids == ()


def test_evidence_packet_rejects_duplicate_evidence_ids() -> None:
    with pytest.raises(ValueError, match="evidence_ids must not contain duplicates"):
        EvidencePacket(
            packet_id="packet-1",
            market_id="market-1",
            snapshot_id="snapshot-1",
            information_cutoff=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
            evidence_ids=("evidence-1", "evidence-1"),
            retrieval_model="retrieval-model",
            retrieval_prompt_version="retrieval-v1",
            created_at=datetime(2026, 8, 7, 8, 5, tzinfo=UTC),
        )
