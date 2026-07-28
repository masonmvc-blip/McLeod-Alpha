# McLeod Alpha Research Report: 2025-07-14 Trading Room — Post 40918

## Executive Assessment

July 14 produced several quick upside scalps but left every named longer-lived
position unresolved. Real July 18 623 calls were reported at `3.97` to `4.10`,
`3.91` to `4.00`, and `3.92` to `4.10`. A fourth real scalp used July 18 624
calls at `3.54` and was still open at the terminal cue.

The formal OMG and published pick both used July 18 623 calls at a reconstructed
`4.05` entry with a `4.29` target, while the 20-contract challenge used July 18
624 calls around `3.51-3.56` with a `3.70` target. Neither reached its target in
the recording. The source explicitly required end-of-day clearing for reporting
but simultaneously said a personal holder could continue because bank earnings
were expected to help. Reporting and discretionary risk therefore diverged.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40918`, published July 14, 2025.
- Authenticated Vimeo asset `1101267057`, title `TR July 14`, duration
  `01:11:56`.
- Complete authorized English auto-generated VTT: 1,439 cues span
  `00:00:00-01:11:30`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Weekend tariff threats, Powell-removal discussion, upcoming CPI/PPI, and bank
  earnings framed a volatile but upward-biased morning.
- SPY repeatedly retraced most of each move, then made higher lows and renewed
  attempts toward `623.70-623.90`.
- Approximate OMG boundaries were `623.08` upside and `621.49` downside.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:07:23-00:07:46 | Presenters discussed moving the downside boundary farther away to avoid another reportable loss that would not “indicate” their method. | Outcome sensitivity influenced boundary placement, creating selection bias. |
| 00:10:45-00:12:29 | Twenty July 18 624 challenge calls entered around `3.51`; a later restatement said `3.56`, target `3.70`. | Entry narration is internally inconsistent and must not be normalized silently. |
| 00:11:17-00:12:50 | Real July 18 623 calls entered `3.97` and sold `4.10`. | One-minute discretionary scalp reached `0.13`. |
| 00:14:53-00:15:35 | Second real 623-call scalp entered `3.91` and sold `4.00`. | Roughly half-minute scalp captured `0.09`. |
| 00:16:38-00:29:22 | Third real 623-call scalp entered `3.92` and later sold `4.10`. | Longer scalp endured repeated retracement before `0.18` reported exit. |
| 00:28:38-00:30:18 | Qualifying upside close activated July 18 623 OMG calls at `4.05`, target `4.29`. | Formal setup aligned with a fresh breakout but entered near the session high. |
| 00:30:37-01:08:36 | Fourth real trade entered July 18 624 calls at `3.54`, target `3.65`; position remained open and possible overnight hold was discussed. | A scalp changed into a carry without an initial maximum loss. |
| 01:06:19-01:07:37 | Published 623-call pick was retrospectively modeled `4.05` to `4.29`; it had not reached target. | Pick and OMG shared the same reconstructed entry/target and were unresolved. |
| 01:08:20-01:10:17 | Challenge, OMG, pick, and real 624 calls remained open; EOD reporting exit and discretionary holding were both discussed. | Ledger outcome and personal risk policy diverged at the terminal cue. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250714-P40918-T01 | 20 July 18 624 calls; challenge | `3.51` initially, later `3.56` | open; `3.70` target |
| DTS-20250714-P40918-T02 | July 18 623 calls; real scalp 1 | `3.97` | `4.10` |
| DTS-20250714-P40918-T03 | July 18 623 calls; real scalp 2 | `3.91` | `4.00` |
| DTS-20250714-P40918-T04 | July 18 623 calls; real scalp 3 | `3.92` | `4.10` |
| DTS-20250714-P40918-T05 | July 18 623 calls; formal upside OMG | `4.05` | open; `4.29` target, EOD exit planned |
| DTS-20250714-P40918-T06 | July 18 624 calls; real scalp/carry | `3.54` | open; `3.65` target, overnight hold considered |
| DTS-20250714-P40918-T07 | July 18 623 calls; published pick | modeled `4.05` | unresolved; modeled `4.29` target |

## Entry and Exit Lessons

1. Boundary placement must be fixed from market structure before the outcome;
   avoiding an unattractive reportable loss is not a valid threshold input.
2. Rapid scalps can produce favorable narration while still lacking quantity,
   spreads, slippage, and aggregate exposure.
3. A scalp may not silently become an overnight position; carry authorization
   needs a predeclared invalidation, size, and event-risk limit.
4. Shared OMG/pick entry reconstruction should count as one underlying signal,
   not independent evidence of two wins or losses.
5. Conflicting challenge entry premiums must remain explicit until an order
   ledger resolves which price and quantity actually filled.

## Contradictions and Process Risks

- Downside-boundary discussion explicitly referenced avoiding a reportable loss.
- Challenge entry was first `3.51`, then the contract was restated near `3.56`.
- The fourth real position began as a tight scalp but was later eligible for an
  overnight earnings hold.
- OMG and pick used the same modeled `4.05` entry and `4.29` target.
- EOD clearing was required for reporting while discretionary holders were
  encouraged to continue if the earnings thesis remained attractive.

## Falsifiable Replay Hypotheses

1. Freeze OMG boundaries before the open and measure selection-bias effects.
2. Reconcile narrated challenge entry prices against immutable order events.
3. Compare strict scalp time stops with discretionary conversion to overnight.
4. Deduplicate OMG and pick signals when entry, contract, and target coincide.
5. Track all same-direction scalps and carries under an aggregate exposure cap.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, definitive challenge entry,
quantities for discretionary scalps, EOD fills, later carry resolution,
aggregate exposure, synchronized bars, executable option paths, MFE/MAE,
spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, overnight-hold,
boundary-selection, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
