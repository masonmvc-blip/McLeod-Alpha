from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from engine.phase2_downstream import Phase2DownstreamAdapter, Phase2DownstreamSnapshot

from .approval import ApprovalState
from .errors import ResearchContextError


@dataclass(frozen=True)
class ResearchContext:
    ticker: str
    overall_phase2_score: float
    component_scores: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    missing_inputs: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    approval_status: ApprovalState = ApprovalState.RESEARCH_ONLY
    artifact_metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Phase2DownstreamSnapshot,
        *,
        approval_status: ApprovalState = ApprovalState.RESEARCH_ONLY,
    ) -> "ResearchContext":
        overall = dict(snapshot.overall_score)
        metadata = {
            "available": snapshot.available,
            "status": snapshot.status,
            "artifact_path": snapshot.artifact_path,
            "review_path": snapshot.review_path,
            "generated_at": snapshot.generated_at,
            "schema_version": snapshot.schema_version,
            "phase2_framework_locked": snapshot.phase2_framework_locked,
            "phase2_lock_name": snapshot.phase2_lock_name,
            "approved_for_eipv": snapshot.approved_for_eipv,
            "informational_only": snapshot.informational_only,
            "source_phase1_artifact_fingerprint": snapshot.source_phase1_artifact_fingerprint,
            "source_phase1_fact_path": snapshot.source_phase1_fact_path,
            "source_phase1_review_path": snapshot.source_phase1_review_path,
        }
        return cls(
            ticker=snapshot.ticker,
            overall_phase2_score=float(overall.get("score") or 0.0),
            component_scores=dict(snapshot.component_scores),
            confidence=float(overall.get("confidence") or snapshot.confidence or 0.0),
            missing_inputs=tuple(snapshot.missing_inputs),
            provenance=dict(snapshot.provenance),
            approval_status=approval_status,
            artifact_metadata=metadata,
        )

    def with_approval_status(self, approval_status: ApprovalState) -> "ResearchContext":
        return replace(self, approval_status=approval_status)


def load_research_context(
    ticker: str,
    *,
    approval_status: ApprovalState = ApprovalState.RESEARCH_ONLY,
    adapter: Phase2DownstreamAdapter | None = None,
) -> ResearchContext:
    phase2_adapter = adapter or Phase2DownstreamAdapter()
    snapshot = phase2_adapter.load_ticker(ticker)
    if snapshot.available is not True:
        raise ResearchContextError(f"Validated Phase 2 context is unavailable for {ticker}.")
    return ResearchContext.from_snapshot(snapshot, approval_status=approval_status)
