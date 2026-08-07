import json

from forecast_ledger.categories import (
    ProtocolCategory,
    classify_candidate,
    filter_protocol_categories,
)
from forecast_ledger.discovery import candidate_from_event_market


def make_candidate(
    tag_slugs: list[str],
):
    event = {
        "id": "event-1",
        "title": "Example event",
        "slug": "example-event",
        "tags": [
            {
                "label": slug,
                "slug": slug,
            }
            for slug in tag_slugs
        ],
    }

    market = {
        "id": "market-1",
        "question": "Will example event happen?",
        "description": "Resolves YES if the event happens.",
        "endDate": "2026-08-31T00:00:00Z",
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps(
            [
                "yes-token",
                "no-token",
            ]
        ),
    }

    return candidate_from_event_market(
        event=event,
        raw_market=market,
    )


def test_ai_tag_maps_to_technology() -> None:
    result = classify_candidate(
        make_candidate(["ai"])
    )

    assert result.included is True
    assert result.categories == (
        ProtocolCategory.TECHNOLOGY,
    )
    assert result.matched_tags == ("ai",)


def test_geopolitics_maps_exactly() -> None:
    result = classify_candidate(
        make_candidate(
            [
                "politics",
                "world",
                "geopolitics",
            ]
        )
    )

    assert result.categories == (
        ProtocolCategory.GEOPOLITICS,
    )
    assert result.matched_tags == (
        "geopolitics",
    )


def test_election_tags_do_not_enter_protocol() -> None:
    result = classify_candidate(
        make_candidate(
            [
                "politics",
                "elections",
                "primary-elections",
            ]
        )
    )

    assert result.included is False
    assert result.categories == ()
    assert result.matched_tags == ()


def test_economy_is_not_silently_treated_as_business() -> None:
    result = classify_candidate(
        make_candidate(["economy"])
    )

    assert result.included is False


def test_candidate_can_match_multiple_protocol_categories() -> None:
    result = classify_candidate(
        make_candidate(
            [
                "ai",
                "business",
            ]
        )
    )

    assert result.categories == (
        ProtocolCategory.TECHNOLOGY,
        ProtocolCategory.BUSINESS,
    )


def test_filter_protocol_categories_removes_nonmatching_candidates() -> None:
    technology = make_candidate(["tech"])
    election = make_candidate(["elections"])

    results = filter_protocol_categories(
        (
            technology,
            election,
        )
    )

    assert len(results) == 1
    assert results[0].candidate == technology
