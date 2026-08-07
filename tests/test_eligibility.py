from datetime import UTC, datetime

from forecast_ledger.domain import Market, MarketSnapshot
from forecast_ledger.eligibility import evaluate_machine_eligibility


NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def make_market(
    close_time: datetime = datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
) -> Market:
    return Market(
        market_id="market-1",
        question="Will example event happen?",
        resolution_rules="Resolves YES if the event happens before the deadline.",
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


def test_valid_candidate_passes_machine_eligibility() -> None:
    result = evaluate_machine_eligibility(
        market=make_market(),
        snapshot=make_snapshot(),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is True
    assert result.rejection_reasons == ()


def test_market_closing_too_late_is_rejected() -> None:
    market = make_market(
        close_time=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )

    result = evaluate_machine_eligibility(
        market=market,
        snapshot=make_snapshot(),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is False
    assert "more_than_45_days_to_close" in result.rejection_reasons


def test_market_closing_too_soon_is_rejected() -> None:
    market = make_market(
        close_time=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
    )

    result = evaluate_machine_eligibility(
        market=market,
        snapshot=make_snapshot(),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is False
    assert "fewer_than_5_days_to_close" in result.rejection_reasons


def test_wide_spread_is_rejected() -> None:
    result = evaluate_machine_eligibility(
        market=make_market(),
        snapshot=make_snapshot(
            yes_bid=0.35,
            yes_ask=0.50,
        ),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is False
    assert "yes_spread_above_0.10" in result.rejection_reasons


def test_extreme_market_probability_is_rejected() -> None:
    result = evaluate_machine_eligibility(
        market=make_market(),
        snapshot=make_snapshot(
            yes_bid=0.96,
            yes_ask=0.98,
        ),
        evaluated_at=NOW,
    )

    assert result.eligible_for_review is False
    assert "market_probability_above_0.95" in result.rejection_reasons


def test_market_and_snapshot_identity_must_match() -> None:
    snapshot = MarketSnapshot(
        snapshot_id="snapshot-2",
        market_id="other-market",
        observed_at=NOW,
        yes_bid=0.40,
        yes_ask=0.44,
    )

    try:
        evaluate_machine_eligibility(
            market=make_market(),
            snapshot=snapshot,
            evaluated_at=NOW,
        )
    except ValueError as exc:
        assert str(exc) == "Snapshot market_id does not match market."
    else:
        raise AssertionError("Expected mismatched market identity to fail.")
