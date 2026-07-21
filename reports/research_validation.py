"""Research-only cohort validation and prioritization from daily opportunity reviews."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
REPORTS_DIR = Path("reports")
WIN_THRESHOLD_PCT = 4.0
OBSERVATION_TARGET = 100
TRADING_DAY_TARGET = 20
MARKET_REGIME_TARGET = 3
TREND_STATE_TARGET = 5
ADX_BUCKET_TARGET = 5
TIME_OF_DAY_TARGET = 4
SHADOW_PROMOTION_OBSERVATION_TARGET = 100
SHADOW_PROMOTION_TRADING_DAY_TARGET = 20
SHADOW_PROMOTION_REGIME_TARGET = 3
SHADOW_PROMOTION_VOLATILITY_TARGET = 4
SHADOW_PROMOTION_CONFIDENCE_TARGET = 80.0


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


def _adx_bucket(value: Any) -> str | None:
    adx = _number(value)
    if adx is None:
        return None
    if adx < 18:
        return "<18"
    if adx < 25:
        return "18-25"
    if adx < 30:
        return "25-30"
    if adx < 35:
        return "30-35"
    return "35+"


def _score(count: int, target: int) -> float:
    return min(count / target, 1.0) * 100.0 if target else 0.0


def _time_of_day_window(event: dict[str, Any]) -> str | None:
    timestamp = str(event.get("candle_time_et") or event.get("evaluation_time_et") or "").strip()
    try:
        hour = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).hour
    except ValueError:
        return None
    if hour < 11:
        return "open"
    if hour < 12:
        return "morning"
    if hour < 14:
        return "midday"
    return "afternoon"


def _matrix_row(dimension: str, count: int | None, target: int, instrumented: bool) -> dict[str, Any]:
    if not instrumented:
        return {"dimension": dimension, "coverage": None, "target": target, "status": "not_instrumented"}
    if count is None or count == 0:
        status = "insufficient"
    elif count >= target:
        status = "good"
    else:
        status = "partial" if count >= max(1, target // 2) else "insufficient"
    return {"dimension": dimension, "coverage": count, "target": target, "status": status}


def _evidence_half_life(dates: set[str]) -> dict[str, Any]:
    parsed_dates = sorted(date.fromisoformat(value) for value in dates)
    if not parsed_dates:
        return {"oldest_trade_date": None, "most_recent_trade_date": None, "median_age_trading_days": None}
    latest = parsed_dates[-1]
    ages = [sum(day <= latest for day in parsed_dates) - index - 1 for index, day in enumerate(parsed_dates)]
    ages.sort()
    midpoint = len(ages) // 2
    median_age = ages[midpoint] if len(ages) % 2 else (ages[midpoint - 1] + ages[midpoint]) / 2
    return {
        "oldest_trade_date": parsed_dates[0].isoformat(),
        "most_recent_trade_date": latest.isoformat(),
        "median_age_trading_days": median_age,
    }


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
    market_regimes: set[str] = set()
    trend_states: set[str] = set()
    adx_buckets: set[str] = set()
    complete_snapshots = 0
    gap_scenarios = set()
    time_of_day_windows: set[str] = set()
    for trade_date, event in rows:
        dates.add(trade_date)
        market_regime = str(event.get("market_regime") or "").strip()
        research = event.get("research") or {}
        trend_state = str(research.get("trend_state") or (event.get("shadow_market_state") or {}).get("state") or "").strip()
        adx_bucket = _adx_bucket(event.get("adx_14"))
        if market_regime:
            market_regimes.add(market_regime)
        if trend_state:
            trend_states.add(trend_state)
        if adx_bucket:
            adx_buckets.add(adx_bucket)
        if market_regime and trend_state and adx_bucket:
            complete_snapshots += 1
        gap_scenario = event.get("gap_scenario") or event.get("opening_gap_scenario")
        if gap_scenario:
            gap_scenarios.add(str(gap_scenario))
        time_window = _time_of_day_window(event)
        if time_window:
            time_of_day_windows.add(time_window)
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
    data_completeness = complete_snapshots / observations if observations else 0.0
    coverage_components = {
        "trading_days": round(_score(len(dates), TRADING_DAY_TARGET), 2),
        "market_regimes": round(_score(len(market_regimes), MARKET_REGIME_TARGET), 2),
        "trend_states": round(_score(len(trend_states), TREND_STATE_TARGET), 2),
        "adx_buckets": round(_score(len(adx_buckets), ADX_BUCKET_TARGET), 2),
        "opening_gap_scenarios": round(_score(len(gap_scenarios), 3), 2) if gap_scenarios else None,
        "time_of_day_windows": round(_score(len(time_of_day_windows), TIME_OF_DAY_TARGET), 2),
    }
    measured_coverage = [value for value in coverage_components.values() if value is not None]
    coverage_score = sum(measured_coverage) / len(measured_coverage) if measured_coverage else 0.0
    observation_score = _score(observations, OBSERVATION_TARGET)
    research_confidence = (
        observation_score * 0.30
        + coverage_score * 0.35
        + outcome_coverage * 100.0 * 0.20
        + data_completeness * 100.0 * 0.15
    )
    evidence_matrix = [
        _matrix_row("Trading Days", len(dates), TRADING_DAY_TARGET, True),
        _matrix_row("Market Regimes", len(market_regimes), MARKET_REGIME_TARGET, True),
        _matrix_row("Trend States", len(trend_states), TREND_STATE_TARGET, True),
        _matrix_row("ADX Buckets", len(adx_buckets), ADX_BUCKET_TARGET, True),
        _matrix_row("Opening Gap Scenarios", len(gap_scenarios), 3, bool(gap_scenarios)),
        _matrix_row("Volatility Regimes", None, SHADOW_PROMOTION_VOLATILITY_TARGET, False),
        _matrix_row("Time-of-Day Windows", len(time_of_day_windows), TIME_OF_DAY_TARGET, True),
    ]
    blockers = []
    if observations < SHADOW_PROMOTION_OBSERVATION_TARGET:
        blockers.append(f"observations below {SHADOW_PROMOTION_OBSERVATION_TARGET}")
    if len(dates) < SHADOW_PROMOTION_TRADING_DAY_TARGET:
        blockers.append(f"trading days below {SHADOW_PROMOTION_TRADING_DAY_TARGET}")
    if len(market_regimes) < SHADOW_PROMOTION_REGIME_TARGET:
        blockers.append(f"market regimes below {SHADOW_PROMOTION_REGIME_TARGET}")
    blockers.append("volatility regimes not instrumented")
    if research_confidence < SHADOW_PROMOTION_CONFIDENCE_TARGET:
        blockers.append(f"research confidence below {SHADOW_PROMOTION_CONFIDENCE_TARGET:g}%")
    blockers.append("manual review not completed")
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
        "market_regimes_observed": sorted(market_regimes),
        "trend_states_observed": sorted(trend_states),
        "adx_buckets_observed": sorted(adx_buckets),
        "time_of_day_windows_observed": sorted(time_of_day_windows),
        "opening_gap_scenarios_observed": sorted(gap_scenarios) if gap_scenarios else None,
        "opening_gap_scenarios_status": "unavailable: opening-gap scenario is not persisted in opportunity snapshots" if not gap_scenarios else "available",
        "average_estimated_mfe_pct": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "average_estimated_mae_pct": round(sum(maes) / len(maes), 4) if maes else None,
        "estimated_expectancy_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "estimated_win_rate_pct": round(sum(value >= WIN_THRESHOLD_PCT for value in mfes) / len(mfes) * 100.0, 2) if mfes else None,
        "outcome_coverage_pct": round(outcome_coverage * 100.0, 2),
        "data_completeness_pct": round(data_completeness * 100.0, 2),
        "coverage_score_pct": round(coverage_score, 2),
        "coverage_score_components_pct": coverage_components,
        "research_confidence_pct": round(research_confidence, 2),
        "research_confidence_weights": {
            "observation_count": 30,
            "market_diversity": 35,
            "outcome_coverage": 20,
            "data_completeness": 15,
        },
        "evidence_matrix": evidence_matrix,
        "evidence_half_life": _evidence_half_life(dates),
        "similarity_to_executed_trades_pct": None,
        "similarity_status": "unavailable: no validated feature-distance model links rejected setups to executed trades",
        "sample_quality": sample_quality,
        "governance_status": _research_status(observations),
        "promotion_eligible": False,
        "shadow_promotion_candidate": False,
        "shadow_promotion_blockers": blockers,
        "shadow_trading_status": "not_started: requires every shadow-promotion gate and explicit manual approval",
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


def _research_debt() -> list[dict[str, str]]:
    return [
        {"dimension": "Opening Gap Classification", "impact": "high", "status": "not instrumented"},
        {"dimension": "Volatility Regime", "impact": "high", "status": "not instrumented"},
        {"dimension": "Executed Trade Similarity", "impact": "medium", "status": "no validated feature-distance model"},
        {"dimension": "Overnight Context", "impact": "medium", "status": "not instrumented"},
    ]


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
        "research_debt": _research_debt(),
        "governance_note": "A cohort becomes a shadow-promotion candidate only after 100 observations, 20 trading days, 3 market regimes, 4 volatility regimes, at least 80% research confidence, and completed manual review. This report never changes the live engine.",
    }
    research_pipeline = {
        "generated_at": generated_at,
        "research_only": True,
        "promotion_eligible": False,
        "backlog": cohorts,
        "research_debt": _research_debt(),
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