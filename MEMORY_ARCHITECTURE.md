# Canonical Memory Architecture

## Boundary

`engine.memory.Memory` is the sole persistence boundary for Brain, Cockpit, and execution code. It is an architectural service, not a SQLite wrapper.

- Brain emits structured decisions, signals, feature vectors, and learning events through Memory.
- Execution submits, modifies, cancels, and queries broker orders; it records resulting state through Memory.
- Cockpit reads Memory/query projections and records operator/configuration actions through Memory.
- Compatibility modules may preserve old imports during migration, but they delegate all writes to Memory.
- No application component may write a database, file, CSV, JSON, JSONL, report, image, or other artifact directly. A durable format is a Memory projection, never a second memory system.

Each append-only `MemoryEvent` has an ID, UTC time, category, event type, source, correlation ID, schema version, and structured payload. The current event-ledger projection happens to be `memory_events` in `data/mcleod_alpha.db`; callers have no SQLite contract.

Memory exposes category operations for trades, orders, positions, diagnostics, feature vectors, signals, latency, experiments, reports, performance, settings, and optimization history. It owns serialization and all compatible projections. Git remains the source-history service for tracked release contracts and configuration.

## Memory Ownership Map

This map is source-grounded as of the feature-vector migration. `Complete` means
the named runtime capability has one Memory boundary. `Partial` and `Remaining`
are explicitly not Memory-owned yet; their existing stores are catalogued so
they can be migrated one capability at a time.

| Data class | Current durable writers | Classification | Memory status | Migration owner |
| --- | --- | --- |
| Live trades, orders, positions, signals, diagnostics | `execution/trade_logger.py`, `execution/position_store.py`, `execution/signal_logger.py` | Live runtime source-of-truth plus compatibility projections | Complete | `engine.memory.Memory` |
| Entry feature vectors | `execution/live_engine.py` | Live runtime decision snapshot | Complete: `feature_vectors` table and `feature_vector_recorded` event, keyed by broker entry order | `engine.memory.Memory` |
| Monitor latency, decision audit, candle cache | `phase3_monitor.py` | Live operational projection | Complete: Memory event/projection APIs | `engine.memory.Memory` |
| Cockpit settings and operator state | `cockpit.py` | Cockpit/operator state | Complete: versioned settings events plus atomic JSON compatibility projections for stop alerts, parity baseline, manual-stop markers, and queued exit commands | `engine.memory.Memory` |
| Daily live performance delivery | `execution/daily_pnl_email.py` | Runtime performance snapshot | Complete: Memory-owned `trade_log` performance query, versioned daily performance event, and `daily_pnl_email_state.json` compatibility projection | `engine.memory.Memory` |
| Runtime, daily, delivery, Morning CIO, McLeod launcher, and latency-insights reports | `daily_report.py`, `execution/daily_trade_log_email.py`, `execution/opportunity_logger.py`, `cockpit.py`, `cio_email/morning_report.py`, `scripts/run_mcleod_report.py`, `scripts/weekly_latency_insights.py`, `scripts/send_daily_latency_email.py`, `reports/*` | Runtime/report artifact | Complete: Memory-owned text, JSON, CSV, and append-only projections with `report-artifact.v1` events | `engine.memory.Memory` |
| CIO evidence and decision journals | `engine/cio/evidence_ledger.py`, `engine/cio/decision_journal.py`, `engine/cio/evidence_replay.py` | Research/governance artifact ledger | Complete: Memory-owned JSONL, JSON, and Markdown compatibility projections with `experiment-artifact.v1` events | `engine.memory.Memory` |
| Model-weight optimization history | `engine/weight_optimizer.py` | Optimizer input, factor-history, and recommendation projections | Complete: Memory-owned CSV and Markdown compatibility projections with `optimization-artifact.v1` events | `engine.memory.Memory` |
| Research experiments | `engine/model_evaluator.py`, `engine/research_lab/*`, `engine/phase4/research_lab/*`, `backtesting/strategy_optimizer.py` | Research run artifact and lineage | Remaining | Experiment migration |
| Git source history and release manifests | Git-tracked `config/research_os_manifest.json` and immutable release contracts | Source/release provenance, not runtime state | Excluded: no runtime writer or Memory event producer exists | Git |
| Backtests, replays, validation output | `backtesting/*`, `engine/replay/*`, `run_backtest.py`, replay runners | Replay/report artifact | Remaining | Replay artifact migration |
| Data-source caches and imports | `engine/data_sources/*`, `engine/importers/*`, historical-data tools | Cache/import operational data | Remaining | Cache/import migration last |
| Phase3 paper portfolio repository and vault | `engine/phase3/paper_portfolio_persistence/*`, `engine/phase3/paper_portfolio_operations/vault.py` | Frozen independent domain state | Deferred | Formal recertification before any change |
| Test fixtures and certification outputs | `tests/*`, test scripts, `tools/*` | Test-only output | Excluded from runtime boundary | Test harness owners |

## Completed First Migration

The live persistence category now routes through Memory while retaining its current durable formats as Memory-managed projections:

- `trade_log`, `bot_order_audit`, and `trade_diagnostic_events` remain in the existing SQLite database, now owned by `Memory`.
- `open_position.json` remains the active position projection, now owned by `Memory`.
- `logs/signals.csv` remains the signal projection, now owned by `Memory`.
- Monitor latency JSONL, decision-audit JSONL, and candle-cache CSV are now Memory projections.
- Cockpit bot-stop alert state, parity baseline, manual-stop markers, and queued
	exit commands are Memory setting projections. Memory owns atomic projection
	replacement and the corresponding setting audit events.
- Every one of these writes also appends a structured event to `memory_events`.
- Live entry feature vectors are stored in the versioned `feature_vectors`
	projection and emit exactly one `feature_vector_recorded` event for each
	broker entry order correlation ID. The legacy `trade_log.feature_payload`
	remains a Memory-owned compatibility projection.

## Migration Order

1. Convert experiments, optimization, replay, research, and remaining CIO outputs to registered artifacts.
2. Consolidate cache/import persistence last, after operational and artifact state has one clear path.
3. Treat the frozen Phase3 paper-portfolio repository as a separately certified migration.
