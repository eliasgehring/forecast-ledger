from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forecast_ledger.categories import (
    CategoryMatch,
    filter_protocol_categories,
)
from forecast_ledger.discovery import (
    DiscoveryReport,
    discover_time_window_candidates,
)
from forecast_ledger.domain import require_timezone_aware
from forecast_ledger.registry import (
    PROTOCOL_VERSION,
    RegistryConflictError,
    initialize_registry,
    load_tracked_markets,
    register_market,
)


@dataclass(frozen=True)
class EnrollmentConflict:
    market_id: str
    error_type: str
    message: str


@dataclass(frozen=True)
class EnrollmentReport:
    discovery: DiscoveryReport
    category_matches: int
    unique_markets: int
    registered: int
    already_tracked: int
    conflicts: tuple[EnrollmentConflict, ...]


def _market_signature(match: CategoryMatch) -> tuple:
    candidate = match.candidate
    market = candidate.market

    return (
        market.question,
        market.resolution_rules,
        market.close_time,
        market.yes_token_id,
        market.no_token_id,
        candidate.event_id,
        candidate.event_title,
        candidate.event_slug,
        tuple(sorted(candidate.tag_slugs)),
        tuple(sorted(match.matched_tags)),
        tuple(
            category.value
            for category in match.categories
        ),
    )


def _deduplicate_matches(
    matches: tuple[CategoryMatch, ...],
) -> tuple[
    tuple[CategoryMatch, ...],
    tuple[EnrollmentConflict, ...],
]:
    first_by_id: dict[str, CategoryMatch] = {}
    conflicted_ids: set[str] = set()

    for match in matches:
        market_id = match.candidate.market.market_id
        existing = first_by_id.get(market_id)

        if existing is None:
            first_by_id[market_id] = match
            continue

        if _market_signature(existing) != _market_signature(match):
            conflicted_ids.add(market_id)

    unique = tuple(
        match
        for market_id, match in sorted(first_by_id.items())
        if market_id not in conflicted_ids
    )

    conflicts = tuple(
        EnrollmentConflict(
            market_id=market_id,
            error_type="DiscoveryDuplicateConflict",
            message=(
                "Same market_id appeared with conflicting "
                "contract/category semantics."
            ),
        )
        for market_id in sorted(conflicted_ids)
    )

    return unique, conflicts


def apply_enrollment(
    connection: sqlite3.Connection,
    discovery: DiscoveryReport,
    first_seen_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> EnrollmentReport:
    require_timezone_aware(
        first_seen_at,
        "first_seen_at",
    )

    initialize_registry(connection)

    matches = filter_protocol_categories(
        discovery.candidates
    )

    unique_matches, duplicate_conflicts = (
        _deduplicate_matches(matches)
    )

    registered = 0
    already_tracked = 0
    conflicts = list(duplicate_conflicts)

    for match in unique_matches:
        market_id = match.candidate.market.market_id

        try:
            created = register_market(
                connection=connection,
                match=match,
                first_seen_at=first_seen_at,
                protocol_version=protocol_version,
            )
        except RegistryConflictError as exc:
            conflicts.append(
                EnrollmentConflict(
                    market_id=market_id,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
            continue

        if created:
            registered += 1
        else:
            already_tracked += 1

    return EnrollmentReport(
        discovery=discovery,
        category_matches=len(matches),
        unique_markets=len(unique_matches),
        registered=registered,
        already_tracked=already_tracked,
        conflicts=tuple(conflicts),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover and enroll new Forecast Ledger v0.2 markets."
        )
    )
    parser.add_argument(
        "--db",
        default="data/forecast_ledger.db",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
    )

    args = parser.parse_args()

    db_path = Path(args.db)

    if not db_path.exists():
        raise FileNotFoundError(db_path)

    evaluated_at = datetime.now(UTC)

    print(
        "Discovering open Polymarket markets "
        "5-45 days from resolution..."
    )

    discovery = discover_time_window_candidates(
        evaluated_at=evaluated_at
    )

    matches = filter_protocol_categories(
        discovery.candidates
    )

    connection = sqlite3.connect(db_path)

    try:
        tracked = tuple(
            market
            for market in load_tracked_markets(connection)
            if market.protocol_version == PROTOCOL_VERSION
        )

        tracked_ids = {
            market.market_id
            for market in tracked
        }

        matched_ids = {
            match.candidate.market.market_id
            for match in matches
        }

        print()
        print("DISCOVERY")
        print("=========")
        print("events:", discovery.events_seen)
        print("raw markets:", discovery.raw_markets_seen)
        print("parsed markets:", discovery.parsed_markets)
        print(
            "outside 5-45d:",
            discovery.outside_time_window,
        )
        print(
            "nonbinary:",
            discovery.excluded_non_binary,
        )
        print(
            "missing close:",
            discovery.excluded_missing_close_time,
        )
        print(
            "missing CLOB tokens:",
            discovery.excluded_missing_clob_token_ids,
        )
        print(
            "discovery issues:",
            len(discovery.issues),
        )
        print(
            "5-45d candidates:",
            len(discovery.candidates),
        )
        print(
            "protocol-category matches:",
            len(matches),
        )
        print(
            "currently tracked:",
            len(tracked),
        )
        print(
            "apparently new:",
            len(matched_ids - tracked_ids),
        )

        if not args.execute:
            print()
            print("DRY RUN: no registry writes.")
            return

        report = apply_enrollment(
            connection=connection,
            discovery=discovery,
            first_seen_at=evaluated_at,
        )

        print()
        print("ENROLLMENT")
        print("==========")
        print(
            "category matches:",
            report.category_matches,
        )
        print(
            "unique markets:",
            report.unique_markets,
        )
        print(
            "newly registered:",
            report.registered,
        )
        print(
            "already tracked:",
            report.already_tracked,
        )
        print(
            "conflicts:",
            len(report.conflicts),
        )

        for conflict in report.conflicts:
            print(
                conflict.market_id,
                conflict.error_type,
                "|",
                conflict.message,
            )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
