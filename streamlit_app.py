from __future__ import annotations

from pathlib import Path

import streamlit as st

from forecast_ledger.checkpoints import Checkpoint
from forecast_ledger.dashboard_data import (
    PROTOCOL_VERSION,
    load_checkpoint_attempt_audit,
    load_checkpoint_detail,
    load_checkpoint_evidence,
    load_checkpoint_forecast_details,
    load_checkpoint_status_counts,
    load_included_pipeline_rows,
    load_research_funnel,
    open_read_only_connection,
)
from forecast_ledger.results import (
    load_primary_results,
    load_scored_checkpoints,
    summarize_scored_checkpoints,
)

DB_PATH = Path("data/forecast_ledger.db")


def probability(value) -> str:
    if value is None:
        return "—"

    return f"{100.0 * float(value):.1f}%"


def status_label(value: str) -> str:
    labels = {
        "matched": "Matched",
        "blocked": "Operationally blocked",
        "interrupted": "Interrupted",
        "retryable_retrieval": "Retryable retrieval",
        "awaiting_evidence": "Awaiting evidence",
        "partial_forecast": "Partial forecast",
        "awaiting_forecast": "Awaiting forecast",
    }

    return labels.get(
        value,
        value.replace("_", " ").title(),
    )


st.set_page_config(
    page_title="Forecast Ledger",
    page_icon="◉",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1220px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    [data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,.22);
        border-radius: 12px;
        padding: 14px 16px;
    }

    .fl-kicker {
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .12em;
        opacity: .58;
        text-transform: uppercase;
        margin-bottom: .2rem;
    }

    .fl-subtle {
        opacity: .67;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


if not DB_PATH.exists():
    st.error(
        "Forecast Ledger database was not found."
    )
    st.stop()


rows = load_included_pipeline_rows(
    DB_PATH
)

funnel = load_research_funnel(
    DB_PATH
)


st.sidebar.markdown(
    "## Forecast Ledger"
)
st.sidebar.caption(
    f"Prospective research ledger · {PROTOCOL_VERSION}"
)

page = st.sidebar.radio(
    "View",
    (
        "Overview",
        "Results",
        "Market detail",
        "Audit",
    ),
)

st.sidebar.divider()
st.sidebar.caption(
    "Read-only interface. Forecast generation and "
    "research state changes live outside Streamlit."
)


if page == "Overview":
    st.markdown(
        '<div class="fl-kicker">Live experiment</div>',
        unsafe_allow_html=True,
    )

    st.title("Forecast Ledger")

    st.markdown(
        """
        A prospective test of whether structured reasoning
        improves probabilistic forecasts from a fixed model.
        Every forecast is frozen before the outcome and tied
        to an auditable evidence packet.
        """
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Frozen snapshots",
        funnel["snapshots"],
    )
    c2.metric(
        "Machine eligible",
        funnel["eligible"],
    )
    c3.metric(
        "Semantically included",
        funnel["included"],
    )
    c4.metric(
        "Matched A/B/C/D",
        funnel["matched"],
    )

    st.write("")

    st.subheader("Primary experiment")

    primary_included = funnel[
        "primary_included"
    ]
    primary_matched = funnel[
        "primary_matched"
    ]

    coverage = (
        primary_matched / primary_included
        if primary_included
        else 0.0
    )

    st.write(
        f"**7-day checkpoint coverage:** "
        f"{primary_matched}/{primary_included} "
        f"({100 * coverage:.1f}%)"
    )

    st.progress(coverage)

    st.caption(
        "The 7-day checkpoint is the preregistered primary "
        "horizon. Other horizons are analyzed separately."
    )

    st.divider()

    st.subheader("Experiment ledger")

    table_rows = []

    for row in rows:
        table_rows.append(
            {
                "Market": row["question"],
                "Horizon": row["checkpoint"],
                "A Market": probability(
                    row["market_probability"]
                ),
                "B Direct": probability(
                    row["direct_probability"]
                ),
                "C Structured": probability(
                    row["structured_probability"]
                ),
                "D + Market": probability(
                    row["market_aware_probability"]
                ),
                "Status": status_label(
                    row["pipeline_status"]
                ),
            }
        )

    st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "A is the frozen YES midpoint. B and C never receive "
        "the market probability. D receives the matched "
        "contemporaneous market probability."
    )

    with st.expander(
        "What do B, C and D mean?"
    ):
        st.markdown(
            """
            **B · Direct**

            Same fixed model, market question, resolution
            rules and frozen evidence packet. Minimal
            forecasting instruction. No market probability.

            **C · Structured independent**

            Same model and evidence as B. The model must
            explicitly state a reference class, estimated
            base rate, strongest evidence for YES, strongest
            evidence for NO, key uncertainty, and final
            P(YES). No market probability.

            **D · Structured + market**

            Same structured procedure as C, plus the frozen
            prediction-market probability.

            Therefore **B → C** isolates the effect of the
            structured forecasting procedure, while
            **C → D** isolates the effect of adding market
            information.
            """
        )

    st.divider()

    st.subheader("Results")

    st.info(
        "No forecasting-performance result is reported before "
        "market settlement. Brier score, log loss and paired "
        "condition comparisons will appear here only after "
        "valid resolutions exist."
    )


