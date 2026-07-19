#!/usr/bin/env python3
"""SPCX open assist workflow.

Manual-only assistant for Monday market open:
- Refreshes portfolio snapshot.
- Validates XNYS session/date gate.
- Fetches live SPCX quote.
- Builds a one-share manual limit plan.
- Sends alert email/SMS summary.

This script NEVER places broker orders.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, date
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from dotenv import load_dotenv
from schwab.auth import easy_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "reports" / "spcx_open_assist"
LOG_DIR = PROJECT_ROOT / "logs"
PLAN_JSON = DATA_DIR / "latest_spcx_open_assist.json"
PLAN_TXT = DATA_DIR / "latest_spcx_open_assist.txt"
RUN_LOG = LOG_DIR / "spcx_open_assist.jsonl"

NEW_YORK_TZ = ZoneInfo("America/New_York")
CHICAGO_TZ = ZoneInfo("America/Chicago")
CALENDAR = xcals.get_calendar("XNYS")


@dataclass
class QuotePlan:
    symbol: str
    quote_time: str
    bid: float | None
    ask: float | None
    last: float | None
    mark: float | None
    suggested_limit: float | None
    max_chase_limit: float | None
    spread: float | None



def _now_ct() -> datetime:
    return datetime.now(CHICAGO_TZ)



def _now_et() -> datetime:
    return datetime.now(NEW_YORK_TZ)



def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)



def _log_setup() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("spcx_open_assist")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = logging.FileHandler(LOG_DIR / "spcx_open_assist.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger



def _append_run_log(payload: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = dict(payload)
    line.setdefault("logged_at", _now_ct().isoformat())
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")



def _is_xnys_session(day: date) -> bool:
    return bool(CALENDAR.is_session(pd.Timestamp(day)))



def _refresh_portfolio(logger: logging.Logger) -> dict[str, Any]:
    cmd = [sys.executable, str(PROJECT_ROOT / "portfolio_sync.py")]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        payload = {
            "attempted": True,
            "succeeded": result.returncode == 0,
            "returncode": result.returncode,
            "stderr": result.stderr,
            "stdout": result.stdout,
        }
        logger.info("portfolio refresh result: %s", json.dumps(payload, sort_keys=True))
        return payload
    except Exception as exc:
        payload = {
            "attempted": True,
            "succeeded": False,
            "returncode": None,
            "stderr": str(exc),
            "stdout": "",
        }
        logger.warning("portfolio refresh failed: %s", exc)
        return payload



def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None



def _fetch_spcx_quote() -> QuotePlan:
    client = easy_client(
        api_key=os.getenv("SCHWAB_APP_KEY"),
        app_secret=os.getenv("SCHWAB_APP_SECRET"),
        callback_url=os.getenv("SCHWAB_CALLBACK_URL"),
        token_path=str(PROJECT_ROOT / "token.json"),
        enforce_enums=False,
    )
    resp = client.get_quote("SPCX")
    resp.raise_for_status()
    payload = resp.json() or {}
    blob = payload.get("SPCX") or {}
    quote = blob.get("quote") or {}
    regular = blob.get("regular") or {}

    bid = _to_float(quote.get("bidPrice") or quote.get("bid"))
    ask = _to_float(quote.get("askPrice") or quote.get("ask"))
    last = _to_float(quote.get("lastPrice") or regular.get("regularMarketLastPrice"))
    mark = _to_float(quote.get("mark"))

    spread = None
    if bid is not None and ask is not None:
        spread = round(max(0.0, ask - bid), 4)

    suggested_limit = None
    max_chase_limit = None
    if ask is not None and ask > 0:
        suggested_limit = round(ask, 2)
        max_chase_limit = round(ask * 1.003, 2)
    elif mark is not None and mark > 0:
        suggested_limit = round(mark, 2)
        max_chase_limit = round(mark * 1.003, 2)
    elif last is not None and last > 0:
        suggested_limit = round(last, 2)
        max_chase_limit = round(last * 1.003, 2)

    return QuotePlan(
        symbol="SPCX",
        quote_time=_now_et().isoformat(),
        bid=bid,
        ask=ask,
        last=last,
        mark=mark,
        suggested_limit=suggested_limit,
        max_chase_limit=max_chase_limit,
        spread=spread,
    )



def _build_text(plan: QuotePlan, run_mode: str, target_day: str, refresh_ok: bool) -> str:
    lines = [
        "SPCX Open Assist (Manual-Only)",
        f"Generated: {_now_ct().isoformat()}",
        f"Target Session Date: {target_day}",
        f"Mode: {run_mode}",
        f"Portfolio Refresh: {'OK' if refresh_ok else 'FAILED'}",
        "",
        "Quote Snapshot:",
        f"- Symbol: {plan.symbol}",
        f"- Quote Time (ET): {plan.quote_time}",
        f"- Bid: {plan.bid}",
        f"- Ask: {plan.ask}",
        f"- Last: {plan.last}",
        f"- Mark: {plan.mark}",
        f"- Spread: {plan.spread}",
        "",
        "Manual Action Plan (No Auto Order):",
        "- Quantity: 1 share",
        "- Order Type: LIMIT",
        f"- Suggested Limit: {plan.suggested_limit}",
        f"- Max Chase Limit (0.30% cap): {plan.max_chase_limit}",
        "- Time in Force: DAY",
        "- Rule: cancel order if not filled in first 2 minutes unless manually re-approved",
        "",
        "Safety:",
        "- autonomous_execution: false",
        "- broker_order_submission: false",
        "- manual_confirmation_required: true",
    ]
    return "\n".join(lines) + "\n"



def _write_artifacts(payload: dict[str, Any], text: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PLAN_TXT.write_text(text, encoding="utf-8")



def _smtp_send(subject: str, body: str, logger: logging.Logger) -> tuple[bool, str]:
    email_address = os.getenv("EMAIL_ADDRESS", "").strip()
    email_password = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    email_to = os.getenv("EMAIL_TO", "").strip()
    from_name = os.getenv("EMAIL_FROM_NAME", "McLeod Alpha").strip() or "McLeod Alpha"

    if not email_address or not email_password or not email_to:
        return False, "missing EMAIL_ADDRESS/EMAIL_APP_PASSWORD/EMAIL_TO"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{email_address}>"
    msg["To"] = email_to
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
            smtp.login(email_address, email_password)
            refused = smtp.send_message(msg)
        if refused:
            return False, f"refused recipients: {refused}"
        logger.info("SMTP alert accepted")
        return True, "accepted"
    except Exception as exc:
        return False, str(exc)



def _mailapp_send(subject: str, body: str, logger: logging.Logger) -> tuple[bool, str]:
    to_email = os.getenv("EMAIL_TO", "").strip()
    if not to_email:
        return False, "missing EMAIL_TO"

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
        result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            err = (result.stderr or "").strip() or (result.stdout or "").strip()
            return False, err or "Mail.app failed"
        logger.info("Mail.app alert accepted")
        return True, "accepted"
    except Exception as exc:
        return False, str(exc)



def _send_alert(subject: str, body: str, logger: logging.Logger) -> tuple[bool, str]:
    ok, detail = _smtp_send(subject, body, logger)
    if ok:
        return ok, "smtp"
    logger.warning("SMTP alert failed: %s", detail)

    ok2, detail2 = _mailapp_send(subject, body, logger)
    if ok2:
        return ok2, "mailapp"
    logger.warning("Mail.app alert failed: %s", detail2)
    return False, f"smtp={detail}; mailapp={detail2}"



def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SPCX Monday open assist (manual-only).")
    parser.add_argument("--send", action="store_true", help="Send open-assist alert via email transport.")
    parser.add_argument("--force", action="store_true", help="Ignore weekday/session gate for testing.")
    parser.add_argument("--target-date", default="", help="Target date YYYY-MM-DD. Defaults to today ET.")
    return parser.parse_args(argv)



def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = _parse_args(argv)
    logger = _log_setup()

    today_et = _now_et().date()
    target_day = today_et
    if args.target_date:
        target_day = date.fromisoformat(args.target_date)

    is_monday = target_day.weekday() == 0
    is_session = _is_xnys_session(target_day)

    if not args.force and (not is_monday or not is_session):
        msg = f"skip gate: monday={is_monday}, xnys_session={is_session}, target_day={target_day.isoformat()}"
        logger.info(msg)
        _append_run_log({"event": "skipped", "reason": msg})
        return 0

    refresh = _refresh_portfolio(logger)
    try:
        plan = _fetch_spcx_quote()
    except Exception as exc:
        logger.exception("quote fetch failed")
        _append_run_log({"event": "failed", "error": str(exc)})
        return 1

    run_mode = "send" if args.send else "dry_run"
    text_body = _build_text(plan, run_mode, target_day.isoformat(), bool(refresh.get("succeeded")))

    payload = {
        "generated_at": _now_ct().isoformat(),
        "mode": run_mode,
        "target_date": target_day.isoformat(),
        "gate": {
            "monday": is_monday,
            "xnys_session": is_session,
            "force": bool(args.force),
        },
        "manual_only": True,
        "autonomous_execution": False,
        "broker_order_submission": False,
        "manual_confirmation_required": True,
        "portfolio_refresh": refresh,
        "quote_plan": {
            "symbol": plan.symbol,
            "quote_time": plan.quote_time,
            "bid": plan.bid,
            "ask": plan.ask,
            "last": plan.last,
            "mark": plan.mark,
            "spread": plan.spread,
            "quantity": 1,
            "suggested_limit": plan.suggested_limit,
            "max_chase_limit": plan.max_chase_limit,
            "tif": "DAY",
        },
    }

    _write_artifacts(payload, text_body)
    logger.info("wrote plan artifacts: %s | %s", PLAN_JSON, PLAN_TXT)

    transport = "none"
    accepted = True
    if args.send:
        subject = f"SPCX Open Assist | {target_day.isoformat()} | Manual Confirmation Required"
        accepted, transport = _send_alert(subject, text_body, logger)

    _append_run_log(
        {
            "event": "completed",
            "accepted": bool(accepted),
            "transport": transport,
            "target_date": target_day.isoformat(),
            "quote_time": plan.quote_time,
            "suggested_limit": plan.suggested_limit,
            "max_chase_limit": plan.max_chase_limit,
        }
    )

    if args.send and not accepted:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
