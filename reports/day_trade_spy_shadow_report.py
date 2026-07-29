"""Historical backfill and daily review for the Day Trade SPY shadow suite."""

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from reports.trend_lifecycle_shadow_report import _first_passage
from strategy.day_trade_spy_shadow_suite import (
    MODEL_VERSION,
    evaluate_day_trade_spy_shadow_suite,
)
from strategy.signals import add_indicators


ROOT = Path(__file__).resolve().parents[1]
EASTERN_TZ = ZoneInfo("America/New_York")
TEST_NAMES = (
    "accepted_break",
    "structural_room_execution",
    "opening_vs_later_entry",
    "congestion_reentry",
    "premise_reset_no_repair",
)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _load_trades(root: Path, trading_date: str) -> list[dict[str, Any]]:
    db_path = root / "data" / "mcleod_alpha.db"
    if not db_path.exists() or not db_path.stat().st_size:
        return []
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "trade_log"):
            return []
        columns = {row[1] for row in connection.execute("PRAGMA table_info(trade_log)")}
        wanted = [
            name for name in (
                "id", "entry_time", "exit_time", "direction", "exit_reason",
                "option_symbol", "option_entry", "option_exit", "option_pnl_dollars",
                "pnl", "broker_entry_order_id", "broker_exit_order_id", "mfe_pct",
                "mae_pct", "feature_payload", "quantity", "option_quantity",
                "stop", "target",
            )
            if name in columns
        ]
        rows = connection.execute(
            f"""
            SELECT {", ".join(wanted)}
            FROM trade_log
            WHERE substr(entry_time, 1, 10) = ?
              AND trim(COALESCE(broker_entry_order_id, '')) <> ''
              AND trim(COALESCE(broker_exit_order_id, '')) <> ''
              AND trim(COALESCE(option_symbol, '')) <> ''
            ORDER BY entry_time, id
            """,
            (trading_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_candles(root: Path, trading_date: str) -> pd.DataFrame:
    base = root / "data" / "reports" / "decision_audit_history.jsonl"
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(base.parent.glob(f"{base.name}*")):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            if trading_date not in line or '"event_type":"entry_evaluation"' not in line:
                continue
            event = _object(line)
            candle_time = str(event.get("candle_time") or "")
            values = [_number(event.get(f"spy_{name}")) for name in ("open", "high", "low", "close", "volume")]
            if not candle_time or any(value is None for value in values):
                continue
            rows[candle_time] = {
                "datetime": candle_time,
                **dict(zip(("open", "high", "low", "close", "volume"), values)),
            }
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows.values())
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["datetime"]).sort_values("datetime").drop_duplicates("datetime")
    return add_indicators(frame.set_index("datetime"))


