from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from openai import OpenAI, OpenAIError

from forecast_ledger import forecast_store
from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.domain import EvidencePacket
from forecast_ledger.evidence_store import (
    PacketValidationStatus,
    load_evidence_items_for_packet,
    load_valid_packet_id_for_checkpoint,
    record_evidence_packet,
    record_packet_validation,
)
from forecast_ledger.forecasting import (
    FORECAST_MODEL,
    FORECAST_REASONING_EFFORT,
    ForecastCondition,
    ForecastOutputError,
    build_forecast_prompt,
    create_forecast,
    prompt_version_for_condition,
)
from forecast_ledger.registry import (
    PROTOCOL_COMMIT,
    PROTOCOL_VERSION,
)
from forecast_ledger.retrieval import (
    RETRIEVAL_MODEL,
    RETRIEVAL_PROMPT_VERSION,
    RetrievalOutputError,
    retrieve_evidence,
    verified_evidence_items,
)
from forecast_ledger.retrieval_store import (
    finish_retrieval_attempt_failure,
    finish_retrieval_attempt_success,
    start_retrieval_attempt,
)
from forecast_ledger.source_verification_store import (
    record_source_verification,
)

PACKET_VALIDATION_REASON = (
    "Candidate URLs grounded in retrieval web-search sources. "
    "Accepted evidence passed independent publication-time "
    "verification. Rejected candidates remain visible in the "
    "source-verification audit."
)

RETRIEVAL_RETRYABLE_ERROR_TYPES = {
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "RetrievalOutputError",
    "NetworkError",
}


class PipelineStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class PipelineTarget:
    market_id: str
    checkpoint: Checkpoint
    question: str
    resolution_rules: str
    snapshot_id: str
    observed_at: datetime
    yes_bid: float
    yes_ask: float

    @property
    def market_probability(self) -> float:
        return (self.yes_bid + self.yes_ask) / 2.0


@dataclass(frozen=True)
class AttemptState:
    attempt_number: int
    status: str
    error_type: str | None


def load_targets(
    connection: sqlite3.Connection,
    market_id: str | None = None,
    checkpoint: Checkpoint | None = None,
) -> tuple[PipelineTarget, ...]:
    rows = connection.execute(
        """
        SELECT
            tm.market_id,
            sr.checkpoint,
            tm.question,
            tm.resolution_rules,
            ms.snapshot_id,
            ms.observed_at,
            ms.yes_bid,
            ms.yes_ask
        FROM semantic_reviews AS sr
        JOIN machine_eligibility AS me
          ON me.market_id = sr.market_id
         AND me.checkpoint = sr.checkpoint
         AND me.protocol_version = sr.protocol_version
        JOIN tracked_markets AS tm
          ON tm.market_id = sr.market_id
         AND tm.protocol_version = sr.protocol_version
        JOIN market_snapshots AS ms
          ON ms.snapshot_id = me.snapshot_id
         AND ms.market_id = sr.market_id
         AND ms.checkpoint = sr.checkpoint
         AND ms.protocol_version = sr.protocol_version
        WHERE sr.protocol_version = ?
          AND sr.decision = 'included'
          AND me.eligible_for_review = 1
        ORDER BY
            ms.observed_at,
            tm.market_id,
            sr.checkpoint
        """,
        (PROTOCOL_VERSION,),
    ).fetchall()

    targets = tuple(
        PipelineTarget(
            market_id=row[0],
            checkpoint=Checkpoint(row[1]),
            question=row[2],
            resolution_rules=row[3],
            snapshot_id=row[4],
            observed_at=datetime.fromisoformat(row[5]),
            yes_bid=float(row[6]),
            yes_ask=float(row[7]),
        )
        for row in rows
    )

    if market_id is not None:
        targets = tuple(
            target
            for target in targets
            if target.market_id == market_id
        )

    if checkpoint is not None:
        targets = tuple(
            target
            for target in targets
            if target.checkpoint == checkpoint
        )

    return targets


