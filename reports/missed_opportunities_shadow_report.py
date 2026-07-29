"""Canonical, research-only review of rejected McLeod Alpha opportunities."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
SCHEMA_VERSION = "missed-opportunities-shadow.v1"
FRESH_START_DATE = "2026-07-29"
FORWARD_WINDOW_MINUTES = 15
TARGET_RETURN_PCT = 6.0
INITIAL_STOP_RETURN_PCT = -3.0
EPISODE_COOLDOWN_MINUTES = 15
MINIMUM_PATTERN_SAMPLE = 20


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN_TZ)
    return parsed.astimezone(EASTERN_TZ)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return _object(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def load_opportunity_events(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> list[dict[str, Any]]:
    path = (
        root
        / "data"
        / "reports"
        / "opportunity_logs"
        / f"opportunity_setups_{trading_date}.jsonl"
    )
    if not path.exists():
        return []
    selected: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            event = _object(line)
        except Exception:
            continue
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        selected[event_id] = event
    return sorted(
        selected.values(),
        key=lambda row: (
            _parse_time(row.get("candle_time_et")) or datetime.min.replace(tzinfo=EASTERN_TZ),
            str(row.get("direction") or ""),
        ),
    )


def _metric_score(value: Any) -> float | None:
    if isinstance(value, dict):
        return _number(value.get("score"))
    return _number(value)


def _phase_label(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("label") or value.get("stage") or value.get("value")
    return str(value or "UNKNOWN").upper()


def _quote_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    snapshot = event.get("option_quote_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _quote_timelines(
    events: list[dict[str, Any]],
) -> dict[str, list[tuple[datetime, float]]]:
    timelines: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for event in events:
        at = _parse_time(event.get("candle_time_et"))
        snapshot = _quote_snapshot(event)
        symbol = str(snapshot.get("symbol") or event.get("option_selected") or "").strip()
        bid = _number(snapshot.get("bid"))
        if at is not None and symbol and bid is not None and bid > 0:
            timelines[symbol].append((at, bid))
        for watched in event.get("option_watch_quotes") or []:
            if not isinstance(watched, dict):
                continue
            watched_symbol = str(watched.get("symbol") or "").strip()
            watched_bid = _number(watched.get("bid"))
            if (
                at is not None
                and watched_symbol
                and watched_bid is not None
                and watched_bid > 0
            ):
                timelines[watched_symbol].append((at, watched_bid))
    for rows in timelines.values():
        rows[:] = sorted(set(rows), key=lambda row: row[0])
    return timelines


def _classify_rejection(event: dict[str, Any]) -> str:
    reason = str(event.get("rejection_reason") or "UNKNOWN").strip()
    normalized = reason.lower()
    distance = _number(event.get("score_distance_to_threshold"))
    if (
        (distance is not None and -2 <= distance < 0)
        or "score below threshold by 1" in normalized
        or "score below threshold by 2" in normalized
        or normalized in {"not entered", "entry not entered"}
        or any(
            marker in normalized
            for marker in ("paused", "cooling", "stale", "rate limit", "pending fill")
        )
    ):
        return "NEAR_MISS_REJECTION"
    return "UNSEEN_MARKET_MOVE"


def evaluate_rejected_candidates(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    timelines = _quote_timelines(events)
    evaluated: list[dict[str, Any]] = []
    for event in events:
        if bool(event.get("entered")):
            continue
        at = _parse_time(event.get("candle_time_et"))
        snapshot = _quote_snapshot(event)
        symbol = str(snapshot.get("symbol") or event.get("option_selected") or "").strip()
        entry_ask = _number(snapshot.get("ask"))
        reason = str(event.get("rejection_reason") or "UNKNOWN")
        base = {
            "event_id": event.get("event_id"),
            "candidate_time_et": at.isoformat() if at else event.get("candle_time_et"),
            "direction": str(event.get("direction") or "UNKNOWN").upper(),
            "rejection_reason": reason,
            "discovery_type": _classify_rejection(event),
            "market_regime": str(event.get("market_regime") or "UNKNOWN"),
            "phase": _phase_label(event.get("stage")),
            "checklist_score": (
                _number(event.get("score"))
                or (
                    _number(event.get("score_distance_to_threshold"))
                    + (_number(event.get("entry_threshold")) or 5)
                    if _number(event.get("score_distance_to_threshold")) is not None
                    else None
                )
            ),
            "cq": _metric_score(event.get("cq")),
            "mas": _metric_score(event.get("mas")),
            "abs": _metric_score(event.get("absorption_score")),
            "conf": _metric_score(event.get("confidence")),
            "positive_signals": list(event.get("positive_signals") or []),
            "penalties": list(event.get("penalties") or []),
            "option_symbol": symbol or None,
            "entry_executable_ask": entry_ask,
            "outcome_evidence": "ACTUAL_EXECUTABLE_OPTION_QUOTES",
            "forward_window_minutes": FORWARD_WINDOW_MINUTES,
            "target_return_pct": TARGET_RETURN_PCT,
            "initial_stop_return_pct": INITIAL_STOP_RETURN_PCT,
        }
        if at is None or not symbol or entry_ask is None or entry_ask <= 0:
            evaluated.append({
                **base,
                "classification": "INSUFFICIENT_OPTION_EVIDENCE",
                "evidence_gap": "missing executable option ask at candidate time",
                "future_quote_count": 0,
                "mfe_pct": None,
                "mae_pct": None,
                "first_passage": None,
                "first_passage_time_et": None,
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
            classification = "INSUFFICIENT_OPTION_EVIDENCE"
            evidence_gap = "no future executable bids for selected contract"
            first_passage = None
            first_passage_time = None
        elif target_hit and (not stop_hit or target_hit[0] < stop_hit[0]):
            classification = "MISSED_PROFITABLE_OPPORTUNITY"
            evidence_gap = None
            first_passage = "TARGET_BEFORE_STOP"
            first_passage_time = target_hit[0]
        elif stop_hit and (not target_hit or stop_hit[0] <= target_hit[0]):
            classification = "LOSS_CORRECTLY_AVOIDED"
            evidence_gap = None
            first_passage = "STOP_BEFORE_TARGET"
            first_passage_time = stop_hit[0]
        else:
            classification = "NO_DECISIVE_MOVE"
            evidence_gap = None
            first_passage = "NEITHER_TARGET_NOR_STOP"
            first_passage_time = None
        evaluated.append({
            **base,
            "classification": classification,
            "evidence_gap": evidence_gap,
            "future_quote_count": len(returns),
            "mfe_pct": round(max((value for _, value in returns), default=0.0), 4)
            if returns else None,
            "mae_pct": round(min((value for _, value in returns), default=0.0), 4)
            if returns else None,
            "first_passage": first_passage,
            "first_passage_time_et": (
                first_passage_time.isoformat() if first_passage_time else None
            ),
        })
    return evaluated


def canonicalize_episodes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated minute signals within the same directional move."""
    canonical: list[dict[str, Any]] = []
    last_by_key: dict[tuple[str, str], datetime] = {}
    for row in sorted(
        rows,
        key=lambda item: _parse_time(item.get("candidate_time_et"))
        or datetime.min.replace(tzinfo=EASTERN_TZ),
    ):
        classification = str(row.get("classification") or "")
        if classification not in {
            "MISSED_PROFITABLE_OPPORTUNITY",
            "LOSS_CORRECTLY_AVOIDED",
        }:
            continue
        at = _parse_time(row.get("candidate_time_et"))
        if at is None:
            continue
        key = (str(row.get("direction")), classification)
        previous = last_by_key.get(key)
        if previous and at <= previous + timedelta(minutes=EPISODE_COOLDOWN_MINUTES):
            continue
        canonical.append({**row, "canonical_episode": True})
        last_by_key[key] = at
    return canonical


