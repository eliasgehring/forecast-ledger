import json
from datetime import UTC, datetime

import pytest

from forecast_ledger.domain import TimestampQuality
from forecast_ledger.retrieval import (
    RetrievalResponse,
    build_retrieval_prompt,
    parse_publication_time,
    parse_retrieval_output,
    verified_evidence_items,
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


def _single_candidate_retrieval() -> RetrievalResponse:
    return RetrievalResponse(
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
                            "title": "Example",
                            "published_at": (
                                "2026-08-07T12:00:00+00:00"
                            ),
                            "timestamp_quality": "verified",
                            "excerpt": "Evidence.",
                        }
                    ]
                }
            )
        ),
    )


def test_verified_source_timestamp_overrides_model_timestamp() -> None:
    from forecast_ledger.source_verification import VerifiedSource

    retrieval = _single_candidate_retrieval()

    source = VerifiedSource(
        source_url="https://example.com/a",
        fetched_at=datetime(
            2026,
            8,
            7,
            11,
            10,
            tzinfo=UTC,
        ),
        content_sha256="abc",
        published_at=datetime(
            2026,
            8,
            7,
            10,
            0,
            tzinfo=UTC,
        ),
        timestamp_quality=TimestampQuality.VERIFIED,
        verification_method="jsonld:datePublished",
        error=None,
    )

    items, audits = verified_evidence_items(
        retrieval,
        CUTOFF,
        fetcher=lambda _: source,
    )

    assert len(items) == 1
    assert items[0].published_at == source.published_at
    assert items[0].published_at != retrieval.candidates[0].published_at
    assert audits[0].accepted is True


def test_verified_future_source_is_rejected() -> None:
    from forecast_ledger.source_verification import VerifiedSource

    retrieval = _single_candidate_retrieval()

    source = VerifiedSource(
        source_url="https://example.com/a",
        fetched_at=datetime(
            2026,
            8,
            7,
            11,
            10,
            tzinfo=UTC,
        ),
        content_sha256="abc",
        published_at=datetime(
            2026,
            8,
            7,
            12,
            0,
            tzinfo=UTC,
        ),
        timestamp_quality=TimestampQuality.VERIFIED,
        verification_method="jsonld:datePublished",
        error=None,
    )

    items, audits = verified_evidence_items(
        retrieval,
        CUTOFF,
        fetcher=lambda _: source,
    )

    assert items == ()
    assert audits[0].accepted is False


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="not valid JSON",
    ):
        parse_retrieval_output(
            '{"evidence": ['
        )


def test_naive_verified_candidate_datetime_is_downgraded_to_date_only():
    raw_output = """
    {
      "evidence": [
        {
          "source_url": "https://example.com/source",
          "source_name": "Example",
          "title": "Example title",
          "published_at": "2026-06-24T09:47:00",
          "timestamp_quality": "verified",
          "excerpt": "Relevant evidence."
        }
      ]
    }
    """

    candidates = parse_retrieval_output(raw_output)

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate.timestamp_quality == TimestampQuality.DATE_ONLY
    assert candidate.published_at == datetime(
        2026,
        6,
        24,
        23,
        59,
        59,
        tzinfo=UTC,
    )


def test_timezone_aware_verified_candidate_preserves_exact_datetime():
    raw_output = """
    {
      "evidence": [
        {
          "source_url": "https://example.com/source",
          "source_name": "Example",
          "title": "Example title",
          "published_at": "2026-06-24T09:47:00+03:00",
          "timestamp_quality": "verified",
          "excerpt": "Relevant evidence."
        }
      ]
    }
    """

    candidate = parse_retrieval_output(raw_output)[0]

    assert candidate.timestamp_quality == TimestampQuality.VERIFIED
    assert candidate.published_at.isoformat() == (
        "2026-06-24T09:47:00+03:00"
    )