def _load_retrieval_attempts(
    connection: sqlite3.Connection,
    target: PipelineTarget,
) -> tuple[AttemptState, ...]:
    rows = connection.execute(
        """
        SELECT
            attempt_number,
            status,
            error_type
        FROM retrieval_attempts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
        ORDER BY attempt_number
        """,
        (
            target.market_id,
            target.checkpoint.value,
            PROTOCOL_VERSION,
        ),
    ).fetchall()

    return tuple(
        AttemptState(
            attempt_number=int(row[0]),
            status=row[1],
            error_type=row[2],
        )
        for row in rows
    )


def _validate_attempt_sequence(
    attempts: tuple[AttemptState, ...],
) -> None:
    actual = tuple(
        attempt.attempt_number
        for attempt in attempts
    )
    expected = tuple(range(1, len(attempts) + 1))

    if actual != expected:
        raise PipelineStateError(
            "Attempt sequence is not contiguous: "
            f"expected {expected}, found {actual}."
        )


def _next_retrieval_attempt(
    attempts: tuple[AttemptState, ...],
) -> int | None:
    _validate_attempt_sequence(attempts)

    if not attempts:
        return 1

    last = attempts[-1]

    if last.status == "started":
        raise PipelineStateError(
            "Retrieval has a STARTED attempt with unknown final state. "
            "Automatic rerun is forbidden."
        )

    if last.status == "succeeded":
        raise PipelineStateError(
            "Retrieval succeeded but no valid evidence packet exists. "
            "Automatic re-retrieval is forbidden."
        )

    if last.status != "failed":
        raise PipelineStateError(
            f"Unknown retrieval attempt status: {last.status}"
        )

    if len(attempts) >= 3:
        return None

    if last.error_type not in RETRIEVAL_RETRYABLE_ERROR_TYPES:
        return None

    return last.attempt_number + 1


