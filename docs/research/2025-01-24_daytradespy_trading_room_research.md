# McLeod Alpha Research Report: January 24, 2025 Trading Room

## Scope and Evidence

This report is based on a complete authorized Vimeo transcript review from `00:00` through `01:09:15`. It contains source-reported market levels, option transaction details, and educational EMA discussion. No independent chart, quote, broker-fill, or ledger verification was available.

## Structure and Indicator Context

- The presenter described support in the upper `608` area and set an OMG support reference near `609.80`, with `610` used as the nearby upper resistance reference.
- The rationale for using `610` was partly structural and partly strike-based: the source stated that option strike prices can serve as support or resistance when price is near them.
- Later educational discussion described the 10-period EMA as weighting more recent closes more heavily than older ones. That explanation is context for the presenter’s use of the indicator, not evidence that EMA signals produce an edge.

## Source-Reported `610` Call Trade

- The recording described a fill in `610` calls at a reported `4.36`, after initially mentioning `4.36` or better. The source then calculated 11 contracts and a required gain of about $0.20 per contract for a `$200` objective after the stated commission allowance.
- The presenter stated a `4.56` limit sell for 11 contracts, identifying that level as the `$200` target. The transcript does not establish whether the order subsequently filled, the bid/ask at placement, or the realized result.
- This trade uses a fixed-dollar target rather than the separate 6% OMG objective. The two formulations should not be collapsed into one performance statistic.

## Reusable Research Observations

1. Test `STRIKE_AS_STRUCTURE` using independently measured strike proximity, volume/open interest, and actual support/resistance response instead of relying on the source’s general assertion.
2. Test `EMA_CONTEXT_VS_TRIGGER`: distinguish indicator explanation or alignment from a defined entry event and validate both separately.
3. Track `FIXED_DOLLAR_LIMIT_ORDER` with entry, contracts, commissions, quote spread, limit placement, and fill probability. The reported `4.36` to `4.56` sequence is a replayable claim, not a verified outcome.
4. Keep `OMG_PERCENT_TARGET` separate from the `$200` target class so outcome comparisons remain like-for-like.

## Evidence Limitations

- All trade prices, contract counts, and target calculations are source-reported only.
- The recording does not resolve the reported `610` call order.

## Decision

No live strike-level, EMA, entry, target, allocation, or limit-order rule is authorized. The source supports only independent research on strike-proximity structure and execution-aware fixed-dollar option targets.