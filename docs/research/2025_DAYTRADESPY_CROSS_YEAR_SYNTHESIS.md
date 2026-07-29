# Day Trade SPY 2025 Full-Year and Cross-Year Research Synthesis

## Outcome

The 2025 catalog is complete at the post level and the research can now move
from source collection to controlled testing:

- 230/230 archive posts have evidence-honest Markdown reports and validated v2
  machine records.
- 221 are Tier C transcript-led source reviews; nine are Tier E access,
  missing-content, or exact-duplicate resolutions.
- The registry has no pending posts, missing record paths, post-ID conflicts,
  source-URL mismatches, or missing report paths.
- No result in this corpus authorizes a live trading change.

The strongest cross-year finding is not a claimed win rate. It is a repeatable
decision sequence: **accepted structure, sufficient room, and executable
option pricing**. The most important recurring failure is converting an
intraday premise into averaging, repair, or overnight exposure without a
reconciled invalidation and terminal outcome.

## Evidence Boundary

The 2025 machine corpus contains 1,216 timeline observations, 758 bounded
claims, and 1,029 trade-observation rows across 219 post records. Of those
trade rows, 512 have a numeric exit premium and 411 have no numeric exit
premium; the remainder use nonnumeric or model-specific terminal fields.
These are presenter-reported or report-derived observations, not broker-
verified executions.

The cross-year comparison uses 81 dated 2026 Day Trade SPY reports through
July 21. The 2026 set is not a matching machine corpus, and only July 21 adds a
reconciled McLeod Alpha ledger fact set. Therefore:

- no source-side profit factor, expectancy, win rate, or drawdown is asserted;
- modeled picks, participant comments, presenter trades, co-presenter trades,
  open positions, and explicit no-trades remain separate;
- duplicate source assets are counted once;
- a target, order, quoted mark, or option high is not treated as a fill;
- term recurrence ranks research questions but does not demonstrate edge.

## Corpus Recurrence Screen

The following is a document-level keyword/label screen of focused timeline,
claim, trade, and counterfactual text. Counts indicate that a concept appears
in a report, not that it occurred once, succeeded, or has the same annotation
depth across years.

| Research concept | 2025 Tier C records | 2026 dated reports | Interpretation |
| --- | ---: | ---: | --- |
| Target/exit/fill lifecycle | 215/221 | 77/81 | Terminal-state integrity is nearly universal and must be explicit. |
| Confirmation/acceptance/retest | 99/221 | 65/81 | First penetration is repeatedly distinguished from an accepted break. |
| Structural room/support/resistance/pivots/EMA/VWAP | 80/221 | 72/81 | Direction alone is insufficient; intervening friction matters. |
| Explicit wait/no-trade/unfilled/cancelled idea | 69/221 | 29/81 | Rejected and missed signals are necessary controls, not missing data. |
| Open/carry/overnight/unresolved exposure | 140/221 | 17/81 | 2025 repeatedly exposes lifecycle and tail-risk ambiguity. |
| Loss/stop/adverse outcome | 109/221 | 71/81 | The corpus includes meaningful negative evidence; it is not a wins-only set. |
| Averaging/repair/reload discussion | 61/221 | 32/81 | Repair is common enough to require separate risk treatment. |
| Bid/ask/spread/liquidity/executable-price discussion | 41/221 | 60/81 | 2026 reports more often foreground execution feasibility. |

Differences in these counts may reflect report style and evidence availability.
They must not be interpreted as year-over-year performance changes.

## Cross-Year Findings

### 1. Acceptance is the best-supported entry-quality hypothesis

Across both years, the recurring admissible sequence is a close through a
predefined level followed by a hold, retest, or fresh continuation. A touch,
wick, first penetration, or one-minute visual pattern is repeatedly shown as
insufficient. Explicit no-trades on February 28 and other sessions are valuable
negative controls because the setup appeared but admission never completed.

**Actionable research label:** `BREAKOUT_ACCEPTED`.

Required fields: defining zone, close-through distance, confirming timeframe,
retest depth, hold duration, relative volume, time of day, and first opposing
structure.

### 2. Structural room is part of the setup, not merely target selection

Pivots, prior extrema, opening ranges, VWAP, and EMA clusters repeatedly limit
follow-through. A correct directional idea can still be a poor entry when the
projected path immediately meets friction. The same principle applies to late
continuation after an extended impulse.

**Actionable research fields:** direction-specific nearest friction,
`room_to_friction_atr`, projected option return to friction, intervening zone
count, and trend-leg/extension state.

### 3. Opening follow-through and later re-entry are different populations

Fast opening scalps and OMG trades frequently report short completion times.
Later entries often require a pullback, reclaim, or new accepted breakout and
show more congestion, target revision, or unresolved status. Pooling these
events would hide time-of-day and regime effects.

**Actionable segmentation:** `OPENING_FOLLOW_THROUGH`,
`LATER_CONTINUATION`, `FAILED_BREAK_RECLAIM`, and `CONGESTION`.

### 4. Terminal-state discipline is a prerequisite to any performance claim

The completed 2025 review repeatedly distinguishes completed wins, completed
losses, stops, open positions, overnight carries, working targets, unfilled
orders, modeled picks, and explicit no-trades. Several sessions combine
profitable realized trades with unresolved risk. Session-level dollar claims
therefore cannot substitute for position-level lifecycle accounting.

**Actionable rule for the research dataset:** every position must end in one of
`COMPLETED_PROFIT`, `COMPLETED_LOSS`, `STOPPED`, `BREAKEVEN`,
`OPEN_INTRADAY`, `OPEN_OVERNIGHT`, `UNFILLED`, `CANCELLED`, `MODELED_ONLY`,
or `UNKNOWN`. Unknown and open states must never be scored as wins.

