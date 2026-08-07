import json

import pytest

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
