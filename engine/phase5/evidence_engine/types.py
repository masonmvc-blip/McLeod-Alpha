from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RawEvidenceRecord:
    evidence_id: str
    ticker: str
    topic: str
    title: str
    publisher: str
    source_url: str
    source_type: str
    published_at: str
    claim: str
    polarity: str
    confidence_hint: float
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class NormalizedEvidenceRecord:
    evidence_id: str
    ticker: str
    topic: str
    title: str
    publisher: str
    source_url: str
    source_type: str
    published_at: str
    claim: str
    polarity: str
    confidence_hint: float
    provenance: Mapping[str, str]
    fingerprint: str


@dataclass(frozen=True)
class EvidenceSummary:
    topic: str
    supporting_evidence_ids: tuple[str, ...]
    opposing_evidence_ids: tuple[str, ...]
    neutral_evidence_ids: tuple[str, ...]
    support_score: float
    oppose_score: float
    confidence: float
    status: str
    rationale: str


@dataclass(frozen=True)
class EvidenceConclusion:
    ticker: str
    as_of: str
    summaries: tuple[EvidenceSummary, ...]
    unresolved_conflict_topics: tuple[str, ...]
    fail_closed: bool
    fail_reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceEngineResult:
    passed: bool
    collected_count: int
    normalized_count: int
    validated_count: int
    deduplicated_count: int
    duplicate_map: Mapping[str, tuple[str, ...]]
    evidence_scores: Mapping[str, float]
    evidence_by_id: Mapping[str, NormalizedEvidenceRecord]
    conclusion: EvidenceConclusion
    audit_steps: tuple[str, ...]


@dataclass(frozen=True)
class CertificationResult:
    passed: bool
    package_isolated: bool
    deterministic_replay_passed: bool
    traceability_passed: bool
    duplicate_handling_passed: bool
    fail_closed_passed: bool
    discrepancies: tuple[str, ...]
