import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from forecast_ledger.domain import (
    EvidenceItem,
    TimestampQuality,
)
from forecast_ledger.forecasting import (
    FORECAST_MODEL,
    ForecastCondition,
    ForecastOutputError,
    build_forecast_prompt,
    create_forecast,
    parse_forecast_output,
    render_evidence_packet,
)


def make_evidence() -> tuple[EvidenceItem, ...]:
    return (
        EvidenceItem(
            evidence_id="a" * 64,
            source_url="https://example.com/a",
            source_name="Example",
            title="Example evidence",
            published_at=datetime(
                2026, 8, 1, 12, tzinfo=UTC
            ),
            retrieved_at=datetime(
                2026, 8, 7, 16, tzinfo=UTC
            ),
            excerpt="A relevant frozen fact.",
            timestamp_quality=TimestampQuality.VERIFIED,
        ),
    )


def test_b_and_c_do_not_receive_market_probability() -> None:
    evidence = make_evidence()
    sentinel = 0.314159265

    prompt_b = build_forecast_prompt(
        condition=ForecastCondition.DIRECT,
        question="Will X happen?",
        resolution_rules="YES if X happens.",
        evidence_items=evidence,
    )

    prompt_c = build_forecast_prompt(
        condition=ForecastCondition.STRUCTURED_INDEPENDENT,
        question="Will X happen?",
        resolution_rules="YES if X happens.",
        evidence_items=evidence,
    )

    assert str(sentinel) not in prompt_b
    assert str(sentinel) not in prompt_c
    assert "CONTEMPORANEOUS MARKET PROBABILITY" not in prompt_b
    assert "CONTEMPORANEOUS MARKET PROBABILITY" not in prompt_c

    with pytest.raises(ValueError):
        build_forecast_prompt(
            condition=ForecastCondition.DIRECT,
            question="Will X happen?",
            resolution_rules="YES if X happens.",
            evidence_items=evidence,
            market_probability=sentinel,
        )

    with pytest.raises(ValueError):
        build_forecast_prompt(
            condition=ForecastCondition.STRUCTURED_INDEPENDENT,
            question="Will X happen?",
            resolution_rules="YES if X happens.",
            evidence_items=evidence,
            market_probability=sentinel,
        )


def test_d_receives_exact_market_probability() -> None:
    prompt = build_forecast_prompt(
        condition=ForecastCondition.STRUCTURED_MARKET_AWARE,
        question="Will X happen?",
        resolution_rules="YES if X happens.",
        evidence_items=make_evidence(),
        market_probability=0.32,
    )

    assert "CONTEMPORANEOUS MARKET PROBABILITY P(YES):" in prompt
    assert "\n0.32\n" in prompt


def test_all_conditions_receive_same_frozen_evidence() -> None:
    evidence = make_evidence()
    rendered = render_evidence_packet(evidence)

    prompts = (
        build_forecast_prompt(
            ForecastCondition.DIRECT,
            "Will X happen?",
            "YES if X happens.",
            evidence,
        ),
        build_forecast_prompt(
            ForecastCondition.STRUCTURED_INDEPENDENT,
            "Will X happen?",
            "YES if X happens.",
            evidence,
        ),
        build_forecast_prompt(
            ForecastCondition.STRUCTURED_MARKET_AWARE,
            "Will X happen?",
            "YES if X happens.",
            evidence,
            market_probability=0.32,
        ),
    )

    assert all(rendered in prompt for prompt in prompts)


def test_direct_output_is_only_probability_yes() -> None:
    analysis = parse_forecast_output(
        ForecastCondition.DIRECT,
        '{"probability_yes":0.61}',
        make_evidence(),
    )

    assert analysis.probability_yes == 0.61

    with pytest.raises(ValueError):
        parse_forecast_output(
            ForecastCondition.DIRECT,
            '{"probability_yes":0.61,"reason":"extra"}',
            make_evidence(),
        )


def test_structured_output_requires_packet_evidence_ids() -> None:
    payload = {
        "reference_class": "Product releases",
        "estimated_base_rate": 0.4,
        "strongest_evidence_yes": {
            "evidence_id": "b" * 64,
            "assessment": "Supports YES.",
        },
        "strongest_evidence_no": {
            "evidence_id": "a" * 64,
            "assessment": "Supports NO.",
        },
        "key_uncertainty": "Timing.",
        "probability_yes": 0.55,
    }

    with pytest.raises(ValueError):
        parse_forecast_output(
            ForecastCondition.STRUCTURED_INDEPENDENT,
            json.dumps(payload),
            make_evidence(),
        )


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_test",
            output_text='{"probability_yes":0.42}',
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_model_request_is_frozen_and_has_no_tools() -> None:
    client = FakeClient()

    response = create_forecast(
        client=client,
        condition=ForecastCondition.DIRECT,
        question="Will X happen?",
        resolution_rules="YES if X happens.",
        evidence_items=make_evidence(),
    )

    assert response.analysis.probability_yes == 0.42
    assert client.responses.kwargs["model"] == FORECAST_MODEL
    assert client.responses.kwargs["reasoning"] == {
        "effort": "medium"
    }
    assert "tools" not in client.responses.kwargs


def test_moving_model_alias_is_rejected() -> None:
    with pytest.raises(ValueError):
        create_forecast(
            client=FakeClient(),
            condition=ForecastCondition.DIRECT,
            question="Will X happen?",
            resolution_rules="YES if X happens.",
            evidence_items=make_evidence(),
            model="gpt-5.4-mini",
        )


def test_malformed_output_becomes_forecast_output_error() -> None:
    client = FakeClient()
    client.responses.create = lambda **kwargs: SimpleNamespace(
        id="resp_bad",
        output_text="not-json",
    )

    with pytest.raises(ForecastOutputError):
        create_forecast(
            client=client,
            condition=ForecastCondition.DIRECT,
            question="Will X happen?",
            resolution_rules="YES if X happens.",
            evidence_items=make_evidence(),
        )
