import json
import sqlite3
from datetime import UTC, datetime

import pytest

from forecast_ledger.registry import (
    TrackedMarket,
)
from forecast_ledger.resolution import (
    ResolutionVerificationError,
    load_unresolved_forecast_market_ids,
    verify_resolution_payloads,
)
from forecast_ledger.resolution_store import (
    initialize_resolution_store,
)

RESOLVED_AT = datetime(
    2026,
    8,
    17,
    23,
    1,
    30,
    tzinfo=UTC,
)


def tracked_market() -> TrackedMarket:
    return TrackedMarket(
        market_id="m1",
        question="Will event happen?",
        resolution_rules=(
            "Resolves YES if event happens."
        ),
        close_time=datetime(
            2026,
            8,
            14,
            23,
            59,
            tzinfo=UTC,
        ),
        yes_token_id="yes-token",
        no_token_id="no-token",
        event_id="event-1",
        event_title="Event",
        event_slug="event",
        categories=("geopolitics",),
        tag_slugs=("geopolitics",),
        first_seen_at=datetime(
            2026,
            8,
            7,
            tzinfo=UTC,
        ),
        protocol_version="v0.2",
    )


def gamma_payload() -> dict:
    return {
        "id": "m1",
        "closed": True,
        "closedTime": (
            RESOLVED_AT.isoformat()
        ),
        "umaResolutionStatus": (
            "resolved"
        ),
        "conditionId": "condition-1",
        "outcomes": json.dumps(
            ["Yes", "No"]
        ),
        "clobTokenIds": json.dumps(
            [
                "yes-token",
                "no-token",
            ]
        ),
        # Deliberately misleading.
        # Resolution logic must ignore this.
        "outcomePrices": json.dumps(
            ["1", "0"]
        ),
    }


def clob_payload(
    *,
    yes_winner: bool,
    no_winner: bool,
) -> dict:
    return {
        "closed": True,
        "tokens": [
            {
                "outcome": "Yes",
                "token_id": "yes-token",
                "winner": yes_winner,
            },
            {
                "outcome": "No",
                "token_id": "no-token",
                "winner": no_winner,
            },
        ],
    }


def test_open_market_is_not_resolved() -> None:
    gamma = gamma_payload()
    gamma["closed"] = False

    result = verify_resolution_payloads(
        market=tracked_market(),
        gamma=gamma,
        clob={},
    )

    assert result is None


def test_no_winner_maps_to_outcome_false() -> None:
    result = verify_resolution_payloads(
        market=tracked_market(),
        gamma=gamma_payload(),
        clob=clob_payload(
            yes_winner=False,
            no_winner=True,
        ),
    )

    assert result is not None
    assert result.outcome_yes is False
    assert (
        result.status.value
        == "resolved_no"
    )


def test_resolution_ignores_outcome_prices() -> None:
    gamma = gamma_payload()

    gamma["outcomePrices"] = (
        json.dumps(
            ["1", "0"]
        )
    )

    result = verify_resolution_payloads(
        market=tracked_market(),
        gamma=gamma,
        clob=clob_payload(
            yes_winner=False,
            no_winner=True,
        ),
    )

    assert result is not None
    assert result.outcome_yes is False


def test_resolution_requires_one_explicit_winner() -> None:
    with pytest.raises(
        ResolutionVerificationError,
        match="exactly one",
    ):
        verify_resolution_payloads(
            market=tracked_market(),
            gamma=gamma_payload(),
            clob=clob_payload(
                yes_winner=False,
                no_winner=False,
            ),
        )


def test_yes_token_identity_must_match_registry() -> None:
    clob = clob_payload(
        yes_winner=True,
        no_winner=False,
    )

    clob["tokens"][0][
        "token_id"
    ] = "different-token"

    with pytest.raises(
        ResolutionVerificationError,
        match="YES token",
    ):
        verify_resolution_payloads(
            market=tracked_market(),
            gamma=gamma_payload(),
            clob=clob,
        )


def test_resolution_source_preserves_winner_lineage() -> None:
    result = verify_resolution_payloads(
        market=tracked_market(),
        gamma=gamma_payload(),
        clob=clob_payload(
            yes_winner=False,
            no_winner=True,
        ),
    )

    assert result is not None

    source = json.loads(
        result.resolution_source
    )

    assert (
        source["condition_id"]
        == "condition-1"
    )
    assert (
        source["winning_outcome"]
        == "No"
    )
    assert (
        source["winning_token_id"]
        == "no-token"
    )


def test_candidate_loader_skips_resolved_markets() -> None:
    connection = sqlite3.connect(
        ":memory:"
    )

    connection.execute(
        """
        CREATE TABLE forecasts (
            market_id TEXT NOT NULL,
            protocol_version TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE tracked_markets (
            market_id TEXT NOT NULL,
            protocol_version TEXT NOT NULL
        )
        """
    )

    initialize_resolution_store(
        connection
    )

    connection.executemany(
        """
        INSERT INTO forecasts (
            market_id,
            protocol_version
        )
        VALUES (?, 'v0.2')
        """,
        [
            ("unresolved",),
            ("resolved",),
        ],
    )

    connection.execute(
        """
        INSERT INTO market_resolutions (
            market_id,
            protocol_version,
            outcome_yes,
            resolved_at,
            resolution_source,
            resolution_status,
            retrieved_at
        )
        VALUES (
            'resolved',
            'v0.2',
            0,
            ?,
            'source',
            'resolved_no',
            ?
        )
        """,
        (
            RESOLVED_AT.isoformat(),
            RESOLVED_AT.isoformat(),
        ),
    )

    connection.commit()

    assert (
        load_unresolved_forecast_market_ids(
            connection
        )
        == ("unresolved",)
    )
