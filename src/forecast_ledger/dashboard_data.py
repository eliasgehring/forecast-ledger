from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "v0.2"


def open_read_only_connection(
    db_path: str | Path,
) -> sqlite3.Connection:
    path = Path(db_path).resolve()

    connection = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row

    return connection


def _rows_as_dicts(
    rows: list[sqlite3.Row],
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
    ]


def load_overview(
    db_path: str | Path,
    protocol_version: str = PROTOCOL_VERSION,
) -> dict[str, int]:
    connection = open_read_only_connection(db_path)

    try:
        market_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM tracked_markets
            WHERE protocol_version = ?
            """,
            (protocol_version,),
        ).fetchone()[0]

        checkpoint_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM checkpoint_records
            WHERE protocol_version = ?
            """,
            (protocol_version,),
        ).fetchone()[0]

        snapshot_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM market_snapshots
            WHERE protocol_version = ?
            """,
            (protocol_version,),
        ).fetchone()[0]

        forecast_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM forecasts
            WHERE protocol_version = ?
            """,
            (protocol_version,),
        ).fetchone()[0]

        matched_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    market_id,
                    checkpoint
                FROM forecasts
                WHERE protocol_version = ?
                GROUP BY
                    market_id,
                    checkpoint
                HAVING
                    COUNT(DISTINCT condition) = 3
                    AND COUNT(DISTINCT packet_id) = 1
                    AND COUNT(DISTINCT snapshot_id) = 1
                    AND COUNT(DISTINCT model) = 1
            )
            """,
            (protocol_version,),
        ).fetchone()[0]

        valid_packet_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM evidence_packets AS p
            JOIN evidence_packet_validations AS v
              ON v.packet_id = p.packet_id
            WHERE p.protocol_version = ?
              AND v.status = 'valid'
            """,
            (protocol_version,),
        ).fetchone()[0]

        forecast_attempt_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM forecast_attempts
            WHERE protocol_version = ?
            """,
            (protocol_version,),
        ).fetchone()[0]

        return {
            "markets": market_count,
            "checkpoints": checkpoint_count,
            "snapshots": snapshot_count,
            "forecasts": forecast_count,
            "matched_forecasts": matched_count,
            "valid_packets": valid_packet_count,
            "forecast_attempts": forecast_attempt_count,
        }

    finally:
        connection.close()


def load_checkpoint_status_counts(
    db_path: str | Path,
    protocol_version: str = PROTOCOL_VERSION,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                status,
                COUNT(*) AS count
            FROM checkpoint_records
            WHERE protocol_version = ?
            GROUP BY status
            ORDER BY status
            """,
            (protocol_version,),
        ).fetchall()

        return _rows_as_dicts(rows)

    finally:
        connection.close()


def load_matched_forecasts(
    db_path: str | Path,
    protocol_version: str = PROTOCOL_VERSION,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                f.market_id,
                tm.question,
                f.checkpoint,
                ms.observed_at,
                ms.yes_bid,
                ms.yes_ask,
                (
                    ms.yes_bid + ms.yes_ask
                ) / 2.0 AS market_probability,
                MAX(
                    CASE
                        WHEN f.condition = 'B_direct'
                        THEN f.probability_yes
                    END
                ) AS direct_probability,
                MAX(
                    CASE
                        WHEN f.condition = 'C_structured_independent'
                        THEN f.probability_yes
                    END
                ) AS structured_probability,
                MAX(
                    CASE
                        WHEN f.condition = 'D_structured_market_aware'
                        THEN f.probability_yes
                    END
                ) AS market_aware_probability,
                MIN(f.packet_id) AS packet_id,
                MIN(f.snapshot_id) AS snapshot_id,
                MIN(f.model) AS model
            FROM forecasts AS f
            JOIN tracked_markets AS tm
              ON tm.market_id = f.market_id
             AND tm.protocol_version = f.protocol_version
            JOIN market_snapshots AS ms
              ON ms.snapshot_id = f.snapshot_id
             AND ms.market_id = f.market_id
             AND ms.checkpoint = f.checkpoint
             AND ms.protocol_version = f.protocol_version
            WHERE f.protocol_version = ?
            GROUP BY
                f.market_id,
                tm.question,
                f.checkpoint,
                ms.observed_at,
                ms.yes_bid,
                ms.yes_ask
            HAVING
                COUNT(DISTINCT f.condition) = 3
                AND COUNT(DISTINCT f.packet_id) = 1
                AND COUNT(DISTINCT f.snapshot_id) = 1
                AND COUNT(DISTINCT f.model) = 1
            ORDER BY
                ms.observed_at DESC,
                f.market_id
            """,
            (protocol_version,),
        ).fetchall()

        return _rows_as_dicts(rows)

    finally:
        connection.close()


def load_checkpoint_options(
    db_path: str | Path,
    protocol_version: str = PROTOCOL_VERSION,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                cr.market_id,
                cr.checkpoint,
                tm.question,
                cr.status,
                cr.scheduled_at
            FROM checkpoint_records AS cr
            JOIN tracked_markets AS tm
              ON tm.market_id = cr.market_id
             AND tm.protocol_version = cr.protocol_version
            WHERE cr.protocol_version = ?
            ORDER BY
                cr.scheduled_at DESC,
                cr.market_id
            """,
            (protocol_version,),
        ).fetchall()

        return _rows_as_dicts(rows)

    finally:
        connection.close()


