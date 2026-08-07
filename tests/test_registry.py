import json
import sqlite3
from datetime import UTC, datetime

import pytest

from forecast_ledger.categories import classify_candidate
from forecast_ledger.discovery import candidate_from_event_market
from forecast_ledger.registry import (
    RegistryConflictError,
    initialize_registry,
    load_tracked_markets,
    register_market,
)


FIRST_SEEN = datetime(
    2026,
    8,
    7,
    10,
    0,
    tzinfo=UTC,
)


def make_match(
    resolution_rules: str = "Resolves YES if the event happens.",
):
    event = {
        "id": "event-1",
        "title": "Example technology event",
        "slug": "example-technology-event",
        "tags": [
            {
                "label": "AI",
                "slug": "ai",
            }
        ],
    }

    market = {
        "id": "market-1",
        "question": "Will example event happen?",
        "description": resolution_rules,
        "endDate": "2026-08-31T00:00:00Z",
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(
            [
                "yes-token",
                "no-token",
            ]
        ),
    }

    candidate = candidate_from_event_market(
        event=event,
        raw_market=market,
    )

    return classify_candidate(candidate)


def test_register_and_load_market() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_registry(connection)

    created = register_market(
        connection=connection,
        match=make_match(),
        first_seen_at=FIRST_SEEN,
    )

    tracked = load_tracked_markets(connection)

    assert created is True
    assert len(tracked) == 1
    assert tracked[0].market_id == "market-1"
    assert tracked[0].categories == ("technology",)
    assert tracked[0].first_seen_at == FIRST_SEEN
    assert tracked[0].protocol_version == "v0.1"


def test_identical_registration_is_idempotent() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_registry(connection)

    first_created = register_market(
        connection=connection,
        match=make_match(),
        first_seen_at=FIRST_SEEN,
    )

    second_created = register_market(
        connection=connection,
        match=make_match(),
        first_seen_at=FIRST_SEEN,
    )

    assert first_created is True
    assert second_created is False
    assert len(load_tracked_markets(connection)) == 1


def test_duplicate_registration_preserves_first_seen_time() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_registry(connection)

    register_market(
        connection=connection,
        match=make_match(),
        first_seen_at=FIRST_SEEN,
    )

    register_market(
        connection=connection,
        match=make_match(),
        first_seen_at=datetime(
            2026,
            8,
            8,
            10,
            0,
            tzinfo=UTC,
        ),
    )

    tracked = load_tracked_markets(connection)

    assert tracked[0].first_seen_at == FIRST_SEEN


def test_changed_contract_is_rejected() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_registry(connection)

    register_market(
        connection=connection,
        match=make_match(
            resolution_rules="Original resolution rules.",
        ),
        first_seen_at=FIRST_SEEN,
    )

    with pytest.raises(
        RegistryConflictError,
        match="changed contract fields",
    ):
        register_market(
            connection=connection,
            match=make_match(
                resolution_rules="Changed resolution rules.",
            ),
            first_seen_at=FIRST_SEEN,
        )


def test_naive_first_seen_time_is_rejected() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_registry(connection)

    naive_time = FIRST_SEEN.replace(tzinfo=None)

    with pytest.raises(
        ValueError,
        match="first_seen_at must be timezone-aware",
    ):
        register_market(
            connection=connection,
            match=make_match(),
            first_seen_at=naive_time,
        )
