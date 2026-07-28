# McLeod Alpha Research Report: 2025-08-18 Trading Room — Post 41322

## Executive Assessment

August 18 produced one underlying call position used for both the formal OMG
and the 320 challenge. August 22 643 calls filled at `4.05`; the formal target
was `4.29` and the challenge target was briefly raised to `4.35`. The option
reportedly printed `4.29`, but the presenters repeatedly said a fill was not
guaranteed and later left both account mandates working at `4.29`. Both must
therefore remain unresolved at the terminal cue.

The published 643-call pick was separately modeled from `3.86` to `4.09`.
August 22 643 puts were twice queued but explicitly not entered. Calls inherited
from the prior week also remained open under a conditional exit plan.

## Source Lineage and Evidence Quality

- Post `41322`; Vimeo `1111069754` (`TR Aug 18`), duration `01:12:08`.
- Complete authorized VTT: 1,397 cues, `00:00:00-01:11:46`.
- Player remained paused at `00:00`; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- The room focused on Ukraine peace talks and the coming Jackson Hole speech.
- OMG boundaries were approximately `643.28` upside and `642.23` downside.
- SPY broke higher, reversed sharply, then spent much of the room fighting near
  the one-minute 50 EMA before revisiting the session high.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:08:19-00:14:19 | Challenge calls were queued, an early order was rejected, and August 22 643 calls finally filled `4.05`. | Rejected orders are not fills; `4.05` is the stated entry. |
| 00:14:29-00:16:26 | The same contract and entry were assigned to OMG and challenge accounts; initial common target `4.29`. | One market position represented two mandates. |
| 00:26:19-00:29:52 | Challenge target was raised to `4.35`; option reached only `4.26` before a full reversal. | The raised target was not achieved. |
| 00:39:08-00:41:49 | 643 puts were queued on a possible EMA failure, then explicitly confirmed unentered. | Correct classification is `NO_TRADE`. |
| 01:02:18-01:06:44 | Option reached a reported high of `4.29`; presenters said a fill was only probable and “close, but no cigar.” | A touch is not sufficient fill evidence. |
| 01:07:01-01:08:04 | Published 643-call pick was modeled at `3.86` to `4.09`. | Source-modeled outcome, not broker evidence. |
| 01:09:21-01:10:08 | Both call mandates were left working at `4.29` for a later update. | Terminal status is unresolved. |
| 01:10:11-01:10:28 | Prior-week calls were conditioned on SPY clearing roughly `644.60`; no exit followed. | Inherited exposure remained unresolved. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250818-P41322-T01 | August 22 643 calls; formal OMG | `4.05` | unresolved; target `4.29` only touched |
| DTS-20250818-P41322-T02 | August 22 643 calls; 320 challenge, 19 contracts | `4.05` | unresolved; target reduced from `4.35` to `4.29` |
| DTS-20250818-P41322-T03 | Published August 22 643-call pick; modeled | `3.86` | modeled `4.09` |
| DTS-20250818-P41322-T04 | August 22 643 puts; queued twice | no fill | `NO_TRADE` |
| DTS-20250818-P41322-T05 | Prior-week calls | prior source | unresolved; conditional exit discussed |

## Entry and Exit Lessons

1. Keep rejected orders, queued orders, and completed fills distinct.
2. A high equal to a limit does not prove that the order filled.
3. One contract used by two mandates requires strategy-tagged accounting.
4. Raising a target after entry changes the management decision and its result.
5. Every inherited position needs a final fill or explicit carry state.

## Contradictions and Process Risks

- The challenge target was raised after favorable movement, then reduced after
  the reversal.
- Presenters alternated between saying the target was reached and acknowledging
  that no fill was assured.
- The recording ended while both current calls and inherited calls were open.
- Repeated put interest never became a trade and must not be hindsight-scored.

## Falsifiable Replay Hypotheses

1. Bid-confirmed limits materially reduce false positive target counts.
2. Fixed post-entry targets outperform discretionary target raising.
3. Strategy-tagged order IDs prevent double counting shared contracts.
4. Rejected-order telemetry improves entry-slippage measurement.
5. Mandatory terminal status changes session-level expectancy estimates.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, bid/ask path, queue priority,
terminal call fills, inherited-call basis or quantity, aggregate exposure,
synchronized bars, Greeks, MFE/MAE, spreads, slippage, or fees is available.

## Explicit Non-Changes

No live entry, target, sizing, shared-contract, inherited-position, confirmation,
or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
