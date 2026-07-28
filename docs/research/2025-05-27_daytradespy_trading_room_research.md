# McLeod Alpha Research Report: 2025-05-27 Trading Room

## Executive Assessment

This session provides unusually strong evidence for separating setup quality
from execution quality. A downside OMG entered May 30 585 puts at `4.70` and
came within roughly four to five cents of the `4.98` target before SPY
reversed. The simulated order did not fill even though later discussion says
the live bid traded above the target. The presenter retained the losing OMG
while a strong recovery invalidated the immediate downside path.

The two completed recovery calls were better managed. May 30 586 calls entered
at `4.69` after price recovered from the opening drop and sold at `5.02` on a
consumer-confidence pop. May 30 587 calls then entered at `4.49` and sold at
`4.68` just below identified resistance. However, the first call was initially
announced as 70 contracts, then retroactively treated as 15 contracts with no
55-contract adjustment reported. That discrepancy makes the stated `$485`
net result unauditable.

The best lesson is operational: record the actual submitted quantity and
executable fill at order time. Good chart logic cannot compensate for an
unreconciled position size or a simulated fill model that differs from the live
market.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40391`; authenticated Vimeo asset `1088498826`,
  `5-27 TR.mp4`.
- Duration `01:10:13`; 460 recovered timestamped cues span
  `00:00:00-01:10:10`.
- Visual orders, broker evidence, synchronized SPY bars, and executable option
  paths remain unavailable.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- SPY opened with a downside reversal after a strong gap tied to improved
  US/EU tariff rhetoric.
- The first selloff reached a major retracement/support cluster, then reversed.
- Better-than-expected consumer confidence at 10:00 accelerated an already
  developing recovery into a persistent uptrend.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:11:44-00:14:14 | A downside OMG closed below `586.12`; May 30 585 puts filled at `4.70`, target `4.98`. | The entry had confirmation, but nearby support limited remaining room. |
| 00:15:42-00:17:12 | Premium reached about `4.93-4.94`, just short of target, before SPY bounced. | A fixed premium target converted a favorable move into an unresolved trade. |
| 00:18:29-00:21:51 | The source waited for a recovery, then bought May 30 586 calls at `4.69` after the move through the planned level. | Direction changed only after evidence of reversal. |
| 00:22:01-00:29:21 | The fill was announced as 70 contracts; the speaker later said it should be 15. No reduction or correction fill was reported. | The actual exposure and later P&L are not reconcilable. |
| 00:34:08-00:39:13 | The target was repeatedly raised; the 10:00 confidence release produced an exit at `5.02`, stated `$485` net on 15 contracts. | The directional result was favorable, but size and event dependence weaken the claim. |
| 00:39:20-00:40:23 | The losing OMG was retained while new support near `586` was explicitly identified. | The original downside path was no longer structurally clean. |
| 00:43:39-00:44:57 | A second recovery scalp entered May 30 587 calls at `4.49`, 15 contracts, after consolidation. | Admission followed trend recovery and a bounded objective. |
| 00:53:16-00:56:47 | The target was `4.65`; the calls sold at `4.68` just below `587.50` resistance, a 19-cent gain. | This is the strongest fully described trade in the recording. |
| 00:59:00-00:59:52 | The published pick reportedly hit in the live market while the simulated order lagged; the source proposed counting success when bid exceeded ask. | Simulator exceptions must be predefined, not adjudicated after the outcome. |
| 01:07:58-01:08:55 | SPY continued straight up; the OMG presenter planned a better simulated exit on a retracement but reported none. | The downside trade remained unresolved as its thesis weakened. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250527-T01 | May 30 585 puts; downside OMG | `4.70` | Unresolved in presenter simulation; target `4.98` reportedly executable live |
| DTS-20250527-T02 | May 30 586 calls; opening recovery | `4.69`; quantity reported as 70 then 15 | `5.02`; stated net `$485` based on 15 contracts |
| DTS-20250527-T03 | 15 May 30 587 calls; continuation scalp | `4.49` | `4.68` |

The published pick and participant results are excluded from
presenter-reported trades.

## Entry and Exit Lessons

1. When a target stops a few cents short at known support, require a partial,
   reduced target, or structural exit rule before entry.
2. Reversing direction after support recovery was stronger than continuing to
   defend the failed downside thesis.
3. The second call used the most reusable pattern: consolidation, continuation,
   and an exit just before known resistance.
4. Actual order quantity must be captured from the broker, not reconstructed
   from intended allocation.
5. Simulation fill rules must be deterministic and frozen before the session.

## Contradictions and Process Risks

- The first call was announced as 70 contracts but all later P&L used 15.
- The target on that call moved from `4.80` to `4.95`, then `5.00`, while a
  scheduled release was imminent.
- The source warned options should always have an exit order, yet the OMG had
  no reported stop or completed exit.
- The live market reportedly filled a target that the simulator missed, and
  success was adjudicated afterward.
- The strong upside recovery was traded successfully while the opposing OMG
  remained open.

## Falsifiable Replay Hypotheses

1. Compare fixed 6% OMG targets with exits one tick before the first support
   cluster.
2. Exit an OMG put after a confirmed recovery above the failed-break boundary.
3. Test continuation calls entered after consolidation against anticipatory
   calls entered during the first bounce.
4. Reconcile intended quantity, submitted quantity, and filled quantity before
   any P&L is accepted.
5. Apply one predefined bid-based fill rule identically to simulated and live
   replay results.

## Ledger and Instrumentation Gaps

No broker orders, actual filled quantity for the first call, executable
bid/ask history, fees, MFE/MAE, synchronized bars, aggregate exposure, or final
OMG exit exists. Reported net P&L is not independently verified.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, hedging, expiration, simulator,
or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
