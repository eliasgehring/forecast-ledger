import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from forecast_ledger.categories import CategoryMatch
from forecast_ledger.domain import require_timezone_aware


PROTOCOL_VERSION = "v0.1"


class RegistryConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrackedMarket:
    market_id: str
    question: str
    resolution_rules: str
    close_time: datetime
    yes_token_id: str
    no_token_id: str
    event_id: str
    event_title: str
    event_slug: str
    categories: tuple[str, ...]
    tag_slugs: tuple[str, ...]
    first_seen_at: datetime
    protocol_version: str


def initialize_registry(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tracked_markets (
            market_id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            resolution_rules TEXT NOT NULL,
            close_time TEXT NOT NULL,
            yes_token_id TEXT NOT NULL,
            no_token_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_title TEXT NOT NULL,
            event_slug TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            tag_slugs_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            protocol_version TEXT NOT NULL
        )
        """
    )
    connection.commit()


def register_market(
    connection: sqlite3.Connection,
    match: CategoryMatch,
    first_seen_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    require_timezone_aware(first_seen_at, "first_seen_at")

    candidate = match.candidate
    market = candidate.market

    categories = tuple(
        category.value
        for category in match.categories
    )

    existing = connection.execute(
        """
        SELECT
            question,
            resolution_rules,
            close_time,
            yes_token_id,
            no_token_id
        FROM tracked_markets
        WHERE market_id = ?
        """,
        (market.market_id,),
    ).fetchone()

    if existing is not None:
        existing_contract = (
            existing[0],
            existing[1],
            existing[2],
            existing[3],
            existing[4],
        )

        observed_contract = (
            market.question,
            market.resolution_rules,
            market.close_time.isoformat(),
            market.yes_token_id,
            market.no_token_id,
        )

        if existing_contract != observed_contract:
            raise RegistryConflictError(
                f"Tracked market {market.market_id} changed contract fields."
            )

        return False

    connection.execute(
        """
        INSERT INTO tracked_markets (
            market_id,
            question,
            resolution_rules,
            close_time,
            yes_token_id,
            no_token_id,
            event_id,
            event_title,
            event_slug,
            categories_json,
            tag_slugs_json,
            first_seen_at,
            protocol_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market.market_id,
            market.question,
            market.resolution_rules,
            market.close_time.isoformat(),
            market.yes_token_id,
            market.no_token_id,
            candidate.event_id,
            candidate.event_title,
            candidate.event_slug,
            json.dumps(categories),
            json.dumps(candidate.tag_slugs),
            first_seen_at.isoformat(),
            protocol_version,
        ),
    )
    connection.commit()

    return True


def load_tracked_markets(
    connection: sqlite3.Connection,
) -> tuple[TrackedMarket, ...]:
    rows = connection.execute(
        """
        SELECT
            market_id,
            question,
            resolution_rules,
            close_time,
            yes_token_id,
            no_token_id,
            event_id,
            event_title,
            event_slug,
            categories_json,
            tag_slugs_json,
            first_seen_at,
            protocol_version
        FROM tracked_markets
        ORDER BY market_id
        """
    ).fetchall()

    return tuple(
        TrackedMarket(
            market_id=row[0],
            question=row[1],
            resolution_rules=row[2],
            close_time=datetime.fromisoformat(row[3]),
            yes_token_id=row[4],
            no_token_id=row[5],
            event_id=row[6],
            event_title=row[7],
            event_slug=row[8],
            categories=tuple(json.loads(row[9])),
            tag_slugs=tuple(json.loads(row[10])),
            first_seen_at=datetime.fromisoformat(row[11]),
            protocol_version=row[12],
        )
        for row in rows
    )
