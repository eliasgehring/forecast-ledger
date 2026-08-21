from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.dashboard_data import (
    load_checkpoint_attempt_audit,
    load_checkpoint_detail,
    load_checkpoint_evidence,
    load_checkpoint_forecast_details,
    load_included_pipeline_rows,
    load_overview,
    load_research_funnel,
    load_source_verifications_for_packet,
    open_read_only_connection,
)
from forecast_ledger.registry import PROTOCOL_VERSION
from forecast_ledger.results import (
    load_primary_results,
    load_scored_checkpoints,
    summarize_scored_checkpoints,
)

DEFAULT_DB_PATH = Path(
    os.environ.get(
        "FORECAST_LEDGER_DB",
        "data/forecast_ledger.db",
    )
)


def _require_database(
    db_path: Path,
) -> None:
    if not db_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Forecast Ledger database "
                "was not found."
            ),
        )


def _results_payload(
    rows,
    summary,
) -> dict:
    return jsonable_encoder(
        {
            "protocol_version": (
                PROTOCOL_VERSION
            ),
            "summary": asdict(summary),
            "rows": [
                asdict(row)
                for row in rows
            ],
        }
    )


def create_app(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> FastAPI:
    path = Path(db_path)

    app = FastAPI(
        title="Forecast Ledger API",
        version="0.1.0",
        description=(
            "Read-only presentation API for "
            "the Forecast Ledger experiment."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "protocol_version": (
                PROTOCOL_VERSION
            ),
            "database_exists": (
                path.exists()
            ),
            "read_only": True,
        }

    @app.get("/api/overview")
    def overview() -> dict:
        _require_database(path)

        return {
            "protocol_version": (
                PROTOCOL_VERSION
            ),
            "overview": load_overview(
                path
            ),
        }

    @app.get("/api/funnel")
    def funnel() -> dict:
        _require_database(path)

        return {
            "protocol_version": (
                PROTOCOL_VERSION
            ),
            "funnel": load_research_funnel(
                path
            ),
        }

    @app.get("/api/markets")
    def markets() -> dict:
        _require_database(path)

        rows = load_included_pipeline_rows(
            path
        )

        return {
            "protocol_version": (
                PROTOCOL_VERSION
            ),
            "count": len(rows),
            "rows": rows,
        }

    @app.get(
        "/api/markets/{market_id}/{checkpoint}"
    )
    def market_checkpoint(
        market_id: str,
        checkpoint: Checkpoint,
    ) -> dict:
        _require_database(path)

        detail = load_checkpoint_detail(
            db_path=path,
            market_id=market_id,
            checkpoint=checkpoint.value,
        )

        if detail is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Market checkpoint "
                    "was not found."
                ),
            )

        evidence = load_checkpoint_evidence(
            db_path=path,
            market_id=market_id,
            checkpoint=checkpoint.value,
        )

        forecasts = (
            load_checkpoint_forecast_details(
                db_path=path,
                market_id=market_id,
                checkpoint=checkpoint.value,
            )
        )

        attempts = (
            load_checkpoint_attempt_audit(
                db_path=path,
                market_id=market_id,
                checkpoint=checkpoint.value,
            )
        )

        packet_id = detail.get(
            "packet_id"
        )

        source_verifications = (
            []
            if not packet_id
            else load_source_verifications_for_packet(
                db_path=path,
                packet_id=packet_id,
            )
        )

        return {
            "protocol_version": (
                PROTOCOL_VERSION
            ),
            "market": detail,
            "evidence": evidence,
            "forecasts": forecasts,
            "attempts": attempts,
            "source_verifications": (
                source_verifications
            ),
        }

    @app.get("/api/results/primary")
    def primary_results() -> dict:
        _require_database(path)

        connection = (
            open_read_only_connection(
                path
            )
        )

        try:
            rows, summary = (
                load_primary_results(
                    connection
                )
            )

            return _results_payload(
                rows,
                summary,
            )

        finally:
            connection.close()

    @app.get(
        "/api/results/checkpoints"
    )
    def checkpoint_results(
        checkpoint: Checkpoint | None = None,
    ) -> dict:
        _require_database(path)

        connection = (
            open_read_only_connection(
                path
            )
        )

        try:
            rows = (
                load_scored_checkpoints(
                    connection=connection,
                    checkpoint=checkpoint,
                )
            )

            summary = (
                summarize_scored_checkpoints(
                    rows
                )
            )

            return _results_payload(
                rows,
                summary,
            )

        finally:
            connection.close()

    frontend_dist = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "dist"
    )

    if frontend_dist.exists():
        app.mount(
            "/",
            StaticFiles(
                directory=frontend_dist,
                html=True,
            ),
            name="frontend",
        )

    return app


app = create_app()
