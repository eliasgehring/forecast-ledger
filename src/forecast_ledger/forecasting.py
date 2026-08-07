from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from openai import OpenAI

from forecast_ledger.domain import EvidenceItem

FORECAST_MODEL = "gpt-5.4-mini-2026-03-17"
FORECAST_REASONING_EFFORT = "medium"

DIRECT_PROMPT_VERSION = "forecast-direct-v0.1"
STRUCTURED_PROMPT_VERSION = "forecast-structured-v0.1"
MARKET_AWARE_PROMPT_VERSION = "forecast-market-aware-v0.1"


class ForecastCondition(str, Enum):
    DIRECT = "B_direct"
    STRUCTURED_INDEPENDENT = "C_structured_independent"
    STRUCTURED_MARKET_AWARE = "D_structured_market_aware"


PROMPT_VERSION_BY_CONDITION = {
    ForecastCondition.DIRECT: DIRECT_PROMPT_VERSION,
    ForecastCondition.STRUCTURED_INDEPENDENT: STRUCTURED_PROMPT_VERSION,
    ForecastCondition.STRUCTURED_MARKET_AWARE: MARKET_AWARE_PROMPT_VERSION,
}


@dataclass(frozen=True)
class ForecastAnalysis:
    condition: ForecastCondition
    probability_yes: float
    reference_class: str | None = None
    estimated_base_rate: float | None = None
    strongest_evidence_yes_id: str | None = None
    strongest_evidence_yes_assessment: str | None = None
    strongest_evidence_no_id: str | None = None
    strongest_evidence_no_assessment: str | None = None
    key_uncertainty: str | None = None


@dataclass(frozen=True)
class ForecastResponse:
    response_id: str
    raw_output: str
    requested_at: datetime
    completed_at: datetime
    prompt: str
    prompt_sha256: str
    analysis: ForecastAnalysis


class ForecastOutputError(ValueError):
    def __init__(
        self,
        message: str,
        response_id: str,
        raw_output: str,
        requested_at: datetime,
        completed_at: datetime,
    ) -> None:
        super().__init__(message)
        self.response_id = response_id
        self.raw_output = raw_output
        self.requested_at = requested_at
        self.completed_at = completed_at


def prompt_version_for_condition(
    condition: ForecastCondition,
) -> str:
    return PROMPT_VERSION_BY_CONDITION[condition]


def _require_probability(
    value: Any,
    field_name: str,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{field_name} must be a number."
        )

    probability = float(value)

    if not 0.0 <= probability <= 1.0:
        raise ValueError(
            f"{field_name} must be between 0 and 1."
        )

    return probability


def _require_nonempty_string(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string."
        )

    return value.strip()


def render_evidence_packet(
    evidence_items: tuple[EvidenceItem, ...],
) -> str:
    payload = []

    for item in evidence_items:
        payload.append(
            {
                "evidence_id": item.evidence_id,
                "source_url": item.source_url,
                "source_name": item.source_name,
                "title": item.title,
                "published_at": item.published_at.isoformat(),
                "timestamp_quality": item.timestamp_quality.value,
                "excerpt": item.excerpt,
            }
        )

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _common_prompt(
    question: str,
    resolution_rules: str,
    evidence_items: tuple[EvidenceItem, ...],
) -> str:
    evidence_json = render_evidence_packet(
        evidence_items
    )

    return f"""
You are producing a probabilistic forecast for a frozen prospective
forecasting experiment.

FORECAST QUESTION:
{question}

RESOLUTION RULES:
{resolution_rules}

FROZEN EVIDENCE PACKET:
{evidence_json}

Probability semantics:
probability_yes means P(the selected Polymarket market resolves YES).

Information rules:
- Treat the frozen evidence packet as the only event-specific factual evidence.
- Do not browse, search, call tools, or request additional information.
- Do not introduce event-specific factual claims that are not supported by the packet.
- General probabilistic reasoning and generic reference-class reasoning are allowed.
- If you refer to a specific evidence item, use only its exact evidence_id.
- Return JSON only.
""".strip()


