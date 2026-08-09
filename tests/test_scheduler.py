import sqlite3
from datetime import UTC, datetime, timedelta

import httpx

from forecast_ledger.checkpoint_ledger import (
    CheckpointStatus,
    create_checkpoint_record,
    initialize_checkpoint_ledger,
)
from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import (
    MarketSnapshot,
)
from forecast_ledger.eligibility_store import (
    initialize_eligibility_store,
)
from forecast_ledger.polymarket import (
    FetchedMarketSnapshot,
)
from forecast_ledger.registry import (
    PROTOCOL_VERSION,
    TrackedMarket,
)
from forecast_ledger.scheduler import (
    CHECKPOINT_WINDOW,
    run_scheduler_iteration,
)
from forecast_ledger.snapshot_store import (
    initialize_snapshot_store,
    record_market_snapshot,
)

NOW = datetime(
    2026,
    8,
    9,
    14,
    tzinfo=UTC,
)


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    initialize_checkpoint_ledger(
        connection
    )
    initialize_snapshot_store(
        connection
    )
    initialize_eligibility_store(
        connection
    )

    return connection


def tracked_market(
    market_id: str,
    close_time: datetime | None = None,
) -> TrackedMarket:
    if close_time is None:
        close_time = (
            NOW
            + timedelta(days=7)
        )

    return TrackedMarket(
        market_id=market_id,
        question=f"Question {market_id}?",
        resolution_rules=(
            "Resolves YES if event occurs."
        ),
        close_time=close_time,
        yes_token_id=f"yes-{market_id}",
        no_token_id=f"no-{market_id}",
        event_id=f"event-{market_id}",
        event_title=f"Event {market_id}",
        event_slug=f"event-{market_id}",
        categories=("technology",),
        tag_slugs=("technology",),
        first_seen_at=(
            NOW - timedelta(days=10)
        ),
        protocol_version=PROTOCOL_VERSION,
    )


def fetched_snapshot(
    market_id: str,
) -> FetchedMarketSnapshot:
    snapshot = MarketSnapshot(
        snapshot_id=(
            f"{market_id}:{NOW.isoformat()}"
        ),
        market_id=market_id,
        observed_at=NOW,
        yes_bid=0.20,
        yes_ask=0.22,
        no_bid=0.78,
        no_ask=0.80,
    )

    return FetchedMarketSnapshot(
        snapshot=snapshot,
        yes_book={
            "bids": [{"price": "0.20"}],
            "asks": [{"price": "0.22"}],
        },
        no_book={
            "bids": [{"price": "0.78"}],
            "asks": [{"price": "0.80"}],
        },
        no_book_error=None,
    )


def test_running_twice_is_idempotent() -> None:
    connection = make_connection()
    market = tracked_market("m1")

    calls = []

    def fetch(_market):
        calls.append(
            _market.market_id
        )
        return fetched_snapshot(
            _market.market_id
        )

    first = run_scheduler_iteration(
        connection=connection,
        tracked_markets=(market,),
        evaluated_at=NOW,
        snapshot_fetcher=fetch,
    )

    second = run_scheduler_iteration(
        connection=connection,
        tracked_markets=(market,),
        evaluated_at=NOW,
        snapshot_fetcher=fetch,
    )

    assert first.snapshots_created == 1
    assert second.snapshots_created == 0

    assert calls == ["m1"]

    assert connection.execute(
        """
        SELECT COUNT(*)
        FROM checkpoint_records
        """
    ).fetchone()[0] == 1

    assert connection.execute(
        """
        SELECT COUNT(*)
        FROM market_snapshots
        """
    ).fetchone()[0] == 1

    assert connection.execute(
        """
        SELECT COUNT(*)
        FROM machine_eligibility
        """
    ).fetchone()[0] == 1


