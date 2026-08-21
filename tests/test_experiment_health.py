import pytest

from forecast_ledger.experiment_health import (
    summarize_experiment_health,
)


def test_health_preserves_checkpoint_and_market_counts():
    rows = [
        {
            "market_id": "m1",
            "checkpoint": "7d",
            "question": "One",
            "pipeline_status": "matched",
            "retrieval_status": "succeeded",
            "condition_count": 3,
        },
        {
            "market_id": "m2",
            "checkpoint": "7d",
            "question": "Two",
            "pipeline_status": "blocked",
            "retrieval_status": "failed",
            "retrieval_error_type": (
                "RetrievalOutputError"
            ),
            "retrieval_attempt_number": 3,
            "condition_count": 0,
        },
        {
            "market_id": "m3",
            "checkpoint": "7d",
            "question": "Three",
            "pipeline_status": "interrupted",
            "retrieval_status": "started",
            "retrieval_attempt_number": 3,
            "condition_count": 0,
        },
        {
            "market_id": "m4",
            "checkpoint": "7d",
            "question": "Four",
            "pipeline_status": (
                "partial_forecast"
            ),
            "retrieval_status": "succeeded",
            "has_valid_packet": True,
            "condition_count": 2,
        },
        {
            "market_id": "m1",
            "checkpoint": "14d",
            "question": "One",
            "pipeline_status": "matched",
            "retrieval_status": "succeeded",
            "condition_count": 3,
        },
        {
            "market_id": "m5",
            "checkpoint": "14d",
            "question": "Five",
            "pipeline_status": "blocked",
            "retrieval_status": "failed",
            "retrieval_error_type": (
                "AuthenticationError"
            ),
            "retrieval_attempt_number": 1,
            "condition_count": 0,
        },
    ]

    health = summarize_experiment_health(
        rows,
        primary_resolved_scored=1,
    )

    assert health.overall.checkpoints == 6
    assert health.overall.unique_markets == 5
    assert health.overall.matched == 2
    assert health.overall.blocked == 2
    assert health.overall.interrupted == 1
    assert health.overall.partial_forecast == 1
    assert health.overall.other == 0

    assert health.primary_7d.checkpoints == 4
    assert health.primary_7d.unique_markets == 4
    assert health.primary_7d.matched == 1
    assert health.primary_resolved_scored == 1

    assert [
        (
            item.name,
            item.count,
        )
        for item in (
            health.retrieval_failure_types
        )
    ] == [
        (
            "AuthenticationError",
            1,
        ),
        (
            "RetrievalOutputError",
            1,
        ),
    ]

    assert len(
        health.nonmatched_checkpoints
    ) == 4


def test_health_rejects_more_scored_than_matched():
    rows = [
        {
            "market_id": "m1",
            "checkpoint": "7d",
            "pipeline_status": "matched",
        }
    ]

    with pytest.raises(
        ValueError,
        match=(
            "cannot exceed matched"
        ),
    ):
        summarize_experiment_health(
            rows,
            primary_resolved_scored=2,
        )


def test_health_handles_empty_experiment():
    health = summarize_experiment_health(
        [],
        primary_resolved_scored=0,
    )

    assert health.overall.checkpoints == 0
    assert health.overall.unique_markets == 0
    assert health.overall.matched == 0
    assert health.primary_7d.checkpoints == 0
    assert health.primary_resolved_scored == 0
    assert (
        health.nonmatched_checkpoints
        == ()
    )
