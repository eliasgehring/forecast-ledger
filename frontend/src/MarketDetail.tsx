import { useEffect, useMemo, useState } from "react";

type Attempt = {
  attempt_number: number;
  condition?: string;
  model: string;
  prompt_version: string;
  requested_at: string;
  completed_at: string | null;
  response_id: string | null;
  status: string;
  error_type: string | null;
  error_message: string | null;
};

type Forecast = {
  condition: string;
  probability_yes: number;
  model: string;
  reasoning_effort: string;
  prompt_version: string;
  attempt_number: number;
  response_id: string;
  forecast_created_at: string;
  analysis: unknown;
  protocol_commit: string;
  code_commit: string;
};

type Evidence = {
  evidence_id: string;
  position: number;
  source_name: string;
  source_url: string;
  title: string;
  excerpt: string;
  published_at: string;
  retrieved_at: string;
  timestamp_quality: string;
};

type Payload = {
  protocol_version: string;

  market: {
    market_id: string;
    checkpoint: string;
    question: string;
    resolution_rules: string;
    observed_at: string;
    information_cutoff: string;
    market_probability: number;
    yes_bid: number;
    yes_ask: number;
    yes_spread: number;
    snapshot_id: string;
    packet_id: string | null;
    packet_validation_status: string | null;
    semantic_decision: string | null;
    semantic_reason: string | null;
  };

  evidence: Evidence[];
  forecasts: Forecast[];

  attempts: {
    retrieval: Attempt[];
    forecasts: Attempt[];
  };

  source_verifications: Array<Record<string, unknown>>;
};

type Props = {
  marketId: string;
  checkpoint: string;
  onBack: () => void;
};

function pct(value: number | null | undefined) {
  return value == null
    ? "—"
    : `${(value * 100).toFixed(1)}%`;
}

function time(value: string | null | undefined) {
  if (!value) return "—";

  const parsed = new Date(value);

  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString();
}

function conditionName(condition: string) {
  const names: Record<string, string> = {
    B_direct: "B Direct",
    C_structured_independent: "C Structured",
    D_structured_market_aware: "D + Market",
  };

  return names[condition] ?? condition;
}

function analysisText(value: unknown) {
  if (value == null) {
    return "No stored analysis.";
  }

  if (typeof value === "string") {
    try {
      return JSON.stringify(
        JSON.parse(value),
        null,
        2,
      );
    } catch {
      return value;
    }
  }

  return JSON.stringify(
    value,
    null,
    2,
  );
}