elif page == "Results":
    st.markdown(
        '<div class="fl-kicker">Scoring</div>',
        unsafe_allow_html=True,
    )

    st.title("Results")

    connection = open_read_only_connection(
        DB_PATH
    )

    try:
        primary_rows, primary = (
            load_primary_results(
                connection
            )
        )

        secondary = []

        for horizon in (
            "14d",
            "3d",
            "1d",
        ):
            horizon_rows = (
                load_scored_checkpoints(
                    connection=connection,
                    checkpoint=Checkpoint(
                        horizon
                    ),
                )
            )

            horizon_summary = (
                summarize_scored_checkpoints(
                    horizon_rows
                )
            )

            secondary.append(
                (
                    horizon,
                    horizon_rows,
                    horizon_summary,
                )
            )

    finally:
        connection.close()

    st.subheader(
        "Primary · 7-day checkpoint"
    )

    st.caption(
        "One resolved market is one primary observation. "
        "Lower Brier score is better."
    )

    if primary.n == 0:
        st.info(
            "No primary markets have a valid terminal "
            "YES/NO resolution yet. No performance claim "
            "can be made."
        )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Resolved N",
        primary.n,
    )

    c2.metric(
        "B · Direct Brier",
        (
            f"{primary.mean_direct_brier:.4f}"
            if primary.mean_direct_brier
            is not None
            else "—"
        ),
    )

    c3.metric(
        "C · Structured Brier",
        (
            f"{primary.mean_structured_brier:.4f}"
            if primary.mean_structured_brier
            is not None
            else "—"
        ),
    )

    c4.metric(
        "D · + Market Brier",
        (
            f"{primary.mean_market_aware_brier:.4f}"
            if primary.mean_market_aware_brier
            is not None
            else "—"
        ),
    )

    st.write("")

    a1, a2, a3 = st.columns(3)

    a1.metric(
        "A · Market Brier",
        (
            f"{primary.mean_market_brier:.4f}"
            if primary.mean_market_brier
            is not None
            else "—"
        ),
    )

    a2.metric(
        "B → C paired effect",
        (
            f"{primary.mean_structured_advantage:+.4f}"
            if primary.mean_structured_advantage
            is not None
            else "—"
        ),
        help=(
            "Brier_B minus Brier_C. "
            "Positive means structured independent "
            "performed better."
        ),
    )

    a3.metric(
        "C → D paired effect",
        (
            f"{primary.mean_market_information_advantage:+.4f}"
            if primary.mean_market_information_advantage
            is not None
            else "—"
        ),
        help=(
            "Brier_C minus Brier_D. "
            "Positive means adding market information "
            "performed better."
        ),
    )

    if primary_rows:
        st.subheader(
            "Primary observations"
        )

        primary_table = []

        for row in primary_rows:
            primary_table.append(
                {
                    "Market": row.question,
                    "Outcome": (
                        "YES"
                        if row.outcome_yes
                        else "NO"
                    ),
                    "A": probability(
                        row.market_probability
                    ),
                    "B": probability(
                        row.direct_probability
                    ),
                    "C": probability(
                        row.structured_probability
                    ),
                    "D": probability(
                        row.market_aware_probability
                    ),
                    "Brier A": (
                        f"{row.market_brier:.4f}"
                    ),
                    "Brier B": (
                        f"{row.direct_brier:.4f}"
                    ),
                    "Brier C": (
                        f"{row.structured_brier:.4f}"
                    ),
                    "Brier D": (
                        f"{row.market_aware_brier:.4f}"
                    ),
                    "B→C": (
                        f"{row.structured_advantage:+.4f}"
                    ),
                    "C→D": (
                        f"{row.market_information_advantage:+.4f}"
                    ),
                }
            )

        st.dataframe(
            primary_table,
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    st.subheader(
        "Secondary horizons"
    )

    st.caption(
        "14d, 3d and 1d are evaluated separately. "
        "Repeated checkpoints from the same market are "
        "not treated as independent primary observations."
    )

    secondary_table = []

    for (
        horizon,
        _rows,
        summary,
    ) in secondary:
        secondary_table.append(
            {
                "Horizon": horizon,
                "N": summary.n,
                "A Market": (
                    f"{summary.mean_market_brier:.4f}"
                    if summary.mean_market_brier
                    is not None
                    else "—"
                ),
                "B Direct": (
                    f"{summary.mean_direct_brier:.4f}"
                    if summary.mean_direct_brier
                    is not None
                    else "—"
                ),
                "C Structured": (
                    f"{summary.mean_structured_brier:.4f}"
                    if summary.mean_structured_brier
                    is not None
                    else "—"
                ),
                "D + Market": (
                    f"{summary.mean_market_aware_brier:.4f}"
                    if summary.mean_market_aware_brier
                    is not None
                    else "—"
                ),
                "B→C": (
                    f"{summary.mean_structured_advantage:+.4f}"
                    if summary.mean_structured_advantage
                    is not None
                    else "—"
                ),
                "C→D": (
                    f"{summary.mean_market_information_advantage:+.4f}"
                    if summary.mean_market_information_advantage
                    is not None
                    else "—"
                ),
            }
        )

    st.dataframe(
        secondary_table,
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    st.caption(
        "Log loss and directional accuracy are stored as "
        "secondary metrics in the scoring engine. "
        "Calibration claims remain disabled until at least "
        "50 resolved markets exist for a condition."
    )


elif page == "Market detail":
    st.title("Market detail")

    if not rows:
        st.info(
            "No included checkpoints are available."
        )
        st.stop()

    options = {
        (
            f"{row['checkpoint']} · "
            f"{row['question']} · "
            f"{row['market_id']}"
        ): row
        for row in rows
    }

    selected_label = st.selectbox(
        "Checkpoint",
        options.keys(),
    )

    selected = options[
        selected_label
    ]

    market_id = selected["market_id"]
    checkpoint = selected["checkpoint"]

    detail = load_checkpoint_detail(
        DB_PATH,
        market_id,
        checkpoint,
    )

    forecasts = (
        load_checkpoint_forecast_details(
            DB_PATH,
            market_id,
            checkpoint,
        )
    )

    evidence = load_checkpoint_evidence(
        DB_PATH,
        market_id,
        checkpoint,
    )

    audit = load_checkpoint_attempt_audit(
        DB_PATH,
        market_id,
        checkpoint,
    )

    if detail is None:
        st.error(
            "Checkpoint detail is missing."
        )
        st.stop()

    forecast_by_condition = {
        item["condition"]: item
        for item in forecasts
    }

    st.markdown(
        f"### {detail['question']}"
    )

    st.caption(
        f"{checkpoint} checkpoint · "
        f"Market {market_id} · "
        f"Status: "
        f"{status_label(selected['pipeline_status'])}"
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "A · Market",
        probability(
            detail["market_probability"]
        ),
    )

    b.metric(
        "B · Direct",
        probability(
            forecast_by_condition.get(
                "B_direct",
                {},
            ).get("probability_yes")
        ),
    )

    c.metric(
        "C · Structured",
        probability(
            forecast_by_condition.get(
                "C_structured_independent",
                {},
            ).get("probability_yes")
        ),
    )

    d.metric(
        "D · + Market",
        probability(
            forecast_by_condition.get(
                "D_structured_market_aware",
                {},
            ).get("probability_yes")
        ),
    )

    st.write("")

    m1, m2, m3 = st.columns(3)

    m1.markdown(
        "**Frozen at**  \n"
        f"{detail.get('observed_at') or '—'}"
    )

    m2.markdown(
        "**YES spread**  \n"
        + (
            probability(
                detail["yes_spread"]
            )
            if detail["yes_spread"]
            is not None
            else "—"
        )
    )

    m3.markdown(
        "**Evidence items**  \n"
        f"{len(evidence)}"
    )

    with st.expander(
        "Resolution rules"
    ):
        st.write(
            detail["resolution_rules"]
        )

    st.divider()

    st.subheader("Structured forecasts")

    for condition in (
        "C_structured_independent",
        "D_structured_market_aware",
    ):
        forecast = forecast_by_condition.get(
            condition
        )

        if forecast is None:
            continue

        title = (
            "C · Structured independent"
            if condition
            == "C_structured_independent"
            else "D · Structured + market"
        )

        with st.expander(
            title,
            expanded=True,
        ):
            analysis = forecast[
                "analysis"
            ]

            st.write(
                "**Reference class:**",
                analysis.get(
                    "reference_class"
                )
                or "—",
            )

            st.write(
                "**Estimated base rate:**",
                probability(
                    analysis.get(
                        "estimated_base_rate"
                    )
                ),
            )

            st.write(
                "**Strongest evidence for YES:**",
                analysis.get(
                    "strongest_evidence_yes_assessment"
                )
                or "—",
            )

            st.write(
                "**Strongest evidence for NO:**",
                analysis.get(
                    "strongest_evidence_no_assessment"
                )
                or "—",
            )

            st.write(
                "**Key uncertainty:**",
                analysis.get(
                    "key_uncertainty"
                )
                or "—",
            )

    st.divider()

    st.subheader("Frozen evidence")

    if not evidence:
        st.caption(
            "No valid evidence packet exists "
            "for this checkpoint."
        )

    for item in evidence:
        with st.container(
            border=True
        ):
            st.markdown(
                f"**{item['title']}**"
            )
            st.caption(
                f"{item['source_name']} · "
                f"{item['published_at']} · "
                f"{item['timestamp_quality']}"
            )
            st.write(
                item["excerpt"]
            )
            st.markdown(
                f"[Open source]({item['source_url']})"
            )

    st.divider()

    st.subheader("Timeline")

    timeline = []

    if detail.get("observed_at"):
        timeline.append(
            {
                "Time": detail["observed_at"],
                "Event": "Market snapshot frozen",
            }
        )

    if detail.get("reviewed_at"):
        timeline.append(
            {
                "Time": detail["reviewed_at"],
                "Event": (
                    "Semantic review · "
                    f"{detail['semantic_decision']}"
                ),
            }
        )

    for attempt in audit["retrieval"]:
        event_time = (
            attempt["completed_at"]
            or attempt["requested_at"]
        )

        timeline.append(
            {
                "Time": event_time,
                "Event": (
                    "Retrieval attempt "
                    f"{attempt['attempt_number']} · "
                    f"{attempt['status']}"
                ),
            }
        )

    for forecast in forecasts:
        timeline.append(
            {
                "Time": forecast[
                    "forecast_created_at"
                ],
                "Event": (
                    f"{forecast['condition']} "
                    "forecast frozen"
                ),
            }
        )

    timeline.sort(
        key=lambda item: item["Time"]
    )

    st.dataframe(
        timeline,
        use_container_width=True,
        hide_index=True,
    )

    with st.expander(
        "Audit lineage"
    ):
        st.markdown(
            "#### Forecast records"
        )

        for forecast in forecasts:
            st.json(
                {
                    key: value
                    for key, value
                    in forecast.items()
                    if key != "analysis"
                }
            )

        st.markdown(
            "#### Retrieval attempts"
        )

        st.dataframe(
            audit["retrieval"],
            use_container_width=True,
            hide_index=True,
        )

        st.markdown(
            "#### Forecast attempts"
        )

        st.dataframe(
            audit["forecasts"],
            use_container_width=True,
            hide_index=True,
        )


elif page == "Audit":
    st.title("Audit")

    st.markdown(
        """
        Operational failures remain part of the experiment
        ledger. They are never silently removed from coverage.
        """
    )

    failures = [
        row
        for row in rows
        if row["pipeline_status"]
        != "matched"
    ]

    failure_table = [
        {
            "Market": row["question"],
            "Horizon": row["checkpoint"],
            "Status": status_label(
                row["pipeline_status"]
            ),
            "Attempt": row[
                "retrieval_attempt_number"
            ],
            "Error type": row[
                "retrieval_error_type"
            ],
            "Error": row[
                "retrieval_error_message"
            ],
        }
        for row in failures
    ]

    st.subheader(
        "Included checkpoints without matched forecasts"
    )

    if failure_table:
        st.dataframe(
            failure_table,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success(
            "Every included checkpoint is matched."
        )

    st.divider()

    st.subheader(
        "Checkpoint ledger"
    )

    st.dataframe(
        load_checkpoint_status_counts(
            DB_PATH
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    st.subheader(
        "Research funnel"
    )

    st.json(funnel)
