import json
from datetime import UTC, datetime

import pytest

from forecast_ledger.domain import TimestampQuality
from forecast_ledger.retrieval import (
    RetrievalResponse,
    accepted_evidence_items,
    build_retrieval_prompt,
    parse_publication_time,
    parse_retrieval_output,
)

CUTOFF = datetime(
    2026,
    8,
    7,
    11,
    2,
    52,
    tzinfo=UTC,
)


def test_prompt_contains_cutoff_and_no_market_prices() -> None:
    prompt = build_retrieval_prompt(
        question="Will example happen?",
        resolution_rules="Resolves YES if example happens.",
        information_cutoff=CUTOFF,
    )

    assert CUTOFF.isoformat() in prompt
    assert "Do not search for" in prompt
    assert "Polymarket probabilities" in prompt


def test_parse_valid_retrieval_output() -> None:
    raw = json.dumps(
        {
            "evidence": [
                {
                    "source_url": "https://example.com/a",
                    "source_name": "Example",
                    "title": "Example title",
                    "published_at": "2026-08-07T09:00:00+00:00",
                    "timestamp_quality": "verified",
                    "excerpt": "Relevant evidence.",
                }
            ]
        }
    )

    candidates = parse_retrieval_output(raw)

    assert len(candidates) == 1
    assert candidates[0].timestamp_quality == TimestampQuality.VERIFIED
    assert candidates[0].published_at == datetime(
        2026,
        8,
        7,
        9,
        0,
        tzinfo=UTC,
    )


def test_date_only_is_conservatively_end_of_day() -> None:
    parsed = parse_publication_time(
        "2026-08-07",
        TimestampQuality.DATE_ONLY,
    )

    assert parsed == datetime(
        2026,
        8,
        7,
        23,
        59,
        59,
        tzinfo=UTC,
    )


def test_future_evidence_is_removed_after_retrieval() -> None:
    retrieval = RetrievalResponse(
        response_id="resp-1",
        raw_output="{}",
        retrieved_at=datetime(
            2026,
            8,
            7,
            11,
            10,
            tzinfo=UTC,
        ),
        candidates=parse_retrieval_output(
            json.dumps(
                {
                    "evidence": [
                        {
                            "source_url": "https://example.com/past",
                            "source_name": "Example",
                            "title": "Past",
                            "published_at": (
                                "2026-08-07T10:00:00+00:00"
                            ),
                            "timestamp_quality": "verified",
                            "excerpt": "Past evidence.",
                        },
                        {
                            "source_url": "https://example.com/future",
                            "source_name": "Example",
                            "title": "Future",
                            "published_at": (
                                "2026-08-07T12:00:00+00:00"
                            ),
                            "timestamp_quality": "verified",
                            "excerpt": "Future evidence.",
                        },
                    ]
                }
            )
        ),
    )

    accepted = accepted_evidence_items(
        retrieval,
        CUTOFF,
    )

    assert len(accepted) == 1
    assert accepted[0].title == "Past"


def test_same_day_date_only_evidence_is_rejected_before_midnight() -> None:
    retrieval = RetrievalResponse(
        response_id="resp-1",
        raw_output="{}",
        retrieved_at=datetime(
            2026,
            8,
            7,
            11,
            10,
            tzinfo=UTC,
        ),
        candidates=parse_retrieval_output(
            json.dumps(
                {
                    "evidence": [
                        {
                            "source_url": "https://example.com/a",
                            "source_name": "Example",
                            "title": "Same day",
                            "published_at": "2026-08-07",
                            "timestamp_quality": "date_only",
                            "excerpt": "Evidence.",
                        }
                    ]
                }
            )
        ),
    )

    accepted = accepted_evidence_items(
        retrieval,
        CUTOFF,
    )

    assert accepted == ()


def test_unknown_timestamp_is_removed() -> None:
    retrieval = RetrievalResponse(
        response_id="resp-1",
        raw_output="{}",
        retrieved_at=datetime(
            2026,
            8,
            7,
            11,
            10,
            tzinfo=UTC,
        ),
        candidates=parse_retrieval_output(
            json.dumps(
                {
                    "evidence": [
                        {
                            "source_url": "https://example.com/a",
                            "source_name": "Example",
                            "title": "Unknown",
                            "published_at": (
                                "2026-08-01T00:00:00+00:00"
                            ),
                            "timestamp_quality": "unknown",
                            "excerpt": "Evidence.",
                        }
                    ]
                }
            )
        ),
    )

    assert accepted_evidence_items(
        retrieval,
        CUTOFF,
    ) == ()


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="not valid JSON",
    ):
        parse_retrieval_output(
            '{"evidence": ['
        )
