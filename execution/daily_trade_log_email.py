"""Automatic daily trade-log export and email delivery.

Runs as a lightweight periodic check from the live monitor loop.

Behavior:
- Weekdays only.
- Default send time: 3:01 PM Central.
- Early-close days: send 5 minutes after regular market close.
- Sends once per trading day.
- On export/email failure, retries once.
- Exports two files:
  - daily_trade_log_<YYYY-MM-DD>.csv
  - daily_trade_review_data_<YYYY-MM-DD>.json
"""

import csv
import json
import os
import re
import smtplib
import sqlite3
import subprocess
from datetime import date, datetime, time as dt_time, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from schwab.auth import easy_client
from reports.daily_opportunity_review import build_daily_opportunity_review

DB_PATH = Path("data/mcleod_alpha.db")
STATE_PATH = Path("data/daily_trade_log_email_state.json")
OUTPUT_DIR = Path("data/reports/trade_logs")
BOT_LOG_PATH = Path("bot_output.log")
DELIVERY_LOG_PATH = Path("data/reports/trade_logs/daily_trade_log_delivery.log")

CENTRAL_TZ = ZoneInfo("America/Chicago")
EASTERN_TZ = ZoneInfo("America/New_York")

_NEGATIVE_REASON_KEYS = {
    "volume_weakening_bullish_move",
    "volume_weakening_bearish_move",
}


def _load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


_load_dotenv_if_present()


def _enabled() -> bool:
    return os.getenv("DAILY_TRADE_LOG_EMAIL_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _transport() -> str:
    return (
        os.getenv("DAILY_TRADE_LOG_EMAIL_TRANSPORT", "").strip().lower()
        or os.getenv("DAILY_PNL_EMAIL_TRANSPORT", "mailapp").strip().lower()
    )


def _recipient() -> str:
    return (
        os.getenv("DAILY_TRADE_LOG_TO_EMAIL", "").strip()
        or os.getenv("DAILY_PNL_TO_EMAIL", "").strip()
        or os.getenv("SMTP_FROM", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
        or "MasonMVC@gmail.com"
    )


def _configured_send_time_ct() -> dt_time:
    raw = os.getenv("DAILY_TRADE_LOG_SEND_TIME_CT", "15:01").strip()
    try:
        hh, mm = raw.split(":", 1)
        return dt_time(int(hh), int(mm))
    except Exception:
        return dt_time(15, 1)


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _parse_iso(value: Any) -> Optional[datetime]:
    text = _to_iso(value)
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and (text[-5] in "+-") and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]

    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EASTERN_TZ)
    return parsed


def _table_columns(table_name: str) -> set:
    if not DB_PATH.exists():
        return set()
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _is_placeholder_option_symbol(symbol: Any) -> bool:
    text = str(symbol or "").strip().upper()
    if not text:
        return False

    if text in {"SPY_CALL", "SPY_PUT", "SPY CALL", "SPY PUT", "SPY"}:
        return True

    if re.match(r"^SPY\s+\d{2}-\d{2}-\d{2}\s+[CP]\d+$", text):
        return True

    return False


