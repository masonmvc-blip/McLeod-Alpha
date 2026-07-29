"""Daily evidence review for McLeod Alpha's post-exit cooling rule."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from reports.missed_opportunities_shadow_report import (
    evaluate_rejected_candidates,
    load_opportunity_events,
)


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
REENTRY_WINDOW_SECONDS = 5 * 60
MINIMUM_DECISION_SAMPLE = 20
MINIMUM_EVIDENCE_COVERAGE = 0.80


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN_TZ)
    return parsed.astimezone(EASTERN_TZ)


def _money(value: Any) -> str:
    amount = float(value or 0.0)
    return f"-${abs(amount):.2f}" if amount < 0 else f"${amount:.2f}"


def _contract_direction(symbol: Any) -> str | None:
    match = re.search(r"\d{6}([CP])\d{8}$", str(symbol or "").replace(" ", ""))
    if not match:
        return None
    return "CALL" if match.group(1) == "C" else "PUT"


def _enrich_cooling_quotes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use the recorded live watchlist when cooling ran before option selection."""
    enriched: list[dict[str, Any]] = []
    for event in events:
        copy = dict(event)
        reason = str(copy.get("rejection_reason") or copy.get("block_reason") or "")
        if reason.lower() != "cooling period" or copy.get("option_quote_snapshot"):
            enriched.append(copy)
            continue
        direction = str(copy.get("direction") or "").upper()
        watched = next(
            (
                row for row in copy.get("option_watch_quotes") or []
                if isinstance(row, dict)
                and _contract_direction(row.get("symbol")) == direction
                and float(row.get("ask") or 0.0) > 0
            ),
            None,
        )
        if watched:
            copy["option_selected"] = watched.get("symbol")
            copy["option_quote_snapshot"] = {
                **watched,
                "entry_executable_price": watched.get("ask"),
                "quote_provenance": "recorded_live_watchlist_reconstruction",
            }
        enriched.append(copy)
    return enriched


