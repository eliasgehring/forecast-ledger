from datetime import UTC, datetime

import pytest

from forecast_ledger.domain import Market, MarketSnapshot


def test_market_accepts_valid_binary_market() -> None:
    market = Market(
        market_id="market-1",
        question="Will example event happen?",
        resolution_rules="Resolves YES if the event happens before the deadline.",
        close_time=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        yes_token_id="yes-1",
        no_token_id="no-1",
    )

    assert market.market_id == "market-1"
    assert market.yes_token_id == "yes-1"
    assert market.no_token_id == "no-1"


def test_market_rejects_identical_yes_and_no_tokens() -> None:
    with pytest.raises(ValueError, match="YES and NO token IDs must be different"):
        Market(
            market_id="market-1",
            question="Will example event happen?",
            resolution_rules="Resolves YES if the event happens.",
            close_time=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            yes_token_id="same-token",
            no_token_id="same-token",
        )


def test_snapshot_calculates_yes_midpoint_probability() -> None:
    snapshot = MarketSnapshot(
        snapshot_id="snapshot-1",
        market_id="market-1",
        observed_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
        yes_bid=0.60,
        yes_ask=0.64,
        no_bid=0.35,
        no_ask=0.39,
    )

    assert snapshot.market_probability == pytest.approx(0.62)
    assert snapshot.yes_spread == pytest.approx(0.04)


def test_snapshot_can_compare_yes_and_no_books() -> None:
    snapshot = MarketSnapshot(
        snapshot_id="snapshot-1",
        market_id="market-1",
        observed_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
        yes_bid=0.60,
        yes_ask=0.64,
        no_bid=0.35,
        no_ask=0.39,
    )

    assert snapshot.no_midpoint == pytest.approx(0.37)
    assert snapshot.no_implied_yes_probability == pytest.approx(0.63)


def test_snapshot_allows_missing_no_book() -> None:
    snapshot = MarketSnapshot(
        snapshot_id="snapshot-1",
        market_id="market-1",
        observed_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
        yes_bid=0.40,
        yes_ask=0.44,
    )

    assert snapshot.no_midpoint is None
    assert snapshot.no_implied_yes_probability is None


def test_snapshot_rejects_partial_no_book() -> None:
    with pytest.raises(
        ValueError,
        match="no_bid and no_ask must either both exist or both be absent",
    ):
        MarketSnapshot(
            snapshot_id="snapshot-1",
            market_id="market-1",
            observed_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
            yes_bid=0.40,
            yes_ask=0.44,
            no_bid=0.55,
        )


def test_snapshot_rejects_bid_above_ask() -> None:
    with pytest.raises(ValueError, match="yes_bid must not exceed yes_ask"):
        MarketSnapshot(
            snapshot_id="snapshot-1",
            market_id="market-1",
            observed_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
            yes_bid=0.70,
            yes_ask=0.60,
        )


def test_snapshot_rejects_naive_timestamp() -> None:
    naive_time = datetime(2026, 8, 7, 8, 0, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        MarketSnapshot(
            snapshot_id="snapshot-1",
            market_id="market-1",
            observed_at=naive_time,
            yes_bid=0.40,
            yes_ask=0.50,
        )
