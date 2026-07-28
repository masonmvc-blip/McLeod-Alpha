# McLeod Alpha Research Report: 2025-08-15 Trading Room — Post 41303

## Executive Assessment

August 15 was an expiration Friday with strong retail-sales data, weak Michigan
sentiment, and repeated downside moves. The formal August 22 645-put OMG entered
`3.50` and exited at `3.76`. Two later put scalps also completed: August 15 643
puts from `3.48` to `3.72`, and August 22 645 puts from `4.09` to `4.32`.

The presenter explicitly said the upside call pick was never entered because
SPY went straight down. Inherited August 22 645 calls around the low `5.30s`
remained unresolved, and a late August 22 644-put scalp entered `3.95` with a
`4.04` target but had no reported exit.

## Source Lineage and Evidence Quality

- Post `41303`; Vimeo `1110343200` (`8-15 TR`), duration `01:33:23`.
- Complete authorized VTT: 1,637 cues, `00:00:01-01:33:19`.
- Player stayed paused at volume `0%`; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Retail sales were firm, Applied Materials guidance pressured technology, and
  double expiration increased intraday risk.
- OMG boundaries were approximately `646.47` upside and `645.67` downside.
- SPY sold immediately, extended lower after weak Michigan sentiment, and
  repeatedly failed moving-average tests.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:10:59-00:11:24 | Presenter disclosed inherited August 22 645 calls around the low `5.30s`. | Prior exposure was already underwater and unresolved. |
| 00:13:07-00:15:50 | Downside OMG close waited for one-minute failure; 645 puts entered `3.50`. | Confirmation logic was explicit. |
| 00:23:38-00:24:02 | OMG puts exited `3.76`. | Presenter-reported completed winner. |
| 00:24:49-00:31:27 | Presenter said the upside pick was never entered and explained why the call thesis failed. | Correct classification is `NO_TRADE`. |
| 00:32:00-00:38:20 | August 15 643 puts entered `3.48`, exited `3.72` as Michigan sentiment hit. | Event-adjacent scalp completed. |
| 00:56:45-01:04:11 | August 22 645 puts entered `4.09`, exited `4.32`. | Second completed downside scalp. |
| 01:17:14-01:23:19 | Inherited 645 calls remained open; partial reduction near `5.00` was contemplated, not executed. | Future management must not be scored as a fill. |
| 01:28:31-01:32:57 | August 22 644 puts entered `3.95`, target `4.04`; no exit reported. | Late scalp unresolved at terminal cue. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250815-P41303-T01 | August 22 645 calls; inherited position | low `5.30s` | unresolved |
| DTS-20250815-P41303-T02 | August 22 645 puts; formal downside OMG | `3.50` | `3.76` |
| DTS-20250815-P41303-T03 | Upside call pick | no fill | `NO_TRADE`; confirmation never occurred |
| DTS-20250815-P41303-T04 | August 15 643 puts; discretionary scalp | `3.48` | `3.72` |
| DTS-20250815-P41303-T05 | August 22 645 puts; discretionary | `4.09` | `4.32` |
| DTS-20250815-P41303-T06 | August 22 644 puts; late discretionary scalp | `3.95` | unresolved; target `4.04` |

## Entry and Exit Lessons

1. Preserve an unentered pick as no trade even if the thesis is discussed.
2. One-minute confirmation can prevent premature entry after a boundary close.
3. Scheduled sentiment data can abruptly complete or reverse a scalp.
4. Future partial-exit plans are not terminal evidence.
5. Late-session trades need explicit close or carry status.

## Contradictions and Process Risks

- An upside pick was discussed while the presenter expected puts later.
- Inherited calls coexisted with repeated same-day put positions.
- The 643-put scalp was held into a scheduled sentiment release.
- The presenter considered repair and weekend carry without terminal action.
- The recording continued well beyond the nominal room end and finished with a
  late put still open.

## Falsifiable Replay Hypotheses

1. Immutable no-trade logging prevents hindsight pick inflation.
2. One-minute failure confirmation improves downside OMG expectancy.
3. Exiting before scheduled sentiment reduces tail risk.
4. Strategy-level aggregate exposure limits improve governance.
5. Mandatory terminal status for overtime trades changes session scoring.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, exact inherited-call entry and
quantity, call terminal fill, late-put exit, event-time executable path,
aggregate exposure, synchronized bars, Greeks, MFE/MAE, spreads, slippage, or
complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, confirmation,
event-risk, repair, weekend-hold, overtime-trade, or aggregate-risk change is
authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
