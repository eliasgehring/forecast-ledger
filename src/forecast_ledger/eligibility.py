from dataclasses import dataclass
from datetime import datetime

from forecast_ledger.domain import (
    Market,
    MarketSnapshot,
    require_timezone_aware,
)

MIN_DAYS_TO_CLOSE = 5.0
MAX_DAYS_TO_CLOSE = 45.0
MAX_YES_SPREAD = 0.10
MIN_MARKET_PROBABILITY = 0.05
MAX_MARKET_PROBABILITY = 0.95


@dataclass(frozen=True)
class EligibilityResult:
    eligible_for_review: bool
    rejection_reasons: tuple[str, ...]


def _validate_market_snapshot_pair(
    market: Market,
    snapshot: MarketSnapshot,
) -> None:
    if snapshot.market_id != market.market_id:
        raise ValueError(
            "Snapshot market_id does not match market."
        )


def _snapshot_rejection_reasons(
    snapshot: MarketSnapshot,
) -> list[str]:
    rejection_reasons: list[str] = []

    if snapshot.yes_spread > MAX_YES_SPREAD:
        rejection_reasons.append(
            "yes_spread_above_0.10"
        )

    if (
        snapshot.market_probability
        < MIN_MARKET_PROBABILITY
    ):
        rejection_reasons.append(
            "market_probability_below_0.05"
        )

    if (
        snapshot.market_probability
        > MAX_MARKET_PROBABILITY
    ):
        rejection_reasons.append(
            "market_probability_above_0.95"
        )

    return rejection_reasons


def evaluate_enrollment_eligibility(
    market: Market,
    snapshot: MarketSnapshot,
    evaluated_at: datetime,
) -> EligibilityResult:
    require_timezone_aware(
        evaluated_at,
        "evaluated_at",
    )

    _validate_market_snapshot_pair(
        market,
        snapshot,
    )

    rejection_reasons = (
        _snapshot_rejection_reasons(snapshot)
    )

    days_to_close = (
        market.close_time - evaluated_at
    ).total_seconds() / 86_400.0

    if days_to_close < MIN_DAYS_TO_CLOSE:
        rejection_reasons.append(
            "fewer_than_5_days_to_close"
        )

    if days_to_close > MAX_DAYS_TO_CLOSE:
        rejection_reasons.append(
            "more_than_45_days_to_close"
        )

    return EligibilityResult(
        eligible_for_review=not rejection_reasons,
        rejection_reasons=tuple(
            rejection_reasons
        ),
    )


def evaluate_checkpoint_eligibility(
    market: Market,
    snapshot: MarketSnapshot,
) -> EligibilityResult:
    """
    Evaluate an already-enrolled market at a forecast checkpoint.

    The 5-to-45-day rule is an enrollment rule. It must not
    invalidate the protocol's 3-day and 1-day checkpoints.
    """
    _validate_market_snapshot_pair(
        market,
        snapshot,
    )

    rejection_reasons = (
        _snapshot_rejection_reasons(snapshot)
    )

    return EligibilityResult(
        eligible_for_review=not rejection_reasons,
        rejection_reasons=tuple(
            rejection_reasons
        ),
    )
