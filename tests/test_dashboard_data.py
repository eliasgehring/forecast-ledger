import sqlite3

import pytest

from forecast_ledger.dashboard_data import (
    load_checkpoint_status_counts,
    load_matched_forecasts,
    load_overview,
    open_read_only_connection,
)


def make_db(tmp_path):
    path = tmp_path / "ledger.db"
    con = sqlite3.connect(path)

    con.executescript(
        """
        CREATE TABLE tracked_markets (
            market_id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            protocol_version TEXT NOT NULL
        );

        CREATE TABLE checkpoint_records (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE market_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            yes_bid REAL NOT NULL,
            yes_ask REAL NOT NULL
        );

        CREATE TABLE forecasts (
            forecast_id TEXT PRIMARY KEY,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            condition TEXT NOT NULL,
            packet_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            model TEXT NOT NULL,
            probability_yes REAL NOT NULL
        );

        CREATE TABLE evidence_packets (
            packet_id TEXT PRIMARY KEY,
            protocol_version TEXT NOT NULL
        );

        CREATE TABLE evidence_packet_validations (
            packet_id TEXT PRIMARY KEY,
            status TEXT NOT NULL
        );

        CREATE TABLE forecast_attempts (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL
        );
        """
    )

    con.execute(
        """
        INSERT INTO tracked_markets
        VALUES ('m1', 'Will X happen?', 'v0.2')
        """
    )

    con.execute(
        """
        INSERT INTO checkpoint_records
        VALUES ('m1', '14d', 'v0.2', 'snapshot_recorded')
        """
    )

    con.execute(
        """
        INSERT INTO market_snapshots
        VALUES (
            's1',
            'm1',
            '14d',
            'v0.2',
            '2026-08-07T15:50:00+00:00',
            0.31,
            0.33
        )
        """
    )

    forecasts = (
        (
            "f1",
            "B_direct",
            0.96,
        ),
        (
            "f2",
            "C_structured_independent",
            0.82,
        ),
        (
            "f3",
            "D_structured_market_aware",
            0.59,
        ),
    )

    for forecast_id, condition, probability in forecasts:
        con.execute(
            """
            INSERT INTO forecasts
            VALUES (
                ?,
                'm1',
                '14d',
                'v0.2',
                ?,
                'p1',
                's1',
                'gpt-5.4-mini-2026-03-17',
                ?
            )
            """,
            (
                forecast_id,
                condition,
                probability,
            ),
        )

    con.execute(
        """
        INSERT INTO evidence_packets
        VALUES ('p1', 'v0.2')
        """
    )

    con.execute(
        """
        INSERT INTO evidence_packet_validations
        VALUES ('p1', 'valid')
        """
    )

    for _ in range(3):
        con.execute(
            """
            INSERT INTO forecast_attempts
            VALUES ('m1', '14d', 'v0.2')
            """
        )

    con.commit()
    con.close()

    return path


def test_connection_is_read_only(tmp_path):
    path = make_db(tmp_path)

    con = open_read_only_connection(path)

    with pytest.raises(
        sqlite3.OperationalError,
        match="readonly",
    ):
        con.execute(
            "CREATE TABLE should_fail (x INTEGER)"
        )

    con.close()


def test_overview_counts_real_entities(tmp_path):
    path = make_db(tmp_path)

    overview = load_overview(path)

    assert overview == {
        "markets": 1,
        "checkpoints": 1,
        "snapshots": 1,
        "forecasts": 3,
        "matched_forecasts": 1,
        "valid_packets": 1,
        "forecast_attempts": 3,
    }


def test_checkpoint_status_counts(tmp_path):
    path = make_db(tmp_path)

    rows = load_checkpoint_status_counts(path)

    assert rows == [
        {
            "status": "snapshot_recorded",
            "count": 1,
        }
    ]


def test_matched_forecast_preserves_probability_semantics(
    tmp_path,
):
    path = make_db(tmp_path)

    rows = load_matched_forecasts(path)

    assert len(rows) == 1

    row = rows[0]

    assert row["market_probability"] == 0.32
    assert row["direct_probability"] == 0.96
    assert row["structured_probability"] == 0.82
    assert row["market_aware_probability"] == 0.59
    assert row["packet_id"] == "p1"
    assert row["snapshot_id"] == "s1"


def test_mismatched_packet_is_not_called_matched(
    tmp_path,
):
    path = make_db(tmp_path)

    con = sqlite3.connect(path)

    con.execute(
        """
        UPDATE forecasts
        SET packet_id = 'different-packet'
        WHERE condition = 'D_structured_market_aware'
        """
    )

    con.commit()
    con.close()

    assert load_matched_forecasts(path) == []
