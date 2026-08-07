from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from forecast_ledger.domain import require_timezone_aware

CHECKPOINT_TOLERANCE = timedelta(hours=6)


class Checkpoint(str, Enum):
    DAYS_14 = "14d"
    DAYS_7 = "7d"
    DAYS_3 = "3d"
    DAYS_1 = "1d"


CHECKPOINT_OFFSETS: dict[Checkpoint, timedelta] = {
    Checkpoint.DAYS_14: timedelta(days=14),
    Checkpoint.DAYS_7: timedelta(days=7),
    Checkpoint.DAYS_3: timedelta(days=3),
    Checkpoint.DAYS_1: timedelta(days=1),
}


@dataclass(frozen=True)
class DueCheckpoint:
    checkpoint: Checkpoint
    scheduled_at: datetime
    observed_at: datetime
    offset_from_schedule: timedelta


def find_due_checkpoint(
    close_time: datetime,
    observed_at: datetime,
) -> DueCheckpoint | None:
    """
    Return the checkpoint whose +/- 6 hour window contains observed_at.

    This function applies to markets already enrolled in the experiment.
    It intentionally does not apply the 5-day enrollment lower bound.
    """
    require_timezone_aware(close_time, "close_time")
    require_timezone_aware(observed_at, "observed_at")

    matches: list[DueCheckpoint] = []

    for checkpoint, horizon in CHECKPOINT_OFFSETS.items():
        scheduled_at = close_time - horizon
        offset = observed_at - scheduled_at

        if abs(offset) <= CHECKPOINT_TOLERANCE:
            matches.append(
                DueCheckpoint(
                    checkpoint=checkpoint,
                    scheduled_at=scheduled_at,
                    observed_at=observed_at,
                    offset_from_schedule=offset,
                )
            )

    if len(matches) > 1:
        raise RuntimeError(
            "Checkpoint windows unexpectedly overlap."
        )

    if not matches:
        return None

    return matches[0]