def _load_quote_cycles(root: Path, trading_date: str) -> dict[str, list[dict[str, Any]]]:
    path = root / "data" / "reports" / "option_quote_telemetry" / f"option_management_cycles_{trading_date}.jsonl"
    grouped: dict[str, list[dict[str, Any]]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return grouped
    for line in lines:
        row = _object(line)
        order_id = str(row.get("broker_entry_order_id") or "")
        if order_id:
            grouped.setdefault(order_id, []).append(row)
    for values in grouped.values():
        values.sort(key=lambda row: str(row.get("recorded_at") or ""))
    return grouped


def _cycles_for_trade(
    trade: dict[str, Any],
    grouped: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    direct = grouped.get(str(trade.get("broker_entry_order_id") or ""), [])
    if direct:
        return direct
    entry_at = pd.to_datetime(trade.get("entry_time"), utc=True, errors="coerce")
    candidates: list[tuple[float, list[dict[str, Any]]]] = []
    for rows in grouped.values():
        if not rows or str(rows[0].get("option_symbol") or "") != str(trade.get("option_symbol") or ""):
            continue
        observed_at = pd.to_datetime(rows[0].get("recorded_at"), utc=True, errors="coerce")
        if pd.isna(entry_at) or pd.isna(observed_at):
            continue
        candidates.append((abs((observed_at - entry_at).total_seconds()), rows))
    if candidates:
        distance, rows = min(candidates, key=lambda item: item[0])
        if distance <= 600:
            return rows
    return []


def _entry_option(trade: dict[str, Any], cycles: list[dict[str, Any]]) -> dict[str, Any]:
    first = cycles[0] if cycles else {}
    entry_quote = _object(
        _object(trade.get("feature_payload")).get("entry_option_quote_snapshot")
    )
    return {
        "symbol": trade.get("option_symbol") or first.get("option_symbol"),
        "bid": entry_quote.get("bid") if entry_quote.get("bid") is not None else first.get("bid"),
        "ask": entry_quote.get("ask") if entry_quote.get("ask") is not None else first.get("ask"),
        "mark": entry_quote.get("mark") if entry_quote.get("mark") is not None else first.get("mark"),
        "last": entry_quote.get("last") if entry_quote.get("last") is not None else first.get("last"),
        "quote_age_seconds": entry_quote.get("quote_age_seconds"),
        "quote_source": entry_quote.get("quote_source"),
        "volume": first.get("volume"),
        "open_interest": first.get("open_interest"),
    }


def _historical_suite(
    trade: dict[str, Any],
    candles: pd.DataFrame,
    cycles: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    features = _object(trade.get("feature_payload"))
    captured = features.get("day_trade_spy_shadow_suite")
    if isinstance(captured, dict) and captured.get("schema_version") == MODEL_VERSION:
        return captured, "captured_live"
    entry_time = pd.to_datetime(trade.get("entry_time"), utc=True, errors="coerce")
    if candles.empty or pd.isna(entry_time):
        history = pd.DataFrame()
        provenance = "UNAVAILABLE"
    else:
        history = candles.loc[candles.index < entry_time]
        provenance = "decision_audit_reconstruction" if not history.empty else "UNAVAILABLE"
    suite = evaluate_day_trade_spy_shadow_suite(
        history,
        str(trade.get("direction") or ""),
        feature_payload=features,
        option=_entry_option(trade, cycles),
        trade_plan={
            "entry": trade.get("option_entry"),
            "stop": (
                features.get("original_stop")
                or trade.get("stop")
                or ((cycles[0] if cycles else {}).get("option_initial_stop"))
                or ((cycles[0] if cycles else {}).get("option_stop"))
            ),
            "target": features.get("original_target") or trade.get("target"),
            "quantity": trade.get("quantity") or trade.get("option_quantity"),
        },
        captured_at=entry_time.to_pydatetime() if not pd.isna(entry_time) else None,
        provenance=provenance,
    )
    return suite, provenance


def _load_opportunities(root: Path, trading_date: str) -> list[dict[str, Any]]:
    path = root / "data" / "reports" / "opportunity_logs" / f"opportunity_setups_{trading_date}.jsonl"
    try:
        rows = [_object(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("event_id") or ""), str(row.get("direction") or ""))
        current = selected.get(key)
        if current is None or (
            row.get("day_trade_spy_shadow_suite")
            and not current.get("day_trade_spy_shadow_suite")
        ):
            selected[key] = row
    return sorted(selected.values(), key=lambda row: (str(row.get("candle_time_et") or ""), str(row.get("direction") or "")))


def _test_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in TEST_NAMES:
        bucket = {
            verdict: {"trades": 0, "wins": 0, "pnl_dollars": 0.0}
            for verdict in ("ADMIT", "REJECT", "DELAY", "TRACK", "UNAVAILABLE")
        }
        for row in rows:
            verdict = str(
                (((row.get("shadow_suite") or {}).get("tests") or {}).get(name) or {}).get("verdict")
                or "UNAVAILABLE"
            )
            if verdict not in bucket:
                verdict = "UNAVAILABLE"
            pnl = _number(row.get("pnl_dollars")) or 0.0
            bucket[verdict]["trades"] += 1
            bucket[verdict]["wins"] += int(pnl > 0)
            bucket[verdict]["pnl_dollars"] += pnl
        for stats in bucket.values():
            stats["pnl_dollars"] = round(stats["pnl_dollars"], 2)
            stats["win_rate"] = (
                round(stats["wins"] / stats["trades"], 4) if stats["trades"] else None
            )
        summary[name] = bucket
    return summary


def build_day_trade_spy_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    trades = _load_trades(root, trading_date)
    candles = _load_candles(root, trading_date)
    quote_cycles = _load_quote_cycles(root, trading_date)
    reviewed: list[dict[str, Any]] = []
    for trade in trades:
        order_id = str(trade.get("broker_entry_order_id") or "")
        cycles = _cycles_for_trade(trade, quote_cycles)
        suite, provenance = _historical_suite(trade, candles, cycles)
        pnl = (
            _number(trade.get("option_pnl_dollars"))
            if trade.get("option_pnl_dollars") is not None
            else _number(trade.get("pnl"))
        ) or 0.0
        reviewed.append({
            "trade_id": trade.get("id"),
            "entry_time": trade.get("entry_time"),
            "exit_time": trade.get("exit_time"),
            "direction": trade.get("direction"),
            "option_symbol": trade.get("option_symbol"),
            "broker_entry_order_id": order_id,
            "broker_exit_order_id": str(trade.get("broker_exit_order_id") or ""),
            "pnl_dollars": round(pnl, 2),
            "exit_reason": trade.get("exit_reason"),
            "shadow_suite": suite,
            "shadow_provenance": provenance,
            "first_passage": _first_passage(trade, cycles),
        })

    reconciliation_path = (
        root / "reports" / "daily_loss_attribution"
        / f"daily_loss_attribution_{trading_date}.json"
    )
    try:
        reconciliation = _object(reconciliation_path.read_text(encoding="utf-8")).get("reconciliation") or {}
    except OSError:
        reconciliation = {}
    opportunities = _load_opportunities(root, trading_date)
    prior_rows: list[dict[str, Any]] = []
    report_dir = root / "reports" / "daily_trade_learning"
    for path in sorted(report_dir.glob("day_trade_spy_shadow_????-??-??.json")):
        if path.name == f"day_trade_spy_shadow_{trading_date}.json":
            continue
        prior = _object(path.read_text(encoding="utf-8"))
        if str(prior.get("trading_date") or "") < trading_date:
            prior_rows.extend(prior.get("trades") or [])
    rolling = prior_rows + reviewed
    valid = [
        row for row in rolling
        if any(
            (((row.get("shadow_suite") or {}).get("tests") or {}).get(name) or {}).get("verdict")
            != "UNAVAILABLE"
            for name in TEST_NAMES
        )
    ]
    known_passage = [
        row for row in rolling
        if (row.get("first_passage") or {}).get("target_before_initial_stop") is not None
    ]
    phase_counts: dict[str, int] = {}
    for row in valid:
        phase = str((row.get("shadow_suite") or {}).get("session_phase") or "UNAVAILABLE")
        if phase != "UNAVAILABLE":
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
    minimum_phase = min(phase_counts.values(), default=0)
    checks = {
        "canonical_reconciliation_complete": bool(reconciliation.get("complete")),
        "minimum_total_sample_50": len(valid) >= 50,
        "minimum_per_observed_phase_10": minimum_phase >= 10,
        "first_passage_coverage_80pct": (
            len(known_passage) / len(rolling) >= 0.80 if rolling else False
        ),
    }
    return {
        "schema_version": "day-trade-spy-shadow-review.v1",
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "automatic_live_change_allowed": False,
        "trading_date": trading_date,
        "generated_at": datetime.now(EASTERN_TZ).isoformat(timespec="seconds"),
        "reconciliation": reconciliation,
        "conclusions_withheld": not bool(reconciliation.get("complete")),
        "sample_size": len(reviewed),
        "evaluated_opportunities": len(opportunities),
        "entered_opportunities": sum(bool(row.get("entered")) for row in opportunities),
        "rejected_opportunities": sum(bool(row.get("rejected")) for row in opportunities),
        "test_summary": _test_summary(reviewed),
        "rolling": {
            "sample_size": len(rolling),
            "valid_sample_size": len(valid),
            "known_first_passage": len(known_passage),
            "session_phase_counts": phase_counts,
            "test_summary": _test_summary(rolling),
        },
        "promotion_gate": {
            "ready": all(checks.values()),
            "checks": checks,
            "decision": "ELIGIBLE_FOR_HUMAN_REVIEW" if all(checks.values()) else "COLLECT_MORE_DATA",
            "automatic_live_change_allowed": False,
        },
        "opportunities": opportunities,
        "trades": reviewed,
    }


def render_day_trade_spy_shadow_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## Day Trade SPY Five-Test Shadow Review",
        "",
        f"- Model: `{payload.get('model_version')}`",
        f"- Broker-backed trades today: {payload.get('sample_size', 0)}",
        f"- Evaluated opportunities: {payload.get('evaluated_opportunities', 0)} "
        f"({payload.get('entered_opportunities', 0)} entered; "
        f"{payload.get('rejected_opportunities', 0)} rejected)",
        "- Research only: no entry, exit, sizing, stop, target, repair, or order behavior is changed.",
        "",
    ]
    if payload.get("conclusions_withheld"):
        lines.extend([
            "**Conclusions withheld because canonical broker reconciliation is incomplete.**",
            "",
        ])
    lines.extend([
        "| Test | Admit | Reject | Delay | Track | Unavailable |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for name in TEST_NAMES:
        stats = (payload.get("test_summary") or {}).get(name) or {}
        lines.append(
            f"| {name} | {stats.get('ADMIT', {}).get('trades', 0)} "
            f"| {stats.get('REJECT', {}).get('trades', 0)} "
            f"| {stats.get('DELAY', {}).get('trades', 0)} "
            f"| {stats.get('TRACK', {}).get('trades', 0)} "
            f"| {stats.get('UNAVAILABLE', {}).get('trades', 0)} |"
        )
    gate = payload.get("promotion_gate") or {}
    lines.extend([
        "",
        "### Evidence Gate",
        "",
        f"- Decision: **{gate.get('decision', 'COLLECT_MORE_DATA')}**",
        "- Requires 50 valid trades, 10 per observed session phase, 80% known "
        "first-passage coverage, and exact broker reconciliation.",
        "- Passing this gate only permits human review and a separately certified "
        "implementation. Automatic live deployment is prohibited.",
        "",
    ])
    return "\n".join(lines)


def write_day_trade_spy_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path, Path]:
    payload = build_day_trade_spy_shadow_report(trading_date, root=root)
    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"day_trade_spy_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_day_trade_spy_shadow_markdown(payload) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "trade_id", "entry_time", "direction", "option_symbol",
            "broker_entry_order_id", "pnl_dollars", "shadow_provenance",
            *TEST_NAMES, "first_passage_status",
        ])
        for row in payload.get("trades") or []:
            tests = (row.get("shadow_suite") or {}).get("tests") or {}
            writer.writerow([
                row.get("trade_id"), row.get("entry_time"), row.get("direction"),
                row.get("option_symbol"), row.get("broker_entry_order_id"),
                row.get("pnl_dollars"), row.get("shadow_provenance"),
                *[(tests.get(name) or {}).get("verdict") for name in TEST_NAMES],
                (row.get("first_passage") or {}).get("status"),
            ])
    return payload, json_path, csv_path, md_path
