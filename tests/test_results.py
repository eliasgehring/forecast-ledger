import sqlite3

import pytest

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.results import (
    load_primary_results,
    load_scored_checkpoints,
    summarize_scored_checkpoints,
)


def make_connection() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")

    con.executescript(
        """
        CREATE TABLE tracked_markets (
            market_id TEXT,
            protocol_version TEXT,
            question TEXT
        );

        CREATE TABLE market_snapshots (
            snapshot_id TEXT,
            market_id TEXT,
            checkpoint TEXT,
            protocol_version TEXT,
            yes_bid REAL,
            yes_ask REAL
        );

        CREATE TABLE forecasts (
            market_id TEXT,
            checkpoint TEXT,
            protocol_version TEXT,
            condition TEXT,
            packet_id TEXT,
            snapshot_id TEXT,
            model TEXT,
            probability_yes REAL
        );

        CREATE TABLE market_resolutions (
            market_id TEXT,
            protocol_version TEXT,
            outcome_yes INTEGER,
            resolution_status TEXT
        );
        """
    )

    return con


def insert_matched(
    con: sqlite3.Connection,
    *,
    market_id: str,
    checkpoint: str,
    outcome_yes: bool,
    packet_id: str = "packet-1",
) -> None:
    con.execute(
        """
        INSERT INTO tracked_markets
        VALUES (?, 'v0.2', ?)
        """,
        (
            market_id,
            f"Question {market_id}",
        ),
    )

    snapshot_id = (
        f"snapshot-{market_id}-{checkpoint}"
    )

    con.execute(
        """
        INSERT INTO market_snapshots
        VALUES (
            ?, ?, ?, 'v0.2', 0.58, 0.62
        )
        """,
        (
            snapshot_id,
            market_id,
            checkpoint,
        ),
    )

    forecasts = (
        ("B_direct", 0.70),
        (
            "C_structured_independent",
            0.80,
        ),
        (
            "D_structured_market_aware",
            0.65,
        ),
    )

    for condition, probability in forecasts:
        con.execute(
            """
            INSERT INTO forecasts
            VALUES (
                ?, ?, 'v0.2', ?, ?, ?, 'model',
                ?
            )
            """,
            (
                market_id,
                checkpoint,
                condition,
                packet_id,
                snapshot_id,
                probability,
            ),
        )

    con.execute(
        """
        INSERT INTO market_resolutions
        VALUES (?, 'v0.2', ?, ?)
        """,
        (
            market_id,
            int(outcome_yes),
            (
                "resolved_yes"
                if outcome_yes
                else "resolved_no"
            ),
        ),
    )

    con.commit()


def test_scores_matched_resolved_checkpoint() -> None:
    con = make_connection()

    insert_matched(
        con,
        market_id="m1",
        checkpoint="7d",
        outcome_yes=True,
    )

    rows = load_scored_checkpoints(
        con,
        checkpoint=Checkpoint.DAYS_7,
    )

    assert len(rows) == 1

    row = rows[0]

    assert row.market_probability == pytest.approx(
        0.60
    )
    assert row.market_brier == pytest.approx(
        0.16
    )
    assert row.direct_brier == pytest.approx(
        0.09
    )
    assert row.structured_brier == pytest.approx(
        0.04
    )
    assert row.market_aware_brier == pytest.approx(
        0.1225
    )

    assert row.structured_advantage == pytest.approx(
        0.05
    )

    assert (
        row.market_information_advantage
        == pytest.approx(-0.0825)
    )


def test_mismatched_packet_is_not_scored() -> None:
    con = make_connection()

    insert_matched(
        con,
        market_id="m1",
        checkpoint="7d",
        outcome_yes=True,
    )

    con.execute(
        """
        UPDATE forecasts
        SET packet_id = 'different-packet'
        WHERE market_id = 'm1'
          AND condition =
              'D_structured_market_aware'
        """
    )
    con.commit()

    rows = load_scored_checkpoints(
        con,
        checkpoint=Checkpoint.DAYS_7,
    )

    assert rows == ()


def test_invalid_resolution_is_not_scored() -> None:
    con = make_connection()

    insert_matched(
        con,
        market_id="m1",
        checkpoint="7d",
        outcome_yes=True,
    )

    con.execute(
        """
        UPDATE market_resolutions
        SET
            outcome_yes = NULL,
            resolution_status = 'invalid'
        WHERE market_id = 'm1'
        """
    )
    con.commit()

    rows = load_scored_checkpoints(
        con,
        checkpoint=Checkpoint.DAYS_7,
    )

    assert rows == ()


def test_primary_results_use_only_7d() -> None:
    con = make_connection()

    insert_matched(
        con,
        market_id="seven",
        checkpoint="7d",
        outcome_yes=True,
        packet_id="packet-seven",
    )

    insert_matched(
        con,
        market_id="fourteen",
        checkpoint="14d",
        outcome_yes=False,
        packet_id="packet-fourteen",
    )

    rows, summary = load_primary_results(
        con
    )

    assert len(rows) == 1
    assert rows[0].market_id == "seven"
    assert summary.n == 1


def test_summary_preserves_paired_advantage() -> None:
    con = make_connection()

    insert_matched(
        con,
        market_id="m1",
        checkpoint="7d",
        outcome_yes=True,
    )

    rows = load_scored_checkpoints(
        con,
        checkpoint=Checkpoint.DAYS_7,
    )

    summary = summarize_scored_checkpoints(
        rows
    )

    assert summary.n == 1

    assert (
        summary.mean_structured_advantage
        == pytest.approx(0.05)
    )


def test_empty_summary_reports_no_fake_metrics() -> None:
    summary = summarize_scored_checkpoints(
        ()
    )

    assert summary.n == 0
    assert summary.mean_direct_brier is None
    assert summary.mean_structured_brier is None
