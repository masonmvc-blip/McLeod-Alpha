"""Daily research-only review of alternative SPY volume interpretations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from reports.entry_quality_shadow_report import load_study_trades


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
MODEL_VERSION = "volume-shadow-review.v1"
MINIMUM_DECISIVE_EPISODES = 20
MINIMUM_OUTCOME_COVERAGE_PCT = 80.0
MINIMUM_TOD_BASELINE_SESSIONS = 3


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_opportunities(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted((root / "reports").glob("daily_opportunity_review_*.json")):
        payload = _load_json(path)
        report_date = path.stem.removeprefix("daily_opportunity_review_")
        for event in payload.get("evaluated_setups") or []:
            volume = event.get("volume_shadow")
            if not isinstance(volume, dict) or not volume.get("valid"):
                continue
            event_id = str(event.get("event_id") or "")
            key = f"{report_date}|{event_id}"
            if key in seen:
                continue
            seen.add(key)
            outcome = event.get("estimated_option_outcome") or {}
            rows.append({
                "report_date": report_date,
                "event_id": event_id,
                "candle_time_et": event.get("candle_time_et"),
                "direction": str(event.get("direction") or "UNKNOWN").upper(),
                "entered": bool(event.get("entered")),
                "phase": (
                    (event.get("stage") or {}).get("label")
                    if isinstance(event.get("stage"), dict)
                    else event.get("stage")
                ),
                "volume_shadow": volume,
                "estimated_mfe_pct": _number(outcome.get("estimated_option_mfe_pct")),
                "estimated_mae_pct": _number(outcome.get("estimated_option_mae_pct")),
            })
    return rows


def _attach_time_of_day_normalization(rows: list[dict[str, Any]]) -> None:
    unique_candles: dict[tuple[str, str, Any], float] = {}
    for row in rows:
        volume = row["volume_shadow"]
        bucket = volume.get("time_of_day_baseline_bucket")
        current = _number(volume.get("current_volume"))
        candle_time = str(row.get("candle_time_et") or "")
        if bucket is None or current is None:
            continue
        unique_candles[(row["report_date"], candle_time, bucket)] = current

    bucket_sessions: dict[Any, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (report_date, _, bucket), current in unique_candles.items():
        bucket_sessions[bucket][report_date].append(current)

    for row in rows:
        volume = row["volume_shadow"]
        bucket = volume.get("time_of_day_baseline_bucket")
        current = _number(volume.get("current_volume"))
        prior_session_values = []
        for session_date, values in bucket_sessions.get(bucket, {}).items():
            if session_date < row["report_date"] and values:
                prior_session_values.append(median(values))
        baseline = median(prior_session_values) if prior_session_values else None
        volume["time_of_day_baseline_sessions"] = len(prior_session_values)
        volume["time_of_day_baseline_volume"] = (
            round(baseline, 4) if baseline is not None else None
        )
        volume["time_of_day_relative_volume"] = (
            round(current / baseline, 4)
            if current is not None and baseline is not None and baseline > 0
            else None
        )


def _cohort(rows: list[dict[str, Any]], outcome_key: str) -> dict[str, Any]:
    values = [_number(row.get(outcome_key)) for row in rows]
    values = [value for value in values if value is not None]
    return {
        "episodes": len(rows),
        "outcome_coverage_pct": round(100.0 * len(values) / len(rows), 1) if rows else 0.0,
        "positive_outcomes": sum(value > 0 for value in values),
        "negative_outcomes": sum(value < 0 for value in values),
        "average_outcome": round(sum(values) / len(values), 2) if values else None,
    }


def _policy_opportunity_cohorts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for policy, result in (row["volume_shadow"].get("policies") or {}).items():
            state = (
                "PASS"
                if result.get("would_pass_score_threshold") is True
                else "BLOCK"
                if result.get("would_pass_score_threshold") is False
                else "UNKNOWN"
            )
            grouped[(row["direction"], policy, state)].append(row)

    output = []
    for (direction, policy, state), members in sorted(grouped.items()):
        mfe = _cohort(members, "estimated_mfe_pct")
        mae_values = [
            value for value in (_number(row.get("estimated_mae_pct")) for row in members)
            if value is not None
        ]
        output.append({
            "direction": direction,
            "policy": policy,
            "state": state,
            **mfe,
            "average_estimated_mae_pct": (
                round(sum(mae_values) / len(mae_values), 2) if mae_values else None
            ),
            "plus_6_opportunities": sum(
                (_number(row.get("estimated_mfe_pct")) or float("-inf")) >= 6.0
                for row in members
            ),
            "minus_5_risks": sum(
                (_number(row.get("estimated_mae_pct")) or float("inf")) <= -5.0
                for row in members
            ),
        })
    return output


def _broker_cohorts(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        volume = trade.get("volume_shadow")
        if not isinstance(volume, dict) or not volume.get("valid"):
            continue
        for policy, result in (volume.get("policies") or {}).items():
            state = (
                "PASS"
                if result.get("would_pass_score_threshold") is True
                else "BLOCK"
                if result.get("would_pass_score_threshold") is False
                else "UNKNOWN"
            )
            grouped[(trade["direction"], policy, state)].append(trade)

    output = []
    for (direction, policy, state), members in sorted(grouped.items()):
        stats = _cohort(members, "pnl_dollars")
        output.append({
            "direction": direction,
            "policy": policy,
            "state": state,
            **stats,
            "broker_backed": True,
        })
    return output


def evaluate_volume_shadow(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    opportunities = _load_opportunities(root)
    _attach_time_of_day_normalization(opportunities)
    trades, trade_coverage = load_study_trades(root=root)
    broker_cohorts = _broker_cohorts(trades)
    opportunity_cohorts = _policy_opportunity_cohorts(opportunities)
    current = [row for row in opportunities if row["report_date"] == trading_date]

    tod_covered = sum(
        int((row["volume_shadow"].get("time_of_day_baseline_sessions") or 0) >= MINIMUM_TOD_BASELINE_SESSIONS)
        for row in opportunities
    )
    outcome_covered = sum(
        row.get("estimated_mfe_pct") is not None and row.get("estimated_mae_pct") is not None
        for row in opportunities
    )
    decisive_ready = any(
        row["episodes"] >= MINIMUM_DECISIVE_EPISODES
        and row["outcome_coverage_pct"] >= MINIMUM_OUTCOME_COVERAGE_PCT
        for row in opportunity_cohorts
    )
    directions = {row["direction"] for row in opportunities}
    phases = {str(row.get("phase")) for row in opportunities if row.get("phase")}
    governance = {
        "minimum_decisive_episodes_per_policy_state": MINIMUM_DECISIVE_EPISODES,
        "minimum_outcome_coverage_pct": MINIMUM_OUTCOME_COVERAGE_PCT,
        "minimum_time_of_day_baseline_sessions": MINIMUM_TOD_BASELINE_SESSIONS,
        "decisive_policy_state_available": decisive_ready,
        "call_and_put_representation": {"CALL", "PUT"}.issubset(directions),
        "multiple_phase_representation": len(phases) >= 2,
        "time_of_day_coverage_pct": (
            round(100.0 * tod_covered / len(opportunities), 1)
            if opportunities else 0.0
        ),
        "outcome_coverage_pct": (
            round(100.0 * outcome_covered / len(opportunities), 1)
            if opportunities else 0.0
        ),
        "human_review_required": True,
        "automatic_live_change_allowed": False,
    }
    governance["ready_for_human_review"] = all((
        governance["decisive_policy_state_available"],
        governance["call_and_put_representation"],
        governance["multiple_phase_representation"],
        governance["time_of_day_coverage_pct"] >= MINIMUM_OUTCOME_COVERAGE_PCT,
        governance["outcome_coverage_pct"] >= MINIMUM_OUTCOME_COVERAGE_PCT,
    ))

    return {
        "schema_version": MODEL_VERSION,
        "generated_at": datetime.now(EASTERN_TZ).isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "hypothesis": (
            "A direction-aligned, strong-close 20-bar volume policy will produce "
            "more +6% opportunities and less adverse excursion than the current "
            "five-bar +/-1 checklist adjustment."
        ),
        "contrary_evidence_required": True,
        "opportunity_episodes": len(opportunities),
        "today_episodes": len(current),
        "broker_trade_coverage": trade_coverage,
        "today": current,
        "opportunity_policy_cohorts": opportunity_cohorts,
        "broker_policy_cohorts": broker_cohorts,
        "governance": governance,
        "recommendation": (
            "KEEP_LIVE_VOLUME_RULE_UNCHANGED"
            if not governance["ready_for_human_review"]
            else "ELIGIBLE_FOR_HUMAN_REVIEW_ONLY"
        ),
    }


def render_volume_shadow_markdown(payload: dict[str, Any]) -> str:
    governance = payload["governance"]
    lines = [
        "## Volume — Daily Shadow Test",
        "",
        f"- **Recommendation:** {payload['recommendation'].replace('_', ' ').title()}",
        f"- **Falsifiable hypothesis:** {payload['hypothesis']}",
        (
            f"- **Coverage:** {payload['opportunity_episodes']} candidate-direction episodes; "
            f"{payload['today_episodes']} today; outcome coverage "
            f"{governance['outcome_coverage_pct']:.1f}%; time-of-day coverage "
            f"{governance['time_of_day_coverage_pct']:.1f}%."
        ),
        (
            "- **Governance:** At least 20 decisive episodes in each compared policy "
            "state, 80% outcome and time-of-day coverage, CALL and PUT representation, "
            "multiple phases, and human review. No automatic live changes."
        ),
        "",
        "### Alternative Checklist Policies",
        "",
        "| Direction | Policy | State | N | +6% opportunities | -5% risks | Avg MFE | Avg MAE |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["opportunity_policy_cohorts"]:
        lines.append(
            f"| {row['direction']} | {row['policy']} | {row['state']} | "
            f"{row['episodes']} | {row['plus_6_opportunities']} | "
            f"{row['minus_5_risks']} | "
            f"{row['average_outcome'] if row['average_outcome'] is not None else '—'} | "
            f"{row['average_estimated_mae_pct'] if row['average_estimated_mae_pct'] is not None else '—'} |"
        )
    if not payload["opportunity_policy_cohorts"]:
        lines.append("| — | New telemetry begins with the next evaluated candle | — | 0 | — | — | — | — |")

    lines.extend([
        "",
        "### Broker-Backed Executed Trades",
        "",
        "| Direction | Policy | State | N | W-L | Average broker P&L |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for row in payload["broker_policy_cohorts"]:
        lines.append(
            f"| {row['direction']} | {row['policy']} | {row['state']} | "
            f"{row['episodes']} | {row['positive_outcomes']}-{row['negative_outcomes']} | "
            f"{row['average_outcome'] if row['average_outcome'] is not None else '—'} |"
        )
    if not payload["broker_policy_cohorts"]:
        lines.append("| — | New telemetry begins with the next broker-backed trade | — | 0 | — | — |")

    lines.extend([
        "",
        "The five-bar live rule remains unchanged. This worksheet separately tests "
        "no volume adjustment, 20-bar mean, 20-bar median, and a strong-close "
        "20-bar confirmation policy. A prior-session 15-minute time-of-day baseline "
        "is added once at least three earlier sessions are available.",
        "",
    ])
    return "\n".join(lines)


def write_volume_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path]:
    payload = evaluate_volume_shadow(trading_date, root=root)
    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"volume_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        render_volume_shadow_markdown(payload) + "\n",
        encoding="utf-8",
    )
    return payload, json_path, md_path
