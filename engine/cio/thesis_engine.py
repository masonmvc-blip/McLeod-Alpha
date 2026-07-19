from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from .thesis_evidence import ClassifiedEvidence, EvidenceSummary, ThesisEvidence, classify_evidence, summarize_classifications
from .thesis_graph import ThesisDefinition, ThesisGraph, build_thesis_graph
from .thesis_monitor import ThesisHealthBreakdown, compute_thesis_health
from .thesis_report import DEFAULT_REPORT_PATH, ThesisReport, render_thesis_report, write_thesis_report


@dataclass(frozen=True)
class ThesisEvaluation:
    thesis_id: str
    symbol: str
    as_of_date: str
    thesis: ThesisDefinition
    graph: ThesisGraph
    evidence_summary: EvidenceSummary
    health_breakdown: ThesisHealthBreakdown
    recent_changes: tuple[str, ...]
    unanswered_questions: tuple[str, ...]
    invalidation_triggers: tuple[str, ...]
    report_path: str
    markdown: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["thesis"] = self.thesis.to_dict()
        return payload


@dataclass(frozen=True)
class ThesisEngineInputs:
    thesis: ThesisDefinition
    evidence: tuple[ThesisEvidence, ...] = field(default_factory=tuple)


def _stable_json(payload: Any) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_payload(payload: Any) -> str:
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _recent_changes(summary: EvidenceSummary) -> tuple[str, ...]:
    ranked = sorted(
        (*summary.supporting, *summary.contradictory),
        key=lambda item: (item.observed_date, item.weighted_impact, item.evidence_id),
        reverse=True,
    )
    lines: list[str] = []
    for item in ranked[:5]:
        lines.append(f"{item.observed_date} | {item.classification} | {item.fact}")
    return tuple(lines)


class ThesisEngine:
    def generate(self, inputs: ThesisEngineInputs, *, report_path: Path | None = None) -> ThesisEvaluation:
        graph = build_thesis_graph(inputs.thesis)

        classified: list[ClassifiedEvidence] = []
        for evidence in sorted(inputs.evidence, key=lambda item: (item.observed_date, item.evidence_id, item.fact)):
            classified.append(classify_evidence(evidence, inputs.thesis))

        summary = summarize_classifications(tuple(classified))
        breakdown = compute_thesis_health(summary)

        unanswered_questions = graph.unanswered_questions
        invalidation_triggers = tuple(sorted({entry for entry in inputs.thesis.invalidation_criteria if entry.strip()}))
        recent_changes = _recent_changes(summary)

        markdown = render_thesis_report(
            thesis=inputs.thesis,
            evidence_summary=summary,
            breakdown=breakdown,
            recent_changes=recent_changes,
            unanswered_questions=unanswered_questions,
            invalidation_triggers=invalidation_triggers,
        )

        evaluation = ThesisEvaluation(
            thesis_id=inputs.thesis.thesis_id,
            symbol=inputs.thesis.symbol,
            as_of_date=inputs.thesis.as_of_date,
            thesis=inputs.thesis,
            graph=graph,
            evidence_summary=summary,
            health_breakdown=breakdown,
            recent_changes=recent_changes,
            unanswered_questions=unanswered_questions,
            invalidation_triggers=invalidation_triggers,
            report_path=str(report_path or DEFAULT_REPORT_PATH),
            markdown=markdown,
            content_hash="",
        )

        content_hash = _hash_payload(
            {
                "thesis_id": evaluation.thesis_id,
                "symbol": evaluation.symbol,
                "as_of_date": evaluation.as_of_date,
                "health_score": evaluation.health_breakdown.health_score,
                "supporting_count": len(evaluation.evidence_summary.supporting),
                "contradictory_count": len(evaluation.evidence_summary.contradictory),
                "neutral_count": len(evaluation.evidence_summary.neutral),
                "unknown_count": len(evaluation.evidence_summary.unknown),
                "markdown": evaluation.markdown,
            }
        )

        evaluation = ThesisEvaluation(
            thesis_id=evaluation.thesis_id,
            symbol=evaluation.symbol,
            as_of_date=evaluation.as_of_date,
            thesis=evaluation.thesis,
            graph=evaluation.graph,
            evidence_summary=evaluation.evidence_summary,
            health_breakdown=evaluation.health_breakdown,
            recent_changes=evaluation.recent_changes,
            unanswered_questions=evaluation.unanswered_questions,
            invalidation_triggers=evaluation.invalidation_triggers,
            report_path=evaluation.report_path,
            markdown=evaluation.markdown,
            content_hash=content_hash,
        )

        write_thesis_report(ThesisReport(report_path=evaluation.report_path, markdown=evaluation.markdown), report_path=report_path)
        return evaluation
