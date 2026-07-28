# McLeod Alpha Research Report: 2025-06-09 Trading Room

## Executive Assessment

June 9 is a useful failed-follow-through case. The opening five-minute close
confirmed below the downside OMG boundary, and June 13 598 puts were
source-adjudicated into the model at `3.82` after the simulator failed to reset.
The `4.05` target was never reported filled. Sellers repeatedly failed to
follow through, price reclaimed the pitchfork/resistance area, and the put
remained open when the recording ended. A 40% premium stop at `2.29` was only
introduced after the trade was already adverse.

The opposing call scalps worked. June 13 600 calls entered at `3.81` and sold
at `3.95` in about two minutes, although the presenter explicitly admitted
“jumping the gun.” A re-entry at `3.98` and the 17-contract model entry at
`4.00` both sold at `4.20`; the model reported `$330` after commission. A
second presenter's June 13 599 puts had a `4.22` target but no audible entry
premium or final exit, so they remain unresolved.

The best lesson is not that the confirmed downside close was useless. It is
that confirmation must include post-break acceptance and follow-through.
Repeated bids, failed seller continuation, and a reclaim were evidence against
the puts and for the recovery calls. A statistical setup label cannot replace
a predeclared invalidation.

## Source Lineage and Evidence Quality

- Day Trade SPY post `40543`; authenticated Vimeo asset `1091844607`, `TR June 9`.
- Duration `01:11:56`; 488 timestamped cues span `00:00:00-01:11:35`.
- Complete authorized transcript; visual orders, broker evidence, synchronized
  bars, and executable option paths unavailable.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- No high-impact release was scheduled; participants awaited US-China trade
  talks and later-week CPI/PPI.
- Volatility and volume were described as low.
- The opening downside break lacked sustained seller follow-through and became
  a grinding recovery through resistance.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:14:07-00:14:59 | June 13 598 puts were assigned a `3.82` entry and `4.05` target after a simulator problem. | A source-adjudicated entry is not a verified executable fill. |
| 00:18:11-00:20:19 | June 13 600 calls entered `3.81` early and sold `3.95`. | Profitable result; admission was explicitly premature. |
| 00:21:12-00:22:02 | Calls re-entered `3.98`; 17 model calls entered `4.00`. | Both relied on the failed downside continuation. |
| 00:23:26 | Another presenter disclosed fast trades that were never announced. | Correctly excludes unverifiable trades from the ledger. |
| 00:28:36-00:42:47 | June 13 599 puts were queued/picked up with a `4.22` target. | Entry premium and final resolution are unavailable. |
| 00:31:29-00:36:13 | Sellers repeatedly failed to follow through and bids defended the level. | This was real-time evidence against continued put exposure. |
| 00:59:29 | Both 600-call positions sold at `4.20`; model net was reported as `$330`. | The reclaim completed; fees are only partially stated. |
| 01:00:56-01:03:48 | The 598 puts remained open; a 40% stop and `599.38` structural decision level were discussed. | Risk rules were added after entry rather than fixed beforehand. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250609-T01 | June 13 598 puts; downside OMG | `3.82` source-adjudicated | Open at recording end; target `4.05`, later stop `2.29` |
| DTS-20250609-T02 | June 13 600 calls; early recovery scalp | `3.81` | `3.95` |
| DTS-20250609-T03 | June 13 600 calls; recovery re-entry | `3.98` | `4.20` |
| DTS-20250609-T04 | 17 June 13 600 calls; model recovery | `4.00` | `4.20`; `$330` net reported |
| DTS-20250609-T05 | June 13 599 puts; second presenter | premium unavailable | Open/unresolved; target `4.22` |

Unannounced fast trades and the pick-of-the-day example are excluded.

## Entry and Exit Lessons

1. A boundary close is admission evidence, not proof of acceptance.
2. Require seller follow-through after a downside break; repeated bid defense
   is an invalidation signal.
3. Define the structural and premium stop before entry.
4. Do not treat a profitable premature entry as proof that anticipation is
   superior to confirmation.
5. Report unresolved positions as unresolved rather than inferring an exit.

## Contradictions and Process Risks

- “Leave it and don't worry” conflicted with the later 40% stop discussion.
- The simulator failure required a hypothetical rather than verified fill.
- Opposing positions obscured net directional exposure.
- The second put lacked an audible entry premium and exit.
- Call targets were chosen during the trade rather than from a fixed plan.

## Falsifiable Replay Hypotheses

1. Compare downside OMG entries with and without two-bar seller follow-through.
2. Exit failed breaks when the broken boundary is reclaimed and holds.
3. Freeze premium and structural invalidation before order submission.
4. Compare recovery calls admitted before versus after the reclaim.

## Ledger and Instrumentation Gaps

No broker orders, verified account mode, synchronized bars, executable
bid/ask path, option MFE/MAE, full fees, net exposure, second-put premium, or
final resolution for either put exists.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, or risk-policy change
is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
