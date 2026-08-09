from __future__ import annotations

import math

LOG_LOSS_EPSILON = 0.000001


def _require_probability(
    probability_yes: float,
) -> float:
    probability = float(
        probability_yes
    )

    if not math.isfinite(probability):
        raise ValueError(
            "Probability must be finite."
        )

    if not 0.0 <= probability <= 1.0:
        raise ValueError(
            "Probability must be between 0 and 1."
        )

    return probability


def brier_score(
    probability_yes: float,
    outcome_yes: bool,
) -> float:
    probability = _require_probability(
        probability_yes
    )

    outcome = (
        1.0
        if outcome_yes
        else 0.0
    )

    return (
        probability - outcome
    ) ** 2


def log_loss(
    probability_yes: float,
    outcome_yes: bool,
) -> float:
    probability = _require_probability(
        probability_yes
    )

    clipped = min(
        max(
            probability,
            LOG_LOSS_EPSILON,
        ),
        1.0 - LOG_LOSS_EPSILON,
    )

    if outcome_yes:
        return -math.log(clipped)

    return -math.log(
        1.0 - clipped
    )


def directional_accuracy(
    probability_yes: float,
    outcome_yes: bool,
) -> bool | None:
    probability = _require_probability(
        probability_yes
    )

    if probability == 0.5:
        return None

    predicts_yes = probability > 0.5

    return predicts_yes == outcome_yes
