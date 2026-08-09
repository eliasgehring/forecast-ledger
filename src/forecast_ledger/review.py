from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.registry import PROTOCOL_VERSION
from forecast_ledger.semantic_review import (
    SemanticDecision,
    initialize_semantic_reviews,
    record_semantic_review,
)


@dataclass(frozen=True)
class ReviewCandidate:
    market_id: str
    checkpoint: Checkpoint
    question: str
    resolution_rules: str
    categories: tuple[str, ...]
    snapshot_id: str
    observed_at: datetime
    yes_bid: float
    yes_ask: float

    @property
    def market_probability(self) -> float:
        return (
            self.yes_bid
            + self.yes_ask
        ) / 2.0

    @property
    def yes_spread(self) -> float:
        return (
            self.yes_ask
            - self.yes_bid
        )


DECISION_BY_CHOICE = {
    "i": SemanticDecision.INCLUDED,
    "a": SemanticDecision.EXCLUDED_AMBIGUOUS,
    "d": SemanticDecision.EXCLUDED_DUPLICATE,
    "e": SemanticDecision.EXCLUDED_EFFECTIVELY_RESOLVED,
    "c": SemanticDecision.EXCLUDED_CATEGORY,
}


def load_review_candidates(
    connection: sqlite3.Connection,
    protocol_version: str = PROTOCOL_VERSION,
) -> tuple[ReviewCandidate, ...]:
    rows = connection.execute(
        """
        SELECT
            me.market_id,
            me.checkpoint,
            tm.question,
            tm.resolution_rules,
            tm.categories_json,
            me.snapshot_id,
            ms.observed_at,
            ms.yes_bid,
            ms.yes_ask

        FROM machine_eligibility AS me

        JOIN tracked_markets AS tm
          ON tm.market_id = me.market_id
         AND tm.protocol_version =
             me.protocol_version

        JOIN market_snapshots AS ms
          ON ms.snapshot_id = me.snapshot_id
         AND ms.market_id = me.market_id
         AND ms.checkpoint = me.checkpoint
         AND ms.protocol_version =
             me.protocol_version

        LEFT JOIN semantic_reviews AS sr
          ON sr.market_id = me.market_id
         AND sr.checkpoint = me.checkpoint
         AND sr.protocol_version =
             me.protocol_version

        WHERE me.protocol_version = ?
          AND me.eligible_for_review = 1
          AND sr.market_id IS NULL

        ORDER BY
            me.evaluated_at,
            me.market_id,
            me.checkpoint
        """,
        (protocol_version,),
    ).fetchall()

    return tuple(
        ReviewCandidate(
            market_id=row[0],
            checkpoint=Checkpoint(row[1]),
            question=row[2],
            resolution_rules=row[3],
            categories=tuple(
                json.loads(row[4])
            ),
            snapshot_id=row[5],
            observed_at=datetime.fromisoformat(
                row[6]
            ),
            yes_bid=float(row[7]),
            yes_ask=float(row[8]),
        )
        for row in rows
    )


def record_candidate_review(
    connection: sqlite3.Connection,
    candidate: ReviewCandidate,
    decision: SemanticDecision,
    reason: str,
    reviewed_at: datetime,
    protocol_version: str = PROTOCOL_VERSION,
) -> bool:
    clean_reason = reason.strip()

    if not clean_reason:
        raise ValueError(
            "Semantic review requires an explicit reason."
        )

    row = connection.execute(
        """
        SELECT
            me.eligible_for_review,
            me.snapshot_id,
            sr.decision

        FROM machine_eligibility AS me

        LEFT JOIN semantic_reviews AS sr
          ON sr.market_id = me.market_id
         AND sr.checkpoint = me.checkpoint
         AND sr.protocol_version =
             me.protocol_version

        WHERE me.market_id = ?
          AND me.checkpoint = ?
          AND me.protocol_version = ?
        """,
        (
            candidate.market_id,
            candidate.checkpoint.value,
            protocol_version,
        ),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "Machine eligibility decision is missing."
        )

    if not bool(row[0]):
        raise RuntimeError(
            "Checkpoint is not eligible for semantic review."
        )

    if row[1] != candidate.snapshot_id:
        raise RuntimeError(
            "Review candidate snapshot does not match "
            "machine eligibility."
        )

    if row[2] is not None:
        raise RuntimeError(
            "Semantic review already exists."
        )

    return record_semantic_review(
        connection=connection,
        market_id=candidate.market_id,
        checkpoint=candidate.checkpoint,
        decision=decision,
        reason=clean_reason,
        reviewed_at=reviewed_at,
        protocol_version=protocol_version,
    )


