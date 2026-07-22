# McLeod Alpha Research Report: July 21, 2026 Trading Room

## Scope and Evidence

Source recording: Day Trade SPY, "Trading Room Video Recording - July 21, 2026" (72:08). The complete Vimeo transcript was reviewed on July 22, 2026. This report treats the presenters' commentary as external qualitative research, not as a trade instruction set. Execution facts come from the canonical McLeod Alpha trade ledger and daily trade log.

## Executive Assessment

The recording characterized the session as an opening rotation followed by a low-conviction, range-bound tape. Its most useful transferable lesson is behavioral: take confirmed opening opportunities quickly, then sharply reduce activity when price repeatedly fails at the same moving averages and pivot area.

McLeod Alpha's ledger recorded nine calls on July 21: two manual-limit trades and seven broker-reconciled exits. The combined realized option P&L was $49. The system's seven later short-duration calls were mixed, with three winners and four losers. The external room explicitly warned about a "third trade" tendency and advocated standing aside once the tape became range-bound. This creates a concrete research hypothesis that a regime-aware post-open re-entry throttle could improve trade quality. It is not yet evidence to change live logic.

## Recording Timeline and Market Read

| Recording time | Observation | Research interpretation |
|---|---|---|
| 00:48-01:47 | Futures, oil, and gold were higher amid geopolitical risk; no major scheduled macro release was expected. | Elevated headline risk but no known intraday calendar catalyst. Avoid assigning directional edge from headlines alone. |
| 08:55-10:54 | Opening surge reversed into a pullback; presenters identified clustered 10/20/50 EMAs, a pivot near 744.92-744.94, and expected opening-order imbalance. | The open was treated as a liquidity/volatility event. Signal quality required a reaction at known structure rather than chasing the first expansion. |
| 13:24-17:26 | A 746 call was entered near 4.05 and exited near 4.35 after a bounce through short-term EMA support. The stated mechanical target was approximately 6%, reached in four minutes. | A high-velocity, confirmation-based call scalp. The defining feature was immediate follow-through, not a static bullish view. |
| 18:55-25:16 | A 745 put scalp was taken near 4.30 and exited near 4.45 as price tested the pivot/support zone. | Short-hold downside trade with a reduced target because support was close. This is evidence for target compression when entering into nearby support. |
| 26:16-38:21 | Repeated discussion of unconfirmed movement, liquidity clearing, failures at the five-minute 50 EMA and pivot, and a range-bound market. | The room identified a no-trade or reduced-size regime: repeated level failures plus overlapping moving averages. |
| 38:35 onward | The presenter explicitly cited over-trading and stated an intention to stop after two trades. Later commentary continued to favor waiting for a clearer signal. | A count-based limit alone is crude, but the behavioral warning supports a re-entry penalty after multiple failed or low-excursion trades in the same unresolved range. |
| Close | The recording ended without a confirmed broad directional thesis replacing the range/chop diagnosis. | The research source does not justify late-session directional continuation entries on its own. |

## McLeod Alpha Ledger Reconciliation

The active ledger reported the following July 21 options trades. Times are normalized to the log's recorded timestamps; some broker-reconciled timestamps are UTC-formatted in the source and are not reinterpreted here.

| Trade | Direction | Contract | Hold | P&L | Exit | Observation |
|---|---|---|---:|---:|---|---|
| 216 | CALL | SPY 260731C00750000 | 4.1m | +$25 | Manual limit | Fast winner; consistent with quick-open scalp behavior. |
| 217 | CALL | SPY 260731C00748000 | 8.1m | -$70 | Manual limit | Later trade; external room's range warning raises a review question. |
| 209 | CALL | SPY 260731C00750000 | 0.6m | -$145 | Broker reconciled | Immediate loss; insufficient retained intratrade marks to determine excursion. |
| 210 | CALL | SPY 260731C00750000 | 2.9m | +$64 | Broker reconciled | Short winner. |
| 211 | CALL | SPY 260731C00750000 | 5.5m | +$155 | Broker reconciled | Best recorded winner. |
| 212 | CALL | SPY 260731C00750000 | 8.6m | -$100 | Broker reconciled | Loss in the later trade sequence. |
| 213 | CALL | SPY 260731C00750000 | 13.9m | +$75 | Broker reconciled | Longer profitable hold. |
| 214 | CALL | SPY 260731C00750000 | 11.1m | -$10 | Broker reconciled | Near-flat loss. |
| 215 | CALL | SPY 260731C00750000 | 8.2m | -$45 | Broker reconciled | Final loss. |

### Ledger Summary

- Trades: 9
- Winners / losers: 4 / 5
- Realized option P&L: +$49
- Directional mix: calls only
- High-watermark, low-watermark, MFE, MAE, and peak timestamps: unavailable for all nine trades

The unavailable excursion telemetry prevents a defensible claim that any exit missed a particular price high. It also prevents estimating whether a proposed target-compression rule would have helped. That data gap is more important than any discretionary comparison with the recording.

## Research Findings

1. **Opening structure should be treated separately from later re-entry.** The first two room trades were rapid, confirmation-led scalps around opening structure. Their logic should not be generalized to a later call-only sequence without a new breakout or trend confirmation.

2. **Repeated 50-EMA and pivot rejection is a measurable regime condition.** The room repeatedly described price returning to the five-minute 50 EMA and pivot without resolution. McLeod Alpha should test an explicit `RANGE_CONGESTION` label built from EMA compression, repeated pivot crossings/rejections, and narrow realized range.

3. **Trade-count friction is a candidate risk control, not a trading thesis.** The external source's "third trade" warning is consistent with a loss-of-selectivity risk. A research-only experiment should compare current performance with a cooldown or raised-confidence threshold after two entries in the same unresolved regime.

4. **Nearby structure should affect reward expectations.** The put scalp reduced its objective because support was nearby. For McLeod Alpha, this suggests testing a minimum room-to-target requirement based on distance to the nearest pivot, intraday range boundary, VWAP, or higher-timeframe EMA.

5. **The recording does not validate a directional bias.** Despite the day's call-only ledger, the room took both a call and a put and repeatedly emphasized uncertainty. The source supports symmetric confirmation requirements, not a persistent long bias.

## Recommended Research Queue

1. Add an observational `range_congestion_score` to the feature payload; do not alter live entry behavior until replay and out-of-sample tests pass.
2. Persist `option_high_since_entry`, `option_low_since_entry`, timestamps, bid, ask, and mark on every management cycle. This is required to evaluate target and exit changes.
3. Run a July replay comparison for three variants: baseline; increased entry threshold after two same-regime trades; and a room-to-target gate. Report trade count, P&L, MFE/MAE, drawdown, and missed-opportunity cost.
4. Audit call/put asymmetry by regime. The correct target is not equal direction counts; it is equal evidence standards and measurable expectancy.

## Decision

No live trading parameters should change from this recording alone. The actionable output is a data-capture and replay-validation agenda: capture option excursion telemetry, label congestion objectively, and test re-entry constraints before deploying any risk or signal modification.