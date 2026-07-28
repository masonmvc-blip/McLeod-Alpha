# McLeod Alpha Research Report: January 10, 2025 Trading Room

## Scope and Evidence

This report is based on a complete authorized Vimeo transcript review from `00:00` through `01:10:07`. It records the source’s stated market map, trade framing, and holding decision. Raw transcript text, chart verification, broker execution, option quotes, and ledger reconciliation are unavailable.

## Market Context and Opening Map

- The room described a sharp initial reaction down to third pivot support, followed by a bounce that the presenter characterized as weak. The source also noted the market’s relationship to the 78% Fibonacci retracement of the January rally and the January 2 upside gap, but those references are not visually verified here.
- The presenter set the OMG boundaries at `586` above and `585` below, with the first five-minute close outside the range intended to establish direction for a stated 6% objective. The broader chart framework included one-, five-, and fifteen-minute views plus pivot support/resistance and moving averages.
- Early recovery was treated cautiously because `586` was also nearby resistance. The room did not treat a bounce alone as a complete reversal signal.

## Setup, Target, and Holding Discussion

- The transcript describes an opening framework in which a confirmed range break, rather than a first intrabar move, controlled directional interest. The presenter also repeated a preference for more time to expiry, which makes option-duration selection part of the stated setup context.
- Later source discussion referenced next-Friday `584` puts, a reported limit target around `5.93`, and a changing underlying target as conditions evolved. These are presenter-reported planning details, not confirmed fills or results.
- By the close, the presenter described staying with `584` calls into the following Monday while acknowledging that a loss was possible. The source tied the choice to continued upside structure and testing of the five-minute 10 EMA, but did not establish the eventual result.

## Risk, Mistakes, and Counterfactuals

- The transcript explicitly acknowledged loss as a normal possibility and described using a fixed investment amount as a way to absorb losses. That is a sizing philosophy stated by the presenter, not evidence of appropriate risk control or expected value.
- The session illustrates why a fixed percentage target is not a complete risk system: the source changed projected underlying objectives, discussed both calls and puts, and elected to retain exposure across the weekend.
- The relevant counterfactual is not to assume a named range-break or Fibonacci reference produces a complete trade. A replay must compare confirmed break, failed break, post-gap support test, and the cost of holding through the weekend.

## Reusable Research Observations

1. Test `MULTI_REFERENCE_OPENING_MAP`: pivot support, prior gap, Fibonacci location, and range boundary should be captured as separate structural fields rather than collapsed into one direction label.
2. Test `FIVE_MINUTE_RANGE_CLOSE` against first touch and first penetration, stratified by whether the next structural level leaves sufficient room.
3. Track `TARGET_REVISED` and `WEEKEND_HOLD` separately. The transcript shows that the stated 6% objective did not end the management problem when the underlying context changed.
4. Keep expiry, strike, liquidity, quote spread, and position size explicit before evaluating the source’s preference for longer-dated options or its fixed-investment loss-absorption approach.

## Evidence Limitations

- No source-reported fill, target, loss, or holding decision is independently reconciled to market data or a broker ledger.
- The recording ends before the stated weekend-held position is resolved.

## Decision

No live entry, exit, stop, sizing, directional, target, or weekend-hold rule is authorized. The source supports replay research into event-driven opening breaks, structural room, revised-target behavior, and overnight/weekend option exposure only after independent validation.