def _filter_placeholder_trade_rows(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in trades:
        if _is_placeholder_option_symbol(row.get("option_symbol")):
            continue
        out.append(row)
    return out


def _append_delivery_log(line: str) -> None:
    try:
        DELIVERY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DELIVERY_LOG_PATH.open("a") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


def _process_pending_verification(state: Dict[str, Any], now_ct: datetime) -> None:
    due_text = str(state.get("verification_due_at") or "").strip()
    already_done = bool(state.get("verification_done"))
    if not due_text or already_done:
        return

    due_dt = _parse_iso(due_text)
    if due_dt is None:
        state["verification_done"] = True
        _save_state(state)
        return

    now_local = now_ct if now_ct.tzinfo is not None else now_ct.replace(tzinfo=CENTRAL_TZ)
    if now_local < due_dt.astimezone(CENTRAL_TZ):
        return

    csv_path = Path(str(state.get("last_csv_path") or "")) if state.get("last_csv_path") else None
    json_path = Path(str(state.get("last_json_path") or "")) if state.get("last_json_path") else None
    csv_exists = bool(csv_path and csv_path.exists())
    json_exists = bool(json_path and json_path.exists())

    verification_line = (
        f"{datetime.now(tz=CENTRAL_TZ).isoformat()} | verification"
        f" | date={state.get('last_sent_date') or state.get('attempt_date') or ''}"
        f" | recipient={state.get('last_to_email') or _recipient()}"
        f" | attempt={state.get('attempt_count') or 0}"
        f" | csv_exists={csv_exists}"
        f" | json_exists={json_exists}"
        f" | csv={state.get('last_csv_path') or ''}"
        f" | json={state.get('last_json_path') or ''}"
    )
    _append_delivery_log(verification_line)

    state["verification_done"] = True
    state["verification_done_at"] = datetime.now(tz=CENTRAL_TZ).isoformat()
    _save_state(state)


def _bot_order_ids_from_audit() -> set:
    if not DB_PATH.exists():
        return set()

    cols = _table_columns("bot_order_audit")
    if not cols:
        return set()

    out = set()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT order_id FROM bot_order_audit").fetchall()
        for row in rows:
            order_id = str(row["order_id"] or "").strip()
            if order_id:
                out.add(order_id)
    return out


def _fetch_trades_for_date(trade_date: str) -> List[Dict[str, Any]]:
    if not DB_PATH.exists():
        return []

    cols = _table_columns("trade_log")
    if not cols:
        return []

    pnl_expr = "COALESCE(option_pnl_dollars, pnl, 0)"

    query = f"""
    SELECT
        id,
        entry_time,
        exit_time,
        direction,
        exit_reason,
        option_symbol,
        option_entry,
        option_exit,
        option_quantity,
        option_pnl_pct,
        {pnl_expr} AS dollar_pnl,
        broker_entry_order_id,
        broker_exit_order_id,
        feature_payload,
        entry_diagnostic_snapshot,
        exit_diagnostic_snapshot
    FROM trade_log
    WHERE substr(entry_time, 1, 10) = ?
    ORDER BY entry_time ASC
    """

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(row) for row in con.execute(query, (trade_date,)).fetchall()]

    return _filter_placeholder_trade_rows(rows)


