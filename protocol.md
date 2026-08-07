# Forecast Ledger Research Protocol

**Status:** FROZEN
**Protocol version:** v0.1
**Scored forecasts permitted:** Yes
**Created:** 2026-08-06
**Frozen:** 2026-08-07

## 1. Research question

Does a structured LLM forecasting process produce better probabilistic forecasts than:

1. a direct LLM forecast;
2. the contemporaneous Polymarket probability?

The project evaluates forecast quality, not trading profitability.

## 2. Probability semantics

Every stored probability means:

> P(the selected Polymarket market resolves YES)

A probability is not a trade instruction.

The following remain distinct:

- market probability;
- model probability;
- forecast difference;
- execution price;
- final settlement.

## 3. Forecasting conditions

Each eligible market will receive four matched forecasts.

### Condition A: Market benchmark

The midpoint of the live YES bid and ask from the market snapshot recorded at forecast time.

### Condition B: Direct LLM baseline

The model receives the question, resolution rules, and frozen evidence packet.

It returns one probability of YES with minimal forecasting structure.

It does not receive the market probability.

### Condition C: Structured independent forecaster

The model receives the same question, resolution rules, and evidence packet.

It must identify:

- a reference class;
- an estimated base rate;
- the strongest evidence for YES;
- the strongest evidence for NO;
- the key uncertainty;
- a final probability of YES.

It does not receive the market probability, bid, ask, spread, or any market-derived field.

### Condition D: Structured market-aware forecaster

The model receives the same evidence packet and structured forecasting instructions as Condition C.

It additionally receives the contemporaneous market probability from the matched market snapshot.

## 4. Shared-information rule

Conditions B, C, and D must use the same frozen evidence packet.

Retrieval may occur once per market checkpoint.

Forecasting conditions may not retrieve additional evidence independently.

This prevents differences in source selection from being mistaken for differences in forecasting ability.

## 5. Market eligibility

A market is eligible only if all of the following conditions hold at the time of selection:

1. The market has exactly two outcomes: YES and NO.
2. The resolution criteria define an externally verifiable event.
3. The market is active and has not resolved, closed, or been cancelled.
4. The scheduled close time is between 5 and 45 days away.
5. A live best bid and best ask exist for the YES token.
6. The YES bid-ask spread is no greater than 0.10.
7. The market probability lies between 0.05 and 0.95.
8. The market belongs to one of the permitted categories:
   - technology;
   - business;
   - science;
   - geopolitics.
9. The market is not an obvious duplicate of another selected market.
10. The outcome is not already effectively known from publicly available information.

The selection decision must be stored before any LLM forecast is generated.

A rejected market must receive an explicit exclusion reason.

## 6. Market exclusions

A market must be excluded if any of the following applies:

- the resolution language is subjective or materially ambiguous;
- the system cannot establish a stable meaning for YES;
- the event contains multiple linked conditions whose settlement cannot be represented clearly as YES or NO;
- the market depends primarily on private or inaccessible information;
- the market is a duplicate or near-duplicate of an already selected question;
- the bid or ask is missing;
- the spread exceeds the permitted threshold;
- the market is already effectively resolved;
- Polymarket marks the market as cancelled, invalid, or otherwise unsuitable for ordinary settlement.

Exclusions are part of the research record and may not be deleted after outcomes become known.

## 7. Forecast checkpoints

Forecasts are created at predefined checkpoints relative to the scheduled market close.

The standard checkpoints are:

- 14 days before close;
- 7 days before close;
- 3 days before close;
- 1 day before close.

A checkpoint forecast may be created within a tolerance of plus or minus 6 hours around the target time.

If a market becomes eligible only after a checkpoint has passed, that checkpoint is recorded as unavailable rather than reconstructed retrospectively.

No historical forecast may ever be manufactured after the checkpoint has passed.

Each combination of:

- market;
- checkpoint;
- forecasting condition;
- model version;
- protocol version

may produce at most one scored forecast.

Repeated forecasts from the same market are not treated as statistically independent observations.

## 8. Information cutoff and timestamp semantics

Each checkpoint begins by recording one live Polymarket market snapshot.

The snapshot timestamp defines the information cutoff for that checkpoint.

The following sequence must be preserved:

