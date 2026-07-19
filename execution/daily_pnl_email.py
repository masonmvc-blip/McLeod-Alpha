"""Daily market-close P&L email sender.

Sends one email per day after configured market-close time.
Supports Mail.app transport (default) and SMTP transport.
"""

import json
import os
import smtplib
import sqlite3
import subprocess
from datetime import datetime, time as dt_time
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Any
from zoneinfo import ZoneInfo

from schwab.auth import easy_client

DB_PATH = Path("data/mcleod_alpha.db")
STATE_PATH = Path("data/daily_pnl_email_state.json")


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
    return os.getenv("DAILY_PNL_EMAIL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _send_time_et() -> dt_time:
    raw = os.getenv("DAILY_PNL_SEND_TIME_ET", "16:01").strip()
    try:
        hh, mm = raw.split(":", 1)
        return dt_time(int(hh), int(mm))
    except Exception:
        return dt_time(16, 1)


def _transport() -> str:
    return os.getenv("DAILY_PNL_EMAIL_TRANSPORT", "mailapp").strip().lower()


def _recipient() -> str:
    return (
        os.getenv("DAILY_PNL_TO_EMAIL", "").strip()
        or os.getenv("SMTP_FROM", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
    )


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


def _table_columns() -> set:
    if not DB_PATH.exists():
        return set()
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("PRAGMA table_info(trade_log)").fetchall()
    return {row[1] for row in rows}


def _broker_today_net_pnl(date_str: str) -> float | None:
    account_hash = os.getenv("SCHWAB_ACCOUNT_HASH", "").strip()
    app_key = os.getenv("SCHWAB_APP_KEY", "").strip()
    app_secret = os.getenv("SCHWAB_APP_SECRET", "").strip()
    callback = os.getenv("SCHWAB_CALLBACK_URL", "").strip()
    if not all([account_hash, app_key, app_secret, callback]):
        return None

    try:
        day_start = datetime.fromisoformat(f"{date_str}T00:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
        day_end = day_start.replace(hour=23, minute=59, second=59)
        client = easy_client(
            api_key=app_key,
            app_secret=app_secret,
            callback_url=callback,
            token_path="token.json",
            enforce_enums=False,
        )
        resp = client.get_transactions(
            account_hash,
            start_date=day_start,
            end_date=day_end,
            transaction_types=["TRADE", "RECEIVE_AND_DELIVER"],
        )
        resp.raise_for_status()
        transactions = resp.json() or []

        total = 0.0
        for tx in transactions:
            tx_type = str((tx or {}).get("type") or "").upper()
            if tx_type and tx_type != "TRADE":
                continue

            transfer_items = (tx or {}).get("transferItems") or []
            in_scope = False
            for item in transfer_items:
                inst = (item or {}).get("instrument") or {}
                asset_type = str(inst.get("assetType") or "").upper()
                symbol = str(inst.get("symbol") or "").upper()
                underlying = str(inst.get("underlyingSymbol") or "").upper()
                if asset_type != "OPTION":
                    continue
                if "SPY" not in symbol and underlying != "SPY":
                    continue
                in_scope = True
                break
            if not in_scope:
                continue

            amount = (tx or {}).get("netAmount")
            if amount is None:
                amount = (tx or {}).get("amount")
            try:
                total += float(amount)
            except Exception:
                continue

        return round(total, 2)
    except Exception:
        return None


def _daily_stats(date_str: str) -> Dict[str, Any]:
    if not DB_PATH.exists():
        return {
            "date": date_str,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "net_pnl": 0.0,
            "rows": [],
        }

    cols = _table_columns()
    use_option = "option_pnl_dollars" in cols
    pnl_col = "option_pnl_dollars" if use_option else "pnl"

    query = f"""
    SELECT id, entry_time, exit_time, direction, exit_reason,
           COALESCE({pnl_col}, 0) AS pnl_value,
           option_symbol
    FROM trade_log
        WHERE substr(entry_time, 1, 10) = ?
    ORDER BY entry_time ASC
    """

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(query, (date_str,)).fetchall()]

    pnl_values = [float(r.get("pnl_value") or 0.0) for r in rows]
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)

    net_pnl = float(sum(pnl_values))
    broker_net_pnl = _broker_today_net_pnl(date_str)
    if broker_net_pnl is not None:
        net_pnl = broker_net_pnl

    return {
        "date": date_str,
        "trades": len(rows),
        "wins": wins,
        "losses": losses,
        "net_pnl": net_pnl,
        "rows": rows,
    }


def _build_subject(date_str: str, net_pnl: float) -> str:
    sign = "+" if net_pnl >= 0 else ""
    return f"McLeod Daily P&L {date_str} | {sign}${net_pnl:,.2f}"


def _build_body(stats: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"Date: {stats['date']}")
    lines.append(f"Total trades: {stats['trades']}")
    lines.append(f"Wins: {stats['wins']}")
    lines.append(f"Losses: {stats['losses']}")
    lines.append(f"Net P&L: ${stats['net_pnl']:,.2f}")
    lines.append("")
    lines.append("Trades:")

    if not stats["rows"]:
        lines.append("- No trades logged for this date.")
    else:
        for row in stats["rows"]:
            lines.append(
                "- #{id} {direction} {symbol} | Entry {entry} | Exit {exit} | "
                "Reason {reason} | P&L ${pnl:,.2f}".format(
                    id=row.get("id", "?"),
                    direction=row.get("direction", "?"),
                    symbol=row.get("option_symbol") or "N/A",
                    entry=row.get("entry_time") or "N/A",
                    exit=row.get("exit_time") or "N/A",
                    reason=row.get("exit_reason") or "N/A",
                    pnl=float(row.get("pnl_value") or 0.0),
                )
            )

    return "\n".join(lines) + "\n"


def _send_via_mailapp(to_email: str, subject: str, body: str) -> bool:
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    applescript = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:false}}
        tell newMessage
            make new to recipient at end of to recipients with properties {{address:"{esc(to_email)}"}}
            send
        end tell
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode == 0:
            return True
        err = (result.stderr or "").strip() or (result.stdout or "").strip()
        print(f"Daily P&L email failed (Mail.app): {err}")
        return False
    except Exception as exc:
        print(f"Daily P&L email failed (Mail.app): {exc}")
        return False