### 5. Repair and overnight conversion are tail-risk hypotheses, not edge

Averaging, repair, holding through expiration risk, and converting a missed
intraday target into an overnight thesis recur across 2025 and remain visible
in 2026. The corpus supplies examples of recovery, loss, and unresolved
exposure, but it does not supply reconciled adverse-excursion paths capable of
showing that repair improves expectancy.

**Research-only treatment:** label `REPAIR_ADD`, `TARGET_TO_CARRY_CONVERSION`,
size multiplier, revised average price, original invalidation, new invalidation,
overnight gap, and total portfolio exposure. Do not weaken live stops or enable
averaging from source recurrence.

### 6. Option executability can veto an otherwise valid SPY setup

The underlying structure and the option trade are separate gates. Contract
identity, expiry, delta, bid, ask, spread, volume/open interest, quote age,
order identity, fill, fees, and slippage are required. An isolated last trade,
option high, midpoint, or narrated target is not enough to prove feasibility.

**Actionable research gate:** `OPTION_EXECUTABLE`, evaluated after the
underlying setup passes and before simulated admission.

## Prioritized Offline Replay Plan

### Experiment 1: Accepted break versus first penetration

- Baseline: current historical admission or first qualifying penetration.
- Treatment: close beyond zone plus hold/retest and follow-through.
- Segment by opening/later session, event window, gap size, direction, and
  trend/congestion state.
- Evaluate after-cost expectancy, MFE/MAE, first-passage target/stop,
  drawdown, exposure, rejected winners, and sample retention.
- Falsify if chronological out-of-sample improvement is absent or comes only
  from removing most trades.

### Experiment 2: Structural room and target compression

- Baseline: direction signal with fixed target.
- Treatments: minimum room gate; structural target cap; both combined.
- Reconstruct pivots, VWAP, prior extrema, opening range, and one-/five-minute
  EMA clusters without future leakage.
- Falsify if room does not improve after-cost target attainment or worsens
  drawdown/sample stability.

### Experiment 3: Congestion no-admission and re-entry friction

- Build a congestion score from realized range, EMA compression, repeated
  pivot/VWAP crossings, failed closes, and same-regime attempt count.
- Compare no-admission and increased re-entry threshold against an ungated
  baseline.
- Include rejected signals so reduced turnover is not misreported as edge.

### Experiment 4: Pullback quality and extension

- Label trend age, impulse-leg count, normalized EMA distance, pullback depth
  and duration, reclaim close, and volume renewal.
- Compare later continuation after a defined pullback/reclaim against shallow
  or zero-pullback entries.
- Keep opening follow-through out of this population.

### Experiment 5: Repair/carry counterfactual

- For every repair or overnight conversion, replay the original stop, no-add
  exit, add/repair path, and end-of-session close.
- Use total capital at risk, overnight gap, option decay, MFE/MAE, and maximum
  drawdown—not recovery frequency—as primary metrics.
- This experiment may only support a prohibition or continued research; it
  does not authorize live averaging.

### Experiment 6: Option execution veto

- Replay the underlying signal using timestamped bid/ask/mark and actual
  contract constraints.
- Reject stale, wide, illiquid, or unidentifiable contracts.
- Compare theoretical midpoint outcomes with executable fill assumptions and
  broker-reconciled results.

## Minimum Data Contract

Every evaluated signal—accepted or rejected—should retain:

1. Timestamp, session phase, direction, setup class, and event-window tag.
2. Defining zone, confirmation close, retest/hold state, relative volume, and
   multi-timeframe structure.
3. Nearest opposing friction, room in ATR/points, trend age, impulse count, and
   pullback depth.
4. Option symbol, expiry, strike, side, delta, IV, volume/open interest, bid,
   ask, mark, last, quote age/source, and spread.
5. Order ID, fill ID, entry/exit fill, fees, slippage, stop, target, target
   revisions, size changes, and repair/carry flags.
6. MFE, MAE, first-passage target/stop, time at high/low, terminal state, and
   canonical ledger linkage.

Rejected signals and no-trades are required to measure opportunity cost and
selection bias.

## Promotion Gate

The existing lifecycle standard remains controlling: at least 50 valid trades,
at least 10 observations per observed phase, at least 80% known first-passage
coverage, and exact broker reconciliation. Evaluation must use chronological
train/validation/test blocks plus rolling walk-forward analysis.

Even if a candidate passes, it requires a separate human-reviewed
implementation and certification decision. This catalog and synthesis never
promote themselves.

## Explicit Non-Changes

- No live entry, exit, stop, target, sizing, direction, expiry, averaging,
  re-entry, or overnight-hold rule changes.
- No source-reported win rate is imported into the bot.

## Automated Shadow Implementation

The five prioritized findings are implemented as the observe-only
`day-trade-spy-shadow-suite.v1`. Prospective capture, historical backfill,
daily reporting, provenance rules, and the human-only promotion boundary are
documented in
[`DAY_TRADE_SPY_SHADOW_AUTOMATION.md`](DAY_TRADE_SPY_SHADOW_AUTOMATION.md).
- No target without a verified fill is scored as completed.
- No open or unknown lifecycle is scored as profitable.
- No duplicate source post is counted as an independent observation.

## Final Decision

`RESEARCH_COMPLETE_VALIDATION_PENDING`.

The catalog is actionable as an offline testing agenda and instrumentation
specification. It is not evidence that any candidate rule improves live
expectancy. Live behavior remains unchanged until separate replay,
out-of-sample, first-passage, and broker-reconciled validation passes the
existing promotion gate.