def _load_broker_trades(root: Path) -> list[dict[str, Any]]:
    db_path = root / "data" / "mcleod_alpha.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT entry_time, exit_time, direction, option_symbol, option_entry,
                   COALESCE(option_pnl_dollars, pnl, 0.0) AS pnl_dollars,
                   broker_entry_order_id, broker_exit_order_id
            FROM trade_log
            WHERE broker_entry_order_id IS NOT NULL
              AND broker_exit_order_id IS NOT NULL
            ORDER BY entry_time
            """
        ).fetchall()
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry_id = str(row["broker_entry_order_id"] or "")
        entered_at = _parse_time(row["entry_time"])
        exited_at = _parse_time(row["exit_time"])
        if not entry_id or entered_at is None or exited_at is None:
            continue
        unique[entry_id] = {
            "entered_at": entered_at,
            "exited_at": exited_at,
            "direction": str(row["direction"] or "").upper(),
            "option_symbol": str(row["option_symbol"] or ""),
            "option_entry": float(row["option_entry"] or 0.0),
            "pnl_dollars": float(row["pnl_dollars"] or 0.0),
            "broker_entry_order_id": entry_id,
            "broker_exit_order_id": str(row["broker_exit_order_id"] or ""),
        }
    return sorted(unique.values(), key=lambda row: row["entered_at"])


def _cooling_times(events: list[dict[str, Any]]) -> list[datetime]:
    return [
        at
        for event in events
        if str(event.get("rejection_reason") or event.get("block_reason") or "").lower()
        == "cooling period"
        if (at := _parse_time(event.get("candle_time_et"))) is not None
    ]


def _uncooled_reentries(
    trades: list[dict[str, Any]],
    cooling_times: list[datetime],
    trading_date: str,
) -> list[dict[str, Any]]:
    current = [
        row for row in trades if row["entered_at"].date().isoformat() == trading_date
    ]
    output: list[dict[str, Any]] = []
    for prior, following in zip(current, current[1:]):
        delay = (following["entered_at"] - prior["exited_at"]).total_seconds()
        if delay < 0 or delay > REENTRY_WINDOW_SECONDS:
            continue
        if prior["direction"] != following["direction"]:
            continue
        if prior["option_symbol"] != following["option_symbol"]:
            continue
        cooling_seen = any(
            prior["exited_at"] <= at <= following["entered_at"]
            for at in cooling_times
        )
        if cooling_seen:
            continue
        output.append({
            "prior_exit_time_et": prior["exited_at"].isoformat(),
            "reentry_time_et": following["entered_at"].isoformat(),
            "delay_seconds": round(delay, 1),
            "direction": following["direction"],
            "option_symbol": following["option_symbol"],
            "reentry_pnl_dollars": round(following["pnl_dollars"], 2),
            "harmful": following["pnl_dollars"] < 0,
            "broker_entry_order_id": following["broker_entry_order_id"],
        })
    return output


def build_cooling_period_review(
    trading_date: str,
    *,
    root: Path = ROOT,
    reconciliation_complete: bool,
) -> dict[str, Any]:
    raw_events = load_opportunity_events(trading_date, root=root)
    events = _enrich_cooling_quotes(raw_events)
    evaluated = [
        row
        for row in evaluate_rejected_candidates(events)
        if str(row.get("rejection_reason") or "").lower() == "cooling period"
    ]
    trades = _load_broker_trades(root)
    reentries = _uncooled_reentries(
        trades,
        _cooling_times(raw_events),
        trading_date,
    )
    decisive = [
        row for row in evaluated
        if row.get("classification") != "INSUFFICIENT_OPTION_EVIDENCE"
    ]
    coverage = len(decisive) / len(evaluated) if evaluated else 0.0
    missed = sum(
        row.get("classification") == "MISSED_PROFITABLE_OPPORTUNITY"
        for row in evaluated
    )
    protected = sum(
        row.get("classification") == "LOSS_CORRECTLY_AVOIDED"
        for row in evaluated
    )
    harmful_reentries = [row for row in reentries if row["harmful"]]

    if not reconciliation_complete:
        recommendation = "HOLD_UNCHANGED_RECONCILIATION_INCOMPLETE"
        rationale = "Broker reconciliation is incomplete; cooling conclusions are withheld."
    elif harmful_reentries:
        recommendation = "KEEP_AT_ONE"
        rationale = (
            "A harmful same-contract re-entry occurred without cooling. This supports reliable "
            "arming of the existing one-signal rule, not a longer rule."
        )
    elif protected > missed:
        recommendation = "KEEP_AT_ONE"
        rationale = "Cooling prevented more stop-first outcomes than target-first opportunities."
    elif missed > protected:
        recommendation = "KEEP_AT_ONE_COLLECT_MORE_DATA"
        rationale = (
            "Cooling blocked more target-first candidates today, but the governed sample is too "
            "small to shorten or remove post-exit protection."
        )
    else:
        recommendation = "KEEP_AT_ONE"
        rationale = "Today provides no decisive evidence that the current one-signal rule is too long or too short."

    return {
        "schema_version": "cooling-period-review.v1",
        "trading_date": trading_date,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "current_setting": "skip_one_otherwise_qualified_signal_after_each_exit",
        "recommendation": recommendation,
        "rationale": rationale,
        "increase_to_two_signals": {
            "recommended": False,
            "reason": "No governed evidence shows that a second blocked signal adds net protection.",
        },
        "remove_cooling": {
            "recommended": False,
            "reason": (
                "Removal is contradicted by harmful uncooled re-entry evidence and requires "
                "a governed target-first sample."
            ),
        },
        "summary": {
            "cooling_blocks": len(evaluated),
            "decisive_option_outcomes": len(decisive),
            "option_evidence_coverage": round(coverage, 4),
            "profitable_opportunities_blocked": missed,
            "losses_correctly_avoided": protected,
            "uncooled_same_contract_reentries": len(reentries),
            "harmful_uncooled_reentries": len(harmful_reentries),
            "harmful_uncooled_reentry_pnl": round(
                sum(row["reentry_pnl_dollars"] for row in harmful_reentries),
                2,
            ),
        },
        "blocked_observations": evaluated,
        "uncooled_reentries": reentries,
        "gate": {
            "minimum_decisive_sample": MINIMUM_DECISION_SAMPLE,
            "minimum_option_evidence_coverage": MINIMUM_EVIDENCE_COVERAGE,
            "sample_passed": len(decisive) >= MINIMUM_DECISION_SAMPLE,
            "coverage_passed": coverage >= MINIMUM_EVIDENCE_COVERAGE,
            "human_review_only": True,
        },
    }


def render_cooling_period_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "## Cooling Period — Daily Assessment",
        "",
        "- Current behavior: skip the next **one otherwise-qualified signal** after every confirmed exit.",
        f"- Today’s recommendation: **{payload.get('recommendation', 'KEEP_AT_ONE')}**.",
        f"- Rationale: {payload.get('rationale')}",
        f"- Increase to two signals: **NO** — {(payload.get('increase_to_two_signals') or {}).get('reason')}",
        f"- Drop cooling entirely: **NO** — {(payload.get('remove_cooling') or {}).get('reason')}",
        f"- Cooling blocks observed today: **{summary.get('cooling_blocks', 0)}**.",
        f"- Profitable opportunities blocked: **{summary.get('profitable_opportunities_blocked', 0)}**; "
        f"losses correctly avoided: **{summary.get('losses_correctly_avoided', 0)}**.",
        f"- Harmful uncooled re-entries: **{summary.get('harmful_uncooled_reentries', 0)}** "
        f"for **{_money(summary.get('harmful_uncooled_reentry_pnl'))}**.",
        f"- Executable blocked-signal coverage: **{float(summary.get('option_evidence_coverage') or 0):.1%}**.",
        "",
        "### Cooling Blocks",
        "",
        "| Time ET | Side | Score | Classification | MFE | MAE |",
        "| --- | --- | ---: | --- | ---: | ---: |",
    ]
    blocked = payload.get("blocked_observations") or []
    if not blocked:
        lines.append("| — | — | — | No cooling block today | — | — |")
    for row in blocked:
        at = _parse_time(row.get("candidate_time_et"))
        mfe = row.get("mfe_pct")
        mae = row.get("mae_pct")
        lines.append(
            f"| {at.strftime('%H:%M') if at else '—'} | {row.get('direction') or '—'} "
            f"| {row.get('checklist_score') if row.get('checklist_score') is not None else '—'} "
            f"| {row.get('classification') or '—'} "
            f"| {f'{float(mfe):.2f}%' if mfe is not None else '—'} "
            f"| {f'{float(mae):.2f}%' if mae is not None else '—'} |"
        )
    lines.extend(["", "### Cooling Failures and Fast Re-entries", ""])
    reentries = payload.get("uncooled_reentries") or []
    if not reentries:
        lines.append("- No same-contract re-entry occurred within five minutes without an intervening cooling block.")
    for row in reentries:
        lines.append(
            f"- {row.get('direction')} re-entry {float(row.get('delay_seconds') or 0):.0f}s after exit "
            f"produced **{_money(row.get('reentry_pnl_dollars'))}**."
        )
    gate = payload.get("gate") or {}
    lines.extend([
        "",
        f"- Change gate: at least **{gate.get('minimum_decisive_sample', MINIMUM_DECISION_SAMPLE)}** decisive cooling blocks "
        f"with **{float(gate.get('minimum_option_evidence_coverage') or MINIMUM_EVIDENCE_COVERAGE):.0%}** executable evidence.",
        "- Any change requires human review; this assessment cannot alter cooling automatically.",
        "",
    ])
    return "\n".join(lines)


def write_cooling_period_review(
    trading_date: str,
    *,
    root: Path = ROOT,
    reconciliation_complete: bool,
) -> tuple[dict[str, Any], Path, Path]:
    payload = build_cooling_period_review(
        trading_date,
        root=root,
        reconciliation_complete=reconciliation_complete,
    )
    payload["generated_at"] = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")
    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"cooling_period_review_{trading_date}.json"
    md_path = report_dir / f"cooling_period_review_{trading_date}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_cooling_period_markdown(payload) + "\n", encoding="utf-8")
    return payload, json_path, md_path
