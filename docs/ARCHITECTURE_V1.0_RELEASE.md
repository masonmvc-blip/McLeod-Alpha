# Architecture v1.0 Release

Release date: 2026-07-20

## Scope

This checkpoint freezes the canonical Brain and Memory architecture before new
development shifts to trading performance, model quality, feature work, and
Cockpit operational validation.

## Completed Brain Migration

- `engine.brain` is the canonical owner of entry, risk, trade-management, exit,
  and position-lifecycle decisions.
- Execution adapters consume broker-neutral Brain decisions and no longer own
  parallel entry or exit policy.
- The live execution path and replay adapters use the canonical decision model.

## Completed Memory Migration

- `engine.memory.Memory` owns live trades, orders, positions, signals,
  diagnostics, feature vectors, settings, daily performance, report artifacts,
  CIO evidence/journals, and model-weight optimization history.
- Existing SQLite, JSON, JSONL, CSV, Markdown, and report paths remain
  compatibility projections owned by Memory.
- Broker-paired trade reconciliation is idempotent in Memory and emits one
  correlated `broker_trade_reconciled` event per inserted ledger record.
- `/api/today-trades` is read-only with respect to `trade_log`.

## Verified Architecture Fixes

- Cockpit no longer directly inserts, updates, deletes, or replaces `trade_log`
  rows.
- Trade-ledger mutations emit Memory trade events with correlation IDs.
- Focused Brain, Memory, reconciliation, and Architecture Health suites passed:
  `32 passed`.

## Deferred Items

- PID lifecycle handling remains file-based and can retain stale process IDs.
- Architecture Health does not yet detect writable `Path.open("w")` or
  `Path.open("a")` calls.
- Cockpit stop-ladder display logic and exit-taxonomy aggregation remain
  intentionally deferred because execution policy is unaffected.

## Operational Caveats

- The Cloudflare-protected Cockpit is the sole supported management interface;
  its private loopback origin is not a public access path.
- Cockpit auto-reload can collide with an already bound port during a
  restart; verify the active listener and PID state before relying on a restart.
- The tag does not certify broker connectivity, live order submission, or
  Cockpit UI behavior. Those are the next operational validation focus.