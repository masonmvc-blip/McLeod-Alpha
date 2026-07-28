# McLeod Alpha Research Report: 2025-08-21 Trading Room — Post 41358

## Executive Assessment

August 21 was an event-sensitive reversal session. The presenter first bought
August 29 636 puts at `5.36`; a `5.68` objective was replaced during the PMI
release, and the position exited at `5.84`. A subsequent five-minute downside
OMG close was correctly rejected after one-minute confirmation failed and price
reversed sharply.

Two upside positions followed. August 29 636 calls entered `6.59` and filled a
`6.90` target. August 29 637 calls entered late at `6.35`; the presenter
immediately acknowledged impatience, accepted the pullback, and left the
position open with an initial `6.55` option target and a longer SPY objective
near `639.25`. No terminal fill was reported.

## Source Lineage and Evidence Quality

- Post `41358`; Vimeo `1112051082` (`8-21 TR`), duration `01:17:12`.
- Complete authorized VTT: 1,434 cues, `00:00:00-01:16:53`.
- Player remained paused at `00:00`; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- PMI and existing-home-sales releases preceded the next day's Powell speech.
- OMG boundaries were approximately `636.88` upside and `635.19` downside.
- SPY opened lower, reacted sharply to the data, rejected a downside
  continuation attempt, and then recovered.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:14:56-00:25:13 | August 29 636 puts entered `5.36`; initial `5.68` objective was superseded and the position exited `5.84` during the data move. | Completed presenter position; event management changed the planned exit. |
| 00:38:35-00:43:13 | Five-minute downside close occurred, but the one-minute chart did not confirm and instead reversed. | Formal downside OMG is `NO_TRADE`. |
| 00:46:06-00:56:51 | August 29 636 calls entered `6.59`; `6.90` target filled. | Completed reversal call. |
| 01:00:32-01:01:03 | Presenter explicitly reviewed the failed downside break as a head fake. | Lower-timeframe confirmation prevented a false entry. |
| 01:04:31-01:05:07 | Weak upside volume, followed by visible selling volume, delayed another call. | Volume was used as a confirmation filter. |
| 01:08:28-01:16:53 | August 29 637 calls entered `6.35`; presenter admitted jumping the gun and left them open. | Unresolved position, not a completed trade. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250821-P41358-T01 | August 29 636 puts; opening/pick trade | `5.36` | `5.84`; completed |
| DTS-20250821-P41358-T02 | Formal downside OMG | no fill | `NO_TRADE`; one-minute confirmation failed |
| DTS-20250821-P41358-T03 | August 29 636 calls; reversal | `6.59` | `6.90`; completed |
| DTS-20250821-P41358-T04 | August 29 637 calls; late discretionary entry | `6.35` | unresolved; initial target `6.55`, longer SPY target about `639.25` |

Participant fills and percentage claims are excluded from the presenter ledger.

## Entry and Exit Lessons

1. Scheduled data can invalidate a passive target and requires explicit
   event-time management.
2. A five-minute boundary close alone was insufficient; the one-minute failure
   correctly cancelled the downside OMG.
3. Volume confirmation helped avoid an earlier low-conviction call.
4. A late entry taken to “get another trade” is a process violation even when
   the directional thesis may remain plausible.
5. A position left for later or possible overnight management is unresolved
   until a fill is reported.

## Contradictions and Process Risks

- The first put target was changed during a fast event move.
- The later call was entered despite the presenter repeatedly emphasizing
  patience and confirmation.
- The final position was allowed to outlive the recorded monitoring window.
- Participant outcomes cannot validate presenter execution or strategy P&L.

## Falsifiable Replay Hypotheses

1. One-minute confirmation after a five-minute OMG close reduces false breaks.
2. Event-time target replacement improves fills only when governed in advance.
3. A minimum upside-volume threshold improves late call selection.
4. Blocking entries motivated by trade-count pressure reduces unresolved risk.
5. Terminal-status enforcement changes measured daily expectancy.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, executable option paths,
independent event-time fills, final 637-call disposition, aggregate exposure,
synchronized bars, Greeks, MFE/MAE, spreads, slippage, or complete fees is
available.

## Explicit Non-Changes

No live OMG, event-management, volume, target, monitoring, sizing, direction,
or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
