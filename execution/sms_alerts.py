"""Trade alerts for entry/exit with free email-to-SMS and optional Twilio.

Environment variables:
- ENABLE_TRADE_SMS_ALERTS=true|false
- TRADE_ALERT_TRANSPORT=email_sms|twilio|auto (default: email_sms)

Free email-to-SMS transport:
- SMTP_HOST=smtp.gmail.com
- SMTP_PORT=587
- SMTP_USERNAME=you@example.com
- SMTP_PASSWORD=app_password
- SMTP_FROM=you@example.com
- TRADE_ALERT_TO_GATEWAY=5551234567@vtext.com

Optional Twilio transport:
- TWILIO_ACCOUNT_SID=...
- TWILIO_AUTH_TOKEN=...
- TWILIO_FROM_NUMBER=+1...
- TRADE_ALERT_TO_NUMBER=+1...
"""

import smtplib
import os
import subprocess
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import requests


def _load_dotenv_if_present() -> None:
    """Load key=value pairs from workspace .env if not already in environment."""
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
        # Non-fatal: environment variables can still come from shell/session.
        pass


_load_dotenv_if_present()


def _is_enabled() -> bool:
    return os.getenv("ENABLE_TRADE_SMS_ALERTS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _execution_alerts_enabled() -> bool:
    """Gate trade entry/exit notifications separately from emergency alerts.

    Default is disabled to avoid duplicate broker-app notifications.
    """
    return os.getenv("ENABLE_TRADE_EXECUTION_ALERTS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }



def _transport() -> str:
    return os.getenv("TRADE_ALERT_TRANSPORT", "email_sms").strip().lower()


def _email_cfg() -> Optional[dict]:
    host = os.getenv("SMTP_HOST", "").strip()
    port_raw = os.getenv("SMTP_PORT", "587").strip()
    user = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("SMTP_FROM", "").strip() or user
    to_addr = os.getenv("TRADE_ALERT_TO_GATEWAY", "").strip()

    if not host or not user or not password or not from_addr or not to_addr:
        return None

    try:
        port = int(port_raw)
    except ValueError:
        port = 587

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from": from_addr,
        "to": to_addr,
    }


def _creds() -> Optional[dict]:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    to_number = os.getenv("TRADE_ALERT_TO_NUMBER", "").strip()

    if not sid or not token or not from_number or not to_number:
        return None

    return {
        "sid": sid,
        "token": token,
        "from": from_number,
        "to": to_number,
    }


def _send_via_email_sms(body: str) -> bool:
    cfg = _email_cfg()
    if cfg is None:
        return False

    msg = EmailMessage()
    msg["Subject"] = "Trade Alert"
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]
    msg.set_content(body)

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            smtp.starttls()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"SMS alert (email gateway) failed: {exc}")
        return False


def _send_via_mailapp_sms(body: str) -> bool:
    to_addr = os.getenv("TRADE_ALERT_TO_GATEWAY", "").strip()
    if not to_addr:
        return False

    # Keep subject short for carrier gateways.
    subject = "Trade Alert"

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    applescript = f'''
tell application "Mail"
    set newMessage to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:false}}
    tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{esc(to_addr)}"}}
        send
    end tell
end tell
'''

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True

        err = (result.stderr or "").strip() or (result.stdout or "").strip()
        print(f"SMS alert (Mail.app gateway) failed: {err}")
        return False
    except Exception as exc:
        print(f"SMS alert (Mail.app gateway) failed: {exc}")
        return False


def _send_via_twilio(body: str) -> bool:
    cfg = _creds()
    if cfg is None:
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg['sid']}/Messages.json"
    payload = {
        "From": cfg["from"],
        "To": cfg["to"],
        "Body": body,
    }

    try:
        resp = requests.post(
            url,
            data=payload,
            auth=(cfg["sid"], cfg["token"]),
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True

        print(f"SMS alert (Twilio) failed: HTTP {resp.status_code}")
        return False
    except Exception as exc:
        print(f"SMS alert (Twilio) failed: {exc}")
        return False


def _send_sms(body: str) -> bool:
    if not _is_enabled():
        return False

    transport = _transport()

    if transport == "mailapp_sms":
        if _send_via_mailapp_sms(body):
            return True
        print("SMS alert skipped: Mail.app transport not configured or failed")
        return False

    if transport == "email_sms":
        if _send_via_email_sms(body):
            return True
        print("SMS alert skipped: email-to-SMS gateway vars missing or failed")
        return False

    if transport == "twilio":
        if _send_via_twilio(body):
            return True
        print("SMS alert skipped: Twilio vars missing or failed")
        return False

    # auto: try Mail.app gateway, then SMTP gateway, then Twilio fallback.
    if _send_via_mailapp_sms(body):
        return True
    if _send_via_email_sms(body):
        return True
    if _send_via_twilio(body):
        return True

    print("SMS alert skipped: no valid transport configured (email_sms/twilio)")
    return False


def send_trade_entry_alert(
    mode: str,
    direction: str,
    quantity: int,
    option_symbol: str,
    option_entry: float,
    spy_entry: float,
    reason: str,
) -> bool:
    if not _execution_alerts_enabled():
        return False

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"[{mode}] OPTION ENTRY {direction}\n"
        f"Qty: {quantity} | Option: {option_symbol or 'N/A'}\n"
        f"Option Px: {option_entry:.2f} | SPY: {spy_entry:.2f}\n"
        f"Reason: {reason}\n"
        f"Time: {ts}"
    )
    return _send_sms(msg)


def send_trade_exit_alert(
    mode: str,
    direction: str,
    quantity: int,
    option_symbol: str,
    option_entry: float,
    option_exit: float,
    pnl_dollars: float,
    pnl_pct: float,
    exit_reason: str,
) -> bool:
    if not _execution_alerts_enabled():
        return False

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"[{mode}] OPTION EXIT {direction}\n"
        f"Qty: {quantity} | Option: {option_symbol or 'N/A'}\n"
        f"In: {option_entry:.2f} | Out: {option_exit:.2f}\n"
        f"PnL: ${pnl_dollars:.2f} ({pnl_pct:.2f}%)\n"
        f"Reason: {exit_reason}\n"
        f"Time: {ts}"
    )
    return _send_sms(msg)


def send_emergency_alert(title: str, details: str = "") -> bool:
    """Send high-priority emergency alert via configured SMS transport."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[EMERGENCY] {title}"
    if details:
        msg += f"\n{details}"
    msg += f"\nTime: {ts}"
    return _send_sms(msg)