def load_checkpoint_detail(
    db_path: str | Path,
    market_id: str,
    checkpoint: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> dict[str, Any] | None:
    connection = open_read_only_connection(db_path)

    try:
        row = connection.execute(
            """
            SELECT
                tm.market_id,
                tm.question,
                tm.resolution_rules,
                tm.close_time,
                tm.event_id,
                tm.event_title,
                tm.event_slug,
                tm.categories_json,
                tm.tag_slugs_json,
                tm.first_seen_at,

                cr.checkpoint,
                cr.scheduled_at,
                cr.window_start,
                cr.window_end,
                cr.status AS checkpoint_status,
                cr.created_at AS checkpoint_created_at,

                ms.snapshot_id,
                ms.observed_at,
                ms.yes_bid,
                ms.yes_ask,
                ms.no_bid,
                ms.no_ask,
                ms.no_book_error,

                sr.decision AS semantic_decision,
                sr.reason AS semantic_reason,
                sr.reviewed_at,

                ep.packet_id,
                ep.attempt_number AS retrieval_attempt_number,
                ep.retrieval_response_id,
                ep.information_cutoff,
                ep.retrieval_model,
                ep.retrieval_prompt_version,
                ep.created_at AS packet_created_at,

                epv.status AS packet_validation_status,
                epv.reason AS packet_validation_reason,
                epv.validated_at AS packet_validated_at

            FROM checkpoint_records AS cr

            JOIN tracked_markets AS tm
              ON tm.market_id = cr.market_id
             AND tm.protocol_version = cr.protocol_version

            LEFT JOIN market_snapshots AS ms
              ON ms.market_id = cr.market_id
             AND ms.checkpoint = cr.checkpoint
             AND ms.protocol_version = cr.protocol_version

            LEFT JOIN semantic_reviews AS sr
              ON sr.market_id = cr.market_id
             AND sr.checkpoint = cr.checkpoint
             AND sr.protocol_version = cr.protocol_version

            LEFT JOIN evidence_packets AS ep
              ON ep.market_id = cr.market_id
             AND ep.checkpoint = cr.checkpoint
             AND ep.protocol_version = cr.protocol_version
             AND EXISTS (
                    SELECT 1
                    FROM evidence_packet_validations AS v
                    WHERE v.packet_id = ep.packet_id
                      AND v.status = 'valid'
             )

            LEFT JOIN evidence_packet_validations AS epv
              ON epv.packet_id = ep.packet_id

            WHERE cr.market_id = ?
              AND cr.checkpoint = ?
              AND cr.protocol_version = ?
            """,
            (
                market_id,
                checkpoint,
                protocol_version,
            ),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)

        for field in (
            "categories_json",
            "tag_slugs_json",
        ):
            raw = result.get(field)

            if raw:
                result[field] = json.loads(raw)

        if (
            result.get("yes_bid") is not None
            and result.get("yes_ask") is not None
        ):
            result["market_probability"] = (
                result["yes_bid"]
                + result["yes_ask"]
            ) / 2.0

            result["yes_spread"] = (
                result["yes_ask"]
                - result["yes_bid"]
            )
        else:
            result["market_probability"] = None
            result["yes_spread"] = None

        if (
            result.get("no_bid") is not None
            and result.get("no_ask") is not None
        ):
            result["no_implied_yes_probability"] = (
                1.0
                - (
                    result["no_bid"]
                    + result["no_ask"]
                )
                / 2.0
            )
        else:
            result["no_implied_yes_probability"] = None

        return result

    finally:
        connection.close()


def load_forecasts_for_checkpoint(
    db_path: str | Path,
    market_id: str,
    checkpoint: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                forecast_id,
                condition,
                packet_id,
                snapshot_id,
                model,
                reasoning_effort,
                prompt_version,
                prompt_sha256,
                attempt_number,
                response_id,
                probability_yes,
                parsed_output_json,
                forecast_created_at,
                protocol_commit,
                code_commit
            FROM forecasts
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
            ORDER BY condition
            """,
            (
                market_id,
                checkpoint,
                protocol_version,
            ),
        ).fetchall()

        forecasts = _rows_as_dicts(rows)

        for forecast in forecasts:
            forecast["parsed_output"] = json.loads(
                forecast["parsed_output_json"]
            )

        return forecasts

    finally:
        connection.close()


def load_evidence_for_packet(
    db_path: str | Path,
    packet_id: str,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                pi.position,
                e.evidence_id,
                e.source_url,
                e.source_name,
                e.title,
                e.published_at,
                e.retrieved_at,
                e.excerpt,
                e.timestamp_quality
            FROM evidence_packet_items AS pi
            JOIN evidence_items AS e
              ON e.evidence_id = pi.evidence_id
            WHERE pi.packet_id = ?
            ORDER BY pi.position
            """,
            (packet_id,),
        ).fetchall()

        return _rows_as_dicts(rows)

    finally:
        connection.close()


def load_source_verifications_for_packet(
    db_path: str | Path,
    packet_id: str,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                sv.position,
                sv.candidate_source_url,
                sv.final_source_url,
                sv.model_published_at,
                sv.model_timestamp_quality,
                sv.verified_published_at,
                sv.verified_timestamp_quality,
                sv.fetched_at,
                sv.content_sha256,
                sv.verification_method,
                sv.modified_at,
                sv.modification_method,
                sv.modification_error,
                sv.verification_error,
                sv.accepted,
                sv.rejection_reason
            FROM evidence_packets AS ep
            JOIN source_verifications AS sv
              ON sv.market_id = ep.market_id
             AND sv.checkpoint = ep.checkpoint
             AND sv.protocol_version = ep.protocol_version
             AND sv.attempt_number = ep.attempt_number
            WHERE ep.packet_id = ?
            ORDER BY sv.position
            """,
            (packet_id,),
        ).fetchall()

        return _rows_as_dicts(rows)

    finally:
        connection.close()


def load_retrieval_attempts_for_checkpoint(
    db_path: str | Path,
    market_id: str,
    checkpoint: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                attempt_number,
                model,
                prompt_version,
                requested_at,
                completed_at,
                response_id,
                status,
                error_type,
                error_message
            FROM retrieval_attempts
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
            ORDER BY attempt_number
            """,
            (
                market_id,
                checkpoint,
                protocol_version,
            ),
        ).fetchall()

        return _rows_as_dicts(rows)

    finally:
        connection.close()


def load_forecast_attempts_for_checkpoint(
    db_path: str | Path,
    market_id: str,
    checkpoint: str,
    protocol_version: str = PROTOCOL_VERSION,
) -> list[dict[str, Any]]:
    connection = open_read_only_connection(db_path)

    try:
        rows = connection.execute(
            """
            SELECT
                condition,
                attempt_number,
                packet_id,
                snapshot_id,
                model,
                reasoning_effort,
                prompt_version,
                prompt_sha256,
                requested_at,
                completed_at,
                response_id,
                status,
                error_type,
                error_message,
                protocol_commit,
                code_commit
            FROM forecast_attempts
            WHERE market_id = ?
              AND checkpoint = ?
              AND protocol_version = ?
            ORDER BY
                condition,
                attempt_number
            """,
            (
                market_id,
                checkpoint,
                protocol_version,
            ),
        ).fetchall()

        return _rows_as_dicts(rows)

    finally:
        connection.close()
