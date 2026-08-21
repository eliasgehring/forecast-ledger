import sqlite3
from dataclasses import asdict

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from forecast_ledger.api import create_app
from forecast_ledger.dashboard_data import (
    open_read_only_connection,
)
from forecast_ledger.results import (
    load_primary_results,
)


def make_results_db(
    tmp_path,
):
    db_path = (
        tmp_path
        / "forecast_ledger.db"
    )

    connection = sqlite3.connect(
        db_path
    )

    connection.executescript(
        """
        CREATE TABLE tracked_markets (
            market_id TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            question TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_title TEXT NOT NULL,
            event_slug TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            tag_slugs_json TEXT NOT NULL
        );

        CREATE TABLE market_resolutions (
            market_id TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            outcome_yes INTEGER,
            resolution_status TEXT NOT NULL
        );

        CREATE TABLE market_snapshots (
            snapshot_id TEXT NOT NULL,
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            yes_bid REAL NOT NULL,
            yes_ask REAL NOT NULL
        );

        CREATE TABLE forecasts (
            market_id TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            protocol_version TEXT NOT NULL,
            condition TEXT NOT NULL,
            packet_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            model TEXT NOT NULL,
            probability_yes REAL NOT NULL
        );
        """
    )

    for market_id in (
        "matched",
        "incomplete",
    ):
        connection.execute(
            """
            INSERT INTO tracked_markets (
                market_id,
                protocol_version,
                question,
                event_id,
                event_title,
                event_slug,
                categories_json,
                tag_slugs_json
            )
            VALUES (
                ?,
                'v0.2',
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                market_id,
                f"Question {market_id}?",
                f"event-{market_id}",
                f"Event {market_id}",
                f"event-{market_id}",
                '["technology"]',
                '["test"]',
            ),
        )

        connection.execute(
            """
            INSERT INTO market_resolutions (
                market_id,
                protocol_version,
                outcome_yes,
                resolution_status
            )
            VALUES (
                ?,
                'v0.2',
                0,
                'resolved_no'
            )
            """,
            (market_id,),
        )

        connection.execute(
            """
            INSERT INTO market_snapshots (
                snapshot_id,
                market_id,
                checkpoint,
                protocol_version,
                yes_bid,
                yes_ask
            )
            VALUES (
                ?,
                ?,
                '7d',
                'v0.2',
                0.19,
                0.21
            )
            """,
            (
                f"snapshot-{market_id}",
                market_id,
            ),
        )

    matched_forecasts = (
        ("B_direct", 0.10),
        (
            "C_structured_independent",
            0.15,
        ),
        (
            "D_structured_market_aware",
            0.12,
        ),
    )

    for condition, probability in (
        matched_forecasts
    ):
        connection.execute(
            """
            INSERT INTO forecasts (
                market_id,
                checkpoint,
                protocol_version,
                condition,
                packet_id,
                snapshot_id,
                model,
                probability_yes
            )
            VALUES (
                'matched',
                '7d',
                'v0.2',
                ?,
                'packet-matched',
                'snapshot-matched',
                'fixed-model',
                ?
            )
            """,
            (
                condition,
                probability,
            ),
        )

    for condition, probability in (
        matched_forecasts[:2]
    ):
        connection.execute(
            """
            INSERT INTO forecasts (
                market_id,
                checkpoint,
                protocol_version,
                condition,
                packet_id,
                snapshot_id,
                model,
                probability_yes
            )
            VALUES (
                'incomplete',
                '7d',
                'v0.2',
                ?,
                'packet-incomplete',
                'snapshot-incomplete',
                'fixed-model',
                ?
            )
            """,
            (
                condition,
                probability,
            ),
        )

    connection.commit()
    connection.close()

    return db_path


def test_health_declares_read_only(
    tmp_path,
) -> None:
    db_path = make_results_db(
        tmp_path
    )

    client = TestClient(
        create_app(db_path)
    )

    response = client.get(
        "/api/health"
    )

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
        "protocol_version": "v0.2",
        "database_exists": True,
        "read_only": True,
    }


def test_primary_api_exactly_matches_results_engine(
    tmp_path,
) -> None:
    db_path = make_results_db(
        tmp_path
    )

    connection = (
        open_read_only_connection(
            db_path
        )
    )

    try:
        expected_rows, expected_summary = (
            load_primary_results(
                connection
            )
        )
    finally:
        connection.close()

    client = TestClient(
        create_app(db_path)
    )

    response = client.get(
        "/api/results/primary"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["summary"] == (
        jsonable_encoder(
            asdict(expected_summary)
        )
    )

    assert payload["rows"] == (
        jsonable_encoder(
            [
                asdict(row)
                for row in expected_rows
            ]
        )
    )


def test_incomplete_forecast_set_is_not_scored(
    tmp_path,
) -> None:
    db_path = make_results_db(
        tmp_path
    )

    client = TestClient(
        create_app(db_path)
    )

    payload = client.get(
        "/api/results/primary"
    ).json()

    assert payload["summary"]["n"] == 1

    assert [
        row["market_id"]
        for row in payload["rows"]
    ] == ["matched"]


def test_api_has_no_write_route(
    tmp_path,
) -> None:
    db_path = make_results_db(
        tmp_path
    )

    client = TestClient(
        create_app(db_path)
    )

    response = client.post(
        "/api/overview"
    )

    assert response.status_code == 405


def test_database_connection_is_physically_read_only(
    tmp_path,
) -> None:
    db_path = make_results_db(
        tmp_path
    )

    connection = (
        open_read_only_connection(
            db_path
        )
    )

    try:
        with pytest.raises(
            sqlite3.OperationalError
        ):
            connection.execute(
                """
                CREATE TABLE forbidden (
                    value INTEGER
                )
                """
            )
    finally:
        connection.close()


def test_market_detail_composes_existing_read_models(
    tmp_path,
    monkeypatch,
) -> None:
    import forecast_ledger.api as api_module

    db_path = tmp_path / "forecast_ledger.db"
    db_path.touch()

    detail = {
        "market_id": "m1",
        "checkpoint": "7d",
        "packet_id": "packet-1",
        "question": "Question?",
    }

    evidence = [
        {
            "evidence_id": "e1",
            "position": 1,
        }
    ]

    forecasts = [
        {
            "condition": "B_direct",
            "probability_yes": 0.2,
        }
    ]

    attempts = {
        "retrieval": [],
        "forecasts": [],
    }

    verifications = [
        {
            "position": 1,
            "accepted": True,
        }
    ]

    monkeypatch.setattr(
        api_module,
        "load_checkpoint_detail",
        lambda **_: detail,
    )

    monkeypatch.setattr(
        api_module,
        "load_checkpoint_evidence",
        lambda **_: evidence,
    )

    monkeypatch.setattr(
        api_module,
        "load_checkpoint_forecast_details",
        lambda **_: forecasts,
    )

    monkeypatch.setattr(
        api_module,
        "load_checkpoint_attempt_audit",
        lambda **_: attempts,
    )

    def load_verifications(
        *,
        db_path,
        packet_id,
    ):
        assert packet_id == "packet-1"
        return verifications

    monkeypatch.setattr(
        api_module,
        "load_source_verifications_for_packet",
        load_verifications,
    )

    client = TestClient(
        create_app(db_path)
    )

    response = client.get(
        "/api/markets/m1/7d"
    )

    assert response.status_code == 200

    assert response.json() == {
        "protocol_version": "v0.2",
        "market": detail,
        "evidence": evidence,
        "forecasts": forecasts,
        "attempts": attempts,
        "source_verifications": verifications,
    }
