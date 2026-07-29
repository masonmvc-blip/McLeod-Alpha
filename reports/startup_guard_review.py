"""Daily evidence review for McLeod Alpha's startup-entry guard."""

from __future__ import annotations

import json
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
FOLLOWUP_WINDOW_SECONDS = 5 * 60
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


def _load_followup_trades(root: Path) -> list[dict[str, Any]]:
    db_path = root / "data" / "mcleod_alpha.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT entry_time, direction, option_symbol, option_entry,
                   COALESCE(option_pnl_dollars, pnl, 0.0) AS pnl_dollars,
                   broker_entry_order_id
            FROM trade_log
            WHERE broker_entry_order_id IS NOT NULL
              AND broker_exit_order_id IS NOT NULL
            ORDER BY entry_time
            """
        ).fetchall()
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        order_id = str(row["broker_entry_order_id"] or "")
        entered_at = _parse_time(row["entry_time"])
        if not order_id or entered_at is None:
            continue
        unique[order_id] = {
            "entered_at": entered_at,
            "direction": str(row["direction"] or "").upper(),
            "option_symbol": str(row["option_symbol"] or ""),
            "option_entry": float(row["option_entry"] or 0.0),
            "pnl_dollars": float(row["pnl_dollars"] or 0.0),
            "broker_entry_order_id": order_id,
        }
    return sorted(unique.values(), key=lambda row: row["entered_at"])


def _followup_trade(
    candidate: dict[str, Any],
    trades: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidate_at = _parse_time(candidate.get("candidate_time_et"))
    if candidate_at is None:
        return None
    direction = str(candidate.get("direction") or "").upper()
    symbol = str(candidate.get("option_symbol") or "")
    for trade in trades:
        delay = (trade["entered_at"] - candidate_at).total_seconds()
        if delay < 0:
            continue
        if delay > FOLLOWUP_WINDOW_SECONDS:
            break
        if trade["direction"] != direction:
            continue
        if symbol and trade["option_symbol"] and trade["option_symbol"] != symbol:
            continue
        candidate_ask = float(candidate.get("entry_executable_ask") or 0.0)
        followup_entry = float(trade.get("option_entry") or 0.0)
        return {
            **trade,
            "entered_at": trade["entered_at"].isoformat(),
            "delay_seconds": round(delay, 1),
            "entry_improvement_dollars": (
                round(candidate_ask - followup_entry, 4)
                if candidate_ask > 0 and followup_entry > 0
                else None
            ),
        }
    return None


def build_startup_guard_review(
    trading_date: str,
    *,
    root: Path = ROOT,
    reconciliation_complete: bool,
) -> dict[str, Any]:
    events = load_opportunity_events(trading_date, root=root)
    evaluated = [
        row
        for row in evaluate_rejected_candidates(events)
        if str(row.get("rejection_reason") or "").lower() == "startup_guard"
    ]
    followup_trades = _load_followup_trades(root)
    observations: list[dict[str, Any]] = []
    for row in evaluated:
        followup = _followup_trade(row, followup_trades)
        observations.append({
            "candidate_time_et": row.get("candidate_time_et"),
            "direction": row.get("direction"),
            "option_symbol": row.get("option_symbol"),
            "checklist_score": row.get("checklist_score"),
            "phase": row.get("phase"),
            "classification": row.get("classification"),
            "first_passage": row.get("first_passage"),
            "mfe_pct": row.get("mfe_pct"),
            "mae_pct": row.get("mae_pct"),
            "entry_executable_ask": row.get("entry_executable_ask"),
            "evidence_gap": row.get("evidence_gap"),
            "followup_trade": followup,
        })

    decisive = [
        row for row in observations
        if row.get("classification") != "INSUFFICIENT_OPTION_EVIDENCE"
    ]
    coverage = len(decisive) / len(observations) if observations else 0.0
    missed = sum(
        row.get("classification") == "MISSED_PROFITABLE_OPPORTUNITY"
        for row in observations
    )
    protected = sum(
        row.get("classification") == "LOSS_CORRECTLY_AVOIDED"
        for row in observations
    )
    preserved = sum(bool(row.get("followup_trade")) for row in observations)

    if not reconciliation_complete:
        recommendation = "HOLD_UNCHANGED_RECONCILIATION_INCOMPLETE"
        rationale = "Broker reconciliation is incomplete; no startup-guard change is supportable."
    elif not observations:
        recommendation = "KEEP_AT_ONE"
        rationale = "No startup-guard block occurred today, so there is no new evidence to change it."
    elif preserved == len(observations):
        recommendation = "KEEP_AT_ONE"
        rationale = (
            "Every guarded setup was entered in the same direction and contract within five minutes; "
            "the guard delayed rather than eliminated the opportunity."
        )
    else:
        recommendation = "KEEP_AT_ONE_COLLECT_MORE_DATA"
        rationale = (
            "At least one guarded setup lacked a prompt matching entry, but the governed sample is "
            "too small to increase or remove startup protection."
        )

    return {
        "schema_version": "startup-guard-review.v1",
        "trading_date": trading_date,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "current_setting": 1,
        "recommendation": recommendation,
        "rationale": rationale,
        "increase_guard": {
            "recommended": False,
            "reason": "No evidence that blocking additional qualified entries improves outcomes.",
        },
        "remove_guard": {
            "recommended": False,
            "reason": (
                "The one-attempt guard protects startup state; removal requires a governed sample "
                "showing repeatable opportunity cost without avoided losses."
            ),
        },
        "summary": {
            "blocked_candidates": len(observations),
            "decisive_option_outcomes": len(decisive),
            "option_evidence_coverage": round(coverage, 4),
            "profitable_candidates_blocked": missed,
            "losses_correctly_avoided": protected,
            "opportunities_preserved_by_prompt_followup": preserved,
        },
        "observations": observations,
        "gate": {
            "minimum_decisive_sample": MINIMUM_DECISION_SAMPLE,
            "minimum_option_evidence_coverage": MINIMUM_EVIDENCE_COVERAGE,
            "sample_passed": len(decisive) >= MINIMUM_DECISION_SAMPLE,
            "coverage_passed": coverage >= MINIMUM_EVIDENCE_COVERAGE,
            "human_review_only": True,
        },
    }


def render_startup_guard_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "## Startup Guard — Daily Assessment",
        "",
        f"- Current setting: block the first **{payload.get('current_setting', 1)}** otherwise-qualified entry after runtime startup.",
        f"- Today’s recommendation: **{payload.get('recommendation', 'KEEP_AT_ONE')}**.",
        f"- Rationale: {payload.get('rationale')}",
        f"- Increase it: **NO** — {(payload.get('increase_guard') or {}).get('reason')}",
        f"- Remove it: **NO** — {(payload.get('remove_guard') or {}).get('reason')}",
        f"- Qualified candidates blocked today: **{summary.get('blocked_candidates', 0)}**.",
        f"- Prompt same-contract opportunities preserved: **{summary.get('opportunities_preserved_by_prompt_followup', 0)}**.",
        f"- Executable outcome coverage: **{float(summary.get('option_evidence_coverage') or 0):.1%}**.",
        "",
        "| Time ET | Side | Score | Outcome | Follow-up | Entry Improvement | Follow-up P&L |",
        "| --- | --- | ---: | --- | --- | ---: | ---: |",
    ]
    observations = payload.get("observations") or []
    if not observations:
        lines.append("| — | — | — | No startup-guard block today | — | — | — |")
    for row in observations:
        at = _parse_time(row.get("candidate_time_et"))
        followup = row.get("followup_trade") or {}
        improvement = followup.get("entry_improvement_dollars")
        pnl = followup.get("pnl_dollars")
        followup_text = (
            f"{float(followup.get('delay_seconds')):.0f}s later"
            if followup
            else "None within 5m"
        )
        improvement_text = (
            f"${float(improvement):.2f} better"
            if improvement is not None
            else "—"
        )
        pnl_text = f"${float(pnl):.2f}" if pnl is not None else "—"
        lines.append(
            f"| {at.strftime('%H:%M') if at else '—'} | {row.get('direction') or '—'} "
            f"| {row.get('checklist_score') if row.get('checklist_score') is not None else '—'} "
            f"| {row.get('classification') or '—'} "
            f"| {followup_text} | {improvement_text} | {pnl_text} |"
        )
    gate = payload.get("gate") or {}
    lines.extend([
        "",
        f"- Change gate: at least **{gate.get('minimum_decisive_sample', MINIMUM_DECISION_SAMPLE)}** decisive guarded setups "
        f"with **{float(gate.get('minimum_option_evidence_coverage') or MINIMUM_EVIDENCE_COVERAGE):.0%}** executable evidence.",
        "- Any change requires human review; this assessment cannot modify the live guard automatically.",
        "",
    ])
    return "\n".join(lines)


def write_startup_guard_review(
    trading_date: str,
    *,
    root: Path = ROOT,
    reconciliation_complete: bool,
) -> tuple[dict[str, Any], Path, Path]:
    payload = build_startup_guard_review(
        trading_date,
        root=root,
        reconciliation_complete=reconciliation_complete,
    )
    payload["generated_at"] = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")
    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"startup_guard_review_{trading_date}.json"
    md_path = report_dir / f"startup_guard_review_{trading_date}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_startup_guard_markdown(payload) + "\n", encoding="utf-8")
    return payload, json_path, md_path
