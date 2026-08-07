import json
from datetime import UTC, datetime

import pytest

from forecast_ledger.domain import Market
from forecast_ledger.polymarket import market_from_gamma


def make_gamma_market() -> dict:
    return {
        "id": "123",
        "question": "Will example event happen?",
        "description": "Resolves YES if the event happens before the deadline.",
        "endDate": "2026-08-20T12:00:00Z",
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
    }


def test_market_from_gamma_maps_binary_market() -> None:
    market = market_from_gamma(make_gamma_market())

    assert market.market_id == "123"
    assert market.question == "Will example event happen?"
    assert market.yes_token_id == "yes-token"
    assert market.no_token_id == "no-token"
    assert market.close_time.isoformat() == "2026-08-20T12:00:00+00:00"


def test_market_from_gamma_rejects_non_binary_market() -> None:
    raw = make_gamma_market()
    raw["outcomes"] = json.dumps(["Candidate A", "Candidate B"])

    with pytest.raises(
        ValueError,
        match="Market outcomes must be exactly",
    ):
        market_from_gamma(raw)


def test_market_from_gamma_rejects_wrong_token_count() -> None:
    raw = make_gamma_market()
    raw["clobTokenIds"] = json.dumps(["only-one-token"])

    with pytest.raises(
        ValueError,
        match="exactly two CLOB token IDs",
    ):
        market_from_gamma(raw)


def test_market_from_gamma_requires_resolution_rules() -> None:
    raw = make_gamma_market()
    raw["description"] = ""
    raw["resolutionSource"] = ""

    with pytest.raises(
        ValueError,
        match="no usable resolution rules",
    ):
        market_from_gamma(raw)


from forecast_ledger.polymarket import best_bid_ask_from_book


def test_best_bid_ask_from_book_does_not_assume_sort_order() -> None:
    raw_book = {
        "bids": [
            {"price": "0.41", "size": "100"},
            {"price": "0.47", "size": "50"},
            {"price": "0.44", "size": "80"},
        ],
        "asks": [
            {"price": "0.55", "size": "40"},
            {"price": "0.51", "size": "70"},
            {"price": "0.53", "size": "90"},
        ],
    }

    best_bid, best_ask = best_bid_ask_from_book(raw_book)

    assert best_bid == pytest.approx(0.47)
    assert best_ask == pytest.approx(0.51)


def test_best_bid_ask_from_book_rejects_missing_bid_side() -> None:
    raw_book = {
        "bids": [],
        "asks": [{"price": "0.51", "size": "70"}],
    }

    with pytest.raises(ValueError, match="no bids"):
        best_bid_ask_from_book(raw_book)


def test_best_bid_ask_from_book_rejects_crossed_book() -> None:
    raw_book = {
        "bids": [{"price": "0.60", "size": "100"}],
        "asks": [{"price": "0.55", "size": "100"}],
    }

    with pytest.raises(ValueError, match="best bid exceeds best ask"):
        best_bid_ask_from_book(raw_book)


def test_no_book_failure_does_not_invalidate_yes_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from forecast_ledger import polymarket

    market = Market(
        market_id="market-1",
        question="Will example happen?",
        resolution_rules="Resolves YES if example happens.",
        close_time=datetime(
            2026,
            8,
            31,
            tzinfo=UTC,
        ),
        yes_token_id="yes-token",
        no_token_id="no-token",
    )

    def fake_fetch(token_id: str) -> dict:
        if token_id == "yes-token":
            return {
                "bids": [{"price": "0.40"}],
                "asks": [{"price": "0.44"}],
            }

        raise httpx.RemoteProtocolError(
            "NO diagnostic failed"
        )

    monkeypatch.setattr(
        polymarket,
        "fetch_order_book",
        fake_fetch,
    )

    fetched = polymarket.fetch_market_snapshot_with_raw(
        market
    )

    assert fetched.snapshot.yes_bid == pytest.approx(0.40)
    assert fetched.snapshot.yes_ask == pytest.approx(0.44)
    assert fetched.snapshot.no_bid is None
    assert fetched.snapshot.no_ask is None
    assert fetched.no_book is None
    assert fetched.no_book_error is not None
