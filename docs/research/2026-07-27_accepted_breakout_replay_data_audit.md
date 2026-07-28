# Accepted-Breakout Replay Data Audit

## Requested Comparison

Compare the current autonomous SPY entry logic with the same logic plus an accepted-breakout condition: a candle close beyond the trigger followed by a successful retest/hold. Contract selection, sizing, stops, exits, and costs must be identical. The comparison must use executable option bid/ask prices and chronological out-of-sample data.

## Result: Fails Evidence Gate

The requested comparison cannot produce a valid pass or fail on the retained historical data. This is a failure of the experiment's evidence prerequisites, not a rejection or approval of the confirmation filter.

## Verified Data Facts

1. The available SPY one-minute file, `data/historical/spy_1min_2026-06-20_to_2026-07-20.csv`, covers June 22 through July 20, 2026.
2. The retained historical option files under `data/historical/options/alpaca/trades/` have only trade-print fields: `timestamp`, `price` (and exchange/condition fields in some files). They contain no historical bid or ask.
3. The existing `backtesting/alpaca_full_backtest.py` downloads and replays option trades. Its `ManagementPricer` returns the same trade print as both option mark and option bid. This is explicitly incompatible with executable bid/ask evaluation.
4. The existing `backtesting/run_strict_retest_experiment.py` is not an implementation of the requested A/B test: it changes the score threshold from the current five to seven and changes the maximum trades per day to one. It also inherits trade-print pricing.
5. No retained historical commission/fee schedule or per-fill cost data exists for the cached option trades. An after-cost P&L cannot be calculated honestly from the local archive.

## Why No Metrics Are Reported

Reporting trade count, after-cost P&L, expectancy, drawdown, rejected winners, or avoided losers from this archive would require one of the prohibited substitutions:

- treating last trade as executable bid/ask;
- assuming a synthetic spread or commission schedule;
- changing the current entry thresholds or daily trade limit;
- treating unavailable option history as an unobserved winner or loser.

Each would make the baseline and treatment comparison non-equivalent or create unsupported execution outcomes.

## Required Replay Inputs

For every candidate contract and management timestamp, collect:

- NBBO or broker quote timestamp, bid, ask, mark, quote condition, and quote age;
- selected contract identity, expiry, strike, delta, volume, open interest, and selection rejection reason;
- actual buy fill, sell fill, commissions/fees, order IDs, and slippage;
- one- and five-minute SPY bars plus reconstructed breakout trigger, retest low/high, hold, and invalidation labels;
- all baseline-qualified signals, including signals rejected by confirmation, so rejected winners and avoided losers are measured from matched counterfactual trades;
- enough consecutive dates for a fixed development period and untouched chronological out-of-sample period.

## Frozen Experiment Design

When these data exist, run two replay variants with identical contract selector, quantity, entry/exit execution rules, stops, maximum daily trade limit, and cost treatment:

| Variant | Entry difference only |
|---|---|
| Baseline | Current closed-candle Brain-qualified entry. |
| Treatment | Baseline entry only after: (1) close beyond prior five-candle direction-specific trigger; (2) later retest that does not close back through the trigger; (3) subsequent close/hold in breakout direction. |

For calls, the trigger is the prior rolling high; for puts, it is the prior rolling low. Retest and hold must be measured only from already closed bars. A rejected baseline trade is matched to its baseline executable option path and classified as a rejected winner or avoided loser only after its original baseline exit is deterministically replayed using the same bid/ask and costs.

## Pass Criterion

The filter passes only if the untouched chronological out-of-sample period shows all of the following against baseline:

1. Positive improvement in after-cost expectancy and after-cost total P&L.
2. No increase in maximum drawdown.
3. No material deterioration in trade count or exposure without an offsetting risk-adjusted improvement.
4. Improvement is not confined to one date, one direction, or one event regime.
5. Every official trade uses executable entry ask, exit bid, and recorded costs; unavailable observations remain excluded and are reported separately.

## Current Conclusion

**Accepted-breakout confirmation: FAILS the current evidence gate.** No live change, threshold change, sizing change, stop change, or inferred performance result is authorized. The newly deployed live option-management telemetry begins collecting part of the needed forward evidence, but historical NBBO/fill-cost backfill is still required for a valid replay.