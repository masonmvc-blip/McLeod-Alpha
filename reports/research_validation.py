"""Research-only cohort validation and prioritization from daily opportunity reviews."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
REPORTS_DIR = Path("reports")
WIN_THRESHOLD_PCT = 4.0


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _research_status(observations: int) -> str:
    if observations >= 100:
        return "shadow_promotion_candidate_requires_manual_approval"
    if observations >= 30:
        return "deep_validation"
    if observations >= 10:
        return "candidate_cohort"
    return "exploratory_insufficient_data"


def _stage_value(event: dict[str, Any]) -> Any:
    stage = event.get("stage")
    if isinstance(stage, dict):
        return stage.get("stage") or stage.get("value") or stage.get("label")
    return stage


def _pattern(event: dict[str, Any]) -> str | None:
    if event.get("entered") or str(event.get("market_regime") or "").upper() == "NO_TRADE":
        return None
    reason = str(event.get("rejection_reason") or "").strip().lower()
    direction = str(event.get("direction") or "UNKNOWN").upper()
    if "score below threshold by 1" in reason:
        return f"{direction} missed by 1 point"
    if "score below threshold by 2" in reason:
        return f"{direction} missed by 2 points"
    if reason in {"not entered", "entry not entered"}:
        stage = _stage_value(event)
        return f"Stage {stage if stage is not None else 'unknown'} Not Entered"
    if any(marker in reason for marker in ("qualified", "operational", "stale", "rate limit", "pending fill")):
        return f"{direction} operationally skipped"
    return None


def _review_events(reports_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(reports_dir.glob("daily_opportunity_review_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        trade_date = str(payload.get("trade_date") or path.stem.removeprefix("daily_opportunity_review_"))
        rows.extend((trade_date, event) for event in payload.get("evaluated_setups") or [])
    return rows


def _cohort_row(pattern: str, rows: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    mfes: list[float] = []
    maes: list[float] = []
    returns: list[float] = []
    dates: set[str] = set()
    for trade_date, event in rows:
        dates.add(trade_date)
        outcome = event.get("estimated_option_outcome") or {}
        mfe = _number(outcome.get("estimated_option_mfe_pct"))
        mae = _number(outcome.get("estimated_option_mae_pct"))
        if mfe is not None:
            mfes.append(mfe)
        if mae is not None:
            maes.append(mae)
        fixed = (event.get("post_rejection_tracking") or {}).get("fixed_horizon_outcomes") or {}
        return_15 = _number((fixed.get("15") or {}).get("estimated_option_return_pct"))
        if return_15 is not None:
            returns.append(return_15)

    observations = len(rows)
    outcome_coverage = len(mfes) / observations if observations else 0.0
    if len(dates) >= 10 and observations >= 30 and outcome_coverage >= 0.9:
        sample_quality = "high"
    elif len(dates) >= 3 and observations >= 10:
        sample_quality = "developing"
    else:
        sample_quality = "preliminary"

    return {
        "pattern": pattern,
        "current_observations": observations,
        "trading_days_observed": len(dates),
        "average_estimated_mfe_pct": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "average_estimated_mae_pct": round(sum(maes) / len(maes), 4) if maes else None,
        "estimated_expectancy_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "estimated_win_rate_pct": round(sum(value >= WIN_THRESHOLD_PCT for value in mfes) / len(mfes) * 100.0, 2) if mfes else None,
        "outcome_coverage_pct": round(outcome_coverage * 100.0, 2),
        "similarity_to_executed_trades_pct": None,
        "similarity_status": "unavailable: no validated feature-distance model links rejected setups to executed trades",
        "sample_quality": sample_quality,
        "governance_status": _research_status(observations),
        "promotion_eligible": False,
        "shadow_trading_status": "not_started: requires 100 observations and explicit manual approval",
        "unavailable_metrics": ["drawdown", "sharpe", "exit_efficiency"],
        "outcome_note": "MFE, MAE, expectancy, and win rate are estimated from the SPY-path option proxy, not executable option P&L.",
    }


def _cohorts(reports_dir: Path) -> list[dict[str, Any]]:
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for trade_date, event in _review_events(reports_dir):
        pattern = _pattern(event)
        if pattern:
            groups[pattern].append((trade_date, event))
    return sorted(
        (_cohort_row(pattern, members) for pattern, members in groups.items()),
        key=lambda row: (row["current_observations"], row["average_estimated_mfe_pct"] or -float("inf")),
        reverse=True,
    )


def _render_html(title: str, rows: list[dict[str, Any]], note: str) -> str:
    if not rows:
        table = "<p>No qualifying cohorts yet.</p>"
    else:
        headers = list(rows[0].keys())
        header_html = "".join(f"<th>{header}</th>" for header in headers)
        body_html = "".join(
            "<tr>" + "".join(f"<td>{row.get(header)}</td>" for header in headers) + "</tr>"
            for row in rows
        )
        table = f"<table border='1' cellpadding='4' cellspacing='0'><tr>{header_html}</tr>{body_html}</table>"
    return (
        "<html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body><h1>{title}</h1>"
        f"<p>{note}</p>{table}</body></html>"
    )


def build_research_validation_reports(reports_dir: Path = REPORTS_DIR) -> tuple[Path, Path, Path, Path]:
    """Create non-executable validation and backlog projections from daily review evidence."""
    cohorts = _cohorts(reports_dir)
    generated_at = datetime.now(EASTERN_TZ).isoformat()
    validation_dashboard = {
        "generated_at": generated_at,
        "research_only": True,
        "promotion_eligible": False,
        "focus_pattern": "CALL missed by 1 point",
        "cohorts": [row for row in cohorts if row["current_observations"] >= 10],
        "governance_note": "A 100-observation cohort may become a shadow-trading candidate only after explicit manual approval; this report never changes the live engine.",
    }
    research_pipeline = {
        "generated_at": generated_at,
        "research_only": True,
        "promotion_eligible": False,
        "backlog": cohorts,
        "prioritization_note": "Ranked by evidence count, then estimated opportunity. Statuses describe research maturity, not trading approval.",
    }
    dashboard_path = reports_dir / "validation_dashboard.json"
    pipeline_path = reports_dir / "research_pipeline.json"
    dashboard_html_path = reports_dir / "validation_dashboard.html"
    pipeline_html_path = reports_dir / "research_pipeline.html"
    dashboard_path.write_text(json.dumps(validation_dashboard, indent=2) + "\n", encoding="utf-8")
    pipeline_path.write_text(json.dumps(research_pipeline, indent=2) + "\n", encoding="utf-8")
    dashboard_html_path.write_text(
        _render_html("Validation Dashboard", validation_dashboard["cohorts"], validation_dashboard["governance_note"]),
        encoding="utf-8",
    )
    pipeline_html_path.write_text(
        _render_html("Research Pipeline", research_pipeline["backlog"], research_pipeline["prioritization_note"]),
        encoding="utf-8",
    )
    return dashboard_path, pipeline_path, dashboard_html_path, pipeline_html_path