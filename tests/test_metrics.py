import math

import pytest

from forecast_ledger.metrics import (
    LOG_LOSS_EPSILON,
    brier_score,
    directional_accuracy,
    log_loss,
)


def test_brier_yes() -> None:
    assert brier_score(
        0.8,
        True,
    ) == pytest.approx(0.04)


def test_brier_no() -> None:
    assert brier_score(
        0.8,
        False,
    ) == pytest.approx(0.64)


def test_log_loss_uses_protocol_clip() -> None:
    assert log_loss(
        0.0,
        True,
    ) == pytest.approx(
        -math.log(
            LOG_LOSS_EPSILON
        )
    )

    assert log_loss(
        1.0,
        False,
    ) == pytest.approx(
        -math.log(
            LOG_LOSS_EPSILON
        )
    )


def test_directional_accuracy() -> None:
    assert directional_accuracy(
        0.8,
        True,
    ) is True

    assert directional_accuracy(
        0.8,
        False,
    ) is False

    assert directional_accuracy(
        0.2,
        False,
    ) is True


def test_exact_half_has_no_direction() -> None:
    assert (
        directional_accuracy(
            0.5,
            True,
        )
        is None
    )


@pytest.mark.parametrize(
    "probability",
    (-0.01, 1.01, float("nan")),
)
def test_invalid_probability_rejected(
    probability: float,
) -> None:
    with pytest.raises(ValueError):
        brier_score(
            probability,
            True,
        )
