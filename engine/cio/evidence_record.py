from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping


_ALLOWED_RELATIONSHIPS = {
    "supports",
    "weakens",
    "triggered",
    "considered",
    "overridden",
    "validated",
    "invalidated",
}


class EvidenceConflictError(ValueError):
    pass


class EvidenceValidationError(ValueError):
    pass


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalize_metadata(metadata: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    if not metadata:
        return ()
    normalized: list[tuple[str, str]] = []
    for key, value in sorted(((str(k), v) for k, v in metadata.items()), key=lambda item: item[0]):
        rendered = value if isinstance(value, (str, int, float, bool)) or value is None else _stable_json(value)
        normalized.append((_normalize_text(key), _normalize_text(str(rendered))))
    return tuple(normalized)


def _evidence_identity_payload(
    *,
    symbol: str,
    observed_at: str,
    source: str,
    source_type: str,
    headline: str,
    summary: str,
    raw_fact: str,
    classification: str,
    confidence: float,
    materiality: float,
    recency_score: float,
    related_thesis_component: str,
    supersedes_evidence_id: str,
    metadata: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    return {
        "symbol": _normalize_text(symbol).upper(),
        "observed_at": _normalize_text(observed_at),
        "source": _normalize_text(source),
        "source_type": _normalize_text(source_type).lower(),
        "headline": _normalize_text(headline),
        "summary": _normalize_text(summary),
        "raw_fact": _normalize_text(raw_fact),
        "classification": _normalize_text(classification).lower(),
        "confidence": round(_clamp(confidence), 6),
        "materiality": round(_clamp(materiality), 6),
        "recency_score": round(_clamp(recency_score), 6),
        "related_thesis_component": _normalize_text(related_thesis_component).lower(),
        "supersedes_evidence_id": _normalize_text(supersedes_evidence_id),
        "metadata": list(metadata),
    }


def build_evidence_id(**kwargs: Any) -> str:
    payload = _evidence_identity_payload(**kwargs)
    digest = sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:20].upper()
    return f"EVD-{digest}"


def build_evidence_content_hash(*, recorded_at: str, **kwargs: Any) -> str:
    payload = _evidence_identity_payload(**kwargs)
    payload["recorded_at"] = _normalize_text(recorded_at)
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    symbol: str
    observed_at: str
    recorded_at: str
    source: str
    source_type: str
    headline: str
    summary: str
    raw_fact: str
    classification: str
    confidence: float
    materiality: float
    recency_score: float
    related_thesis_component: str
    content_hash: str
    supersedes_evidence_id: str = ""
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = [list(item) for item in self.metadata]
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidenceRecord:
        metadata_rows = payload.get("metadata", []) or []
        metadata = tuple((str(item[0]), str(item[1])) for item in metadata_rows)
        return cls(
            evidence_id=str(payload["evidence_id"]),
            symbol=str(payload["symbol"]),
            observed_at=str(payload["observed_at"]),
            recorded_at=str(payload["recorded_at"]),
            source=str(payload["source"]),
            source_type=str(payload["source_type"]),
            headline=str(payload["headline"]),
            summary=str(payload["summary"]),
            raw_fact=str(payload["raw_fact"]),
            classification=str(payload["classification"]),
            confidence=float(payload["confidence"]),
            materiality=float(payload["materiality"]),
            recency_score=float(payload["recency_score"]),
            related_thesis_component=str(payload["related_thesis_component"]),
            content_hash=str(payload["content_hash"]),
            supersedes_evidence_id=str(payload.get("supersedes_evidence_id", "")),
            metadata=metadata,
        )


@dataclass(frozen=True)
class EvidenceLineageRecord:
    lineage_id: str
    evidence_id: str
    target_type: str
    target_id: str
    relationship: str
    influence_weight: float
    reason: str
    created_at: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidenceLineageRecord:
        return cls(
            lineage_id=str(payload["lineage_id"]),
            evidence_id=str(payload["evidence_id"]),
            target_type=str(payload["target_type"]),
            target_id=str(payload["target_id"]),
            relationship=str(payload["relationship"]),
            influence_weight=float(payload["influence_weight"]),
            reason=str(payload["reason"]),
            created_at=str(payload["created_at"]),
            content_hash=str(payload["content_hash"]),
        )


def build_lineage_id(
    *,
    evidence_id: str,
    target_type: str,
    target_id: str,
    relationship: str,
    influence_weight: float,
    reason: str,
    created_at: str,
) -> str:
    payload = {
        "evidence_id": _normalize_text(evidence_id),
        "target_type": _normalize_text(target_type),
        "target_id": _normalize_text(target_id),
        "relationship": _normalize_text(relationship).lower(),
        "influence_weight": round(_clamp(influence_weight), 6),
        "reason": _normalize_text(reason),
        "created_at": _normalize_text(created_at),
    }
    return "LNK-" + sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:20].upper()