def _packet_id(
    target: PipelineTarget,
    response_id: str,
    evidence_ids: tuple[str, ...],
) -> str:
    material = json.dumps(
        {
            "protocol_version": PROTOCOL_VERSION,
            "market_id": target.market_id,
            "checkpoint": target.checkpoint.value,
            "snapshot_id": target.snapshot_id,
            "retrieval_response_id": response_id,
            "retrieval_model": RETRIEVAL_MODEL,
            "retrieval_prompt_version": (
                RETRIEVAL_PROMPT_VERSION
            ),
            "evidence_ids": evidence_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()


def _validate_existing_packet(
    connection: sqlite3.Connection,
    target: PipelineTarget,
    packet_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT
            snapshot_id,
            information_cutoff,
            retrieval_model,
            retrieval_prompt_version
        FROM evidence_packets
        WHERE packet_id = ?
        """,
        (packet_id,),
    ).fetchone()

    if row is None:
        raise PipelineStateError(
            "Valid packet loader returned an unknown packet."
        )

    expected = (
        target.snapshot_id,
        target.observed_at.isoformat(),
        RETRIEVAL_MODEL,
        RETRIEVAL_PROMPT_VERSION,
    )

    if row != expected:
        raise PipelineStateError(
            "Existing valid packet does not match the frozen "
            "snapshot/model/prompt configuration."
        )


def _retrieval_failure_details(
    exc: Exception,
    retrieval_response=None,
) -> tuple[str, str | None, str | None]:
    if isinstance(exc, RetrievalOutputError):
        return (
            "RetrievalOutputError",
            exc.response_id,
            exc.raw_output,
        )

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code

        if status == 429:
            error_type = "RateLimitError"
        elif status >= 500:
            error_type = "NetworkError"
        else:
            error_type = "SourceVerificationHTTPError"

        response_id = (
            retrieval_response.response_id
            if retrieval_response is not None
            else None
        )
        raw_output = (
            retrieval_response.raw_output
            if retrieval_response is not None
            else None
        )

        return error_type, response_id, raw_output

    if isinstance(exc, httpx.TransportError):
        response_id = (
            retrieval_response.response_id
            if retrieval_response is not None
            else None
        )
        raw_output = (
            retrieval_response.raw_output
            if retrieval_response is not None
            else None
        )

        return "NetworkError", response_id, raw_output

    if isinstance(exc, OpenAIError):
        return type(exc).__name__, None, None

    raise TypeError(
        "Unsupported retrieval failure classification."
    )


def ensure_evidence_packet(
    connection: sqlite3.Connection,
    client: OpenAI,
    target: PipelineTarget,
) -> str | None:
    existing = load_valid_packet_id_for_checkpoint(
        connection=connection,
        market_id=target.market_id,
        checkpoint=target.checkpoint,
        protocol_version=PROTOCOL_VERSION,
    )

    if existing is not None:
        _validate_existing_packet(
            connection,
            target,
            existing,
        )
        return existing

    while True:
        attempts = _load_retrieval_attempts(
            connection,
            target,
        )

        attempt_number = _next_retrieval_attempt(
            attempts
        )

        if attempt_number is None:
            return None

        requested_at = datetime.now(UTC)

        start_retrieval_attempt(
            connection=connection,
            market_id=target.market_id,
            checkpoint=target.checkpoint,
            attempt_number=attempt_number,
            model=RETRIEVAL_MODEL,
            prompt_version=RETRIEVAL_PROMPT_VERSION,
            requested_at=requested_at,
            protocol_version=PROTOCOL_VERSION,
        )

        retrieval_response = None

        try:
            retrieval_response = retrieve_evidence(
                client=client,
                model=RETRIEVAL_MODEL,
                question=target.question,
                resolution_rules=target.resolution_rules,
                information_cutoff=target.observed_at,
            )

            evidence_items, verifications = (
                verified_evidence_items(
                    retrieval=retrieval_response,
                    information_cutoff=target.observed_at,
                )
            )

        except (
            RetrievalOutputError,
            OpenAIError,
            httpx.HTTPStatusError,
            httpx.TransportError,
        ) as exc:
            error_type, response_id, raw_output = (
                _retrieval_failure_details(
                    exc,
                    retrieval_response,
                )
            )

            finish_retrieval_attempt_failure(
                connection=connection,
                market_id=target.market_id,
                checkpoint=target.checkpoint,
                attempt_number=attempt_number,
                completed_at=datetime.now(UTC),
                error_type=error_type,
                error_message=str(exc),
                response_id=response_id,
                raw_output=raw_output,
                protocol_version=PROTOCOL_VERSION,
            )

            if (
                error_type
                not in RETRIEVAL_RETRYABLE_ERROR_TYPES
            ):
                return None

            continue

        finish_retrieval_attempt_success(
            connection=connection,
            market_id=target.market_id,
            checkpoint=target.checkpoint,
            attempt_number=attempt_number,
            completed_at=retrieval_response.retrieved_at,
            response_id=retrieval_response.response_id,
            raw_output=retrieval_response.raw_output,
            protocol_version=PROTOCOL_VERSION,
        )

        for verification in verifications:
            record_source_verification(
                connection=connection,
                market_id=target.market_id,
                checkpoint=target.checkpoint,
                attempt_number=attempt_number,
                verification=verification,
                protocol_version=PROTOCOL_VERSION,
            )

        evidence_ids = tuple(
            item.evidence_id
            for item in evidence_items
        )

        packet_id = _packet_id(
            target=target,
            response_id=retrieval_response.response_id,
            evidence_ids=evidence_ids,
        )

        packet = EvidencePacket(
            packet_id=packet_id,
            market_id=target.market_id,
            snapshot_id=target.snapshot_id,
            information_cutoff=target.observed_at,
            evidence_ids=evidence_ids,
            retrieval_model=RETRIEVAL_MODEL,
            retrieval_prompt_version=(
                RETRIEVAL_PROMPT_VERSION
            ),
            created_at=datetime.now(UTC),
        )

        record_evidence_packet(
            connection=connection,
            packet=packet,
            checkpoint=target.checkpoint,
            evidence_items=evidence_items,
            attempt_number=attempt_number,
            protocol_version=PROTOCOL_VERSION,
        )

        record_packet_validation(
            connection=connection,
            packet_id=packet_id,
            status=PacketValidationStatus.VALID,
            reason=PACKET_VALIDATION_REASON,
            validated_at=datetime.now(UTC),
        )

        return packet_id


def _condition_market_probability(
    condition: ForecastCondition,
    target: PipelineTarget,
) -> float | None:
    if condition == ForecastCondition.STRUCTURED_MARKET_AWARE:
        return target.market_probability

    return None


def _forecast_exists(
    connection: sqlite3.Connection,
    target: PipelineTarget,
    condition: ForecastCondition,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM forecasts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND condition = ?
          AND model = ?
        LIMIT 1
        """,
        (
            target.market_id,
            target.checkpoint.value,
            PROTOCOL_VERSION,
            condition.value,
            FORECAST_MODEL,
        ),
    ).fetchone()

    return row is not None


def _load_forecast_attempts(
    connection: sqlite3.Connection,
    target: PipelineTarget,
    condition: ForecastCondition,
) -> tuple[AttemptState, ...]:
    rows = connection.execute(
        """
        SELECT
            attempt_number,
            status,
            error_type
        FROM forecast_attempts
        WHERE market_id = ?
          AND checkpoint = ?
          AND protocol_version = ?
          AND condition = ?
        ORDER BY attempt_number
        """,
        (
            target.market_id,
            target.checkpoint.value,
            PROTOCOL_VERSION,
            condition.value,
        ),
    ).fetchall()

    return tuple(
        AttemptState(
            attempt_number=int(row[0]),
            status=row[1],
            error_type=row[2],
        )
        for row in rows
    )


def _next_forecast_attempt(
    attempts: tuple[AttemptState, ...],
) -> int | None:
    _validate_attempt_sequence(attempts)

    if not attempts:
        return 1

    last = attempts[-1]

    if last.status == "started":
        raise PipelineStateError(
            "Forecast has a STARTED attempt with unknown final state. "
            "Automatic rerun is forbidden."
        )

    if last.status == "succeeded":
        raise PipelineStateError(
            "Forecast attempt succeeded but no scored forecast exists. "
            "Automatic new model call is forbidden."
        )

    if last.status != "failed":
        raise PipelineStateError(
            f"Unknown forecast attempt status: {last.status}"
        )

    if len(attempts) >= 3:
        return None

    if (
        last.error_type
        not in forecast_store.RETRYABLE_ERROR_TYPES
    ):
        return None

    return last.attempt_number + 1


def run_forecast_condition(
    connection: sqlite3.Connection,
    client: OpenAI,
    target: PipelineTarget,
    packet_id: str,
    condition: ForecastCondition,
    code_commit: str,
) -> str:
    if _forecast_exists(
        connection,
        target,
        condition,
    ):
        return "existing"

    evidence_items = load_evidence_items_for_packet(
        connection,
        packet_id,
    )

    market_probability = _condition_market_probability(
        condition,
        target,
    )

    while True:
        attempts = _load_forecast_attempts(
            connection,
            target,
            condition,
        )

        attempt_number = _next_forecast_attempt(
            attempts
        )

        if attempt_number is None:
            return "blocked"

        prompt = build_forecast_prompt(
            condition=condition,
            question=target.question,
            resolution_rules=target.resolution_rules,
            evidence_items=evidence_items,
            market_probability=market_probability,
        )

        prompt_sha256 = hashlib.sha256(
            prompt.encode("utf-8")
        ).hexdigest()

        requested_at = datetime.now(UTC)

        forecast_store.start_forecast_attempt(
            connection=connection,
            market_id=target.market_id,
            checkpoint=target.checkpoint,
            condition=condition,
            attempt_number=attempt_number,
            packet_id=packet_id,
            snapshot_id=target.snapshot_id,
            model=FORECAST_MODEL,
            reasoning_effort=FORECAST_REASONING_EFFORT,
            prompt_version=prompt_version_for_condition(
                condition
            ),
            prompt_sha256=prompt_sha256,
            requested_at=requested_at,
            protocol_commit=PROTOCOL_COMMIT,
            code_commit=code_commit,
            protocol_version=PROTOCOL_VERSION,
        )

        try:
            response = create_forecast(
                client=client,
                condition=condition,
                question=target.question,
                resolution_rules=target.resolution_rules,
                evidence_items=evidence_items,
                market_probability=market_probability,
                model=FORECAST_MODEL,
                reasoning_effort=FORECAST_REASONING_EFFORT,
            )

        except ForecastOutputError as exc:
            forecast_store.finish_forecast_attempt_failure(
                connection=connection,
                market_id=target.market_id,
                checkpoint=target.checkpoint,
                condition=condition,
                attempt_number=attempt_number,
                completed_at=exc.completed_at,
                error_type=type(exc).__name__,
                error_message=str(exc),
                response_id=exc.response_id,
                raw_output=exc.raw_output,
                protocol_version=PROTOCOL_VERSION,
            )
            continue

        except OpenAIError as exc:
            error_type = type(exc).__name__

            forecast_store.finish_forecast_attempt_failure(
                connection=connection,
                market_id=target.market_id,
                checkpoint=target.checkpoint,
                condition=condition,
                attempt_number=attempt_number,
                completed_at=datetime.now(UTC),
                error_type=error_type,
                error_message=str(exc),
                protocol_version=PROTOCOL_VERSION,
            )

            if (
                error_type
                not in forecast_store.RETRYABLE_ERROR_TYPES
            ):
                return "blocked"

            continue

        if response.prompt != prompt:
            raise PipelineStateError(
                "Forecast response prompt differs from "
                "the prompt recorded before the API call."
            )

        if response.prompt_sha256 != prompt_sha256:
            raise PipelineStateError(
                "Forecast response prompt hash differs from "
                "the pre-call prompt hash."
            )

        forecast_store.finish_forecast_attempt_success(
            connection=connection,
            market_id=target.market_id,
            checkpoint=target.checkpoint,
            condition=condition,
            attempt_number=attempt_number,
            completed_at=response.completed_at,
            response_id=response.response_id,
            raw_output=response.raw_output,
            protocol_version=PROTOCOL_VERSION,
        )

        forecast_store.record_forecast(
            connection=connection,
            market_id=target.market_id,
            checkpoint=target.checkpoint,
            condition=condition,
            packet_id=packet_id,
            snapshot_id=target.snapshot_id,
            model=FORECAST_MODEL,
            reasoning_effort=FORECAST_REASONING_EFFORT,
            prompt_version=prompt_version_for_condition(
                condition
            ),
            prompt_sha256=prompt_sha256,
            attempt_number=attempt_number,
            response_id=response.response_id,
            analysis=response.analysis,
            forecast_created_at=response.completed_at,
            protocol_commit=PROTOCOL_COMMIT,
            code_commit=code_commit,
            protocol_version=PROTOCOL_VERSION,
        )

        return "created"


def run_target(
    connection: sqlite3.Connection,
    client: OpenAI,
    target: PipelineTarget,
    code_commit: str,
) -> None:
    print()
    print("=" * 80)
    print(
        target.market_id,
        target.checkpoint.value,
        "|",
        target.question,
    )
    print(
        "snapshot:",
        target.snapshot_id,
        "| market p:",
        f"{target.market_probability:.4f}",
    )

    packet_id = ensure_evidence_packet(
        connection=connection,
        client=client,
        target=target,
    )

    if packet_id is None:
        print("retrieval: BLOCKED")
        return

    print("packet:", packet_id)

    conditions = (
        ForecastCondition.DIRECT,
        ForecastCondition.STRUCTURED_INDEPENDENT,
        ForecastCondition.STRUCTURED_MARKET_AWARE,
    )

    for condition in conditions:
        try:
            state = run_forecast_condition(
                connection=connection,
                client=client,
                target=target,
                packet_id=packet_id,
                condition=condition,
                code_commit=code_commit,
            )
        except PipelineStateError as exc:
            print(
                condition.value,
                "BLOCKED:",
                exc,
            )
            continue

        row = connection.execute(
            """
            SELECT probability_yes
            FROM forecasts
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
              AND condition = ?
              AND model = ?
            """,
            (
                target.market_id,
                target.checkpoint.value,
                PROTOCOL_VERSION,
                condition.value,
                FORECAST_MODEL,
            ),
        ).fetchone()

        probability = (
            f"{float(row[0]):.4f}"
            if row is not None
            else "none"
        )

        print(
            condition.value,
            state.upper(),
            "p=",
            probability,
        )


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _require_clean_git() -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain"],
        text=True,
    ).strip()

    if status:
        raise RuntimeError(
            "Refusing scored execution with an uncommitted "
            "working tree. Commit the runner first.\n"
            f"{status}"
        )


def print_dry_run(
    connection: sqlite3.Connection,
    targets: tuple[PipelineTarget, ...],
) -> None:
    print("Forecast Ledger v0.2 pipeline dry run")
    print("=======================================")
    print("targets:", len(targets))
    print()

    for target in targets:
        packet_id = load_valid_packet_id_for_checkpoint(
            connection=connection,
            market_id=target.market_id,
            checkpoint=target.checkpoint,
            protocol_version=PROTOCOL_VERSION,
        )

        retrieval_rows = connection.execute(
            """
            SELECT attempt_number, status, error_type
            FROM retrieval_attempts
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
            ORDER BY attempt_number
            """,
            (
                target.market_id,
                target.checkpoint.value,
                PROTOCOL_VERSION,
            ),
        ).fetchall()

        forecast_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM forecasts
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
              AND model = ?
            """,
            (
                target.market_id,
                target.checkpoint.value,
                PROTOCOL_VERSION,
                FORECAST_MODEL,
            ),
        ).fetchone()[0]

        retrieval_state = (
            "none"
            if not retrieval_rows
            else (
                f"{retrieval_rows[-1][1]}"
                f"/{retrieval_rows[-1][2] or '-'}"
                f"/attempt{retrieval_rows[-1][0]}"
            )
        )

        print(
            target.market_id,
            target.checkpoint.value,
            f"market_p={target.market_probability:.4f}",
            f"retrieval={retrieval_state}",
            f"packet={'yes' if packet_id else 'no'}",
            f"forecasts={forecast_count}/3",
            "|",
            target.question,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run frozen v0.2 Forecast Ledger forecasts."
    )
    parser.add_argument(
        "--db",
        default="data/forecast_ledger.db",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually make retrieval and forecasting API calls.",
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

    checkpoint = (
        Checkpoint(args.checkpoint)
        if args.checkpoint is not None
        else None
    )

    targets = load_targets(
        connection=connection,
        market_id=args.market_id,
        checkpoint=checkpoint,
    )

    if not args.execute:
        print_dry_run(
            connection,
            targets,
        )
        connection.close()
        return

    _require_clean_git()
    code_commit = _git_commit()

    print("OpenAI authentication preflight...")
    client = OpenAI()
    client.models.list()
    print("preflight: OK")
    print("code commit:", code_commit)
    print("protocol commit:", PROTOCOL_COMMIT)

    for target in targets:
        try:
            run_target(
                connection=connection,
                client=client,
                target=target,
                code_commit=code_commit,
            )
        except PipelineStateError as exc:
            print()
            print(
                target.market_id,
                target.checkpoint.value,
                "BLOCKED:",
                exc,
            )

    connection.close()


if __name__ == "__main__":
    main()
