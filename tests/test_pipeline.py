import sqlite3
from datetime import UTC, datetime

import pytest

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.forecasting import ForecastCondition
from forecast_ledger.pipeline import (
    AttemptState,
    PipelineStateError,
    PipelineTarget,
    _condition_market_probability,
    _next_retrieval_attempt,
    _packet_id,
    load_targets,
)
from forecast_ledger.registry import PROTOCOL_VERSION

OBSERVED_AT = datetime(
    2026,
    8,
    7,
    12,
    0,
    tzinfo=UTC,
)


def make_target() -> PipelineTarget:
    return PipelineTarget(
        market_id="market-1",
        checkpoint=Checkpoint.DAYS_7,
        question="Will X happen?",
        resolution_rules="Resolve YES if X happens.",
        snapshot_id="snapshot-1",
        observed_at=OBSERVED_AT,
        yes_bid=0.30,
        yes_ask=0.34,
    )


def test_only_market_aware_condition_receives_market_probability():
    target = make_target()

    assert (
        _condition_market_probability(
            ForecastCondition.DIRECT,
            target,
        )
        is None
    )

    assert (
        _condition_market_probability(
            ForecastCondition.STRUCTURED_INDEPENDENT,
            target,
        )
        is None
    )

    assert _condition_market_probability(
        ForecastCondition.STRUCTURED_MARKET_AWARE,
        target,
    ) == pytest.approx(0.32)


def test_first_retrieval_attempt_is_one():
    assert _next_retrieval_attempt(()) == 1


def test_retryable_retrieval_failure_advances_sequentially():
    attempts = (
        AttemptState(
            attempt_number=1,
            status="failed",
            error_type="RetrievalOutputError",
        ),
    )

    assert _next_retrieval_attempt(attempts) == 2


def test_authentication_failure_is_not_retried():
    attempts = (
        AttemptState(
            attempt_number=1,
            status="failed",
            error_type="AuthenticationError",
        ),
    )

    assert _next_retrieval_attempt(attempts) is None


def test_started_retrieval_fails_closed():
    attempts = (
        AttemptState(
            attempt_number=1,
            status="started",
            error_type=None,
        ),
    )

    with pytest.raises(PipelineStateError):
        _next_retrieval_attempt(attempts)


def test_succeeded_retrieval_without_packet_fails_closed():
    attempts = (
        AttemptState(
            attempt_number=1,
            status="succeeded",
            error_type=None,
        ),
    )

    with pytest.raises(PipelineStateError):
        _next_retrieval_attempt(attempts)


def test_retrieval_never_exceeds_three_attempts():
    attempts = (
        AttemptState(1, "failed", "RetrievalOutputError"),
        AttemptState(2, "failed", "RateLimitError"),
        AttemptState(3, "failed", "APIConnectionError"),
    )

    assert _next_retrieval_attempt(attempts) is None


def test_packet_id_is_deterministic_and_membership_sensitive():
    target = make_target()

    first = _packet_id(
        target,
        "resp-1",
        ("evidence-a", "evidence-b"),
    )

    second = _packet_id(
        target,
        "resp-1",
        ("evidence-a", "evidence-b"),
    )

    reordered = _packet_id(
        target,
        "resp-1",
        ("evidence-b", "evidence-a"),
    )

    assert first == second
    assert first != reordered


def test_load_targets_requires_machine_eligibility_and_inclusion():
    connection = sqlite3.connect(":memory:")

    connection.executescript(
        """
        CREATE TABLE tracked_markets (
            market_id TEXT,
            question TEXT,
            resolution_rules TEXT,
            protocol_version TEXT
        );

        CREATE TABLE semantic_reviews (
            market_id TEXT,
            checkpoint TEXT,
            protocol_version TEXT,
            decision TEXT
        );

        CREATE TABLE machine_eligibility (
            market_id TEXT,
            checkpoint TEXT,
            protocol_version TEXT,
            snapshot_id TEXT,
            eligible_for_review INTEGER
        );

        CREATE TABLE market_snapshots (
            snapshot_id TEXT,
            market_id TEXT,
            checkpoint TEXT,
            protocol_version TEXT,
            observed_at TEXT,
            yes_bid REAL,
            yes_ask REAL
        );
        """
    )

    connection.execute(
        """
        INSERT INTO tracked_markets
        VALUES ('included', 'Included?', 'rules', ?)
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO tracked_markets
        VALUES ('excluded', 'Excluded?', 'rules', ?)
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO tracked_markets
        VALUES ('ineligible', 'Ineligible?', 'rules', ?)
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO semantic_reviews
        VALUES ('included', '7d', ?, 'included')
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO semantic_reviews
        VALUES (
            'excluded',
            '7d',
            ?,
            'excluded_ambiguous'
        )
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO semantic_reviews
        VALUES ('ineligible', '7d', ?, 'included')
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO machine_eligibility
        VALUES (
            'included',
            '7d',
            ?,
            'snapshot-included',
            1
        )
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO machine_eligibility
        VALUES (
            'excluded',
            '7d',
            ?,
            'snapshot-excluded',
            1
        )
        """,
        (PROTOCOL_VERSION,),
    )

    connection.execute(
        """
        INSERT INTO machine_eligibility
        VALUES (
            'ineligible',
            '7d',
            ?,
            'snapshot-ineligible',
            0
        )
        """,
        (PROTOCOL_VERSION,),
    )

    for market_id in (
        "included",
        "excluded",
        "ineligible",
    ):
        connection.execute(
            """
            INSERT INTO market_snapshots
            VALUES (?, ?, '7d', ?, ?, 0.30, 0.34)
            """,
            (
                f"snapshot-{market_id}",
                market_id,
                PROTOCOL_VERSION,
                OBSERVED_AT.isoformat(),
            ),
        )

    targets = load_targets(connection)

    assert len(targets) == 1
    assert targets[0].market_id == "included"
    assert targets[0].snapshot_id == "snapshot-included"

    connection.close()


def test_source_verification_http_failure_is_retryable():
    attempts = (
        AttemptState(
            attempt_number=1,
            status="failed",
            error_type="SourceVerificationHTTPError",
        ),
    )

    assert _next_retrieval_attempt(attempts) == 2