def build_lineage_content_hash(
    *,
    evidence_id: str,
    target_type: str,
    target_id: str,
    relationship: str,
    influence_weight: float,
    reason: str,
    created_at: str,
) -> str:
    payload = {
        "evidence_id": _normalize_text(evidence_id),
        "target_type": _normalize_text(target_type),
        "target_id": _normalize_text(target_id),
        "relationship": _normalize_text(relationship).lower(),
        "influence_weight": round(_clamp(influence_weight), 6),
        "reason": _normalize_text(reason),
        "created_at": _normalize_text(created_at),
    }
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def create_evidence_record(
    *,
    symbol: str,
    observed_at: str,
    recorded_at: str,
    source: str,
    source_type: str,
    headline: str,
    summary: str,
    raw_fact: str,
    classification: str,
    confidence: float,
    materiality: float,
    recency_score: float,
    related_thesis_component: str,
    supersedes_evidence_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceRecord:
    normalized_metadata = _normalize_metadata(metadata)
    evidence_id = build_evidence_id(
        symbol=symbol,
        observed_at=observed_at,
        source=source,
        source_type=source_type,
        headline=headline,
        summary=summary,
        raw_fact=raw_fact,
        classification=classification,
        confidence=confidence,
        materiality=materiality,
        recency_score=recency_score,
        related_thesis_component=related_thesis_component,
        supersedes_evidence_id=supersedes_evidence_id,
        metadata=normalized_metadata,
    )
    content_hash = build_evidence_content_hash(
        symbol=symbol,
        observed_at=observed_at,
        recorded_at=recorded_at,
        source=source,
        source_type=source_type,
        headline=headline,
        summary=summary,
        raw_fact=raw_fact,
        classification=classification,
        confidence=confidence,
        materiality=materiality,
        recency_score=recency_score,
        related_thesis_component=related_thesis_component,
        supersedes_evidence_id=supersedes_evidence_id,
        metadata=normalized_metadata,
    )

    return EvidenceRecord(
        evidence_id=evidence_id,
        symbol=_normalize_text(symbol).upper(),
        observed_at=_normalize_text(observed_at),
        recorded_at=_normalize_text(recorded_at),
        source=_normalize_text(source),
        source_type=_normalize_text(source_type).lower(),
        headline=_normalize_text(headline),
        summary=_normalize_text(summary),
        raw_fact=_normalize_text(raw_fact),
        classification=_normalize_text(classification).lower(),
        confidence=round(_clamp(confidence), 6),
        materiality=round(_clamp(materiality), 6),
        recency_score=round(_clamp(recency_score), 6),
        related_thesis_component=_normalize_text(related_thesis_component).lower(),
        content_hash=content_hash,
        supersedes_evidence_id=_normalize_text(supersedes_evidence_id),
        metadata=normalized_metadata,
    )


def create_lineage_record(
    *,
    evidence_id: str,
    target_type: str,
    target_id: str,
    relationship: str,
    influence_weight: float,
    reason: str,
    created_at: str,
) -> EvidenceLineageRecord:
    normalized_relationship = _normalize_text(relationship).lower()
    if normalized_relationship not in _ALLOWED_RELATIONSHIPS:
        raise EvidenceValidationError(f"Invalid relationship: {relationship}")

    lineage_id = build_lineage_id(
        evidence_id=evidence_id,
        target_type=target_type,
        target_id=target_id,
        relationship=normalized_relationship,
        influence_weight=influence_weight,
        reason=reason,
        created_at=created_at,
    )
    content_hash = build_lineage_content_hash(
        evidence_id=evidence_id,
        target_type=target_type,
        target_id=target_id,
        relationship=normalized_relationship,
        influence_weight=influence_weight,
        reason=reason,
        created_at=created_at,
    )

    return EvidenceLineageRecord(
        lineage_id=lineage_id,
        evidence_id=_normalize_text(evidence_id),
        target_type=_normalize_text(target_type),
        target_id=_normalize_text(target_id),
        relationship=normalized_relationship,
        influence_weight=round(_clamp(influence_weight), 6),
        reason=_normalize_text(reason),
        created_at=_normalize_text(created_at),
        content_hash=content_hash,
    )
