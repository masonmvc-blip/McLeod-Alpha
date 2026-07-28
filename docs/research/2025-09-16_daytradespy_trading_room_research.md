# McLeod Alpha Research Report: 2025-09-16 Trading Room — Post 41609

## Executive Assessment

September 16 was a downside session complicated by material simulator failure.
The formal September 19 661-put OMG was described as successful for room
participants, with entries around `4.40-4.45` and a target around `4.71`, but
the presenter explicitly said he could not enter. It is therefore a modeled
OMG, not a presenter fill.

The presenter separately entered September 19 660 puts at `4.30` and sold at
least some at `4.47`, reporting 17 cents banked. He then entered September 26
660 puts at `6.09` with a later `6.27` target and left them open and in the red
at the terminal cue. A late additional downside idea was canceled. The source
also discloses an earlier accidental 100-contract simulator sale, making order
state a first-order research constraint.

## Source Lineage and Evidence Quality

- Post `41609`; Vimeo `1119172065` (`9-16 TR`), duration `01:20:05`.
- Complete authorized VTT: 1,461 cues, `00:00:02-01:20:01`.
- Player was paused at `00:00`, explicitly set to `0%` volume, and never
  played.
- Tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Retail-sales and housing data preceded the next day's FOMC decision.
- The OMG range was approximately `661.25-661.88`.
- The early break was downward, but later support repeatedly interrupted
  continuation.

## Timestamped Evidence Timeline

| Time | Source evidence | Interpretation |
| --- | --- | --- |
| 00:14:56-00:15:03 | Published pick was reported taken out. | Completed modeled pick; terms unavailable. |
| 00:17:19-00:20:58 | Presenter attempted the downside OMG but simulator rejected it; participants entered. | No presenter fill. |
| 00:20:58-00:28:04 | Participant entries `4.40-4.45`; target about `4.71` was reported reached. | Modeled OMG success only. |
| 00:30:41-00:31:04 | Presenter described an accidental prior 100-contract sale and slow simulator. | Severe execution-instrumentation risk. |
| 00:32:22-00:34:41 | Sep. 19 660 puts entered `4.30`; target revised to `4.59`. | Personal scalp opened. |
| 00:47:16-00:48:07 | Presenter sold some at `4.47`, reporting 17 cents banked. | Partial/completed amount unspecified. |
| 00:49:56-00:54:50 | Sep. 26 660 puts entered `6.09`; target later set `6.27`. | Longer-dated downside position. |
| 01:13:33-01:13:44 | Additional downside order was deleted. | `NO_TRADE`. |
| 01:15:58-terminal | Sep. 26 puts remained open and in the red. | Unresolved terminal exposure. |

## Presenter-Reported Trades and Decisions

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250916-P41609-T01 | Published pick | terms unavailable | reported taken out; result not computable |
| DTS-20250916-P41609-T02 | Sep. 19 661 puts; formal downside OMG | no presenter fill | modeled target reached by participants |
| DTS-20250916-P41609-T03 | Sep. 19 660 puts; personal scalp | `4.30` | at least partial sale `4.47`; size unresolved |
| DTS-20250916-P41609-T04 | Sep. 26 660 puts | `6.09` | unresolved; target `6.27`, in red late |
| DTS-20250916-P41609-T05 | Late downside idea | no fill | `NO_TRADE`; order deleted |

## Entry and Exit Lessons

1. Room-participant fills cannot substitute for a presenter fill.
2. Partial-exit size must be known before a trade can be treated as fully
   closed.
3. A longer expiration does not eliminate terminal loss or thesis risk.
4. Simulator rejection and stale order state invalidate clean execution
   attribution.
5. Explicit cancellation of the late entry prevented stacking further
   downside exposure.

## Contradictions and Process Risks

- The formal OMG was discussed as a success even though the presenter did not
  obtain a source-supported fill.
- The `4.30` trade banked some gain, but the amount sold and residual position
  are unspecified.
- The `6.09` position remained open while the presenter used extra time as a
  reason to tolerate adverse movement.
- An accidental 100-contract sale demonstrates that simulator state cannot be
  treated as a reliable broker ledger.

## Falsifiable Replay Hypotheses

1. Fill-qualified OMG statistics are lower than room-level target-hit
   statistics.
2. A simulator-health gate prevents trades during rejected or stale order
   state.
3. Mandatory size reporting resolves partial-exit outcome ambiguity.
4. Time-to-expiration is not a substitute for price-based invalidation.
5. A no-stack rule limits exposure when a longer-dated position is already
   open.

## Ledger and Instrumentation Gaps

No full visual review, published-pick terms, presenter OMG fill, partial-exit
size, terminal September 26 fill, reliable simulator ledger, broker orders,
independent P&L, sizes, executable option paths, synchronized bars, Greeks,
MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live OMG, simulator, partial-exit, expiration, invalidation, sizing,
direction, or risk-policy change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
