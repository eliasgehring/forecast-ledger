import json
from datetime import datetime
from typing import Any

import httpx

from forecast_ledger.domain import Market


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


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
