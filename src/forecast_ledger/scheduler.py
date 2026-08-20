from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from forecast_ledger import pipeline
from forecast_ledger.checkpoint_ledger import (
    CheckpointStatus,
    create_checkpoint_record,
    initialize_checkpoint_ledger,
    load_checkpoint_records,
    mark_expired_pending_market_data_failure,
)
from forecast_ledger.checkpoints import (
    Checkpoint,
    find_due_checkpoint,
)
from forecast_ledger.domain import Market
from forecast_ledger.eligibility_store import (
    initialize_eligibility_store,
    load_machine_eligibility,
    record_machine_eligibility,
)
from forecast_ledger.polymarket import (
    FetchedMarketSnapshot,
    fetch_market_snapshot_with_raw,
)
from forecast_ledger.registry import (
    PROTOCOL_VERSION,
    TrackedMarket,
    load_tracked_markets,
)
from forecast_ledger.semantic_review import (
    load_semantic_reviews,
)
from forecast_ledger.snapshot_store import (
    initialize_snapshot_store,
    load_market_snapshots,
    record_market_snapshot,
)

CHECKPOINT_WINDOW = timedelta(hours=6)

SnapshotFetcher = Callable[
    [Market],
    FetchedMarketSnapshot,
]


@dataclass(frozen=True)
class FetchFailure:
    market_id: str
    checkpoint: Checkpoint
    error_type: str
    error_message: str


@dataclass(frozen=True)
class SchedulerReport:
    due_checkpoints: int
    checkpoint_records_created: int
    stale_pending_closed: int
    snapshots_created: int
    eligibility_decisions_created: int
    fetch_failures: tuple[FetchFailure, ...]


@dataclass(frozen=True)
class ReviewQueueItem:
    market_id: str
    checkpoint: Checkpoint
    snapshot_id: str


def _as_market(
    tracked_market: TrackedMarket,
) -> Market:
    return Market(
        market_id=tracked_market.market_id,
        question=tracked_market.question,
        resolution_rules=tracked_market.resolution_rules,
        close_time=tracked_market.close_time,
        yes_token_id=tracked_market.yes_token_id,
        no_token_id=tracked_market.no_token_id,
    )


def _key(
    market_id: str,
    checkpoint: Checkpoint,
) -> tuple[str, Checkpoint, str]:
    return (
        market_id,
        checkpoint,
        PROTOCOL_VERSION,
    )


