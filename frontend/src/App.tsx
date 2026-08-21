import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./App.css";
import MarketDetail from "./MarketDetail";
import ResultsView from "./ResultsView";

type Page = "overview" | "results" | "markets" | "audit";

type Health = {
  status: string;
  protocol_version: string;
  database_exists: boolean;
  read_only: boolean;
};

type Funnel = {
  snapshots: number;
  eligible: number;
  included: number;
  matched: number;
  primary_included: number;
  primary_matched: number;
};

type Summary = {
  n: number;
  mean_market_brier: number | null;
  mean_direct_brier: number | null;
  mean_structured_brier: number | null;
  mean_market_aware_brier: number | null;
  mean_structured_advantage: number | null;
  mean_market_information_advantage: number | null;
};

type ResultRow = {
  market_id: string;
  question: string;
  checkpoint: string;
  outcome_yes: boolean;
  market_probability: number;
  direct_probability: number;
  structured_probability: number;
  market_aware_probability: number;
  market_brier: number;
  direct_brier: number;
  structured_brier: number;
  market_aware_brier: number;
};

type ResultsPayload = {
  protocol_version: string;
  summary: Summary;
  rows: ResultRow[];
};

type MarketRow = {
  market_id: string;
  checkpoint: string;
  question: string;
  observed_at: string;
  market_probability: number;
  condition_count: number;
  direct_probability: number | null;
  structured_probability: number | null;
  market_aware_probability: number | null;
  retrieval_status: string | null;
  retrieval_attempt_number: number | null;
  has_valid_packet: boolean;
  pipeline_status: string;
};

type MarketsPayload = {
  protocol_version: string;
  count: number;
  rows: MarketRow[];
};

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function pct(value: number | null): string {
  return value === null ? "—" : `${(100 * value).toFixed(1)}%`;
}

function signed(value: number | null): string {
  if (value === null) return "—";

  return `${value > 0 ? "+" : ""}${value.toFixed(4)}`;
}

function statusLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function App() {
  const [page, setPage] = useState<Page>("overview");

  const [selectedMarket, setSelectedMarket] = useState<{
    marketId: string;
    checkpoint: string;
  } | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [results, setResults] = useState<ResultsPayload | null>(null);
  const [markets, setMarkets] = useState<MarketsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchJson<Health>("/api/health"),
      fetchJson<{ funnel: Funnel }>("/api/funnel"),
      fetchJson<ResultsPayload>("/api/results/primary"),
      fetchJson<MarketsPayload>("/api/markets"),
    ])
      .then(([healthData, funnelData, resultsData, marketsData]) => {
        setHealth(healthData);
        setFunnel(funnelData.funnel);
        setResults(resultsData);
        setMarkets(marketsData);
      })
      .catch((caught: unknown) => {
        setError(
          caught instanceof Error
            ? caught.message
            : String(caught),
        );
      });
  }, []);

  const chartData = useMemo(() => {
    if (!results) return [];

    return [
      {
        name: "A Market",
        value: results.summary.mean_market_brier,
      },
      {
        name: "B Direct",
        value: results.summary.mean_direct_brier,
      },
      {
        name: "C Structured",
        value: results.summary.mean_structured_brier,
      },
      {
        name: "D + Market",
        value: results.summary.mean_market_aware_brier,
      },
    ].filter(
      (
        row,
      ): row is {
        name: string;
        value: number;
      } => row.value !== null,
    );
  }, [results]);

  if (error) {
    return (
      <main className="shell">
        <section className="state-card">
          <div className="kicker">Forecast Ledger</div>
          <h1>Research engine unavailable</h1>
          <p>{error}</p>
        </section>
      </main>
    );
  }

  if (!health || !funnel || !results || !markets) {
    return (
      <main className="shell">
        <div className="loading">Loading experiment…</div>
      </main>
    );
  }

  const primaryCoverage =
    funnel.primary_included === 0
      ? null
      : funnel.primary_matched / funnel.primary_included;

  return (
    <main className="shell">
      <header className="masthead">
        <div className="brand-block">
          <div className="kicker">Live prospective experiment</div>
          <h1>Forecast Ledger</h1>
          <p className="subtitle">
            Testing whether structured reasoning and market information improve
            probabilistic forecasts from a fixed model.
          </p>
        </div>

        <div className="protocol-pill">
          <span className="status-dot" />
          {health.protocol_version}
        </div>
      </header>

      <nav className="nav">
        {(["overview", "results", "markets", "audit"] as Page[]).map(
          (item) => (
            <button
              key={item}
              className={page === item ? "nav-active" : ""}
              onClick={() => {
                setSelectedMarket(null);
                setPage(item);
              }}
              type="button"
            >
              {item[0].toUpperCase() + item.slice(1)}
            </button>
          ),
        )}
      </nav>

      {selectedMarket ? (
        <MarketDetail
          marketId={selectedMarket.marketId}
          checkpoint={selectedMarket.checkpoint}
          onBack={() => setSelectedMarket(null)}
        />
      ) : page === "overview" && (
        <>
          <section className="metrics">
            <Metric label="Frozen snapshots" value={funnel.snapshots} />
            <Metric label="Machine eligible" value={funnel.eligible} />
            <Metric label="Semantically included" value={funnel.included} />
            <Metric label="Matched B/C/D" value={funnel.matched} />
          </section>

          <section className="hero-grid">
            <article className="panel primary-panel">
              <div className="panel-heading">
                <div>
                  <div className="kicker">Primary · 7 day</div>
                  <h2>Does structure improve the model?</h2>
                </div>

                <div className="n-pill">N = {results.summary.n}</div>
              </div>

              <div className="effect-grid">
                <Effect
                  label="Structured advantage"
                  value={results.summary.mean_structured_advantage}
                  formula="Brier(B) − Brier(C)"
                />

                <Effect
                  label="Market-information effect"
                  value={
                    results.summary.mean_market_information_advantage
                  }
                  formula="Brier(C) − Brier(D)"
                />
              </div>

              <div className="pilot-note">
                {results.summary.n < 20
                  ? "Pilot evidence. Too few resolved primary markets for inference."
                  : "Prospective paired evidence."}
              </div>
            </article>

            <article className="panel coverage-panel">
              <div className="kicker">Primary matched coverage</div>

              <div className="coverage-number">
                {primaryCoverage === null
                  ? "—"
                  : `${(100 * primaryCoverage).toFixed(0)}%`}
              </div>

              <p className="muted">
                {funnel.primary_matched} of {funnel.primary_included} included
                7-day checkpoints have complete matched B/C/D forecasts.
              </p>

              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{
                    width: `${
                      primaryCoverage === null
                        ? 0
                        : Math.min(100, 100 * primaryCoverage)
                    }%`,
                  }}
                />
              </div>
            </article>
          </section>

          <section className="panel chart-panel">
            <div className="panel-heading">
              <div>
                <div className="kicker">Resolved primary sample</div>
                <h2>Mean Brier score</h2>
              </div>

              <span className="quiet-pill">Lower is better</span>
            </div>

            <div className="chart">
              <ResponsiveContainer width="100%" height={290}>
                <BarChart data={chartData}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    vertical={false}
                    opacity={0.16}
                  />
                  <XAxis
                    dataKey="name"
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip />
                  <Bar
                    dataKey="value"
                    fill="currentColor"
                    radius={[9, 9, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      )}

      {!selectedMarket && page === "results" && (
        <ResultsView
          funnel={funnel}
          onOpenMarket={(marketId, checkpoint) =>
            setSelectedMarket({
              marketId,
              checkpoint,
            })
          }
        />
      )}

      {!selectedMarket && page === "markets" && (
        <>
          <section className="section-head">
            <div>
              <div className="kicker">Prospective ledger</div>
              <h2>Included checkpoints</h2>
            </div>

            <div className="n-pill">{markets.count} rows</div>
          </section>

          <section className="panel">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Checkpoint</th>
                    <th>Market</th>
                    <th>B</th>
                    <th>C</th>
                    <th>D</th>
                    <th>Status</th>
                  </tr>
                </thead>

                <tbody>
                  {markets.rows.map((row) => (
                    <tr
                      key={`${row.market_id}-${row.checkpoint}`}
                      className="clickable-row"
                      onClick={() =>
                        setSelectedMarket({
                          marketId: row.market_id,
                          checkpoint: row.checkpoint,
                        })
                      }
                    >
                      <td>
                        <div className="question">{row.question}</div>
                        <div className="row-meta">{row.market_id}</div>
                      </td>

                      <td>{row.checkpoint}</td>
                      <td>{pct(row.market_probability)}</td>
                      <td>{pct(row.direct_probability)}</td>
                      <td>{pct(row.structured_probability)}</td>
                      <td>{pct(row.market_aware_probability)}</td>

                      <td>
                        <span
                          className={`status-pill status-${row.pipeline_status}`}
                        >
                          {statusLabel(row.pipeline_status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {!selectedMarket && page === "audit" && (
        <section className="audit-grid">
          <article className="panel">
            <div className="kicker">Research authority</div>
            <h2>Truth-preserving boundary</h2>

            <AuditRow
              label="Protocol"
              value={health.protocol_version}
            />
            <AuditRow
              label="Database"
              value={health.database_exists ? "Connected" : "Missing"}
            />
            <AuditRow
              label="API mode"
              value={health.read_only ? "Read-only" : "Unexpected write access"}
            />
            <AuditRow
              label="Primary resolved N"
              value={String(results.summary.n)}
            />
            <AuditRow
              label="Matched checkpoints"
              value={String(funnel.matched)}
            />
          </article>

          <article className="panel">
            <div className="kicker">Primary quantities</div>
            <h2>Paired effects</h2>

            <AuditRow
              label="Structured advantage"
              value={signed(results.summary.mean_structured_advantage)}
            />
            <AuditRow
              label="Market-information effect"
              value={signed(
                results.summary.mean_market_information_advantage,
              )}
            />
            <AuditRow
              label="Primary matched coverage"
              value={
                primaryCoverage === null
                  ? "—"
                  : `${(100 * primaryCoverage).toFixed(1)}%`
              }
            />
          </article>
        </section>
      )}
    </main>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <article className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </article>
  );
}

function Effect({
  label,
  value,
  formula,
}: {
  label: string;
  value: number | null;
  formula: string;
}) {
  const className =
    value === null
      ? ""
      : value > 0
        ? "positive"
        : value < 0
          ? "negative"
          : "";

  return (
    <div className="effect">
      <div className="effect-label">{label}</div>
      <div className={`effect-value ${className}`}>
        {signed(value)}
      </div>
      <div className="formula">{formula}</div>
    </div>
  );
}

function AuditRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="audit-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
