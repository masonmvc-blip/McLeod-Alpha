# McLeod Alpha Research Report: 2025-09-05 Trading Room — Post 41518

## Executive Assessment

September 5 opened after weak employment data and a sharp premarket rise, then
sold off as profit-taking returned. The presenter reported seven completed
personal/OMG trades with stated entries and exits, while a `360` challenge idea
was explicitly declined. The session is unusually important for governance:
after saying he was five-for-five and repeatedly announcing a final trade, the
presenter continued trading.

The formal downside OMG bought September 12 650 puts at `3.45` and was recapped
out at `3.72`. The room also used same-day puts despite describing them as
high-risk. No broker ledger, independent P&L, option path, or complete visual
review is available, so the reported wins remain source claims.

## Source Lineage and Evidence Quality

- Post `41518`; Vimeo `1116238582` (`TR Sept 5`), duration `01:10:54`.
- Complete authorized VTT: 1,498 cues, `00:00:00-01:10:33`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Weak employment data preceded a sharp premarket rise and opening reversal.
- The downside OMG boundary was approximately `651.02`.
- The room described the decline as another Friday profit-taking pattern.
- Both September 12 and same-day contracts were used.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:17:52-00:19:30 | Sep. 12 652 calls entered `3.96`, sold `4.10`. | Completed source-reported scalp. |
| 00:20:09-00:23:20 | Same-day 652 puts entered `1.25`, sold `1.40`. | Completed high-risk scalp. |
| 00:27:55-00:30:22 | Same-day 652 puts entered `1.20`, sold `1.35`. | Completed; presenter called it trade three. |
| 00:34:06-00:35:16 | Same-day 650 puts entered `0.89`, sold `1.00`. | Completed high-risk scalp. |
| 00:37:16-00:37:56 | Sep. 12 650 puts entered `3.32`, sold `3.40`; presenter then said five-for-five. | Completed source-reported scalp. |
| 00:38:12-00:46:17 | Downside OMG Sep. 12 650 puts entered `3.45`, target `3.66`, recapped out `3.72`. | Completed source-reported OMG. |
| 00:42:50-00:45:02 | Separate Sep. 12 650 puts entered `3.50`; terminal statement supports an exit around `3.80`. | Completed, but speaker/fill attribution is imperfect. |
| 00:46:23-00:46:36 | `360` challenge declined because of pressure and proximity to the goal. | Explicit `NO_TRADE`. |
| 00:52:58-00:54:04 | Sep. 12 649 puts entered `3.85`, sold `4.05`. | Completed after prior “done” statements. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250905-P41518-T01 | Sep. 12 652 calls | `3.96` | `4.10` |
| DTS-20250905-P41518-T02 | Same-day 652 puts | `1.25` | `1.40` |
| DTS-20250905-P41518-T03 | Same-day 652 puts | `1.20` | `1.35` |
| DTS-20250905-P41518-T04 | Same-day 650 puts | `0.89` | `1.00` |
| DTS-20250905-P41518-T05 | Sep. 12 650 puts | `3.32` | `3.40` |
| DTS-20250905-P41518-T06 | Sep. 12 650 puts; downside OMG | `3.45` | recap `3.72` |
| DTS-20250905-P41518-T07 | Sep. 12 650 puts; separate personal position | `3.50` | approximately `3.80`; attribution imperfect |
| DTS-20250905-P41518-T08 | `360` Sep. 12 652-call idea, 20 contracts | no fill | `NO_TRADE` |
| DTS-20250905-P41518-T09 | Sep. 12 649 puts | `3.85` | `4.05` |

## Entry and Exit Lessons

1. A no-trade decision can be the correct risk action even when a setup exists.
2. Same-day premium scalps require separate tail-risk and spread analysis.
3. Repeated “last trade” statements are not enforceable risk limits.
4. Overlapping OMG and personal positions obscure aggregate exposure.
5. Recapped favorable fills require broker reconciliation.

## Contradictions and Process Risks

- Trading continued after “five out of five,” “last trade,” and “done”
  statements.
- The room used same-day contracts while emphasizing their high risk.
- The `3.50` position's exact speaker and terminal fill are less certain than
  the other trades.
- A claimed aggregate gain cannot be reconciled to sizes, commissions, or a
  broker ledger.

## Falsifiable Replay Hypotheses

1. A hard daily trade-count cap reduces post-goal risk without materially
   reducing expected value.
2. The `360` pressure filter improves challenge drawdown.
3. Same-day contracts underperform one-week contracts after spread and tail
   loss adjustment.
4. Aggregate exposure limits improve results when OMG and personal trades
   overlap.
5. Broker-fill reconciliation removes favorable recap bias.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, independent P&L, exact sizes
for personal trades, executable option paths, aggregate exposure, synchronized
bars, Greeks, MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, challenge, same-day-option, trade-count, sizing, direction, or
risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
