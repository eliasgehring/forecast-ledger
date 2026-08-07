import sqlite3
from datetime import UTC, datetime

import pytest

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.semantic_review import (
    SemanticDecision,
    initialize_semantic_reviews,
    load_semantic_reviews,
    record_semantic_review,
)

REVIEWED_AT = datetime(
    2026,
    8,
    7,
    11,
    15,
    tzinfo=UTC,
)


def test_semantic_review_is_persisted() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_semantic_reviews(connection)

    created = record_semantic_review(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        decision=SemanticDecision.INCLUDED,
        reason="Resolution semantics are sufficiently objective.",
        reviewed_at=REVIEWED_AT,
    )

    reviews = load_semantic_reviews(connection)

    assert created is True
    assert len(reviews) == 1
    assert reviews[0].decision == SemanticDecision.INCLUDED


def test_identical_review_is_idempotent() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_semantic_reviews(connection)

    kwargs = {
        "connection": connection,
        "market_id": "market-1",
        "checkpoint": Checkpoint.DAYS_7,
        "decision": SemanticDecision.INCLUDED,
        "reason": "Valid market.",
        "reviewed_at": REVIEWED_AT,
    }

    assert record_semantic_review(**kwargs) is True
    assert record_semantic_review(**kwargs) is False


def test_semantic_decision_cannot_be_silently_changed() -> None:
    connection = sqlite3.connect(":memory:")
    initialize_semantic_reviews(connection)

    record_semantic_review(
        connection=connection,
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        decision=SemanticDecision.INCLUDED,
        reason="Valid market.",
        reviewed_at=REVIEWED_AT,
    )

    with pytest.raises(
        RuntimeError,
        match="different decision",
    ):
        record_semantic_review(
            connection=connection,
            market_id="market-1",
            checkpoint=Checkpoint.DAYS_7,
            decision=SemanticDecision.EXCLUDED_DUPLICATE,
            reason="Changed my mind.",
            reviewed_at=REVIEWED_AT,
        )
