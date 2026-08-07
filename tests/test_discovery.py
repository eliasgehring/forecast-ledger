import json
from datetime import UTC, datetime

import pytest

from forecast_ledger import discovery
from forecast_ledger.discovery import (
    candidate_from_event_market,
    extract_event_tag_slugs,
)


def make_event() -> dict:
    return {
        "id": "event-1",
        "title": "GPT-6 released by...?",
        "slug": "gpt-6-released-by",
        "tags": [
            {
                "label": "Artificial Intelligence",
                "slug": "artificial-intelligence",
            },
            {
                "label": "Technology",
                "slug": "technology",
            },
        ],
    }


def make_market() -> dict:
    return {
        "id": "market-1",
        "question": "Will GPT-6 be released by August 31, 2026?",
        "description": (
            "Resolves YES if GPT-6 is publicly released before the deadline."
        ),
        "endDate": "2026-08-31T00:00:00Z",
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
    }


def test_extract_event_tag_slugs() -> None:
    tags = extract_event_tag_slugs(make_event())

    assert tags == (
        "artificial-intelligence",
        "technology",
    )


def test_candidate_keeps_event_metadata_separate_from_market() -> None:
    candidate = candidate_from_event_market(
        event=make_event(),
        raw_market=make_market(),
    )

    assert candidate.market.market_id == "market-1"
    assert candidate.event_id == "event-1"
    assert candidate.event_title == "GPT-6 released by...?"
    assert candidate.tag_slugs == (
        "artificial-intelligence",
        "technology",
    )


def test_extract_event_tag_slugs_rejects_wrong_shape() -> None:
    event = make_event()
    event["tags"] = "technology"

    with pytest.raises(TypeError, match="Event tags must be a list"):
        extract_event_tag_slugs(event)


def test_candidate_preserves_market_close_time() -> None:
    candidate = candidate_from_event_market(
        event=make_event(),
        raw_market=make_market(),
    )

    assert candidate.market.close_time == datetime(
        2026,
        8,
        31,
        0,
        0,
        tzinfo=UTC,
    )


def test_discovery_exhausts_all_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_1 = make_event()
    event_1["id"] = "event-1"

    market_1 = make_market()
    market_1["id"] = "market-1"
    event_1["markets"] = [market_1]

    event_2 = make_event()
    event_2["id"] = "event-2"

    market_2 = make_market()
    market_2["id"] = "market-2"
    event_2["markets"] = [market_2]

    calls: list[str | None] = []

    def fake_fetch_event_page(
        limit: int = 100,
        after_cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        calls.append(after_cursor)

        if after_cursor is None:
            return [event_1], "cursor-1"

        if after_cursor == "cursor-1":
            return [event_2], None

        raise AssertionError("Unexpected cursor.")

    monkeypatch.setattr(
        discovery,
        "fetch_event_page",
        fake_fetch_event_page,
    )

    report = discovery.discover_time_window_candidates(
        evaluated_at=datetime(
            2026,
            8,
            7,
            9,
            0,
            tzinfo=UTC,
        ),
    )

    assert [candidate.market.market_id for candidate in report.candidates] == [
        "market-1",
        "market-2",
    ]
    assert calls == [None, "cursor-1"]


def test_discovery_rejects_repeated_pagination_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()
    event["markets"] = [make_market()]

    def fake_fetch_event_page(
        limit: int = 100,
        after_cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        return [event], "cursor-1"

    monkeypatch.setattr(
        discovery,
        "fetch_event_page",
        fake_fetch_event_page,
    )

    with pytest.raises(
        RuntimeError,
        match="repeated cursor",
    ):
        discovery.discover_time_window_candidates(
            evaluated_at=datetime(
                2026,
                8,
                7,
                9,
                0,
                tzinfo=UTC,
            ),
        )


def test_discovery_records_unparseable_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()
    bad_market = make_market()
    bad_market["outcomes"] = "not-json"
    event["markets"] = [bad_market]

    def fake_fetch_event_page(
        limit: int = 100,
        after_cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        return [event], None

    monkeypatch.setattr(
        discovery,
        "fetch_event_page",
        fake_fetch_event_page,
    )

    report = discovery.discover_time_window_candidates(
        evaluated_at=datetime(
            2026,
            8,
            7,
            9,
            0,
            tzinfo=UTC,
        ),
    )

    assert report.candidates == ()
    assert report.raw_markets_seen == 1
    assert report.parsed_markets == 0
    assert len(report.issues) == 1
    assert report.issues[0].market_id == "market-1"
