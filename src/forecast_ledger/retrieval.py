import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from forecast_ledger.domain import (
    EvidenceItem,
    TimestampQuality,
)

RETRIEVAL_PROMPT_VERSION = "retrieval-v0.1"


@dataclass(frozen=True)
class RetrievalCandidate:
    source_url: str
    source_name: str
    title: str
    published_at: datetime
    excerpt: str
    timestamp_quality: TimestampQuality


@dataclass(frozen=True)
class RetrievalResponse:
    response_id: str
    raw_output: str
    retrieved_at: datetime
    candidates: tuple[RetrievalCandidate, ...]
    source_urls: tuple[str, ...] = ()


class RetrievalOutputError(ValueError):
    def __init__(
        self,
        message: str,
        response_id: str,
        raw_output: str,
    ) -> None:
        super().__init__(message)
        self.response_id = response_id
        self.raw_output = raw_output


def build_retrieval_prompt(
    question: str,
    resolution_rules: str,
    information_cutoff: datetime,
) -> str:
    if (
        information_cutoff.tzinfo is None
        or information_cutoff.utcoffset() is None
    ):
        raise ValueError(
            "information_cutoff must be timezone-aware."
        )

    return f"""
You are constructing a frozen evidence packet for a prospective
forecasting experiment.

Forecast question:
{question}

Resolution rules:
{resolution_rules}

INFORMATION CUTOFF:
{information_cutoff.isoformat()}

Search the public web for information relevant to estimating whether
this market will resolve YES.

Critical temporal rule:
Only return evidence that was published at or before the information
cutoff. Do not use or summarize information published after that time.

Do not search for, mention, infer, or return prediction-market prices,
Polymarket probabilities, betting odds, market odds, or crowd forecasts.

Return JSON only with this exact top-level structure:

{{
  "evidence": [
    {{
      "source_url": "https://...",
      "source_name": "publisher or organization",
      "title": "source title",
      "published_at": "ISO-8601 datetime or YYYY-MM-DD",
      "timestamp_quality": "verified|reported|date_only|unknown",
      "excerpt": "brief factual excerpt or faithful summary relevant to the forecast"
    }}
  ]
}}

Timestamp rules:
- verified: publication datetime is explicitly available from the source.
- reported: a publication datetime is reported but not independently verified.
- date_only: only a publication date is available.
- unknown: publication time cannot be established.
- Do not invent publication timestamps.
- Prefer primary sources and high-quality reporting.
- Return at most 10 evidence items.
- Evidence may be empty.
""".strip()


def parse_publication_time(
    value: str,
    timestamp_quality: TimestampQuality,
) -> datetime:
    if timestamp_quality == TimestampQuality.DATE_ONLY:
        publication_date = date.fromisoformat(value)

        return datetime.combine(
            publication_date,
            time(23, 59, 59),
            tzinfo=UTC,
        )

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            "Non-date-only publication timestamps "
            "must be timezone-aware."
        )

    return parsed


def _require_nonempty_string(
    raw: dict[str, Any],
    field_name: str,
) -> str:
    value = raw.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string."
        )

    return value.strip()


def parse_retrieval_output(
    raw_output: str,
) -> tuple[RetrievalCandidate, ...]:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Retrieval output is not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError(
            "Retrieval output must decode to an object."
        )

    raw_evidence = payload.get("evidence")

    if not isinstance(raw_evidence, list):
        raise TypeError(
            "Retrieval output must contain an evidence list."
        )

    candidates: list[RetrievalCandidate] = []

    for raw_item in raw_evidence:
        if not isinstance(raw_item, dict):
            raise TypeError(
                "Each retrieval evidence item must be an object."
            )

        source_url = _require_nonempty_string(
            raw_item,
            "source_url",
        )

        parsed_url = urlparse(source_url)

        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError(
                "Evidence source_url must use http or https."
            )

        timestamp_quality = TimestampQuality(
            _require_nonempty_string(
                raw_item,
                "timestamp_quality",
            )
        )

        published_at = parse_publication_time(
            _require_nonempty_string(
                raw_item,
                "published_at",
            ),
            timestamp_quality,
        )

        candidates.append(
            RetrievalCandidate(
                source_url=source_url,
                source_name=_require_nonempty_string(
                    raw_item,
                    "source_name",
                ),
                title=_require_nonempty_string(
                    raw_item,
                    "title",
                ),
                published_at=published_at,
                excerpt=_require_nonempty_string(
                    raw_item,
                    "excerpt",
                ),
                timestamp_quality=timestamp_quality,
            )
        )

    return tuple(candidates)


