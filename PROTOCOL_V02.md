# Forecast Ledger Protocol v0.2

Protocol v0.2 inherits all research semantics, eligibility rules,
checkpoint definitions, evidence rules, scoring rules, retry rules,
and experimental conditions from frozen protocol v0.1 except for the
forecast model change described below.

## Status of v0.1

Protocol v0.1 is classified as pilot/protocol-development work.

Data collected under v0.1, including market snapshots, retrieval
attempts, evidence packets, validation failures, and audit records,
must be preserved.

No v0.1 observation may enter the primary scored v0.2 experiment.

## Forecast model

Conditions B, C, and D use exactly:

    gpt-5.4-mini-2026-03-17

Reasoning effort:

    medium

The same model and reasoning effort must be used for B, C, and D.

The model may not browse, use web search, or call external tools.

If this model becomes unavailable, protocol v0.2 stops. It must not be
silently replaced by another model.

## Retrieval model

Evidence retrieval remains:

    gpt-5.4-mini-2026-03-17

Retrieval may use web search.

Forecast conditions B, C, and D receive only the frozen validated
evidence packet.

## Reason for protocol change

The primary research objective is to estimate whether structured
forecasting improves over a direct LLM baseline.

Forecasting outcomes are noisy and repeated checkpoints within a
market are correlated. Unique resolved markets therefore provide more
statistical information than simply increasing the number of
checkpoints on a small sample.

GPT-5.4 mini was selected before the first scored B/C/D forecast because it provides a dated immutable model snapshot, modern reasoning capability, and sufficiently low inference cost to support a substantially larger prospective sample.

This changes the interpretation of the experiment:

    Can structured elicitation and market information improve the
    forecasting performance of a low-cost modern reasoning model?

It does not test whether structure improves the strongest available
frontier model.

## Primary conditions

A: market benchmark

B: direct GPT-5.4 mini forecast

C: structured independent GPT-5.4 mini forecast

D: structured market-aware GPT-5.4 mini forecast

All other frozen v0.1 semantics remain unchanged.

## Scoring boundary

Only forecasts generated prospectively under protocol v0.2 after this
protocol is committed may enter aggregate v0.2 results.

No pilot observation may be retroactively relabeled as v0.2.
