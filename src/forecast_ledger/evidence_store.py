import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import (
    EvidenceItem,
    EvidencePacket,
    TimestampQuality,
    require_timezone_aware,
)
from forecast_ledger.registry import PROTOCOL_VERSION
from forecast_ledger.validation import validate_evidence_for_cutoff


class EvidenceConflictError(RuntimeError):
    pass


class PacketValidationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class StoredEvidencePacket:
    packet: EvidencePacket
    checkpoint: Checkpoint
    protocol_version: str
    attempt_number: int
    retrieval_response_id: str


@dataclass(frozen=True)
class PacketValidation:
    packet_id: str
    status: PacketValidationStatus
    reason: str | None
    validated_at: datetime | None


def _table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    return {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


def initialize_evidence_store(
    connection: sqlite3.Connection,
) -> None:
    existing_packet_columns = _table_columns(
        connection,
        "evidence_packets",
    )

    if (
        existing_packet_columns
        and "attempt_number" not in existing_packet_columns
    ):
        raise RuntimeError(
            "Legacy evidence_packets schema detected. "
            "Run the evidence packet migration first."
        )

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
            attempt_number INTEGER NOT NULL,
            retrieval_response_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            information_cutoff TEXT NOT NULL,
            retrieval_model TEXT NOT NULL,
            retrieval_prompt_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (
                market_id,
                checkpoint,
                protocol_version,
                attempt_number
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

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_packet_validations (
            packet_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            validated_at TEXT NOT NULL
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


def _load_retrieval_response_id(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    protocol_version: str,
    attempt_number: int,
) -> str:
    row = connection.execute(
        """
        SELECT response_id
        FROM retrieval_attempts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND attempt_number = ?
          AND status = 'succeeded'
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
            attempt_number,
        ),
    ).fetchone()

    if row is None or not row[0]:
        raise ValueError(
            "Evidence packet requires a successful "
            "retrieval attempt."
        )

    return row[0]


def record_evidence_packet(
    connection: sqlite3.Connection,
    packet: EvidencePacket,
    checkpoint: Checkpoint,
    evidence_items: tuple[EvidenceItem, ...],
    attempt_number: int = 1,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    if attempt_number not in {1, 2, 3}:
        raise ValueError(
            "Evidence packet attempt number must be 1, 2, or 3."
        )

    _validate_packet_against_snapshot(
        connection=connection,
        packet=packet,
        checkpoint=checkpoint,
        protocol_version=protocol_version,
    )

    retrieval_response_id = _load_retrieval_response_id(
        connection=connection,
        market_id=packet.market_id,
        checkpoint=checkpoint,
        protocol_version=protocol_version,
        attempt_number=attempt_number,
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
            retrieval_response_id,
            snapshot_id,
            information_cutoff,
            retrieval_model,
            retrieval_prompt_version,
            created_at
        FROM evidence_packets
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND attempt_number = ?
        """,
        (
            packet.market_id,
            checkpoint.value,
            protocol_version,
            attempt_number,
        ),
    ).fetchone()

    if existing_packet is not None:
        incoming_packet = (
            packet.packet_id,
            retrieval_response_id,
            packet.snapshot_id,
            packet.information_cutoff.isoformat(),
            packet.retrieval_model,
            packet.retrieval_prompt_version,
            packet.created_at.isoformat(),
        )

        if existing_packet != incoming_packet:
            raise EvidenceConflictError(
                "A different evidence packet already exists "
                "for this retrieval attempt."
            )

        existing_ids = tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT evidence_id
                FROM evidence_packet_items
                WHERE packet_id = ?
                ORDER BY position
                """,
                (packet.packet_id,),
            ).fetchall()
        )

        if existing_ids != packet.evidence_ids:
            raise EvidenceConflictError(
                "Stored evidence membership differs "
                "from incoming packet."
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
                attempt_number,
                retrieval_response_id,
                snapshot_id,
                information_cutoff,
                retrieval_model,
                retrieval_prompt_version,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                packet.packet_id,
                packet.market_id,
                checkpoint.value,
                protocol_version,
                attempt_number,
                retrieval_response_id,
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


def record_packet_validation(
    connection: sqlite3.Connection,
    packet_id: str,
    status: PacketValidationStatus,
    reason: str,
    validated_at: datetime,
) -> bool:
    require_timezone_aware(
        validated_at,
        "validated_at",
    )

    if status == PacketValidationStatus.UNVERIFIED:
        raise ValueError(
            "UNVERIFIED is represented by absence of validation."
        )

    if not reason.strip():
        raise ValueError(
            "Packet validation reason cannot be empty."
        )

    packet_row = connection.execute(
        """
        SELECT
            market_id,
            checkpoint,
            protocol_version
        FROM evidence_packets
        WHERE packet_id = ?
        """,
        (packet_id,),
    ).fetchone()

    if packet_row is None:
        raise ValueError(
            "Cannot validate an unknown evidence packet."
        )

    existing = connection.execute(
        """
        SELECT status, reason, validated_at
        FROM evidence_packet_validations
        WHERE packet_id = ?
        """,
        (packet_id,),
    ).fetchone()

    incoming = (
        status.value,
        reason,
        validated_at.isoformat(),
    )

    if existing is not None:
        if existing != incoming:
            raise EvidenceConflictError(
                "Evidence packet validation is immutable."
            )

        return False

    if status == PacketValidationStatus.VALID:
        other_valid = connection.execute(
            """
            SELECT packet.packet_id
            FROM evidence_packets AS packet
            JOIN evidence_packet_validations AS validation
              ON validation.packet_id = packet.packet_id
            WHERE packet.market_id = ?
              AND packet.checkpoint = ?
              AND packet.protocol_version = ?
              AND validation.status = 'valid'
            LIMIT 1
            """,
            packet_row,
        ).fetchone()

        if other_valid is not None:
            raise EvidenceConflictError(
                "A valid evidence packet already exists "
                "for this checkpoint."
            )

    connection.execute(
        """
        INSERT INTO evidence_packet_validations (
            packet_id,
            status,
            reason,
            validated_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            packet_id,
            status.value,
            reason,
            validated_at.isoformat(),
        ),
    )
    connection.commit()

    return True


def load_packet_validation(
    connection: sqlite3.Connection,
    packet_id: str,
) -> PacketValidation:
    row = connection.execute(
        """
        SELECT status, reason, validated_at
        FROM evidence_packet_validations
        WHERE packet_id = ?
        """,
        (packet_id,),
    ).fetchone()

    if row is None:
        return PacketValidation(
            packet_id=packet_id,
            status=PacketValidationStatus.UNVERIFIED,
            reason=None,
            validated_at=None,
        )

    return PacketValidation(
        packet_id=packet_id,
        status=PacketValidationStatus(row[0]),
        reason=row[1],
        validated_at=datetime.fromisoformat(row[2]),
    )


def load_valid_packet_id_for_checkpoint(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    protocol_version: str = PROTOCOL_VERSION,
) -> str | None:
    row = connection.execute(
        """
        SELECT packet.packet_id
        FROM evidence_packets AS packet
        JOIN evidence_packet_validations AS validation
          ON validation.packet_id = packet.packet_id
        WHERE packet.market_id = ?
          AND packet.checkpoint = ?
          AND packet.protocol_version = ?
          AND validation.status = 'valid'
        """,
        (
            market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    return None if row is None else row[0]


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
