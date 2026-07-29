"""Research-only comparison of broad session trend entry policies."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from reports.entry_quality_shadow_report import load_study_trades
from reports.missed_opportunities_shadow_report import load_opportunity_events


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
SCHEMA_VERSION = "market-trend-shadow.v1"
FRESH_START_DATE = "2026-07-29"
FORWARD_WINDOW_MINUTES = 15
TARGET_RETURN_PCT = 6.0
INITIAL_STOP_RETURN_PCT = -3.0
EPISODE_COOLDOWN_MINUTES = 15
MINIMUM_RELATIONSHIP_EPISODES = 20
MINIMUM_EXECUTABLE_COVERAGE = 0.80
RELATIONSHIPS = ("ALIGNED", "NEUTRAL", "OPPOSED")


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN_TZ)
    return parsed.astimezone(EASTERN_TZ)


def _quote_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("option_quote_snapshot")
    return value if isinstance(value, dict) else {}


def _quote_timelines(
    events: list[dict[str, Any]],
) -> dict[str, list[tuple[datetime, float]]]:
    timelines: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for event in events:
        at = _parse_time(event.get("candle_time_et"))
        if at is None:
            continue
        snapshots = [_quote_snapshot(event), *(event.get("option_watch_quotes") or [])]
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


def _relationship(event: dict[str, Any]) -> str:
    captured = str(event.get("session_trend_relationship") or "").upper()
    if captured in {*RELATIONSHIPS, "UNKNOWN"}:
        return captured
    direction = str(event.get("direction") or "").upper()
    trend = str(event.get("session_market_trend") or "UNKNOWN").upper()
    expected = "BULL_TREND" if direction == "CALL" else "BEAR_TREND"
    opposed = "BEAR_TREND" if direction == "CALL" else "BULL_TREND"
    if trend == expected:
        return "ALIGNED"
    if trend == "NEUTRAL":
        return "NEUTRAL"
    if trend == opposed:
        return "OPPOSED"
    return "UNKNOWN"


def _qualified(event: dict[str, Any]) -> bool:
    research = event.get("research")
    if isinstance(research, dict) and "current_engine_qualified" in research:
        return bool(research.get("current_engine_qualified"))
    direction = str(event.get("direction") or "").upper()
    regime = str(event.get("market_regime") or "").upper()
    score = _number(event.get("score")) or 0.0
    required = "BULL_TREND" if direction == "CALL" else "BEAR_TREND"
    return regime == required and score >= float(event.get("entry_threshold") or 5)


def _actual_trade_match(
    event: dict[str, Any],
    broker_trades: list[dict[str, Any]],
) -> dict[str, Any] | None:
    event_time = _parse_time(event.get("candle_time_et"))
    direction = str(event.get("direction") or "").upper()
    if event_time is None:
        return None
    candidates = []
    for trade in broker_trades:
        if str(trade.get("direction") or "").upper() != direction:
            continue
        entry_time = _parse_time(trade.get("entry_time"))
        if entry_time is None:
            continue
        distance = abs((entry_time - event_time).total_seconds())
        if distance <= 120:
            candidates.append((distance, trade))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def evaluate_market_trend_candidates(
    events: list[dict[str, Any]],
    *,
    broker_trades: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate every otherwise-qualified completed-candle setup."""
    timelines = _quote_timelines(events)
    broker_trades = list(broker_trades or [])
    evaluated: list[dict[str, Any]] = []
    for event in events:
        if not _qualified(event):
            continue
        at = _parse_time(event.get("candle_time_et"))
        snapshot = _quote_snapshot(event)
        symbol = str(snapshot.get("symbol") or event.get("option_selected") or "").strip()
        entry_ask = _number(snapshot.get("ask"))
        relationship = _relationship(event)
        base = {
            "event_id": event.get("event_id"),
            "candidate_time_et": at.isoformat() if at else event.get("candle_time_et"),
            "direction": str(event.get("direction") or "UNKNOWN").upper(),
            "entry_regime": str(event.get("market_regime") or "UNKNOWN").upper(),
            "session_market_trend": str(
                event.get("session_market_trend") or "UNKNOWN"
            ).upper(),
            "session_trend_relationship": relationship,
            "session_market_trend_snapshot": (
                event.get("session_market_trend_snapshot")
                if isinstance(event.get("session_market_trend_snapshot"), dict)
                else {}
            ),
            "phase": str(
                (event.get("stage") or {}).get("label")
                if isinstance(event.get("stage"), dict)
                else event.get("stage") or "UNKNOWN"
            ).upper(),
            "checklist_score": _number(event.get("score")),
            "cq": _number(
                (event.get("cq") or {}).get("score")
                if isinstance(event.get("cq"), dict)
                else event.get("cq")
            ),
            "mas": _number(
                (event.get("mas") or {}).get("score")
                if isinstance(event.get("mas"), dict)
                else event.get("mas")
            ),
            "abs": _number(
                (event.get("absorption_score") or {}).get("score")
                if isinstance(event.get("absorption_score"), dict)
                else event.get("absorption_score")
            ),
            "conf": _number(
                (event.get("confidence") or {}).get("score")
                if isinstance(event.get("confidence"), dict)
                else event.get("confidence")
            ),
            "entered_live": bool(event.get("entered")),
            "option_symbol": symbol or None,
            "entry_executable_ask": entry_ask,
            "policy_would_admit": {
                "CURRENT_BASELINE": True,
                "ALIGNED_OR_NEUTRAL": relationship in {"ALIGNED", "NEUTRAL"},
                "ALIGNED_ONLY": relationship == "ALIGNED",
            },
        }
        matched_trade = _actual_trade_match(event, broker_trades) if event.get("entered") else None
        base["actual_broker_pnl_dollars"] = (
            _number(matched_trade.get("pnl_dollars")) if matched_trade else None
        )
        base["actual_broker_entry_order_id"] = (
            matched_trade.get("broker_entry_order_id") if matched_trade else None
        )
        if (
            at is None
            or relationship == "UNKNOWN"
            or not symbol
            or entry_ask is None
            or entry_ask <= 0
        ):
            evaluated.append({
                **base,
                "classification": "INSUFFICIENT_EVIDENCE",
                "evidence_gap": (
                    "entry-time session trend not captured"
                    if relationship == "UNKNOWN"
                    else "missing executable option ask"
                ),
                "future_quote_count": 0,
                "mfe_pct": None,
                "mae_pct": None,
                "first_passage": None,
            })
            continue

        end = at + timedelta(minutes=FORWARD_WINDOW_MINUTES)
        future = [
            (quote_time, bid)
            for quote_time, bid in timelines.get(symbol, [])
            if at < quote_time <= end
        ]
        returns = [
            (quote_time, ((bid - entry_ask) / entry_ask) * 100.0)
            for quote_time, bid in future
        ]
        target_hit = next(
            ((quote_time, value) for quote_time, value in returns if value >= TARGET_RETURN_PCT),
            None,
        )
        stop_hit = next(
            ((quote_time, value) for quote_time, value in returns if value <= INITIAL_STOP_RETURN_PCT),
            None,
        )
        if not returns:
            classification = "INSUFFICIENT_EVIDENCE"
            first_passage = None
            gap = "no subsequent executable bids for the same contract"
        elif target_hit and (not stop_hit or target_hit[0] < stop_hit[0]):
            classification = "TARGET_BEFORE_STOP"
            first_passage = "TARGET_BEFORE_STOP"
            gap = None
        elif stop_hit and (not target_hit or stop_hit[0] <= target_hit[0]):
            classification = "STOP_BEFORE_TARGET"
            first_passage = "STOP_BEFORE_TARGET"
            gap = None
        else:
            classification = "NO_DECISIVE_MOVE"
            first_passage = "NEITHER_TARGET_NOR_STOP"
            gap = None
        evaluated.append({
            **base,
            "classification": classification,
            "evidence_gap": gap,
            "future_quote_count": len(returns),
            "mfe_pct": round(max((value for _, value in returns), default=0.0), 4)
            if returns else None,
            "mae_pct": round(min((value for _, value in returns), default=0.0), 4)
            if returns else None,
            "first_passage": first_passage,
        })
    return evaluated


