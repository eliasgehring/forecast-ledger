import {
  useEffect,
  useState,
} from "react";

type PipelineSlice = {
  checkpoints: number;
  unique_markets: number;

  matched: number;
  blocked: number;
  interrupted: number;
  partial_forecast: number;
  other: number;
};

type NonMatched = {
  market_id: string;
  checkpoint: string;
  question: string;

  pipeline_status: string;

  retrieval_status: string | null;
  retrieval_attempt_number:
    number | null;
  retrieval_error_type:
    string | null;

  has_valid_packet: boolean;
  condition_count: number;
};

type HealthPayload = {
  protocol_version: string;

  health: {
    overall: PipelineSlice;
    primary_7d: PipelineSlice;

    primary_resolved_scored: number;

    retrieval_failure_types: Array<{
      name: string;
      count: number;
    }>;

    nonmatched_checkpoints:
      NonMatched[];
  };
};

function percentage(
  numerator: number,
  denominator: number,
): string {
  if (denominator === 0) {
    return "—";
  }

  return `${(
    (numerator / denominator)
    * 100
  ).toFixed(0)}%`;
}

function pretty(
  value: string,
): string {
  return value
    .replaceAll("_", " ")
    .replace(
      /\b\w/g,
      (letter) =>
        letter.toUpperCase(),
    );
}

export default function ExperimentHealthPanel() {
  const [data, setData] =
    useState<HealthPayload | null>(
      null,
    );

  const [error, setError] =
    useState<string | null>(
      null,
    );

  useEffect(() => {
    fetch("/api/experiment-health")
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Experiment health returned ${response.status}`,
          );
        }

        return response.json();
      })
      .then(
        (
          payload: HealthPayload,
        ) => {
          setData(payload);
        },
      )
      .catch(
        (caught: unknown) => {
          setError(
            caught instanceof Error
              ? caught.message
              : String(caught),
          );
        },
      );
  }, []);

  if (error) {
    return (
      <section className="panel">
        <div className="kicker">
          Experiment health
        </div>

        <p className="muted">
          {error}
        </p>
      </section>
    );
  }

  if (!data) {
    return (
      <div className="loading">
        Loading experiment health…
      </div>
    );
  }

  const health = data.health;
  const overall = health.overall;
  const primary = health.primary_7d;

  const unmatched =
    overall.checkpoints
    - overall.matched;

  return (
    <section className="panel experiment-health">
      <div className="panel-heading">
        <div>
          <div className="kicker">
            Experiment health
          </div>

          <h2>
            Where did the observations go?
          </h2>

          <p className="health-intro">
            Counts below are checkpoint
            observations, not independent
            markets. Repeated horizons for
            one market remain separate
            checkpoints.
          </p>
        </div>

        <span className="quiet-pill">
          {data.protocol_version}
        </span>
      </div>

      <div className="health-overview">
        <HealthMetric
          label="Included checkpoints"
          value={overall.checkpoints}
          note={`${overall.unique_markets} unique markets`}
        />

        <HealthMetric
          label="Matched B/C/D"
          value={overall.matched}
          note={`${percentage(
            overall.matched,
            overall.checkpoints,
          )} coverage`}
        />

        <HealthMetric
          label="Non-matched"
          value={unmatched}
          note={
            "Preserved, never silently dropped"
          }
        />

        <HealthMetric
          label="Primary scored"
          value={
            health.primary_resolved_scored
          }
          note={`${percentage(
            health.primary_resolved_scored,
            primary.matched,
          )} of matched 7d`}
        />
      </div>

      <div className="health-columns">
        <div>
          <div className="health-section-title">
            Overall checkpoint states
          </div>

          <HealthBar
            label="Matched"
            count={overall.matched}
            total={overall.checkpoints}
          />

          <HealthBar
            label="Blocked"
            count={overall.blocked}
            total={overall.checkpoints}
          />

          <HealthBar
            label="Interrupted"
            count={
              overall.interrupted
            }
            total={
              overall.checkpoints
            }
          />

          <HealthBar
            label="Partial forecast"
            count={
              overall.partial_forecast
            }
            total={
              overall.checkpoints
            }
          />

          {overall.other > 0 && (
            <HealthBar
              label="Other"
              count={overall.other}
              total={
                overall.checkpoints
              }
            />
          )}
        </div>

        <div>
          <div className="health-section-title">
            Primary 7d
          </div>

          <div className="primary-health-flow">
            <HealthFlowStep
              label="Included"
              value={
                primary.checkpoints
              }
            />

            <span>→</span>

            <HealthFlowStep
              label="Matched"
              value={primary.matched}
            />

            <span>→</span>

            <HealthFlowStep
              label="Scored"
              value={
                health.primary_resolved_scored
              }
            />
          </div>

          <div className="health-small-note">
            Match coverage{" "}
            {percentage(
              primary.matched,
              primary.checkpoints,
            )}
            {" · "}
            resolution coverage among
            matched{" "}
            {percentage(
              health.primary_resolved_scored,
              primary.matched,
            )}
          </div>

          {health.retrieval_failure_types
            .length > 0 && (
            <>
              <div className="health-section-title health-errors-title">
                Retrieval failure types
              </div>

              <div className="failure-pills">
                {health
                  .retrieval_failure_types
                  .map((item) => (
                    <span
                      key={item.name}
                      className="failure-pill"
                    >
                      {item.name}
                      {" · "}
                      {item.count}
                    </span>
                  ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="health-section-title health-ledger-title">
        Preserved non-matched checkpoints
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Checkpoint</th>
              <th>Market</th>
              <th>Status</th>
              <th>Retrieval</th>
              <th>Forecasts</th>
            </tr>
          </thead>

          <tbody>
            {health
              .nonmatched_checkpoints
              .map((row) => (
                <tr
                  key={`${row.market_id}-${row.checkpoint}`}
                >
                  <td>
                    {row.checkpoint}
                  </td>

                  <td>
                    <div className="question">
                      {row.question}
                    </div>

                    <div className="row-meta">
                      {row.market_id}
                    </div>
                  </td>

                  <td>
                    <span
                      className={`status-pill status-${row.pipeline_status}`}
                    >
                      {pretty(
                        row.pipeline_status,
                      )}
                    </span>
                  </td>

                  <td>
                    <div>
                      {row.retrieval_status
                        ? pretty(
                            row.retrieval_status,
                          )
                        : "—"}
                    </div>

                    {row.retrieval_error_type && (
                      <div className="row-meta">
                        {
                          row.retrieval_error_type
                        }
                      </div>
                    )}
                  </td>

                  <td>
                    {row.condition_count}/3
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function HealthMetric({
  label,
  value,
  note,
}: {
  label: string;
  value: number;
  note: string;
}) {
  return (
    <div className="health-metric">
      <span>{label}</span>

      <strong>{value}</strong>

      <small>{note}</small>
    </div>
  );
}

function HealthBar({
  label,
  count,
  total,
}: {
  label: string;
  count: number;
  total: number;
}) {
  const width =
    total === 0
      ? 0
      : (count / total) * 100;

  return (
    <div className="health-bar-row">
      <div className="health-bar-label">
        <span>{label}</span>
        <strong>{count}</strong>
      </div>

      <div className="health-bar-track">
        <div
          className="health-bar-fill"
          style={{
            width: `${width}%`,
          }}
        />
      </div>
    </div>
  );
}

function HealthFlowStep({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="health-flow-step">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
