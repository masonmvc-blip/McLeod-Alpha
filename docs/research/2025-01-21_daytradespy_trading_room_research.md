# McLeod Alpha Research Report: January 21, 2025 Trading Room

## Scope and Evidence

This report is based on a complete authorized Vimeo transcript review from `00:00` through `01:08:09`. It preserves the presenter’s stated range, option selection, target, stop, and overnight-management logic. No underlying chart data, option-chain history, broker fills, or ledger mapping was independently reviewed.

## Range and Directional Logic

- The room set OMG resistance at `680` and a downside boundary around `612`. It defined the first five-minute close outside either line as the directional condition for a 6% target.
- A later discussion acknowledged an actual close of `683` against the `680` line. This is a useful edge case: the presenter treated the modest excess as enough to satisfy the stated close-beyond-range criterion, despite describing it as close to splitting hairs.
- The source separately mentioned nearby resistance around `601`/`601.60` and described waiting for a resistance break before considering calls. A retracement to support before continuation was also contemplated.

## Source-Reported Position and Targets

- The presenter stated that prior calls had been sold at breakeven and then discussed Friday January 24 `601` calls as the prospective trade.
- The stated sizing example allocated roughly `$5,000` across 13 contracts, with a reported `3.76` entry reference. A `$200` objective required a stated `3.93` sell target, and the transcript says a sell order for 13 `601` calls at `3.93` was placed.
- The room gave two different target references for the same general context: `3.93` for the fixed-dollar trade and `3.90` for the OMG trade. The distinction matters; the transcript does not demonstrate that either was filled.

## Risk and Holding Discussion

- The presenter stated a 40% stop-loss option while also saying they did not expect a stop would be needed. This is a source-reported loss threshold, not evidence of an independently tested risk policy.
- If neither target nor stop occurred, the described fallback was to hold overnight and revisit the position the next morning. The transcript therefore combines a same-day target construct with discretionary overnight exposure.

## Reusable Research Observations

1. Test `MARGINAL_RANGE_CLOSE` by measuring whether small close-through distances, such as the reported `683` versus `680`, have different follow-through than decisive breaks.
2. Maintain `FIXED_DOLLAR_TARGET` and `PERCENT_TARGET` as distinct labels. The reported `3.93` and `3.90` values arise from different target formulations.
3. Test `STOP_OR_OVERNIGHT_FALLBACK` with actual bid/ask data, expiry, adverse excursion, and gap exposure. A 40% stop and overnight hold are materially different risk outcomes.
4. Record the initial breakeven liquidation separately from any later `601` call setup; otherwise legacy position management contaminates setup results.

## Evidence Limitations

- Price, contract, target, stop, and order-placement details are source-reported only.
- The recording does not establish final fill status or the next-day disposition of any held position.

## Decision

No live range-break, target, stop, sizing, or overnight-hold rule is authorized. The source supports replay research into marginal range-close quality and the execution-adjusted trade-off between percentage targets, fixed-dollar targets, stops, and overnight exposure.