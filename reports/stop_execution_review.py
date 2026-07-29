"""Daily broker-protection and trailing-stop reliability review."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
SCHEMA_VERSION = "stop-execution-review.v1"
MINIMUM_TRADES = 20
MINIMUM_TRANSITIONS = 50
MAX_ACCEPTANCE_LATENCY_SECONDS = 3.0


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def load_stop_events(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> list[dict[str, Any]]:
    path = (
        root / "data" / "reports" / "stop_telemetry"
        / f"protective_stop_events_{trading_date}.jsonl"
    )
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            events.append(row)
    return events


def _trade_key(event: dict[str, Any]) -> str | None:
    key = str(event.get("trade_key") or "").strip()
    return key or None


def _attach_unkeyed_events(
    events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Associate legacy submission events with the only matching live trade."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    keys_by_symbol: dict[str, list[str]] = defaultdict(list)
    for event in events:
        key = _trade_key(event)
        if not key:
            continue
        grouped[key].append(event)
        symbol = str(event.get("option_symbol") or key.split(":", 1)[0])
        if key not in keys_by_symbol[symbol]:
            keys_by_symbol[symbol].append(key)

    for event in events:
        if _trade_key(event):
            continue
        symbol = str(event.get("option_symbol") or "")
        candidates = keys_by_symbol.get(symbol) or []
        if len(candidates) == 1:
            grouped[candidates[0]].append(event)
    for rows in grouped.values():
        rows.sort(key=lambda row: str(row.get("recorded_at") or ""))
    return {
        key: rows
        for key, rows in grouped.items()
        if any(
            event.get("event_type") == "option_quote_observed"
            and (_number(event.get("bid")) or 0.0) > 0
            for event in rows
        )
    }


def _trade_summary(trade_key: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    types = Counter(str(event.get("event_type") or "UNKNOWN") for event in events)
    quotes = [
        event for event in events
        if event.get("event_type") == "option_quote_observed"
    ]
    decisions = [
        event for event in events
        if event.get("event_type") == "stop_management_decision"
    ]
    update_decisions = [
        event for event in decisions
        if str(event.get("action") or "") == "UPDATE_STOP"
    ]
    submissions = [
        event for event in events
        if event.get("event_type") == "protective_stop_submitted"
    ]
    verified = [
        event for event in events
        if event.get("event_type") == "stop_ratchet_broker_verified"
    ]
    ratchet_failures = [
        event for event in events
        if event.get("event_type") == "stop_ratchet_submission_failed"
    ]
    protective_submission_failures = [
        event for event in events
        if event.get("event_type") == "protective_stop_submission_failed"
    ]
    deferred = [
        event for event in events
        if event.get("event_type") == "stop_ratchet_deferred"
    ]
    terminal = [
        event for event in events
        if event.get("event_type") == "protective_stop_known_order_terminal"
    ]
    recovered = [
        event for event in events
        if event.get("event_type") == "protective_stop_identity_recovered"
    ]
    missing = [
        event for event in decisions
        if str(event.get("action") or "") == "RESTORE_PROTECTIVE_STOP"
    ]
    response_texts = [
        str(event.get("response_text") or event.get("error") or "")
        for event in protective_submission_failures
    ]
    deferred_reasons = Counter(
        reason
        for event in deferred
        for reason in (event.get("deferral_reasons") or [])
    )
    desired_stops = [
        value
        for value in (
            _number(event.get("candidate_stop"))
            or _number(event.get("desired_stop"))
            for event in [*update_decisions, *events]
        )
        if value is not None
    ]
    submitted_stops = [
        value
        for value in (_number(event.get("stop_price")) for event in submissions)
        if value is not None
    ]
    bids = [
        value
        for value in (_number(event.get("bid")) for event in quotes)
        if value is not None
    ]
    lag_values = [
        value
        for value in (
            _number(event.get("ratchet_lag_dollars")) for event in decisions
        )
        if value is not None
    ]
    latencies = [
        value
        for value in (
            _number(event.get("submission_latency_ms")) for event in events
            if event.get("event_type")
            == "stop_ratchet_submission_accepted_pending_verification"
        )
        if value is not None
    ]
    replacement_rejections = sum(
        "status REJECTED" in text or "400 Bad Request" in text
        for text in response_texts
    )
    rate_limit_failures = sum(
        "rate-limit" in text.lower() or "429" in text for text in response_texts
    )
    issues = []
    if replacement_rejections:
        issues.append("BROKER_REJECTED_REPLACEMENT")
    if recovered:
        issues.append("STALE_REPLACEMENT_ID_RECOVERED")
    if rate_limit_failures:
        issues.append("BROKER_RATE_LIMIT")
    if ratchet_failures or protective_submission_failures:
        issues.append("RATCHET_SUBMISSION_FAILURE")
    if missing:
        issues.append("PROTECTIVE_STOP_MISSING_OR_TERMINAL")
    return {
        "trade_key": trade_key,
        "option_symbol": trade_key.split(":", 1)[0],
        "first_event_at": events[0].get("recorded_at") if events else None,
        "last_event_at": events[-1].get("recorded_at") if events else None,
        "quote_observations": len(quotes),
        "update_decisions": len(update_decisions),
        "broker_stop_submissions": len(submissions),
        "broker_verified_ratchets": len(verified),
        "ratchet_failures": len(ratchet_failures),
        "protective_submission_failures": len(protective_submission_failures),
        "replacement_rejections": replacement_rejections,
        "rate_limit_failures": rate_limit_failures,
        "identity_recoveries": len(recovered),
        "terminal_known_orders": len(terminal),
        "protective_stop_missing_decisions": len(missing),
        "deferred_updates": len(deferred),
        "deferred_reasons": dict(deferred_reasons),
        "highest_executable_bid": max(bids) if bids else None,
        "highest_desired_stop": max(desired_stops) if desired_stops else None,
        "highest_submitted_stop": max(submitted_stops) if submitted_stops else None,
        "maximum_recorded_ratchet_lag_dollars": max(lag_values) if lag_values else None,
        "maximum_submission_latency_ms": max(latencies) if latencies else None,
        "issues": issues,
        "status": "HEALTHY" if not issues else "REVIEW_REQUIRED",
        "event_type_counts": dict(types),
    }


def build_stop_execution_review(
    events: list[dict[str, Any]],
    *,
    trading_date: str,
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    grouped = _attach_unkeyed_events(events)
    trades = [
        _trade_summary(trade_key, rows)
        for trade_key, rows in sorted(grouped.items())
    ]
    transitions = sum(trade["broker_stop_submissions"] for trade in trades)
    failures = sum(trade["ratchet_failures"] for trade in trades)
    protective_failures = sum(
        trade["protective_submission_failures"] for trade in trades
    )
    rejected = sum(trade["replacement_rejections"] for trade in trades)
    recoveries = sum(trade["identity_recoveries"] for trade in trades)
    missing = sum(trade["protective_stop_missing_decisions"] for trade in trades)
    verified = sum(trade["broker_verified_ratchets"] for trade in trades)
    prospective_submissions = sum(
        int((trade.get("event_type_counts") or {}).get(
            "stop_ratchet_submission_accepted_pending_verification", 0
        ))
        for trade in trades
    )
    verification_rate = (
        verified / prospective_submissions if prospective_submissions else None
    )
    checks = {
        "canonical_reconciliation_complete": bool(reconciliation.get("complete")),
        "minimum_20_trades_or_50_transitions": (
            len(trades) >= MINIMUM_TRADES or transitions >= MINIMUM_TRANSITIONS
        ),
        "zero_rejected_replacements": rejected == 0,
        "zero_ratchet_submission_failures": failures == 0,
        "zero_protective_submission_failures": protective_failures == 0,
        "zero_protection_missing_decisions": missing == 0,
        "zero_identity_recoveries": recoveries == 0,
        "broker_verification_rate_at_least_95_pct": (
            verification_rate is not None and verification_rate >= 0.95
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "trading_date": trading_date,
        "automatic_strategy_change_allowed": False,
        "trades": trades,
        "summary": {
            "trades_observed": len(trades),
            "broker_stop_submissions": transitions,
            "ratchet_failures": failures,
            "protective_submission_failures": protective_failures,
            "replacement_rejections": rejected,
            "identity_recoveries": recoveries,
            "protective_stop_missing_decisions": missing,
            "prospective_ratchet_submissions": prospective_submissions,
            "broker_verified_ratchets": verified,
            "broker_verification_rate": (
                round(verification_rate, 4)
                if verification_rate is not None else None
            ),
        },
        "gate": {
            "checks": checks,
            "decision": (
                "RELIABILITY_GATE_PASSED"
                if all(checks.values())
                else "COLLECT_AND_REPAIR"
            ),
        },
        "reconciliation": reconciliation,
        "conclusions_withheld": not bool(reconciliation.get("complete")),
    }


def render_stop_execution_markdown(payload: dict[str, Any]) -> str:
    def money(value: Any) -> str:
        number = _number(value)
        return f"${number:.2f}" if number is not None else "N/A"

    summary = payload.get("summary") or {}
    lines = [
        "## Protective Stop and Ratchet Reliability",
        "",
        f"- Trades observed: **{summary.get('trades_observed', 0)}**; "
        f"broker stop submissions: **{summary.get('broker_stop_submissions', 0)}**.",
        f"- Ratchet failures: **{summary.get('ratchet_failures', 0)}**; "
        f"rejected replacements: **{summary.get('replacement_rejections', 0)}**; "
        f"identity recoveries: **{summary.get('identity_recoveries', 0)}**.",
        "- The 4% tier is a 1%-behind-high synthetic trail armed after +4%; the report distinguishes desired, submitted, and broker-verified stops.",
        "",
        "| Trade | Quotes | Updates | Submitted | Verified | Highest Bid | Highest Desired Stop | Highest Submitted Stop | Failures | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for trade in payload.get("trades") or []:
        lines.append(
            f"| {trade.get('trade_key')} | {trade.get('quote_observations', 0)} "
            f"| {trade.get('update_decisions', 0)} "
            f"| {trade.get('broker_stop_submissions', 0)} "
            f"| {trade.get('broker_verified_ratchets', 0)} "
            f"| {money(trade.get('highest_executable_bid'))} "
            f"| {money(trade.get('highest_desired_stop'))} "
            f"| {money(trade.get('highest_submitted_stop'))} "
            f"| {trade.get('ratchet_failures', 0)} | {trade.get('status')} |"
        )
    if not payload.get("trades"):
        lines.append("| — | 0 | 0 | 0 | 0 | N/A | N/A | N/A | 0 | No trades |")
    lines.extend([
        "",
        f"### Reliability Gate: **{(payload.get('gate') or {}).get('decision')}**",
        "",
    ])
    for name, passed in ((payload.get("gate") or {}).get("checks") or {}).items():
        lines.append(f"- {'PASS' if passed else 'WAIT'} — {name}")
    lines.append("")
    return "\n".join(lines)


def write_stop_execution_review(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path]:
    reconciliation_path = (
        root / "reports" / "daily_loss_attribution"
        / f"daily_loss_attribution_{trading_date}.json"
    )
    try:
        reconciliation = (
            json.loads(reconciliation_path.read_text(encoding="utf-8"))
            .get("reconciliation") or {}
        )
    except (OSError, ValueError, json.JSONDecodeError):
        reconciliation = {}
    payload = build_stop_execution_review(
        load_stop_events(trading_date, root=root),
        trading_date=trading_date,
        reconciliation=reconciliation,
    )
    payload["generated_at"] = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")
    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"stop_execution_review_{trading_date}.json"
    md_path = report_dir / f"stop_execution_review_{trading_date}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_stop_execution_markdown(payload) + "\n", encoding="utf-8")
    return payload, json_path, md_path
