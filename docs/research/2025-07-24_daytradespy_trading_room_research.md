# McLeod Alpha Research Report: 2025-07-24 Trading Room — Post 41038

## Executive Assessment

July 24 traded around fresh highs with PMI and new-home-sales releases. A real
August 1 634-call scalp entered at `5.48` and exited at `5.72`, above its
`5.70` target. The formal upside OMG then entered August 1 635 calls at `5.37`
with a `5.69` target. Fifteen challenge calls on the same contract entered at
`5.32` with a `5.55` target. Neither position had an evidenced exit by the
terminal cue.

A later discretionary 635-call position filled, but its entry premium was not
stated; its `5.49` target also remained unresolved. The source explicitly
planned to hold the challenge calls overnight if their target did not fill,
while the OMG would be held until target or sold at end of day. This created
overlapping same-contract exposure with different, incompletely evidenced exit
rules.

## Source Lineage and Evidence Quality

- Day Trade SPY post `41038`, published July 24, 2025.
- Authenticated Vimeo asset `1104236491`, duration `01:14:20`.
- Complete authorized English auto-generated VTT: 1,522 cues span
  `00:00:00-01:14:08`.
- Player volume was verified at `0%`; the Play control remained present and
  playback was never started.
- Evidence tier C: `TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE`.

## Market Context

- Futures were mixed near all-time highs after an extended rally.
- Scheduled catalysts included 9:45 PMI and 10:00 new-home-sales data.
- Initial OMG boundaries were approximately `633.80` downside and `635.02`
  upside; the upside line followed repeated overnight resistance.

## Timestamped Evidence Timeline

| Time | Source evidence | Research interpretation |
| --- | --- | --- |
| 00:09:30-00:09:51 | A presenter said an unnamed pick was entered and exited, but supplied no instrument or premiums. | The event is incomplete and cannot support contract-level expectancy. |
| 00:21:49-00:23:40 | August 1 634 calls entered `5.48`, targeted `5.70`, and exited `5.72` during PMI. | A completed real scalp entered immediately before scheduled data. |
| 00:27:31-00:28:34 | The upside OMG triggered; August 1 635 calls filled `5.37` at 9:50 with target `5.69`. | Formal trade remained unresolved at the terminal cue. |
| 00:29:39-00:30:55 | Fifteen challenge 635 calls entered `5.32` at 9:52, target `5.55`. | Same-contract challenge and OMG exposure overlapped. |
| 00:44:17-00:46:48 | Another 635-call order filled; the entry premium was unstated and target was `5.49`. | Missing entry prevents P&L calculation; later discussion called for repair. |
| 00:51:37-00:53:48 | The room discussed holding the challenge position overnight and potentially adding calls to repair. | A day scalp was converted into multi-session risk after adverse movement. |
| 01:11:43-01:12:42 | OMG would remain until target or EOD sale; challenge calls would be held overnight if unfilled, and the presenter might accept less than 6%. | Terminal outcomes and exact exit policy remained unavailable. |

## Presenter-Reported Trades

| ID | Setup | Entry | Exit / status |
| --- | --- | --- | --- |
| DTS-20250724-P41038-T01 | Unnamed published/personal pick | instrument and premiums unavailable | source said entered and exited within about 21 seconds |
| DTS-20250724-P41038-T02 | August 1 634 calls; real PMI scalp | `5.48` | `5.72`; target `5.70` |
| DTS-20250724-P41038-T03 | August 1 635 calls; formal upside OMG | `5.37` | unresolved; target `5.69`, EOD exit rule discussed |
| DTS-20250724-P41038-T04 | August 1 635 calls; challenge, 15 contracts | `5.32` | unresolved; target `5.55`, overnight hold planned |
| DTS-20250724-P41038-T05 | August 1 635 calls; later discretionary scalp | unavailable | unresolved; target `5.49` |

## Entry and Exit Lessons

1. Apply the scheduled-news rule consistently; a profitable pre-PMI entry does
   not validate unmanaged release risk.
2. Aggregate OMG, challenge, and discretionary positions sharing the same
   contract.
3. Do not convert a day-trade target into an overnight hold without a new
   maximum-loss and event-risk decision.
4. Exclude trades missing entry premium from return and expectancy statistics.
5. Record the actual EOD fill when a formal policy depends on liquidation at
   the close.

## Contradictions and Process Risks

- A real call scalp was entered seconds before PMI despite repeated event-risk
  discussion.
- OMG, challenge, and later discretionary trades reused August 1 635 calls.
- The later discretionary call had no narrated entry premium.
- An initial challenge scalp became an overnight position after failing to
  reach target.
- The presenter discussed repairing calls while the original positions and
  aggregate premium at risk were unreconciled.
- The formal OMG's terminal EOD disposition was absent.

## Falsifiable Replay Hypotheses

1. Exclude new entries inside a predeclared scheduled-data blackout.
2. Deduplicate all August 1 635-call variants into one exposure family.
3. Require a separately approved overnight-risk ticket for horizon changes.
4. Reject trades with missing entry premiums from expectancy.
5. Require broker-verified EOD liquidation for formal unfilled targets.

## Ledger and Instrumentation Gaps

No full visual review, broker/simulator orders, unnamed-pick contract or fills,
later-call entry, terminal OMG/challenge/call exits, quantities except the
challenge, aggregate premium/Greeks, synchronized bars, executable option
paths, MFE/MAE, spreads, slippage, or complete fees is available.

## Explicit Non-Changes

No live entry, exit, stop, sizing, direction, expiration, event-window,
overnight, repair, or aggregate-risk change is authorized.

## Final Governance Decision

`RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE`.
