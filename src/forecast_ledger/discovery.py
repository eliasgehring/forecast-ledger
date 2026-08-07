from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from forecast_ledger.domain import Market
from forecast_ledger.polymarket import GAMMA_BASE_URL, market_from_gamma


@dataclass(frozen=True)
class MarketCandidate:
    market: Market
    event_id: str
    event_title: str
    event_slug: str
    tag_slugs: tuple[str, ...]


def extract_event_tag_slugs(event: dict[str, Any]) -> tuple[str, ...]:
    raw_tags = event.get("tags", [])

    if not isinstance(raw_tags, list):
        raise TypeError("Event tags must be a list.")

    slugs: list[str] = []

    for raw_tag in raw_tags:
        if not isinstance(raw_tag, dict):
            raise TypeError("Each event tag must be an object.")

        slug = raw_tag.get("slug")

        if isinstance(slug, str) and slug:
            slugs.append(slug)

    return tuple(slugs)


def candidate_from_event_market(
    event: dict[str, Any],
    raw_market: dict[str, Any],
) -> MarketCandidate:
    market = market_from_gamma(raw_market)

    return MarketCandidate(
        market=market,
        event_id=str(event["id"]),
        event_title=str(event["title"]),
        event_slug=str(event["slug"]),
        tag_slugs=extract_event_tag_slugs(event),
    )


def fetch_event_page(
    limit: int = 100,
    after_cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, str | int] = {
        "closed": "false",
        "limit": limit,
    }

    if after_cursor is not None:
        params["after_cursor"] = after_cursor

    response = httpx.get(
        f"{GAMMA_BASE_URL}/events/keyset",
        params=params,
        timeout=20.0,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise TypeError("Gamma event response must be an object.")

    events = payload.get("events")

    if not isinstance(events, list):
        raise TypeError("Gamma event response must contain an events list.")

    cursor = payload.get("next_cursor")

    if cursor is not None and not isinstance(cursor, str):
        raise TypeError("next_cursor must be a string or null.")

    return events, cursor


def discover_time_window_candidates(
    evaluated_at: datetime | None = None,
    minimum_days: float = 5.0,
    maximum_days: float = 45.0,
) -> list[MarketCandidate]:
    if evaluated_at is None:
        evaluated_at = datetime.now(UTC)

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware.")

    candidates: list[MarketCandidate] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()

    while True:
        events, next_cursor = fetch_event_page(
            limit=100,
            after_cursor=cursor,
        )

        for event in events:
            raw_markets = event.get("markets", [])

            if not isinstance(raw_markets, list):
                continue

            for raw_market in raw_markets:
                if not isinstance(raw_market, dict):
                    continue

                try:
                    candidate = candidate_from_event_market(
                        event=event,
                        raw_market=raw_market,
                    )
                except (KeyError, TypeError, ValueError):
                    continue

                days_to_close = (
                    candidate.market.close_time - evaluated_at
                ).total_seconds() / 86_400.0

                if minimum_days <= days_to_close <= maximum_days:
                    candidates.append(candidate)

        if next_cursor is None:
            break

        if next_cursor in seen_cursors:
            raise RuntimeError(
                "Gamma pagination returned a repeated cursor."
            )

        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return candidates