def build_forecast_prompt(
    condition: ForecastCondition,
    question: str,
    resolution_rules: str,
    evidence_items: tuple[EvidenceItem, ...],
    market_probability: float | None = None,
) -> str:
    common = _common_prompt(
        question=question,
        resolution_rules=resolution_rules,
        evidence_items=evidence_items,
    )

    if condition == ForecastCondition.DIRECT:
        if market_probability is not None:
            raise ValueError(
                "Direct condition must not receive market probability."
            )

        return f"""
{common}

FORECASTING CONDITION:
Give a direct probability forecast with minimal forecasting structure.

Return exactly:
{{
  "probability_yes": 0.0
}}

Do not add additional fields.
""".strip()

    if (
        condition
        == ForecastCondition.STRUCTURED_INDEPENDENT
    ):
        if market_probability is not None:
            raise ValueError(
                "Structured independent condition must not receive "
                "market probability."
            )

        return f"""
{common}

FORECASTING CONDITION:
Use a structured independent forecasting process.

Identify:
1. a relevant reference class;
2. an estimated base rate;
3. the strongest supplied evidence for YES;
4. the strongest supplied evidence for NO;
5. the key uncertainty;
6. a final probability that the market resolves YES.

For strongest evidence fields, use an evidence_id from the frozen packet.
If the packet contains zero evidence items, use null for both evidence fields.

Return exactly:
{{
  "reference_class": "text",
  "estimated_base_rate": 0.0,
  "strongest_evidence_yes": {{
    "evidence_id": "exact evidence id",
    "assessment": "text"
  }},
  "strongest_evidence_no": {{
    "evidence_id": "exact evidence id",
    "assessment": "text"
  }},
  "key_uncertainty": "text",
  "probability_yes": 0.0
}}
""".strip()

    if (
        condition
        == ForecastCondition.STRUCTURED_MARKET_AWARE
    ):
        if market_probability is None:
            raise ValueError(
                "Market-aware condition requires market probability."
            )

        probability = _require_probability(
            market_probability,
            "market_probability",
        )

        return f"""
{common}

CONTEMPORANEOUS MARKET PROBABILITY P(YES):
{probability!r}

FORECASTING CONDITION:
Use the same structured forecasting process as the independent condition,
but additionally incorporate the contemporaneous market probability above.

Identify:
1. a relevant reference class;
2. an estimated base rate;
3. the strongest supplied evidence for YES;
4. the strongest supplied evidence for NO;
5. the key uncertainty;
6. a final probability that the market resolves YES.

For strongest evidence fields, use an evidence_id from the frozen packet.
If the packet contains zero evidence items, use null for both evidence fields.

Return exactly:
{{
  "reference_class": "text",
  "estimated_base_rate": 0.0,
  "strongest_evidence_yes": {{
    "evidence_id": "exact evidence id",
    "assessment": "text"
  }},
  "strongest_evidence_no": {{
    "evidence_id": "exact evidence id",
    "assessment": "text"
  }},
  "key_uncertainty": "text",
  "probability_yes": 0.0
}}
""".strip()

    raise ValueError(
        f"Unsupported forecast condition: {condition}"
    )


def _parse_evidence_reference(
    value: Any,
    field_name: str,
    allowed_ids: set[str],
    evidence_is_empty: bool,
) -> tuple[str | None, str | None]:
    if evidence_is_empty:
        if value is not None:
            raise ValueError(
                f"{field_name} must be null for an empty evidence packet."
            )

        return None, None

    if not isinstance(value, dict):
        raise TypeError(
            f"{field_name} must be an object."
        )

    expected_keys = {
        "evidence_id",
        "assessment",
    }

    if set(value) != expected_keys:
        raise ValueError(
            f"{field_name} must contain exactly "
            "evidence_id and assessment."
        )

    evidence_id = _require_nonempty_string(
        value["evidence_id"],
        f"{field_name}.evidence_id",
    )

    if evidence_id not in allowed_ids:
        raise ValueError(
            f"{field_name} cites evidence outside the frozen packet."
        )

    assessment = _require_nonempty_string(
        value["assessment"],
        f"{field_name}.assessment",
    )

    return evidence_id, assessment


def _validate_all_evidence_ids(
    raw_output: str,
    allowed_ids: set[str],
) -> None:
    cited_ids = set(
        re.findall(
            r"\b[0-9a-fA-F]{64}\b",
            raw_output,
        )
    )

    unknown = {
        evidence_id
        for evidence_id in cited_ids
        if evidence_id not in allowed_ids
    }

    if unknown:
        raise ValueError(
            "Forecast output cites evidence IDs outside "
            f"the frozen packet: {sorted(unknown)}"
        )