def _parse_snapshot(trade: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("entry_diagnostic_snapshot", "feature_payload"):
        text = trade.get(key)
        if not text:
            continue
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return {}


def _direction_suffix(direction: str) -> str:
    return "put" if str(direction or "").upper() == "PUT" else "call"


def _extract_entry_score(snap: Dict[str, Any], direction: str) -> Optional[float]:
    if snap.get("entry_score") is not None:
        try:
            return float(snap.get("entry_score"))
        except Exception:
            return None

    suffix = _direction_suffix(direction)
    key = "put_score" if suffix == "put" else "call_score"
    val = snap.get(key)
    try:
        return float(val) if val is not None else None
    except Exception:
        return None


def _extract_trend_stage(snap: Dict[str, Any], direction: str) -> Optional[int]:
    direct = snap.get("trend_stage")
    if isinstance(direct, dict):
        try:
            return int(direct.get("stage"))
        except Exception:
            pass
    if direct is not None:
        try:
            return int(direct)
        except Exception:
            pass

    suffix = _direction_suffix(direction)
    keyed = snap.get(f"trend_stage_{suffix}")
    if isinstance(keyed, dict):
        try:
            return int(keyed.get("stage"))
        except Exception:
            return None
    try:
        return int(keyed) if keyed is not None else None
    except Exception:
        return None


def _extract_continuation_quality(snap: Dict[str, Any], direction: str) -> Optional[float]:
    val = snap.get("continuation_quality_score")
    if val is not None:
        try:
            return float(val)
        except Exception:
            pass

    suffix = _direction_suffix(direction)
    obj = snap.get(f"continuation_quality_{suffix}")
    if isinstance(obj, dict):
        try:
            return float(obj.get("score"))
        except Exception:
            return None
    return None


def _extract_momentum_freshness(snap: Dict[str, Any], direction: str) -> Tuple[Optional[float], Optional[str]]:
    suffix = _direction_suffix(direction)
    obj = snap.get(f"momentum_freshness_{suffix}")
    if isinstance(obj, dict):
        score = obj.get("score")
        phase = obj.get("phase")
        try:
            score = float(score) if score is not None else None
        except Exception:
            score = None
        return score, (str(phase) if phase is not None else None)

    score_key = f"momentum_freshness_score_{suffix}"
    phase_key = f"momentum_phase_{suffix}"

    score = snap.get(score_key)
    phase = snap.get(phase_key)
    try:
        score = float(score) if score is not None else None
    except Exception:
        score = None
    return score, (str(phase) if phase is not None else None)


def _extract_momentum_acceleration(snap: Dict[str, Any], direction: str) -> Optional[float]:
    val = snap.get("momentum_acceleration_score")
    if val is not None:
        try:
            return float(val)
        except Exception:
            pass

    suffix = _direction_suffix(direction)
    obj = snap.get(f"momentum_acceleration_{suffix}")
    if isinstance(obj, dict):
        try:
            return float(obj.get("score"))
        except Exception:
            return None
    return None


def _extract_absorption_score(snap: Dict[str, Any], direction: str) -> Optional[float]:
    val = snap.get("absorption_score")
    if val is not None:
        try:
            return float(val)
        except Exception:
            pass

    suffix = _direction_suffix(direction)
    obj = snap.get(f"absorption_score_{suffix}")
    if isinstance(obj, dict):
        try:
            return float(obj.get("score"))
        except Exception:
            return None
    return None


def _extract_reasons(snap: Dict[str, Any], direction: str) -> Tuple[List[str], List[str]]:
    suffix = _direction_suffix(direction)

    reasons = snap.get("entry_reasons")
    if not isinstance(reasons, list):
        reasons = snap.get(f"entry_reasons_{suffix}")
    if not isinstance(reasons, list):
        reasons = []

    positives: List[str] = []
    penalties: List[str] = []

    for reason in reasons:
        text = str(reason or "").strip()
        if not text:
            continue
        if text in _NEGATIVE_REASON_KEYS:
            penalties.append(text)
        else:
            positives.append(text)

    mf_obj = snap.get(f"momentum_freshness_{suffix}")
    if isinstance(mf_obj, dict):
        for label in mf_obj.get("positives") or []:
            txt = str(label or "").strip()
            if txt:
                positives.append(f"momentum:{txt}")
        for label in mf_obj.get("penalties") or []:
            txt = str(label or "").strip()
            if txt:
                penalties.append(f"momentum:{txt}")

    if isinstance(snap.get("penalties"), list):
        for label in snap.get("penalties"):
            txt = str(label or "").strip()
            if txt:
                penalties.append(txt)

    return positives, penalties


def _extract_market_regime(snap: Dict[str, Any]) -> Optional[str]:
    regime = snap.get("market_regime")
    return str(regime) if regime is not None else None


def _extract_operational_log_entries(trade_date: str) -> List[Tuple[datetime, str]]:
    if not BOT_LOG_PATH.exists():
        return []

    entries: List[Tuple[datetime, str]] = []
    ts_re = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")

    try:
        for raw_line in BOT_LOG_PATH.read_text(errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            upper = line.upper()
            if ("ERROR" not in upper) and ("ALERT" not in upper) and ("EXCEPTION" not in upper) and ("FAILED" not in upper):
                continue

            match = ts_re.search(line)
            if not match:
                continue
            parsed = _parse_iso(match.group(1))
            if parsed is None:
                continue

            if parsed.astimezone(EASTERN_TZ).date().isoformat() != trade_date:
                continue

            entries.append((parsed, line))
    except Exception:
        return []

    return entries


def _errors_for_trade(
    entry_dt: Optional[datetime],
    exit_dt: Optional[datetime],
    option_symbol: Optional[str],
    direction: Optional[str],
    log_entries: List[Tuple[datetime, str]],
) -> List[str]:
    if entry_dt is None:
        return []

    start = entry_dt - timedelta(minutes=1)
    end = (exit_dt + timedelta(minutes=1)) if exit_dt is not None else (entry_dt + timedelta(minutes=30))

    out: List[str] = []
    symbol_text = str(option_symbol or "").strip().upper()
    direction_text = str(direction or "").strip().upper()

    for ts, line in log_entries:
        if ts < start or ts > end:
            continue
        upper = line.upper()
        if symbol_text and symbol_text in upper:
            out.append(line)
            continue
        if direction_text and direction_text in upper:
            out.append(line)
            continue
        # Keep generic high-severity failures in the trade window.
        if "EXCEPTION" in upper or "FAILED" in upper:
            out.append(line)

    return out[:8]


def _normalize_option_pnl_pct(raw_pct: Any, option_entry: Any, option_exit: Any) -> Optional[float]:
    try:
        if option_entry is not None and option_exit is not None and float(option_entry) > 0:
            return round(((float(option_exit) - float(option_entry)) / float(option_entry)) * 100.0, 4)
    except Exception:
        pass

    try:
        if raw_pct is None:
            return None
        value = float(raw_pct)
        # Stored value is usually ratio in this codebase.
        if abs(value) <= 3:
            return round(value * 100.0, 4)
        return round(value, 4)
    except Exception:
        return None


def _build_export_rows(trades: List[Dict[str, Any]], trade_date: str) -> List[Dict[str, Any]]:
    bot_ids = _bot_order_ids_from_audit()
    log_entries = _extract_operational_log_entries(trade_date)

    rows: List[Dict[str, Any]] = []
    for trade in trades:
        direction = str(trade.get("direction") or "")
        entry_dt = _parse_iso(trade.get("entry_time"))
        exit_dt = _parse_iso(trade.get("exit_time"))

        hold_minutes = None
        if entry_dt is not None and exit_dt is not None:
            hold_minutes = round((exit_dt - entry_dt).total_seconds() / 60.0, 3)

        snap = _parse_snapshot(trade)
        positives, penalties = _extract_reasons(snap, direction)

        broker_exit_id = str(trade.get("broker_exit_order_id") or "").strip()
        manual_override = bool(broker_exit_id and broker_exit_id not in bot_ids)

        op_errors = _errors_for_trade(
            entry_dt=entry_dt,
            exit_dt=exit_dt,
            option_symbol=trade.get("option_symbol"),
            direction=direction,
            log_entries=log_entries,
        )

        row = {
            "trade_id": trade.get("id"),
            "entry_time": _to_iso(trade.get("entry_time")),
            "exit_time": _to_iso(trade.get("exit_time")),
            "direction": direction,
            "option_symbol": trade.get("option_symbol"),
            "option_entry_price": trade.get("option_entry"),
            "option_exit_price": trade.get("option_exit"),
            "dollar_pnl": round(float(trade.get("dollar_pnl") or 0.0), 4),
            "percent_pnl": _normalize_option_pnl_pct(
                raw_pct=trade.get("option_pnl_pct"),
                option_entry=trade.get("option_entry"),
                option_exit=trade.get("option_exit"),
            ),
            "hold_duration_minutes": hold_minutes,
            "entry_score": _extract_entry_score(snap, direction),
            "positives": positives,
            "penalties": penalties,
            "market_regime": _extract_market_regime(snap),
            "trend_stage": _extract_trend_stage(snap, direction),
            "continuation_quality": _extract_continuation_quality(snap, direction),
            "momentum_freshness_score": _extract_momentum_freshness(snap, direction)[0],
            "momentum_freshness_phase": _extract_momentum_freshness(snap, direction)[1],
            "momentum_acceleration": _extract_momentum_acceleration(snap, direction),
            "absorption_score": _extract_absorption_score(snap, direction),
            "exit_reason": trade.get("exit_reason"),
            "manual_override": manual_override,
            "operational_errors": op_errors,
        }
        rows.append(row)

    return rows


def _csv_row_from_export_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "trade_id": row.get("trade_id"),
        "entry_time": row.get("entry_time"),
        "exit_time": row.get("exit_time"),
        "direction": row.get("direction"),
        "option_symbol": row.get("option_symbol"),
        "option_entry_price": row.get("option_entry_price"),
        "option_exit_price": row.get("option_exit_price"),
        "dollar_pnl": row.get("dollar_pnl"),
        "percent_pnl": row.get("percent_pnl"),
        "hold_duration_minutes": row.get("hold_duration_minutes"),
        "entry_score": row.get("entry_score"),
        "positives": " | ".join(row.get("positives") or []),
        "penalties": " | ".join(row.get("penalties") or []),
        "market_regime": row.get("market_regime"),
        "trend_stage": row.get("trend_stage"),
        "continuation_quality": row.get("continuation_quality"),
        "momentum_freshness_score": row.get("momentum_freshness_score"),
        "momentum_freshness_phase": row.get("momentum_freshness_phase"),
        "momentum_acceleration": row.get("momentum_acceleration"),
        "absorption_score": row.get("absorption_score"),
        "exit_reason": row.get("exit_reason"),
        "manual_override": row.get("manual_override"),
        "operational_errors": " | ".join(row.get("operational_errors") or []),
    }


def _export_files(trade_date: str, rows: List[Dict[str, Any]]) -> Tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / f"daily_trade_log_{trade_date}.csv"
    json_path = OUTPUT_DIR / f"daily_trade_review_data_{trade_date}.json"

    csv_fields = [
        "trade_id",
        "entry_time",
        "exit_time",
        "direction",
        "option_symbol",
        "option_entry_price",
        "option_exit_price",
        "dollar_pnl",
        "percent_pnl",
        "hold_duration_minutes",
        "entry_score",
        "positives",
        "penalties",
        "market_regime",
        "trend_stage",
        "continuation_quality",
        "momentum_freshness_score",
        "momentum_freshness_phase",
        "momentum_acceleration",
        "absorption_score",
        "exit_reason",
        "manual_override",
        "operational_errors",
    ]

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row_from_export_row(row))

    wins = sum(1 for row in rows if float(row.get("dollar_pnl") or 0.0) > 0)
    losses = sum(1 for row in rows if float(row.get("dollar_pnl") or 0.0) < 0)
    net = round(sum(float(row.get("dollar_pnl") or 0.0) for row in rows), 4)

    payload = {
        "trading_date": trade_date,
        "generated_at": datetime.now(tz=CENTRAL_TZ).isoformat(),
        "summary": {
            "total_trades": len(rows),
            "wins": wins,
            "losses": losses,
            "net_pnl": net,
            "win_rate_pct": round((wins / len(rows) * 100.0) if rows else 0.0, 4),
        },
        "trades": rows,
    }

    json_path.write_text(json.dumps(payload, indent=2))
    return csv_path, json_path


