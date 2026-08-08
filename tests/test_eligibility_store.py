import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import Market, MarketSnapshot
from forecast_ledger.eligibility_store import (
    EligibilityConflictError,
    initialize_eligibility_store,
    load_machine_eligibility,
    record_machine_eligibility,
)

OBSERVED_AT = datetime(
    2026,
    8,
    7,
    12,
    tzinfo=UTC,
)


def make_market() -> Market:
    return Market(
        market_id="m1",
        question="Will X happen?",
        resolution_rules="YES if X happens.",
        close_time=OBSERVED_AT + timedelta(days=3),
        yes_token_id="yes1",
        no_token_id="no1",
    )


def make_snapshot(
    *,
    yes_bid: float = 0.40,
    yes_ask: float = 0.44,
    snapshot_id: str = "s1",
) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id=snapshot_id,
        market_id="m1",
        observed_at=OBSERVED_AT,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=1.0 - yes_ask,
        no_ask=1.0 - yes_bid,
    )


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    connection.execute(
        """
        CREATE TABLE market_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL
        )
        """
    )

    initialize_eligibility_store(
        connection
    )

    return connection


def persist_snapshot(
    connection: sqlite3.Connection,
    snapshot: MarketSnapshot,
) -> None:
    connection.execute(
        """
        INSERT INTO market_snapshots (
            snapshot_id,
            market_id,
            checkpoint,
            protocol_version
        )
        VALUES (?, ?, '3d', 'v0.2')
        """,
        (
            snapshot.snapshot_id,
            snapshot.market_id,
        ),
    )

    connection.commit()


def test_records_eligible_checkpoint() -> None:
    connection = make_connection()
    market = make_market()
    snapshot = make_snapshot()

    persist_snapshot(
        connection,
        snapshot,
    )

    created = record_machine_eligibility(
        connection=connection,
        market=market,
        snapshot=snapshot,
        checkpoint=Checkpoint.DAYS_3,
        evaluated_at=OBSERVED_AT
        + timedelta(seconds=1),
    )

    assert created is True

    decisions = load_machine_eligibility(
        connection
    )

    assert len(decisions) == 1
    assert decisions[0].eligible_for_review is True
    assert decisions[0].rejection_reasons == ()


def test_records_exact_rejection_reasons() -> None:
    connection = make_connection()
    market = make_market()

    snapshot = make_snapshot(
        yes_bid=0.01,
        yes_ask=0.02,
    )

    persist_snapshot(
        connection,
        snapshot,
    )

    record_machine_eligibility(
        connection=connection,
        market=market,
        snapshot=snapshot,
        checkpoint=Checkpoint.DAYS_3,
        evaluated_at=OBSERVED_AT
        + timedelta(seconds=1),
    )

    decision = load_machine_eligibility(
        connection
    )[0]

    assert decision.eligible_for_review is False
    assert decision.rejection_reasons == (
        "market_probability_below_0.05",
    )


def test_requires_persisted_snapshot() -> None:
    connection = make_connection()

    with pytest.raises(
        ValueError,
        match="persisted market snapshot",
    ):
        record_machine_eligibility(
            connection=connection,
            market=make_market(),
            snapshot=make_snapshot(),
            checkpoint=Checkpoint.DAYS_3,
            evaluated_at=OBSERVED_AT
            + timedelta(seconds=1),
        )


def test_cannot_claim_evaluation_before_snapshot() -> None:
    connection = make_connection()
    snapshot = make_snapshot()

    persist_snapshot(
        connection,
        snapshot,
    )

    with pytest.raises(
        ValueError,
        match="before",
    ):
        record_machine_eligibility(
            connection=connection,
            market=make_market(),
            snapshot=snapshot,
            checkpoint=Checkpoint.DAYS_3,
            evaluated_at=OBSERVED_AT
            - timedelta(seconds=1),
        )


def test_identical_rerun_is_idempotent() -> None:
    connection = make_connection()
    market = make_market()
    snapshot = make_snapshot()

    persist_snapshot(
        connection,
        snapshot,
    )

    first_time = (
        OBSERVED_AT
        + timedelta(seconds=1)
    )

    assert record_machine_eligibility(
        connection=connection,
        market=market,
        snapshot=snapshot,
        checkpoint=Checkpoint.DAYS_3,
        evaluated_at=first_time,
    )

    assert not record_machine_eligibility(
        connection=connection,
        market=market,
        snapshot=snapshot,
        checkpoint=Checkpoint.DAYS_3,
        evaluated_at=first_time
        + timedelta(hours=1),
    )

    decision = load_machine_eligibility(
        connection
    )[0]

    assert decision.evaluated_at == first_time


def test_different_snapshot_cannot_replace_decision() -> None:
    connection = make_connection()
    market = make_market()

    first = make_snapshot(
        snapshot_id="s1",
    )

    second = make_snapshot(
        snapshot_id="s2",
    )

    persist_snapshot(
        connection,
        first,
    )

    persist_snapshot(
        connection,
        second,
    )

    record_machine_eligibility(
        connection=connection,
        market=market,
        snapshot=first,
        checkpoint=Checkpoint.DAYS_3,
        evaluated_at=OBSERVED_AT
        + timedelta(seconds=1),
    )

    with pytest.raises(
        EligibilityConflictError
    ):
        record_machine_eligibility(
            connection=connection,
            market=market,
            snapshot=second,
            checkpoint=Checkpoint.DAYS_3,
            evaluated_at=OBSERVED_AT
            + timedelta(seconds=2),
        )