def _pattern_summary(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in episodes:
        grouped[(
            str(row.get("direction") or "UNKNOWN"),
            str(row.get("phase") or "UNKNOWN"),
            str(row.get("rejection_reason") or "UNKNOWN"),
        )].append(row)
    output: list[dict[str, Any]] = []
    for (direction, phase, reason), members in grouped.items():
        missed = sum(
            row.get("classification") == "MISSED_PROFITABLE_OPPORTUNITY"
            for row in members
        )
        protected = sum(
            row.get("classification") == "LOSS_CORRECTLY_AVOIDED"
            for row in members
        )
        mfes = [
            float(row["mfe_pct"]) for row in members if row.get("mfe_pct") is not None
        ]
        maes = [
            float(row["mae_pct"]) for row in members if row.get("mae_pct") is not None
        ]
        sample = len(members)
        output.append({
            "direction": direction,
            "phase": phase,
            "rejection_reason": reason,
            "canonical_episodes": sample,
            "missed_profitable": missed,
            "losses_avoided": protected,
            "miss_rate": round(missed / sample, 4) if sample else None,
            "median_mfe_pct": round(median(mfes), 4) if mfes else None,
            "median_mae_pct": round(median(maes), 4) if maes else None,
            "research_status": (
                "ELIGIBLE_FOR_HUMAN_REVIEW"
                if sample >= MINIMUM_PATTERN_SAMPLE
                else "COLLECT_MORE_DATA"
            ),
            "automatic_live_change_allowed": False,
        })
    return sorted(
        output,
        key=lambda row: (
            -row["missed_profitable"],
            -row["canonical_episodes"],
            row["direction"],
            row["phase"],
        ),
    )


def build_missed_opportunities_payload(
    events: list[dict[str, Any]],
    *,
    trading_date: str,
    reconciliation: dict[str, Any],
    historical_episodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evaluated = evaluate_rejected_candidates(events)
    episodes = canonicalize_episodes(evaluated)
    missed = [
        row for row in episodes
        if row.get("classification") == "MISSED_PROFITABLE_OPPORTUNITY"
    ]
    protected = [
        row for row in episodes
        if row.get("classification") == "LOSS_CORRECTLY_AVOIDED"
    ]
    decisive_candidates = [
        row for row in evaluated
        if row.get("classification") != "INSUFFICIENT_OPTION_EVIDENCE"
    ]
    evidence_coverage = (
        len(decisive_candidates) / len(evaluated) if evaluated else 0.0
    )
    rolling_episodes = list(historical_episodes or []) + episodes
    rolling_patterns = _pattern_summary(rolling_episodes)
    return {
        "schema_version": SCHEMA_VERSION,
        "trading_date": trading_date,
        "fresh_start_date": FRESH_START_DATE,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "methodology": {
            "candidate_unit": "one rejected direction per completed candle",
            "episode_unit": (
                f"one {EPISODE_COOLDOWN_MINUTES}-minute directional outcome episode"
            ),
            "entry_price": "selected contract executable ask",
            "exit_price": "subsequent executable bids for the same contract",
            "target_return_pct": TARGET_RETURN_PCT,
            "initial_stop_return_pct": INITIAL_STOP_RETURN_PCT,
            "forward_window_minutes": FORWARD_WINDOW_MINUTES,
            "proxy_estimates_can_create_missed_label": False,
        },
        "summary": {
            "rejected_candidates": len(evaluated),
            "candidates_with_executable_outcome_evidence": len(decisive_candidates),
            "option_evidence_coverage": round(evidence_coverage, 4),
            "canonical_missed_opportunities": len(missed),
            "canonical_losses_correctly_avoided": len(protected),
            "near_miss_opportunities": sum(
                row.get("discovery_type") == "NEAR_MISS_REJECTION" for row in missed
            ),
            "unseen_market_moves": sum(
                row.get("discovery_type") == "UNSEEN_MARKET_MOVE" for row in missed
            ),
            "no_decisive_move_candidates": sum(
                row.get("classification") == "NO_DECISIVE_MOVE" for row in evaluated
            ),
            "insufficient_option_evidence": sum(
                row.get("classification") == "INSUFFICIENT_OPTION_EVIDENCE"
                for row in evaluated
            ),
        },
        "missed_opportunities": missed,
        "losses_correctly_avoided": protected,
        "today_pattern_summary": _pattern_summary(episodes),
        "pattern_summary": rolling_patterns,
        "rolling_canonical_episodes": len(rolling_episodes),
        "evidence_gaps": [
            {
                "event_id": row.get("event_id"),
                "candidate_time_et": row.get("candidate_time_et"),
                "direction": row.get("direction"),
                "rejection_reason": row.get("rejection_reason"),
                "gap": row.get("evidence_gap"),
            }
            for row in evaluated
            if row.get("classification") == "INSUFFICIENT_OPTION_EVIDENCE"
        ],
        "gate": {
            "canonical_reconciliation_complete": bool(reconciliation.get("complete")),
            "minimum_pattern_sample": MINIMUM_PATTERN_SAMPLE,
            "minimum_option_evidence_coverage": 0.80,
            "option_evidence_coverage_passed": evidence_coverage >= 0.80,
            "decision": (
                "REVIEW_PATTERNS"
                if bool(reconciliation.get("complete"))
                and evidence_coverage >= 0.80
                and any(
                    row["canonical_episodes"] >= MINIMUM_PATTERN_SAMPLE
                    for row in rolling_patterns
                )
                else "COLLECT_MORE_DATA"
            ),
        },
        "reconciliation": reconciliation,
        "conclusions_withheld": not bool(reconciliation.get("complete")),
    }


def _moneyless_percent(value: Any) -> str:
    number = _number(value)
    return f"{number:.2f}%" if number is not None else "N/A"


def _episode_table(rows: list[dict[str, Any]], empty_label: str) -> list[str]:
    lines = [
        "| Time ET | Side | Type | Phase | Score | Rejection Reason | Contract | MFE | MAE | First Passage |",
        "| --- | --- | --- | --- | ---: | --- | --- | ---: | ---: | --- |",
    ]
    if not rows:
        lines.append(f"| — | — | — | — | — | {empty_label} | — | — | — | — |")
        return lines
    for row in rows:
        at = _parse_time(row.get("candidate_time_et"))
        time_text = at.strftime("%H:%M") if at else str(row.get("candidate_time_et") or "—")
        score = row.get("checklist_score")
        score_text = f"{float(score):.0f}" if score is not None else "N/A"
        lines.append(
            f"| {time_text} | {row.get('direction')} | {row.get('discovery_type')} "
            f"| {row.get('phase')} | {score_text} | {row.get('rejection_reason')} "
            f"| {row.get('option_symbol') or 'N/A'} | {_moneyless_percent(row.get('mfe_pct'))} "
            f"| {_moneyless_percent(row.get('mae_pct'))} | {row.get('first_passage')} |"
        )
    return lines


def render_missed_opportunities_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "## Missed Opportunities — Shadow Review",
        "",
        "- Research only: this worksheet cannot alter live admission, sizing, or exits.",
        f"- A profitable miss requires executable option quotes: buy at ask, then reach "
        f"**+{TARGET_RETURN_PCT:.0f}% before {INITIAL_STOP_RETURN_PCT:.0f}%** using subsequent bids.",
        f"- Repeated minute signals are collapsed into one {EPISODE_COOLDOWN_MINUTES}-minute directional episode.",
        "- SPY-proxy estimates and hindsight chart moves are never labeled as missed profits.",
        "",
        "### Daily Scorecard",
        "",
        f"- Rejected candidates evaluated: **{summary.get('rejected_candidates', 0)}**",
        f"- Executable option-evidence coverage: **{float(summary.get('option_evidence_coverage') or 0):.1%}**",
        f"- Canonical profitable opportunities missed: **{summary.get('canonical_missed_opportunities', 0)}**",
        f"- Losses correctly avoided: **{summary.get('canonical_losses_correctly_avoided', 0)}**",
        f"- Near-miss rejections: **{summary.get('near_miss_opportunities', 0)}**; "
        f"unseen market moves: **{summary.get('unseen_market_moves', 0)}**",
        f"- Candidates lacking sufficient option evidence: **{summary.get('insufficient_option_evidence', 0)}**",
        "",
    ]
    if payload.get("conclusions_withheld"):
        lines.extend([
            "**Trading conclusions are withheld because canonical broker reconciliation is incomplete.**",
            "",
        ])
    lines.extend(["### Canonical Missed Opportunities", ""])
    lines.extend(_episode_table(
        payload.get("missed_opportunities") or [],
        "No executable +6%-before-stop episode",
    ))
    lines.extend(["", "### Losses Correctly Avoided", ""])
    lines.extend(_episode_table(
        payload.get("losses_correctly_avoided") or [],
        "No executable stop-before-target episode",
    ))
    lines.extend([
        "",
        "### Recurring Rejection Patterns",
        "",
        f"- Rolling fresh sample begins {payload.get('fresh_start_date')} and contains "
        f"**{payload.get('rolling_canonical_episodes', 0)} canonical episodes**.",
        "",
        "| Side | Phase | Rejection Reason | Episodes | Missed | Protected | Miss Rate | Median MFE | Status |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    patterns = payload.get("pattern_summary") or []
    if not patterns:
        lines.append("| — | — | No decisive canonical episodes yet | 0 | 0 | 0 | N/A | N/A | COLLECT_MORE_DATA |")
    else:
        for row in patterns:
            miss_rate = row.get("miss_rate")
            lines.append(
                f"| {row.get('direction')} | {row.get('phase')} | {row.get('rejection_reason')} "
                f"| {row.get('canonical_episodes')} | {row.get('missed_profitable')} "
                f"| {row.get('losses_avoided')} | "
                f"{f'{miss_rate:.1%}' if miss_rate is not None else 'N/A'} "
                f"| {_moneyless_percent(row.get('median_mfe_pct'))} "
                f"| {row.get('research_status')} |"
            )
    gate = payload.get("gate") or {}
    lines.extend([
        "",
        "### Evidence Gate",
        "",
        f"- Decision: **{gate.get('decision', 'COLLECT_MORE_DATA')}**",
        f"- Require at least {gate.get('minimum_pattern_sample', MINIMUM_PATTERN_SAMPLE)} canonical episodes per pattern.",
        f"- Require at least {float(gate.get('minimum_option_evidence_coverage') or 0.8):.0%} executable option-evidence coverage.",
        "- Passing the gate permits human review only; automatic live changes are permanently disabled.",
        "",
    ])
    return "\n".join(lines)


def write_missed_opportunities_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path, Path]:
    events = load_opportunity_events(trading_date, root=root)
    report_dir = root / "reports" / "daily_trade_learning"
    historical_episodes: list[dict[str, Any]] = []
    for path in sorted(report_dir.glob("missed_opportunities_shadow_????-??-??.json")):
        report_date = path.stem.removeprefix("missed_opportunities_shadow_")
        if report_date >= trading_date or report_date < FRESH_START_DATE:
            continue
        prior = _load_json(path)
        historical_episodes.extend(prior.get("missed_opportunities") or [])
        historical_episodes.extend(prior.get("losses_correctly_avoided") or [])
    reconciliation = _load_json(
        root
        / "reports"
        / "daily_loss_attribution"
        / f"daily_loss_attribution_{trading_date}.json"
    ).get("reconciliation") or {}
    payload = build_missed_opportunities_payload(
        events,
        trading_date=trading_date,
        reconciliation=reconciliation,
        historical_episodes=historical_episodes,
    )
    payload["generated_at"] = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")

    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"missed_opportunities_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_missed_opportunities_markdown(payload) + "\n", encoding="utf-8")
    rows = (
        list(payload.get("missed_opportunities") or [])
        + list(payload.get("losses_correctly_avoided") or [])
    )
    fieldnames = [
        "event_id",
        "candidate_time_et",
        "direction",
        "discovery_type",
        "classification",
        "rejection_reason",
        "market_regime",
        "phase",
        "checklist_score",
        "cq",
        "mas",
        "abs",
        "conf",
        "option_symbol",
        "entry_executable_ask",
        "future_quote_count",
        "mfe_pct",
        "mae_pct",
        "first_passage",
        "first_passage_time_et",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return payload, json_path, csv_path, md_path
