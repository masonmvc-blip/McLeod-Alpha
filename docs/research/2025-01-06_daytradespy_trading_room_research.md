# McLeod Alpha Research Report: January 6, 2025 Trading Room

## Scope and Evidence

This report is based on a complete authorized Vimeo transcript review from `00:00` through `01:09:41`. It preserves the source’s stated technical framework, contract-selection discussion, and management decisions without retaining raw transcript text. Chart verification, independently reconciled executions, option bid/ask/mark history, underlying bars, and canonical ledger data are unavailable.

## Market Context and Structure

- The session opened after a roughly five-point pre-market rise. The presenter marked `597` as the upper OMG boundary and approximately `595.55` as the lower boundary drawn from the body of the relevant five-minute pre-market candle.
- The stated opening rule was to wait for the first five-minute close outside those boundaries before choosing direction. The framework also included the one-minute chart, five-minute chart, longer-horizon context, a 20 EMA, pivot point, and pivot-resistance lines.
- The room repeatedly distinguished a move into resistance from a durable break. A strong pre-market run into `597` was expected to be capable of retracing, and the later upside thesis required price to clear nearby resistance rather than merely reach it.

## Entries, Contract Selection, and Targets

- The presenter said that lower call-side volatility and warmer put-side volatility required caution on puts. For an upside scalp, the stated preference was the at-the-money January 10 `596` calls because volume was higher there than in adjacent strikes.
- The transcript records a source-reported fill at `4.25` for the `596` calls and a stated `4.25` target. The rationale was a one-minute push through the 20 EMA combined with return strength toward the marked resistance. The transcript does not independently establish the order, quote, size, or result.
- Later reversal discussion used the same structural logic in the opposite direction: resistance near `597` could create room for puts, but the room emphasized waiting for a red candle and pressure confirmation rather than anticipating a decline at the level.

## Trade Management and Counterfactuals

- A source-reported participant result in `598` calls was described as a `13.7%` gain, but it is not independently verified. The reviewable lesson is the source’s sequencing: wait for a resistance response before treating the reversal as actionable.
- For a position described at a `3.38` cost, the presenter discussed a `3.58` target and a wide `1.35` stop as a possible risk boundary, while also expressing a willingness to hold if the anticipated reversal still appeared viable. This is not a validated stop model; it illustrates tension between a defined loss limit and discretionary repair/hold behavior.
- By the close, the presenter described a profit position around `2.97` with a `3.10` target, then chose to retain it overnight with a stated 50% stop rather than sell at the session end. The rationale was remaining time to expiry and the expectation that the target might fill later. The ultimate outcome is not available in this recording.

## Reusable Research Observations

1. Test `OPENING_RANGE_CLOSE_THROUGH` with the pre-market range width, first five-minute close, resistance proximity, and subsequent retest. A range boundary alone was explicitly insufficient in the source discussion.
2. Test `EMA_STRENGTH_CONFIRMATION` as a sequence: one-minute interaction with the 20 EMA, five-minute agreement, and room to resistance. Do not evaluate an EMA condition as a standalone entry trigger.
3. Preserve `OPTION_LIQUIDITY_SELECTION` fields: strike, expiry, volume, delta, spread, and premium. The source selected the `596` calls for stated volume, not direction alone.
4. Separate `TARGET_HOLD_OVERNIGHT` from `STOP_DEFINED`. The transcript shows a target, a wide stop, and a discretionary overnight hold coexisting; replay must measure their distinct impact on option excursion and realized risk.

## Evidence Limitations

- All prices, contracts, targets, fills, percentage gains, stops, and positions are presenter-reported transcript content, not broker- or market-data-verified facts.
- Visual chart interpretation and end-of-day or next-day trade outcomes are unavailable.

## Decision

No live entry, exit, stop, sizing, direction, or other trading-policy change is authorized. This session supports research into opening-range confirmation, resistance-aware reversal admission, option-liquidity selection, and the difference between a stated stop and discretionary overnight management.