def _send_via_smtp(to_email: str, subject: str, body: str, attachments: List[Path]) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    port_raw = os.getenv("SMTP_PORT", "587").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_email = os.getenv("SMTP_FROM", "").strip() or username

    if not host or not username or not password or not from_email:
        print("Daily trade-log email failed (SMTP): missing SMTP settings")
        return False

    try:
        port = int(port_raw)
    except Exception:
        port = 587

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    for path in attachments:
        try:
            data = path.read_bytes()
            msg.add_attachment(
                data,
                maintype="application",
                subtype="octet-stream",
                filename=path.name,
            )
        except Exception as exc:
            print(f"Daily trade-log email failed (SMTP): attachment error for {path}: {exc}")
            return False

    try:
        with smtplib.SMTP(host, port, timeout=12) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"Daily trade-log email failed (SMTP): {exc}")
        return False


def _send_via_mailapp(to_email: str, subject: str, body: str, attachments: List[Path]) -> bool:
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    attach_cmds = []
    for path in attachments:
        attach_cmds.append(
            f'make new attachment with properties {{file name:POSIX file "{esc(str(path.resolve()))}"}} at after the last paragraph'
        )

    attach_script = "\n            ".join(attach_cmds)

    applescript = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:false}}
        tell newMessage
            make new to recipient at end of to recipients with properties {{address:"{esc(to_email)}"}}
            {attach_script}
            send
        end tell
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True
        err = (result.stderr or "").strip() or (result.stdout or "").strip()
        print(f"Daily trade-log email failed (Mail.app): {err}")
        return False
    except Exception as exc:
        print(f"Daily trade-log email failed (Mail.app): {exc}")
        return False


