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


def test_discovery_classifies_non_binary_as_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()
    market = make_market()
    market["outcomes"] = json.dumps(
        ["Candidate A", "Candidate B", "Candidate C"]
    )
    event["markets"] = [market]

    monkeypatch.setattr(
        discovery,
        "fetch_event_page",
        lambda limit=100, after_cursor=None: ([event], None),
    )

    report = discovery.discover_time_window_candidates(
        evaluated_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )

    assert report.excluded_non_binary == 1
    assert report.issues == ()
    assert report.parsed_markets == 0


def test_discovery_classifies_missing_close_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()
    market = make_market()
    del market["endDate"]
    event["markets"] = [market]

    monkeypatch.setattr(
        discovery,
        "fetch_event_page",
        lambda limit=100, after_cursor=None: ([event], None),
    )

    report = discovery.discover_time_window_candidates(
        evaluated_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )

    assert report.excluded_missing_close_time == 1
    assert report.issues == ()
    assert report.parsed_markets == 0


def test_discovery_classifies_missing_clob_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()
    market = make_market()
    del market["clobTokenIds"]
    event["markets"] = [market]

    monkeypatch.setattr(
        discovery,
        "fetch_event_page",
        lambda limit=100, after_cursor=None: ([event], None),
    )

    report = discovery.discover_time_window_candidates(
        evaluated_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )

    assert report.excluded_missing_clob_token_ids == 1
    assert report.issues == ()
    assert report.parsed_markets == 0


def test_discovery_accounting_reconciles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = make_event()

    valid = make_market()

    non_binary = make_market()
    non_binary["id"] = "non-binary"
    non_binary["outcomes"] = json.dumps(["A", "B", "C"])

    missing_close = make_market()
    missing_close["id"] = "missing-close"
    del missing_close["endDate"]

    missing_tokens = make_market()
    missing_tokens["id"] = "missing-tokens"
    del missing_tokens["clobTokenIds"]

    malformed = make_market()
    malformed["id"] = "malformed"
    malformed["outcomes"] = "not-json"

    event["markets"] = [
        valid,
        non_binary,
        missing_close,
        missing_tokens,
        malformed,
    ]

    monkeypatch.setattr(
        discovery,
        "fetch_event_page",
        lambda limit=100, after_cursor=None: ([event], None),
    )

    report = discovery.discover_time_window_candidates(
        evaluated_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )

    accounted = (
        report.parsed_markets
        + report.excluded_non_binary
        + report.excluded_missing_close_time
        + report.excluded_missing_clob_token_ids
        + len(report.issues)
    )

    assert accounted == report.raw_markets_seen
    assert report.parsed_markets == (
        report.outside_time_window
        + len(report.candidates)
    )


def test_fetch_event_page_retries_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    calls = 0

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "events": [],
                "next_cursor": None,
            }

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1

        if calls == 1:
            raise httpx.RemoteProtocolError(
                "temporary disconnect"
            )

        return FakeResponse()

    monkeypatch.setattr(
        discovery.httpx,
        "get",
        fake_get,
    )
    monkeypatch.setattr(
        discovery.time,
        "sleep",
        lambda seconds: None,
    )

    events, cursor = discovery.fetch_event_page()

    assert events == []
    assert cursor is None
    assert calls == 2
