# McLeod Alpha Research Report: 2025-07-08 Trading Room — Post 40855

## Executive Assessment

July 8 produced a clean source-reported downside OMG result and a much weaker
challenge-management example. Ten July 11 620 puts entered at `2.88`, initially
targeted `3.05`, and sold `3.13` for a reported `8.7%`. At the same time, 25
July 11 622 challenge calls entered at `2.96`. Their target moved from `3.10` to
`3.15`, missed by one cent, returned to `3.10`, and was later reduced in
discussion toward breakeven. The calls remained unresolved at the terminal cue.

The session also revisited July 7 losses. The prior OMG and pick were reported
closed as end-of-day losses, yet holders of other July 11 624 calls were told
not to realize a possible `80%+` loss because time remained and repair was
available. This is not a stop rule; it is a recovery thesis that can expand
exposure while avoiding loss recognition.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40855`, published July 8, 2025.
- Authenticated Vimeo asset `1099727269`, title `TR July 8`, duration
  `01:07:32`.
- Complete authorized English auto-generated VTT: 1,361 cues span
  `00:00:01-01:07:11`.
- Player volume was verified at `0%`; playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Tariff letters, the August 1 extension, and expectations for negotiated
  de-escalation drove sentiment; no high-impact scheduled release was expected.
- SPY opened within a wide range, broke below the approximate `620.72` lower
  OMG boundary, then oscillated between downside continuation and recovery.
- The call challenge and put OMG intentionally held opposite directional
  exposure during part of the session.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:13:38-00:15:24 | A downside close activated 10 July 11 620 puts at `2.88`, target `3.05`. | Formal OMG direction was corrected after one "calls" misspeak. |
| 00:17:27-00:18:23 | July 7 OMG and pick were reported as end-of-day losses; presenter said a personal position might instead have been held. | Reporting rule and discretionary thesis diverged. |
| 00:19:45-00:21:10 | Twenty-five July 11 622 challenge calls entered `2.96`, initial target `3.10`. | Opposite-direction challenge exposure coexisted with the put OMG. |
| 00:24:20-00:31:54 | Challenge target moved to `3.15`; source high reached `3.14`. | A reachable initial objective was displaced, then missed by one cent. |
| 00:40:40-00:45:48 | Published July 11 622-call pick was reconstructed near `2.89` with `3.06` target, but alternative entries `2.95-2.98` were debated. | Retrospective entry method is not immutable enough for clean performance statistics. |
| 00:44:24-00:44:55 | OMG puts sold `3.13` at narrated 10:05, reported `8.7%`. | Favorable exit exceeded the original `3.05` target. |
| 00:47:51-00:52:09 | Challenge calls had fallen near `2.47`; target moved back to `3.10`. | Target drift converted a missed win into a large unrealized drawdown. |
| 01:01:01-01:02:44 | Challenge calls remained open; breakeven `2.96` and later reassessment were discussed. | No terminal exit or maximum loss was supplied. |
| 01:02:56-01:05:59 | Holders of July 7 624 calls were advised to wait, possibly repair, and not realize an `80%+` loss while four days remained. | Calendar time and loss aversion replaced contemporaneous invalidation. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250708-P40855-T01 | 10 July 11 620 puts; formal downside OMG | `2.88` | `3.13`; `8.7%` reported |
| DTS-20250708-P40855-T02 | 25 July 11 622 calls; three-20 | `2.96` | open; target `3.10` → `3.15` → `3.10`, breakeven later considered |
| DTS-20250708-P40855-T03 | July 11 622 calls; published pick | source-modeled `2.89`; entry method disputed | source-modeled `3.06` target reached |
| DTS-20250708-P40855-T04 | July 7 formal OMG calls; cross-day resolution | prior source `4.08` | end-of-day loss; exit premium unavailable |
| DTS-20250708-P40855-T05 | July 7 published pick; cross-day resolution | unavailable | end-of-day loss; exit premium unavailable |
| DTS-20250708-P40855-T06 | July 11 624 calls carried from July 7 | possible prior real/repair correspondence; unproven | unresolved; hold/possible repair advised |

## Entry and Exit Lessons

1. Opposite-direction positions need an explicit hedge policy and net-exposure
   ledger; otherwise they are simply competing trades.
2. The initial target cannot be moved solely because price appears likely to
   continue; target versioning materially changed the challenge outcome.
3. Published-pick entry rules must be immutable and contemporaneous, not
   reconstructed from candle high/low after the move.
4. "Only lose when you sell" is not risk control; unrealized losses and repair
   exposure belong in the same ledger as realized losses.
5. Favorable OMG slippage remains a presenter claim pending executable quote
   and order evidence.

## Contradictions and Process Risks

- The presenter first said 620 calls, then corrected the downside OMG to puts.
- Put OMG and call challenge positions overlapped without net-risk accounting.
- The challenge target moved `3.10` → `3.15` → `3.10`, then toward breakeven.
- The published-pick entry was alternately modeled near `2.89`, observed at
  `2.95`, and argued as `2.98`; the claimed win depends on entry selection.
- July 7 reporting closed the OMG and pick as losses while discretionary
  holders were advised to wait or repair.
- A possible `80%+` call loss was framed as unrealized and therefore avoidable,
  with no price-based maximum loss.

## Falsifiable Replay Hypotheses

1. Compare immutable initial targets with discretionary target extensions.
2. Require net-delta and aggregate-risk limits for overlapping call/put trades.
3. Recompute pick performance using a contemporaneous, executable entry rule.
4. Compare time/repair management with a fixed price invalidation.
5. Track realized and unrealized PnL in one cross-day position ledger.

## Ledger and Instrumentation Gaps

No full visual review, broker orders, exact cross-day position mapping,
aggregate/net exposure, immutable published-pick entry, later challenge exit,
synchronized bars, executable option paths, MFE/MAE, spreads, slippage, or
complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, hedge, repair, or
risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
