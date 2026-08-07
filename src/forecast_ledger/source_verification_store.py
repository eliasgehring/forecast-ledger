import sqlite3
from dataclasses import dataclass
from datetime import datetime

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.registry import PROTOCOL_VERSION
from forecast_ledger.retrieval import CandidateVerification


class SourceVerificationConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSourceVerification:
    market_id: str
    checkpoint: Checkpoint
    protocol_version: str
    attempt_number: int
    position: int
    candidate_source_url: str
    final_source_url: str
    model_published_at: datetime
    verified_published_at: datetime | None
    fetched_at: datetime
    content_sha256: str
    accepted: bool
    rejection_reason: str | None


def initialize_source_verification_store(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_verifications (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            position INTEGER NOT NULL,
            candidate_source_url TEXT NOT NULL,
            final_source_url TEXT NOT NULL,
            model_published_at TEXT NOT NULL,
            model_timestamp_quality TEXT NOT NULL,
            verified_published_at TEXT,
            verified_timestamp_quality TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            verification_method TEXT,
            modified_at TEXT,
            modification_method TEXT,
            modification_error TEXT,
            verification_error TEXT,
            accepted INTEGER NOT NULL,
            rejection_reason TEXT,
            PRIMARY KEY (
                market_id,
                checkpoint,
                protocol_version,
                attempt_number,
                position
            )
        )
        """
    )

    connection.commit()


def _verification_tuple(
    verification: CandidateVerification,
) -> tuple:
    candidate = verification.candidate
    source = verification.source

    return (
        candidate.source_url,
        source.source_url,
        candidate.published_at.isoformat(),
        candidate.timestamp_quality.value,
        (
            None
            if source.published_at is None
            else source.published_at.isoformat()
        ),
        source.timestamp_quality.value,
        source.fetched_at.isoformat(),
        source.content_sha256,
        source.verification_method,
        (
            None
            if source.modified_at is None
            else source.modified_at.isoformat()
        ),
        source.modification_method,
        source.modification_error,
        source.error,
        int(verification.accepted),
        verification.rejection_reason,
    )


def record_source_verification(
    connection: sqlite3.Connection,
    market_id: str,
    checkpoint: Checkpoint,
    attempt_number: int,
    verification: CandidateVerification,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    key = (
        market_id,
        checkpoint.value,
        protocol_version,
        attempt_number,
        verification.position,
    )

    existing = connection.execute(
        """
        SELECT
            candidate_source_url,
            final_source_url,
            model_published_at,
            model_timestamp_quality,
            verified_published_at,
            verified_timestamp_quality,
            fetched_at,
            content_sha256,
            verification_method,
            modified_at,
            modification_method,
            modification_error,
            verification_error,
            accepted,
            rejection_reason
        FROM source_verifications
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND attempt_number = ?
          AND position = ?
        """,
        key,
    ).fetchone()

    incoming = _verification_tuple(
        verification
    )

    if existing is not None:
        if existing != incoming:
            raise SourceVerificationConflictError(
                "Stored source verification changed."
            )

        return False

    connection.execute(
        """
        INSERT INTO source_verifications (
            market_id,
            checkpoint,
            protocol_version,
            attempt_number,
            position,
            candidate_source_url,
            final_source_url,
            model_published_at,
            model_timestamp_quality,
            verified_published_at,
            verified_timestamp_quality,
            fetched_at,
            content_sha256,
            verification_method,
            modified_at,
            modification_method,
            modification_error,
            verification_error,
            accepted,
            rejection_reason
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            *key,
            *incoming,
        ),
    )

    connection.commit()

    return True
