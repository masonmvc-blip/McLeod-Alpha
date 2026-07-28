# McLeod Alpha Research Report: 2025-07-10 Trading Room — Post 40894

## Executive Assessment

July 10 was a range-bound, low-volatility session in which the two challenge
scalps were better bounded than the formal OMG. Seventeen July 18 624 calls
entered `4.70` and sold `4.81`, then another 17 entered `4.56` and sold `4.72`.
The source reported `$439` total net, exceeding the `$320` daily objective.

The downside OMG was less resolved. Hugh entered July 18 623 puts at `4.02`
with a `4.26` target while John chose July 18 624 puts at `4.42`. Both remained
open at the terminal cue with an end-of-day exit rule, but the recording never
supplied the resulting fills. The session therefore documents a profitable
challenge result and an unresolved named signal, not a fully reconciled day.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40894`, published July 10, 2025.
- Authenticated Vimeo asset `1100402584`, title `TR July 10`, duration
  `01:14:48`.
- Complete authorized English auto-generated VTT: 1,470 cues span
  `00:00:00-01:14:36`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Additional tariffs, Fed-minute interpretation, jobless claims, and a
  low-news calendar framed the session.
- SPY repeatedly rejected resistance near `624.00-624.50` and found support
  near `623.40`, producing whipsaw rather than trend.
- Approximate OMG boundaries were `624.50` upside and `623.40` downside.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:08:19-00:14:20 | July 9 July 18 624 calls at `5.35` were still open; presenter later said “I got out” without an exit premium. | Cross-day status improved only from open to source-reported exit; PnL remains unknowable. |
| 00:18:00-00:19:16 | Published July 18 623-put pick was modeled `3.53` to `3.74`; a `3.63` high entry required `3.85`, later reached. | Pick outcome changed with entry selection but both modeled paths eventually reached 6%. |
| 00:26:32-00:27:16 | Seventeen July 18 624 challenge calls entered `4.70`, initial target `4.90`. | Scalp entered after a close over clustered moving averages. |
| 00:39:03-00:40:20 | A one-cent downside close activated Hugh's July 18 623 puts at `4.02`, target `4.26`; John chose 624 puts at `4.42`. | Same signal produced different contracts and non-comparable target mechanics. |
| 00:57:12-00:57:40 | Challenge calls sold `4.81`, reporting `$177` net; John separately sold his call position at `4.78`. | Challenge took a reduced profit after prolonged range trade. |
| 00:58:23-00:58:46 | OMG puts had shown roughly `0.12-0.15` favorable excursion, but no partial exit was taken. | Fixed 6% objective displaced an available smaller gain in low volatility. |
| 01:08:46-01:12:52 | Second 17-contract challenge entered `4.56`, target `4.70`, and sold `4.72`; `$262` net reported. | Second bounded scalp brought daily challenge net to `$439`. |
| 01:13:27-01:13:46 | OMG puts remained open; end-of-day liquidation was planned if target failed. | Terminal recording does not prove the planned exit occurred or at what premium. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250710-P40894-T01 | July 9 July 18 624 calls; cross-day carry | `5.35` | exited by source statement; premium unavailable |
| DTS-20250710-P40894-T02 | July 18 623 puts; published pick | modeled `3.53` | modeled `3.74`; high-entry `3.63` path later reached `3.85` |
| DTS-20250710-P40894-T03 | 17 July 18 624 calls; challenge trade 1 | `4.70` | `4.81`; `$177` net |
| DTS-20250710-P40894-T04 | John July 18 624 calls; real scalp | entry unavailable | `4.78`; PnL unavailable |
| DTS-20250710-P40894-T05 | July 18 623 puts; formal downside OMG | `4.02` | open; `4.26` target, EOD exit planned |
| DTS-20250710-P40894-T06 | John July 18 624 puts; parallel real trade | `4.42` | open; exact target unresolved |
| DTS-20250710-P40894-T07 | 17 July 18 624 calls; challenge trade 2 | `4.56` | `4.72`; `$262` net |

## Entry and Exit Lessons

1. Low-volatility conditions justify testing smaller fixed targets, but the
   rule must be declared before entry rather than after favorable excursion.
2. A one-cent boundary close should be replayed against a minimum-break filter
   because it admitted the OMG directly into support and whipsaw.
3. Different option strikes on the same signal require separate expected-value
   accounting; their deltas, targets, and fills are not interchangeable.
4. Reduced challenge targets preserved realized gains in a range, whereas the
   OMG remained exposed under a rigid 6% objective.
5. A planned end-of-day exit is not evidence of an executed exit; the ledger
   remains open until a fill is captured.

## Contradictions and Process Risks

- The prior-day call exit was narrated without premium, time, quantity, or PnL.
- The published pick used a midpoint entry after the fact; the source separately
  discussed a high-entry path and different target time.
- Hugh and John implemented the same downside signal with different strikes.
- The OMG had an audible favorable excursion but no immutable management rule
  for partial profit in low volatility.
- End-of-day liquidation was stated but not evidenced before the terminal cue.

## Falsifiable Replay Hypotheses

1. Test a minimum boundary-break filter against one-cent OMG admissions.
2. Compare volatility-scaled targets with the fixed 6% OMG objective.
3. Evaluate 623-put and 624-put implementations separately by delta and spread.
4. Require immutable EOD-exit fills before classifying a signal outcome.
5. Recompute published picks from contemporaneous executable entry rules.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, prior-day exit premium,
contemporaneous pick signal, John-call entry, EOD OMG/put fills, synchronized
bars, executable option paths, MFE/MAE, spreads, slippage, or complete fees is
available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, volatility-target,
or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
