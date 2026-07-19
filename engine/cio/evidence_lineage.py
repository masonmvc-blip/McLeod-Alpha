from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Mapping

from .decision_record import DecisionRecord
from .outcome_reconciliation import RealizedOutcome
from .portfolio_plan import PortfolioPlan
from .thesis_engine import ThesisEvaluation
from .thesis_evidence import ClassifiedEvidence, ThesisEvidence
from .evidence_record import EvidenceLineageRecord, EvidenceValidationError, create_lineage_record


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def evidence_from_thesis_input(
    *,
    classified_evidence: ClassifiedEvidence,
    recorded_at: str,
    metadata: Mapping[str, str] | None = None,
):
    from .evidence_record import create_evidence_record

    data = {
        "classification_rationale": classified_evidence.rationale,
        "weighted_impact": f"{classified_evidence.weighted_impact:.6f}",
    }
    if metadata:
        data.update({str(key): str(value) for key, value in metadata.items()})

    return create_evidence_record(
        symbol="",
        observed_at=classified_evidence.observed_date,
        recorded_at=recorded_at,
        source=classified_evidence.source,
        source_type="thesis_input",
        headline=classified_evidence.fact[:120],
        summary=classified_evidence.rationale,
        raw_fact=classified_evidence.fact,
        classification=classified_evidence.classification,
        confidence=classified_evidence.confidence,
        materiality=classified_evidence.materiality,
        recency_score=classified_evidence.recency,
        related_thesis_component="thesis",
        supersedes_evidence_id="",
        metadata=data,
    )


def _build_links(
    *,
    evidence_ids: Iterable[str],
    target_type: str,
    target_id: str,
    relationship: str,
    influence_weight: float,
    reason: str,
    created_at: str,
) -> tuple[EvidenceLineageRecord, ...]:
    items = tuple(_normalize(evidence_id) for evidence_id in evidence_ids if _normalize(evidence_id))
    if not items:
        raise EvidenceValidationError("Explicit evidence IDs are required for lineage links.")
    return tuple(
        create_lineage_record(
            evidence_id=evidence_id,
            target_type=target_type,
            target_id=target_id,
            relationship=relationship,
            influence_weight=influence_weight,
            reason=reason,
            created_at=created_at,
        )
        for evidence_id in sorted(set(items))
    )


def lineage_from_thesis_evaluation(
    *,
    evaluation: ThesisEvaluation,
    evidence_ids: Iterable[str],
    relationship: str = "considered",
    influence_weight: float = 50.0,
    reason: str = "Evidence considered during thesis evaluation.",
    created_at: str | None = None,
) -> tuple[EvidenceLineageRecord, ...]:
    created = _normalize(created_at or evaluation.as_of_date)
    return _build_links(
        evidence_ids=evidence_ids,
        target_type="ThesisEvaluation",
        target_id=evaluation.thesis_id,
        relationship=relationship,
        influence_weight=influence_weight,
        reason=reason,
        created_at=created,
    )


def lineage_from_decision_record(
    *,
    decision_record: DecisionRecord,
    evidence_ids: Iterable[str],
    relationship: str = "triggered",
    influence_weight: float = 60.0,
    reason: str = "Evidence influenced recommendation rationale.",
    created_at: str | None = None,
) -> tuple[EvidenceLineageRecord, ...]:
    created = _normalize(created_at or decision_record.as_of_date)
    return _build_links(
        evidence_ids=evidence_ids,
        target_type="DecisionRecord",
        target_id=decision_record.decision_id,
        relationship=relationship,
        influence_weight=influence_weight,
        reason=reason,
        created_at=created,
    )


def lineage_from_portfolio_plan(
    *,
    portfolio_plan: PortfolioPlan,
    evidence_ids: Iterable[str],
    relationship: str = "considered",
    influence_weight: float = 55.0,
    reason: str = "Evidence considered when forming portfolio plan.",
    created_at: str | None = None,
) -> tuple[EvidenceLineageRecord, ...]:
    created = _normalize(created_at or portfolio_plan.date)
    target_id = f"PLAN-{portfolio_plan.date}"
    return _build_links(
        evidence_ids=evidence_ids,
        target_type="PortfolioPlan",
        target_id=target_id,
        relationship=relationship,
        influence_weight=influence_weight,
        reason=reason,
        created_at=created,
    )


def lineage_from_realized_outcome(
    *,
    realized_outcome: RealizedOutcome,
    evidence_ids: Iterable[str],
    relationship: str,
    influence_weight: float = 70.0,
    reason: str = "Outcome validated or invalidated prior evidence.",
    created_at: str | None = None,
) -> tuple[EvidenceLineageRecord, ...]:
    if relationship not in {"validated", "invalidated"}:
        raise EvidenceValidationError("Outcome lineage relationship must be 'validated' or 'invalidated'.")
    created = _normalize(created_at or realized_outcome.evaluation_date)
    target_id = _normalize(realized_outcome.decision_id) or f"OUTCOME-{created}"
    return _build_links(
        evidence_ids=evidence_ids,
        target_type="RealizedOutcome",
        target_id=target_id,
        relationship=relationship,
        influence_weight=influence_weight,
        reason=reason,
        created_at=created,
    )
