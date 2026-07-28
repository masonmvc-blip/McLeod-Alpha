# McLeod Alpha Research Report: 2025-08-26 Trading Room — Post 41398

## Executive Assessment

August 26 was a slow, choppy upside session around durable-goods data,
consumer confidence, and the Richmond Fed release. The 320 challenge bought 20
August 29 643 calls at `3.32` and eventually exited `3.55`, with the presenter
reporting `450` dollars after commission. A separate real-money 643-call
position entered `3.46` and also exited `3.55`.

The published 643-call pick was later reconstructed at an average `3.27` entry.
The presenter explicitly said it was closed early, but did not state an
executable exit premium. The formal upside OMG entered `3.39` with a `3.59`
target and was finally described as out after the option traded through the
objective; it is retained as a source-reported target fill. One additional
unannounced trade was acknowledged near the end without usable terms and is
unresolved.

## Source Lineage and Evidence Quality

- Post `41398`; Vimeo `1113342185` (`8-26 TR`), duration `01:14:47`.
- Complete authorized VTT: 1,553 cues, `00:00:00-01:14:26`.
- Player remained paused at `00:00`; no audio was played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Durable-goods data had already printed; consumer confidence and Richmond Fed
  data were scheduled for 10:00.
- OMG boundaries were approximately `642.51` upside and `640.96` downside.
- An inverted head-and-shoulders thesis competed with persistent resistance
  near `642.50-642.80`; the session repeatedly surged, retraced, and rebuilt.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:10:37-01:01:31 | Challenge bought 20 643 calls at `3.32`; after repeated resistance, `3.55` filled and `450` dollars net was reported. | Completed, but required about 50 minutes of exposure. |
| 00:11:51-01:01:20 | Real-money 643 calls entered `3.46` and later exited `3.55`. | Separate completed mandate. |
| 00:11:54-01:00:39 | Presenter said the pick was out; later reconstructed average entry `3.27` and a modeled `3.47` six-percent objective. | Closed, exit price unavailable; later target is modeled, not a fill. |
| 00:14:55-01:01:23 | Formal upside OMG entered `3.39`, target `3.59`; source then said the position was finally out after trading through the target. | Source-reported target fill. |
| 00:31:11-00:35:12 | Presenter initially thought a call had sold, corrected that it remained open, and discussed possible removal. | Order-state confusion is explicit. |
| 00:38:13-00:43:17 | Scheduled data caused only a muted reaction and the market remained range-bound. | News did not supply immediate follow-through. |
| 01:11:19-01:11:31 | Presenter acknowledged another unannounced trade without terms. | Unresolved and excluded from scored results. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250826-P41398-T01 | August 29 643 calls; 320 challenge, 20 contracts | `3.32` | `3.55`; reported `450` dollars net |
| DTS-20250826-P41398-T02 | August 29 643 calls; real-money discretionary | `3.46` | `3.55`; completed |
| DTS-20250826-P41398-T03 | Published August 29 643-call pick | modeled average `3.27` | closed early; executable exit unavailable |
| DTS-20250826-P41398-T04 | August 29 643 calls; formal upside OMG | `3.39` | source-reported `3.59` target fill |
| DTS-20250826-P41398-T05 | Unannounced additional trade | terms unavailable | unresolved |

Participant percentage claims are excluded from the presenter ledger.

## Entry and Exit Lessons

1. Same-contract mandates must be separated by account and strategy.
2. Persistent resistance can turn a scalp into prolonged exposure.
3. “I thought I sold” is a material order-state control failure.
4. A retrospective target calculation is not an executable exit.
5. Unannounced positions cannot be scored without instrument, entry, and exit.

## Contradictions and Process Risks

- The challenge sought a quick daily objective but remained open through many
  failed resistance tests.
- The presenter briefly misidentified an open call as sold.
- The pick's exit was asserted without a premium.
- The OMG fill is supported by target-trade and closure language, not an
  independent order record.
- A final unannounced position prevented complete exposure reconciliation.

## Falsifiable Replay Hypotheses

1. Strategy/account tags eliminate same-contract attribution conflicts.
2. A maximum time-in-trade rule improves scalp risk-adjusted outcomes.
3. Broker-confirmed order state prevents mistaken open-position assumptions.
4. Resistance-test counts predict delayed target completion.
5. Requiring announced terms reduces hindsight trade inflation.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, pick exit premium, terms for
the unannounced trade, independent target-fill or P&L reconciliation,
executable option paths, aggregate exposure, synchronized bars, Greeks,
MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, time-in-trade, target, order-state, sizing, direction, or
risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
