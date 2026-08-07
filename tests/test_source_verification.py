from datetime import UTC, datetime

from forecast_ledger.domain import TimestampQuality
from forecast_ledger.source_verification import (
    extract_publication_candidates,
    verify_source_html,
)

FETCHED_AT = datetime(
    2026,
    8,
    7,
    12,
    0,
    tzinfo=UTC,
)


def test_json_ld_date_published_is_extracted() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@type": "NewsArticle",
          "datePublished": "2026-07-21T10:30:00+00:00"
        }
        </script>
      </head>
    </html>
    """

    candidates = extract_publication_candidates(html)

    assert (
        "jsonld:datePublished",
        "2026-07-21T10:30:00+00:00",
    ) in candidates


def test_verified_datetime_is_preferred() -> None:
    html = """
    <html>
      <head>
        <meta
          property="article:published_time"
          content="2026-07-21T10:30:00+00:00"
        >
      </head>
    </html>
    """

    result = verify_source_html(
        source_url="https://example.com/article",
        html=html,
        fetched_at=FETCHED_AT,
    )

    assert result.published_at == datetime(
        2026,
        7,
        21,
        10,
        30,
        tzinfo=UTC,
    )
    assert (
        result.timestamp_quality
        == TimestampQuality.VERIFIED
    )


def test_date_only_becomes_end_of_day() -> None:
    html = """
    <html>
      <head>
        <meta
          name="datePublished"
          content="2026-07-21"
        >
      </head>
    </html>
    """

    result = verify_source_html(
        source_url="https://example.com/article",
        html=html,
        fetched_at=FETCHED_AT,
    )

    assert result.published_at == datetime(
        2026,
        7,
        21,
        23,
        59,
        59,
        tzinfo=UTC,
    )
    assert (
        result.timestamp_quality
        == TimestampQuality.DATE_ONLY
    )


def test_missing_metadata_becomes_unknown() -> None:
    result = verify_source_html(
        source_url="https://example.com/article",
        html="<html><body>No date.</body></html>",
        fetched_at=FETCHED_AT,
    )

    assert result.published_at is None
    assert (
        result.timestamp_quality
        == TimestampQuality.UNKNOWN
    )


def test_conflicting_dates_become_unknown() -> None:
    html = """
    <html>
      <head>
        <meta
          property="article:published_time"
          content="2026-07-21T10:30:00+00:00"
        >
        <script type="application/ld+json">
        {
          "datePublished": "2026-07-22T10:30:00+00:00"
        }
        </script>
      </head>
    </html>
    """

    result = verify_source_html(
        source_url="https://example.com/article",
        html=html,
        fetched_at=FETCHED_AT,
    )

    assert result.published_at is None
    assert (
        result.timestamp_quality
        == TimestampQuality.UNKNOWN
    )
    assert result.error == (
        "Conflicting publication dates found."
    )
