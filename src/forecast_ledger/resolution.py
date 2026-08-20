from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from forecast_ledger.domain import require_timezone_aware
from forecast_ledger.polymarket import (
    CLOB_BASE_URL,
    GAMMA_BASE_URL,
    parse_json_string_list,
)
from forecast_ledger.registry import (
    PROTOCOL_VERSION,
    TrackedMarket,
    load_tracked_markets,
)
from forecast_ledger.resolution_store import (
    ResolutionStatus,
    initialize_resolution_store,
    record_resolution,
)


class ResolutionVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedResolution:
    market_id: str
    outcome_yes: bool
    resolved_at: datetime
    resolution_source: str

    @property
    def status(self) -> ResolutionStatus:
        if self.outcome_yes:
            return ResolutionStatus.RESOLVED_YES

        return ResolutionStatus.RESOLVED_NO


@dataclass(frozen=True)
class ResolutionFailure:
    market_id: str
    error_type: str
    message: str


@dataclass(frozen=True)
class ResolutionSweepReport:
    checked: int
    pending: int
    verified: int
    created: int
    existing: int
    failures: tuple[ResolutionFailure, ...]


HttpGet = Callable[..., Any]


def _parse_source_datetime(
    value: str,
    *,
    field_name: str,
) -> datetime:
    parsed = datetime.fromisoformat(
        value
    )

    require_timezone_aware(
        parsed,
        field_name,
    )

    return parsed