def _build_subject(trade_date: str, rows: Optional[List[Dict[str, Any]]] = None) -> str:
    row_list = rows or []
    net = round(sum(float(row.get("dollar_pnl") or 0.0) for row in row_list), 2)
    return f"McLeod Alpha Trade Log - {trade_date} | Net P&L: ${net:,.2f}"


def _build_body(
    trade_date: str,
    rows: List[Dict[str, Any]],
    csv_path: Path,
    json_path: Path,
    opportunity_paths: Optional[List[Path]] = None,
) -> str:
    wins = sum(1 for row in rows if float(row.get("dollar_pnl") or 0.0) > 0)
    losses = sum(1 for row in rows if float(row.get("dollar_pnl") or 0.0) < 0)
    net = round(sum(float(row.get("dollar_pnl") or 0.0) for row in rows), 2)

    extra_attachments = ""
    for path in opportunity_paths or []:
        extra_attachments += f"- {path.name}\n"

    return (
        f"Trade date: {trade_date}\n"
        f"Total trades: {len(rows)}\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Net P/L: ${net:,.2f}\n\n"
        f"Attached:\n"
        f"- {csv_path.name}\n"
        f"- {json_path.name}\n"
        f"{extra_attachments}"
    )


def _get_market_close_time_ct(trade_date: date) -> dt_time:
    # Default US equity close in Central Time.
    fallback = dt_time(15, 0)

    try:
        client = easy_client(
            api_key=os.getenv("SCHWAB_APP_KEY"),
            app_secret=os.getenv("SCHWAB_APP_SECRET"),
            callback_url=os.getenv("SCHWAB_CALLBACK_URL"),
            token_path="token.json",
            enforce_enums=False,
        )

        resp = client.get_market_hours(markets=["equity"], date=trade_date)
        if getattr(resp, "status_code", 0) != 200:
            return fallback

        payload = resp.json() or {}
        equity_section = payload.get("equity") or {}

        for _, market_blob in equity_section.items():
            regular = ((market_blob.get("sessionHours") or {}).get("regularMarket") or [])
            if not regular:
                continue
            end_text = regular[0].get("end")
            end_dt = _parse_iso(end_text)
            if end_dt is None:
                continue
            return end_dt.astimezone(CENTRAL_TZ).time()

        return fallback
    except Exception as exc:
        print(f"Daily trade-log schedule warning: market-hours lookup failed: {exc}")
        return fallback


