"""Daily diagnostic loss attribution and conservative negative-edge warnings.

This module is reporting-only. It never changes orders, eligibility, sizing, or
configuration. Attribution labels are evidence flags, not causal conclusions.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from engine.memory import Memory


MINIMUM_SETUP_TRADES = 10
MINIMUM_SETUP_DAYS = 3
ROLLING_TRADE_LIMIT = 200


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _broker_backed(row: dict[str, Any]) -> bool:
    return bool(
        str(row.get("broker_entry_order_id") or "").strip()
        and str(row.get("broker_exit_order_id") or "").strip()
        and str(row.get("option_symbol") or "").strip()
    )


def _recorded_pnl(row: dict[str, Any]) -> float | None:
    value = row.get("option_pnl_dollars")
    if value is None:
        value = row.get("pnl")
    return _number(value)


def _setup_key(row: dict[str, Any], feature: dict[str, Any]) -> str:
    direction = str(row.get("direction") or feature.get("direction") or "UNKNOWN").upper()
    regime = str(feature.get("regime") or "UNCLASSIFIED").upper()
    admit = feature.get("accepted_breakout_admit")
    if admit is True:
        setup = "ACCEPTED_BREAKOUT"
    elif admit is False:
        setup = "UNCONFIRMED_BREAKOUT"
    else:
        setup = "BASELINE"
    return f"{setup}:{direction}:{regime}"


def _loss_flags(row: dict[str, Any], feature: dict[str, Any]) -> list[dict[str, str]]:
    """Return provisional evidence flags for a losing trade."""
    flags: list[dict[str, str]] = []
    direction = str(row.get("direction") or feature.get("direction") or "").upper()
    regime = str(feature.get("regime") or "").upper()
    support_resistance = feature.get("support_resistance") or {}

    if feature.get("accepted_breakout_admit") is False:
        flags.append({
            "category": "confirmation",
            "evidence": str(feature.get("accepted_breakout_reason") or "observer_rejected"),
        })

    if any(label in regime for label in ("RANGE", "CHOP", "CONGEST")):
        flags.append({"category": "congestion", "evidence": f"regime={regime}"})

    room_key = "distance_to_resistance_pct" if direction == "CALL" else "distance_to_support_pct"
    room = _number(support_resistance.get(room_key))
    if room is not None and 0.0 <= room <= 0.05:
        flags.append({"category": "structural_room", "evidence": f"{room_key}={room:.4f}"})

    exit_reason = str(row.get("exit_reason") or "").upper()
    if "STOP" in exit_reason:
        flags.append({"category": "risk", "evidence": f"exit_reason={exit_reason}"})

    exit_efficiency = _number(row.get("exit_efficiency_pct"))
    peak_capture = _number(row.get("peak_capture_pct"))
    if (exit_efficiency is not None and exit_efficiency < 25.0) or (
        peak_capture is not None and peak_capture < 25.0
    ):
        flags.append({
            "category": "execution",
            "evidence": f"exit_efficiency={exit_efficiency}, peak_capture={peak_capture}",
        })

    if not flags:
        flags.append({
            "category": "signal",
            "evidence": "loss not explained by available confirmation, regime, room, execution, or stop facts",
        })
    return flags


def _conservative_upper_bound(values: list[float]) -> float | None:
    """Conservative mean upper bound used only for an operator warning.

    The multiplier is deliberately wider than a normal 95% one-sided bound for
    the minimum sample. This is not a promotion test and never changes trading.
    """
    if len(values) < MINIMUM_SETUP_TRADES:
        return None
    if len(values) == 1:
        return values[0]
    multiplier = 2.262 if len(values) < 20 else 2.086 if len(values) < 30 else 2.042 if len(values) < 60 else 2.0
    return mean(values) + multiplier * stdev(values) / math.sqrt(len(values))


def build_loss_attribution(
    rows: Iterable[dict[str, Any]],
    *,
    trading_date: str,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = list(rows)
    today = [row for row in normalized if str(row.get("trade_date") or "") == trading_date]
    broker_today = [row for row in today if _broker_backed(row) and _recorded_pnl(row) is not None]

    category_counts: dict[str, int] = defaultdict(int)
    attributed_losses: list[dict[str, Any]] = []
    for row in broker_today:
        pnl = _recorded_pnl(row)
        if pnl is None or pnl >= 0:
            continue
        feature = _payload(row.get("feature_payload") or row.get("entry_diagnostic_snapshot"))
        flags = _loss_flags(row, feature)
        for flag in flags:
            category_counts[flag["category"]] += 1
        attributed_losses.append({
            "trade_id": row.get("id"),
            "direction": row.get("direction"),
            "option_symbol": row.get("option_symbol"),
            "recorded_pnl_dollars": round(pnl, 2),
            "setup": _setup_key(row, feature),
            "flags": flags,
        })

    setup_values: dict[str, list[float]] = defaultdict(list)
    setup_days: dict[str, set[str]] = defaultdict(set)
    for row in normalized:
        pnl = _recorded_pnl(row)
        if not _broker_backed(row) or pnl is None:
            continue
        feature = _payload(row.get("feature_payload") or row.get("entry_diagnostic_snapshot"))
        key = _setup_key(row, feature)
        setup_values[key].append(pnl)
        setup_days[key].add(str(row.get("trade_date") or ""))

    setups: list[dict[str, Any]] = []
    warning_setups: list[str] = []
    reconciliation = dict(reconciliation or {})
    reconciliation_complete = bool(
        reconciliation.get("healthy")
        and reconciliation.get("count_reconciled")
        and reconciliation.get("pnl_reconciled")
        and int(reconciliation.get("pending_outbox_entries") or 0) == 0
    )
    for key in sorted(setup_values):
        values = setup_values[key]
        upper_bound = _conservative_upper_bound(values)
        enough_days = len(setup_days[key] - {""}) >= MINIMUM_SETUP_DAYS
        convincingly_negative = bool(
            reconciliation_complete and upper_bound is not None and enough_days and upper_bound < 0.0
        )
        if convincingly_negative:
            warning_setups.append(key)
        setups.append({
            "setup": key,
            "completed_trades": len(values),
            "trading_days": len(setup_days[key] - {""}),
            "recorded_expectancy_dollars": round(mean(values), 2),
            "conservative_expectancy_upper_bound_dollars": (
                round(upper_bound, 2) if upper_bound is not None else None
            ),
            "convincingly_negative_warning": convincingly_negative,
        })

    today_pnl = sum(_recorded_pnl(row) or 0.0 for row in broker_today)
    return {
        "schema_version": "daily-loss-attribution.v1",
        "trading_date": trading_date,
        "generated_at": datetime.now().astimezone().isoformat(),
        "diagnostic_only": True,
        "automatic_live_change": False,
        "pnl_basis": (
            "Recorded broker-backed realized P&L. If fees are absent, a negative "
            "pre-fee upper bound remains negative after nonnegative costs."
        ),
        "attribution_boundary": (
            "Flags identify available evidence, may be multi-label, and do not establish causality."
        ),
        "learning_status": "eligible_for_diagnostic_conclusions" if reconciliation_complete else "withheld_incomplete_reconciliation",
        "reconciliation": {
            "complete": reconciliation_complete,
            **reconciliation,
        },
        "today": {
            "all_recorded_trades": len(today),
            "broker_backed_trades": len(broker_today),
            "excluded_unlinked_or_missing_pnl": len(today) - len(broker_today),
            "broker_backed_losses": len(attributed_losses),
            "recorded_pnl_dollars": round(today_pnl, 2),
            "loss_category_counts": dict(sorted(category_counts.items())),
            "losses": attributed_losses,
        },
        "rolling_setup_evidence": setups,
        "operator_warning": {
            "active": bool(warning_setups),
            "setups": warning_setups,
            "minimum_trades": MINIMUM_SETUP_TRADES,
            "minimum_trading_days": MINIMUM_SETUP_DAYS,
            "reason": (
                "Conservative expectancy upper bound is below zero."
                if warning_setups
                else (
                    "Learning conclusions are withheld because broker count/P&L reconciliation is incomplete."
                    if not reconciliation_complete
                    else "No setup crosses the conservative negative-evidence threshold."
                )
            ),
        },
    }


def load_rows(db_path: Path, trading_date: str, *, limit: int = ROLLING_TRADE_LIMIT) -> list[dict[str, Any]]:
    """Load canonical completed trades; trade_log is not a learning source."""
    memory = Memory(db_path=db_path)
    rows = memory.load_completed_trades("2020-01-01", trading_date)
    normalized = []
    for trade in rows[-limit:]:
        row = dict(trade)
        row["id"] = row.get("canonical_trade_id")
        row["trade_date"] = row.get("trade_date") or str(row.get("entry_time") or "")[:10]
        normalized.append(row)
    return normalized


def fetch_reconciliation_health(
    trading_date: str | None = None,
    url: str = "http://127.0.0.1:5001/api/trade-reconciliation-health",
) -> dict[str, Any]:
    """Trigger broker reconciliation through the existing local Cockpit boundary."""
    try:
        if trading_date:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode({'date': trading_date})}"
        with urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        return {"healthy": False, "error": f"reconciliation_health_unavailable:{type(exc).__name__}"}


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trading_date = str(report["trading_date"])
    json_path = output_dir / f"daily_loss_attribution_{trading_date}.json"
    md_path = output_dir / f"daily_loss_attribution_{trading_date}.md"
    latest_json = output_dir / "latest_daily_loss_attribution.json"
    latest_md = output_dir / "latest_daily_loss_attribution.md"

    json_text = json.dumps(report, indent=2) + "\n"
    warning = report["operator_warning"]
    today = report["today"]
    lines = [
        f"# Daily Loss Attribution: {trading_date}",
        "",
        f"- Diagnostic only: `{report['diagnostic_only']}`",
        f"- Learning status: `{report['learning_status']}`",
        f"- Reconciliation complete: `{report['reconciliation']['complete']}`",
        f"- All recorded trades: {today['all_recorded_trades']}",
        f"- Broker-backed trades: {today['broker_backed_trades']}",
        f"- Excluded unlinked/missing-P&L trades: {today['excluded_unlinked_or_missing_pnl']}",
        f"- Broker-backed losses: {today['broker_backed_losses']}",
        f"- Recorded P&L: `${today['recorded_pnl_dollars']:.2f}`",
        f"- Negative-edge warning: `{'ACTIVE' if warning['active'] else 'CLEAR'}`",
        "",
        "## Loss Categories",
        "",
    ]
    counts = today["loss_category_counts"]
    lines.extend([f"- {key}: {value}" for key, value in counts.items()] or ["- No broker-backed losses."])
    lines.extend(["", "## Rolling Setup Evidence", ""])
    for setup in report["rolling_setup_evidence"]:
        lines.append(
            f"- {setup['setup']}: n={setup['completed_trades']}, "
            f"days={setup['trading_days']}, expectancy=${setup['recorded_expectancy_dollars']:.2f}, "
            f"upper_bound={setup['conservative_expectancy_upper_bound_dollars']}, "
            f"warning={setup['convincingly_negative_warning']}"
        )
    lines.extend(["", f"> {report['attribution_boundary']}", ""])
    md_text = "\n".join(lines)

    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    latest_md.write_text(md_text, encoding="utf-8")
    return json_path, md_path


def maybe_send_operator_warning(
    report: dict[str, Any],
    *,
    state_path: Path,
    alert_sender: Any = None,
) -> bool:
    warning = report.get("operator_warning") or {}
    if not warning.get("active"):
        return False
    signature = f"{report.get('trading_date')}:{','.join(warning.get('setups') or [])}"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    if state.get("signature") == signature:
        return False

    if alert_sender is None:
        from execution.sms_alerts import send_emergency_alert
        alert_sender = send_emergency_alert
    delivered = bool(alert_sender(
        "NEGATIVE SETUP EXPECTANCY WARNING",
        (
            f"Date: {report.get('trading_date')}\n"
            f"Setups: {', '.join(warning.get('setups') or [])}\n"
            "Diagnostic only; review before any manual change."
        ),
    ))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"signature": signature, "alert_delivered": delivered}, indent=2) + "\n",
        encoding="utf-8",
    )
    return delivered
