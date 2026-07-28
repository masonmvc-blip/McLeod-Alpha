# McLeod Alpha Research Report: 2025-09-12 Trading Room — Post 41587

## Executive Assessment

September 12 was a range-bound, high-noise Friday. The presenter completed one
short downside scalp in September 19 658 puts from `4.78` to `4.93`. A second
658-put scalp entered `4.82` with a `4.94` target but remained open at the end
of the recording.

The formal upside OMG achieved a five-minute close, but the one-minute chart
failed to confirm and sharply rejected the breakout. The presenter explicitly
killed the OMG without entering. This is a valuable negative example of the
two-stage confirmation rule. The published upside pick also remained open and
was discussed as a possible hold into the following week.

## Source Lineage and Evidence Quality

- Post `41587`; Vimeo `1118196722` (`9-12 TR`), duration `01:19:24`.
- Complete authorized VTT: 1,479 cues, `00:00:00-01:19:06`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- The session oscillated in a narrow range around the five-minute 50 EMA.
- The downside OMG boundary was near `657.12`; the upside boundary was near
  `658.07`.
- Michigan sentiment data added volatility without creating sustained trend.
- Friday profit-taking competed with the broader upward trend.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:16:03-00:17:50 | Sep. 19 658-put scalp entered `4.78`, sold `4.93`. | Completed 15-cent source-reported scalp. |
| 00:22:44-00:23:41 | Second Sep. 19 658 puts entered `4.82`, target `4.94`. | Discretionary scalp opened. |
| 00:25:33-00:29:05 | No formal OMG close while the second put chopped around. | Position remained open. |
| 00:48:52-00:49:23 | Five-minute upside OMG close occurred; presenter waited for one-minute confirmation. | Threshold one only. |
| 00:50:01-00:53:07 | One-minute price failed to confirm and rejected the breakout. | Entry correctly withheld. |
| 00:54:02-00:54:08 | Presenter explicitly killed the OMG trade. | Formal `NO_TRADE`. |
| 01:04:31-01:05:25 | Published upside pick was still open amid a sub-one-point range. | Unresolved pick. |
| 01:17:21-terminal | Presenter planned to let both the pick and put work beyond the room. | Two unresolved source positions. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250912-P41587-T01 | Sep. 19 658 puts; downside scalp | `4.78` | `4.93` |
| DTS-20250912-P41587-T02 | Sep. 19 658 puts; second scalp | `4.82` | unresolved; target `4.94` |
| DTS-20250912-P41587-T03 | Upside OMG Sep. 19 658-call idea | no fill | `NO_TRADE`; failed one-minute confirmation |
| DTS-20250912-P41587-T04 | Published upside pick | terms unavailable | unresolved; possible hold into next week |
| DTS-20250912-P41587-T05 | Late 657/658-call pattern idea | no fill | `NO_TRADE`; presenter stayed on the fence |

## Entry and Exit Lessons

1. A five-minute breakout is insufficient without the required one-minute
   confirmation.
2. Explicitly canceling a failed setup prevents a false-positive trade.
3. Repeating a profitable scalp can create a materially different outcome.
4. Narrow ranges amplify spread and whipsaw risk.
5. Open picks and personal trades must stay out of completed-win statistics.

## Contradictions and Process Risks

- The first put scalp completed quickly, but the repeated version remained
  open.
- The presenter correctly rejected the OMG yet continued holding a separate
  downside put.
- The upside pick and downside put created opposing exposure without sizes or
  Greeks.
- Optimism about later resolution did not supply terminal fills.

## Falsifiable Replay Hypotheses

1. Two-stage OMG confirmation filters failed breakouts.
2. A no-repeat rule after a completed scalp reduces range-day exposure.
3. Spread-adjusted filters improve narrow-range option entries.
4. Opposing-position caps reduce gross exposure.
5. Terminal-ledger enforcement removes unresolved trades from win rates.

## Ledger and Instrumentation Gaps

No full visual review, published-pick terms, terminal put or pick fills,
broker/simulator orders, independent P&L, exact sizes, aggregate opposing
exposure, executable option paths, synchronized bars, Greeks, MFE/MAE,
spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, confirmation, repeat-trade, spread, holding-time, sizing,
direction, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
