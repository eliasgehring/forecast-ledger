from datetime import UTC, datetime, timedelta

import pytest

from forecast_ledger.checkpoints import (
    Checkpoint,
    find_due_checkpoint,
)

CLOSE_TIME = datetime(
    2026,
    8,
    31,
    12,
    0,
    tzinfo=UTC,
)


@pytest.mark.parametrize(
    ("days_before_close", "expected_checkpoint"),
    [
        (14, Checkpoint.DAYS_14),
        (7, Checkpoint.DAYS_7),
        (3, Checkpoint.DAYS_3),
        (1, Checkpoint.DAYS_1),
    ],
)
def test_exact_checkpoint_is_due(
    days_before_close: int,
    expected_checkpoint: Checkpoint,
) -> None:
    observed_at = CLOSE_TIME - timedelta(
        days=days_before_close
    )

    result = find_due_checkpoint(
        close_time=CLOSE_TIME,
        observed_at=observed_at,
    )

    assert result is not None
    assert result.checkpoint == expected_checkpoint
    assert result.offset_from_schedule == timedelta(0)


def test_three_day_checkpoint_remains_valid_after_enrollment() -> None:
    observed_at = CLOSE_TIME - timedelta(days=3)

    result = find_due_checkpoint(
        close_time=CLOSE_TIME,
        observed_at=observed_at,
    )

    assert result is not None
    assert result.checkpoint == Checkpoint.DAYS_3


@pytest.mark.parametrize(
    "offset",
    [
        timedelta(hours=-6),
        timedelta(hours=6),
    ],
)
def test_six_hour_boundary_is_inclusive(
    offset: timedelta,
) -> None:
    scheduled_at = CLOSE_TIME - timedelta(days=7)

    result = find_due_checkpoint(
        close_time=CLOSE_TIME,
        observed_at=scheduled_at + offset,
    )

    assert result is not None
    assert result.checkpoint == Checkpoint.DAYS_7


@pytest.mark.parametrize(
    "offset",
    [
        timedelta(hours=-6, seconds=-1),
        timedelta(hours=6, seconds=1),
    ],
)
def test_outside_six_hour_window_is_not_due(
    offset: timedelta,
) -> None:
    scheduled_at = CLOSE_TIME - timedelta(days=7)

    result = find_due_checkpoint(
        close_time=CLOSE_TIME,
        observed_at=scheduled_at + offset,
    )

    assert result is None


def test_unrelated_time_has_no_due_checkpoint() -> None:
    result = find_due_checkpoint(
        close_time=CLOSE_TIME,
        observed_at=CLOSE_TIME - timedelta(days=10),
    )

    assert result is None


def test_naive_observed_time_is_rejected() -> None:
    observed_at = datetime(
        2026,
        8,
        24,
        12,
        0,
        tzinfo=UTC,
    ).replace(tzinfo=None)

    with pytest.raises(
        ValueError,
        match="observed_at must be timezone-aware",
    ):
        find_due_checkpoint(
            close_time=CLOSE_TIME,
            observed_at=observed_at,
        )
