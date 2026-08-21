import { useEffect, useState } from "react";
import "./App.css";

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

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/health").then((response) => {
        if (!response.ok) {
          throw new Error("Health endpoint failed.");
        }

        return response.json();
      }),

      fetch("/api/funnel").then((response) => {
        if (!response.ok) {
          throw new Error("Research funnel endpoint failed.");
        }

        return response.json();
      }),
    ])
      .then(([healthPayload, funnelPayload]) => {
        setHealth(healthPayload);
        setFunnel(funnelPayload.funnel);
      })
      .catch((caught) => {
        setError(
          caught instanceof Error
            ? caught.message
            : String(caught),
        );
      });
  }, []);

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

  if (!health || !funnel) {
    return (
      <main className="shell">
        <div className="loading">
          Loading experiment…
        </div>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="header">
        <div>
          <div className="kicker">
            Live prospective experiment
          </div>

          <h1>Forecast Ledger</h1>

          <p className="subtitle">
            Testing whether structured reasoning and
            market information improve probabilistic
            forecasts from a fixed model.
          </p>
        </div>

        <div className="protocol">
          {health.protocol_version}
        </div>
      </header>

      <section className="metrics">
        <Metric
          label="Frozen snapshots"
          value={funnel.snapshots}
        />

        <Metric
          label="Machine eligible"
          value={funnel.eligible}
        />

        <Metric
          label="Semantically included"
          value={funnel.included}
        />

        <Metric
          label="Matched B/C/D"
          value={funnel.matched}
        />
      </section>

      <section className="panel">
        <div>
          <div className="kicker">
            Research integrity
          </div>

          <h2>Read-only experiment interface</h2>
        </div>

        <div className="integrity-row">
          <span>
            Database
          </span>

          <strong>
            {health.database_exists
              ? "Connected"
              : "Missing"}
          </strong>
        </div>

        <div className="integrity-row">
          <span>
            API authority
          </span>

          <strong>
            {health.read_only
              ? "Read-only"
              : "Unexpected write access"}
          </strong>
        </div>

        <div className="integrity-row">
          <span>
            Primary matched coverage
          </span>

          <strong>
            {funnel.primary_matched}
            {" / "}
            {funnel.primary_included}
          </strong>
        </div>
      </section>
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
      <div className="metric-label">
        {label}
      </div>

      <div className="metric-value">
        {value}
      </div>
    </article>
  );
}