def extract_web_search_source_urls(
    response_payload: dict[str, Any],
) -> tuple[str, ...]:
    urls: list[str] = []

    output = response_payload.get("output", [])

    if not isinstance(output, list):
        return ()

    for item in output:
        if not isinstance(item, dict):
            continue

        if item.get("type") != "web_search_call":
            continue

        action = item.get("action")

        if not isinstance(action, dict):
            continue

        sources = action.get("sources", [])

        if not isinstance(sources, list):
            continue

        for source in sources:
            if not isinstance(source, dict):
                continue

            url = source.get("url")

            if isinstance(url, str) and url:
                urls.append(url)

    return tuple(dict.fromkeys(urls))


def _source_key(url: str) -> tuple[str, str]:
    parsed = urlparse(url)

    return (
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
    )


def validate_candidate_sources(
    candidates: tuple[RetrievalCandidate, ...],
    source_urls: tuple[str, ...],
) -> None:
    source_keys = {
        _source_key(url)
        for url in source_urls
    }

    for candidate in candidates:
        if _source_key(candidate.source_url) not in source_keys:
            raise ValueError(
                "Retrieval candidate URL was not present "
                "in the web-search source list."
            )


def retrieve_evidence(
    client: OpenAI,
    model: str,
    question: str,
    resolution_rules: str,
    information_cutoff: datetime,
) -> RetrievalResponse:
    prompt = build_retrieval_prompt(
        question=question,
        resolution_rules=resolution_rules,
        information_cutoff=information_cutoff,
    )

    response = client.responses.create(
        model=model,
        tools=[
            {
                "type": "web_search",
            }
        ],
        include=[
            "web_search_call.action.sources",
        ],
        input=prompt,
    )

    retrieved_at = datetime.now(UTC)
    raw_output = response.output_text or ""

    if not raw_output:
        raise RetrievalOutputError(
            "Retrieval response contained no output text.",
            response_id=response.id,
            raw_output=raw_output,
        )

    response_payload = response.model_dump()

    source_urls = extract_web_search_source_urls(
        response_payload
    )

    try:
        candidates = parse_retrieval_output(
            raw_output
        )

        validate_candidate_sources(
            candidates,
            source_urls,
        )
    except (TypeError, ValueError) as exc:
        raise RetrievalOutputError(
            str(exc),
            response_id=response.id,
            raw_output=raw_output,
        ) from exc

    return RetrievalResponse(
        response_id=response.id,
        raw_output=raw_output,
        retrieved_at=retrieved_at,
        candidates=candidates,
        source_urls=source_urls,
    )


def accepted_evidence_items(
    retrieval: RetrievalResponse,
    information_cutoff: datetime,
) -> tuple[EvidenceItem, ...]:
    accepted: list[EvidenceItem] = []

    for index, candidate in enumerate(
        retrieval.candidates
    ):
        if (
            candidate.timestamp_quality
            == TimestampQuality.UNKNOWN
        ):
            continue

        if candidate.published_at > information_cutoff:
            continue

        evidence_id_material = (
            f"{retrieval.response_id}|"
            f"{index}|"
            f"{candidate.source_url}"
        )

        evidence_id = hashlib.sha256(
            evidence_id_material.encode("utf-8")
        ).hexdigest()

        accepted.append(
            EvidenceItem(
                evidence_id=evidence_id,
                source_url=candidate.source_url,
                source_name=candidate.source_name,
                title=candidate.title,
                published_at=candidate.published_at,
                retrieved_at=retrieval.retrieved_at,
                excerpt=candidate.excerpt,
                timestamp_quality=candidate.timestamp_quality,
            )
        )

    return tuple(accepted)
