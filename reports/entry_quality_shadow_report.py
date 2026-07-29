"""Canonical, research-only studies for Phase/CQ/MAS/ABS/CONF."""

from __future__ import annotations

import csv
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
STUDY_VERSION = "entry-quality-shadow.v1"
FRESH_START_DATE = "2026-07-29"
MINIMUM_GROUP_SAMPLE = 20
STANDARD_PHASES = {
    "INITIATION",
    "EARLY_CONTINUATION",
    "ESTABLISHED",
    "MATURE",
    "LATE_EXHAUSTION",
}


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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return _object(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _diagnostic_values(row: sqlite3.Row) -> dict[str, Any]:
    payload = _object(row["feature_payload"])
    stage = payload.get("trend_stage") or {}
    return {
        "phase": (
            payload.get("momentum_phase")
            or row["momentum_phase"]
            or (stage.get("label") if isinstance(stage, dict) else None)
        ),
        "cq": _number(
            payload.get("continuation_quality_score")
            if payload.get("continuation_quality_score") is not None
            else (payload.get("continuation_quality") or {}).get("score")
        ),
        "mas": _number(
            payload.get("momentum_acceleration_score")
            if payload.get("momentum_acceleration_score") is not None
            else (payload.get("momentum_acceleration") or {}).get("score")
        ),
        "abs": _number(
            payload.get("absorption_score")
            if payload.get("absorption_score") is not None
            else (
                (payload.get("absorption") or {}).get("score")
                if payload.get("absorption")
                else row["absorption_score"]
            )
        ),
        "conf": _number(
            payload.get("confidence_score")
            if payload.get("confidence_score") is not None
            else (payload.get("confidence") or {}).get("score")
        ),
    }


def _load_best_diagnostics(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, broker_entry_order_id, momentum_phase,
               absorption_score, feature_payload
        FROM trade_log
        WHERE trim(COALESCE(broker_entry_order_id, '')) <> ''
        ORDER BY id
        """
    ).fetchall()
    selected: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for row in rows:
        values = _diagnostic_values(row)
        coverage = sum(value is not None for value in values.values())
        order_id = str(row["broker_entry_order_id"] or "")
        candidate = (coverage, int(row["id"]), values)
        if order_id not in selected or candidate[:2] > selected[order_id][:2]:
            selected[order_id] = candidate
    return {order_id: candidate[2] for order_id, candidate in selected.items()}


def _load_latest_canonical_payloads(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT canonical_trade_id, canonical_version, payload
        FROM canonical_completed_trade_versions
        ORDER BY canonical_trade_id, canonical_version
        """
    ).fetchall()
    selected: dict[str, dict[str, Any]] = {}
    for canonical_trade_id, canonical_version, raw_payload in rows:
        payload = _object(raw_payload)
        current = selected.get(str(canonical_trade_id))
        broker_cash = str(payload.get("pnl_source") or "").lower() == "broker_cash"
        current_broker_cash = bool(
            current and str(current.get("pnl_source") or "").lower() == "broker_cash"
        )
        if (
            current is None
            or (broker_cash and not current_broker_cash)
            or (
                broker_cash == current_broker_cash
                and int(canonical_version) > int(current.get("canonical_version") or 0)
            )
        ):
            payload["canonical_trade_id"] = str(canonical_trade_id)
            payload["canonical_version"] = int(canonical_version)
            selected[str(canonical_trade_id)] = payload
    return list(selected.values())


def load_study_trades(*, root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return one economic trade per broker entry order plus coverage facts."""
    db_path = root / "data" / "mcleod_alpha.db"
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        diagnostics = _load_best_diagnostics(connection)
        canonical = _load_latest_canonical_payloads(connection)

    representations: list[dict[str, Any]] = []
    for payload in canonical:
        entry_order_id = str(payload.get("broker_entry_order_id") or "")
        if not all(
            (
                entry_order_id,
                str(payload.get("broker_exit_order_id") or ""),
                str(payload.get("option_symbol") or ""),
            )
        ):
            continue
        entry_time = str(payload.get("entry_time") or "")
        values = diagnostics.get(entry_order_id, {})
        representations.append(
            {
                "canonical_trade_id": payload.get("canonical_trade_id"),
                "broker_entry_order_id": entry_order_id,
                "broker_exit_order_id": str(payload.get("broker_exit_order_id") or ""),
                "trade_date": entry_time[:10],
                "entry_time": entry_time,
                "direction": str(payload.get("direction") or "UNKNOWN").upper(),
                "pnl_dollars": round(
                    _number(payload.get("option_pnl_dollars"))
                    or _number(payload.get("pnl"))
                    or 0.0,
                    2,
                ),
                "exit_reason": str(payload.get("exit_reason") or "UNKNOWN"),
                "source": str(payload.get("source") or ""),
                **values,
            }
        )

    # Historical local-close and broker-reconciled representations can share
    # one broker entry order. Prefer the actual broker-reconciled outcome.
    deduplicated: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for trade in representations:
        preference = (
            trade["exit_reason"] == "BROKER_RECONCILED_EXIT",
            trade["source"] == "cockpit_health_reconciliation",
            str(trade["canonical_trade_id"]),
        )
        order_id = trade["broker_entry_order_id"]
        if order_id not in deduplicated or preference > deduplicated[order_id][0]:
            deduplicated[order_id] = (preference, trade)
    trades = sorted(
        (item[1] for item in deduplicated.values()),
        key=lambda trade: (trade["entry_time"], trade["broker_entry_order_id"]),
    )
    coverage = {
        "canonical_representations": len(representations),
        "distinct_broker_entries": len(trades),
        "phase_cq_mas_conf": sum(
            all(trade.get(key) is not None for key in ("phase", "cq", "mas", "conf"))
            for trade in trades
        ),
        "complete_five_metrics": sum(
            all(trade.get(key) is not None for key in ("phase", "cq", "mas", "abs", "conf"))
            for trade in trades
        ),
        "standard_phase_complete": sum(
            all(trade.get(key) is not None for key in ("cq", "mas", "abs", "conf"))
            and trade.get("phase") in STANDARD_PHASES
            for trade in trades
        ),
    }
    return trades, coverage


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(row.get("pnl_dollars") or 0.0) for row in rows]
    wins = sum(pnl > 0 for pnl in pnls)
    directions = {
        "CALL": sum(str(row.get("direction")) == "CALL" for row in rows),
        "PUT": sum(str(row.get("direction")) == "PUT" for row in rows),
    }
    return {
        "trades": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "win_rate": round(wins / len(rows), 4) if rows else None,
        "pnl_dollars": round(sum(pnls), 2),
        "average_pnl_dollars": round(sum(pnls) / len(rows), 2) if rows else None,
        "median_pnl_dollars": round(median(pnls), 2) if rows else None,
        "directions": directions,
    }


def _cohorts(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "early_continuation_conf_4_candidate": [
            row for row in rows
            if row.get("phase") == "EARLY_CONTINUATION" and float(row.get("conf") or 0) >= 4.0
        ],
        "all_other_complete_comparator": [
            row for row in rows
            if not (
                row.get("phase") == "EARLY_CONTINUATION"
                and float(row.get("conf") or 0) >= 4.0
            )
        ],
        "established_call_shadow_reject": [
            row for row in rows
            if row.get("phase") == "ESTABLISHED" and row.get("direction") == "CALL"
        ],
        "non_established_call_comparator": [
            row for row in rows
            if row.get("phase") != "ESTABLISHED" and row.get("direction") == "CALL"
        ],
        "established_put_shadow_reject": [
            row for row in rows
            if row.get("phase") == "ESTABLISHED" and row.get("direction") == "PUT"
        ],
        "non_established_put_comparator": [
            row for row in rows
            if row.get("phase") != "ESTABLISHED" and row.get("direction") == "PUT"
        ],
    }


def evaluate_entry_quality_shadow(
    trades: list[dict[str, Any]],
    *,
    trading_date: str,
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    comparable = [
        trade for trade in trades
        if trade.get("phase") in STANDARD_PHASES
        and all(trade.get(key) is not None for key in ("cq", "mas", "abs", "conf"))
    ]
    historical = _cohorts(comparable)
    fresh_rows = [
        trade for trade in comparable
        if FRESH_START_DATE <= str(trade.get("trade_date") or "") <= trading_date
    ]
    fresh = _cohorts(fresh_rows)
    historical_stats = {name: _stats(rows) for name, rows in historical.items()}
    fresh_stats = {name: _stats(rows) for name, rows in fresh.items()}

    primary_candidate = fresh_stats["early_continuation_conf_4_candidate"]
    primary_comparator = fresh_stats["all_other_complete_comparator"]
    primary_checks = {
        "candidate_minimum_20": primary_candidate["trades"] >= MINIMUM_GROUP_SAMPLE,
        "comparator_minimum_20": primary_comparator["trades"] >= MINIMUM_GROUP_SAMPLE,
        "candidate_has_call_and_put": all(
            primary_candidate["directions"].get(direction, 0) > 0
            for direction in ("CALL", "PUT")
        ),
        "comparator_has_call_and_put": all(
            primary_comparator["directions"].get(direction, 0) > 0
            for direction in ("CALL", "PUT")
        ),
    }
    established_groups = (
        "established_call_shadow_reject",
        "non_established_call_comparator",
        "established_put_shadow_reject",
        "non_established_put_comparator",
    )
    established_checks = {
        f"{name}_minimum_20": fresh_stats[name]["trades"] >= MINIMUM_GROUP_SAMPLE
        for name in established_groups
    }
    common_checks = {
        "fresh_collection_started": trading_date >= FRESH_START_DATE,
        "canonical_reconciliation_complete": bool(reconciliation.get("complete")),
    }
    primary_ready = all({**common_checks, **primary_checks}.values())
    established_ready = all({**common_checks, **established_checks}.values())
    return {
        "schema_version": STUDY_VERSION,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "fresh_start_date": FRESH_START_DATE,
        "trading_date": trading_date,
        "historical_comparable_trades": len(comparable),
        "fresh_comparable_trades": len(fresh_rows),
        "today_trades": [
            trade for trade in comparable if trade.get("trade_date") == trading_date
        ],
        "historical_cohorts": historical_stats,
        "fresh_cohorts": fresh_stats,
        "hypotheses": {
            "early_continuation_conf_4": {
                "candidate": "early_continuation_conf_4_candidate",
                "comparator": "all_other_complete_comparator",
                "checks": {**common_checks, **primary_checks},
                "ready_for_human_review": primary_ready,
                "decision": "ELIGIBLE_FOR_HUMAN_REVIEW" if primary_ready else "COLLECT_MORE_DATA",
            },
            "established_shadow_reject_by_direction": {
                "checks": {**common_checks, **established_checks},
                "ready_for_human_review": established_ready,
                "decision": "ELIGIBLE_FOR_HUMAN_REVIEW" if established_ready else "COLLECT_MORE_DATA",
            },
        },
        "reconciliation": reconciliation,
        "conclusions_withheld": not bool(reconciliation.get("complete")),
    }


def render_entry_quality_shadow_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## Entry Quality Shadow Studies",
        "",
        f"- Study: `{payload.get('schema_version')}`; fresh collection begins "
        f"**{payload.get('fresh_start_date')}**.",
        "- Research only: these cohorts do not block, resize, or alter any live trade.",
        f"- Comparable historical baseline: {payload.get('historical_comparable_trades', 0)} trades; "
        f"fresh sample: {payload.get('fresh_comparable_trades', 0)}.",
        "",
    ]
    if payload.get("conclusions_withheld"):
        lines.extend([
            "**Conclusions withheld because canonical broker reconciliation is incomplete.**",
            "",
        ])

    lines.extend([
        "### Today's Recorded Metrics",
        "",
        "| Order | Direction | Phase | CQ | MAS | ABS | CONF | Shadow Cohort | P&L |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ])
    today_rows = payload.get("today_trades") or []
    if today_rows:
        for trade in today_rows:
            cohorts = []
            if (
                trade.get("phase") == "EARLY_CONTINUATION"
                and float(trade.get("conf") or 0) >= 4.0
            ):
                cohorts.append("EC + CONF≥4 candidate")
            else:
                cohorts.append("primary comparator")
            if trade.get("phase") == "ESTABLISHED":
                cohorts.append(f"Established {trade.get('direction')} shadow reject")
            lines.append(
                f"| {trade.get('broker_entry_order_id')} | {trade.get('direction')} "
                f"| {trade.get('phase')} | {float(trade.get('cq') or 0):.2f} "
                f"| {float(trade.get('mas') or 0):.2f} | {float(trade.get('abs') or 0):.2f} "
                f"| {float(trade.get('conf') or 0):.2f} | {', '.join(cohorts)} "
                f"| ${float(trade.get('pnl_dollars') or 0):.2f} |"
            )
    else:
        lines.append("| — | — | No comparable trades | — | — | — | — | — | $0.00 |")
    lines.append("")

    labels = {
        "early_continuation_conf_4_candidate": "Early Continuation + CONF ≥4",
        "all_other_complete_comparator": "All other complete trades",
        "established_call_shadow_reject": "Established CALL shadow reject",
        "non_established_call_comparator": "Non-Established CALL comparator",
        "established_put_shadow_reject": "Established PUT shadow reject",
        "non_established_put_comparator": "Non-Established PUT comparator",
    }
    for title, key in (
        ("Historical Context", "historical_cohorts"),
        ("Fresh Forward Sample", "fresh_cohorts"),
    ):
        lines.extend([
            f"### {title}",
            "",
            "| Cohort | Trades | W-L | Win Rate | P&L | Average | CALL/PUT |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for name, stats in (payload.get(key) or {}).items():
            win_rate = stats.get("win_rate")
            rate_text = f"{win_rate:.1%}" if win_rate is not None else "N/A"
            average = stats.get("average_pnl_dollars")
            average_text = f"${average:.2f}" if average is not None else "N/A"
            directions = stats.get("directions") or {}
            lines.append(
                f"| {labels.get(name, name)} | {stats.get('trades', 0)} "
                f"| {stats.get('wins', 0)}-{stats.get('losses', 0)} | {rate_text} "
                f"| ${float(stats.get('pnl_dollars') or 0):.2f} | {average_text} "
                f"| {directions.get('CALL', 0)}/{directions.get('PUT', 0)} |"
            )
        lines.append("")

    lines.extend(["### Locked Evidence Gates", ""])
    for name, hypothesis in (payload.get("hypotheses") or {}).items():
        lines.append(f"- **{name}: {hypothesis.get('decision')}**")
        for check, passed in (hypothesis.get("checks") or {}).items():
            lines.append(f"  - {'PASS' if passed else 'WAIT'} — {check}")
    lines.extend([
        "",
        "- A passing gate permits discussion and human review only. It cannot change live admission logic automatically.",
        "",
    ])
    return "\n".join(lines)


def write_entry_quality_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path, Path]:
    trades, coverage = load_study_trades(root=root)
    reconciliation = _load_json(
        root / "reports" / "daily_loss_attribution"
        / f"daily_loss_attribution_{trading_date}.json"
    ).get("reconciliation") or {}
    payload = evaluate_entry_quality_shadow(
        trades,
        trading_date=trading_date,
        reconciliation=reconciliation,
    )
    payload["generated_at"] = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")
    payload["coverage"] = coverage

    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"entry_quality_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_entry_quality_shadow_markdown(payload) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "broker_entry_order_id", "trade_date", "direction", "phase",
            "cq", "mas", "abs", "conf", "pnl_dollars", "fresh",
            "early_continuation_conf_4_candidate", "established_shadow_reject",
        ])
        for trade in trades:
            writer.writerow([
                trade.get("broker_entry_order_id"), trade.get("trade_date"),
                trade.get("direction"), trade.get("phase"), trade.get("cq"),
                trade.get("mas"), trade.get("abs"), trade.get("conf"),
                trade.get("pnl_dollars"),
                int(str(trade.get("trade_date") or "") >= FRESH_START_DATE),
                int(
                    trade.get("phase") == "EARLY_CONTINUATION"
                    and float(trade.get("conf") or 0) >= 4.0
                ),
                int(trade.get("phase") == "ESTABLISHED"),
            ])
    return payload, json_path, csv_path, md_path
