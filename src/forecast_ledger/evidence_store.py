import sqlite3
from dataclasses import dataclass
from datetime import datetime

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import (
    EvidenceItem,
    EvidencePacket,
    TimestampQuality,
)
from forecast_ledger.registry import PROTOCOL_VERSION
from forecast_ledger.validation import validate_evidence_for_cutoff


class EvidenceConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredEvidencePacket:
    packet: EvidencePacket
    checkpoint: Checkpoint
    protocol_version: str


def initialize_evidence_store(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_items (
            evidence_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            source_name TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            timestamp_quality TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_packets (
            packet_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            information_cutoff TEXT NOT NULL,
            retrieval_model TEXT NOT NULL,
            retrieval_prompt_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (
                market_id,
                checkpoint,
                protocol_version
            )
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_packet_items (
            packet_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (
                packet_id,
                evidence_id
            ),
            UNIQUE (
                packet_id,
                position
            )
        )
        """
    )

    connection.commit()


def _evidence_item_tuple(
    item: EvidenceItem,
) -> tuple:
    return (
        item.source_url,
        item.source_name,
        item.title,
        item.published_at.isoformat(),
        item.retrieved_at.isoformat(),
        item.excerpt,
        item.timestamp_quality.value,
    )


def _validate_packet_against_snapshot(
    connection: sqlite3.Connection,
    packet: EvidencePacket,
    checkpoint: Checkpoint,
    protocol_version: str,
) -> None:
    row = connection.execute(
        """
        SELECT observed_at
        FROM market_snapshots
        WHERE snapshot_id = ?
          AND market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        """,
        (
            packet.snapshot_id,
            packet.market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    if row is None:
        raise ValueError(
            "Evidence packet requires a persisted market snapshot."
        )

    snapshot_observed_at = datetime.fromisoformat(row[0])

    if packet.information_cutoff != snapshot_observed_at:
        raise ValueError(
            "Evidence packet cutoff must equal snapshot observed_at."
        )


def record_evidence_packet(
    connection: sqlite3.Connection,
    packet: EvidencePacket,
    checkpoint: Checkpoint,
    evidence_items: tuple[EvidenceItem, ...],
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    _validate_packet_against_snapshot(
        connection=connection,
        packet=packet,
        checkpoint=checkpoint,
        protocol_version=protocol_version,
    )

    item_ids = tuple(
        item.evidence_id
        for item in evidence_items
    )

    if item_ids != packet.evidence_ids:
        raise ValueError(
            "Evidence items must exactly match packet evidence_ids "
            "in the same order."
        )

    for item in evidence_items:
        validate_evidence_for_cutoff(
            item,
            packet.information_cutoff,
        )

        if item.retrieved_at < packet.information_cutoff:
            raise ValueError(
                "Evidence retrieved_at cannot precede "
                "the information cutoff."
            )

        if item.retrieved_at > packet.created_at:
            raise ValueError(
                "Evidence retrieved_at cannot be after "
                "packet created_at."
            )

    existing_packet = connection.execute(
        """
        SELECT
            packet_id,
            snapshot_id,
            information_cutoff,
            retrieval_model,
            retrieval_prompt_version,
            created_at
        FROM evidence_packets
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        """,
        (
            packet.market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    if existing_packet is not None:
        existing_ids = tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT evidence_id
                FROM evidence_packet_items
                WHERE packet_id = ?
                ORDER BY position
                """,
                (existing_packet[0],),
            ).fetchall()
        )

        incoming_packet = (
            packet.packet_id,
            packet.snapshot_id,
            packet.information_cutoff.isoformat(),
            packet.retrieval_model,
            packet.retrieval_prompt_version,
            packet.created_at.isoformat(),
        )

        if existing_packet != incoming_packet:
            raise EvidenceConflictError(
                "A different evidence packet already exists "
                "for this checkpoint."
            )

        if existing_ids != packet.evidence_ids:
            raise EvidenceConflictError(
                "Stored evidence membership differs "
                "from incoming packet."
            )

        for item in evidence_items:
            stored = connection.execute(
                """
                SELECT
                    source_url,
                    source_name,
                    title,
                    published_at,
                    retrieved_at,
                    excerpt,
                    timestamp_quality
                FROM evidence_items
                WHERE evidence_id = ?
                """,
                (item.evidence_id,),
            ).fetchone()

            if stored != _evidence_item_tuple(item):
                raise EvidenceConflictError(
                    f"Evidence item {item.evidence_id} changed."
                )

        return False

    with connection:
        for item in evidence_items:
            existing_item = connection.execute(
                """
                SELECT
                    source_url,
                    source_name,
                    title,
                    published_at,
                    retrieved_at,
                    excerpt,
                    timestamp_quality
                FROM evidence_items
                WHERE evidence_id = ?
                """,
                (item.evidence_id,),
            ).fetchone()

            incoming_item = _evidence_item_tuple(item)

            if existing_item is not None:
                if existing_item != incoming_item:
                    raise EvidenceConflictError(
                        f"Evidence item {item.evidence_id} changed."
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO evidence_items (
                        evidence_id,
                        source_url,
                        source_name,
                        title,
                        published_at,
                        retrieved_at,
                        excerpt,
                        timestamp_quality
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.evidence_id,
                        *incoming_item,
                    ),
                )

        connection.execute(
            """
            INSERT INTO evidence_packets (
                packet_id,
                market_id,
                checkpoint,
                protocol_version,
                snapshot_id,
                information_cutoff,
                retrieval_model,
                retrieval_prompt_version,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                packet.packet_id,
                packet.market_id,
                checkpoint.value,
                protocol_version,
                packet.snapshot_id,
                packet.information_cutoff.isoformat(),
                packet.retrieval_model,
                packet.retrieval_prompt_version,
                packet.created_at.isoformat(),
            ),
        )

        for position, evidence_id in enumerate(
            packet.evidence_ids
        ):
            connection.execute(
                """
                INSERT INTO evidence_packet_items (
                    packet_id,
                    evidence_id,
                    position
                )
                VALUES (?, ?, ?)
                """,
                (
                    packet.packet_id,
                    evidence_id,
                    position,
                ),
            )

    return True


def load_evidence_items_for_packet(
    connection: sqlite3.Connection,
    packet_id: str,
) -> tuple[EvidenceItem, ...]:
    rows = connection.execute(
        """
        SELECT
            item.evidence_id,
            item.source_url,
            item.source_name,
            item.title,
            item.published_at,
            item.retrieved_at,
            item.excerpt,
            item.timestamp_quality
        FROM evidence_packet_items AS mapping
        JOIN evidence_items AS item
          ON item.evidence_id = mapping.evidence_id
        WHERE mapping.packet_id = ?
        ORDER BY mapping.position
        """,
        (packet_id,),
    ).fetchall()

    return tuple(
        EvidenceItem(
            evidence_id=row[0],
            source_url=row[1],
            source_name=row[2],
            title=row[3],
            published_at=datetime.fromisoformat(row[4]),
            retrieved_at=datetime.fromisoformat(row[5]),
            excerpt=row[6],
            timestamp_quality=TimestampQuality(row[7]),
        )
        for row in rows
    )