def _print_candidate(
    candidate: ReviewCandidate,
    index: int,
    total: int,
) -> None:
    print()
    print("=" * 80)
    print(f"SEMANTIC REVIEW {index} / {total}")
    print("=" * 80)
    print()
    print("Market:", candidate.market_id)
    print("Checkpoint:", candidate.checkpoint.value)
    print()
    print(candidate.question)
    print()
    print(
        "Frozen probability:",
        f"{candidate.market_probability:.1%}",
    )
    print(
        "YES spread:",
        f"{candidate.yes_spread:.1%}",
    )
    print(
        "Observed at:",
        candidate.observed_at.isoformat(),
    )
    print(
        "Snapshot:",
        candidate.snapshot_id,
    )
    print(
        "Categories:",
        ", ".join(candidate.categories),
    )
    print()
    print("RESOLUTION RULES")
    print("----------------")
    print(candidate.resolution_rules)
    print()
    print("MACHINE ELIGIBILITY")
    print("-------------------")
    print("ELIGIBLE")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Review machine-eligible Forecast Ledger "
            "checkpoints."
        )
    )

    parser.add_argument(
        "--db",
        default="data/forecast_ledger.db",
    )

    parser.add_argument(
        "--market-id",
        default=None,
    )

    parser.add_argument(
        "--checkpoint",
        choices=[
            checkpoint.value
            for checkpoint in Checkpoint
        ],
        default=None,
    )

    args = parser.parse_args()

    db_path = Path(args.db)

    if not db_path.exists():
        raise FileNotFoundError(db_path)

    connection = sqlite3.connect(db_path)

    try:
        initialize_semantic_reviews(
            connection
        )

        candidates = load_review_candidates(
            connection
        )

        if args.market_id is not None:
            candidates = tuple(
                candidate
                for candidate in candidates
                if (
                    candidate.market_id
                    == args.market_id
                )
            )

        if args.checkpoint is not None:
            checkpoint = Checkpoint(
                args.checkpoint
            )

            candidates = tuple(
                candidate
                for candidate in candidates
                if (
                    candidate.checkpoint
                    == checkpoint
                )
            )

        if not candidates:
            print(
                "Semantic review queue is empty."
            )
            return

        for index, candidate in enumerate(
            candidates,
            start=1,
        ):
            _print_candidate(
                candidate,
                index,
                len(candidates),
            )

            while True:
                print(
                    "[i] include"
                )
                print(
                    "[a] exclude: ambiguous"
                )
                print(
                    "[d] exclude: duplicate"
                )
                print(
                    "[e] exclude: effectively resolved"
                )
                print(
                    "[c] exclude: category"
                )
                print(
                    "[s] skip"
                )
                print(
                    "[q] quit"
                )

                choice = input(
                    "\nDecision: "
                ).strip().lower()

                if choice == "q":
                    print(
                        "Review session ended."
                    )
                    return

                if choice == "s":
                    print(
                        "SKIPPED: no state written."
                    )
                    break

                decision = DECISION_BY_CHOICE.get(
                    choice
                )

                if decision is None:
                    print(
                        "Unknown decision."
                    )
                    continue

                reason = input(
                    "Reason: "
                ).strip()

                if not reason:
                    print(
                        "Reason is required."
                    )
                    continue

                created = record_candidate_review(
                    connection=connection,
                    candidate=candidate,
                    decision=decision,
                    reason=reason,
                    reviewed_at=datetime.now(UTC),
                )

                if not created:
                    raise RuntimeError(
                        "Review unexpectedly already existed."
                    )

                print()
                print(
                    "RECORDED:",
                    decision.value,
                )
                break

    finally:
        connection.close()


if __name__ == "__main__":
    main()
