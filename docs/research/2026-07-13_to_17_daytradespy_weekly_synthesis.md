# Day Trade SPY Weekly Synthesis: July 13-17, 2026

## Coverage

This completed weekly block covers five browser-reviewed trading-room recordings from Monday, July 13 through Friday, July 17, 2026. The source is external qualitative research and has not changed McLeod Alpha live trading behavior.

## Weekly Patterns

| Recurring pattern | Days | Evidence-backed research direction |
|---|---|---|
| Fast opening follow-through with predefined short-duration objectives | July 13, 14, 15, 16, 17 | Label and evaluate `OPENING_FOLLOW_THROUGH` separately from later continuation/reclaim attempts. |
| Pivot and multi-timeframe EMA confluence | July 13, 14, 15, 16, 17 | Measure support/resistance confluence and require defined invalidation or confirmation. |
| Choppy/range conditions around clustered levels | July 14, 15, 16, 17 | Build an observational `CONGESTION` regime from crossings, failed breakouts, range compression, and reference clustering. |
| Structural room limits target reliability | July 14, 15, 16, 17 | Test `room_to_target` and `distance_to_friction` against MFE and target achievement. |
| Fresh confirmation after a shock, rejection, or failed target attempt | July 13, 14, 15, 16, 17 | Require a new close/hold or accepted reclaim; do not infer renewed eligibility from prior direction alone. |
| Option last-trade highs can be non-executable | July 15 | Persist bid, ask, mark, high/low since entry, MFE/MAE, and timestamps before assessing exit quality. |

## Research Priorities

1. Instrument executable option telemetry on every trade-management cycle.
2. Add research-only labels for `OPENING_FOLLOW_THROUGH`, `CONGESTION`, `BREAKOUT_ACCEPTED`, `NEAR_TARGET_REJECTION`, `EVENT_SHOCK`, and `RECOVERY_ACCEPTED`.
3. Calculate structural room using pivots, VWAP, intraday extremes, and multi-timeframe EMA clusters.
4. Replay each label against baseline trade count, P&L, MFE/MAE, drawdown, and missed-opportunity cost.
5. Require out-of-sample improvement and the existing risk/certification process before any live deployment.

## Explicit Non-Changes

- No averaging, reloading, or discretionary re-entry rule is adopted from the source.
- No stop or trailing-stop policy change is supported by this weekly block.
- No directional bias is inferred from a set of source-side call examples.

## Conclusion

The week consistently favors confirmation, structural room, and fresh evidence after failed or disrupted moves. Its practical value is a finite, testable research queue, not a discretionary overlay on the live bot.