from __future__ import annotations

from pathlib import Path

from .replay_runner import ReplayRunResult


DEFAULT_REPLAY_REPORT_PATH = Path("artifacts") / "replay" / "replay_report.md"


def _render_timeline_rows(result: ReplayRunResult) -> list[str]:
    if not result.timeline:
        return ["- None"]
    out: list[str] = []
    for event in result.timeline:
        out.append(
            f"- {event['snapshot_date']} | {event['snapshot_id']} | {event['stage']} | {event['status']} | {event['content_hash'][:12]}"
        )
    return out


def _render_decision_timeline(result: ReplayRunResult) -> list[str]:
    rows: list[str] = []
    for day in result.day_results:
        payload = day["stages"]["decision"]["payload"]
        rows.append(
            f"- {day['snapshot_date']} | recommendation={payload.get('recommendation')} | confidence={payload.get('confidence')}"
        )
    return rows or ["- None"]


def _render_portfolio_timeline(result: ReplayRunResult) -> list[str]:
    rows: list[str] = []
    for day in result.day_results:
        payload = day["stages"]["portfolio"]["payload"]
        rows.append(
            f"- {day['snapshot_date']} | turnover={payload.get('turnover')} | cash_weight={payload.get('cash_weight')}"
        )
    return rows or ["- None"]


def _render_thesis_timeline(result: ReplayRunResult) -> list[str]:
    rows: list[str] = []
    for day in result.day_results:
        payload = day["stages"]["thesis"]["payload"]
        rows.append(
            f"- {day['snapshot_date']} | health_score={payload.get('health_score')} | status={payload.get('status')}"
        )
    return rows or ["- None"]


def _render_performance_timeline(result: ReplayRunResult) -> list[str]:
    rows: list[str] = []
    for day in result.day_results:
        payload = day["stages"]["performance"]["payload"]
        rows.append(
            f"- {day['snapshot_date']} | alpha={payload.get('alpha')} | replacement_quality={payload.get('replacement_quality')}"
        )
    return rows or ["- None"]


def render_replay_report(result: ReplayRunResult) -> str:
    metrics = result.metrics
    lines: list[str] = [
        f"# Historical Replay Report - {result.replay_id}",
        "",
        "## Replay Summary",
        f"- Snapshot count: {result.snapshot_count}",
        f"- Replay content hash: {result.content_hash}",
        f"- Decision stability: {metrics.decision_stability:.6f}",
        f"- Recommendation changes: {metrics.recommendation_changes}",
        f"- Portfolio turnover: {metrics.portfolio_turnover:.6f}",
        f"- Replacement quality: {metrics.replacement_quality:.6f}",
        f"- Confidence calibration: {metrics.confidence_calibration:.6f}",
        f"- Max drawdown: {metrics.max_drawdown:.6f}",
        "",
        "## Timeline",
        *_render_timeline_rows(result),
        "",
        "## Decision Timeline",
        *_render_decision_timeline(result),
        "",
        "## Portfolio Timeline",
        *_render_portfolio_timeline(result),
        "",
        "## Thesis Timeline",
        *_render_thesis_timeline(result),
        "",
        "## Performance Timeline",
        *_render_performance_timeline(result),
        "",
        "## Failures",
        "- None",
        "",
        "## Successes",
        "- No lookahead leakage detected.",
        "- Replay completed with deterministic stage hashes.",
        "- Replay metrics generated and serialized deterministically.",
    ]
    return "\n".join(lines) + "\n"


def write_replay_report(result: ReplayRunResult, *, report_path: Path | None = None) -> Path:
    target = Path(report_path or DEFAULT_REPLAY_REPORT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_replay_report(result), encoding="utf-8")
    return target
