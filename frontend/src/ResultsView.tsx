import { useEffect, useMemo, useState } from "react";

type Checkpoint =
  | "7d"
  | "1d"
  | "3d"
  | "14d";

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
  checkpoint: Checkpoint;
  outcome_yes: boolean;

  market_probability: number;
  direct_probability: number;
  structured_probability: number;
  market_aware_probability: number;

  market_brier: number;
  direct_brier: number;
  structured_brier: number;
  market_aware_brier: number;

  structured_advantage: number;
  market_information_advantage: number;
};

type ResultsPayload = {
  protocol_version: string;
  summary: Summary;
  rows: ResultRow[];
};

type Funnel = {
  primary_included: number;
  primary_matched: number;
};

type Props = {
  funnel: Funnel;

  onOpenMarket: (
    marketId: string,
    checkpoint: string,
  ) => void;
};

const HORIZONS: Array<{
  value: Checkpoint;
  label: string;
  role: string;
}> = [
  {
    value: "7d",
    label: "7 day",
    role: "Primary",
  },
  {
    value: "1d",
    label: "1 day",
    role: "Secondary",
  },
  {
    value: "3d",
    label: "3 day",
    role: "Secondary",
  },
  {
    value: "14d",
    label: "14 day",
    role: "Secondary",
  },
];

