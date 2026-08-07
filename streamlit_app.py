from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from forecast_ledger.dashboard_data import (
    load_checkpoint_detail,
    load_checkpoint_options,
    load_checkpoint_status_counts,
    load_evidence_for_packet,
    load_forecast_attempts_for_checkpoint,
    load_forecasts_for_checkpoint,
    load_matched_forecasts,
    load_overview,
    load_retrieval_attempts_for_checkpoint,
    load_source_verifications_for_packet,
)

DEFAULT_DB_PATH = Path(
    os.getenv(
        "FORECAST_LEDGER_DB",
        "data/forecast_ledger.db",
    )
)


st.set_page_config(
    page_title="Forecast Ledger",
    page_icon="📡",
    layout="wide",
)


def probability(value):
    if value is None:
        return "—"

    return f"{100 * value:.1f}%"


def checkpoint_label(row):
    return (
        f"{row['checkpoint']} · "
        f"{row['market_id']} · "
        f"{row['question']}"
    )


def render_probability_row(row):
    columns = st.columns(4)

    columns[0].metric(
        "A · Market",
        probability(row["market_probability"]),
    )

    columns[1].metric(
        "B · Direct LLM",
        probability(row["direct_probability"]),
    )

    columns[2].metric(
        "C · Structured",
        probability(row["structured_probability"]),
    )

    columns[3].metric(
        "D · Structured + Market",
        probability(row["market_aware_probability"]),
    )


def render_checkpoint_selector(options):
    if not options:
        st.info("No checkpoint records exist yet.")
        return None

    labels = {
        checkpoint_label(row): (
            row["market_id"],
            row["checkpoint"],
        )
        for row in options
    }

    selected_label = st.selectbox(
        "Checkpoint",
        options=list(labels),
    )

    return labels[selected_label]


def render_checkpoint_detail(
    db_path,
    market_id,
    checkpoint,
):
    detail = load_checkpoint_detail(
        db_path,
        market_id,
        checkpoint,
    )

    if detail is None:
        st.error("Checkpoint could not be loaded.")
        return

    st.header(detail["question"])
    st.caption(
        f"Market {market_id} · {checkpoint} checkpoint"
    )

    st.subheader("Resolution rules")
    st.write(detail["resolution_rules"])

    overview_columns = st.columns(4)

    overview_columns[0].metric(
        "Market P(YES)",
        probability(
            detail["market_probability"]
        ),
    )

    overview_columns[1].metric(
        "YES spread",
        probability(
            detail["yes_spread"]
        ),
    )

    overview_columns[2].metric(
        "Checkpoint state",
        detail["checkpoint_status"],
    )

    overview_columns[3].metric(
        "Semantic review",
        detail["semantic_decision"] or "—",
    )

    st.subheader("Market snapshot")

    st.write(
        {
            "snapshot_id": detail["snapshot_id"],
            "observed_at": detail["observed_at"],
            "yes_bid": detail["yes_bid"],
            "yes_ask": detail["yes_ask"],
            "no_bid": detail["no_bid"],
            "no_ask": detail["no_ask"],
            "no_implied_yes_probability": (
                detail["no_implied_yes_probability"]
            ),
            "no_book_error": detail["no_book_error"],
        }
    )

    if detail["semantic_reason"]:
        st.subheader("Semantic decision")
        st.write(detail["semantic_reason"])

    forecasts = load_forecasts_for_checkpoint(
        db_path,
        market_id,
        checkpoint,
    )

    if forecasts:
        st.subheader("Model forecasts")

        forecast_by_condition = {
            row["condition"]: row
            for row in forecasts
        }

        columns = st.columns(4)

        columns[0].metric(
            "A · Market",
            probability(
                detail["market_probability"]
            ),
        )

        mapping = (
            (
                "B_direct",
                "B · Direct",
            ),
            (
                "C_structured_independent",
                "C · Structured",
            ),
            (
                "D_structured_market_aware",
                "D · Structured + Market",
            ),
        )

        for column, (condition, label) in zip(
            columns[1:],
            mapping,
        ):
            row = forecast_by_condition.get(
                condition
            )

            column.metric(
                label,
                (
                    probability(
                        row["probability_yes"]
                    )
                    if row
                    else "—"
                ),
            )

        with st.expander(
            "Structured model outputs"
        ):
            for forecast in forecasts:
                st.markdown(
                    f"**{forecast['condition']}**"
                )
                st.json(
                    forecast["parsed_output"]
                )

    packet_id = detail["packet_id"]

    if packet_id:
        evidence = load_evidence_for_packet(
            db_path,
            packet_id,
        )

        st.subheader("Frozen evidence")

        st.caption(
            f"Packet {packet_id} · "
            f"information cutoff "
            f"{detail['information_cutoff']}"
        )

        if not evidence:
            st.info(
                "Valid zero-evidence packet."
            )

        for item in evidence:
            with st.expander(
                f"{item['position'] + 1}. "
                f"{item['title']}"
            ):
                st.write(
                    f"**Source:** "
                    f"{item['source_name']}"
                )
                st.write(
                    f"**Published:** "
                    f"{item['published_at']}"
                )
                st.write(
                    f"**Timestamp quality:** "
                    f"{item['timestamp_quality']}"
                )
                st.write(item["excerpt"])
                st.code(
                    item["evidence_id"],
                    language=None,
                )
                st.link_button(
                    "Open source",
                    item["source_url"],
                )

    st.subheader("Lineage")

    lineage = {
        "first_seen_at": detail["first_seen_at"],
        "scheduled_at": detail["scheduled_at"],
        "window_start": detail["window_start"],
        "window_end": detail["window_end"],
        "snapshot_id": detail["snapshot_id"],
        "information_cutoff": detail[
            "information_cutoff"
        ],
        "packet_id": packet_id,
        "retrieval_response_id": detail[
            "retrieval_response_id"
        ],
        "retrieval_model": detail[
            "retrieval_model"
        ],
        "retrieval_prompt_version": detail[
            "retrieval_prompt_version"
        ],
        "packet_validation": detail[
            "packet_validation_status"
        ],
    }

    st.json(lineage)


