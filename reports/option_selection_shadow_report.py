"""Daily evidence report for the spread-aware option selection shadow."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from reports.missed_opportunities_shadow_report import load_opportunity_events


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
SCHEMA_VERSION = "option-selection-shadow-report.v1"
FORWARD_WINDOW_MINUTES = 15
TARGET_RETURN_PCT = 6.0
INITIAL_STOP_RETURN_PCT = -4.0
EPISODE_COOLDOWN_MINUTES = 15
MINIMUM_DECISIVE_DIFFERING_EPISODES = 20
MINIMUM_EXECUTABLE_COVERAGE_PCT = 80.0


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN_TZ)
    return parsed.astimezone(EASTERN_TZ)


def _phase(event: dict[str, Any]) -> str:
    value = event.get("stage")
    if isinstance(value, dict):
        value = value.get("label") or value.get("stage")
    return str(value or "UNKNOWN").upper()


def _load_events_through(
    trading_date: str,
    *,
    root: Path,
) -> list[dict[str, Any]]:
    log_dir = root / "data" / "reports" / "opportunity_logs"
    selected: dict[str, dict[str, Any]] = {}
    for path in sorted(log_dir.glob("opportunity_setups_*.jsonl")):
        report_date = path.stem.removeprefix("opportunity_setups_")
        if report_date > trading_date:
            continue
        for event in load_opportunity_events(report_date, root=root):
            key = f"{report_date}|{event.get('event_id')}"
            selected[key] = event
    return sorted(
        selected.values(),
        key=lambda row: (
            _parse_time(row.get("candle_time_et"))
            or datetime.min.replace(tzinfo=EASTERN_TZ),
            str(row.get("direction") or ""),
        ),
    )


def _quote_timelines(
    events: list[dict[str, Any]],
) -> dict[str, list[tuple[datetime, float]]]:
    timelines: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for event in events:
        at = _parse_time(event.get("candle_time_et"))
        if at is None:
            continue
        snapshots = [
            event.get("option_quote_snapshot"),
            *(event.get("option_watch_quotes") or []),
        ]
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            symbol = str(snapshot.get("symbol") or "").strip()
            bid = _number(snapshot.get("bid"))
            if symbol and bid is not None and bid > 0:
                timelines[symbol].append((at, bid))
    for rows in timelines.values():
        rows[:] = sorted(set(rows), key=lambda row: row[0])
    return timelines


def _contract_outcome(
    *,
    at: datetime | None,
    snapshot: dict[str, Any],
    timelines: dict[str, list[tuple[datetime, float]]],
) -> dict[str, Any]:
    symbol = str(snapshot.get("symbol") or "").strip()
    ask = _number(snapshot.get("ask"))
    spread = _number(snapshot.get("spread"))
    if spread is None:
        bid = _number(snapshot.get("bid"))
        spread = ask - bid if ask is not None and bid is not None else None
    base = {
        "symbol": symbol or None,
        "entry_ask": ask,
        "entry_spread": round(spread, 4) if spread is not None else None,
        "entry_spread_pct": _number(snapshot.get("spread_pct")),
    }
    if at is None or not symbol or ask is None or ask <= 0:
        return {
            **base,
            "executable": False,
            "future_bid_count": 0,
            "mfe_pct": None,
            "mae_pct": None,
            "first_passage": None,
        }
    future = [
        (quote_at, bid)
        for quote_at, bid in timelines.get(symbol, [])
        if at < quote_at <= at + timedelta(minutes=FORWARD_WINDOW_MINUTES)
    ]
    returns = [
        (quote_at, ((bid - ask) / ask) * 100.0)
        for quote_at, bid in future
    ]
    if not returns:
        return {
            **base,
            "executable": False,
            "future_bid_count": 0,
            "mfe_pct": None,
            "mae_pct": None,
            "first_passage": None,
        }
    target = next((row for row in returns if row[1] >= TARGET_RETURN_PCT), None)
    stop = next((row for row in returns if row[1] <= INITIAL_STOP_RETURN_PCT), None)
    if target and (not stop or target[0] < stop[0]):
        first_passage = "TARGET_BEFORE_STOP"
    elif stop and (not target or stop[0] <= target[0]):
        first_passage = "STOP_BEFORE_TARGET"
    else:
        first_passage = "NEITHER"
    return {
        **base,
        "executable": True,
        "future_bid_count": len(returns),
        "mfe_pct": round(max(value for _, value in returns), 4),
        "mae_pct": round(min(value for _, value in returns), 4),
        "first_passage": first_passage,
    }


def evaluate_option_selection_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    timelines = _quote_timelines(events)
    rows: list[dict[str, Any]] = []
    for event in events:
        shadow = event.get("option_selection_shadow")
        if not isinstance(shadow, dict) or not shadow.get("valid"):
            continue
        live_snapshot = shadow.get("live_selection")
        if not isinstance(live_snapshot, dict):
            live_snapshot = event.get("option_quote_snapshot")
        shadow_snapshot = shadow.get("shadow_selection")
        if not isinstance(live_snapshot, dict) or not isinstance(shadow_snapshot, dict):
            continue
        at = _parse_time(event.get("candle_time_et"))
        live_outcome = _contract_outcome(
            at=at,
            snapshot=live_snapshot,
            timelines=timelines,
        )
        shadow_outcome = _contract_outcome(
            at=at,
            snapshot=shadow_snapshot,
            timelines=timelines,
        )
        both_executable = bool(
            live_outcome["executable"] and shadow_outcome["executable"]
        )
        mfe_delta = (
            round(shadow_outcome["mfe_pct"] - live_outcome["mfe_pct"], 4)
            if both_executable
            else None
        )
        if not both_executable:
            comparison = "INSUFFICIENT_EXECUTABLE_EVIDENCE"
        elif shadow_outcome["first_passage"] == "TARGET_BEFORE_STOP" and (
            live_outcome["first_passage"] != "TARGET_BEFORE_STOP"
        ):
            comparison = "SHADOW_BETTER"
        elif live_outcome["first_passage"] == "TARGET_BEFORE_STOP" and (
            shadow_outcome["first_passage"] != "TARGET_BEFORE_STOP"
        ):
            comparison = "LIVE_BETTER"
        elif mfe_delta is not None and mfe_delta >= 0.5:
            comparison = "SHADOW_BETTER"
        elif mfe_delta is not None and mfe_delta <= -0.5:
            comparison = "LIVE_BETTER"
        else:
            comparison = "SIMILAR"
        rows.append({
            "event_id": event.get("event_id"),
            "candidate_time_et": at.isoformat() if at else event.get("candle_time_et"),
            "trading_date": at.date().isoformat() if at else None,
            "direction": str(event.get("direction") or "UNKNOWN").upper(),
            "phase": _phase(event),
            "entered_live": bool(event.get("entered")),
            "selection_differs": bool(shadow.get("selection_differs")),
            "liquidity_tier": shadow.get("liquidity_tier"),
            "estimated_spread_saving_per_contract": _number(
                shadow.get("estimated_spread_saving_per_contract")
            ),
            "estimated_spread_saving_total": _number(
                shadow.get("estimated_spread_saving_total")
            ),
            "stability_evidence_ready": bool(shadow.get("stability_evidence_ready")),
            "live": live_outcome,
            "shadow": shadow_outcome,
            "both_executable": both_executable,
            "mfe_delta_pct_points": mfe_delta,
            "comparison": comparison,
        })
    return rows


def _canonical_differing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    last_by_direction: dict[str, datetime] = {}
    for row in rows:
        if not row["selection_differs"]:
            continue
        at = _parse_time(row.get("candidate_time_et"))
        direction = row["direction"]
        if at is None:
            continue
        previous = last_by_direction.get(direction)
        if previous and at <= previous + timedelta(minutes=EPISODE_COOLDOWN_MINUTES):
            continue
        canonical.append({**row, "canonical_episode": True})
        last_by_direction[direction] = at
    return canonical


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    executable = [row for row in rows if row["both_executable"]]
    savings = [
        row["estimated_spread_saving_total"]
        for row in rows
        if row["estimated_spread_saving_total"] is not None
    ]
    deltas = [
        row["mfe_delta_pct_points"]
        for row in executable
        if row["mfe_delta_pct_points"] is not None
    ]
    return {
        "episodes": len(rows),
        "executable_episodes": len(executable),
        "executable_coverage_pct": (
            round(100.0 * len(executable) / len(rows), 1) if rows else 0.0
        ),
        "shadow_better": sum(row["comparison"] == "SHADOW_BETTER" for row in executable),
        "live_better_contrary_evidence": sum(
            row["comparison"] == "LIVE_BETTER" for row in executable
        ),
        "similar": sum(row["comparison"] == "SIMILAR" for row in executable),
        "shadow_target_before_stop": sum(
            row["shadow"]["first_passage"] == "TARGET_BEFORE_STOP"
            for row in executable
        ),
        "live_target_before_stop": sum(
            row["live"]["first_passage"] == "TARGET_BEFORE_STOP"
            for row in executable
        ),
        "median_estimated_spread_saving_total": (
            round(median(savings), 2) if savings else None
        ),
        "average_shadow_minus_live_mfe_pct_points": (
            round(mean(deltas), 4) if deltas else None
        ),
    }


def evaluate_option_selection_shadow(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    events = _load_events_through(trading_date, root=root)
    evaluated = evaluate_option_selection_events(events)
    canonical = _canonical_differing(evaluated)
    current = [row for row in evaluated if row["trading_date"] == trading_date]
    current_differing = [row for row in current if row["selection_differs"]]
    canonical_summary = _summary(canonical)
    directions = {row["direction"] for row in canonical}
    phases = {row["phase"] for row in canonical if row["phase"] != "UNKNOWN"}
    stability_coverage = (
        round(
            100.0 * sum(row["stability_evidence_ready"] for row in canonical)
            / len(canonical),
            1,
        )
        if canonical else 0.0
    )
    governance = {
        "minimum_decisive_differing_episodes": MINIMUM_DECISIVE_DIFFERING_EPISODES,
        "minimum_executable_coverage_pct": MINIMUM_EXECUTABLE_COVERAGE_PCT,
        "canonical_differing_episodes": len(canonical),
        "executable_coverage_pct": canonical_summary["executable_coverage_pct"],
        "quote_stability_coverage_pct": stability_coverage,
        "call_and_put_representation": {"CALL", "PUT"}.issubset(directions),
        "multiple_phase_representation": len(phases) >= 2,
        "exact_broker_reconciliation_required_before_live_change": True,
        "human_review_required": True,
        "automatic_live_change_allowed": False,
    }
    governance["ready_for_human_review"] = all((
        len(canonical) >= MINIMUM_DECISIVE_DIFFERING_EPISODES,
        canonical_summary["executable_coverage_pct"]
        >= MINIMUM_EXECUTABLE_COVERAGE_PCT,
        stability_coverage >= MINIMUM_EXECUTABLE_COVERAGE_PCT,
        governance["call_and_put_representation"],
        governance["multiple_phase_representation"],
    ))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(EASTERN_TZ).isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "hypothesis": (
            "Among contracts that already pass every live eligibility filter, "
            "ranking spread tightness, liquidity, quote stability, and strike "
            "proximity will reduce execution cost without reducing the rate of "
            "+6% before -4% executable outcomes."
        ),
        "today_all_captured": _summary(current),
        "today_differing_selections": _summary(current_differing),
        "rolling_canonical_differing": canonical_summary,
        "today_rows": current,
        "governance": governance,
        "contrary_evidence": (
            f"The live highest-volume selection beat the shadow selection in "
            f"{canonical_summary['live_better_contrary_evidence']} executable "
            "canonical episodes."
        ),
        "recommendation": (
            "ELIGIBLE_FOR_HUMAN_REVIEW_ONLY"
            if governance["ready_for_human_review"]
            else "KEEP_LIVE_HIGHEST_VOLUME_RANKING_UNCHANGED"
        ),
    }


def _fmt(value: Any, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def render_option_selection_shadow_markdown(payload: dict[str, Any]) -> str:
    today = payload["today_differing_selections"]
    rolling = payload["rolling_canonical_differing"]
    governance = payload["governance"]
    lines = [
        "## Option Selection — Spread-Aware Shadow Ranking",
        "",
        f"- **Recommendation:** {payload['recommendation'].replace('_', ' ').title()}",
        f"- **Falsifiable hypothesis:** {payload['hypothesis']}",
        (
            f"- **Today:** {today['episodes']} differing selections; "
            f"{today['executable_coverage_pct']:.1f}% executable comparison coverage; "
            f"median estimated eight-contract spread saving "
            f"${_fmt(today['median_estimated_spread_saving_total'])}."
        ),
        (
            f"- **Rolling canonical sample:** {rolling['episodes']} differing episodes; "
            f"shadow better {rolling['shadow_better']}, live better "
            f"{rolling['live_better_contrary_evidence']}, similar {rolling['similar']}; "
            f"shadow/live +6%-before--4% outcomes "
            f"{rolling['shadow_target_before_stop']}/{rolling['live_target_before_stop']}."
        ),
        f"- **Contrary evidence:** {payload['contrary_evidence']}",
        (
            "- **Governance:** Keep live selection unchanged until at least 20 "
            "canonical differing episodes, 80% executable and quote-stability "
            "coverage, CALL and PUT representation, multiple phases, exact broker "
            "reconciliation, and human review."
        ),
        "",
        "### Today's Contract Comparisons",
        "",
        "| Time ET | Dir | Phase | Live | Shadow | Est. spread saving (8) | Live MFE | Shadow MFE | Evidence |",
        "|---|---|---|---|---|---:|---:|---:|---|",
    ]
    differing_rows = [
        row for row in payload["today_rows"] if row["selection_differs"]
    ]
    for row in differing_rows:
        at = _parse_time(row.get("candidate_time_et"))
        lines.append(
            f"| {at.strftime('%H:%M') if at else '—'} | {row['direction']} | "
            f"{row['phase']} | {row['live']['symbol'] or '—'} | "
            f"{row['shadow']['symbol'] or '—'} | "
            f"${_fmt(row['estimated_spread_saving_total'])} | "
            f"{_fmt(row['live']['mfe_pct'], '%')} | "
            f"{_fmt(row['shadow']['mfe_pct'], '%')} | "
            f"{row['comparison'].replace('_', ' ').title()} |"
        )
    if not differing_rows:
        lines.append(
            "| — | — | New telemetry begins with the next evaluated setup | — | — | — | — | — | — |"
        )
    lines.extend([
        "",
        (
            "The shadow score is 45% spread tightness, 25% liquidity, 20% quote "
            "stability, and 10% strike proximity. Only contracts already eligible "
            "under the live expiration, quote, spread, volume/open-interest rules "
            "are compared. Entry uses the contemporaneous ask and exit evidence "
            "uses subsequent executable bids; no midpoint fills are assumed."
        ),
        "",
    ])
    return "\n".join(lines)


def write_option_selection_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path]:
    payload = evaluate_option_selection_shadow(trading_date, root=root)
    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"option_selection_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        render_option_selection_shadow_markdown(payload) + "\n",
        encoding="utf-8",
    )
    return payload, json_path, md_path
