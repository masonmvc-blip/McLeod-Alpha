# Day Trade SPY Research Ingestion Protocol

## Purpose

This is a research-only ingestion system for Day Trade SPY recordings. Presenter commentary is qualitative external evidence, never live trade instruction or production authority.

## Daily Operation

Run:

```sh
python3 tools/run_daytradespy_daily_ingestion.py
```

The command refreshes the public archive manifest and merges it into the recording registry. A record already marked `complete` under the current analysis protocol is not eligible for repeat processing. A protocol-version change marks it for reprocessing.

## Persistent Artifacts

- `data/research/daytradespy/archive_manifest.json`: public-source inventory.
- `data/research/daytradespy/recording_registry.json`: chronological recording control plane and source lineage.
- `data/research/daytradespy/hypothesis_registry.json`: deduplicated, versioned research hypotheses.
- `data/research/daytradespy/claim_registry.json`: timestamped claims and recurrence outcomes.
- `data/research/daytradespy/instrumentation_backlog.json`: data gaps ordered by research impact.
- `data/research/daytradespy/unresolved_conflicts.json`: source, ledger, and replay conflicts.
- `data/research/daytradespy/source_scorecard.json`: incremental replay value of observations, not reported trade wins.

## Recording Completion Standard

Each completed JSON record must preserve source lineage, title, publication date, duration, transcript availability/completeness, review date, protocol version, timestamped claims, timeline entries, setup and regime labels, source-reported trades, ledger reconciliation, hypotheses, conflicts, confidence, data quality, and the final governance decision.

The accompanying Markdown report must include an executive assessment, evidence timeline, reported-trade table, ledger reconciliation, recurring and contradictory evidence, no more than five candidate hypotheses, instrumentation gaps, explicit non-changes, and final decision.

## Evidence Quality

Grade each report across transcript completeness, trade-detail capture, ledger reconciliation, underlying market data, and option excursion telemetry. Do not infer option MFE, MAE, intratrade highs/lows, or peak timestamps from source commentary. Mark missing fields as unavailable and add the gap to the instrumentation backlog.

### Evidence Tiers

- **Tier A**: 100% transcript and 100% visual review.
- **Tier B**: at least 90% transcript and completed visual review.
- **Tier C**: at least 90% transcript and visual review unavailable.
- **Tier D**: 50% through 89% transcript coverage.
- **Tier E**: less than 50% transcript coverage.

Tiers B through D are eligible for partial research. Extract only observable evidence through the measured transcript cutoff, label the unobserved remainder `UNKNOWN`, and lower confidence according to the tier. Only Tier E is blocked for insufficient transcript evidence. Tier A remains the only completion standard; incomplete visual coverage must not be reported as complete.

Every timestamped assessment must be evaluated against standardized forward windows of 1, 3, 5, 10, and 15 minutes plus the remainder of the session when underlying bars are available. Searches for disconfirming evidence are mandatory: failed follow-through, worse confirmed entries, congestion resolving into expansion, and resistance failing to constrain MFE.

## Governance

All source ideas begin as `OBSERVATION_ONLY` or `NEEDS_INSTRUMENTATION`. A change can move through `READY_FOR_PROTOCOL`, `REPLAY_PENDING`, and `SHADOW_TESTING` only with replay evidence and independently governed approval. This ingestion system cannot alter live entry, exit, stop, sizing, direction, or risk behavior.