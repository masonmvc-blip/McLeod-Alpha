# July 24, 2026 Autonomous Trade Review

## Scope

This review concerns autonomous decisions recorded by McLeod Alpha on July 24. It is not discretionary trading guidance and does not activate a live signal or exit change.

## Evidence

The source of truth was `canonical_completed_trades` and its immutable payload versions in `data/mcleod_alpha.db`. All four entries have closed-candle decision snapshots. Their exit snapshots retain realized entry and exit prices, but not timestamped option bid, ask, mark, MFE, or MAE paths.

| ET entry | Contract | Phase | Checklist | CQ | MA | ABS | CONF | Gross option P&L | Recorded exit |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 10:46 | 738 put | Established | 5 | 2.60 | 3.75 | 3.33 | 3.15 | -$198 | Broker reconciled exit |
| 10:58 | 740 call | Early continuation | 7 | 3.96 | 5.00 | 5.00 | 4.27 | +$108 | Broker reconciled exit |
| 11:57 | 745 call | Early continuation | 5 | 3.38 | 3.75 | 1.67 | 3.79 | +$6 | Broker reconciled exit |
| 13:35 | 745 call | Early continuation | 6 | 3.69 | 3.75 | 3.33 | 4.13 | -$114 | Broker reconciled exit |

The canonical option P&L sums to -$198 before the approximately $32.21 all-in costs supplied for the operational report, or -$230.21 net. Every trade used six contracts. The profitable call was the highest recorded observation on checklist, CQ, MA, ABS, and CONF.

## Root-Cause Findings

1. **Fixed exposure:** `engine/brain/live_rules.py` returns `MAX_OPEN_CONTRACTS` after merely checking that the underlying stop distance is nonzero. `engine/brain/engine.py` then requires submitted quantity to equal that maximum. The July 24 risk magnitude was therefore not normalized to a dollar budget.
2. **Weak Established admission:** the 10:46 put had phase `ESTABLISHED`, CQ 2.60, CONF 3.15, no pullback-depth confirmation, and a 12-minute trend age. The live score threshold admitted it because score and regime were sufficient; the feature snapshot was observational at that time.
3. **Insufficient structural room:** the 11:57 call was already beyond recorded nearest resistance and the 13:35 call was also beyond recorded resistance. Both had zero pullback-depth candles. The current live admission path does not require room to the next opposing structure.
4. **Transaction costs matter:** the 11:57 call's canonical gross result was only +$6, so it cannot cover the reported all-in costs. Current entry selection has broad quote-quality safeguards but no explicit expected-edge-versus-cost admission test.

## Rejected Hypotheses

- **A different stop, trailing stop, or Mason-style exit would have improved July 24:** rejected as untestable. The retained `mfe_pct`, `mae_pct`, option high/low, timestamps, and intratrade executable bid/ask/mark values are null for all four trades. A candle-only model cannot establish an executable option exit.
- **The new candidate thresholds improve historical expectancy:** rejected as unvalidated. The retained ledger spans July 7-24, but the available OHLCV replay file ends July 20 and does not include the July 24 option contracts or executable option paths. This prevents a chronological in-sample/validation/out-of-sample comparison that includes the reviewed session with realistic costs.
- **Reduce fixed six-contract sizing immediately:** rejected for live activation. The sizing implementation is coupled to the runtime exact-maximum contract lock and has no validated risk budget or option-path replay evidence.

## Candidate Controls

`config/autonomous_candidate_controls.json` introduces explicit, disabled-by-default controls:

- `block_low_confidence_established`
- `block_extended_no_pullback`
- `require_structural_room`
- `require_cost_efficiency`
- `use_dollar_risk_sizing`

The first four are wired into post-option-selection entry admission only when both the global `enabled` flag and the individual flag are true. Rejections are recorded in existing shadow-opportunity telemetry. `use_dollar_risk_sizing` is deliberately calculation-only until its contract-lock integration and historical validation are separately certified.

## Next Session

Keep every candidate flag disabled. Capture per-management-cycle option bid, ask, mark, high/low since entry, timestamped MFE/MAE, and broker fill costs. Backfill matching SPY and option histories through July 24 and later dates. Only then run fixed chronological splits with baseline versus each candidate and combinations, reporting net expectancy, profit factor, average winner/loser, win rate, max drawdown, risk-adjusted return, exposure, phase/confidence buckets, rejected trades, and before/after costs.

Promotion requires out-of-sample improvement without material sample collapse or higher drawdown. Until then, the baseline remains the production policy and rollback is immediate: retain `enabled: false` in the candidate configuration.