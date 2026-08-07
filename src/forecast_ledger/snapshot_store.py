import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from forecast_ledger.checkpoint_ledger import CheckpointStatus
from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import MarketSnapshot
from forecast_ledger.registry import PROTOCOL_VERSION


class SnapshotConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredMarketSnapshot:
    snapshot: MarketSnapshot
    checkpoint: Checkpoint
    protocol_version: str
    raw_yes_book: dict
    raw_no_book: dict | None
    no_book_error: str | None


def initialize_snapshot_store(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            yes_bid REAL NOT NULL,
            yes_ask REAL NOT NULL,
            no_bid REAL,
            no_ask REAL,
            raw_yes_book_json TEXT NOT NULL,
            raw_no_book_json TEXT,
            no_book_error TEXT,
            UNIQUE (
                market_id,
                checkpoint,
                protocol_version
            )
        )
        """
    )
    connection.commit()


def record_market_snapshot(
    connection: sqlite3.Connection,
    snapshot: MarketSnapshot,
    checkpoint: Checkpoint,
    raw_yes_book: dict,
    raw_no_book: dict | None,
    no_book_error: str | None,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    yes_json = json.dumps(
        raw_yes_book,
        sort_keys=True,
        separators=(",", ":"),
    )

    no_json = (
        None
        if raw_no_book is None
        else json.dumps(
            raw_no_book,
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    existing = connection.execute(
        """
        SELECT
            snapshot_id,
            observed_at,
            yes_bid,
            yes_ask,
            no_bid,
            no_ask,
            raw_yes_book_json,
            raw_no_book_json,
            no_book_error
        FROM market_snapshots
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        """,
        (
            snapshot.market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    incoming = (
        snapshot.snapshot_id,
        snapshot.observed_at.isoformat(),
        snapshot.yes_bid,
        snapshot.yes_ask,
        snapshot.no_bid,
        snapshot.no_ask,
        yes_json,
        no_json,
        no_book_error,
    )

    if existing is not None:
        if existing == incoming:
            return False

        raise SnapshotConflictError(
            "A different snapshot already exists for "
            f"{snapshot.market_id} {checkpoint.value}."
        )

    checkpoint_row = connection.execute(
        """
        SELECT status
        FROM checkpoint_records
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        """,
        (
            snapshot.market_id,
            checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    if checkpoint_row is None:
        raise ValueError(
            "Checkpoint must exist before recording a snapshot."
        )

    if checkpoint_row[0] != CheckpointStatus.PENDING.value:
        raise ValueError(
            "Checkpoint must be pending before recording a snapshot."
        )

    with connection:
        connection.execute(
            """
            INSERT INTO market_snapshots (
                snapshot_id,
                market_id,
                checkpoint,
                protocol_version,
                observed_at,
                yes_bid,
                yes_ask,
                no_bid,
                no_ask,
                raw_yes_book_json,
                raw_no_book_json,
                no_book_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.market_id,
                checkpoint.value,
                protocol_version,
                snapshot.observed_at.isoformat(),
                snapshot.yes_bid,
                snapshot.yes_ask,
                snapshot.no_bid,
                snapshot.no_ask,
                yes_json,
                no_json,
                no_book_error,
            ),
        )

        connection.execute(
            """
            UPDATE checkpoint_records
            SET status = ?
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
            """,
            (
                CheckpointStatus.SNAPSHOT_RECORDED.value,
                snapshot.market_id,
                checkpoint.value,
                protocol_version,
            ),
        )

    return True


def load_market_snapshots(
    connection: sqlite3.Connection,
) -> tuple[StoredMarketSnapshot, ...]:
    rows = connection.execute(
        """
        SELECT
            snapshot_id,
            market_id,
            checkpoint,
            protocol_version,
            observed_at,
            yes_bid,
            yes_ask,
            no_bid,
            no_ask,
            raw_yes_book_json,
            raw_no_book_json,
            no_book_error
        FROM market_snapshots
        ORDER BY market_id, checkpoint
        """
    ).fetchall()

    return tuple(
        StoredMarketSnapshot(
            snapshot=MarketSnapshot(
                snapshot_id=row[0],
                market_id=row[1],
                observed_at=datetime.fromisoformat(row[4]),
                yes_bid=row[5],
                yes_ask=row[6],
                no_bid=row[7],
                no_ask=row[8],
            ),
            checkpoint=Checkpoint(row[2]),
            protocol_version=row[3],
            raw_yes_book=json.loads(row[9]),
            raw_no_book=(
                None
                if row[10] is None
                else json.loads(row[10])
            ),
            no_book_error=row[11],
        )
        for row in rows
    )