def _target_send_time_ct(trade_date: date) -> dt_time:
    configured = _configured_send_time_ct()
    configured_dt = datetime.combine(trade_date, configured, tzinfo=CENTRAL_TZ)

    close_time = _get_market_close_time_ct(trade_date)
    close_plus_5 = datetime.combine(trade_date, close_time, tzinfo=CENTRAL_TZ) + timedelta(minutes=5)

    return min(configured_dt, close_plus_5).time()


def _attempt_send_for_date(trade_date: str) -> bool:
    rows = _build_export_rows(_fetch_trades_for_date(trade_date), trade_date)
    csv_path, json_path = _export_files(trade_date, rows)

    opportunity_paths: List[Path] = []
    try:
        review_paths = build_daily_opportunity_review(trade_date)
        opportunity_paths = [review_paths.html, review_paths.csv, review_paths.json]
    except Exception as exc:
        print(f"Daily opportunity review generation warning: {exc}")

    to_email = _recipient()
    if not to_email:
        print("Daily trade-log email failed: recipient not configured")
        return False

    subject = _build_subject(trade_date, rows)
    body = _build_body(trade_date, rows, csv_path, json_path, opportunity_paths=opportunity_paths)
    attachments = [csv_path, json_path] + opportunity_paths

    transport = _transport()
    if transport == "smtp":
        sent = _send_via_smtp(to_email, subject, body, attachments)
        if not sent:
            _append_delivery_log(
                f"{datetime.now(tz=CENTRAL_TZ).isoformat()} | send_failed"
                f" | date={trade_date} | recipient={to_email} | transport=smtp"
                f" | csv={csv_path} | json={json_path}"
            )
        return sent
    if transport == "mailapp":
        sent = _send_via_mailapp(to_email, subject, body, attachments)
        if not sent:
            _append_delivery_log(
                f"{datetime.now(tz=CENTRAL_TZ).isoformat()} | send_failed"
                f" | date={trade_date} | recipient={to_email} | transport=mailapp"
                f" | csv={csv_path} | json={json_path}"
            )
        return sent

    # auto transport fallback
    sent = _send_via_mailapp(to_email, subject, body, attachments) or _send_via_smtp(to_email, subject, body, attachments)
    if not sent:
        _append_delivery_log(
            f"{datetime.now(tz=CENTRAL_TZ).isoformat()} | send_failed"
            f" | date={trade_date} | recipient={to_email} | transport=auto"
            f" | csv={csv_path} | json={json_path}"
        )
    return sent