1. record the live market snapshot;
2. freeze its timestamp as the information cutoff;
3. retrieve candidate evidence;
4. reject evidence published after the information cutoff;
5. freeze one evidence packet;
6. run all LLM forecasting conditions from that same packet;
7. store the resulting forecasts immutably.

The market benchmark is calculated from the same snapshot used to define the information cutoff.

Therefore:

> market probability and model forecasts are matched to one checkpoint and one market snapshot.

Evidence retrieval may complete after the information cutoff, but an evidence item is eligible only if its publication time is known and is no later than the information cutoff.

The following timestamps are distinct and must not be conflated:

- `observed_at`: when the market snapshot was recorded;
- `information_cutoff`: the latest publication time permitted for model evidence;
- `published_at`: when an evidence item became public;
- `retrieved_at`: when Forecast Ledger retrieved the evidence item;
- `forecast_created_at`: when a model forecast was successfully produced.

For version 0.1:

> `information_cutoff = market_snapshot.observed_at`

A forecast must never use a market snapshot collected after that forecast's information cutoff.

A forecast must never use evidence published after that forecast's information cutoff.

## 9. Evidence validity

An evidence item is eligible only if all of the following are true:

1. The source is publicly accessible.
2. The item is relevant to the market's resolution.
3. The source URL is stored.
4. The item has a usable publication time.
5. The publication time is no later than the information cutoff.
6. The retrieved content can be tied to the stored source.
7. The evidence item is stored before any forecasting condition is executed.

Each evidence item must record:

- `evidence_id`;
- `source_url`;
- `source_name`;
- `title`;
- `published_at`;
- `retrieved_at`;
- `excerpt`;
- `timestamp_quality`.

Permitted timestamp-quality values are:

- `verified`: a precise publication timestamp is available from the source or reliable metadata;
- `reported`: a precise timestamp is reported by a credible retrieval source but cannot be independently verified from the page;
- `date_only`: only the publication date is known;
- `unknown`: no reliable publication time can be established.

Evidence with `timestamp_quality = unknown` is excluded.

For `date_only` evidence, the system must use a conservative effective publication time of 23:59:59 UTC on the reported publication date.

Therefore, a date-only source published on the same calendar day as the information cutoff will usually be excluded until the following day.

This rule intentionally sacrifices some usable evidence in exchange for protection against future-information leakage.

## 10. Frozen evidence packet

For each market checkpoint, Forecast Ledger creates exactly one frozen evidence packet.

The packet must contain:

- `packet_id`;
- `market_id`;
- `snapshot_id`;
- `information_cutoff`;
- ordered evidence IDs;
- retrieval model or method;
- retrieval prompt version;
- creation timestamp.

After the packet is frozen, its contents may not be altered.

Conditions B, C, and D must receive the same packet.

No forecasting condition may:

- browse independently;
- request additional sources;
- replace evidence items;
- remove evidence items;
- access evidence published after the information cutoff.

If evidence retrieval fails completely, the checkpoint is recorded as a retrieval failure rather than silently skipped.

If the packet contains no valid evidence, the forecasting conditions may still run using only the market question and resolution rules, but the packet must explicitly record that it contains zero evidence items.

## 11. Evidence identity invariant

Every evidence citation produced by an LLM must refer to an `evidence_id` contained in the frozen packet.

An unknown or invented evidence ID invalidates that model output.

The system may retry a schema or citation failure according to a fixed retry policy, but it may not silently repair the model's substantive answer.

## 12. Primary evaluation

The primary unit of evaluation is one resolved market at the 7-day forecast checkpoint.

A market enters the primary analysis only if:

- it was eligible at the 7-day checkpoint;
- a valid matched market snapshot exists;
- the required forecasting conditions produced valid outputs;
- the market later received a valid YES or NO resolution.

Markets without a valid 7-day forecast remain visible in coverage statistics but do not enter the primary Brier comparison.

The primary proper scoring rule is Brier score.

For a forecast probability `p` and binary outcome `y`:

> `Brier = (p - y)^2`

where:

- `p` is the forecast probability that the market resolves YES;
- `y = 1` if the market resolves YES;
- `y = 0` if the market resolves NO.

Lower Brier score is better.

A perfect forecast has Brier score 0.

A forecast of 0.50 has Brier score 0.25 regardless of whether the final outcome is YES or NO.

## 13. Primary hypothesis

The primary research hypothesis is:

> At the 7-day checkpoint, the structured independent forecaster will achieve a lower mean Brier score than the direct LLM baseline.

For each resolved market `i`, define:

> `structured_advantage_i = Brier_direct_i - Brier_structured_independent_i`

A positive value means the structured independent forecaster performed better on that market.

The headline comparison is:

> `mean(structured_advantage_i)`

A positive mean indicates that the structured forecasting procedure outperformed the direct LLM baseline.

This hypothesis is primary because it tests whether the forecasting architecture adds value beyond simply asking the same underlying LLM for a probability.

## 14. Market comparison

Beating the prediction market is a secondary and harder hypothesis.

For each forecasting condition and resolved market `i`, define:

> `market_advantage_i = Brier_market_i - Brier_model_i`

A positive value means the model produced a better probabilistic forecast than the contemporaneous market benchmark.

The market probability is calculated from the matched YES order-book snapshot as:

> `market_probability = (yes_bid + yes_ask) / 2`

The market benchmark and model forecast must refer to the same `snapshot_id`.

No model-to-market comparison may be scored if the snapshot identity does not match.

## 15. Secondary metrics

Forecast Ledger will also report log loss.

For probability `p` and outcome `y`:

> `LogLoss = -(y * ln(p) + (1 - y) * ln(1 - p))`

Lower log loss is better.

For numerical stability only, probabilities used in log-loss calculation are clipped to the interval:

> `[0.000001, 0.999999]`

The stored forecast probability itself is never modified.

Directional accuracy may also be reported as a descriptive metric.

A forecast is directionally correct when:

- `p > 0.50` and the market resolves YES; or
- `p < 0.50` and the market resolves NO.

A forecast of exactly `p = 0.50` is classified as having made no directional prediction.

Directional accuracy is never the headline evaluation metric because it discards information about confidence.

## 16. Calibration

Calibration asks whether stated confidence corresponds to empirical frequency.

For example, forecasts near 0.70 should resolve YES approximately 70 percent of the time.

Calibration analysis is descriptive until enough resolved forecasts exist.

Forecast Ledger will not make substantive calibration claims from fewer than 50 resolved markets for a forecasting condition.

Once sufficient observations exist, forecasts may be grouped into probability bins and compared with the empirical YES frequency in each bin.

Calibration results must report the number of observations contributing to every bin.

Empty or very small bins must remain visible rather than being merged opportunistically after outcomes are observed.

## 17. Additional forecast horizons

The 14-day, 3-day, and 1-day checkpoints are secondary analyses.

Each horizon is evaluated separately.

Forecasts from different checkpoints of the same market must not be treated as independent observations.

No headline result may be produced by pooling all checkpoint rows together as though each row represented a separate market.

A secondary overall trajectory may show how forecast quality changes as resolution approaches.

## 18. Coverage and failures

Every eligible checkpoint must end in one explicit status.

Permitted statuses include:

- `forecast_created`;
- `market_data_failure`;
- `evidence_retrieval_failure`;
- `model_failure`;
- `validation_failure`;
- `checkpoint_unavailable`;
- `resolution_invalid`;
- `resolution_pending`.

Failures, exclusions, abstentions, and unavailable checkpoints remain part of the experiment ledger.

They may not disappear from reported coverage statistics.

The system must report at minimum:

- number of markets considered;
- number eligible;
- number excluded;
- number of forecast attempts;
- number of successful forecasts;
- number of resolved markets;
- number entering the primary analysis.

## 19. Statistical uncertainty

The project will report observed effect sizes before making claims about statistical certainty.

For paired model comparisons, uncertainty should be calculated over markets rather than over individual forecast rows.

Once the primary analysis contains enough resolved markets to justify inference, Forecast Ledger may report a bootstrap confidence interval for the mean paired Brier difference by resampling markets.

Repeated checkpoints from one market must remain grouped together in any analysis involving multiple horizons.

A small prospective sample is reported as pilot evidence, not as proof of general forecasting superiority.

## 20. Interpretation rules

The experiment is considered informative even if the structured system fails to beat the direct LLM or the market.

Possible outcomes include:

- structured forecasting beats the direct LLM but not the market;
- market awareness improves the structured forecast;
- market awareness harms the structured forecast through anchoring;
- structure produces no measurable improvement;
- the market remains superior;
- results remain too uncertain to distinguish the forecasting conditions.