def run_scheduler_iteration(
    connection: sqlite3.Connection,
    tracked_markets: tuple[TrackedMarket, ...],
    evaluated_at: datetime,
    snapshot_fetcher: SnapshotFetcher = (
        fetch_market_snapshot_with_raw
    ),
) -> SchedulerReport:
    if evaluated_at.tzinfo is None:
        raise ValueError(
            "evaluated_at must be timezone-aware."
        )

    checkpoint_records = {
        _key(
            record.market_id,
            record.checkpoint,
        ): record
        for record in load_checkpoint_records(
            connection
        )
        if (
            record.protocol_version
            == PROTOCOL_VERSION
        )
    }

    snapshots = {
        _key(
            stored.snapshot.market_id,
            stored.checkpoint,
        ): stored
        for stored in load_market_snapshots(
            connection
        )
        if (
            stored.protocol_version
            == PROTOCOL_VERSION
        )
    }

    eligibility = {
        _key(
            decision.market_id,
            decision.checkpoint,
        ): decision
        for decision in load_machine_eligibility(
            connection,
            protocol_version=PROTOCOL_VERSION,
        )
    }

    stale_pending_closed = 0

    for key, record in tuple(
        checkpoint_records.items()
    ):
        if (
            record.status
            == CheckpointStatus.PENDING
            and record.window_end
            < evaluated_at
        ):
            changed = (
                mark_expired_pending_market_data_failure(
                    connection=connection,
                    market_id=record.market_id,
                    checkpoint=record.checkpoint,
                    evaluated_at=evaluated_at,
                    protocol_version=PROTOCOL_VERSION,
                )
            )

            stale_pending_closed += int(
                changed
            )

    due_checkpoints = 0
    checkpoint_records_created = 0
    snapshots_created = 0
    eligibility_decisions_created = 0
    fetch_failures: list[FetchFailure] = []

    for tracked_market in tracked_markets:
        if (
            tracked_market.protocol_version
            != PROTOCOL_VERSION
        ):
            continue

        due = find_due_checkpoint(
            close_time=tracked_market.close_time,
            observed_at=evaluated_at,
        )

        if due is None:
            continue

        due_checkpoints += 1

        key = _key(
            tracked_market.market_id,
            due.checkpoint,
        )

        record = checkpoint_records.get(
            key
        )

        if record is None:
            created = create_checkpoint_record(
                connection=connection,
                market_id=(
                    tracked_market.market_id
                ),
                checkpoint=due.checkpoint,
                scheduled_at=due.scheduled_at,
                window_start=(
                    due.scheduled_at
                    - CHECKPOINT_WINDOW
                ),
                window_end=(
                    due.scheduled_at
                    + CHECKPOINT_WINDOW
                ),
                status=CheckpointStatus.PENDING,
                created_at=evaluated_at,
                protocol_version=PROTOCOL_VERSION,
            )

            checkpoint_records_created += int(
                created
            )

        stored_snapshot = snapshots.get(
            key
        )

        market = _as_market(
            tracked_market
        )

        if stored_snapshot is not None:
            if key not in eligibility:
                created = (
                    record_machine_eligibility(
                        connection=connection,
                        market=market,
                        snapshot=(
                            stored_snapshot.snapshot
                        ),
                        checkpoint=due.checkpoint,
                        evaluated_at=evaluated_at,
                        protocol_version=(
                            PROTOCOL_VERSION
                        ),
                    )
                )

                eligibility_decisions_created += (
                    int(created)
                )

            continue

        current_status_row = (
            connection.execute(
                """
                SELECT status
                FROM checkpoint_records
                WHERE market_id = ?
                  AND checkpoint = ?
                  AND protocol_version = ?
                """,
                (
                    tracked_market.market_id,
                    due.checkpoint.value,
                    PROTOCOL_VERSION,
                ),
            ).fetchone()
        )

        if current_status_row is None:
            raise RuntimeError(
                "Checkpoint disappeared after creation."
            )

        if (
            current_status_row[0]
            != CheckpointStatus.PENDING.value
        ):
            continue

        try:
            fetched = snapshot_fetcher(
                market
            )
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            fetch_failures.append(
                FetchFailure(
                    market_id=(
                        tracked_market.market_id
                    ),
                    checkpoint=due.checkpoint,
                    error_type=(
                        type(exc).__name__
                    ),
                    error_message=str(exc),
                )
            )
            continue

        created = record_market_snapshot(
            connection=connection,
            snapshot=fetched.snapshot,
            checkpoint=due.checkpoint,
            raw_yes_book=fetched.yes_book,
            raw_no_book=fetched.no_book,
            no_book_error=(
                fetched.no_book_error
            ),
            protocol_version=PROTOCOL_VERSION,
        )

        snapshots_created += int(
            created
        )

        created = record_machine_eligibility(
            connection=connection,
            market=market,
            snapshot=fetched.snapshot,
            checkpoint=due.checkpoint,
            evaluated_at=max(
                evaluated_at,
                fetched.snapshot.observed_at,
            ),
            protocol_version=PROTOCOL_VERSION,
        )

        eligibility_decisions_created += int(
            created
        )

    return SchedulerReport(
        due_checkpoints=due_checkpoints,
        checkpoint_records_created=(
            checkpoint_records_created
        ),
        stale_pending_closed=(
            stale_pending_closed
        ),
        snapshots_created=snapshots_created,
        eligibility_decisions_created=(
            eligibility_decisions_created
        ),
        fetch_failures=tuple(
            fetch_failures
        ),
    )


def load_semantic_review_queue(
    connection: sqlite3.Connection,
) -> tuple[ReviewQueueItem, ...]:
    decisions = load_machine_eligibility(
        connection,
        protocol_version=PROTOCOL_VERSION,
    )

    reviews = load_semantic_reviews(
        connection
    )

    reviewed = {
        (
            review.market_id,
            review.checkpoint,
            review.protocol_version,
        )
        for review in reviews
    }

    queue = []

    for decision in decisions:
        key = (
            decision.market_id,
            decision.checkpoint,
            decision.protocol_version,
        )

        if (
            decision.eligible_for_review
            and key not in reviewed
        ):
            queue.append(
                ReviewQueueItem(
                    market_id=(
                        decision.market_id
                    ),
                    checkpoint=(
                        decision.checkpoint
                    ),
                    snapshot_id=(
                        decision.snapshot_id
                    ),
                )
            )

    return tuple(queue)


