from collections.abc import Sequence
from datetime import datetime

from forecast_ledger.domain import (
    EvidenceItem,
    EvidencePacket,
    Market,
    MarketSnapshot,
    TimestampQuality,
)


def validate_evidence_for_cutoff(
    evidence: EvidenceItem,
    information_cutoff: datetime,
) -> None:
    if evidence.timestamp_quality is TimestampQuality.UNKNOWN:
        raise ValueError("Evidence with unknown timestamp quality is not permitted.")

    if evidence.published_at > information_cutoff:
        raise ValueError("Evidence was published after the information cutoff.")


def validate_evidence_packet(
    packet: EvidencePacket,
    market: Market,
    snapshot: MarketSnapshot,
    evidence_items: Sequence[EvidenceItem],
) -> None:
    if packet.market_id != market.market_id:
        raise ValueError("Evidence packet market_id does not match market.")

    if packet.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Evidence packet snapshot_id does not match snapshot.")

    if snapshot.market_id != market.market_id:
        raise ValueError("Snapshot market_id does not match market.")

    if packet.information_cutoff != snapshot.observed_at:
        raise ValueError(
            "Protocol v0.1 requires information_cutoff to equal snapshot.observed_at."
        )

    if packet.created_at < packet.information_cutoff:
        raise ValueError("Evidence packet cannot be created before its information cutoff.")

    actual_evidence_ids = tuple(item.evidence_id for item in evidence_items)

    if actual_evidence_ids != packet.evidence_ids:
        raise ValueError(
            "Evidence packet IDs must exactly match the supplied evidence items and order."
        )

    for evidence in evidence_items:
        validate_evidence_for_cutoff(
            evidence=evidence,
            information_cutoff=packet.information_cutoff,
        )
