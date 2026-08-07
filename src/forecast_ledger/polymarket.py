import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from forecast_ledger.domain import Market, MarketSnapshot

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"



@dataclass(frozen=True)
class FetchedMarketSnapshot:
    snapshot: MarketSnapshot
    yes_book: dict[str, Any]
    no_book: dict[str, Any] | None
    no_book_error: str | None


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def parse_json_string_list(value: str, field_name: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} is not valid JSON.") from exc

    if not isinstance(parsed, list):
        raise TypeError(f"{field_name} must decode to a list.")

    if not all(isinstance(item, str) for item in parsed):
        raise TypeError(f"{field_name} must contain only strings.")

    return parsed


def market_from_gamma(raw: dict[str, Any]) -> Market:
    outcomes = parse_json_string_list(
        raw["outcomes"],
        field_name="outcomes",
    )

    token_ids = parse_json_string_list(
        raw["clobTokenIds"],
        field_name="clobTokenIds",
    )

    if outcomes != ["Yes", "No"]:
        raise ValueError("Market outcomes must be exactly ['Yes', 'No'].")

    if len(token_ids) != 2:
        raise ValueError("Binary market must have exactly two CLOB token IDs.")

    resolution_rules = raw.get("description") or raw.get("resolutionSource")

    if not resolution_rules:
        raise ValueError("Market has no usable resolution rules.")

    return Market(
        market_id=str(raw["id"]),
        question=str(raw["question"]),
        resolution_rules=str(resolution_rules),
        close_time=parse_datetime(raw["endDate"]),
        yes_token_id=token_ids[0],
        no_token_id=token_ids[1],
    )


def fetch_open_gamma_markets(
    limit: int = 20,
) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{GAMMA_BASE_URL}/markets",
        params={
            "limit": limit,
            "closed": "false",
        },
        timeout=20.0,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, list):
        raise TypeError("Gamma markets response must be a list.")

    return payload


def fetch_first_parseable_market() -> Market:
    raw_markets = fetch_open_gamma_markets()

    errors: list[str] = []

    for raw_market in raw_markets:
        try:
            return market_from_gamma(raw_market)
        except (KeyError, TypeError, ValueError) as exc:
            market_id = raw_market.get("id", "<unknown>")
            errors.append(f"{market_id}: {exc}")

    raise RuntimeError(
        "No parseable binary market found.\n"
        + "\n".join(errors)
    )


def best_bid_ask_from_book(
    raw_book: dict[str, Any],
) -> tuple[float, float]:
    bids = raw_book.get("bids")
    asks = raw_book.get("asks")

    if not isinstance(bids, list):
        raise TypeError("Order-book bids must be a list.")

    if not isinstance(asks, list):
        raise TypeError("Order-book asks must be a list.")

    if not bids:
        raise ValueError("Order book has no bids.")

    if not asks:
        raise ValueError("Order book has no asks.")

    try:
        bid_prices = [float(level["price"]) for level in bids]
        ask_prices = [float(level["price"]) for level in asks]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Order book contains an invalid price level.") from exc

    best_bid = max(bid_prices)
    best_ask = min(ask_prices)

    if best_bid > best_ask:
        raise ValueError("Order book best bid exceeds best ask.")

    return best_bid, best_ask


def fetch_order_book(
    token_id: str,
) -> dict[str, Any]:
    response = httpx.get(
        f"{CLOB_BASE_URL}/book",
        params={"token_id": token_id},
        timeout=20.0,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise TypeError("CLOB order-book response must be an object.")

    return payload


def fetch_market_snapshot_with_raw(
    market: Market,
) -> FetchedMarketSnapshot:
    yes_book = fetch_order_book(market.yes_token_id)
    yes_bid, yes_ask = best_bid_ask_from_book(yes_book)

    # The protocol benchmark depends on the YES book.
    # Freeze the observation time immediately after that
    # required market information has been observed.
    observed_at = datetime.now(UTC)

    no_book: dict[str, Any] | None = None
    no_book_error: str | None = None
    no_bid: float | None = None
    no_ask: float | None = None

    try:
        no_book = fetch_order_book(market.no_token_id)
        no_bid, no_ask = best_bid_ask_from_book(no_book)
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        no_book_error = f"{type(exc).__name__}: {exc}"

    snapshot_id = (
        f"{market.market_id}:"
        f"{observed_at.isoformat(timespec='microseconds')}"
    )

    snapshot = MarketSnapshot(
        snapshot_id=snapshot_id,
        market_id=market.market_id,
        observed_at=observed_at,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
    )

    return FetchedMarketSnapshot(
        snapshot=snapshot,
        yes_book=yes_book,
        no_book=no_book,
        no_book_error=no_book_error,
    )


def fetch_market_snapshot(
    market: Market,
) -> MarketSnapshot:
    return fetch_market_snapshot_with_raw(market).snapshot