def maybe_send_daily_trade_log_email(now_ct: Optional[datetime] = None) -> bool:
    """Send daily trade-log files by email once per trading day.

    Returns True only when send succeeds in this call.
    """
    if not _enabled():
        return False

    now = now_ct or datetime.now(CENTRAL_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CENTRAL_TZ)
    else:
        now = now.astimezone(CENTRAL_TZ)

    # Weekdays only.
    if now.weekday() >= 5:
        return False

    trade_date = now.date()
    trade_date_str = trade_date.isoformat()

    state = _load_state()
    _process_pending_verification(state, now)

    if now.time() < _target_send_time_ct(trade_date):
        return False

    if state.get("last_sent_date") == trade_date_str:
        return False

    attempts_today = 0
    if state.get("attempt_date") == trade_date_str:
        try:
            attempts_today = int(state.get("attempt_count") or 0)
        except Exception:
            attempts_today = 0

    # One initial attempt + one retry max.
    if attempts_today >= 2:
        return False

    remaining = 2 - attempts_today
    for _ in range(remaining):
        attempts_today += 1
        state["attempt_date"] = trade_date_str
        state["attempt_count"] = attempts_today
        state["last_attempt_at"] = datetime.now(tz=CENTRAL_TZ).isoformat()
        state["last_to_email"] = _recipient()
        _save_state(state)

        try:
            sent = _attempt_send_for_date(trade_date_str)
        except Exception as exc:
            sent = False
            print(f"Daily trade-log send attempt {attempts_today}/2 failed: {exc}")

        if sent:
            csv_path = OUTPUT_DIR / f"daily_trade_log_{trade_date_str}.csv"
            json_path = OUTPUT_DIR / f"daily_trade_review_data_{trade_date_str}.json"
            state["last_sent_date"] = trade_date_str
            state["last_sent_at"] = datetime.now(tz=CENTRAL_TZ).isoformat()
            state["last_subject"] = _build_subject(trade_date_str, _build_export_rows(_fetch_trades_for_date(trade_date_str), trade_date_str))
            state["attempt_count"] = attempts_today
            state["last_csv_path"] = str(csv_path)
            state["last_json_path"] = str(json_path)
            state["verification_due_at"] = (datetime.now(tz=CENTRAL_TZ) + timedelta(minutes=1)).isoformat()
            state["verification_done"] = False
            _save_state(state)
            _append_delivery_log(
                f"{datetime.now(tz=CENTRAL_TZ).isoformat()} | send_success"
                f" | date={trade_date_str} | recipient={_recipient()}"
                f" | attempt={attempts_today} | csv={csv_path} | json={json_path}"
            )
            print(f"Daily trade-log email sent for {trade_date_str} to {_recipient()}")
            return True

        print(f"Daily trade-log send attempt {attempts_today}/2 failed")

    return False
