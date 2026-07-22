# McLeod Alpha Research Note: July 20, 2026 Trading Room

## Scope and Evidence

Source recording: Day Trade SPY, "Trading Room Video Recording - July 20, 2026" (approximately 71 minutes). The Vimeo transcript was reviewed in the browser on July 22, 2026. This is external qualitative research, not a trade instruction or a justification for changing live execution.

## Session Assessment

The room treated a bullish opening as a fast follow-through opportunity, then spent most of the later session assessing whether price could reclaim short-term moving averages. The important distinction was not a persistent bullish view: it was the difference between an opening move that immediately achieved its target and a later call that did not have reliable continuation.

## Evidence Timeline

| Recording time | Observation | Research interpretation |
|---|---|---|
| 00:56-01:51 | Index futures and large-cap technology were higher before the open; oil and gold had softened. | Context was risk-on, but the source did not treat pre-market direction as sufficient for entry. |
| 17:06 | The presenter reported selling calls at 09:37 after a two-minute trade. | Short-hold opening execution was explicitly favored once immediate follow-through occurred. |
| 19:05-20:30 | A 750 call was filled near 3.89 with a stated 4.12 option target; the underlying target was near 748.80. | The target was stated before the trade-management discussion, providing a measurable reward objective. |
| 24:31-25:48 | Price remained below the intended option target; commentary shifted to hoping for a bounce from the 20 EMA and exiting if a higher chart structure formed. | The later trade became conditional on a reclaim rather than receiving the immediate confirmation seen at the open. |
| 39:21-44:25 | The source described failed buyer follow-through, low room to the prior low, and attempts to trade out of doji structure on both one- and five-minute charts. | This is a candidate congestion condition: limited range plus overlapping short-horizon structure reduces continuation quality. |
| 51:05-59:03 | A shallow 23.6% retracement was criticized as inadequate, followed by a new low and continued failure to reach the option target. | Pullback depth and room-to-target should be studied as explicit entry-quality features. |
| 1:01:34-1:02:37 | The recap reported a 746-call opening buy around 5.91, a 6% objective near 6.26, and a high near 6.54. | The fast opening setup had measurable favorable excursion and met its defined objective. |
| 1:09:33-1:09:55 | The proposed next setup required price to test and hold the one-minute 50 EMA, with the five-minute 20/50 cluster identified as nearby friction. | A multi-timeframe moving-average hold was treated as confirmation, not merely a directional signal. |

## Research Findings

1. **Immediate follow-through and later reclaim attempts should be separate setup classes.** The opening call reached the stated 6% target within minutes. The later call remained dependent on a bounce and structural reclaim. A single bullish-score threshold may not distinguish those states.

2. **Require measurable room beyond nearby friction.** The room repeatedly referenced the one-minute 20/50 EMA, five-minute moving-average cluster, neckline, prior low, and pivot/R1. McLeod Alpha should test a room-to-target feature that discounts signals whose projected target lies behind nearby structure.

3. **Shallow pullbacks are an explicit quality warning.** The source called a 23.6% retracement insufficient before the tape made a new low. This supports a research hypothesis that retracement depth, or a comparable pullback-quality measure, can help distinguish continuation from fragile extension.

4. **No live parameter change follows from this recording.** The room's commentary provides hypotheses only. Any feature or gate must be evaluated in replay with recorded option marks, MFE/MAE, and out-of-sample results.

## Candidate Replay Experiments

1. Label entries as `OPENING_FOLLOW_THROUGH` or `LATER_RECLAIM_ATTEMPT` using time since open, breakout/reclaim state, and trend maturity; compare expectancy and adverse excursion.
2. Add observational distance-to-nearest-friction fields for VWAP, pivots, intraday high/low, and multi-timeframe EMA clusters.
3. Compare baseline entries with a pullback-quality filter that requires either sufficient retracement or a confirmed reclaim after the pullback.

## Decision

The July 20 evidence supports building research labels for opening follow-through, pullback quality, and room to target. It does not support modifying the live bot until replay validation demonstrates improvement.