function fmt(
  value: number | null,
  digits = 4,
): string {
  if (value === null) {
    return "—";
  }

  return value.toFixed(digits);
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function signed(
  value: number | null,
): string {
  if (value === null) {
    return "—";
  }

  const prefix =
    value > 0
      ? "+"
      : "";

  return `${prefix}${value.toFixed(4)}`;
}

function coverage(
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

function directionText(
  effect: number | null,
  left: string,
  right: string,
): string {
  if (effect === null) {
    return "No resolved matched observations yet.";
  }

  if (effect > 0) {
    return `${right} currently has the lower mean Brier score.`;
  }

  if (effect < 0) {
    return `${left} currently has the lower mean Brier score.`;
  }

  return "The observed mean Brier scores are tied.";
}

function maturityText(
  n: number,
): string {
  if (n === 0) {
    return "No resolved matched observations yet.";
  }

  return (
    "Descriptive prospective evidence only. "
    + "The current sample is too small for a strong inference."
  );
}

export default function ResultsView({
  funnel,
  onOpenMarket,
}: Props) {
  const [active, setActive] =
    useState<Checkpoint>("7d");

  const [payloads, setPayloads] =
    useState<
      Partial<
        Record<
          Checkpoint,
          ResultsPayload
        >
      >
    >({});

  const [error, setError] =
    useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    Promise.all(
      HORIZONS.map(async ({ value }) => {
        const response = await fetch(
          `/api/results/checkpoints?checkpoint=${value}`,
        );

        if (!response.ok) {
          throw new Error(
            `Results ${value} returned ${response.status}`,
          );
        }

        const payload = (
          await response.json()
        ) as ResultsPayload;

        return [
          value,
          payload,
        ] as const;
      }),
    )
      .then((entries) => {
        if (cancelled) {
          return;
        }

        setPayloads(
          Object.fromEntries(
            entries,
          ) as Record<
            Checkpoint,
            ResultsPayload
          >,
        );
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return;
        }

        setError(
          caught instanceof Error
            ? caught.message
            : String(caught),
        );
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const data = payloads[active];

  const horizon = HORIZONS.find(
    (item) =>
      item.value === active,
  );

  const orderedRows = useMemo(() => {
    if (!data) {
      return [];
    }

    return [...data.rows].sort(
      (a, b) =>
        a.market_id.localeCompare(
          b.market_id,
        ),
    );
  }, [data]);

  if (error) {
    return (
      <section className="panel">
        <div className="kicker">
          Results
        </div>

        <h2>
          Results endpoint unavailable
        </h2>

        <p className="muted">
          {error}
        </p>
      </section>
    );
  }

  if (!data || !horizon) {
    return (
      <div className="loading">
        Loading scored checkpoints…
      </div>
    );
  }

  const summary = data.summary;

  const resolutionCoverage =
    funnel.primary_matched === 0
      ? "—"
      : coverage(
          summary.n,
          funnel.primary_matched,
        );

  return (
    <>
      <section className="results-hero">
        <div>
          <div className="kicker">
            Prospective scoring
          </div>

          <h2 className="results-title">
            What has the experiment
            actually learned?
          </h2>

          <p className="results-subtitle">
            Brier score is the primary
            metric. Lower is better.
            Paired effects preserve the
            frozen v0.2 comparison:
            B→C tests structured
            elicitation, C→D tests added
            market information.
          </p>
        </div>

        <div className="results-version">
          {data.protocol_version}
        </div>
      </section>

      <section className="horizon-tabs">
        {HORIZONS.map((item) => {
          const itemData =
            payloads[item.value];

          return (
            <button
              key={item.value}
              type="button"
              className={
                active === item.value
                  ? "horizon-tab horizon-active"
                  : "horizon-tab"
              }
              onClick={() =>
                setActive(item.value)
              }
            >
              <span>
                {item.label}
              </span>

              <small>
                {item.role}
                {itemData
                  ? ` · N=${itemData.summary.n}`
                  : ""}
              </small>
            </button>
          );
        })}
      </section>

      <section className="results-context">
        <div>
          <span className="context-role">
            {horizon.role}
          </span>

          <strong>
            {horizon.label} checkpoint
          </strong>
        </div>

        <div className="context-n">
          N = {summary.n} resolved
        </div>
      </section>

      <section className="effect-question-grid">
        <EffectQuestion
          eyebrow="Primary comparison"
          question={
            "Does structured elicitation improve the fixed model?"
          }
          leftLabel="B Direct"
          leftValue={
            summary.mean_direct_brier
          }
          rightLabel="C Structured"
          rightValue={
            summary.mean_structured_brier
          }
          effectLabel="Brier(B) − Brier(C)"
          effect={
            summary.mean_structured_advantage
          }
          interpretation={directionText(
            summary.mean_structured_advantage,
            "B Direct",
            "C Structured",
          )}
        />

        <EffectQuestion
          eyebrow="Market-information comparison"
          question={
            "Does adding the market improve structured forecasts?"
          }
          leftLabel="C Structured"
          leftValue={
            summary.mean_structured_brier
          }
          rightLabel="D + Market"
          rightValue={
            summary.mean_market_aware_brier
          }
          effectLabel="Brier(C) − Brier(D)"
          effect={
            summary.mean_market_information_advantage
          }
          interpretation={directionText(
            summary.mean_market_information_advantage,
            "C Structured",
            "D + Market",
          )}
        />
      </section>

      <section className="panel maturity-panel">
        <div className="maturity-copy">
          <div className="kicker">
            Evidence maturity
          </div>

          <h2>
            {summary.n === 0
              ? "Awaiting outcomes"
              : "Early evidence, not a verdict"}
          </h2>

          <p>
            {maturityText(
              summary.n,
            )}
          </p>
        </div>

        <div className="maturity-stat">
          <span>
            Resolved matched
          </span>

          <strong>
            {summary.n}
          </strong>
        </div>
      </section>

      {active === "7d" && (
        <section className="panel sample-pipeline">
          <div className="panel-heading">
            <div>
              <div className="kicker">
                Primary sample integrity
              </div>

              <h2>
                Included → matched →
                scored
              </h2>
            </div>

            <span className="quiet-pill">
              Frozen 7d cohort
            </span>
          </div>

          <div className="pipeline-steps">
            <PipelineStep
              label="Included"
              value={
                funnel.primary_included
              }
              note={
                "Passed machine and semantic eligibility"
              }
            />

            <div className="pipeline-arrow">
              →
            </div>

            <PipelineStep
              label="Matched"
              value={
                funnel.primary_matched
              }
              note={
                `${coverage(
                  funnel.primary_matched,
                  funnel.primary_included,
                )} of included`
              }
            />

            <div className="pipeline-arrow">
              →
            </div>

            <PipelineStep
              label="Resolved + scored"
              value={summary.n}
              note={
                `${resolutionCoverage} of matched`
              }
            />
          </div>

          <p className="pipeline-note">
            A checkpoint can have a
            complete B/C/D forecast set
            without being scored yet.
            Scoring requires an explicit
            terminal YES/NO resolution.
          </p>
        </section>
      )}

      <section className="results-score-strip">
        <MeanScore
          label="A Market"
          value={
            summary.mean_market_brier
          }
        />

        <MeanScore
          label="B Direct"
          value={
            summary.mean_direct_brier
          }
        />

        <MeanScore
          label="C Structured"
          value={
            summary.mean_structured_brier
          }
        />

        <MeanScore
          label="D + Market"
          value={
            summary.mean_market_aware_brier
          }
        />
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <div className="kicker">
              Resolved checkpoints
            </div>

            <h2>
              Paired observation ledger
            </h2>
          </div>

          <span className="quiet-pill">
            {orderedRows.length} rows
          </span>
        </div>

        {orderedRows.length === 0 ? (
          <div className="empty-results">
            No resolved matched{" "}
            {active} checkpoints yet.
            The experiment remains
            prospective.
          </div>
        ) : (
          <div className="table-wrap results-table-wrap">
            <table className="results-ledger">
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Outcome</th>
                  <th>A Market</th>
                  <th>B Direct</th>
                  <th>C Structured</th>
                  <th>D + Market</th>
                  <th>B→C</th>
                  <th>C→D</th>
                </tr>
              </thead>

              <tbody>
                {orderedRows.map(
                  (row) => {
                    const best =
                      Math.min(
                        row.market_brier,
                        row.direct_brier,
                        row.structured_brier,
                        row.market_aware_brier,
                      );

                    return (
                      <tr
                        key={`${row.market_id}-${row.checkpoint}`}
                        className="clickable-row"
                        onClick={() =>
                          onOpenMarket(
                            row.market_id,
                            row.checkpoint,
                          )
                        }
                      >
                        <td>
                          <div className="question">
                            {row.question}
                          </div>

                          <div className="row-meta">
                            {row.market_id}
                            {" · "}
                            {row.checkpoint}
                          </div>
                        </td>

                        <td>
                          <span className="outcome-pill">
                            {row.outcome_yes
                              ? "YES"
                              : "NO"}
                          </span>
                        </td>

                        <ScoreCell
                          probability={
                            row.market_probability
                          }
                          brier={
                            row.market_brier
                          }
                          best={
                            row.market_brier
                            === best
                          }
                        />

                        <ScoreCell
                          probability={
                            row.direct_probability
                          }
                          brier={
                            row.direct_brier
                          }
                          best={
                            row.direct_brier
                            === best
                          }
                        />

                        <ScoreCell
                          probability={
                            row.structured_probability
                          }
                          brier={
                            row.structured_brier
                          }
                          best={
                            row.structured_brier
                            === best
                          }
                        />

                        <ScoreCell
                          probability={
                            row.market_aware_probability
                          }
                          brier={
                            row.market_aware_brier
                          }
                          best={
                            row.market_aware_brier
                            === best
                          }
                        />

                        <td>
                          <EffectCell
                            value={
                              row.structured_advantage
                            }
                          />
                        </td>

                        <td>
                          <EffectCell
                            value={
                              row.market_information_advantage
                            }
                          />
                        </td>
                      </tr>
                    );
                  },
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="results-footnote">
        <strong>
          Interpretation rule:
        </strong>{" "}
        positive B→C means C had lower
        Brier than B; positive C→D means
        D had lower Brier than C.
        Negative values mean the
        opposite. Direction is not
        statistical significance.
      </section>
    </>
  );
}

function EffectQuestion({
  eyebrow,
  question,
  leftLabel,
  leftValue,
  rightLabel,
  rightValue,
  effectLabel,
  effect,
  interpretation,
}: {
  eyebrow: string;
  question: string;
  leftLabel: string;
  leftValue: number | null;
  rightLabel: string;
  rightValue: number | null;
  effectLabel: string;
  effect: number | null;
  interpretation: string;
}) {
  return (
    <article className="panel effect-question">
      <div className="kicker">
        {eyebrow}
      </div>

      <h2>
        {question}
      </h2>

      <div className="comparison-pair">
        <div>
          <span>
            {leftLabel}
          </span>

          <strong>
            {fmt(leftValue)}
          </strong>
        </div>

        <div className="versus">
          vs
        </div>

        <div>
          <span>
            {rightLabel}
          </span>

          <strong>
            {fmt(rightValue)}
          </strong>
        </div>
      </div>

      <div className="effect-result">
        <div>
          <span>
            {effectLabel}
          </span>

          <strong>
            {signed(effect)}
          </strong>
        </div>

        <p>
          {interpretation}
        </p>
      </div>
    </article>
  );
}

function PipelineStep({
  label,
  value,
  note,
}: {
  label: string;
  value: number;
  note: string;
}) {
  return (
    <div className="pipeline-step">
      <span>
        {label}
      </span>

      <strong>
        {value}
      </strong>

      <small>
        {note}
      </small>
    </div>
  );
}

function MeanScore({
  label,
  value,
}: {
  label: string;
  value: number | null;
}) {
  return (
    <article className="mean-score-card">
      <span>
        {label}
      </span>

      <strong>
        {fmt(value)}
      </strong>

      <small>
        Mean Brier
      </small>
    </article>
  );
}

function ScoreCell({
  probability,
  brier,
  best,
}: {
  probability: number;
  brier: number;
  best: boolean;
}) {
  return (
    <td
      className={
        best
          ? "score-cell score-best"
          : "score-cell"
      }
    >
      <strong>
        {brier.toFixed(4)}
      </strong>

      <small>
        P(YES) {pct(probability)}
      </small>
    </td>
  );
}

function EffectCell({
  value,
}: {
  value: number;
}) {
  return (
    <span className="paired-effect">
      {value > 0 ? "+" : ""}
      {value.toFixed(4)}
    </span>
  );
}
