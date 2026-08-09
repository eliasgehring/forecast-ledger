import json
import sqlite3
from datetime import UTC, datetime

import pytest

from forecast_ledger.eligibility_store import (
    initialize_eligibility_store,
)
from forecast_ledger.review import (
    DECISION_BY_CHOICE,
    load_review_candidates,
    record_candidate_review,
)
from forecast_ledger.semantic_review import (
    SemanticDecision,
    initialize_semantic_reviews,
)

NOW = datetime(
    2026,
    8,
    9,
    15,
    tzinfo=UTC,
)


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    connection.execute(
        """
        CREATE TABLE tracked_markets (
            market_id TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            question TEXT NOT NULL,
            resolution_rules TEXT NOT NULL,
            categories_json TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE market_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            yes_bid REAL NOT NULL,
            yes_ask REAL NOT NULL
        )
        """
    )

    initialize_eligibility_store(
        connection
    )
    initialize_semantic_reviews(
        connection
    )

    return connection


def insert_candidate(
    connection: sqlite3.Connection,
    *,
    market_id: str = "m1",
    eligible: bool = True,
) -> None:
    snapshot_id = (
        f"snapshot-{market_id}"
    )

    connection.execute(
        """
        INSERT INTO tracked_markets
        VALUES (
            ?, 'v0.2', ?, ? , ?
        )
        """,
        (
            market_id,
            f"Will {market_id} happen?",
            "Resolves YES if it happens.",
            json.dumps(
                ["technology"]
            ),
        ),
    )

    connection.execute(
        """
        INSERT INTO market_snapshots
        VALUES (
            ?, ?, '7d', 'v0.2',
            ?, 0.20, 0.22
        )
        """,
        (
            snapshot_id,
            market_id,
            NOW.isoformat(),
        ),
    )

    connection.execute(
        """
        INSERT INTO machine_eligibility (
            market_id,
            checkpoint,
            protocol_version,
            snapshot_id,
            eligible_for_review,
            rejection_reasons_json,
            evaluated_at
        )
        VALUES (
            ?, '7d', 'v0.2', ?, ?, '[]', ?
        )
        """,
        (
            market_id,
            snapshot_id,
            int(eligible),
            NOW.isoformat(),
        ),
    )

    connection.commit()


def test_loads_only_machine_eligible_unreviewed() -> None:
    connection = make_connection()

    insert_candidate(
        connection,
        market_id="eligible",
        eligible=True,
    )

    insert_candidate(
        connection,
        market_id="ineligible",
        eligible=False,
    )

    candidates = load_review_candidates(
        connection
    )

    assert len(candidates) == 1
    assert (
        candidates[0].market_id
        == "eligible"
    )
    assert (
        candidates[0].market_probability
        == pytest.approx(0.21)
    )
    assert (
        candidates[0].yes_spread
        == pytest.approx(0.02)
    )


def test_reviewed_candidate_leaves_queue() -> None:
    connection = make_connection()
    insert_candidate(connection)

    candidate = load_review_candidates(
        connection
    )[0]

    created = record_candidate_review(
        connection=connection,
        candidate=candidate,
        decision=SemanticDecision.INCLUDED,
        reason=(
            "Resolution is objective and binary."
        ),
        reviewed_at=NOW,
    )

    assert created is True

    assert (
        load_review_candidates(
            connection
        )
        == ()
    )


def test_review_requires_reason() -> None:
    connection = make_connection()
    insert_candidate(connection)

    candidate = load_review_candidates(
        connection
    )[0]

    with pytest.raises(
        ValueError,
        match="explicit reason",
    ):
        record_candidate_review(
            connection=connection,
            candidate=candidate,
            decision=SemanticDecision.INCLUDED,
            reason="   ",
            reviewed_at=NOW,
        )


def test_ineligible_checkpoint_cannot_be_reviewed() -> None:
    connection = make_connection()

    insert_candidate(
        connection,
        eligible=False,
    )

    connection.execute(
        """
        UPDATE machine_eligibility
        SET eligible_for_review = 1
        """
    )

    candidate = load_review_candidates(
        connection
    )[0]

    connection.execute(
        """
        UPDATE machine_eligibility
        SET eligible_for_review = 0
        """
    )
    connection.commit()

    with pytest.raises(
        RuntimeError,
        match="not eligible",
    ):
        record_candidate_review(
            connection=connection,
            candidate=candidate,
            decision=SemanticDecision.INCLUDED,
            reason="reason",
            reviewed_at=NOW,
        )


def test_snapshot_mismatch_fails_closed() -> None:
    connection = make_connection()
    insert_candidate(connection)

    candidate = load_review_candidates(
        connection
    )[0]

    connection.execute(
        """
        UPDATE machine_eligibility
        SET snapshot_id = 'different-snapshot'
        """
    )
    connection.commit()

    with pytest.raises(
        RuntimeError,
        match="snapshot",
    ):
        record_candidate_review(
            connection=connection,
            candidate=candidate,
            decision=SemanticDecision.INCLUDED,
            reason="reason",
            reviewed_at=NOW,
        )


def test_decision_keys_have_expected_semantics() -> None:
    assert (
        DECISION_BY_CHOICE["i"]
        == SemanticDecision.INCLUDED
    )
    assert (
        DECISION_BY_CHOICE["a"]
        == SemanticDecision.EXCLUDED_AMBIGUOUS
    )
    assert (
        DECISION_BY_CHOICE["d"]
        == SemanticDecision.EXCLUDED_DUPLICATE
    )
    assert (
        DECISION_BY_CHOICE["e"]
        == (
            SemanticDecision
            .EXCLUDED_EFFECTIVELY_RESOLVED
        )
    )
    assert (
        DECISION_BY_CHOICE["c"]
        == SemanticDecision.EXCLUDED_CATEGORY
    )
