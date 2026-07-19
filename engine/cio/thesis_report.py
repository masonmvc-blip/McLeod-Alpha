from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .thesis_evidence import ClassifiedEvidence, EvidenceSummary
from .thesis_graph import ThesisDefinition
from .thesis_monitor import ThesisHealthBreakdown


DEFAULT_REPORT_PATH = Path("artifacts") / "cio" / "thesis_report.md"


@dataclass(frozen=True)
class ThesisReport:
    report_path: str
    markdown: str


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _render_evidence(items: tuple[ClassifiedEvidence, ...]) -> list[str]:
    if not items:
        return ["- None"]
    lines: list[str] = []
    for item in items:
        lines.append(
            "- "
            f"[{item.observed_date}] {item.fact} "
            f"(source: {item.source}, confidence: {_pct(item.confidence)}, "
            f"materiality: {_pct(item.materiality)}, recency: {_pct(item.recency)}, "
            f"impact: {item.weighted_impact:.2f})"
        )
    return lines


def render_thesis_report(
    *,
    thesis: ThesisDefinition,
    evidence_summary: EvidenceSummary,
    breakdown: ThesisHealthBreakdown,
    recent_changes: tuple[str, ...],
    unanswered_questions: tuple[str, ...],
    invalidation_triggers: tuple[str, ...],
) -> str:
    lines: list[str] = [
        f"# Thesis Report - {thesis.symbol} - {thesis.as_of_date}",
        "",
        "## Current Thesis",
        thesis.current_thesis,
        "",
        "## Supporting Evidence",
        *_render_evidence(evidence_summary.supporting),
        "",
        "## Contradictory Evidence",
        *_render_evidence(evidence_summary.contradictory),
        "",
        "## Health Score",
        f"Thesis health score: {breakdown.health_score:.2f}",
        "",
        "### Score Explanation",
    ]
    for line in breakdown.explanation:
        lines.append(f"- {line}")

    lines.extend([
        "",
        "## Recent Changes",
    ])
    if recent_changes:
        lines.extend(f"- {entry}" for entry in recent_changes)
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Key Unanswered Questions",
    ])
    if unanswered_questions:
        lines.extend(f"- {entry}" for entry in unanswered_questions)
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Possible Invalidation Triggers",
    ])
    if invalidation_triggers:
        lines.extend(f"- {entry}" for entry in invalidation_triggers)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def write_thesis_report(report: ThesisReport, *, report_path: Path | None = None) -> Path:
    output_path = Path(report_path or report.report_path or DEFAULT_REPORT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.markdown, encoding="utf-8")
    return output_path