def canonicalize_relationship_episodes(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    last_by_key: dict[tuple[str, str], datetime] = {}
    for row in sorted(
        rows,
        key=lambda item: _parse_time(item.get("candidate_time_et"))
        or datetime.min.replace(tzinfo=EASTERN_TZ),
    ):
        if row.get("classification") == "INSUFFICIENT_EVIDENCE":
            continue
        at = _parse_time(row.get("candidate_time_et"))
        if at is None:
            continue
        key = (
            str(row.get("direction") or "UNKNOWN"),
            str(row.get("session_trend_relationship") or "UNKNOWN"),
        )
        previous = last_by_key.get(key)
        if previous and at <= previous + timedelta(minutes=EPISODE_COOLDOWN_MINUTES):
            continue
        canonical.append({**row, "canonical_episode": True})
        last_by_key[key] = at
    return canonical


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    covered = [
        row for row in rows
        if row.get("classification") != "INSUFFICIENT_EVIDENCE"
    ]
    mfes = [float(row["mfe_pct"]) for row in covered if row.get("mfe_pct") is not None]
    maes = [float(row["mae_pct"]) for row in covered if row.get("mae_pct") is not None]
    broker_pnls = [
        float(row["actual_broker_pnl_dollars"])
        for row in rows
        if row.get("actual_broker_pnl_dollars") is not None
    ]
    return {
        "candidates": len(rows),
        "executable_outcomes": len(covered),
        "target_before_stop": sum(
            row.get("classification") == "TARGET_BEFORE_STOP" for row in covered
        ),
        "stop_before_target": sum(
            row.get("classification") == "STOP_BEFORE_TARGET" for row in covered
        ),
        "no_decisive_move": sum(
            row.get("classification") == "NO_DECISIVE_MOVE" for row in covered
        ),
        "target_precision": round(
            sum(row.get("classification") == "TARGET_BEFORE_STOP" for row in covered)
            / len(covered),
            4,
        ) if covered else None,
        "average_mfe_pct": round(mean(mfes), 4) if mfes else None,
        "average_mae_pct": round(mean(maes), 4) if maes else None,
        "actual_broker_trades": len(broker_pnls),
        "actual_broker_pnl_dollars": round(sum(broker_pnls), 2),
        "directions": {
            direction: sum(row.get("direction") == direction for row in rows)
            for direction in ("CALL", "PUT")
        },
    }


def build_market_trend_shadow_payload(
    events: list[dict[str, Any]],
    *,
    broker_trades: list[dict[str, Any]],
    trading_date: str,
    reconciliation: dict[str, Any],
    historical_episodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evaluated = evaluate_market_trend_candidates(
        events,
        broker_trades=broker_trades,
    )
    today_episodes = canonicalize_relationship_episodes(evaluated)
    rolling_episodes = list(historical_episodes or []) + today_episodes
    relationship_stats = {
        relationship: _stats([
            row for row in rolling_episodes
            if row.get("session_trend_relationship") == relationship
        ])
        for relationship in RELATIONSHIPS
    }
    policy_stats = {
        policy: _stats([
            row for row in rolling_episodes
            if bool((row.get("policy_would_admit") or {}).get(policy))
        ])
        for policy in ("CURRENT_BASELINE", "ALIGNED_OR_NEUTRAL", "ALIGNED_ONLY")
    }
    captured_relationship = [
        row for row in evaluated
        if row.get("session_trend_relationship") in RELATIONSHIPS
    ]
    executable = [
        row for row in captured_relationship
        if row.get("classification") != "INSUFFICIENT_EVIDENCE"
    ]
    coverage = (
        len(executable) / len(captured_relationship)
        if captured_relationship else 0.0
    )
    checks = {
        "canonical_reconciliation_complete": bool(reconciliation.get("complete")),
        "minimum_executable_coverage_80_pct": coverage >= MINIMUM_EXECUTABLE_COVERAGE,
        **{
            f"{relationship.lower()}_minimum_20_episodes": (
                relationship_stats[relationship]["executable_outcomes"]
                >= MINIMUM_RELATIONSHIP_EPISODES
            )
            for relationship in RELATIONSHIPS
        },
        **{
            f"{relationship.lower()}_has_call_and_put": all(
                relationship_stats[relationship]["directions"].get(direction, 0) > 0
                for direction in ("CALL", "PUT")
            )
            for relationship in RELATIONSHIPS
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "trading_date": trading_date,
        "fresh_start_date": FRESH_START_DATE,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "methodology": {
            "candidate": (
                "completed-candle direction satisfying the current entry regime "
                "and score gate before session-trend policy"
            ),
            "entry_evidence": "selected contract executable ask",
            "exit_evidence": "subsequent executable bids for the same contract",
            "target_return_pct": TARGET_RETURN_PCT,
            "initial_stop_return_pct": INITIAL_STOP_RETURN_PCT,
            "forward_window_minutes": FORWARD_WINDOW_MINUTES,
            "episode_cooldown_minutes": EPISODE_COOLDOWN_MINUTES,
            "policies": {
                "CURRENT_BASELINE": "session trend has no admission effect",
                "ALIGNED_OR_NEUTRAL": "reject only opposed session trend",
                "ALIGNED_ONLY": "require entry regime and session trend agreement",
            },
        },
        "today_candidates": evaluated,
        "today_canonical_episodes": today_episodes,
        "rolling_canonical_episodes": rolling_episodes,
        "relationship_stats": relationship_stats,
        "policy_stats": policy_stats,
        "coverage": {
            "otherwise_qualified_candidates": len(evaluated),
            "entry_time_session_trend_captured": len(captured_relationship),
            "executable_outcomes": len(executable),
            "executable_outcome_coverage": round(coverage, 4),
            "legacy_or_missing_session_trend": (
                len(evaluated) - len(captured_relationship)
            ),
        },
        "gate": {
            "minimum_relationship_episodes": MINIMUM_RELATIONSHIP_EPISODES,
            "minimum_executable_coverage": MINIMUM_EXECUTABLE_COVERAGE,
            "checks": checks,
            "decision": (
                "ELIGIBLE_FOR_HUMAN_REVIEW"
                if all(checks.values())
                else "COLLECT_MORE_DATA"
            ),
        },
        "reconciliation": reconciliation,
        "conclusions_withheld": not bool(reconciliation.get("complete")),
    }


def render_market_trend_shadow_markdown(payload: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        number = _number(value)
        return f"{number:.2f}%" if number is not None else "N/A"

    coverage = payload.get("coverage") or {}
    lines = [
        "## Session Market Trend — Entry Shadow Test",
        "",
        "- Research only: session trend does not currently block, resize, or alter a live trade.",
        "- Compares the current baseline with aligned-or-neutral and aligned-only admission policies.",
        f"- Captured entry-time trend: **{coverage.get('entry_time_session_trend_captured', 0)}**/"
        f"**{coverage.get('otherwise_qualified_candidates', 0)}** qualified candidates; "
        f"executable outcome coverage: **{float(coverage.get('executable_outcome_coverage') or 0):.1%}**.",
        "",
    ]
    if payload.get("conclusions_withheld"):
        lines.extend([
            "**Conclusions withheld because broker reconciliation is incomplete.**",
            "",
        ])
    lines.extend([
        "### Relationship Evidence",
        "",
        "| Relationship | Episodes | Target First | Stop First | No Decision | Precision | Avg MFE | Avg MAE | CALL/PUT |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for relationship in RELATIONSHIPS:
        stats = (payload.get("relationship_stats") or {}).get(relationship) or {}
        precision = stats.get("target_precision")
        directions = stats.get("directions") or {}
        lines.append(
            f"| {relationship} | {stats.get('executable_outcomes', 0)} "
            f"| {stats.get('target_before_stop', 0)} | {stats.get('stop_before_target', 0)} "
            f"| {stats.get('no_decisive_move', 0)} "
            f"| {f'{precision:.1%}' if precision is not None else 'N/A'} "
            f"| {pct(stats.get('average_mfe_pct'))} "
            f"| {pct(stats.get('average_mae_pct'))} "
            f"| {directions.get('CALL', 0)}/{directions.get('PUT', 0)} |"
        )
    lines.extend([
        "",
        "### Policy Comparison",
        "",
        "| Policy | Episodes Admitted | Target First | Stop First | Precision | Actual Broker Trades | Actual Broker P&L |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    labels = {
        "CURRENT_BASELINE": "Current baseline",
        "ALIGNED_OR_NEUTRAL": "Aligned or neutral",
        "ALIGNED_ONLY": "Aligned only",
    }
    for policy, stats in (payload.get("policy_stats") or {}).items():
        precision = stats.get("target_precision")
        lines.append(
            f"| {labels.get(policy, policy)} | {stats.get('executable_outcomes', 0)} "
            f"| {stats.get('target_before_stop', 0)} | {stats.get('stop_before_target', 0)} "
            f"| {f'{precision:.1%}' if precision is not None else 'N/A'} "
            f"| {stats.get('actual_broker_trades', 0)} "
            f"| ${float(stats.get('actual_broker_pnl_dollars') or 0):.2f} |"
        )
    lines.extend([
        "",
        f"### Evidence Gate: **{(payload.get('gate') or {}).get('decision')}**",
        "",
    ])
    for name, passed in ((payload.get("gate") or {}).get("checks") or {}).items():
        lines.append(f"- {'PASS' if passed else 'WAIT'} — {name}")
    lines.extend([
        "",
        "- A passing gate permits human review only; it cannot change live admission automatically.",
        "",
    ])
    return "\n".join(lines)


def write_market_trend_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path, Path]:
    events = load_opportunity_events(trading_date, root=root)
    broker_trades, _ = load_study_trades(root=root)
    broker_trades = [
        trade for trade in broker_trades
        if str(trade.get("trade_date") or "") == trading_date
    ]
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
    report_dir = root / "reports" / "daily_trade_learning"
    historical_episodes: list[dict[str, Any]] = []
    for path in sorted(report_dir.glob("market_trend_shadow_????-??-??.json")):
        prior_date = path.stem.removeprefix("market_trend_shadow_")
        if prior_date >= trading_date:
            continue
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        historical_episodes.extend(prior.get("today_canonical_episodes") or [])

    payload = build_market_trend_shadow_payload(
        events,
        broker_trades=broker_trades,
        trading_date=trading_date,
        reconciliation=reconciliation,
        historical_episodes=historical_episodes,
    )
    payload["generated_at"] = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"market_trend_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_market_trend_shadow_markdown(payload) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "event_id", "candidate_time_et", "direction", "entry_regime",
            "session_market_trend", "session_trend_relationship", "phase",
            "checklist_score", "cq", "mas", "abs", "conf", "entered_live",
            "option_symbol", "entry_executable_ask", "classification",
            "mfe_pct", "mae_pct", "actual_broker_pnl_dollars",
            "baseline_admit", "aligned_or_neutral_admit", "aligned_only_admit",
        ])
        for row in payload.get("today_candidates") or []:
            policies = row.get("policy_would_admit") or {}
            writer.writerow([
                row.get("event_id"), row.get("candidate_time_et"),
                row.get("direction"), row.get("entry_regime"),
                row.get("session_market_trend"),
                row.get("session_trend_relationship"), row.get("phase"),
                row.get("checklist_score"), row.get("cq"), row.get("mas"),
                row.get("abs"), row.get("conf"), int(bool(row.get("entered_live"))),
                row.get("option_symbol"), row.get("entry_executable_ask"),
                row.get("classification"), row.get("mfe_pct"), row.get("mae_pct"),
                row.get("actual_broker_pnl_dollars"),
                int(bool(policies.get("CURRENT_BASELINE"))),
                int(bool(policies.get("ALIGNED_OR_NEUTRAL"))),
                int(bool(policies.get("ALIGNED_ONLY"))),
            ])
    return payload, json_path, csv_path, md_path
