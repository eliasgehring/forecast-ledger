import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from html.parser import HTMLParser
from typing import Any

import httpx

from forecast_ledger.domain import TimestampQuality

PUBLICATION_META_KEYS = {
    "article:published_time",
    "datepublished",
    "date",
    "publishdate",
    "publish-date",
    "pubdate",
}

MODIFICATION_META_KEYS = {
    "article:modified_time",
    "datemodified",
    "modified",
    "lastmod",
    "last-modified",
}


@dataclass(frozen=True)
class VerifiedSource:
    source_url: str
    fetched_at: datetime
    content_sha256: str
    published_at: datetime | None
    timestamp_quality: TimestampQuality
    verification_method: str | None
    error: str | None
    modified_at: datetime | None = None
    modification_method: str | None = None
    modification_error: str | None = None


class PublicationMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta_values: list[tuple[str, str]] = []
        self.time_values: list[str] = []
        self.json_ld_blocks: list[str] = []
        self._inside_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attrs_dict = {
            key.lower(): value
            for key, value in attrs
            if value is not None
        }

        if tag == "meta":
            key = (
                attrs_dict.get("property")
                or attrs_dict.get("name")
                or attrs_dict.get("itemprop")
            )
            content = attrs_dict.get("content")

            if key and content:
                self.meta_values.append(
                    (key.lower(), content.strip())
                )

        if tag == "time":
            value = attrs_dict.get("datetime")

            if value:
                self.time_values.append(value.strip())

        if tag == "script":
            script_type = attrs_dict.get("type", "").lower()

            if script_type == "application/ld+json":
                self._inside_json_ld = True
                self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._inside_json_ld:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside_json_ld:
            self.json_ld_blocks.append(
                "".join(self._json_ld_parts).strip()
            )
            self._inside_json_ld = False
            self._json_ld_parts = []


def parse_source_timestamp(
    value: str,
) -> tuple[datetime, TimestampQuality]:
    value = value.strip()

    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        parsed_date = None

    if (
        parsed_date is not None
        and value == parsed_date.isoformat()
    ):
        return (
            datetime.combine(
                parsed_date,
                time(23, 59, 59),
                tzinfo=UTC,
            ),
            TimestampQuality.DATE_ONLY,
        )

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported publication timestamp: {value}"
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            "Publication datetime is timezone-naive."
        )

    return parsed, TimestampQuality.VERIFIED


def _json_ld_values(
    value: Any,
    target_key: str,
) -> list[str]:
    values: list[str] = []

    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() == target_key.lower():
                if isinstance(nested, str):
                    values.append(nested)
            else:
                values.extend(
                    _json_ld_values(
                        nested,
                        target_key,
                    )
                )

    elif isinstance(value, list):
        for nested in value:
            values.extend(
                _json_ld_values(
                    nested,
                    target_key,
                )
            )

    return values


def _extract_candidates(
    html: str,
    meta_keys: set[str],
    json_ld_key: str,
    include_time_tags: bool,
) -> tuple[tuple[str, str], ...]:
    parser = PublicationMetadataParser()
    parser.feed(html)

    candidates: list[tuple[str, str]] = []

    for key, value in parser.meta_values:
        if key in meta_keys:
            candidates.append(
                (f"meta:{key}", value)
            )

    for block in parser.json_ld_blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue

        for value in _json_ld_values(
            payload,
            json_ld_key,
        ):
            candidates.append(
                (f"jsonld:{json_ld_key}", value)
            )

    if include_time_tags:
        for value in parser.time_values:
            candidates.append(
                ("time:datetime", value)
            )

    return tuple(candidates)


def extract_publication_candidates(
    html: str,
) -> tuple[tuple[str, str], ...]:
    return _extract_candidates(
        html=html,
        meta_keys=PUBLICATION_META_KEYS,
        json_ld_key="datePublished",
        include_time_tags=True,
    )


def extract_modification_candidates(
    html: str,
) -> tuple[tuple[str, str], ...]:
    return _extract_candidates(
        html=html,
        meta_keys=MODIFICATION_META_KEYS,
        json_ld_key="dateModified",
        include_time_tags=False,
    )


def _choose_timestamp(
    candidates: tuple[tuple[str, str], ...],
    conflict_message: str,
) -> tuple[
    datetime | None,
    TimestampQuality,
    str | None,
    str | None,
]:
    parsed_candidates: list[
        tuple[str, datetime, TimestampQuality]
    ] = []

    for method, raw_value in candidates:
        try:
            timestamp, quality = parse_source_timestamp(
                raw_value
            )
        except ValueError:
            continue

        parsed_candidates.append(
            (
                method,
                timestamp,
                quality,
            )
        )

    if not parsed_candidates:
        return (
            None,
            TimestampQuality.UNKNOWN,
            None,
            None,
        )

    distinct_dates = {
        candidate[1].date()
        for candidate in parsed_candidates
    }

    if len(distinct_dates) != 1:
        return (
            None,
            TimestampQuality.UNKNOWN,
            None,
            conflict_message,
        )

    verified_candidates = [
        candidate
        for candidate in parsed_candidates
        if candidate[2] == TimestampQuality.VERIFIED
    ]

    chosen = (
        verified_candidates[0]
        if verified_candidates
        else parsed_candidates[0]
    )

    return (
        chosen[1],
        chosen[2],
        chosen[0],
        None,
    )


def verify_source_html(
    source_url: str,
    html: str,
    fetched_at: datetime,
) -> VerifiedSource:
    content_sha256 = hashlib.sha256(
        html.encode("utf-8")
    ).hexdigest()

    (
        published_at,
        timestamp_quality,
        verification_method,
        publication_error,
    ) = _choose_timestamp(
        extract_publication_candidates(html),
        "Conflicting publication dates found.",
    )

    if published_at is None:
        return VerifiedSource(
            source_url=source_url,
            fetched_at=fetched_at,
            content_sha256=content_sha256,
            published_at=None,
            timestamp_quality=TimestampQuality.UNKNOWN,
            verification_method=None,
            error=(
                publication_error
                or "No usable publication metadata found."
            ),
        )

    (
        modified_at,
        _,
        modification_method,
        modification_error,
    ) = _choose_timestamp(
        extract_modification_candidates(html),
        "Conflicting modification dates found.",
    )

    return VerifiedSource(
        source_url=source_url,
        fetched_at=fetched_at,
        content_sha256=content_sha256,
        published_at=published_at,
        timestamp_quality=timestamp_quality,
        verification_method=verification_method,
        error=None,
        modified_at=modified_at,
        modification_method=modification_method,
        modification_error=modification_error,
    )


def fetch_and_verify_source(
    source_url: str,
) -> VerifiedSource:
    response = httpx.get(
        source_url,
        timeout=20.0,
        follow_redirects=True,
    )
    response.raise_for_status()

    fetched_at = datetime.now(UTC)

    return verify_source_html(
        source_url=str(response.url),
        html=response.text,
        fetched_at=fetched_at,
    )
