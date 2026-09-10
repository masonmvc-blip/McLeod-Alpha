"""Once-per-session email alerts for the SPCX accumulator."""

from __future__ import annotations

import json
import os
import smtplib
import subprocess
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "McLeod Alpha"
    / "runtime"
    / "spcx_daily_accumulator"
    / "email_alert_state.json"
)


def _recipient() -> str:
    return (
        os.getenv("SPCX_ALERT_TO_EMAIL", "").strip()
        or os.getenv("DAILY_PNL_TO_EMAIL", "").strip()
        or os.getenv("EMAIL_TO", "").strip()
        or os.getenv("SMTP_FROM", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
    )


def _transport() -> str:
    return (
        os.getenv("SPCX_ALERT_EMAIL_TRANSPORT", "").strip().lower()
        or os.getenv("DAILY_PNL_EMAIL_TRANSPORT", "outlook").strip().lower()
    )


def _send_outlook(to_email: str, subject: str, body: str) -> bool:
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
    tell application "Microsoft Outlook"
        set newMessage to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:false}}
        tell newMessage
            make new to recipient at end of to recipients with properties {{address:"{esc(to_email)}"}}
            send
        end tell
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return result.returncode == 0


def _send_smtp(to_email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_email = os.getenv("SMTP_FROM", "").strip() or username
    if not all((host, username, password, from_email)):
        return False
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body)
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)
    return True


def send_insufficient_cash_alert_once(
    session_date: str, *, available: str, required: str
) -> bool:
    """Send one cash-blocked email per session; return True only when sent."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    if (
        state.get("session_date") == session_date
        and state.get("reason") == "insufficient_non_margin_cash"
        and state.get("sent") is True
    ):
        return False

    recipient = _recipient()
    if not recipient:
        return False
    subject = f"SPCX buy blocked: cash needed | {session_date}"
    body = (
        "The automated one-share SPCX purchase was not submitted because Schwab "
        "reported insufficient non-margin buying power.\n\n"
        f"Available: ${available}\n"
        f"Required at the checked ask: ${required}\n\n"
        "Add settled cash or free non-margin buying power, then review the SPCX bot.\n"
    )
    try:
        sent = (
            _send_smtp(recipient, subject, body)
            if _transport() == "smtp"
            else _send_outlook(recipient, subject, body)
        )
    except Exception:
        sent = False
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "session_date": session_date,
                "reason": "insufficient_non_margin_cash",
                "sent": sent,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return sent
