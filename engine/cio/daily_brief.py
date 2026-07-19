from __future__ import annotations

from pathlib import Path

from .models import DailyCIOBrief


DEFAULT_REPORT_PATH = Path("artifacts") / "cio" / "daily_cio_brief.md"


def _component_lookup(components: tuple[tuple[str, float], ...]) -> dict[str, float]:
    return dict(components)


def _format_pct(value: float) -> str:
    return f"{value:.1f}%"


def _format_action_line(action) -> str:
    evidence = ", ".join(action.supporting_evidence) if action.supporting_evidence else "None"
    return (
        f"{action.priority}. {action.title} | Confidence {action.confidence:.1f}% | "
        f"Reason: {action.reason} | Benefit: {action.expected_benefit} | Evidence: {evidence}"
    )


def render_daily_cio_brief(brief: DailyCIOBrief) -> str:
    component_scores = _component_lookup(brief.portfolio_health_components)
    lines = [
        f"# Daily CIO Brief - {brief.date}",
        "",
        "## Executive Summary",
        brief.executive_summary,
        "",
        "## Portfolio Health",
        f"Overall Score: {brief.portfolio_health_score:.1f}/100",
        f"Overall Risk: {brief.overall_risk}",
        "",
        "| Component | Score |",
        "| --- | ---: |",
    ]
    for name, score in sorted(component_scores.items()):
        lines.append(f"| {name.replace('_', ' ').title()} | {score:.1f} |")

    lines.extend([
        "",
        "## Top Three Actions",
    ])
    for action in brief.top_actions:
        lines.append(f"- {_format_action_line(action)}")

    lines.extend([
        "",
        "## Material Thesis Changes",
    ])
    if brief.thesis_changes:
        for change in brief.thesis_changes:
            evidence = ", ".join(change.supporting_evidence) if change.supporting_evidence else "None"
            lines.append(
                f"- {change.symbol}: {change.previous_score:.1f} -> {change.adjusted_score:.1f} "
                f"(delta {change.delta:+.1f}) | {change.reason} | Evidence: {evidence}"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Recommended Buys",
    ])
    if brief.recommended_buys:
        lines.extend(f"- {_format_action_line(action)}" for action in brief.recommended_buys)
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Recommended Trims",
    ])
    if brief.recommended_trims:
        lines.extend(f"- {_format_action_line(action)}" for action in brief.recommended_trims)
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Holds",
    ])
    if brief.holds:
        lines.extend(f"- {_format_action_line(action)}" for action in brief.holds)
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Watchlist Changes",
    ])
    if brief.watchlist_changes:
        for change in brief.watchlist_changes:
            evidence = ", ".join(change.supporting_evidence) if change.supporting_evidence else "None"
            lines.append(
                f"- {change.symbol}: {change.change} | {change.reason} | Confidence {change.confidence:.1f}% | Evidence: {evidence}"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Material News",
    ])
    if brief.material_news:
        for news in brief.material_news:
            lines.append(
                f"- {news.symbol}: {news.headline} | {news.impact} | {news.materiality_score:.1f} | {news.summary}"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Cash Recommendation",
        brief.cash_recommendation,
        "",
        "## Risk Summary",
        f"Portfolio health score {_format_pct(brief.portfolio_health_score)} with {brief.overall_risk} risk profile.",
        "",
        "## Open Questions",
    ])
    open_questions = [
        "Which capital move best improves the portfolio without breaching cash and concentration constraints?",
        "Which thesis changes need follow-up before the next CIO review?",
    ]
    lines.extend(f"- {item}" for item in open_questions)
    return "\n".join(lines) + "\n"


def write_daily_cio_brief(brief: DailyCIOBrief, report_path: Path | None = None) -> Path:
    output_path = Path(report_path or DEFAULT_REPORT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_daily_cio_brief(brief), encoding="utf-8")
    return output_path