def _send_via_smtp(to_email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    port_raw = os.getenv("SMTP_PORT", "587").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_email = os.getenv("SMTP_FROM", "").strip() or username

    if not host or not username or not password or not from_email:
        print("Daily P&L email skipped (SMTP): missing SMTP settings")
        return False

    try:
        port = int(port_raw)
    except ValueError:
        port = 587

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=12) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"Daily P&L email failed (SMTP): {exc}")
        return False


def maybe_send_daily_pnl_email() -> bool:
    """Send one daily close email after configured ET time.

    Returns True when an email was sent in this call.
    """
    if not _enabled():
        return False

    now_et = datetime.now(ZoneInfo("America/New_York"))
    today_str = now_et.strftime("%Y-%m-%d")

    if now_et.time() < _send_time_et():
        return False

    state = _load_state()
    if state.get("last_sent_date") == today_str:
        return False

    to_email = _recipient()
    if not to_email:
        print("Daily P&L email skipped: DAILY_PNL_TO_EMAIL not configured")
        return False

    stats = _daily_stats(today_str)
    subject = _build_subject(today_str, stats["net_pnl"])
    body = _build_body(stats)

    transport = _transport()
    sent = False

    if transport == "smtp":
        sent = _send_via_smtp(to_email, subject, body)
    elif transport == "mailapp":
        sent = _send_via_mailapp(to_email, subject, body)
    else:
        # auto: try Mail.app first, then SMTP fallback
        sent = _send_via_mailapp(to_email, subject, body) or _send_via_smtp(to_email, subject, body)

    if sent:
        state["last_sent_date"] = today_str
        state["last_subject"] = subject
        state["last_sent_at"] = datetime.now().isoformat()
        _save_state(state)
        print(f"Daily P&L email sent to {to_email}")
        return True

    return False