db_path = DEFAULT_DB_PATH

st.title("Forecast Ledger")
st.caption(
    "Prospective, auditable AI forecasting experiment"
)

if not db_path.exists():
    st.error(
        f"Database not found: {db_path}"
    )
    st.stop()


page = st.sidebar.radio(
    "View",
    (
        "Overview",
        "Forecasts",
        "Market detail",
        "Audit",
    ),
)


if page == "Overview":
    overview = load_overview(db_path)

    st.subheader(
        "Protocol v0.2 · GPT-5.4 mini · live"
    )

    columns = st.columns(4)

    columns[0].metric(
        "Markets enrolled",
        f"{overview['markets']:,}",
    )

    columns[1].metric(
        "Snapshots",
        f"{overview['snapshots']:,}",
    )

    columns[2].metric(
        "Model forecasts",
        f"{overview['forecasts']:,}",
    )

    columns[3].metric(
        "Matched B/C/D sets",
        f"{overview['matched_forecasts']:,}",
    )

    st.subheader("Completed matched forecasts")

    matched = load_matched_forecasts(
        db_path
    )

    if not matched:
        st.info(
            "No complete B/C/D forecast sets yet."
        )

    for row in matched:
        with st.container(border=True):
            st.markdown(
                f"### {row['question']}"
            )
            st.caption(
                f"{row['checkpoint']} checkpoint · "
                f"snapshot {row['observed_at']}"
            )

            render_probability_row(row)

    st.subheader("Checkpoint coverage")

    status_counts = (
        load_checkpoint_status_counts(
            db_path
        )
    )

    st.dataframe(
        status_counts,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Dashboard is read-only. "
        "No experimental state can be modified here."
    )


elif page == "Forecasts":
    matched = load_matched_forecasts(
        db_path
    )

    st.header("Matched forecasts")

    if not matched:
        st.info(
            "No complete matched forecast sets yet."
        )

    for row in matched:
        with st.container(border=True):
            st.markdown(
                f"### {row['question']}"
            )

            st.caption(
                f"Market {row['market_id']} · "
                f"{row['checkpoint']} · "
                f"{row['observed_at']}"
            )

            render_probability_row(row)

            st.caption(
                f"Packet: {row['packet_id']}"
            )


elif page == "Market detail":
    options = load_checkpoint_options(
        db_path
    )

    selected = render_checkpoint_selector(
        options
    )

    if selected:
        market_id, checkpoint = selected

        render_checkpoint_detail(
            db_path,
            market_id,
            checkpoint,
        )


elif page == "Audit":
    options = load_checkpoint_options(
        db_path
    )

    selected = render_checkpoint_selector(
        options
    )

    if selected:
        market_id, checkpoint = selected

        detail = load_checkpoint_detail(
            db_path,
            market_id,
            checkpoint,
        )

        if detail is None:
            st.error(
                "Checkpoint could not be loaded."
            )
            st.stop()

        st.header("Audit trail")
        st.write(
            detail["question"]
        )

        st.subheader("Checkpoint")
        st.json(detail)

        st.subheader("Retrieval attempts")

        retrieval_attempts = (
            load_retrieval_attempts_for_checkpoint(
                db_path,
                market_id,
                checkpoint,
            )
        )

        st.dataframe(
            retrieval_attempts,
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Forecast attempts")

        forecast_attempts = (
            load_forecast_attempts_for_checkpoint(
                db_path,
                market_id,
                checkpoint,
            )
        )

        st.dataframe(
            forecast_attempts,
            use_container_width=True,
            hide_index=True,
        )

        packet_id = detail["packet_id"]

        if packet_id:
            st.subheader(
                "Source verification"
            )

            verifications = (
                load_source_verifications_for_packet(
                    db_path,
                    packet_id,
                )
            )

            st.dataframe(
                verifications,
                use_container_width=True,
                hide_index=True,
            )

        forecasts = (
            load_forecasts_for_checkpoint(
                db_path,
                market_id,
                checkpoint,
            )
        )

        if forecasts:
            st.subheader(
                "Forecast lineage"
            )

            for forecast in forecasts:
                with st.expander(
                    forecast["condition"]
                ):
                    st.json(
                        {
                            key: value
                            for key, value
                            in forecast.items()
                            if key
                            != "parsed_output_json"
                        }
                    )


st.sidebar.divider()
st.sidebar.caption(
    "Research engine → immutable SQLite ledger → read-only dashboard"
)