The reported conclusion must follow the observed prospective data.

The project does not claim that an LLM possesses a tradable edge unless a separate execution-aware trading experiment establishes that claim.

## 21. Resolution semantics

A forecast becomes scoreable only after the corresponding market has received a valid final resolution.

Every resolution record must contain:

- `market_id`;
- `outcome_yes`;
- `resolved_at`;
- `resolution_source`;
- `resolution_status`;
- `retrieved_at`.

For a valid binary market:

- `outcome_yes = true` means the market resolved YES;
- `outcome_yes = false` means the market resolved NO.

The outcome must never be inferred from price movement.

The outcome must come from the market's final resolution state or the authoritative resolution source specified by the market.

Permitted resolution statuses are:

- `pending`;
- `resolved_yes`;
- `resolved_no`;
- `invalid`;
- `cancelled`;
- `ambiguous`.

Only `resolved_yes` and `resolved_no` may enter scoring.

A cancelled, invalid, ambiguous, or unresolved market must never be silently mapped to NO.

If the recorded resolution conflicts with the market's stated resolution rules or cannot be interpreted unambiguously, the market is marked `ambiguous` and excluded from scoring.

The exclusion remains visible in coverage statistics.

## 22. Model failure and retry policy

Every model request has a maximum of three total attempts:

- one initial attempt;
- at most two retries.

A retry is permitted only for:

- network failure;
- API timeout;
- rate-limit failure;
- malformed structured output;
- schema-validation failure;
- citation of an evidence ID not contained in the frozen packet.

A retry must use:

- the same model snapshot;
- the same reasoning configuration;
- the same prompt version;
- the same market input;
- the same frozen evidence packet;
- the same market snapshot where applicable.

The system must not retry merely because a forecast probability appears surprising, extreme, implausible, or unfavorable.

Every attempt must be recorded.

If no valid output exists after three attempts, the forecasting condition receives status `model_failure`.

A failed condition is not silently rerun later to obtain a more convenient forecast.

The system may never manually edit a model probability after generation.

## 23. OpenAI model configuration

Forecast Ledger version 0.1 uses the OpenAI Responses API.

The core forecasting model is:

> `gpt-5.5-2026-04-23`

The forecasting reasoning configuration is:

> `reasoning.effort = medium`

The same forecasting model snapshot and reasoning configuration are used for:

- Condition B: direct LLM baseline;
- Condition C: structured independent forecaster;
- Condition D: structured market-aware forecaster.

This is necessary so that differences between conditions are attributable to the forecasting procedure rather than to different underlying model capabilities.

The evidence-retrieval model is:

> `gpt-5.4-mini-2026-03-17`

The retrieval model may use web search.

Forecasting conditions B, C, and D may not use web search or any other retrieval tool.

They operate only on:

- the market question;
- the resolution rules;
- the frozen evidence packet;
- and, for Condition D only, the matched market probability.

Every model request must store:

- model ID;
- reasoning configuration;
- prompt version;
- response ID;
- attempt number;
- request timestamp;
- completion timestamp.

Model aliases such as `gpt-5.5`, `gpt-5.6`, or `chat-latest` are not permitted for scored version 0.1 forecasts because their underlying implementation may change during the experiment.

A future model change requires a new experimental model version and must not overwrite or relabel earlier forecasts.

## 24. Protocol change policy

This protocol governs all scored version 0.1 forecasts.

After the protocol is frozen, changes to any of the following require a new protocol version:

- market eligibility;
- market exclusions;
- forecast checkpoints;
- evidence validity;
- forecasting conditions;
- model snapshot;
- reasoning configuration;
- retry policy;
- resolution semantics;
- primary metric;
- primary hypothesis;
- primary analysis horizon.

Implementation changes that do not alter experimental semantics may be made without creating a new protocol version.

Examples include:

- bug fixes that make code conform to the existing protocol;
- logging improvements;
- database performance improvements;
- dashboard changes;
- additional deterministic tests.

If a semantic bug is discovered after scored forecasts exist, affected forecasts must be identified explicitly.

They may not be silently recomputed under the old protocol version.

## 25. Protocol freeze

Version 0.1 becomes active only when this document is changed from `DRAFT` to `FROZEN` and committed to Git before the first scored forecast.

The Git commit hash of the frozen protocol becomes part of the experiment metadata.

No scored forecast may predate that commit.