def test_expired_pending_checkpoint_is_closed() -> None:
    connection = make_connection()

    market = tracked_market(
        "m1",
        close_time=(
            NOW + timedelta(days=30)
        ),
    )

    scheduled = (
        NOW - timedelta(days=1)
    )

    create_checkpoint_record(
        connection=connection,
        market_id="m1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=scheduled,
        window_start=(
            scheduled
            - CHECKPOINT_WINDOW
        ),
        window_end=(
            scheduled
            + CHECKPOINT_WINDOW
        ),
        status=CheckpointStatus.PENDING,
        created_at=scheduled,
        protocol_version=PROTOCOL_VERSION,
    )

    report = run_scheduler_iteration(
        connection=connection,
        tracked_markets=(market,),
        evaluated_at=NOW,
        snapshot_fetcher=lambda _: (
            fetched_snapshot("m1")
        ),
    )

    assert (
        report.stale_pending_closed
        == 1
    )

    status = connection.execute(
        """
        SELECT status
        FROM checkpoint_records
        WHERE market_id = 'm1'
        """
    ).fetchone()[0]

    assert (
        status
        == CheckpointStatus.MARKET_DATA_FAILURE.value
    )


def test_existing_snapshot_is_never_refetched() -> None:
    connection = make_connection()

    market = tracked_market(
        "m1"
    )

    create_checkpoint_record(
        connection=connection,
        market_id="m1",
        checkpoint=Checkpoint.DAYS_7,
        scheduled_at=NOW,
        window_start=(
            NOW - CHECKPOINT_WINDOW
        ),
        window_end=(
            NOW + CHECKPOINT_WINDOW
        ),
        status=CheckpointStatus.PENDING,
        created_at=NOW,
        protocol_version=PROTOCOL_VERSION,
    )

    fetched = fetched_snapshot(
        "m1"
    )

    record_market_snapshot(
        connection=connection,
        snapshot=fetched.snapshot,
        checkpoint=Checkpoint.DAYS_7,
        raw_yes_book=fetched.yes_book,
        raw_no_book=fetched.no_book,
        no_book_error=None,
        protocol_version=PROTOCOL_VERSION,
    )

    def forbidden_fetch(_market):
        raise AssertionError(
            "Existing snapshot was refetched."
        )

    report = run_scheduler_iteration(
        connection=connection,
        tracked_markets=(market,),
        evaluated_at=NOW,
        snapshot_fetcher=forbidden_fetch,
    )

    assert report.snapshots_created == 0
    assert (
        report.eligibility_decisions_created
        == 1
    )


def test_one_fetch_failure_does_not_abort_sweep() -> None:
    connection = make_connection()

    bad = tracked_market("bad")
    good = tracked_market("good")

    def fetch(market):
        if market.market_id == "bad":
            request = httpx.Request(
                "GET",
                "https://example.com/book",
            )
            raise httpx.ReadTimeout(
                "temporary market-data failure",
                request=request,
            )

        return fetched_snapshot(
            market.market_id
        )

    report = run_scheduler_iteration(
        connection=connection,
        tracked_markets=(
            bad,
            good,
        ),
        evaluated_at=NOW,
        snapshot_fetcher=fetch,
    )

    assert len(
        report.fetch_failures
    ) == 1

    assert (
        report.fetch_failures[0].market_id
        == "bad"
    )

    assert report.snapshots_created == 1

    good_snapshot_count = (
        connection.execute(
            """
            SELECT COUNT(*)
            FROM market_snapshots
            WHERE market_id = 'good'
            """
        ).fetchone()[0]
    )

    bad_snapshot_count = (
        connection.execute(
            """
            SELECT COUNT(*)
            FROM market_snapshots
            WHERE market_id = 'bad'
            """
        ).fetchone()[0]
    )

    assert good_snapshot_count == 1
    assert bad_snapshot_count == 0

    bad_status = connection.execute(
        """
        SELECT status
        FROM checkpoint_records
        WHERE market_id = 'bad'
        """
    ).fetchone()[0]

    assert (
        bad_status
        == CheckpointStatus.PENDING.value
    )
