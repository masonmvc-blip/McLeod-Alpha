# McLeod Alpha Research Report: 2025-08-20 Trading Room — Post 41346

## Executive Assessment

August 20 became a persistent downside session with several overlapping put
mandates. August 29 638 puts entered `4.99` after a close below the lower OMG
line and filled a `5.23` target; a second `5.25` fill was mentioned immediately
afterward without enough account identity to determine whether it was a distinct
order. The room later called this “pretty much the OMG trade.”

Additional completed puts were August 29 635 puts `5.42` to `5.85`, August 22
636 puts `3.79` to `3.84`, August 29 635 puts `5.98` to `6.15`, and August 29
635 puts `5.82` to `6.11`. A second 320 challenge in August 22 635 puts entered
`4.02` with a `4.15` target but remained open at the terminal cue. Calls queued
near the end were never entered.

## Source Lineage and Evidence Quality

- Post `41346`; Vimeo `1111743060` (`8-20 TR`), duration `01:16:13`.
- Complete authorized VTT: 1,746 cues, `00:00:00-01:16:06`.
- Player remained paused at `00:00`; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Retail earnings, FOMC minutes, and Jackson Hole dominated the discussion.
- OMG boundaries were approximately `640.17` upside and `638.44` downside.
- SPY failed repeated rebound attempts and stair-stepped through support while
  the presenters repeatedly debated whether the move was too extended to short.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:19:31-00:23:05 | 638 puts were queued after an ABCD decline and a failed bounce; entry filled `4.99`. | Downside entry followed confirmation, but structural room was questioned. |
| 00:23:40-00:25:55 | Target `5.23` filled; another `5.25` fill was stated without clear account identity. | Preserve the fill ambiguity rather than double-count. |
| 00:27:29-00:27:50 | The completed 638-put position was described as effectively the OMG. | Strategy attribution is retrospective and imperfect. |
| 00:35:02-00:47:02 | 320 challenge bought 20 August 22 636 puts at `3.79`; trailing stop exited `3.84`, reported `90` dollars net. | Completed, but management surrendered a larger excursion. |
| 00:43:17-00:44:25 | August 29 635 puts entered `5.42`, exited `5.85`. | Separate next-week discretionary scalp. |
| 00:55:03-00:55:54 | August 29 635 puts entered `5.98`, exited `6.15`. | Fast completed discretionary scalp. |
| 00:56:01-01:14:41 | Second challenge bought 20 August 22 635 puts at `4.02`, target `4.15`; no exit was reported before departure. | Unresolved despite statements that it would be sold later. |
| 01:02:47-01:07:37 | August 29 635 calls were queued, then abandoned for 635 puts at `5.82`. | Calls are `NO_TRADE`; direction was explicitly flipped. |
| 01:07:37-01:08:53 | Flipped August 29 635 puts exited `6.11`. | Completed put scalp. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250820-P41346-T01 | August 29 638 puts; downside/OMG-like trade | `4.99` | `5.23`; separate `5.25` fill identity unclear |
| DTS-20250820-P41346-T02 | August 22 636 puts; first 320 challenge, 20 contracts | `3.79` | `3.84`; reported `90` dollars net |
| DTS-20250820-P41346-T03 | August 29 635 puts; discretionary | `5.42` | `5.85` |
| DTS-20250820-P41346-T04 | August 29 635 puts; discretionary | `5.98` | `6.15` |
| DTS-20250820-P41346-T05 | August 22 635 puts; second 320 challenge, 20 contracts | `4.02` | unresolved; target `4.15` |
| DTS-20250820-P41346-T06 | August 29 635 calls; queued | no fill | `NO_TRADE`; flipped to puts |
| DTS-20250820-P41346-T07 | August 29 635 puts; post-flip scalp | `5.82` | `6.11` |

## Entry and Exit Lessons

1. Strategy/account identity is mandatory when simultaneous fills are reported.
2. A trend can remain valid while already too extended for a fresh entry.
3. Trailing stops change realized outcomes and must be evaluated against
   executable path data.
4. Queued calls abandoned for puts are a no-trade, not a losing call.
5. “Will sell later” is not terminal execution evidence.

## Contradictions and Process Risks

- Presenters repeatedly warned against chasing, then entered several extended
  downside scalps.
- The initial 638-put fill was only retrospectively associated with OMG.
- The second challenge remained open despite travel and monitoring constraints.
- Same strikes and expirations were reused across distinct mandates.
- Presenters discouraged panic-selling inherited calls without reconciling them.

## Falsifiable Replay Hypotheses

1. Strategy-tagged fills eliminate ambiguous dual-account results.
2. Maximum extension-from-EMA gates improve late-trend entry quality.
3. Fixed targets outperform ten-cent trailing stops on short put scalps.
4. Monitoring-availability gates reduce unresolved terminal positions.
5. Explicit queue cancellation prevents hindsight trade inflation.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, identity for the `5.25` fill,
terminal second-challenge fill, inherited-call ledger, executable option paths,
aggregate exposure, synchronized bars, Greeks, MFE/MAE, spreads, slippage, or
complete fees is available.

## Explicit Non-Changes

No live direction, extension, target, trailing-stop, sizing, strategy-account,
monitoring, or inherited-position policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
