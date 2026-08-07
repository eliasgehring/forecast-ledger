from datetime import UTC, datetime

import pytest

from forecast_ledger.domain import (
    Market,
    MarketSnapshot,
)
from forecast_ledger.eligibility import (
    evaluate_checkpoint_eligibility,
    evaluate_enrollment_eligibility,
)

NOW = datetime(
    2026,
    8,
    7,
    9,
    0,
    tzinfo=UTC,
)


def make_market(
    close_time: datetime = datetime(
        2026,
        8,
        27,
        9,
        0,
        tzinfo=UTC,
    ),
) -> Market:
    return Market(
        market_id="market-1",
        question="Will example event happen?",
        resolution_rules=(
            "Resolves YES if the event happens "
            "before the deadline."
        ),
        close_time=close_time,
        yes_token_id="yes-token",
        no_token_id="no-token",
    )


def make_snapshot(
    yes_bid: float = 0.40,
    yes_ask: float = 0.44,
) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id="snapshot-1",
        market_id="market-1",
        observed_at=NOW,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=0.55,
        no_ask=0.59,
    )


def test_valid_candidate_passes_enrollment_eligibility() -> None:
    result = evaluate_enrollment_eligibility(
        market=make_market(),
        snapshot=make_snapshot(),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is True
    assert result.rejection_reasons == ()


def test_enrollment_rejects_market_closing_too_late() -> None:
    result = evaluate_enrollment_eligibility(
        market=make_market(
            close_time=datetime(
                2026,
                10,
                1,
                9,
                0,
                tzinfo=UTC,
            )
        ),
        snapshot=make_snapshot(),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is False
    assert (
        "more_than_45_days_to_close"
        in result.rejection_reasons
    )


def test_enrollment_rejects_market_closing_too_soon() -> None:
    result = evaluate_enrollment_eligibility(
        market=make_market(
            close_time=datetime(
                2026,
                8,
                10,
                9,
                0,
                tzinfo=UTC,
            )
        ),
        snapshot=make_snapshot(),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is False
    assert (
        "fewer_than_5_days_to_close"
        in result.rejection_reasons
    )


def test_three_day_checkpoint_does_not_apply_enrollment_window() -> None:
    market = make_market(
        close_time=datetime(
            2026,
            8,
            10,
            9,
            0,
            tzinfo=UTC,
        )
    )

    result = evaluate_checkpoint_eligibility(
        market=market,
        snapshot=make_snapshot(),
    )

    assert result.eligible_for_review is True
    assert result.rejection_reasons == ()


def test_one_day_checkpoint_does_not_apply_enrollment_window() -> None:
    market = make_market(
        close_time=datetime(
            2026,
            8,
            8,
            9,
            0,
            tzinfo=UTC,
        )
    )

    result = evaluate_checkpoint_eligibility(
        market=market,
        snapshot=make_snapshot(),
    )

    assert result.eligible_for_review is True


def test_checkpoint_still_rejects_wide_spread() -> None:
    result = evaluate_checkpoint_eligibility(
        market=make_market(),
        snapshot=make_snapshot(
            yes_bid=0.35,
            yes_ask=0.50,
        ),
    )

    assert result.eligible_for_review is False
    assert (
        "yes_spread_above_0.10"
        in result.rejection_reasons
    )


def test_checkpoint_still_rejects_extreme_probability() -> None:
    result = evaluate_checkpoint_eligibility(
        market=make_market(),
        snapshot=make_snapshot(
            yes_bid=0.96,
            yes_ask=0.98,
        ),
    )

    assert result.eligible_for_review is False
    assert (
        "market_probability_above_0.95"
        in result.rejection_reasons
    )


def test_market_and_snapshot_identity_must_match() -> None:
    snapshot = MarketSnapshot(
        snapshot_id="snapshot-2",
        market_id="other-market",
        observed_at=NOW,
        yes_bid=0.40,
        yes_ask=0.44,
    )

    with pytest.raises(
        ValueError,
        match="Snapshot market_id does not match market",
    ):
        evaluate_checkpoint_eligibility(
            market=make_market(),
            snapshot=snapshot,
        )
