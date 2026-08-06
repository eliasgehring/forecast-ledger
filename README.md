# Forecast Ledger

> Can an LLM make probability claims that deserve their confidence?

Forecast Ledger is a live, prospective AI forecasting experiment.

The system records probabilistic forecasts before outcomes are known, preserves the evidence and prediction-market state available at forecast time, and evaluates each forecast after resolution.

## Research question

Does a structured LLM forecasting process produce better probabilistic forecasts than:

1. a direct LLM forecast;
2. the contemporaneous Polymarket probability?

## Why this project exists

A fluent explanation can conceal unjustified certainty.

Forecast Ledger makes AI confidence accountable by storing exactly what the model predicted, what evidence it received, when the forecast was created, and how reality later scored it.

## Planned forecasting conditions

The experiment will compare:

1. the live Polymarket probability;
2. a direct LLM forecast;
3. a structured independent forecast that cannot see the market price;
4. a structured market-aware forecast using the same evidence packet.

## Evaluation

The primary evaluation metric will be Brier score.

Additional diagnostics will include log loss, paired performance against the market, calibration, directional accuracy, exclusions, abstentions, and API failures.

## Core semantics

Every forecast probability means:

> P(the selected Polymarket market resolves YES)

Market probability, model probability, edge, execution price, and settlement are distinct concepts. Forecast Ledger evaluates predictions, not trades.

## Current status

Repository initialized.

The research protocol is still a draft. No scored forecasts have been created.

## Design principles

Forecasts will be immutable.

Evidence must be valid at the forecast cutoff.

All forecasting conditions for a market must use the same frozen evidence packet.

Bot and market forecasts must use the same market snapshot.

Failures and exclusions must remain visible.

A negative empirical result is still a valid result.
