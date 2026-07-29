# Day Trade SPY Shadow Automation

## Purpose

`day-trade-spy-shadow-suite.v1` converts the completed 2025–2026 catalog
findings into five falsifiable, observe-only evaluations:

1. Accepted break versus first penetration.
2. Structural room plus executable option quote.
3. Opening follow-through versus later pullback/reclaim.
4. Congestion no-admission plus re-entry friction.
5. Original-premise/no-repair counterfactual.

The suite is research telemetry. It cannot place, block, resize, stop, target,
repair, carry, or close a trade. Every snapshot contains:

```json
{
  "shadow_only": true,
  "automatic_live_change_allowed": false
}
```

## Automatic Prospective Capture

The live monitor evaluates CALL and PUT independently on each completed-candle
entry evaluation. It also records labels when entry evaluation is skipped
because a position is already open or the entry window is closed.

For a selected contract, the full suite is copied into the immutable entry
`feature_payload`. The evaluation ID and snapshot then flow into option
management telemetry and the broker-backed completed trade.

After the live quote guard passes and the broker fill is known, the same entry
payload is enriched with the actual pre-submit bid, ask, mark, last, quote age,
spread, timestamp/source, submitted limit, fill price, fill method, and
slippage. These fields are observational and are not read by admission logic.

The opportunity log retains both entered and rejected directions. This is
required to measure opportunity cost and prevents lower turnover from being
misreported as edge.

## Historical Backfill

Run every broker-backed date:

```bash
python3 scripts/backfill_day_trade_spy_shadow.py
```

Or select dates:

```bash
python3 scripts/backfill_day_trade_spy_shadow.py \
  --date 2026-07-28 \
  --date 2026-07-29
```

Backfill joins completed trades by broker order ID, uses only decision-audit
candles strictly earlier than the entry, and joins timestamped option
management telemetry. Provenance is one of:

- `captured_live`
- `decision_audit_reconstruction`
- `UNAVAILABLE`

Missing quotes, stops, candles, or first-passage observations are never
inferred. Delayed-entry treatments cannot be claimed executable without a
timestamped option quote at the proposed entry.

## Daily Review

`run_daily_trade_learning.py` automatically writes:

- `day_trade_spy_shadow_YYYY-MM-DD.json`
- `day_trade_spy_shadow_YYYY-MM-DD.csv`
- `day_trade_spy_shadow_YYYY-MM-DD.md`

The Markdown review is appended to the normal daily learning report. The
existing after-close scheduler retries daily learning until broker
reconciliation succeeds.

## Promotion Boundary

The report remains `COLLECT_MORE_DATA` until all of these are true:

- exact canonical broker reconciliation;
- at least 50 valid broker-backed trades;
- at least 10 observations per observed session phase;
- at least 80% known target-versus-initial-stop first passage.

After those checks pass, the result is only
`ELIGIBLE_FOR_HUMAN_REVIEW`. Chronological holdout and rolling walk-forward
review are still required. A live rule requires a separate implementation,
review, and certification change.

## Historical Backfill Completed on 2026-07-28

A read-only SQLite backup of the local authoritative runtime ledger was used.
The source database and live runtime files were not modified.

- 98 broker-backed committed trades across 9 dates were reviewed.
- 3,408 entered/rejected opportunity records were available across five dates.
- 70 committed trades had at least one reconstructable test.
- 5 trades had known option target-versus-initial-stop first passage.
- Promotion remained `COLLECT_MORE_DATA`.
- No live trading behavior changed.

The limiting facts are expected: historical option-quote and original-stop
coverage did not exist for most earlier trades. Prospective capture now stores
those facts automatically.