def parse_forecast_output(
    condition: ForecastCondition,
    raw_output: str,
    evidence_items: tuple[EvidenceItem, ...],
) -> ForecastAnalysis:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Forecast output is not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError(
            "Forecast output must decode to an object."
        )

    allowed_ids = {
        item.evidence_id
        for item in evidence_items
    }

    _validate_all_evidence_ids(
        raw_output,
        allowed_ids,
    )

    if condition == ForecastCondition.DIRECT:
        if set(payload) != {"probability_yes"}:
            raise ValueError(
                "Direct forecast must contain exactly probability_yes."
            )

        return ForecastAnalysis(
            condition=condition,
            probability_yes=_require_probability(
                payload["probability_yes"],
                "probability_yes",
            ),
        )

    expected_keys = {
        "reference_class",
        "estimated_base_rate",
        "strongest_evidence_yes",
        "strongest_evidence_no",
        "key_uncertainty",
        "probability_yes",
    }

    if set(payload) != expected_keys:
        raise ValueError(
            "Structured forecast output has incorrect fields."
        )

    yes_id, yes_assessment = _parse_evidence_reference(
        payload["strongest_evidence_yes"],
        "strongest_evidence_yes",
        allowed_ids,
        not evidence_items,
    )

    no_id, no_assessment = _parse_evidence_reference(
        payload["strongest_evidence_no"],
        "strongest_evidence_no",
        allowed_ids,
        not evidence_items,
    )

    return ForecastAnalysis(
        condition=condition,
        probability_yes=_require_probability(
            payload["probability_yes"],
            "probability_yes",
        ),
        reference_class=_require_nonempty_string(
            payload["reference_class"],
            "reference_class",
        ),
        estimated_base_rate=_require_probability(
            payload["estimated_base_rate"],
            "estimated_base_rate",
        ),
        strongest_evidence_yes_id=yes_id,
        strongest_evidence_yes_assessment=yes_assessment,
        strongest_evidence_no_id=no_id,
        strongest_evidence_no_assessment=no_assessment,
        key_uncertainty=_require_nonempty_string(
            payload["key_uncertainty"],
            "key_uncertainty",
        ),
    )


def analysis_to_json(
    analysis: ForecastAnalysis,
) -> str:
    payload: dict[str, Any] = {
        "condition": analysis.condition.value,
        "probability_yes": analysis.probability_yes,
    }

    if analysis.condition != ForecastCondition.DIRECT:
        payload.update(
            {
                "reference_class": analysis.reference_class,
                "estimated_base_rate": analysis.estimated_base_rate,
                "strongest_evidence_yes_id": (
                    analysis.strongest_evidence_yes_id
                ),
                "strongest_evidence_yes_assessment": (
                    analysis.strongest_evidence_yes_assessment
                ),
                "strongest_evidence_no_id": (
                    analysis.strongest_evidence_no_id
                ),
                "strongest_evidence_no_assessment": (
                    analysis.strongest_evidence_no_assessment
                ),
                "key_uncertainty": analysis.key_uncertainty,
            }
        )

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def create_forecast(
    client: OpenAI,
    condition: ForecastCondition,
    question: str,
    resolution_rules: str,
    evidence_items: tuple[EvidenceItem, ...],
    market_probability: float | None = None,
    model: str = FORECAST_MODEL,
    reasoning_effort: str = FORECAST_REASONING_EFFORT,
) -> ForecastResponse:
    if model != FORECAST_MODEL:
        raise ValueError(
            "Scored forecasts require the frozen model snapshot."
        )

    if reasoning_effort != FORECAST_REASONING_EFFORT:
        raise ValueError(
            "Scored forecasts require reasoning effort medium."
        )

    prompt = build_forecast_prompt(
        condition=condition,
        question=question,
        resolution_rules=resolution_rules,
        evidence_items=evidence_items,
        market_probability=market_probability,
    )

    prompt_sha256 = hashlib.sha256(
        prompt.encode("utf-8")
    ).hexdigest()

    requested_at = datetime.now(UTC)

    response = client.responses.create(
        model=model,
        reasoning={
            "effort": reasoning_effort,
        },
        input=prompt,
    )

    completed_at = datetime.now(UTC)
    raw_output = response.output_text or ""

    if not raw_output:
        raise ForecastOutputError(
            "Forecast response contained no output text.",
            response_id=response.id,
            raw_output=raw_output,
            requested_at=requested_at,
            completed_at=completed_at,
        )

    try:
        analysis = parse_forecast_output(
            condition=condition,
            raw_output=raw_output,
            evidence_items=evidence_items,
        )
    except (TypeError, ValueError) as exc:
        raise ForecastOutputError(
            str(exc),
            response_id=response.id,
            raw_output=raw_output,
            requested_at=requested_at,
            completed_at=completed_at,
        ) from exc

    return ForecastResponse(
        response_id=response.id,
        raw_output=raw_output,
        requested_at=requested_at,
        completed_at=completed_at,
        prompt=prompt,
        prompt_sha256=prompt_sha256,
        analysis=analysis,
    )