def verify_resolution_payloads(
    *,
    market: TrackedMarket,
    gamma: dict[str, Any],
    clob: dict[str, Any],
) -> VerifiedResolution | None:
    gamma_market_id = str(
        gamma.get("id", "")
    )

    if gamma_market_id != market.market_id:
        raise ResolutionVerificationError(
            "Gamma market identity does not match "
            "the tracked market."
        )

    if gamma.get("closed") is not True:
        return None

    if (
        gamma.get("umaResolutionStatus")
        != "resolved"
    ):
        return None

    outcomes_raw = gamma.get("outcomes")

    if not isinstance(outcomes_raw, str):
        raise ResolutionVerificationError(
            "Gamma outcomes must use the expected "
            "JSON-string representation."
        )

    outcomes = parse_json_string_list(
        outcomes_raw,
        field_name="outcomes",
    )

    if outcomes != ["Yes", "No"]:
        raise ResolutionVerificationError(
            "Resolved market is no longer an exact "
            "YES/NO market."
        )

    token_ids_raw = gamma.get(
        "clobTokenIds"
    )

    if not isinstance(token_ids_raw, str):
        raise ResolutionVerificationError(
            "Gamma CLOB token IDs are missing."
        )

    token_ids = parse_json_string_list(
        token_ids_raw,
        field_name="clobTokenIds",
    )

    expected_token_ids = [
        market.yes_token_id,
        market.no_token_id,
    ]

    if token_ids != expected_token_ids:
        raise ResolutionVerificationError(
            "Gamma YES/NO token identity changed "
            "after the market was tracked."
        )

    condition_id = gamma.get(
        "conditionId"
    )

    if not isinstance(
        condition_id,
        str,
    ) or not condition_id.strip():
        raise ResolutionVerificationError(
            "Gamma conditionId is missing."
        )

    closed_time = gamma.get(
        "closedTime"
    )

    if not isinstance(
        closed_time,
        str,
    ) or not closed_time.strip():
        raise ResolutionVerificationError(
            "Resolved Gamma market has no closedTime."
        )

    resolved_at = _parse_source_datetime(
        closed_time,
        field_name="closedTime",
    )

    if clob.get("closed") is not True:
        raise ResolutionVerificationError(
            "Gamma reports final resolution but "
            "CLOB market is not closed."
        )

    tokens = clob.get(
        "tokens"
    )

    if not isinstance(tokens, list):
        raise ResolutionVerificationError(
            "CLOB tokens must be a list."
        )

    if len(tokens) != 2:
        raise ResolutionVerificationError(
            "Binary market must have exactly "
            "two CLOB tokens."
        )

    by_outcome: dict[
        str,
        dict[str, Any],
    ] = {}

    for token in tokens:
        if not isinstance(token, dict):
            raise ResolutionVerificationError(
                "CLOB token must be an object."
            )

        outcome = token.get(
            "outcome"
        )

        if outcome not in (
            "Yes",
            "No",
        ):
            raise ResolutionVerificationError(
                "Unexpected CLOB outcome label."
            )

        if outcome in by_outcome:
            raise ResolutionVerificationError(
                "Duplicate CLOB outcome label."
            )

        by_outcome[outcome] = token

    if set(by_outcome) != {
        "Yes",
        "No",
    }:
        raise ResolutionVerificationError(
            "CLOB market does not contain exact "
            "YES/NO outcomes."
        )

    yes_token = by_outcome["Yes"]
    no_token = by_outcome["No"]

    if (
        str(yes_token.get("token_id"))
        != market.yes_token_id
    ):
        raise ResolutionVerificationError(
            "CLOB YES token does not match the "
            "frozen tracked YES token."
        )

    if (
        str(no_token.get("token_id"))
        != market.no_token_id
    ):
        raise ResolutionVerificationError(
            "CLOB NO token does not match the "
            "frozen tracked NO token."
        )

    winners = [
        token
        for token in tokens
        if token.get("winner") is True
    ]

    if len(winners) != 1:
        raise ResolutionVerificationError(
            "Expected exactly one explicit "
            "winning CLOB token."
        )

    winner = winners[0]

    winner_token_id = str(
        winner.get("token_id")
    )

    if (
        winner_token_id
        == market.yes_token_id
    ):
        outcome_yes = True

    elif (
        winner_token_id
        == market.no_token_id
    ):
        outcome_yes = False

    else:
        raise ResolutionVerificationError(
            "Winning token is not one of the "
            "frozen YES/NO tokens."
        )

    gamma_url = (
        f"{GAMMA_BASE_URL}/markets/"
        f"{market.market_id}"
    )

    clob_url = (
        f"{CLOB_BASE_URL}/markets/"
        f"{condition_id}"
    )

    resolution_source = json.dumps(
        {
            "provider": "polymarket",
            "gamma_url": gamma_url,
            "clob_url": clob_url,
            "condition_id": condition_id,
            "winning_outcome": (
                "Yes"
                if outcome_yes
                else "No"
            ),
            "winning_token_id": (
                winner_token_id
            ),
            "gamma_closed_time": (
                closed_time
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return VerifiedResolution(
        market_id=market.market_id,
        outcome_yes=outcome_yes,
        resolved_at=resolved_at,
        resolution_source=(
            resolution_source
        ),
    )


def fetch_polymarket_resolution(
    market: TrackedMarket,
    *,
    http_get: HttpGet = httpx.get,
) -> VerifiedResolution | None:
    gamma_url = (
        f"{GAMMA_BASE_URL}/markets/"
        f"{market.market_id}"
    )

    gamma_response = http_get(
        gamma_url,
        timeout=20.0,
    )
    gamma_response.raise_for_status()

    gamma = gamma_response.json()

    if not isinstance(gamma, dict):
        raise TypeError(
            "Gamma market response must "
            "be an object."
        )

    if gamma.get("closed") is not True:
        return None

    if (
        gamma.get("umaResolutionStatus")
        != "resolved"
    ):
        return None

    condition_id = gamma.get(
        "conditionId"
    )

    if not isinstance(
        condition_id,
        str,
    ) or not condition_id.strip():
        raise ResolutionVerificationError(
            "Resolved Gamma market has no "
            "conditionId."
        )

    clob_url = (
        f"{CLOB_BASE_URL}/markets/"
        f"{condition_id}"
    )

    clob_response = http_get(
        clob_url,
        timeout=20.0,
    )
    clob_response.raise_for_status()

    clob = clob_response.json()

    if not isinstance(clob, dict):
        raise TypeError(
            "CLOB market response must "
            "be an object."
        )

    return verify_resolution_payloads(
        market=market,
        gamma=gamma,
        clob=clob,
    )


def load_unresolved_forecast_market_ids(
    connection: sqlite3.Connection,
    *,
    market_id: str | None = None,
    protocol_version: str = (
        PROTOCOL_VERSION
    ),
) -> tuple[str, ...]:
    sql = """
        SELECT DISTINCT
            f.market_id
        FROM forecasts AS f

        LEFT JOIN market_resolutions AS r
          ON r.market_id = f.market_id
         AND r.protocol_version =
             f.protocol_version

        WHERE f.protocol_version = ?
          AND r.market_id IS NULL
    """

    parameters: list[str] = [
        protocol_version
    ]

    if market_id is not None:
        sql += """
          AND f.market_id = ?
        """
        parameters.append(
            market_id
        )

    sql += """
        ORDER BY f.market_id
    """

    rows = connection.execute(
        sql,
        tuple(parameters),
    ).fetchall()

    return tuple(
        str(row[0])
        for row in rows
    )


def sweep_resolutions(
    connection: sqlite3.Connection,
    *,
    execute: bool,
    market_id: str | None = None,
    http_get: HttpGet = httpx.get,
    retrieved_at: datetime | None = None,
) -> ResolutionSweepReport:
    initialize_resolution_store(
        connection
    )

    observed_at = (
        retrieved_at
        if retrieved_at is not None
        else datetime.now(UTC)
    )

    require_timezone_aware(
        observed_at,
        "retrieved_at",
    )

    candidate_ids = (
        load_unresolved_forecast_market_ids(
            connection,
            market_id=market_id,
        )
    )

    tracked_by_id = {
        market.market_id: market
        for market in load_tracked_markets(
            connection
        )
        if (
            market.protocol_version
            == PROTOCOL_VERSION
        )
    }

    pending = 0
    verified = 0
    created = 0
    existing = 0

    failures: list[
        ResolutionFailure
    ] = []

    for candidate_id in candidate_ids:
        market = tracked_by_id.get(
            candidate_id
        )

        if market is None:
            raise RuntimeError(
                "Forecast references a market "
                "missing from the tracked registry: "
                f"{candidate_id}"
            )

        try:
            resolution = (
                fetch_polymarket_resolution(
                    market,
                    http_get=http_get,
                )
            )

        except (
            httpx.HTTPError,
            KeyError,
            TypeError,
            ValueError,
            ResolutionVerificationError,
        ) as exc:
            failures.append(
                ResolutionFailure(
                    market_id=(
                        candidate_id
                    ),
                    error_type=(
                        type(exc).__name__
                    ),
                    message=str(exc),
                )
            )
            continue

        if resolution is None:
            pending += 1
            continue

        verified += 1

        if not execute:
            continue

        was_created = record_resolution(
            connection=connection,
            market_id=(
                resolution.market_id
            ),
            outcome_yes=(
                resolution.outcome_yes
            ),
            resolved_at=(
                resolution.resolved_at
            ),
            resolution_source=(
                resolution.resolution_source
            ),
            resolution_status=(
                resolution.status
            ),
            retrieved_at=observed_at,
        )

        if was_created:
            created += 1
        else:
            existing += 1

    return ResolutionSweepReport(
        checked=len(candidate_ids),
        pending=pending,
        verified=verified,
        created=created,
        existing=existing,
        failures=tuple(failures),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and ingest explicit "
            "Polymarket resolutions."
        )
    )

    parser.add_argument(
        "--db",
        default=(
            "data/forecast_ledger.db"
        ),
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Persist verified terminal "
            "resolutions."
        ),
    )

    parser.add_argument(
        "--market-id",
        default=None,
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
        report = sweep_resolutions(
            connection=connection,
            execute=args.execute,
            market_id=args.market_id,
        )

        print()
        print("RESOLUTION SWEEP")
        print("================")
        print(
            "forecasted unresolved markets:",
            report.checked,
        )
        print(
            "still pending:",
            report.pending,
        )
        print(
            "explicitly verified:",
            report.verified,
        )

        if args.execute:
            print(
                "new resolutions:",
                report.created,
            )
            print(
                "already existing:",
                report.existing,
            )
        else:
            print(
                "DRY RUN: no resolution "
                "records written."
            )

        print(
            "verification failures:",
            len(report.failures),
        )

        if report.failures:
            print()
            print("FAILURES")
            print("--------")

            for failure in report.failures:
                print(
                    failure.market_id,
                    failure.error_type,
                    "|",
                    failure.message,
                )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
