# McLeod Alpha Research Report: 2025-06-05 Trading Room

## Executive Assessment

The cleanest June 5 trade was the downside OMG. After a confirmed lower
five-minute close and one-minute continuation, June 6 596 puts entered at
`2.90` and sold at `3.10` within roughly two minutes. A next-week version
reportedly moved from `5.10` to `5.66`. Confirmation mattered, but the source
later admitted the room entered at a disadvantage and had selected the wrong
expiration for the primary example.

Downside continuation remained profitable in source reporting: June 13 puts
near the 595/596 strike moved from `5.45` to `5.64`, and 20 June 6 595 puts
moved from `3.25` to `3.41`. The strike description on the former changed,
which prevents precise contract reconciliation. After support stabilized, the
better directional change waited for an inverted-head-and-shoulders reclaim.
Thirteen June 13 597 calls entered at `5.13` and exited at `5.46`; another
presenter traded June 13 595 calls from `6.18` to `6.47`.

The process risk is the repeated claim that an open call is not a loss until it
is sold. Several calls from prior sessions remained open, one presenter exited
a carry near flat after losing confidence, and another kept exposure “on the
back burner.” The best lesson is to distinguish a planned multi-session thesis
from an intraday trade that became a carry. Time to expiration is not a stop.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40511`; authenticated Vimeo asset `1090950935`,
  `TR June 5`.
- Duration `01:12:53`; 515 timestamped cues span `00:00:00-01:12:27`.
- Complete authorized transcript; visual orders, broker evidence, synchronized
  bars, and executable option paths unavailable.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Jobless-claims and trade headlines drove an early downside break.
- Price repeatedly tested support, allowing bounded put targets but increasing
  reversal risk.
- A later inverted-head-and-shoulders recovery supported a direction change to
  calls.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:09:42-00:10:09 | A prior-day call entered near `3.45` sold near `3.46` after confidence was lost. | A carry consumed time while producing essentially no return. |
| 00:13:18-00:17:22 | Downside OMG confirmed; June 6 596 puts entered `2.90`, target `3.07`, sold `3.10`. | Confirmation plus structural room produced the best complete trade. |
| 00:17:32-00:18:13 | Next-week OMG puts reportedly moved from `5.10` to `5.66`. | Strong result, but exact broker evidence remains absent. |
| 00:21:31-00:30:31 | June 13 puts entered `5.45`, exited `5.64`; strike narration shifted between 596 and 595. | Contract ambiguity weakens reconciliation. |
| 00:24:47-00:33:51 | Twenty June 6 595 puts entered `3.25`, sold `3.41`. | Nearby support justified taking the bounded gain. |
| 00:39:50 | Queued 600 calls were explicitly never entered. | Correctly excludes a non-fill from the trade ledger. |
| 00:40:36-00:41:07 | Multiple prior-day/next-week calls remained open. | Aggregate carry exposure was not quantified. |
| 00:43:48-01:03:51 | Thirteen June 13 597 calls entered `5.13` after recovery and sold `5.46`. | The direction change waited for a reclaim and used a resistance exit. |
| 00:45:57-01:01:31 | June 13 595 calls entered `6.18` and sold `6.47`. | A bounded recovery target completed the trade. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250605-T01 | June 6 596 puts; downside OMG | `2.90` | `3.10` |
| DTS-20250605-T02 | June 13 596 puts; alternate OMG | `5.10` | `5.66` |
| DTS-20250605-T03 | June 13 595/596 puts; retest | `5.45` | `5.64`; strike ambiguous |
| DTS-20250605-T04 | 20 June 6 595 puts; model downside | `3.25` | `3.41` |
| DTS-20250605-T05 | 13 June 13 597 calls; model recovery | `5.13` | `5.46` |
| DTS-20250605-T06 | June 13 595 calls; recovery | `6.18` | `6.47` |

Prior-session carries are discussed but not double-counted as June 5 entries.
Queued 600 calls were not filled and are excluded.

## Entry and Exit Lessons

1. Downside confirmation prevented guessing at first support contact.
2. Expiration and strike must be fixed and read back before submission.
3. When support is repeatedly defended, take the bounded put gain.
4. Direction changes should wait for a reclaim, not merely a hoped-for bounce.
5. A carried intraday option needs an explicit maximum loss and time stop.

## Contradictions and Process Risks

- The source changed OMG timing/expiration interpretation after the result.
- One put's strike was narrated inconsistently.
- “You only lose when you sell” ignores mark-to-market and opportunity cost.
- Multiple legacy calls remained open without aggregate exposure reporting.
- A favorable result cannot repair a wrong expiration or incomplete contract ID.

## Falsifiable Replay Hypotheses

1. Compare first-boundary entries with close-plus-confirmation OMG entries.
2. Lock strike and expiration before order admission.
3. Exit puts at the first repeatedly defended support.
4. Test recovery calls only after a confirmed neckline/EMA reclaim.
5. Force-close intraday positions that lack a predeclared carry plan.

## Ledger and Instrumentation Gaps

No broker orders, definitive strike for one next-week put, executable option
paths, synchronized bars, MFE/MAE, complete fees, aggregate exposure, or final
resolution for legacy calls exists.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, or risk-policy change
is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
