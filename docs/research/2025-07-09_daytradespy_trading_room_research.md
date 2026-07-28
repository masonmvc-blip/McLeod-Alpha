# McLeod Alpha Research Report: 2025-07-09 Trading Room — Post 40875

## Executive Assessment

July 9 opened with a powerful upside expansion and produced two clean
source-reported scalps. Thirty-two July 11 624 challenge calls and the formal
OMG shared a `2.34` entry and sold at `2.55`; the challenge reported `$662`
after commission. A separate July 18 625-call scalp entered `4.72` and exited
by trailing stop at `4.88`.

The strongest evidence is also the day's main governance warning. The presenter
initially announced a `2.55` sale that had not occurred, corrected the ledger,
then later recorded the actual exit. Separately, July 18 624 calls entered near
`5.34-5.35` by two presenters and were carried after the morning rally fully
reversed. The source closed by proposing patience or later repair, without a
price invalidation or aggregate-risk ledger.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40875`, published July 9, 2025.
- Authenticated Vimeo asset `1100060503`, title `7-9 TR`, duration
  `01:09:40`.
- Complete authorized English auto-generated VTT: 1,467 cues span
  `00:00:00-01:09:27`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Tariff announcements, a two-week extension, and the afternoon Fed minutes
  framed the session.
- SPY surged through multiple Fibonacci and pitchfork levels, reached a new
  morning high, then surrendered the entire opening rally.
- Approximate OMG boundaries were `622.80` upside and `622.37` downside after
  several pre-open revisions.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:08:42-00:18:50 | July 18 624 calls carried from July 7 at average `3.96` sold `2.55`, a stated `1.41` loss. | Cross-day repair exposure was finally realized; exact quantity and fees remain unavailable. |
| 00:13:57-00:14:24 | A qualifying upside close activated July 11 624 calls at `2.34`; the same entry served the 32-contract challenge and formal OMG. | Two named ledgers shared one directional position and fill. |
| 00:15:47-00:18:23 | A `2.55` sale was announced, retracted as an order-state mistake, then later actually filled at `2.55`. | The correction is valuable, but proves the need for immutable order-state events. |
| 00:19:32-00:19:46 | Challenge result was calculated as `$672` gross and `$662` net. | Source-reported arithmetic is internally consistent for 32 contracts and a `0.21` gain. |
| 00:22:33-00:22:53 | A July 18 625-call position was reported sold at `5.29`; its entry was described only as later than another trade. | Outcome is under-specified and cannot enter clean performance statistics. |
| 00:24:39-00:28:56 | July 18 625 calls entered `4.72`; trailing stop exited `4.88`. | Explicit, bounded scalp captured `0.16`, but quantity was not stated. |
| 00:41:00-00:41:24 | Published July 18 623-call pick was retrospectively modeled `5.12` to `5.42`. | Claimed three-minute win lacks a contemporaneous immutable signal/fill. |
| 00:43:33-00:44:03 | Hugh entered July 18 624 calls at `5.35`; John reported `5.34`, later restated as `5.33`. | Parallel presenter positions had inconsistent reported entry details. |
| 01:05:00-01:09:03 | The morning rally failed; the 624 calls remained open and later repair was considered. | Calendar time replaced a price-based invalidation at the terminal cue. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250709-P40875-T01 | July 18 624 calls carried from July 7 | `3.96` average | `2.55`; `1.41` loss reported |
| DTS-20250709-P40875-T02 | 32 July 11 624 calls; three-20 challenge | `2.34` | `2.55`; `$662` net reported |
| DTS-20250709-P40875-T03 | July 11 624 calls; formal upside OMG | `2.34` | `2.55`; shared fill with challenge |
| DTS-20250709-P40875-T04 | July 18 625 calls; under-specified presenter position | unavailable | `5.29`; entry and quantity unavailable |
| DTS-20250709-P40875-T05 | July 18 625 calls; real scalp | `4.72` | `4.88` trailing-stop exit |
| DTS-20250709-P40875-T06 | July 18 623 calls; published pick | modeled `5.12` | modeled `5.42` target reached |
| DTS-20250709-P40875-T07 | Hugh July 18 624 calls | `5.35` | open; hold/possible repair |
| DTS-20250709-P40875-T08 | John July 18 624 calls | `5.33-5.34` reported inconsistently | open at terminal cue |

## Entry and Exit Lessons

1. A shared fill can serve multiple research ledgers only if quantity and PnL
   attribution are explicit; it is not two independent opportunities.
2. Order submission, acknowledgment, and fill must be separate immutable
   events; an audible notification was briefly mistaken for an execution.
3. A trailing stop fit the strongly trending 625-call scalp and bounded the
   exit without retrospective target selection.
4. A delayed entry after an extended move needs a maximum loss and time stop,
   not merely more expiration time and a future repair option.
5. Cross-day positions require identity continuity so prior repairs, current
   carries, and exits cannot be silently reassigned.

## Contradictions and Process Risks

- A `2.55` exit was first reported, then retracted, then later actually filled.
- The same `2.34` fill represented both the OMG and challenge ledgers without
  explicit allocation.
- The carried July 7 calls were described at `3.96` average and later sold at a
  large loss, but quantity and repair history were absent.
- John's July 18 624-call entry was alternately stated as `5.34` and `5.33`.
- The terminal 624-call positions had no maximum loss; patience and repair were
  substituted for invalidation after a complete rally reversal.

## Falsifiable Replay Hypotheses

1. Compare immutable broker fill events with narration-derived trade ledgers.
2. Separate shared-fill OMG/challenge accounting from independent-trade counts.
3. Test trailing stops against fixed targets on high-momentum opening scalps.
4. Compare late-move entries with a required price/time invalidation.
5. Reconcile every repair and carry through a persistent cross-day position ID.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, quantities for discretionary
positions, shared-fill allocation, exact July 7 repair lineage, later July 18
624-call exits, synchronized bars, executable option paths, MFE/MAE, spreads,
slippage, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, trailing-stop,
repair, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
