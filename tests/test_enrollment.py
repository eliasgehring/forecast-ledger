import sqlite3
from datetime import UTC, datetime, timedelta

from forecast_ledger.discovery import (
    DiscoveryReport,
    MarketCandidate,
)
from forecast_ledger.domain import Market
from forecast_ledger.enrollment import apply_enrollment
from forecast_ledger.registry import load_tracked_markets

NOW = datetime(
    2026,
    8,
    20,
    21,
    tzinfo=UTC,
)


def candidate(
    market_id: str,
    *,
    tags: tuple[str, ...],
    question: str | None = None,
    event_id: str | None = None,
) -> MarketCandidate:
    return MarketCandidate(
        market=Market(
            market_id=market_id,
            question=(
                question
                or f"Will {market_id} happen?"
            ),
            resolution_rules=(
                "Resolves YES if the event happens."
            ),
            close_time=(
                NOW + timedelta(days=20)
            ),
            yes_token_id=f"yes-{market_id}",
            no_token_id=f"no-{market_id}",
        ),
        event_id=(
            event_id
            or f"event-{market_id}"
        ),
        event_title=f"Event {market_id}",
        event_slug=f"event-{market_id}",
        tag_slugs=tags,
    )


def report(
    *candidates: MarketCandidate,
) -> DiscoveryReport:
    return DiscoveryReport(
        candidates=tuple(candidates),
        events_seen=len(candidates),
        raw_markets_seen=len(candidates),
        parsed_markets=len(candidates),
        outside_time_window=0,
        excluded_non_binary=0,
        excluded_missing_close_time=0,
        excluded_missing_clob_token_ids=0,
        issues=(),
    )


def connection() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def test_only_protocol_category_markets_are_enrolled() -> None:
    con = connection()

    result = apply_enrollment(
        connection=con,
        discovery=report(
            candidate(
                "ai",
                tags=("ai",),
            ),
            candidate(
                "sports",
                tags=("sports",),
            ),
        ),
        first_seen_at=NOW,
    )

    assert result.category_matches == 1
    assert result.registered == 1
    assert result.already_tracked == 0
    assert result.conflicts == ()

    tracked = load_tracked_markets(con)

    assert len(tracked) == 1
    assert tracked[0].market_id == "ai"
    assert tracked[0].categories == (
        "technology",
    )


def test_repeated_enrollment_is_idempotent() -> None:
    con = connection()

    discovery = report(
        candidate(
            "m1",
            tags=("business",),
        )
    )

    first = apply_enrollment(
        connection=con,
        discovery=discovery,
        first_seen_at=NOW,
    )

    second = apply_enrollment(
        connection=con,
        discovery=discovery,
        first_seen_at=(
            NOW + timedelta(days=1)
        ),
    )

    assert first.registered == 1
    assert second.registered == 0
    assert second.already_tracked == 1

    tracked = load_tracked_markets(con)

    assert len(tracked) == 1
    assert tracked[0].first_seen_at == NOW


def test_changed_tracked_contract_fails_closed() -> None:
    con = connection()

    apply_enrollment(
        connection=con,
        discovery=report(
            candidate(
                "m1",
                tags=("science",),
                question="Original question?",
            )
        ),
        first_seen_at=NOW,
    )

    changed = apply_enrollment(
        connection=con,
        discovery=report(
            candidate(
                "m1",
                tags=("science",),
                question="Changed question?",
            )
        ),
        first_seen_at=(
            NOW + timedelta(days=1)
        ),
    )

    assert changed.registered == 0
    assert changed.already_tracked == 0
    assert len(changed.conflicts) == 1
    assert (
        changed.conflicts[0].error_type
        == "RegistryConflictError"
    )

    tracked = load_tracked_markets(con)

    assert tracked[0].question == (
        "Original question?"
    )


def test_conflicting_duplicate_discovery_is_excluded() -> None:
    con = connection()

    result = apply_enrollment(
        connection=con,
        discovery=report(
            candidate(
                "m1",
                tags=("ai",),
                question="Question one?",
            ),
            candidate(
                "m1",
                tags=("ai",),
                question="Question two?",
            ),
        ),
        first_seen_at=NOW,
    )

    assert result.category_matches == 2
    assert result.unique_markets == 0
    assert result.registered == 0
    assert len(result.conflicts) == 1
    assert (
        result.conflicts[0].error_type
        == "DiscoveryDuplicateConflict"
    )
    assert load_tracked_markets(con) == ()


def test_conflicting_event_identity_is_excluded() -> None:
    con = connection()

    result = apply_enrollment(
        connection=con,
        discovery=report(
            candidate(
                "m1",
                tags=("geopolitics",),
                event_id="event-a",
            ),
            candidate(
                "m1",
                tags=("geopolitics",),
                event_id="event-b",
            ),
        ),
        first_seen_at=NOW,
    )

    assert result.unique_markets == 0
    assert result.registered == 0
    assert len(result.conflicts) == 1


def test_identical_duplicate_is_registered_once() -> None:
    con = connection()

    first = candidate(
        "m1",
        tags=("geopolitics",),
    )

    duplicate = candidate(
        "m1",
        tags=("geopolitics",),
    )

    result = apply_enrollment(
        connection=con,
        discovery=report(
            first,
            duplicate,
        ),
        first_seen_at=NOW,
    )

    assert result.category_matches == 2
    assert result.unique_markets == 1
    assert result.registered == 1
    assert result.conflicts == ()
    assert len(load_tracked_markets(con)) == 1
