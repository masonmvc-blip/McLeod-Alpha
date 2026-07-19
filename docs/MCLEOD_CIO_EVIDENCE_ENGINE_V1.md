# McLeodCIOEvidenceEngine_v1.0

## Purpose

`McLeodCIOEvidenceEngine_v1.0` is an isolated, deterministic, advisory-only Phase 5 subsystem that organizes publicly available investment evidence into traceable recommendation support.

The engine is designed to improve recommendation quality without mutating portfolios, rankings, broker state, or live production state.

## Location

- `engine/phase5/evidence_engine/`

## Architectural Guarantees

- Advisory-only: no broker imports, no order execution, no production portfolio access.
- Deterministic: identical inputs produce identical outputs regardless of input order.
- Immutable: all public data structures are frozen dataclasses.
- Traceable: every summary references supporting evidence IDs.
- Conflict preserving: supporting and opposing evidence are both retained.
- Fail closed: missing required topics, invalid evidence, or unresolved conflicts produce a fail-closed conclusion.
- Isolated: package-level firewall blocks Phase 2 downstream, portfolio engine, execution, and broker imports.

## Pipeline

1. Collect
2. Normalize
3. Validate
4. Deduplicate
5. Score
6. Summarize

## Required Topics

The current fail-closed minimum topic set is:

- `valuation`
- `quality`
- `growth`

If any required topic is missing for the evaluated ticker, the engine does not pass.

## Inputs

The engine accepts explicit `RawEvidenceRecord` inputs only. It does not fetch remote data itself.

Each record includes:

- `evidence_id`
- `ticker`
- `topic`
- `title`
- `publisher`
- `source_url`
- `source_type`
- `published_at`
- `claim`
- `polarity`
- `confidence_hint`
- `provenance`

## Outputs

The engine returns `EvidenceEngineResult`, containing:

- deterministic counts for collection/normalization/validation/deduplication
- duplicate map
- per-evidence scores
- immutable evidence registry
- immutable `EvidenceConclusion`
- ordered audit step list

## Fail-Closed Conditions

The engine fail-closes when any of the following occur:

- required fields missing
- unsupported source type or polarity
- non-public URL scheme
- evidence timestamp after `as_of`
- missing `source_document_id` provenance
- missing required topic coverage
- unresolved support/oppose conflict on a topic
- no valid evidence for ticker

## Duplicate Handling

Duplicates are identified by a canonical fingerprint built from normalized public fields. The first deterministic record is retained as canonical and all duplicates are preserved in `duplicate_map`.

## Validation Status

Local Phase 5 invariant and certification suites passed.

The repository canonical validation matrix is currently not green because pre-existing frozen milestone artifacts required by existing Phase 3 and Phase 4 certification suites are missing in this workspace state. Therefore:

- `McLeodCIOEvidenceEngine_v1.0_Validated.json` was not created.

## Public Interfaces

- `EvidenceEngineModel`
- `EvidenceEngineCertificationModel`
- `RawEvidenceRecord`
- `EvidenceEngineResult`
- `EvidenceConclusion`
