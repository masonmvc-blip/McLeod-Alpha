"""Build the daily research-only Trend Lifecycle V2 outcome report."""

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from strategy.signals import add_indicators
from strategy.trend_lifecycle_v2 import MODEL_VERSION, classify_trend_lifecycle_v2


ROOT = Path(__file__).resolve().parent.parent
EASTERN_TZ = ZoneInfo("America/New_York")
REPORT_DIR = ROOT / "reports" / "daily_trade_learning"
TELEMETRY_DIR = ROOT / "data" / "reports" / "option_quote_telemetry"
DECISION_AUDIT = ROOT / "data" / "reports" / "decision_audit_history.jsonl"
DB_PATH = ROOT / "data" / "mcleod_alpha.db"
ATTRIBUTION_DIR = ROOT / "reports" / "daily_loss_attribution"


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if pd.notna(value) else None


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return _json(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _load_reconciliation(root: Path, trading_date: str) -> dict[str, Any]:
    path = root / "reports" / "daily_loss_attribution" / f"daily_loss_attribution_{trading_date}.json"
    return _read_json(path).get("reconciliation") or {}


def _load_trades(root: Path, trading_date: str) -> list[dict[str, Any]]:
    db_path = root / "data" / "mcleod_alpha.db"
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, entry_time, exit_time, direction, exit_reason,
                   option_symbol, option_entry, option_exit,
                   COALESCE(option_pnl_dollars, pnl, 0.0) AS pnl_dollars,
                   broker_entry_order_id, broker_exit_order_id,
                   mfe_pct, mae_pct, feature_payload
            FROM trade_log
            WHERE substr(entry_time, 1, 10) = ?
              AND broker_entry_order_id IS NOT NULL
              AND trim(broker_entry_order_id) <> ''
              AND broker_exit_order_id IS NOT NULL
              AND trim(broker_exit_order_id) <> ''
              AND option_symbol IS NOT NULL
              AND trim(option_symbol) <> ''
            ORDER BY entry_time, id
            """,
            (trading_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_entry_candles(root: Path, trading_date: str) -> pd.DataFrame:
    by_time: dict[str, dict[str, Any]] = {}
    base = root / "data" / "reports" / "decision_audit_history.jsonl"
    for path in sorted(base.parent.glob(f"{base.name}*")):
        try:
            handle = path.open("r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                if trading_date not in line or '"event_type":"entry_evaluation"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not str(row.get("ts_et") or "").startswith(trading_date):
                    continue
                candle_time = str(row.get("candle_time") or "")
                if not candle_time or not all(
                    _number(row.get(key)) is not None
                    for key in ("spy_open", "spy_high", "spy_low", "spy_close", "spy_volume")
                ):
                    continue
                by_time[candle_time] = {
                    "datetime": candle_time,
                    "open": float(row["spy_open"]),
                    "high": float(row["spy_high"]),
                    "low": float(row["spy_low"]),
                    "close": float(row["spy_close"]),
                    "volume": float(row["spy_volume"]),
                }
    if not by_time:
        return pd.DataFrame()
    frame = pd.DataFrame(by_time.values())
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["datetime"]).sort_values("datetime").drop_duplicates("datetime")
    return add_indicators(frame.set_index("datetime"))


def _lifecycle_at_entry(
    trade: dict[str, Any],
    candles: pd.DataFrame,
) -> tuple[dict[str, Any], str]:
    features = _json(trade.get("feature_payload"))
    captured = features.get("trend_lifecycle_v2_shadow")
    if isinstance(captured, dict) and captured.get("model_version") == MODEL_VERSION:
        return captured, "captured_live"
    if candles.empty:
        return classify_trend_lifecycle_v2(pd.DataFrame(), trade.get("direction")), "unavailable"
    entry = pd.to_datetime(trade.get("entry_time"), utc=True, errors="coerce")
    if pd.isna(entry):
        return classify_trend_lifecycle_v2(pd.DataFrame(), trade.get("direction")), "unavailable"
    history = candles.loc[candles.index < entry]
    if history.empty:
        return classify_trend_lifecycle_v2(pd.DataFrame(), trade.get("direction")), "unavailable"
    return classify_trend_lifecycle_v2(history, trade.get("direction")), "decision_audit_reconstruction"


def _load_quote_cycles(root: Path, trading_date: str) -> dict[str, list[dict[str, Any]]]:
    path = root / "data" / "reports" / "option_quote_telemetry" / f"option_management_cycles_{trading_date}.jsonl"
    grouped: dict[str, list[dict[str, Any]]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return grouped
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        order_id = str(row.get("broker_entry_order_id") or "")
        if not order_id:
            continue
        grouped.setdefault(order_id, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: str(row.get("recorded_at") or ""))
    return grouped


def _first_passage(
    trade: dict[str, Any],
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    entry = _number(trade.get("option_entry"))
    if not entry or not cycles:
        return {
            "status": "UNAVAILABLE",
            "target_before_initial_stop": None,
            "target_6_timestamp": None,
            "initial_stop_cross_timestamp": None,
            "initial_stop": None,
            "initial_stop_source": None,
            "observed_mfe_pct": _number(trade.get("mfe_pct")),
            "observed_mae_pct": _number(trade.get("mae_pct")),
        }
    explicit_stops = [
        _number(row.get("option_initial_stop"))
        for row in cycles
        if _number(row.get("option_initial_stop"))
    ]
    initial_stop = explicit_stops[0] if explicit_stops else _number(cycles[0].get("option_stop"))
    stop_source = "position_initial_stop" if explicit_stops else "first_observed_stop"
    target = entry * 1.06
    target_at = None
    stop_at = None
    prices: list[float] = []
    for row in cycles:
        price = _number(row.get("executable_exit_price"))
        if price is None:
            continue
        prices.append(price)
        timestamp = row.get("recorded_at")
        if target_at is None and price >= target:
            target_at = timestamp
        if initial_stop and stop_at is None and price <= initial_stop:
            stop_at = timestamp
    if target_at and stop_at:
        if str(target_at) < str(stop_at):
            status, before = "TARGET_FIRST", True
        elif str(stop_at) < str(target_at):
            status, before = "STOP_FIRST", False
        else:
            status, before = "SIMULTANEOUS", None
    elif target_at:
        status, before = "TARGET_ONLY", True
    elif stop_at:
        status, before = "STOP_ONLY", False
    else:
        # The chronological quote series is present and neither barrier was
        # observed. The falsifiable "+6% before initial stop" outcome is false.
        status, before = "NEITHER_OBSERVED", False
    observed_mfe = ((max(prices) - entry) / entry * 100.0) if prices else None
    observed_mae = ((min(prices) - entry) / entry * 100.0) if prices else None
    return {
        "status": status,
        "target_before_initial_stop": before,
        "target_6_timestamp": target_at,
        "initial_stop_cross_timestamp": stop_at,
        "initial_stop": round(initial_stop, 4) if initial_stop else None,
        "initial_stop_source": stop_source if initial_stop else None,
        "observed_mfe_pct": round(observed_mfe, 4) if observed_mfe is not None else None,
        "observed_mae_pct": round(observed_mae, 4) if observed_mae is not None else None,
    }


def _phase_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        phase = str((row.get("lifecycle_v2") or {}).get("phase") or "UNKNOWN")
        bucket = summary.setdefault(
            phase,
            {"trades": 0, "wins": 0, "pnl": 0.0, "target_first": 0, "known_first_passage": 0},
        )
        bucket["trades"] += 1
        pnl = _number(row.get("pnl_dollars")) or 0.0
        bucket["pnl"] += pnl
        bucket["wins"] += int(pnl > 0)
        before = (row.get("first_passage") or {}).get("target_before_initial_stop")
        if before is not None:
            bucket["known_first_passage"] += 1
            bucket["target_first"] += int(before is True)
    for bucket in summary.values():
        bucket["pnl"] = round(bucket["pnl"], 2)
        bucket["win_rate"] = round(bucket["wins"] / bucket["trades"], 4) if bucket["trades"] else 0.0
        known = bucket["known_first_passage"]
        bucket["target_first_rate"] = round(bucket["target_first"] / known, 4) if known else None
    return summary


def build_trend_lifecycle_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    reconciliation = _load_reconciliation(root, trading_date)
    trades = _load_trades(root, trading_date)
    candles = _load_entry_candles(root, trading_date)
    quote_cycles = _load_quote_cycles(root, trading_date)
    reviewed: list[dict[str, Any]] = []
    for trade in trades:
        lifecycle, provenance = _lifecycle_at_entry(trade, candles)
        features = _json(trade.get("feature_payload"))
        v1_phase = features.get("momentum_phase") or (features.get("trend_stage") or {}).get("label")
        order_id = str(trade.get("broker_entry_order_id") or "")
        cycles = quote_cycles.get(order_id, [])
        if not cycles:
            # The live position can retain the submitted parent order while
            # canonical reconciliation stores the broker's filled child order.
            # Join that case by contract plus nearest observed management time.
            entry_at = pd.to_datetime(trade.get("entry_time"), utc=True, errors="coerce")
            candidates: list[tuple[float, list[dict[str, Any]]]] = []
            for candidate_rows in quote_cycles.values():
                if not candidate_rows:
                    continue
                if str(candidate_rows[0].get("option_symbol") or "") != str(trade.get("option_symbol") or ""):
                    continue
                observed_at = pd.to_datetime(
                    candidate_rows[0].get("recorded_at"), utc=True, errors="coerce"
                )
                if pd.isna(entry_at) or pd.isna(observed_at):
                    continue
                candidates.append((abs((observed_at - entry_at).total_seconds()), candidate_rows))
            if candidates and min(candidates, key=lambda item: item[0])[0] <= 600:
                cycles = min(candidates, key=lambda item: item[0])[1]
        reviewed.append(
            {
                "trade_id": int(trade["id"]),
                "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"),
                "direction": trade.get("direction"),
                "option_symbol": trade.get("option_symbol"),
                "broker_entry_order_id": str(trade.get("broker_entry_order_id") or ""),
                "broker_exit_order_id": str(trade.get("broker_exit_order_id") or ""),
                "pnl_dollars": round(_number(trade.get("pnl_dollars")) or 0.0, 2),
                "exit_reason": trade.get("exit_reason"),
                "v1_phase": v1_phase,
                "lifecycle_v2": lifecycle,
                "lifecycle_v2_provenance": provenance,
                "first_passage": _first_passage(
                    trade,
                    cycles,
                ),
            }
        )

    phase_summary = _phase_summary(reviewed)
    prior_rows: list[dict[str, Any]] = []
    report_dir = root / "reports" / "daily_trade_learning"
    for path in sorted(report_dir.glob("trend_lifecycle_shadow_????-??-??.json")):
        if path.name == f"trend_lifecycle_shadow_{trading_date}.json":
            continue
        prior = _read_json(path)
        if str(prior.get("trading_date") or "") >= trading_date:
            continue
        prior_rows.extend(prior.get("trades") or [])
    rolling_rows = prior_rows + reviewed
    rolling_phase_summary = _phase_summary(rolling_rows)
    valid = [row for row in rolling_rows if (row["lifecycle_v2"] or {}).get("valid")]
    known_passage = [
        row for row in rolling_rows
        if (row["first_passage"] or {}).get("target_before_initial_stop") is not None
    ]
    phase_minimum = min(
        (stats["trades"] for phase, stats in rolling_phase_summary.items() if phase != "UNKNOWN"),
        default=0,
    )
    reconciliation_complete = bool(reconciliation.get("complete"))
    promotion_checks = {
        "canonical_reconciliation_complete": reconciliation_complete,
        "minimum_total_sample_30": len(valid) >= 30,
        "minimum_per_observed_phase_10": phase_minimum >= 10,
        "first_passage_coverage_80pct": (
            (len(known_passage) / len(rolling_rows)) >= 0.80 if rolling_rows else False
        ),
    }
    promotion_ready = all(promotion_checks.values())
    return {
        "schema_version": "trend-lifecycle-shadow-review.v1",
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "trading_date": trading_date,
        "generated_at": datetime.now(EASTERN_TZ).isoformat(timespec="seconds"),
        "reconciliation": reconciliation,
        "conclusions_withheld": not reconciliation_complete,
        "sample_size": len(reviewed),
        "valid_v2_sample_size": len([
            row for row in reviewed if (row["lifecycle_v2"] or {}).get("valid")
        ]),
        "first_passage_known_sample_size": len([
            row for row in reviewed
            if (row["first_passage"] or {}).get("target_before_initial_stop") is not None
        ]),
        "phase_summary": phase_summary,
        "rolling": {
            "sample_size": len(rolling_rows),
            "valid_v2_sample_size": len(valid),
            "first_passage_known_sample_size": len(known_passage),
            "phase_summary": rolling_phase_summary,
        },
        "promotion_gate": {
            "ready": promotion_ready,
            "checks": promotion_checks,
            "decision": "ELIGIBLE_FOR_HUMAN_REVIEW" if promotion_ready else "COLLECT_MORE_DATA",
            "automatic_live_change_allowed": False,
        },
        "trades": reviewed,
    }


def render_trend_lifecycle_shadow_markdown(payload: dict[str, Any]) -> str:
    reconciliation = payload.get("reconciliation") or {}
    lines = [
        "## Trend Lifecycle V2 Shadow Review",
        "",
        f"- Model: `{payload.get('model_version')}` (research only; no live decision impact)",
        f"- Sample today: {payload.get('sample_size', 0)} broker-backed trades; "
        f"{payload.get('valid_v2_sample_size', 0)} with valid V2 labels",
        f"- Reconciliation: {'COMPLETE' if reconciliation.get('complete') else 'INCOMPLETE'} "
        f"(broker/canonical {reconciliation.get('broker_trades_today', '?')}/"
        f"{reconciliation.get('canonical_completed_trades', '?')}, "
        f"P&L variance ${float(reconciliation.get('pnl_variance_dollars') or 0):.2f}, "
        f"pending outbox {reconciliation.get('pending_outbox_entries', '?')})",
        "",
    ]
    if payload.get("conclusions_withheld"):
        lines.extend([
            "**Trading conclusions withheld because canonical reconciliation is incomplete.**",
            "",
        ])
    lines.extend([
        "| Trade | Direction | V1 Phase | V2 Phase | Leg | Momentum | P&L | +6% vs Initial Stop |",
        "| ---: | --- | --- | --- | ---: | --- | ---: | --- |",
    ])
    for row in payload.get("trades") or []:
        lifecycle = row.get("lifecycle_v2") or {}
        passage = row.get("first_passage") or {}
        lines.append(
            f"| {row.get('trade_id')} | {row.get('direction')} | {row.get('v1_phase') or 'UNKNOWN'} "
            f"| {lifecycle.get('phase') or 'UNKNOWN'} | {lifecycle.get('active_leg') or 0} "
            f"| {lifecycle.get('momentum_state') or 'UNKNOWN'} | ${float(row.get('pnl_dollars') or 0):.2f} "
            f"| {passage.get('status') or 'UNAVAILABLE'} |"
        )
    lines.extend([
        "",
        "### V2 Phase Outcomes",
        "",
        "| V2 Phase | Trades | Wins | Win Rate | P&L | Known First Passage | +6% First |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for phase, stats in sorted((payload.get("phase_summary") or {}).items()):
        rate = stats.get("target_first_rate")
        lines.append(
            f"| {phase} | {stats['trades']} | {stats['wins']} | {stats['win_rate']:.1%} "
            f"| ${stats['pnl']:.2f} | {stats['known_first_passage']} "
            f"| {rate:.1%} |" if rate is not None else
            f"| {phase} | {stats['trades']} | {stats['wins']} | {stats['win_rate']:.1%} "
            f"| ${stats['pnl']:.2f} | {stats['known_first_passage']} | N/A |"
        )
    gate = payload.get("promotion_gate") or {}
    lines.extend([
        "",
        "### Evidence Gate",
        "",
        f"- Rolling sample: {(payload.get('rolling') or {}).get('valid_v2_sample_size', 0)} valid trades; "
        f"{(payload.get('rolling') or {}).get('first_passage_known_sample_size', 0)} with known first-passage outcomes.",
        f"- Decision: **{gate.get('decision', 'COLLECT_MORE_DATA')}**",
        "- Minimum before considering a live change: 30 valid trades, 10 observations per observed "
        "phase, at least 80% first-passage coverage, and exact broker reconciliation.",
        "- Even after the gate passes, any implementation requires a separate human-reviewed change; "
        "this shadow tracker never promotes itself.",
        "",
    ])
    return "\n".join(lines)


def write_trend_lifecycle_shadow_report(
    trading_date: str,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path, Path, Path]:
    payload = build_trend_lifecycle_shadow_report(trading_date, root=root)
    report_dir = root / "reports" / "daily_trade_learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = f"trend_lifecycle_shadow_{trading_date}"
    json_path = report_dir / f"{stem}.json"
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_trend_lifecycle_shadow_markdown(payload) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "trade_id", "entry_time", "direction", "v1_phase", "v2_phase",
            "v2_active_leg", "v2_momentum_state", "pnl_dollars",
            "first_passage_status", "target_before_initial_stop", "v2_provenance",
        ])
        for row in payload.get("trades") or []:
            lifecycle = row.get("lifecycle_v2") or {}
            passage = row.get("first_passage") or {}
            writer.writerow([
                row.get("trade_id"), row.get("entry_time"), row.get("direction"),
                row.get("v1_phase"), lifecycle.get("phase"), lifecycle.get("active_leg"),
                lifecycle.get("momentum_state"), row.get("pnl_dollars"), passage.get("status"),
                passage.get("target_before_initial_stop"), row.get("lifecycle_v2_provenance"),
            ])
    return payload, json_path, csv_path, md_path