def run_included_forecasts(
    connection: sqlite3.Connection,
) -> None:
    targets = pipeline.load_targets(
        connection
    )

    if not targets:
        print(
            "forecast phase: no included targets"
        )
        return

    pipeline._require_clean_git()
    code_commit = pipeline._git_commit()

    print()
    print("OpenAI authentication preflight...")

    from openai import OpenAI

    client = OpenAI()
    client.models.list()

    print("preflight: OK")
    print("code commit:", code_commit)
    print(
        "protocol commit:",
        pipeline.PROTOCOL_COMMIT,
    )

    for target in targets:
        try:
            pipeline.run_target(
                connection=connection,
                client=client,
                target=target,
                code_commit=code_commit,
            )
        except pipeline.PipelineStateError as exc:
            print()
            print(
                target.market_id,
                target.checkpoint.value,
                "BLOCKED:",
                exc,
            )


def print_report(
    report: SchedulerReport,
) -> None:
    print()
    print("SCHEDULER REPORT")
    print("================")
    print(
        "due checkpoints:",
        report.due_checkpoints,
    )
    print(
        "checkpoint records created:",
        report.checkpoint_records_created,
    )
    print(
        "stale pending closed:",
        report.stale_pending_closed,
    )
    print(
        "snapshots created:",
        report.snapshots_created,
    )
    print(
        "eligibility decisions created:",
        report.eligibility_decisions_created,
    )
    print(
        "fetch failures:",
        len(report.fetch_failures),
    )

    for failure in report.fetch_failures:
        print(
            " ",
            failure.market_id,
            failure.checkpoint.value,
            failure.error_type,
            "|",
            failure.error_message,
        )


def print_review_queue(
    connection: sqlite3.Connection,
    tracked_markets: tuple[TrackedMarket, ...],
) -> None:
    queue = load_semantic_review_queue(
        connection
    )

    questions = {
        market.market_id: market.question
        for market in tracked_markets
    }

    print()
    print("SEMANTIC REVIEW QUEUE")
    print("=====================")

    for item in queue:
        print(
            item.market_id,
            item.checkpoint.value,
            "|",
            questions.get(
                item.market_id,
                "<unknown market>",
            ),
        )

    print("count:", len(queue))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run one Forecast Ledger checkpoint "
            "scheduler iteration."
        )
    )

    parser.add_argument(
        "--db",
        default="data/forecast_ledger.db",
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Create checkpoint state and fetch "
            "live snapshots."
        ),
    )

    parser.add_argument(
        "--forecasts",
        action="store_true",
        help=(
            "After checkpoint processing, run "
            "B/C/D for already INCLUDED targets."
        ),
    )

    args = parser.parse_args()

    db_path = Path(
        args.db
    )

    if not db_path.exists():
        raise FileNotFoundError(
            db_path
        )

    connection = sqlite3.connect(
        db_path
    )

    try:
        initialize_checkpoint_ledger(
            connection
        )
        initialize_snapshot_store(
            connection
        )
        initialize_eligibility_store(
            connection
        )

        tracked_markets = tuple(
            market
            for market in load_tracked_markets(
                connection
            )
            if (
                market.protocol_version
                == PROTOCOL_VERSION
            )
        )

        now = datetime.now(UTC)

        if not args.execute:
            due = sum(
                find_due_checkpoint(
                    market.close_time,
                    now,
                )
                is not None
                for market in tracked_markets
            )

            stale = sum(
                record.protocol_version
                == PROTOCOL_VERSION
                and record.status
                == CheckpointStatus.PENDING
                and record.window_end < now
                for record in load_checkpoint_records(
                    connection
                )
            )

            print(
                "Forecast Ledger scheduler dry run"
            )
            print("===============================")
            print(
                "tracked markets:",
                len(tracked_markets),
            )
            print(
                "currently due:",
                due,
            )
            print(
                "expired pending:",
                stale,
            )

            print_review_queue(
                connection,
                tracked_markets,
            )
            return

        report = run_scheduler_iteration(
            connection=connection,
            tracked_markets=tracked_markets,
            evaluated_at=now,
        )

        print_report(
            report
        )

        print_review_queue(
            connection,
            tracked_markets,
        )

        if args.forecasts:
            run_included_forecasts(
                connection
            )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
