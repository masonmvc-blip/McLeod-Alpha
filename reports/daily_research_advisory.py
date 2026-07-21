"""Daily evidence-governance advice derived from research-only report projections."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
REPORTS_DIR = Path("reports")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _recommendations(dashboard: dict[str, Any], pipeline: dict[str, Any]) -> list[dict[str, str]]:
    recommendations = [{
        "area": "live_trading_governance",
        "priority": "high",
        "advice": "Maintain current live entry rules. No research cohort may change live trading automatically.",
    }]
    focus = next((row for row in dashboard.get("cohorts") or [] if row.get("pattern") == dashboard.get("focus_pattern")), None)
    if focus:
        days = int(focus.get("trading_days_observed") or 0)
        if days < 20:
            recommendations.append({
                "area": "market_diversity",
                "priority": "high",
                "advice": f"Continue collecting the focus cohort across market sessions: {days}/20 trading days observed.",
            })
        blockers = focus.get("shadow_promotion_blockers") or []
        recommendations.append({
            "area": "shadow_promotion",
            "priority": "high",
            "advice": "Do not start shadow trading yet. Current blockers: " + "; ".join(str(item) for item in blockers) + ".",
        })
    for debt in (dashboard.get("research_debt") or [])[:2]:
        recommendations.append({
            "area": "instrumentation_debt",
            "priority": str(debt.get("impact") or "medium"),
            "advice": f"Instrument {debt.get('dimension')}: {debt.get('status')}.",
        })
    backlog = pipeline.get("backlog") or []
    if backlog:
        recommendations.append({
            "area": "research_priority",
            "priority": "medium",
            "advice": f"Review {backlog[0].get('pattern')} first; it has the largest current evidence cohort.",
        })
    return recommendations


def _render_html(trade_date: str, recommendations: list[dict[str, str]]) -> str:
    rows = "".join(
        f"<tr><td>{row['priority']}</td><td>{row['area']}</td><td>{row['advice']}</td></tr>"
        for row in recommendations
    )
    return (
        "<html><head><meta charset='utf-8'><title>Daily Research Advisory</title></head><body>"
        f"<h1>Daily Research Advisory - {trade_date}</h1>"
        "<p>Research-only guidance derived from recorded evidence. It does not issue trade signals or change live rules.</p>"
        "<table border='1' cellpadding='4' cellspacing='0'><tr><th>Priority</th><th>Area</th><th>Advice</th></tr>"
        f"{rows}</table></body></html>"
    )


def build_daily_research_advisory(trade_date: str, reports_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    """Create daily system and trading-governance advice from existing research reports."""
    dashboard = _load_json(reports_dir / "validation_dashboard.json")
    pipeline = _load_json(reports_dir / "research_pipeline.json")
    recommendations = _recommendations(dashboard, pipeline)
    payload = {
        "trade_date": trade_date,
        "generated_at": datetime.now(EASTERN_TZ).isoformat(),
        "research_only": True,
        "live_policy_change_recommended": False,
        "recommendations": recommendations,
        "source_reports": ["validation_dashboard.json", "research_pipeline.json"],
    }
    json_path = reports_dir / f"daily_research_advisory_{trade_date}.json"
    html_path = reports_dir / f"daily_research_advisory_{trade_date}.html"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(_render_html(trade_date, recommendations), encoding="utf-8")
    return json_path, html_path