export default function MarketDetail({
  marketId,
  checkpoint,
  onBack,
}: Props) {
  const [data, setData] =
    useState<Payload | null>(null);

  const [error, setError] =
    useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);

    fetch(
      `/api/markets/${encodeURIComponent(
        marketId,
      )}/${encodeURIComponent(checkpoint)}`,
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Checkpoint returned ${response.status}`,
          );
        }

        return response.json();
      })
      .then((payload: Payload) => {
        setData(payload);
      })
      .catch((caught: unknown) => {
        setError(
          caught instanceof Error
            ? caught.message
            : String(caught),
        );
      });
  }, [marketId, checkpoint]);

  const forecastMap = useMemo(() => {
    if (!data) return new Map();

    return new Map(
      data.forecasts.map((forecast) => [
        forecast.condition,
        forecast,
      ]),
    );
  }, [data]);

  if (error) {
    return (
      <>
        <button
          type="button"
          className="back-button"
          onClick={onBack}
        >
          ← Markets
        </button>

        <section className="panel">
          <h2>Checkpoint unavailable</h2>
          <p className="muted">{error}</p>
        </section>
      </>
    );
  }

  if (!data) {
    return (
      <div className="loading">
        Loading frozen lineage…
      </div>
    );
  }

  const market = data.market;

  const probabilities = [
    ["A Market", market.market_probability],
    [
      "B Direct",
      forecastMap.get("B_direct")
        ?.probability_yes,
    ],
    [
      "C Structured",
      forecastMap.get(
        "C_structured_independent",
      )?.probability_yes,
    ],
    [
      "D + Market",
      forecastMap.get(
        "D_structured_market_aware",
      )?.probability_yes,
    ],
  ] as const;

  return (
    <>
      <button
        type="button"
        className="back-button"
        onClick={onBack}
      >
        ← Markets
      </button>

      <section className="detail-head">
        <div>
          <div className="kicker">
            {market.checkpoint} checkpoint
          </div>

          <h2 className="detail-title">
            {market.question}
          </h2>

          <div className="detail-meta">
            Frozen {time(market.observed_at)}
            {" · "}
            {data.protocol_version}
            {" · "}
            {market.semantic_decision ??
              "unreviewed"}
          </div>
        </div>

        <span
          className={
            data.forecasts.length === 3
              ? "status-pill status-matched"
              : "status-pill status-partial_forecast"
          }
        >
          {data.forecasts.length === 3
            ? "Matched"
            : `${data.forecasts.length}/3 forecasts`}
        </span>
      </section>

      <section className="probability-grid">
        {probabilities.map(
          ([label, value]) => (
            <article
              className="probability-card"
              key={label}
            >
              <div className="metric-label">
                {label}
              </div>

              <div className="probability-value">
                {pct(value)}
              </div>
            </article>
          ),
        )}
      </section>

      <section className="detail-grid">
        <article className="panel">
          <div className="kicker">
            Frozen information state
          </div>

          <h2>Market snapshot</h2>

          <DetailRow
            label="Market P(YES)"
            value={pct(
              market.market_probability,
            )}
          />

          <DetailRow
            label="YES bid"
            value={pct(market.yes_bid)}
          />

          <DetailRow
            label="YES ask"
            value={pct(market.yes_ask)}
          />

          <DetailRow
            label="YES spread"
            value={pct(market.yes_spread)}
          />

          <DetailRow
            label="Information cutoff"
            value={time(
              market.information_cutoff,
            )}
          />

          <DetailRow
            label="Snapshot ID"
            value={market.snapshot_id}
            mono
          />

          <DetailRow
            label="Packet ID"
            value={market.packet_id ?? "—"}
            mono
          />
        </article>

        <article className="panel">
          <div className="kicker">
            Settlement semantics
          </div>

          <h2>Resolution contract</h2>

          <p className="resolution-copy">
            {market.resolution_rules}
          </p>

          <div className="semantic-note">
            <strong>Semantic review</strong>

            <p>
              {market.semantic_reason ??
                "No review reason stored."}
            </p>
          </div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <div className="kicker">
              Frozen evidence
            </div>

            <h2>Evidence packet</h2>
          </div>

          <span className="quiet-pill">
            {data.evidence.length} items
          </span>
        </div>

        <div className="evidence-list">
          {data.evidence.map((item) => (
            <article
              className="evidence-card"
              key={item.evidence_id}
            >
              <div className="evidence-number">
                {item.position}
              </div>

              <div>
                <div className="evidence-source">
                  {item.source_name}
                </div>

                <h3>{item.title}</h3>

                <p>{item.excerpt}</p>

                <div className="evidence-meta">
                  Published{" "}
                  {time(item.published_at)}
                  {" · "}
                  {item.timestamp_quality}
                </div>

                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open source ↗
                </a>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="forecast-detail-grid">
        {data.forecasts.map((forecast) => (
          <article
            className="panel forecast-card"
            key={forecast.condition}
          >
            <div className="kicker">
              {conditionName(
                forecast.condition,
              )}
            </div>

            <div className="forecast-probability">
              {pct(
                forecast.probability_yes,
              )}
            </div>

            <div className="forecast-meta">
              {forecast.model}
              {" · "}
              {forecast.reasoning_effort}
              {" · attempt "}
              {forecast.attempt_number}
            </div>

            <pre className="analysis-block">
              {analysisText(
                forecast.analysis,
              )}
            </pre>
          </article>
        ))}
      </section>

      <section className="detail-grid">
        <article className="panel">
          <div className="kicker">
            Execution provenance
          </div>

          <h2>Attempt history</h2>

          <h3 className="audit-subhead">
            Retrieval
          </h3>

          {data.attempts.retrieval.map(
            (attempt) => (
              <AttemptRow
                key={`retrieval-${attempt.attempt_number}`}
                attempt={attempt}
              />
            ),
          )}

          <h3 className="audit-subhead">
            Forecasts
          </h3>

          {data.attempts.forecasts.map(
            (attempt) => (
              <AttemptRow
                key={`${attempt.condition}-${attempt.attempt_number}`}
                attempt={attempt}
              />
            ),
          )}
        </article>

        <article className="panel">
          <div className="kicker">
            Integrity
          </div>

          <h2>Frozen lineage</h2>

          <DetailRow
            label="Packet validation"
            value={
              market.packet_validation_status ??
              "—"
            }
          />

          <DetailRow
            label="Evidence items"
            value={String(
              data.evidence.length,
            )}
          />

          <DetailRow
            label="Source verifications"
            value={String(
              data.source_verifications.length,
            )}
          />

          <DetailRow
            label="Forecast conditions"
            value={`${data.forecasts.length}/3`}
          />
        </article>
      </section>
    </>
  );
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="audit-row">
      <span>{label}</span>

      <strong
        className={
          mono ? "mono-value" : ""
        }
      >
        {value}
      </strong>
    </div>
  );
}

function AttemptRow({
  attempt,
}: {
  attempt: Attempt;
}) {
  return (
    <div className="attempt-row">
      <div>
        <strong>
          {attempt.condition
            ? conditionName(
                attempt.condition,
              )
            : `Attempt ${attempt.attempt_number}`}
        </strong>

        <div className="row-meta">
          {time(attempt.requested_at)}
        </div>

        {attempt.error_type && (
          <div className="attempt-error">
            {attempt.error_type}
          </div>
        )}
      </div>

      <span
        className={`attempt-status attempt-${attempt.status}`}
      >
        {attempt.status}
      </span>
    </div>
  );
}
