from forecast_ledger.ops import (
    OperationsStatus,
    print_status,
)


def test_operations_status_keeps_distinct_denominators(
    capsys,
) -> None:
    status = OperationsStatus(
        tracked_markets=100,
        checkpoint_statuses={
            "snapshot_recorded": 20,
            "checkpoint_unavailable": 80,
        },
        included_checkpoints=12,
        matched_checkpoints=8,
        blocked_checkpoints=2,
        interrupted_checkpoints=1,
        partial_forecasts=1,
        primary_included=6,
        primary_matched=4,
        primary_resolved_scored=3,
        unique_included_markets=9,
        included_event_clusters=5,
    )

    print_status(status)

    output = capsys.readouterr().out

    assert "included checkpoints:     12" in output
    assert "unique included markets:  9" in output
    assert "included event clusters:  5" in output
    assert "resolved + scored:        3" in output
