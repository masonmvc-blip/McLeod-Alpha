# McLeod Alpha Research Report: 2025-09-10 Trading Room — Post 41560

## Executive Assessment

September 10 opened after tame PPI data and an Oracle-driven premarket rally.
The downside OMG bought September 19 653 puts at approximately `4.95`, narrowly
missed its working target, then moved against the position. Near the end of the
room the presenter added equal exposure at `4.89`, stated an average near
`4.93`, and revised the target to roughly `5.22`. It remained open.

A separate September 19 654-call trade entered `4.86` with a `5.15` target and
also remained open. The published upside pick was reported successful, but its
terms were not stated. The recording therefore ended with opposing positions
and cannot support a closed winning-day classification.

## Source Lineage and Evidence Quality

- Post `41560`; Vimeo `1117545252` (`9-10 TR`), duration `01:21:48`.
- Complete authorized VTT: 1,324 cues, `00:00:01-01:21:05`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Tame PPI data and Oracle commentary drove a large premarket gap.
- OMG boundaries were approximately `654.20` upside and `653.41` downside.
- Early profit-taking produced the downside trigger, but buyers then drove a
  new regular-session high.
- The presenter selected September 19 contracts to buy time.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:14:13-00:15:37 | Downside OMG Sep. 19 653 puts filled near `4.95`, target `5.30`. | Position opened after five- and one-minute confirmation. |
| 00:23:56-00:25:00 | Published upside pick reported successful; members cited 6% and 32 cents. | Source-reported/model result; terms absent. |
| 00:28:28-00:29:35 | OMG puts reached roughly `5.21-5.22`, but presenter did not close and the quote retreated. | Missed near-target exit. |
| 00:49:27-00:50:41 | Sep. 19 654 calls entered `4.86`, target `5.15`. | Separate opposing call position opened. |
| 01:01:48-01:04:20 | Presenter acknowledged three trades with only the pick banked and relied on time for the two open positions. | Terminal-risk warning. |
| 01:13:29-01:16:31 | Added 653 puts at `4.89`, stated average near `4.93`, revised target near `5.22`. | Averaging down increased exposure. |
| 01:16:40-terminal | Presenter said both positions would remain open and expected an exit later that day or within days. | Two terminal unresolved positions. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250910-P41560-T01 | Published upside pick | terms unavailable | reported successful |
| DTS-20250910-P41560-T02 | Sep. 19 653 puts; downside OMG | approximately `4.95`, equal add `4.89`, stated average `4.93` | unresolved; revised target about `5.22` |
| DTS-20250910-P41560-T03 | Sep. 19 654 calls | `4.86` | unresolved; target `5.15` |

## Entry and Exit Lessons

1. A near-target quote is not a closed trade.
2. Buying time does not remove directional or overnight risk.
3. Opposing options create gross exposure unless quantities and Greeks prove a
   hedge.
4. Averaging down requires a predeclared exposure cap.
5. Cross-day positions require immutable entry and fill reconciliation.

## Contradictions and Process Risks

- The presenter preferred being flat during the room but left two positions
  open.
- The OMG was nearly profitable enough to close before being averaged down.
- A call was opened while the downside OMG remained active.
- The stated average is approximate and requires quantities/fills.

## Falsifiable Replay Hypotheses

1. A near-target capture rule improves risk-adjusted OMG outcomes.
2. Prohibiting opposing discretionary positions reduces gross-exposure risk.
3. A no-average-down rule improves downside tail control.
4. A maximum holding-time rule outperforms reliance on extra days to expiry.
5. Terminal-ledger enforcement prevents open trades from entering win counts.

## Ledger and Instrumentation Gaps

No full visual review, published-pick fills, broker/simulator orders, exact
position sizes, reconciled average, terminal exits, independent P&L,
executable option paths, aggregate Greeks, synchronized bars, MFE/MAE, spreads,
slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, averaging, holding-time, opposing-position, sizing, direction, or
risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
