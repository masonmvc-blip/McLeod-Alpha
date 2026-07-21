#!/usr/bin/env python3
"""
McLeod SPY Options Trader Cockpit 1.4 - Local dashboard for live bot management
Provides one-click controls for starting, stopping, and monitoring the trading bot
"""

import os
import sys
import json
import csv
import re
import hashlib
import importlib.metadata
import sqlite3
import subprocess
import signal
import time
import socket
import threading
import smtplib
import requests
from datetime import datetime, timezone, timedelta, date
import calendar
from typing import Optional
from pathlib import Path

from engine.memory import get_memory
from engine.brain import active_stop_category, classify_exit_reason
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
import ssl
from zoneinfo import ZoneInfo
from flask import Flask, render_template_string, jsonify, request, make_response
from dotenv import load_dotenv
from schwab.auth import easy_client
from email.message import EmailMessage

try:
    import certifi
except Exception:
    certifi = None

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent / "config" / "cockpit.env", override=True)

# Account management
sys.path.insert(0, str(Path(__file__).parent))
from utils.account_manager import AccountManager
from utils.decision_contract import normalize_reason_text, reason_code_from_text, quote_state_from_age
from execution.equity_stream import SchwabEquityQuoteStream
from engine.architecture_health import build_architecture_health
from spy_bot_reviewer import SpyBotReviewer

# Setup paths
PROJECT_ROOT = Path(__file__).parent
if (PROJECT_ROOT / ".venv" / "bin" / "python").exists():
    VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
elif (PROJECT_ROOT / ".venv" / "bin" / "python3").exists():
    VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python3"
else:
    VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python3"
BOT_SCRIPT = PROJECT_ROOT / "phase3_monitor.py"
EXPECTED_BOT_SCRIPT_NAME = "phase3_monitor.py"
BOT_PID_FILE = PROJECT_ROOT / ".bot_pid"
BOT_LOG_FILE = PROJECT_ROOT / "bot_output.log"
CANONICAL_DEPLOY_SCRIPT = PROJECT_ROOT / "scripts" / "maintenance" / "sync_and_restart_from_start_button.sh"
CANONICAL_DEPLOY_PID_FILE = PROJECT_ROOT / ".canonical_deploy_pid"
CANONICAL_DEPLOY_LOG_FILE = PROJECT_ROOT / "logs" / "canonical_deploy.log"
STATUS_FILE = PROJECT_ROOT / ".cockpit_status"
BOT_STOP_ALERT_STATE_FILE = PROJECT_ROOT / "data" / "bot_stop_alert_state.json"
CONTINUATION_STATUS_FILE = PROJECT_ROOT / "data" / "continuation_last_test.json"
CONTINUATION_CALIBRATION_FILE = PROJECT_ROOT / "data" / "reports" / "continuation_calibration.jsonl"
CONTROL_COMMAND_FILE = PROJECT_ROOT / "data" / "control_command.json"
ENTRY_PAUSE_FILE = PROJECT_ROOT / "data" / "entry_pause.json"
BOT_MANUAL_STOP_MARKER_FILE = PROJECT_ROOT / "data" / "bot_manual_stop_marker.json"
LATEST_REJECTION_FILE = PROJECT_ROOT / "output" / "latest_rejection_reason.json"
RUNTIME_ALERT_FLAG_FILE = PROJECT_ROOT / "data" / "runtime_alert_flag.json"
INTERNET_QUALITY_HISTORY_FILE = PROJECT_ROOT / "data" / "reports" / "internet_quality_history.jsonl"
DAILY_TRADES_CHART_DIR = PROJECT_ROOT / "data" / "reports" / "daily_trades_charts"
DAILY_TRADES_CHART_LOG = PROJECT_ROOT / "data" / "reports" / "daily_trades_charts.jsonl"
PARITY_BASELINE_FILE = PROJECT_ROOT / "data" / "parity_baseline.json"
DAILY_TRADE_LEARNING_LATEST_FILE = PROJECT_ROOT / "reports" / "daily_trade_learning" / "latest_daily_trade_learning.json"
GO_LIVE_SCRIPT = PROJECT_ROOT / "scripts" / "maintenance" / "go_live.sh"
GO_LIVE_LOG_FILE = PROJECT_ROOT / "logs" / "go_live_from_cockpit.log"
HEARTBEAT_STALE_SECONDS = int(os.getenv("BOT_HEARTBEAT_STALE_SECONDS", "180"))
HEARTBEAT_BANNER_STOP_SECONDS = int(os.getenv("BOT_HEARTBEAT_BANNER_STOP_SECONDS", "120"))
BOT_STOP_EMAIL_CONFIRMATION_SECONDS = int(os.getenv("BOT_STOP_EMAIL_CONFIRMATION_SECONDS", "20"))
OPTION_CONTRACT_MULTIPLIER = float(os.getenv("OPTION_CONTRACT_MULTIPLIER", "100"))
OPTION_COMMISSION_PER_CONTRACT_SIDE = float(os.getenv("OPTION_COMMISSION_PER_CONTRACT_SIDE", "0.665"))
OPTION_REGULATORY_FEE_PER_CONTRACT_CLOSE = float(os.getenv("OPTION_REGULATORY_FEE_PER_CONTRACT_CLOSE", "0.0135"))
MTD_PNL_CACHE_SECONDS = int(os.getenv("MTD_PNL_CACHE_SECONDS", "60"))
_BROKER_PNL_CACHE = {
    "timestamp": 0.0,
    "today": 0.0,
    "wtd": 0.0,
    "mtd": 0.0,
    "ytd": 0.0,
    "today_source": "schwab_transactions",
}
_ACTIVE_PROTECTIVE_STOP_CACHE = {
    "timestamp": 0.0,
    "symbol": None,
    "preferred_order_id": None,
    "price": None,
}

_EXECUTION_QUALITY_CACHE = {
    "timestamp": 0.0,
    "trading_date": None,
    "payload": None,
}

SPY_QUOTE_MAX_STALE_SECONDS = int(os.getenv("SPY_QUOTE_MAX_STALE_SECONDS", "1800"))
_SPY_QUOTE_CACHE = {
    "timestamp": 0.0,
    "price": None,
    "change": None,
    "change_pct": None,
    "as_of": None,
    "source": None,
}
_SPY_CLOSE_BASELINE_CACHE = {
    "trading_date": None,
    "close_price": None,
    "updated_at": None,
}
ALPACA_DATA_URL = str(os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets")).rstrip("/")

_INTERNET_QUALITY_CACHE = {
    "timestamp": 0.0,
    "payload": None,
}

_DAILY_LEARNING_INSIGHTS_CACHE = {
    "timestamp": 0.0,
    "payload": None,
}

INTERNET_QUALITY_CACHE_SECONDS = int(os.getenv("INTERNET_QUALITY_CACHE_SECONDS", "30"))
INTERNET_QUALITY_TIMEOUT_SECONDS = float(os.getenv("INTERNET_QUALITY_TIMEOUT_SECONDS", "3.5"))
INTERNET_TREND_BAR_POINTS = max(10, int(os.getenv("INTERNET_TREND_BAR_POINTS", "60")))
INTERNET_TREND_HISTORY_SAMPLES = max(240, int(os.getenv("INTERNET_TREND_HISTORY_SAMPLES", "720")))
STATUS_SNAPSHOT_CACHE_SECONDS = float(os.getenv("STATUS_SNAPSHOT_CACHE_SECONDS", "1.5"))
BROKER_PNL_REFRESH_SECONDS = float(os.getenv("BROKER_PNL_REFRESH_SECONDS", "15"))
DAILY_LEARNING_CACHE_SECONDS = float(os.getenv("DAILY_LEARNING_CACHE_SECONDS", "30"))
COCKPIT_PUBLIC_URL = os.environ["COCKPIT_PUBLIC_URL"].rstrip("/")
CANONICAL_REPO_BASENAME = os.getenv("MCLEOD_CANONICAL_REPO_BASENAME", "McLeod-Alpha-New").strip()
CANONICAL_REPO_PATH = Path(
    os.getenv("MCLEOD_CANONICAL_REPO_PATH", str(Path.home() / "GitHub" / CANONICAL_REPO_BASENAME))
).expanduser().resolve()
ENFORCE_CANONICAL_REPO_PATH = str(
    os.getenv("MCLEOD_ENFORCE_CANONICAL_REPO_PATH", "1")
).strip().lower() in {"1", "true", "yes", "on"}
_SPY_QUOTE_REFRESH_LEGACY = os.getenv("SPY_QUOTE_REFRESH_SECONDS")
SPY_QUOTE_REFRESH_SECONDS_OPEN = float(
    os.getenv("SPY_QUOTE_REFRESH_SECONDS_OPEN", _SPY_QUOTE_REFRESH_LEGACY or "3")
)
SPY_QUOTE_REFRESH_SECONDS_CLOSED = float(
    os.getenv("SPY_QUOTE_REFRESH_SECONDS_CLOSED", _SPY_QUOTE_REFRESH_LEGACY or "10")
)
SPY_TRACKER_REFRESH_SECONDS = max(0.5, float(os.getenv("SPY_TRACKER_REFRESH_SECONDS", "1.0")))
SPY_TRACKER_MAX_STALE_SECONDS = max(2.0, float(os.getenv("SPY_TRACKER_MAX_STALE_SECONDS", "3.0")))
CODE_SYNC_CHECK_SECONDS = max(2.0, float(os.getenv("CODE_SYNC_CHECK_SECONDS", "5")))
AUTO_REEXEC_ON_COCKPIT_CHANGE = str(
    os.getenv("AUTO_REEXEC_ON_COCKPIT_CHANGE", "1")
).strip().lower() in {"1", "true", "yes", "on"}
AUTO_RESTART_BOT_ON_SCRIPT_CHANGE = str(
    os.getenv("AUTO_RESTART_BOT_ON_SCRIPT_CHANGE", "1")
).strip().lower() in {"1", "true", "yes", "on"}
ENFORCE_RUNTIME_CONFIG_ON_START = str(
    os.getenv("ENFORCE_RUNTIME_CONFIG_ON_START", "1")
).strip().lower() in {"1", "true", "yes", "on"}
ENFORCE_CLEAN_GIT_ON_START = str(
    os.getenv("ENFORCE_CLEAN_GIT_ON_START", "0")
).strip().lower() in {"1", "true", "yes", "on"}
INTERNET_QUALITY_TARGETS = [
    ("Google 204", "https://www.google.com/generate_204"),
    ("Schwab", "https://client.schwab.com/"),
    {"label": "Cloudflare", "url": "https://www.cloudflare.com/cdn-cgi/trace"},
]


def _resolve_schwab_token_path() -> str:
    configured = str(os.getenv("SCHWAB_TOKEN_PATH", "")).strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())

    candidates.extend(
        [
            PROJECT_ROOT / "token.json",
            Path.cwd() / "token.json",
            Path.home() / "token.json",
            Path.home() / "Documents" / "GitHub" / "McLeod-Alpha" / "token.json",
            Path.home() / "Documents" / "GitHub" / "McLeod-Alpha-New" / "token.json",
        ]
    )

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
        except Exception:
            continue

    return str((PROJECT_ROOT / "token.json").resolve())


def _internet_ssl_context():
    """Create a CA-verified SSL context, preferring certifi on macOS Python builds."""
    try:
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    return ssl.create_default_context()


INTERNET_SSL_CONTEXT = _internet_ssl_context()

def _bot_log_candidates():
    candidates = [BOT_LOG_FILE]
    try:
        candidates.extend(sorted(PROJECT_ROOT.glob("bot_output*.log")))
    except Exception:
        pass

    deduped = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _bot_process_log_file(pid=None):
    target_pid = pid or _find_running_bot_pid()
    if not target_pid:
        return None

    try:
        output = subprocess.check_output(
            ["lsof", "-p", str(target_pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None

    for raw_line in output.splitlines():
        line = str(raw_line or "")
        if str(PROJECT_ROOT) not in line:
            continue
        if "bot_output" not in line or ".log" not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        path_text = parts[-1]
        try:
            path = Path(path_text)
        except Exception:
            continue
        if path.exists() and path.is_file():
            return path
    return None


def _resolve_active_bot_log_file():
    process_log = _bot_process_log_file()
    if process_log is not None:
        return process_log

    existing = [path for path in _bot_log_candidates() if path.exists() and path.is_file()]
    if not existing:
        return BOT_LOG_FILE
    return max(existing, key=lambda path: path.stat().st_mtime)


def _format_recent_log_line_et(
    raw_line: str,
    *,
    source_date: date,
    local_tz,
    previous_local_dt: datetime | None,
):
    """Normalize supported log-line timestamps to Eastern Time for dashboard display."""
    line = str(raw_line or "")
    stripped = line.rstrip("\n")

    # Handle ISO-like timestamp prefixes.
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?)(.*)$", stripped)
    if iso_match:
        iso_raw = iso_match.group(1)
        suffix = iso_match.group(2)
        try:
            dt = datetime.fromisoformat(iso_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz)
            dt_et = dt.astimezone(EASTERN_TZ)
            return f"{dt_et.strftime('%Y-%m-%d %H:%M:%S')} ET{suffix}\n", dt.astimezone(local_tz)
        except Exception:
            return raw_line, previous_local_dt

    # Handle hh:mm:ss prefixes used by the live monitor log stream.
    hms_match = re.match(
        r"^(\s*)(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*(ET|EST|EDT|CT|CST|CDT))?(\s*\|.*)$",
        stripped,
    )
    if not hms_match:
        return raw_line, previous_local_dt

    prefix = hms_match.group(1)
    hour = int(hms_match.group(2))
    minute = int(hms_match.group(3))
    second = int(hms_match.group(4) or 0)
    tz_token = (hms_match.group(5) or "").strip().upper()
    suffix = hms_match.group(6)

    if tz_token in {"ET", "EST", "EDT"}:
        source_tz = EASTERN_TZ
    elif tz_token in {"CT", "CST", "CDT"}:
        source_tz = CENTRAL_TZ
    else:
        source_tz = BOT_LOG_SOURCE_TZ

    try:
        local_dt = datetime(
            source_date.year,
            source_date.month,
            source_date.day,
            hour,
            minute,
            second,
            tzinfo=source_tz,
        )
        # If logs cross midnight, roll forward the date to keep time monotonic.
        if previous_local_dt is not None and local_dt < (previous_local_dt - timedelta(hours=12)):
            local_dt = local_dt + timedelta(days=1)
        et_dt = local_dt.astimezone(EASTERN_TZ)
        return f"{prefix}{et_dt.strftime('%H:%M:%S')} ET{suffix}\n", local_dt
    except Exception:
        return raw_line, previous_local_dt


def _load_bot_stop_alert_state():
    loaded = get_memory().load_setting(BOT_STOP_ALERT_STATE_FILE, {})
    return loaded if isinstance(loaded, dict) else {}


def _save_bot_stop_alert_state(state: dict):
    get_memory().save_setting("bot_stop_alert_state", state, BOT_STOP_ALERT_STATE_FILE)


def _bot_stop_alert_recipient():
    return (
        os.getenv("COCKPIT_ALERT_EMAIL", "").strip()
        or os.getenv("DAILY_PNL_TO_EMAIL", "").strip()
        or "MasonMVC@gmail.com"
    )


def _send_bot_stop_email(subject: str, body: str):
    to_email = _bot_stop_alert_recipient()
    transport = os.getenv("COCKPIT_ALERT_TRANSPORT", "auto").strip().lower()

    def _send_via_mailapp() -> bool:
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
                check=False,
            )
            if result.returncode == 0:
                return True
            err = (result.stderr or "").strip() or (result.stdout or "").strip()
            print(f"Cockpit stop email failed (Mail.app): {err}")
            return False
        except Exception as exc:
            print(f"Cockpit stop email failed (Mail.app): {exc}")
            return False

    def _send_via_smtp() -> bool:
        host = os.getenv("SMTP_HOST", "").strip()
        port_raw = os.getenv("SMTP_PORT", "587").strip()
        username = os.getenv("SMTP_USERNAME", "").strip()
        password = os.getenv("SMTP_PASSWORD", "").strip()
        from_email = os.getenv("SMTP_FROM", "").strip() or username

        if not host or not username or not password or not from_email:
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
            print(f"Cockpit stop email failed (SMTP): {exc}")
            return False

    if transport == "smtp":
        return _send_via_smtp()
    if transport == "mailapp":
        return _send_via_mailapp()
    return _send_via_mailapp() or _send_via_smtp()


def _bot_stop_email_body(reason: str, status: dict) -> str:
    lines = [
        f"Reason: {reason}",
        f"Bot running: {bool(status.get('bot_running'))}",
        f"Mode: {status.get('mode') or 'UNKNOWN'}",
        f"Heartbeat age: {status.get('heartbeat_age_seconds') if status.get('heartbeat_age_seconds') is not None else 'unknown'} seconds",
        f"Log stale: {status.get('log_stale')}",
        f"Parity state: {status.get('parity_state') or 'UNKNOWN'}",
        f"Last error: {status.get('last_error') or 'none'}",
    ]
    return "\n".join(lines) + "\n"


def _maybe_notify_bot_stop(status: dict, reason: str | None = None, force: bool = False) -> bool:
    state = _load_bot_stop_alert_state()
    current_running = bool(status.get("bot_running"))
    previous_running = bool(state.get("last_bot_running"))
    now_iso = datetime.now(timezone.utc).isoformat()

    if current_running:
        if not previous_running:
            state["last_bot_running"] = True
            state["last_seen_at"] = now_iso
        state.pop("stop_candidate_at", None)
        state.pop("stop_candidate_reason", None)
        state.pop("stop_candidate_notified", None)
        state["last_seen_at"] = now_iso
        state["last_running_at"] = now_iso
        _save_bot_stop_alert_state(state)
        return False

    if force:
        stop_reason = reason or "Bot process stopped or is no longer running"
        subject = f"Cockpit: Bot stopped - {datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %I:%M %p ET')}"
        sent = _send_bot_stop_email(subject, _bot_stop_email_body(stop_reason, status))
        state["last_bot_running"] = False
        state.pop("stop_candidate_at", None)
        state.pop("stop_candidate_reason", None)
        state.pop("stop_candidate_notified", None)
        state["last_seen_at"] = now_iso
        state["last_notified_at"] = now_iso
        state["last_reason"] = stop_reason
        state["last_email_sent"] = bool(sent)
        _save_bot_stop_alert_state(state)
        return sent

    candidate_started_at = state.get("stop_candidate_at")
    candidate_reason = str(state.get("stop_candidate_reason") or reason or "Bot process stopped or is no longer running")

    if not previous_running:
        state["last_bot_running"] = False
        state["last_seen_at"] = now_iso
        state.pop("stop_candidate_at", None)
        state.pop("stop_candidate_reason", None)
        state.pop("stop_candidate_notified", None)
        _save_bot_stop_alert_state(state)
        return False

    if not candidate_started_at:
        state["stop_candidate_at"] = now_iso
        state["stop_candidate_reason"] = candidate_reason
        state["stop_candidate_notified"] = False
        state["last_seen_at"] = now_iso
        _save_bot_stop_alert_state(state)
        return False

    try:
        candidate_dt = datetime.fromisoformat(str(candidate_started_at))
        candidate_age_seconds = (datetime.now(timezone.utc) - candidate_dt).total_seconds()
    except Exception:
        candidate_age_seconds = 0.0

    if candidate_age_seconds < BOT_STOP_EMAIL_CONFIRMATION_SECONDS:
        state["last_seen_at"] = now_iso
        state["stop_candidate_reason"] = candidate_reason
        _save_bot_stop_alert_state(state)
        return False

    if bool(state.get("stop_candidate_notified")):
        return False

    stop_reason = candidate_reason
    subject = f"Cockpit: Bot stopped - {datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %I:%M %p ET')}"
    sent = _send_bot_stop_email(subject, _bot_stop_email_body(stop_reason, status))
    state["last_bot_running"] = False
    state["last_seen_at"] = now_iso
    state["last_notified_at"] = now_iso
    state["last_reason"] = stop_reason
    state["last_email_sent"] = bool(sent)
    state["stop_candidate_notified"] = bool(sent)
    _save_bot_stop_alert_state(state)
    return sent

NETWORK_STATUS_CACHE_SECONDS = int(os.getenv("NETWORK_STATUS_CACHE_SECONDS", "15"))

_NETWORK_STATUS_CACHE = {
    "timestamp": 0.0,
    "payload": None,
}

_RUNTIME_CONFIG_CACHE = {
    "checked_at": None,
    "errors": [],
    "warnings": [],
}

_RUNTIME_FINGERPRINT_CACHE = {
    "timestamp": 0.0,
    "payload": None,
}

_PARITY_BASELINE_CACHE = {
    "mtime": None,
    "payload": None,
}

EXECUTION_QUALITY_GOALS = {
    "fill_rate_pct": 95.0,
    "fallback_rate_pct": 10.0,
    "avg_slippage": 0.05,
    "avg_slippage_bps": 5.0,
    "side_window_avg_slippage": 0.05,
    "side_window_avg_slippage_bps": 5.0,
}

_BROKER_REALIZED_DAY_CACHE = {
    "timestamp": 0.0,
    "date": None,
    "pnl": None,
}

_BROKER_CLIENT = None
_SPY_TRACKER_THREAD = None
_SPY_TRACKER_LOCK = threading.Lock()
_SPY_TRACKER_STATE = {
    "updated_at": None,
    "source": "UNAVAILABLE",
    "price": None,
    "change": None,
    "change_pct": None,
    "quote_age_seconds": None,
    "quote_as_of": None,
    "stale": True,
    "state": "UNAVAILABLE",
    "last_rest_attempt_ts": 0.0,
    "last_schwab_source": None,
    "last_schwab_price": None,
    "last_schwab_change": None,
    "last_schwab_change_pct": None,
    "last_schwab_quote_as_of": None,
}
EASTERN_TZ = ZoneInfo("America/New_York")
CENTRAL_TZ = ZoneInfo("America/Chicago")
BOT_LOG_SOURCE_TZ = ZoneInfo(os.getenv("BOT_LOG_SOURCE_TZ", "America/Chicago"))
_NYSE_HOLIDAY_CACHE = {}
_NYSE_EARLY_CLOSE_CACHE = {}
_BELL_BROADCAST = {
    "id": 0,
    "kind": "open",
    "triggered_at": None,
    "source": None,
}

_STATUS_SNAPSHOT_CACHE = {
    "timestamp": 0.0,
    "payload": None,
}

_CODE_SYNC_THREAD = None
_CODE_SYNC_LOCK = threading.Lock()


def trigger_bell_broadcast(kind: str = "open", source: str = "manual") -> dict:
    """Create a bell broadcast event consumed by all dashboard sessions."""
    global _BELL_BROADCAST
    normalized_kind = "close" if str(kind).strip().lower() == "close" else "open"
    next_id = int(_BELL_BROADCAST.get("id") or 0) + 1
    _BELL_BROADCAST = {
        "id": next_id,
        "kind": normalized_kind,
        "triggered_at": datetime.now(EASTERN_TZ).isoformat(),
        "source": str(source or "manual"),
    }
    return dict(_BELL_BROADCAST)


def _env_flag(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return str(os.getenv(name, fallback)).strip().lower() in {"1", "true", "yes", "on"}


def _sha256_file(path: Path):
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


_RUNNING_COCKPIT_SHA256 = _sha256_file(Path(__file__))
_RUNNING_BOT_SCRIPT_SHA256 = _sha256_file(BOT_SCRIPT) if BOT_SCRIPT.exists() else None


def _dependency_hash_snapshot():
    py_exe = str(Path(sys.executable))
    try:
        result = subprocess.run(
            [py_exe, "-m", "pip", "freeze", "--disable-pip-version-check"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if result.returncode != 0:
            return None, 0
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("empty pip freeze")
        normalized = "\n".join(sorted(lines))
        digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
        return digest, len(lines)
    except Exception:
        try:
            deps = []
            for dist in importlib.metadata.distributions():
                name = (dist.metadata.get("Name") or "").strip()
                version = (dist.version or "").strip()
                if name and version:
                    deps.append(f"{name}=={version}")
            if not deps:
                return None, 0
            normalized = "\n".join(sorted(set(deps)))
            digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
            return digest, len(set(deps))
        except Exception:
            return None, 0


def _runtime_fingerprint_snapshot(force_refresh: bool = False):
    global _RUNNING_BOT_SCRIPT_SHA256

    now_ts = time.time()
    cached = _RUNTIME_FINGERPRINT_CACHE.get("payload")
    if cached and not force_refresh and (now_ts - float(_RUNTIME_FINGERPRINT_CACHE.get("timestamp") or 0.0)) < 300:
        return dict(cached)

    disk_cockpit_sha = _sha256_file(Path(__file__))
    disk_bot_script_sha = _sha256_file(BOT_SCRIPT) if BOT_SCRIPT.exists() else None
    if _RUNNING_BOT_SCRIPT_SHA256 is None:
        _RUNNING_BOT_SCRIPT_SHA256 = disk_bot_script_sha

    dependency_hash, dep_count = _dependency_hash_snapshot()
    payload = {
        "hostname": socket.gethostname(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_executable": str(Path(sys.executable).resolve()),
        "venv_python": str(VENV_PYTHON.resolve()) if VENV_PYTHON.exists() else str(VENV_PYTHON),
        "bot_python_mode": str(os.getenv("BOT_PYTHON_MODE", "newest")).strip().lower(),
        "project_root": str(PROJECT_ROOT.resolve()),
        # Runtime hashes reflect the code currently executing in-memory.
        "cockpit_sha256": _RUNNING_COCKPIT_SHA256,
        "bot_script_sha256": _RUNNING_BOT_SCRIPT_SHA256,
        # Disk hashes expose pending sync/restart drift.
        "cockpit_disk_sha256": disk_cockpit_sha,
        "bot_script_disk_sha256": disk_bot_script_sha,
        "cockpit_drift": bool(
            _RUNNING_COCKPIT_SHA256 and disk_cockpit_sha and _RUNNING_COCKPIT_SHA256 != disk_cockpit_sha
        ),
        "bot_script_drift": bool(
            _RUNNING_BOT_SCRIPT_SHA256 and disk_bot_script_sha and _RUNNING_BOT_SCRIPT_SHA256 != disk_bot_script_sha
        ),
        "dependency_hash": dependency_hash,
        "dependency_count": dep_count,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    _RUNTIME_FINGERPRINT_CACHE["timestamp"] = now_ts
    _RUNTIME_FINGERPRINT_CACHE["payload"] = dict(payload)
    return payload


def _parity_baseline_from_fingerprint(fingerprint: dict):
    return {
        "cockpit_sha256": fingerprint.get("cockpit_sha256"),
        "bot_script_sha256": fingerprint.get("bot_script_sha256"),
        "python_version": fingerprint.get("python_version"),
        "dependency_hash": fingerprint.get("dependency_hash"),
        "bot_python_mode": fingerprint.get("bot_python_mode"),
    }


def _save_parity_baseline(payload: dict):
    memory = get_memory()
    memory.save_setting("parity_baseline", payload, PARITY_BASELINE_FILE)
    _PARITY_BASELINE_CACHE["mtime"] = memory.setting_projection_revision(PARITY_BASELINE_FILE)
    _PARITY_BASELINE_CACHE["payload"] = dict(payload)


def _load_parity_baseline(force_reload: bool = False):
    try:
        memory = get_memory()
        current_mtime = memory.setting_projection_revision(PARITY_BASELINE_FILE)
        if current_mtime is None:
            _PARITY_BASELINE_CACHE["mtime"] = None
            _PARITY_BASELINE_CACHE["payload"] = None
            return None

        if (
            not force_reload
            and _PARITY_BASELINE_CACHE.get("payload") is not None
            and _PARITY_BASELINE_CACHE.get("mtime") == current_mtime
        ):
            return dict(_PARITY_BASELINE_CACHE["payload"])

        loaded = memory.load_setting(PARITY_BASELINE_FILE)
        if not isinstance(loaded, dict):
            return None

        _PARITY_BASELINE_CACHE["mtime"] = current_mtime
        _PARITY_BASELINE_CACHE["payload"] = dict(loaded)
        return loaded
    except Exception:
        return None


def _parity_status_snapshot():
    fingerprint = _runtime_fingerprint_snapshot()
    baseline = _load_parity_baseline()

    auto_adopt = _env_flag("PARITY_AUTO_ADOPT_RUNTIME", default=False)
    runtime_fp = _parity_baseline_from_fingerprint(fingerprint)
    baseline_fp = baseline.get("fingerprint") if isinstance((baseline or {}).get("fingerprint"), dict) else (baseline or {})
    baseline_matches_runtime = all(
        (baseline_fp.get(key) == runtime_fp.get(key))
        for key in ("cockpit_sha256", "bot_script_sha256", "python_version", "dependency_hash", "bot_python_mode")
    )

    if auto_adopt and (baseline is None or not baseline_matches_runtime):
        now_iso = datetime.now(timezone.utc).isoformat()
        created_at = None
        if isinstance(baseline, dict):
            created_at = baseline.get("created_at")
        baseline = {
            "version": 1,
            "created_at": created_at or now_iso,
            "updated_at": now_iso,
            "created_on_host": fingerprint.get("hostname"),
            "auto_adopted": True,
            "fingerprint": runtime_fp,
        }
        _save_parity_baseline(baseline)
    elif baseline is None and _env_flag("AUTO_CREATE_PARITY_BASELINE", default=True):
        baseline = {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint": runtime_fp,
            "created_on_host": fingerprint.get("hostname"),
        }
        _save_parity_baseline(baseline)

    if baseline is None:
        return {
            "state": "UNSET",
            "summary": "Parity baseline file not found",
            "issues": ["Parity baseline is not set"],
            "runtime_fingerprint": fingerprint,
            "baseline_path": str(PARITY_BASELINE_FILE),
        }

    baseline_fp = baseline.get("fingerprint") if isinstance(baseline.get("fingerprint"), dict) else baseline
    keys = (
        "cockpit_sha256",
        "bot_script_sha256",
        "python_version",
        "dependency_hash",
        "bot_python_mode",
    )
    issues = []
    for key in keys:
        expected = baseline_fp.get(key)
        observed = fingerprint.get(key)
        if expected and observed and expected != observed:
            issues.append(f"{key} differs")

    if issues:
        return {
            "state": "MISMATCH",
            "summary": "Runtime differs from parity baseline",
            "issues": issues,
            "runtime_fingerprint": fingerprint,
            "baseline_path": str(PARITY_BASELINE_FILE),
        }

    return {
        "state": "MATCH",
        "summary": "Runtime matches parity baseline",
        "issues": [],
        "runtime_fingerprint": fingerprint,
        "baseline_path": str(PARITY_BASELINE_FILE),
    }


def _parity_start_guard_payload():
    """Return an API error payload when parity enforcement blocks bot start."""
    enforce = _env_flag("PARITY_ENFORCE_ON_START", default=True)
    if not enforce:
        return None

    parity = _parity_status_snapshot()
    parity_state = str(parity.get("state") or "UNKNOWN").upper()
    if parity_state == "MATCH":
        return None

    issues = list(parity.get("issues") or [])
    issue_text = ", ".join(issues) if issues else str(parity.get("summary") or "parity check failed")
    return {
        "status": "error",
        "message": (
            f"Start blocked by parity lock ({parity_state}). {issue_text}. "
            "Parity baseline will auto-sync to the active machine when PARITY_AUTO_ADOPT_RUNTIME is enabled."
        ),
        "parity_state": parity_state,
        "parity_summary": parity.get("summary"),
        "parity_issues": issues,
        "parity_baseline_path": str(parity.get("baseline_path") or PARITY_BASELINE_FILE),
    }


def _nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> date:
    """Return the date of the Nth weekday in a given month.

    weekday: Monday=0 ... Sunday=6
    occurrence: 1..5
    """
    first_weekday, days_in_month = calendar.monthrange(year, month)
    day = 1 + ((weekday - first_weekday) % 7) + (occurrence - 1) * 7
    if day > days_in_month:
        raise ValueError("Occurrence exceeds days in month")
    return date(year, month, day)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return the date of the last weekday in a given month."""
    _, days_in_month = calendar.monthrange(year, month)
    d = date(year, month, days_in_month)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed_fixed_holiday(d: date) -> date:
    """Observe fixed-date holidays on nearest weekday when they fall on weekend."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def _monday_to_sunday_week_bounds(d: date) -> tuple[date, date]:
    """Return the calendar-week bounds for Monday-through-Sunday reporting."""
    week_start = d - timedelta(days=d.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _easter_sunday(year: int) -> date:
    """Compute Gregorian Easter Sunday using Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nyse_holidays_for_year(year: int):
    cached = _NYSE_HOLIDAY_CACHE.get(year)
    if cached is not None:
        return cached

    holidays = set()
    holidays.add(_observed_fixed_holiday(date(year, 1, 1)))   # New Year's Day
    holidays.add(_nth_weekday_of_month(year, 1, 0, 3))        # Martin Luther King Jr. Day
    holidays.add(_nth_weekday_of_month(year, 2, 0, 3))        # Presidents' Day
    holidays.add(_easter_sunday(year) - timedelta(days=2))    # Good Friday
    holidays.add(_last_weekday_of_month(year, 5, 0))          # Memorial Day
    holidays.add(_observed_fixed_holiday(date(year, 6, 19)))  # Juneteenth
    holidays.add(_observed_fixed_holiday(date(year, 7, 4)))   # Independence Day
    holidays.add(_nth_weekday_of_month(year, 9, 0, 1))        # Labor Day
    holidays.add(_nth_weekday_of_month(year, 11, 3, 4))       # Thanksgiving
    holidays.add(_observed_fixed_holiday(date(year, 12, 25))) # Christmas

    _NYSE_HOLIDAY_CACHE[year] = holidays
    return holidays


def _is_nyse_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _nyse_holidays_for_year(d.year)


def _nyse_early_closes_for_year(year: int):
    cached = _NYSE_EARLY_CLOSE_CACHE.get(year)
    if cached is not None:
        return cached

    early = set()

    # Day after Thanksgiving (Friday)
    thanksgiving = _nth_weekday_of_month(year, 11, 3, 4)
    day_after_thanksgiving = thanksgiving + timedelta(days=1)
    if _is_nyse_trading_day(day_after_thanksgiving):
        early.add(day_after_thanksgiving)

    # Christmas Eve (when it's a trading day)
    christmas_eve = date(year, 12, 24)
    if _is_nyse_trading_day(christmas_eve):
        early.add(christmas_eve)

    # Typically July 3 when it is a trading day.
    july_3 = date(year, 7, 3)
    if _is_nyse_trading_day(july_3):
        early.add(july_3)

    _NYSE_EARLY_CLOSE_CACHE[year] = early
    return early


def _nyse_regular_close_time_for_date(d: date) -> str:
    """Return NYSE close time in ET HH:MM:SS for the given date."""
    if d in _nyse_early_closes_for_year(d.year):
        return "13:00:00"
    return "16:00:00"


def _get_broker_client():
    global _BROKER_CLIENT
    if _BROKER_CLIENT is not None:
        return _BROKER_CLIENT

    _BROKER_CLIENT = easy_client(
        api_key=os.getenv("SCHWAB_APP_KEY"),
        app_secret=os.getenv("SCHWAB_APP_SECRET"),
        callback_url=os.getenv("SCHWAB_CALLBACK_URL"),
        token_path=_resolve_schwab_token_path(),
        enforce_enums=False,
    )
    return _BROKER_CLIENT


def _get_spy_quote_stream():
    global _SPY_QUOTE_STREAM
    try:
        stream = _SPY_QUOTE_STREAM
    except NameError:
        _SPY_QUOTE_STREAM = None
        stream = None

    if stream is None:
        stream = SchwabEquityQuoteStream(_get_broker_client(), "SPY")
        _SPY_QUOTE_STREAM = stream

    if not stream.is_healthy():
        try:
            stream.start()
        except Exception:
            pass
    return stream


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_alpaca_headers():
    api_key = (
        os.getenv("APCA_API_KEY_ID")
        or os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("ALPACA_API_KEY")
        or ""
    ).strip()
    api_secret = (
        os.getenv("APCA_API_SECRET_KEY")
        or os.getenv("ALPACA_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET")
        or ""
    ).strip()
    if not api_key or not api_secret:
        return None
    return {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }


def _extract_alpaca_spy_quote_fields():
    headers = _get_alpaca_headers()
    if not headers:
        return {}

    quote_payload = {}
    trade_payload = {}
    try:
        resp = requests.get(f"{ALPACA_DATA_URL}/v2/stocks/SPY/quotes/latest", headers=headers, timeout=10)
        resp.raise_for_status()
        quote_payload = resp.json() or {}
    except Exception:
        quote_payload = {}

    try:
        resp = requests.get(f"{ALPACA_DATA_URL}/v2/stocks/SPY/trades/latest", headers=headers, timeout=10)
        resp.raise_for_status()
        trade_payload = resp.json() or {}
    except Exception:
        trade_payload = {}

    quote = quote_payload.get("quote") or {}
    trade = trade_payload.get("trade") or {}

    spy_price = None
    for candidate in (
        trade.get("p"),
        quote.get("ap"),
        quote.get("bp"),
    ):
        spy_price = _safe_float(candidate)
        if spy_price is not None and spy_price > 0:
            break

    quote_time = None
    for candidate in (trade.get("t"), quote.get("t")):
        text = str(candidate or "").strip()
        if not text:
            continue
        try:
            quote_time = datetime.fromisoformat(text.replace("Z", "+00:00"))
            break
        except Exception:
            continue

    if spy_price is None or quote_time is None:
        return {}

    return {
        "spy_price": spy_price,
        "spy_close_candidate": None,
        "spy_change": None,
        "spy_change_pct": None,
        "quote_time_ms": int(quote_time.timestamp() * 1000),
    }


def _extract_yahoo_spy_quote_fields():
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": "SPY"},
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception:
        return {}

    rows = (((payload or {}).get("quoteResponse") or {}).get("result") or [])
    if not rows:
        return {}

    row = rows[0] or {}
    spy_price = None
    for candidate in (
        row.get("regularMarketPrice"),
        row.get("postMarketPrice"),
        row.get("preMarketPrice"),
        row.get("bid"),
        row.get("ask"),
    ):
        spy_price = _safe_float(candidate)
        if spy_price is not None and spy_price > 0:
            break
    if spy_price is None:
        return {}

    quote_time_ms = None
    market_time = row.get("regularMarketTime")
    try:
        if market_time is not None:
            quote_time_ms = int(float(market_time) * 1000)
    except (TypeError, ValueError):
        quote_time_ms = None

    spy_change = _safe_float(row.get("regularMarketChange"))
    spy_change_pct = _safe_float(row.get("regularMarketChangePercent"))
    prev_close = _safe_float(row.get("regularMarketPreviousClose"))

    return {
        "spy_price": spy_price,
        "spy_close_candidate": prev_close,
        "spy_change": spy_change,
        "spy_change_pct": spy_change_pct,
        "quote_time_ms": quote_time_ms,
    }


def _extract_nasdaq_public_spy_quote_fields():
    try:
        resp = requests.get(
            "https://api.nasdaq.com/api/quote/SPY/info",
            params={"assetclass": "etf"},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://www.nasdaq.com/",
            },
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception:
        return {}

    data = (payload or {}).get("data") or {}
    primary = data.get("primaryData") or {}
    if not primary:
        return {}

    def _parse_money(value):
        cleaned = str(value or "").replace("$", "").replace(",", "").strip()
        return _safe_float(cleaned)

    def _parse_percent(value):
        cleaned = str(value or "").replace("%", "").replace(",", "").strip()
        return _safe_float(cleaned)

    spy_price = _parse_money(primary.get("lastSalePrice"))
    if spy_price is None or spy_price <= 0:
        return {}

    spy_change = _parse_money(primary.get("netChange"))
    spy_change_pct = _parse_percent(primary.get("percentageChange"))
    if spy_change_pct is None and spy_change is not None and spy_price is not None:
        prev_close = spy_price - spy_change
        if prev_close:
            spy_change_pct = (spy_change / prev_close) * 100.0

    spy_close_candidate = None
    if spy_change is not None:
        spy_close_candidate = spy_price - spy_change

    return {
        "spy_price": spy_price,
        "spy_close_candidate": spy_close_candidate,
        "spy_change": spy_change,
        "spy_change_pct": spy_change_pct,
        # Nasdaq public endpoint can be delayed; omit source time so tracker uses arrival time.
        "quote_time_ms": None,
    }


def _extract_spy_quote_fields(payload: dict):
    symbol_blob = payload.get("SPY") or next(iter(payload.values()), {})
    quote = symbol_blob.get("quote") or {}

    bid_price = _safe_float(quote.get("bidPrice"))
    ask_price = _safe_float(quote.get("askPrice"))
    last_price = _safe_float(quote.get("lastPrice"))
    mark_price = _safe_float(quote.get("mark"))

    quote_time_ms = None
    for candidate in (
        quote.get("quoteTime"),
        quote.get("tradeTime"),
    ):
        try:
            if candidate is not None and int(candidate) > 0:
                quote_time_ms = int(candidate)
                break
        except (TypeError, ValueError):
            continue

    mid_price = None
    if bid_price is not None and ask_price is not None and bid_price > 0 and ask_price > 0:
        mid_price = (bid_price + ask_price) / 2.0

    spy_price = None
    for candidate in (
        mid_price,
        mark_price,
        last_price,
        bid_price,
        ask_price,
        quote.get("closePrice"),
    ):
        spy_price = _safe_float(candidate)
        if spy_price is not None and spy_price > 0:
            break

    spy_close_candidate = _safe_float(quote.get("closePrice"))
    if spy_close_candidate is None:
        raw_change = _safe_float(quote.get("netChange"))
        if spy_price is not None and raw_change is not None:
            spy_close_candidate = spy_price - raw_change

    spy_change = None
    for candidate in (
        quote.get("netChange"),
        quote.get("markChange"),
        quote.get("change"),
        quote.get("regularMarketNetChange"),
    ):
        spy_change = _safe_float(candidate)
        if spy_change is not None:
            break

    spy_change_pct = None
    for candidate in (
        quote.get("netPercentChange"),
        quote.get("percentChange"),
        quote.get("markPercentChange"),
        quote.get("regularMarketPercentChangeInDouble"),
    ):
        spy_change_pct = _safe_float(candidate)
        if spy_change_pct is not None:
            break

    if spy_change_pct is None and spy_price is not None and spy_change is not None:
        prev_close = spy_price - spy_change
        if prev_close:
            spy_change_pct = (spy_change / prev_close) * 100.0

    return {
        "spy_price": spy_price,
        "spy_close_candidate": spy_close_candidate,
        "spy_change": spy_change,
        "spy_change_pct": spy_change_pct,
        "quote_time_ms": quote_time_ms,
    }


def _apply_spy_quote_snapshot(status: dict, quote_fields: dict, source: str, now_ts: float, now_et_live: datetime):
    spy_price = quote_fields.get("spy_price")
    spy_close_candidate = quote_fields.get("spy_close_candidate")
    spy_change = quote_fields.get("spy_change")
    spy_change_pct = quote_fields.get("spy_change_pct")
    quote_time_ms = quote_fields.get("quote_time_ms")

    if spy_price is not None:
        status["spy_price"] = round(spy_price, 2)
    if spy_change is not None:
        status["spy_change"] = round(spy_change, 2)
    if spy_change_pct is not None:
        status["spy_change_pct"] = round(spy_change_pct, 2)

    close_date = _latest_completed_nyse_close_date(now_et_live)
    if close_date and spy_close_candidate is not None and spy_close_candidate > 0:
        cached_close_date = str(_SPY_CLOSE_BASELINE_CACHE.get("trading_date") or "")
        target_close_date = close_date.isoformat()
        if cached_close_date != target_close_date:
            _SPY_CLOSE_BASELINE_CACHE["trading_date"] = target_close_date
        _SPY_CLOSE_BASELINE_CACHE["close_price"] = float(spy_close_candidate)
        _SPY_CLOSE_BASELINE_CACHE["updated_at"] = datetime.now(timezone.utc).isoformat()

    _apply_spy_close_baseline(status)

    if spy_price is not None and spy_price > 0:
        quote_ts = (quote_time_ms / 1000.0) if quote_time_ms else now_ts
        age_seconds = max(0.0, now_ts - quote_ts)
        _SPY_QUOTE_CACHE["timestamp"] = quote_ts
        _SPY_QUOTE_CACHE["price"] = float(spy_price)
        _SPY_QUOTE_CACHE["change"] = float(spy_change) if spy_change is not None else None
        _SPY_QUOTE_CACHE["change_pct"] = float(spy_change_pct) if spy_change_pct is not None else None
        _SPY_QUOTE_CACHE["as_of"] = datetime.fromtimestamp(quote_ts, tz=timezone.utc).isoformat()
        _SPY_QUOTE_CACHE["source"] = source
        status["spy_quote_stale"] = age_seconds > max(5.0, float(status.get("spy_quote_refresh_seconds_current") or 0.0) * 2.0)
        status["spy_quote_age_seconds"] = round(age_seconds, 1)
        status["spy_quote_as_of"] = _SPY_QUOTE_CACHE["as_of"]
        status["spy_quote_state"] = source


def _spy_tracker_apply_quote(quote_fields: dict, source: str, now_ts: float, now_et_live: datetime):
    spy_price = quote_fields.get("spy_price")
    if spy_price is None or spy_price <= 0:
        return

    spy_change = quote_fields.get("spy_change")
    spy_change_pct = quote_fields.get("spy_change_pct")
    quote_time_ms = quote_fields.get("quote_time_ms")
    spy_close_candidate = quote_fields.get("spy_close_candidate")

    close_date = _latest_completed_nyse_close_date(now_et_live)
    if close_date and spy_close_candidate is not None and spy_close_candidate > 0:
        cached_close_date = str(_SPY_CLOSE_BASELINE_CACHE.get("trading_date") or "")
        target_close_date = close_date.isoformat()
        if cached_close_date != target_close_date:
            _SPY_CLOSE_BASELINE_CACHE["trading_date"] = target_close_date
        _SPY_CLOSE_BASELINE_CACHE["close_price"] = float(spy_close_candidate)
        _SPY_CLOSE_BASELINE_CACHE["updated_at"] = datetime.now(timezone.utc).isoformat()

    quote_ts = (quote_time_ms / 1000.0) if quote_time_ms else now_ts
    age_seconds = max(0.0, now_ts - quote_ts)
    quote_as_of_iso = datetime.fromtimestamp(quote_ts, tz=timezone.utc).isoformat()
    stale = age_seconds > float(SPY_TRACKER_MAX_STALE_SECONDS)
    state_label = quote_state_from_age(
        age_seconds,
        max_stale_seconds=SPY_QUOTE_MAX_STALE_SECONDS,
        refresh_seconds=SPY_TRACKER_REFRESH_SECONDS,
    )

    with _SPY_TRACKER_LOCK:
        _SPY_TRACKER_STATE["updated_at"] = datetime.now(timezone.utc).isoformat()
        _SPY_TRACKER_STATE["source"] = source
        _SPY_TRACKER_STATE["price"] = round(float(spy_price), 2)
        _SPY_TRACKER_STATE["change"] = round(float(spy_change), 2) if spy_change is not None else None
        _SPY_TRACKER_STATE["change_pct"] = round(float(spy_change_pct), 2) if spy_change_pct is not None else None
        _SPY_TRACKER_STATE["quote_age_seconds"] = round(age_seconds, 2)
        _SPY_TRACKER_STATE["quote_as_of"] = quote_as_of_iso
        _SPY_TRACKER_STATE["stale"] = bool(stale)
        _SPY_TRACKER_STATE["state"] = state_label
        if str(source).startswith("SCHWAB"):
            _SPY_TRACKER_STATE["last_schwab_source"] = source
            _SPY_TRACKER_STATE["last_schwab_price"] = round(float(spy_price), 2)
            _SPY_TRACKER_STATE["last_schwab_change"] = round(float(spy_change), 2) if spy_change is not None else None
            _SPY_TRACKER_STATE["last_schwab_change_pct"] = round(float(spy_change_pct), 2) if spy_change_pct is not None else None
            _SPY_TRACKER_STATE["last_schwab_quote_as_of"] = quote_as_of_iso

    # Keep cache in sync for existing downstream compatibility.
    _SPY_QUOTE_CACHE["timestamp"] = quote_ts
    _SPY_QUOTE_CACHE["price"] = float(spy_price)
    _SPY_QUOTE_CACHE["change"] = float(spy_change) if spy_change is not None else None
    _SPY_QUOTE_CACHE["change_pct"] = float(spy_change_pct) if spy_change_pct is not None else None
    _SPY_QUOTE_CACHE["as_of"] = quote_as_of_iso
    _SPY_QUOTE_CACHE["source"] = source


def _spy_tracker_restore_last_schwab(now_ts: float) -> bool:
    with _SPY_TRACKER_LOCK:
        quote_as_of_iso = str(_SPY_TRACKER_STATE.get("last_schwab_quote_as_of") or "").strip()
        price = _SPY_TRACKER_STATE.get("last_schwab_price")
        change = _SPY_TRACKER_STATE.get("last_schwab_change")
        change_pct = _SPY_TRACKER_STATE.get("last_schwab_change_pct")
        source = str(_SPY_TRACKER_STATE.get("last_schwab_source") or "SCHWAB_REST")

    if price is None or not quote_as_of_iso:
        return False

    try:
        quote_dt = datetime.fromisoformat(quote_as_of_iso.replace("Z", "+00:00"))
        if quote_dt.tzinfo is None:
            quote_dt = quote_dt.replace(tzinfo=timezone.utc)
        quote_ts = quote_dt.timestamp()
    except Exception:
        return False

    age_seconds = max(0.0, now_ts - quote_ts)
    state_label = quote_state_from_age(
        age_seconds,
        max_stale_seconds=SPY_QUOTE_MAX_STALE_SECONDS,
        refresh_seconds=SPY_TRACKER_REFRESH_SECONDS,
    )
    stale = age_seconds > float(SPY_TRACKER_MAX_STALE_SECONDS)

    with _SPY_TRACKER_LOCK:
        _SPY_TRACKER_STATE["updated_at"] = datetime.now(timezone.utc).isoformat()
        _SPY_TRACKER_STATE["source"] = source
        _SPY_TRACKER_STATE["price"] = price
        _SPY_TRACKER_STATE["change"] = change
        _SPY_TRACKER_STATE["change_pct"] = change_pct
        _SPY_TRACKER_STATE["quote_age_seconds"] = round(age_seconds, 2)
        _SPY_TRACKER_STATE["quote_as_of"] = quote_as_of_iso
        _SPY_TRACKER_STATE["stale"] = bool(stale)
        _SPY_TRACKER_STATE["state"] = state_label

    _SPY_QUOTE_CACHE["timestamp"] = quote_ts
    _SPY_QUOTE_CACHE["price"] = float(price)
    _SPY_QUOTE_CACHE["change"] = float(change) if change is not None else None
    _SPY_QUOTE_CACHE["change_pct"] = float(change_pct) if change_pct is not None else None
    _SPY_QUOTE_CACHE["as_of"] = quote_as_of_iso
    _SPY_QUOTE_CACHE["source"] = source
    return True


def _spy_tracker_mark_unavailable(now_ts: float):
    if _spy_tracker_restore_last_schwab(now_ts):
        return

    with _SPY_TRACKER_LOCK:
        _SPY_TRACKER_STATE["updated_at"] = datetime.now(timezone.utc).isoformat()
        _SPY_TRACKER_STATE["source"] = "UNAVAILABLE"
        _SPY_TRACKER_STATE["price"] = None
        _SPY_TRACKER_STATE["change"] = None
        _SPY_TRACKER_STATE["change_pct"] = None
        _SPY_TRACKER_STATE["quote_age_seconds"] = None
        _SPY_TRACKER_STATE["quote_as_of"] = None
        _SPY_TRACKER_STATE["stale"] = True
        _SPY_TRACKER_STATE["state"] = "UNAVAILABLE"


def _run_spy_tracker_once(now_ts: float | None = None):
    if now_ts is None:
        now_ts = time.time()
    now_et_live = datetime.now(EASTERN_TZ)

    stream_payload = None
    try:
        stream_payload = _get_spy_quote_stream().get_latest_quote_payload()
    except Exception:
        stream_payload = None

    stream_quote_fields = _extract_spy_quote_fields(stream_payload) if stream_payload else {}
    stream_price = stream_quote_fields.get("spy_price")
    stream_quote_ms = stream_quote_fields.get("quote_time_ms")
    stream_age_seconds = max(0.0, now_ts - (stream_quote_ms / 1000.0)) if stream_quote_ms else 0.0
    stream_is_fresh = bool(
        stream_price is not None
        and stream_price > 0
        and stream_age_seconds <= float(SPY_TRACKER_MAX_STALE_SECONDS)
    )

    if stream_is_fresh:
        _spy_tracker_apply_quote(stream_quote_fields, "SCHWAB_STREAM_LIVE", now_ts, now_et_live)
        return

    # REST quote fallback throttled to avoid over-polling when stream is stale.
    should_try_rest = False
    with _SPY_TRACKER_LOCK:
        last_rest_attempt_ts = float(_SPY_TRACKER_STATE.get("last_rest_attempt_ts") or 0.0)
        if (now_ts - last_rest_attempt_ts) >= max(1.0, float(SPY_TRACKER_REFRESH_SECONDS)):
            _SPY_TRACKER_STATE["last_rest_attempt_ts"] = now_ts
            should_try_rest = True

    if should_try_rest:
        try:
            client = _get_broker_client()
            resp = client.get_quote("SPY")
            resp.raise_for_status()
            payload = resp.json() or {}
            rest_quote_fields = _extract_spy_quote_fields(payload)
            rest_price = rest_quote_fields.get("spy_price")
            rest_quote_ms = rest_quote_fields.get("quote_time_ms")
            rest_age_seconds = max(0.0, now_ts - (rest_quote_ms / 1000.0)) if rest_quote_ms else 0.0
            rest_is_fresh = bool(
                rest_price is not None
                and rest_price > 0
                and rest_age_seconds <= float(SPY_TRACKER_MAX_STALE_SECONDS)
            )
            if rest_is_fresh:
                _spy_tracker_apply_quote(rest_quote_fields, "SCHWAB_REST_LIVE", now_ts, now_et_live)
                return
        except Exception:
            pass

    try:
        alpaca_quote_fields = _extract_alpaca_spy_quote_fields()
        alpaca_price = alpaca_quote_fields.get("spy_price")
        alpaca_quote_ms = alpaca_quote_fields.get("quote_time_ms")
        alpaca_age_seconds = max(0.0, now_ts - (alpaca_quote_ms / 1000.0)) if alpaca_quote_ms else 0.0
        alpaca_is_fresh = bool(
            alpaca_price is not None
            and alpaca_price > 0
            and alpaca_age_seconds <= float(SPY_TRACKER_MAX_STALE_SECONDS)
        )
        if alpaca_is_fresh:
            _spy_tracker_apply_quote(alpaca_quote_fields, "ALPACA_LIVE", now_ts, now_et_live)
            return
    except Exception:
        pass

    try:
        yahoo_quote_fields = _extract_yahoo_spy_quote_fields()
        yahoo_price = yahoo_quote_fields.get("spy_price")
        yahoo_quote_ms = yahoo_quote_fields.get("quote_time_ms")
        yahoo_age_seconds = max(0.0, now_ts - (yahoo_quote_ms / 1000.0)) if yahoo_quote_ms else 0.0
        yahoo_is_fresh = bool(
            yahoo_price is not None
            and yahoo_price > 0
            and yahoo_age_seconds <= float(SPY_TRACKER_MAX_STALE_SECONDS)
        )
        if yahoo_is_fresh:
            _spy_tracker_apply_quote(yahoo_quote_fields, "YAHOO_LIVE", now_ts, now_et_live)
            return
    except Exception:
        pass

    try:
        nasdaq_quote_fields = _extract_nasdaq_public_spy_quote_fields()
        nasdaq_price = nasdaq_quote_fields.get("spy_price")
        nasdaq_quote_ms = nasdaq_quote_fields.get("quote_time_ms")
        nasdaq_age_seconds = max(0.0, now_ts - (nasdaq_quote_ms / 1000.0)) if nasdaq_quote_ms else 0.0
        nasdaq_is_fresh = bool(
            nasdaq_price is not None
            and nasdaq_price > 0
            and nasdaq_age_seconds <= float(SPY_TRACKER_MAX_STALE_SECONDS)
        )
        if nasdaq_is_fresh:
            _spy_tracker_apply_quote(nasdaq_quote_fields, "NASDAQ_PUBLIC_DELAYED", now_ts, now_et_live)
            return
    except Exception:
        pass

    _spy_tracker_mark_unavailable(now_ts)


def _spy_tracker_loop():
    while True:
        try:
            _run_spy_tracker_once()
        except Exception:
            _spy_tracker_mark_unavailable(time.time())
        time.sleep(float(SPY_TRACKER_REFRESH_SECONDS))


def _ensure_spy_tracker_running():
    global _SPY_TRACKER_THREAD
    with _SPY_TRACKER_LOCK:
        thread = _SPY_TRACKER_THREAD
        if thread is not None and thread.is_alive():
            return
        _SPY_TRACKER_THREAD = threading.Thread(
            target=_spy_tracker_loop,
            name="spy-price-tracker",
            daemon=True,
        )
        _SPY_TRACKER_THREAD.start()


def _spy_tracker_snapshot() -> dict:
    with _SPY_TRACKER_LOCK:
        return dict(_SPY_TRACKER_STATE)


def _title_case_words(value: str) -> str:
    words = str(value or "").strip().split()
    return " ".join(word[:1].upper() + word[1:].lower() if word else "" for word in words)


def _log_daily_trades_chart_snapshot(trading_date, trades, summary, is_fallback_day):
    dated_svg = DAILY_TRADES_CHART_DIR / f"daily_trades_chart_{trading_date}.svg"
    latest_svg = DAILY_TRADES_CHART_DIR / "latest_daily_trades_chart.svg"
    dated_json = DAILY_TRADES_CHART_DIR / f"daily_trades_chart_{trading_date}.json"
    latest_json = DAILY_TRADES_CHART_DIR / "latest_daily_trades_chart.json"

    rows = list(trades or [])
    bar_values = []
    for index, trade in enumerate(rows[:14], 1):
        try:
            pnl = float(trade.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        bar_values.append({
            "index": index,
            "label": str(trade.get("option_symbol") or trade.get("direction") or f"Trade {index}"),
            "pnl": pnl,
        })

    width = 1120
    height = 420
    chart_top = 90
    chart_left = 70
    chart_right = 1040
    chart_bottom = 320
    chart_height = chart_bottom - chart_top
    chart_width = chart_right - chart_left
    bar_count = max(1, len(bar_values))
    gap = 12
    bar_width = max(18, (chart_width - (gap * (bar_count - 1))) / bar_count)
    max_abs = max([abs(item["pnl"]) for item in bar_values] + [1.0])
    baseline = chart_top + (chart_height / 2)

    def scale(amount):
        return max(6, (abs(amount) / max_abs) * ((chart_height / 2) - 24))

    bars = []
    labels = []
    for idx, item in enumerate(bar_values):
        x = chart_left + idx * (bar_width + gap)
        pnl = item["pnl"]
        bar_h = scale(pnl)
        if pnl >= 0:
            y = baseline - bar_h
            color = "#28a745"
        else:
            y = baseline
            color = "#dc3545"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" rx="6" fill="{color}" opacity="0.9"><title>{item["label"]}: ${pnl:,.2f}</title></rect>'
        )
        label_y = chart_bottom + 24
        labels.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{label_y:.1f}" text-anchor="middle" font-size="12" fill="#52616f">{item["index"]}</text>'
        )

    pnl_total = float(summary.get("total_pnl") or 0.0)
    win_rate = float(summary.get("win_rate") or 0.0)
    trade_count = int(summary.get("total_trades") or 0)
    chart_caption = "No trades to chart" if not bar_values else "Daily trades P&L snapshot"

    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>
  <rect x='0' y='0' width='{width}' height='{height}' rx='18' fill='#ffffff'/>
  <rect x='18' y='18' width='{width - 36}' height='{height - 36}' rx='16' fill='#f8fafc' stroke='#dbe4ee'/>
  <text x='40' y='56' font-size='24' font-weight='700' fill='#111827'>Daily Trades Chart</text>
  <text x='40' y='80' font-size='13' fill='#6b7280'>Date: {trading_date} | {'Fallback day' if is_fallback_day else 'Today'} | Trades: {trade_count} | Win rate: {win_rate:.1f}% | Total P&amp;L: ${pnl_total:,.2f}</text>
  <line x1='{chart_left}' y1='{baseline:.1f}' x2='{chart_right}' y2='{baseline:.1f}' stroke='#9ca3af' stroke-width='2'/>
  {''.join(bars) if bars else '<text x="560" y="185" text-anchor="middle" font-size="16" fill="#6b7280">No trades to chart</text>'}
  {''.join(labels)}
  <text x='{chart_left}' y='360' font-size='12' fill='#6b7280'>{chart_caption}</text>
  <text x='{chart_left}' y='380' font-size='12' fill='#6b7280'>Positive bars are green; negative bars are red.</text>
</svg>"""

    payload = {
        "trading_date": trading_date,
        "generated_at": datetime.now(EASTERN_TZ).isoformat(),
        "is_fallback_day": bool(is_fallback_day),
        "summary": summary,
        "trade_count": trade_count,
        "chart_file": str(dated_svg),
    }

    memory = get_memory()
    correlation_id = f"daily-trades-chart:{trading_date}"
    memory.write_report_text(dated_svg, svg, "daily_trades_chart", source="cockpit", correlation_id=correlation_id)
    memory.write_report_text(latest_svg, svg, "daily_trades_chart", source="cockpit", correlation_id=correlation_id)
    memory.write_report_json(dated_json, payload, "daily_trades_chart", source="cockpit", correlation_id=correlation_id)
    memory.write_report_json(latest_json, payload, "daily_trades_chart", source="cockpit", correlation_id=correlation_id)
    memory.append_report_line(
        DAILY_TRADES_CHART_LOG, json.dumps(payload, sort_keys=True), "daily_trades_chart",
        source="cockpit", correlation_id=correlation_id,
    )

    return payload


def _probe_url_latency(label: str, url: str):
    start = time.perf_counter()
    req = Request(url, headers={"User-Agent": "McLeodControlCenter/1.0"})
    try:
        with urlopen(req, timeout=INTERNET_QUALITY_TIMEOUT_SECONDS, context=INTERNET_SSL_CONTEXT) as resp:
            status_code = getattr(resp, "status", None) or getattr(resp, "code", None) or 200
        latency_ms = round((time.perf_counter() - start) * 1000.0, 1)
        return {
            "label": label,
            "url": url,
            "ok": True,
            "status_code": int(status_code),
            "latency_ms": latency_ms,
            "error": None,
        }
    except HTTPError as e:
        latency_ms = round((time.perf_counter() - start) * 1000.0, 1)
        return {
            "label": label,
            "url": url,
            "ok": False,
            "status_code": int(getattr(e, "code", 0) or 0),
            "latency_ms": latency_ms,
            "error": f"HTTP {getattr(e, 'code', 'error')}",
        }
    except (URLError, TimeoutError, OSError) as e:
        latency_ms = round((time.perf_counter() - start) * 1000.0, 1)
        err_text = str(e)
        err_upper = err_text.upper()
        tls_cert_issue = (
            "CERTIFICATE_VERIFY_FAILED" in err_upper
            or "SELF-SIGNED CERTIFICATE" in err_upper
        )
        return {
            "label": label,
            "url": url,
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "error": err_text,
            "tls_cert_issue": tls_cert_issue,
        }


def _run_command_capture(args, timeout_seconds: float = 2.5):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return (result.returncode == 0), (result.stdout or "")
    except Exception:
        return False, ""


def _parse_hardware_ports():
    ok, out = _run_command_capture(["networksetup", "-listallhardwareports"], timeout_seconds=3.0)
    if not ok or not out.strip():
        return {}

    mapping = {}
    current_port = None
    for raw in out.splitlines():
        line = str(raw or "").strip()
        if line.startswith("Hardware Port:"):
            current_port = line.split(":", 1)[1].strip()
            continue
        if current_port and line.startswith("Device:"):
            device = line.split(":", 1)[1].strip()
            if device:
                mapping[device] = current_port
            current_port = None
    return mapping


def _looks_like_ethernet_port(port_name: str):
    lower = str(port_name or "").strip().lower()
    if not lower:
        return False
    ethernet_markers = (
        "ethernet",
        "lan",
        "usb 10/100",
        "usb 10/100/1000",
        "2.5gbase",
        "gigabit",
    )
    return any(marker in lower for marker in ethernet_markers)


def _looks_like_wifi_port(port_name: str):
    lower = str(port_name or "").strip().lower()
    return ("wi-fi" in lower) or ("wifi" in lower) or ("airport" in lower)


def _is_market_hours_now_et():
    now_et = datetime.now(EASTERN_TZ)
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def _latest_completed_nyse_close_date(now_et: Optional[datetime] = None) -> Optional[date]:
    now_et = now_et or datetime.now(EASTERN_TZ)
    candidate = now_et.date()

    if _is_nyse_trading_day(candidate):
        close_text = _nyse_regular_close_time_for_date(candidate)
        try:
            close_hour, close_minute, close_second = [int(x) for x in close_text.split(":")]
        except Exception:
            close_hour, close_minute, close_second = 16, 0, 0
        close_dt = datetime.combine(candidate, datetime.min.time(), tzinfo=EASTERN_TZ).replace(
            hour=close_hour,
            minute=close_minute,
            second=close_second,
            microsecond=0,
        )
        if now_et >= close_dt:
            return candidate

    probe = candidate - timedelta(days=1)
    for _ in range(10):
        if _is_nyse_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    return None


def _apply_spy_close_baseline(status: dict):
    try:
        spy_price = float(status.get("spy_price")) if status.get("spy_price") is not None else None
    except (TypeError, ValueError):
        spy_price = None
    try:
        close_price = float(_SPY_CLOSE_BASELINE_CACHE.get("close_price")) if _SPY_CLOSE_BASELINE_CACHE.get("close_price") is not None else None
    except (TypeError, ValueError):
        close_price = None

    if spy_price is None or close_price is None or close_price <= 0:
        return

    spy_change = spy_price - close_price
    spy_change_pct = (spy_change / close_price) * 100.0
    status["spy_change"] = round(spy_change, 2)
    status["spy_change_pct"] = round(spy_change_pct, 2)
    status["spy_close_reference"] = round(close_price, 2)
    status["spy_close_reference_date"] = _SPY_CLOSE_BASELINE_CACHE.get("trading_date")
    status["spy_close_reference_updated_at"] = _SPY_CLOSE_BASELINE_CACHE.get("updated_at")


def _validate_runtime_config():
    required_keys = (
        "SCHWAB_APP_KEY",
        "SCHWAB_APP_SECRET",
        "SCHWAB_CALLBACK_URL",
        "SCHWAB_ACCOUNT_NUMBER",
        "SCHWAB_ACCOUNT_HASH",
    )
    errors = []
    warnings = []

    for key in required_keys:
        if not str(os.getenv(key) or "").strip():
            errors.append(f"Missing required env var: {key}")

    def _check_float(name, min_value, max_value):
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return
        try:
            val = float(raw)
        except (TypeError, ValueError):
            errors.append(f"Invalid numeric env var {name}={raw}")
            return
        if val < min_value or val > max_value:
            warnings.append(f"Out-of-range {name}={val} (expected {min_value}..{max_value})")

    _check_float("SPY_QUOTE_REFRESH_SECONDS_OPEN", 1.0, 30.0)
    _check_float("SPY_QUOTE_REFRESH_SECONDS_CLOSED", 1.0, 120.0)
    _check_float("BROKER_PNL_REFRESH_SECONDS", 5.0, 300.0)
    _check_float("STATUS_SNAPSHOT_CACHE_SECONDS", 0.25, 15.0)

    # Guardrail: legacy monitor scripts should not live in active root.
    for legacy_name in ("phase1_monitor.py", "phase2_monitor.py"):
        if (PROJECT_ROOT / legacy_name).exists():
            warnings.append(
                f"Legacy monitor present in root: {legacy_name}. Archive it to prevent accidental launches."
            )

    _RUNTIME_CONFIG_CACHE["checked_at"] = datetime.now(timezone.utc).isoformat()
    _RUNTIME_CONFIG_CACHE["errors"] = errors
    _RUNTIME_CONFIG_CACHE["warnings"] = warnings
    return {
        "checked_at": _RUNTIME_CONFIG_CACHE["checked_at"],
        "errors": list(errors),
        "warnings": list(warnings),
        "ok": not errors,
    }


def _get_primary_network_status(force: bool = False):
    now = time.time()
    cached = _NETWORK_STATUS_CACHE.get("payload")
    if not force and cached and (now - float(_NETWORK_STATUS_CACHE.get("timestamp") or 0.0)) < NETWORK_STATUS_CACHE_SECONDS:
        return cached

    primary_interface = None
    ok_route, route_out = _run_command_capture(["route", "-n", "get", "default"]) 
    if ok_route:
        for raw in route_out.splitlines():
            line = str(raw or "").strip()
            if line.startswith("interface:"):
                primary_interface = line.split(":", 1)[1].strip() or None
                break

    port_map = _parse_hardware_ports()
    primary_port = port_map.get(primary_interface) if primary_interface else None
    on_ethernet = _looks_like_ethernet_port(primary_port)
    on_wifi = _looks_like_wifi_port(primary_port)

    wifi_power = None
    wifi_device = None
    wifi_port_name = None
    for device, port in port_map.items():
        if _looks_like_wifi_port(port):
            wifi_device = device
            wifi_port_name = port
            break

    if wifi_port_name:
        ok_wifi, wifi_out = _run_command_capture(["networksetup", "-getairportpower", wifi_port_name])
        if ok_wifi and wifi_out:
            text = wifi_out.strip().lower()
            if " on" in text or text.endswith(": on"):
                wifi_power = "ON"
            elif " off" in text or text.endswith(": off"):
                wifi_power = "OFF"

    if primary_interface and primary_port:
        summary = f"{primary_port} ({primary_interface})"
    elif primary_interface:
        summary = f"{primary_interface}"
    else:
        summary = "Unknown"

    payload = {
        "primary_interface": primary_interface,
        "primary_port": primary_port,
        "on_ethernet": bool(on_ethernet),
        "on_wifi": bool(on_wifi),
        "wifi_device": wifi_device,
        "wifi_power": wifi_power,
        "summary": summary,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    _NETWORK_STATUS_CACHE["timestamp"] = now
    _NETWORK_STATUS_CACHE["payload"] = payload
    return payload


def _append_internet_quality_sample(payload: dict):
    try:
        get_memory().append_report_line(
            INTERNET_QUALITY_HISTORY_FILE,
            json.dumps(payload, separators=(",", ":")),
            "internet_quality_history",
            source="cockpit",
        )
    except Exception:
        pass


def _load_recent_internet_quality_samples(max_samples: int = INTERNET_TREND_HISTORY_SAMPLES):
    if not INTERNET_QUALITY_HISTORY_FILE.exists():
        return []
    try:
        with INTERNET_QUALITY_HISTORY_FILE.open("r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except Exception:
        return []

    samples = []
    for raw in lines[-max_samples:]:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except Exception:
            continue
        if isinstance(item, dict):
            samples.append(item)

    return samples



def _summarize_internet_quality_history(samples):
    if not samples:
        return {
            "samples": 0,
            "successful_samples": 0,
            "trend": "INSUFFICIENT_DATA",
            "stability": "UNKNOWN",
            "recent_avg_latency_ms": None,
            "all_time_avg_latency_ms": None,
            "recent_best_latency_ms": None,
            "recent_worst_latency_ms": None,
            "latest_latency_ms": None,
            "window_minutes": None,
            "recent_points_ms": [],
            "recent_point_timestamps": [],
            "latest_checked_at": None,
            "day_avg_latency_ms": None,
            "day_best_latency_ms": None,
            "day_worst_latency_ms": None,
        }

    def _sample_latency(sample):
        try:
            value = sample.get("avg_latency_ms")
            return float(value) if value is not None else None
        except (TypeError, ValueError, AttributeError):
            return None

    def _sample_checked_at(sample):
        try:
            return str(sample.get("checked_at") or "").strip()
        except Exception:
            return ""

    def _parse_checked_at(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    successful = [s for s in samples if _sample_latency(s) is not None]
    records = [
        {
            "latency": _sample_latency(sample),
            "checked_at": _sample_checked_at(sample),
        }
        for sample in successful
    ]

    latencies = [record["latency"] for record in records if record.get("latency") is not None]
    latest_latency = latencies[-1] if latencies else None
    all_time_avg = round(sum(latencies) / len(latencies), 1) if latencies else None
    latest_checked_at = records[-1]["checked_at"] if records else ""

    recent = []
    latest_dt = _parse_checked_at(latest_checked_at)
    chart_records = []
    if latest_dt is not None:
        cutoff_dt = latest_dt - timedelta(minutes=30)
        for record in records:
            record_dt = _parse_checked_at(record.get("checked_at"))
            if record_dt is not None and record_dt >= cutoff_dt:
                recent.append(record["latency"])
                chart_records.append(record)
    if not recent:
        recent = latencies[-10:]
    if not chart_records:
        chart_records = records[-INTERNET_TREND_BAR_POINTS:]

    recent_avg = round(sum(recent) / len(recent), 1) if recent else None
    best = round(min(recent), 1) if recent else None
    worst = round(max(recent), 1) if recent else None
    recent_points = [round(float(record.get("latency") or 0.0), 1) for record in chart_records]
    recent_point_timestamps = [str(record.get("checked_at") or "") for record in chart_records]

    if recent_avg is None or all_time_avg is None:
        trend = "INSUFFICIENT_DATA"
    else:
        delta = recent_avg - all_time_avg
        if delta <= -40:
            trend = "IMPROVING"
        elif delta >= 40:
            trend = "WORSENING"
        else:
            trend = "STEADY"

    if len(recent) < 3:
        stability = "UNKNOWN"
    else:
        spread = max(recent) - min(recent)
        if spread <= 75:
            stability = "VERY_STEADY"
        elif spread <= 150:
            stability = "STEADY"
        elif spread <= 300:
            stability = "MIXED"
        else:
            stability = "CHOPPY"

    first_ts = str(chart_records[0].get("checked_at") or "").strip() if chart_records else ""
    last_ts = latest_checked_at
    window_minutes = None
    try:
        if first_ts and last_ts:
            start_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            window_minutes = round((end_dt - start_dt).total_seconds() / 60.0, 1)
    except Exception:
        window_minutes = None

    today_et = datetime.now(EASTERN_TZ).date()
    day_latencies = []
    for sample in successful:
        latency = _sample_latency(sample)
        if latency is None:
            continue
        ts = _sample_checked_at(sample)
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(EASTERN_TZ)
        except Exception:
            continue
        if dt.date() == today_et:
            day_latencies.append(float(latency))

    day_avg = round(sum(day_latencies) / len(day_latencies), 1) if day_latencies else None
    day_best = round(min(day_latencies), 1) if day_latencies else None
    day_worst = round(max(day_latencies), 1) if day_latencies else None

    return {
        "samples": len(samples),
        "successful_samples": len(successful),
        "trend": trend,
        "stability": stability,
        "recent_avg_latency_ms": recent_avg,
        "all_time_avg_latency_ms": all_time_avg,
        "recent_best_latency_ms": best,
        "recent_worst_latency_ms": worst,
        "latest_latency_ms": round(latest_latency, 1) if latest_latency is not None else None,
        "window_minutes": window_minutes,
        "recent_points_ms": recent_points,
        "recent_point_timestamps": recent_point_timestamps,
        "latest_checked_at": recent_point_timestamps[-1] if recent_point_timestamps else None,
        "day_avg_latency_ms": day_avg,
        "day_best_latency_ms": day_best,
        "day_worst_latency_ms": day_worst,
    }


def _internet_quality_from_rolling_average(avg_latency_ms):
    """Classify the Internet Trend title from its rolling 30-minute latency average."""
    if avg_latency_ms is None:
        return None, None
    if avg_latency_ms <= 250:
        return "EXCELLENT", f"Excellent ({avg_latency_ms:.0f} ms 30 min avg)"
    if avg_latency_ms <= 600:
        return "GOOD", f"Good ({avg_latency_ms:.0f} ms 30 min avg)"
    if avg_latency_ms <= 1000:
        return "FAIR", f"Fair ({avg_latency_ms:.0f} ms 30 min avg)"
    return "DEGRADED", f"Degraded ({avg_latency_ms:.0f} ms 30 min avg)"


def _get_internet_quality_snapshot(force: bool = False):
    now = time.time()
    cached = _INTERNET_QUALITY_CACHE.get("payload")
    if not force and cached and (now - float(_INTERNET_QUALITY_CACHE.get("timestamp") or 0.0)) < INTERNET_QUALITY_CACHE_SECONDS:
        return cached

    probes = []
    for target in INTERNET_QUALITY_TARGETS:
        if isinstance(target, dict):
            label = str(target.get("label") or "target")
            url = str(target.get("url") or "").strip()
        else:
            try:
                label, url = target
            except (TypeError, ValueError):
                continue
            label = str(label)
            url = str(url).strip()

        if not url:
            continue
        probes.append(_probe_url_latency(label, url))

    ok_probes = [p for p in probes if p.get("ok")]
    failed_probes = [p for p in probes if not p.get("ok")]
    tls_cert_issues = [p for p in failed_probes if p.get("tls_cert_issue")]
    tls_only_failures = bool(failed_probes) and len(tls_cert_issues) == len(failed_probes)
    latency_probes = ok_probes if ok_probes else tls_cert_issues
    avg_latency_ms = round(sum(p.get("latency_ms") or 0.0 for p in latency_probes) / len(latency_probes), 1) if latency_probes else None
    max_latency_ms = max((p.get("latency_ms") or 0.0 for p in latency_probes), default=None)

    if len(ok_probes) == len(probes) and avg_latency_ms is not None and avg_latency_ms <= 250:
        quality = "EXCELLENT"
        summary = f"Excellent ({avg_latency_ms:.0f} ms avg)"
    elif len(ok_probes) == len(probes) and avg_latency_ms is not None and avg_latency_ms <= 600:
        quality = "GOOD"
        summary = f"Good ({avg_latency_ms:.0f} ms avg)"
    elif ok_probes and not failed_probes:
        quality = "FAIR"
        summary = f"Fair ({avg_latency_ms:.0f} ms avg)"
    elif ok_probes:
        quality = "DEGRADED"
        summary = "Degraded"
    elif tls_only_failures:
        if avg_latency_ms is not None and avg_latency_ms <= 250:
            quality = "GOOD"
            summary = f"Good connectivity ({avg_latency_ms:.0f} ms avg, TLS validation issue)"
        elif avg_latency_ms is not None and avg_latency_ms <= 600:
            quality = "FAIR"
            summary = f"Fair connectivity ({avg_latency_ms:.0f} ms avg, TLS validation issue)"
        else:
            quality = "DEGRADED"
            summary = "Connectivity detected (TLS certificate validation failed)"
    else:
        quality = "DOWN"
        summary = "No internet response"

    payload = {
        "quality": quality,
        "summary": summary,
        "avg_latency_ms": avg_latency_ms,
        "max_latency_ms": round(max_latency_ms, 1) if max_latency_ms is not None else None,
        "ok_count": len(ok_probes),
        "target_count": len(probes),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "targets": probes,
    }
    _append_internet_quality_sample(payload)
    history = _summarize_internet_quality_history(_load_recent_internet_quality_samples())
    rolling_quality, rolling_summary = _internet_quality_from_rolling_average(
        history.get("recent_avg_latency_ms")
    )
    if rolling_quality is not None:
        payload["quality"] = rolling_quality
        payload["summary"] = rolling_summary
        payload["rolling_avg_latency_ms"] = history.get("recent_avg_latency_ms")
        payload["quality_window_minutes"] = history.get("window_minutes")
    _INTERNET_QUALITY_CACHE["timestamp"] = now
    _INTERNET_QUALITY_CACHE["payload"] = payload
    return payload


def _build_problem_messages(status: dict):
    problems = []

    if status.get("runtime_alert_active"):
        problems.append(str(status.get("runtime_alert_message") or "Runtime alert active").strip())

    if not status.get("bot_running"):
        problems.append("Bot is not running")
    elif status.get("heartbeat_ok") is False:
        age = status.get("heartbeat_age_seconds")
        if age is not None:
            problems.append(f"Bot heartbeat is stale ({age}s old)")
        else:
            problems.append("Bot heartbeat is stale")

    if status.get("mode") not in {None, "LIVE TRADING"}:
        problems.append(f"Mode is {status.get('mode')}")

    if status.get("broker_reconciliation") in {"FAILED", "SAFE MODE"}:
        problems.append(f"Broker reconciliation is {status.get('broker_reconciliation')}")

    if int(status.get("pending_orders") or 0) > 0:
        problems.append(f"{int(status.get('pending_orders') or 0)} pending order(s) still open")

    if not status.get("trade_log_schema_ok"):
        problems.append("Trade log schema is missing required fields")

    if not status.get("trade_log_email_armed"):
        problems.append("Daily trade-log email is not armed")

    if not status.get("broker_pnl_source_file"):
        problems.append("No Schwab history export found")

    if status.get("on_ethernet") is False:
        network_summary = str(status.get("network_summary") or "Wi-Fi").strip()
        problems.append(f"Primary network is not Ethernet: {network_summary}")

    preopen_status = str(status.get("preopen_dry_run_status") or "NOT_RUN").upper()
    if preopen_status == "FAILED":
        problems.append(f"Pre-open dry run failed: {status.get('preopen_dry_run_message') or 'unknown reason'}")

    internet = status.get("internet_quality") or {}
    internet_quality = str(internet.get("quality") or "UNKNOWN").upper()
    if internet_quality in {"DEGRADED", "DOWN"}:
        internet_problem = str(internet.get("summary") or internet_quality).strip()
        problems.append(f"Internet quality is {internet_problem}")

    last_error = str(status.get("last_error") or "").strip()
    if last_error:
        problems.append(last_error)

    seen = set()
    deduped = []
    for problem in problems:
        key = str(problem).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _load_runtime_alert_flag():
    if not RUNTIME_ALERT_FLAG_FILE.exists():
        return {}
    try:
        payload = json.loads(RUNTIME_ALERT_FLAG_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _python_version(python_path: Path):
    """Return interpreter version tuple, or (0, 0, 0) when unavailable."""
    try:
        result = subprocess.run(
            [str(python_path), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        version = result.stdout.strip()
        if not version:
            return (0, 0, 0)
        return tuple(int(x) for x in version.split("."))
    except Exception:
        return (0, 0, 0)


def _python_has_modules(python_path: Path, modules):
    """Check whether interpreter can import required modules."""
    import_line = "import " + ", ".join(modules)
    try:
        result = subprocess.run(
            [str(python_path), "-c", import_line],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _bot_python_mode() -> str:
    mode = os.getenv("BOT_PYTHON_MODE", "stable").strip().lower()
    return mode if mode in {"stable", "newest"} else "stable"


def find_newest_compatible_python():
    """Resolve newest available Python 3 that can run bot dependencies."""
    required_modules = ("pandas", "dotenv", "requests", "schwab")

    candidates = []
    patterns = [
        "/Library/Frameworks/Python.framework/Versions/*/bin/python3",
        "/opt/homebrew/bin/python3*",
        "/usr/local/bin/python3*",
        "/usr/bin/python3",
    ]

    for pattern in patterns:
        for item in sorted(Path("/").glob(pattern.lstrip("/"))):
            if item.is_file() and os.access(item, os.X_OK):
                candidates.append(item)

    # Prefer current interpreter and venv as deterministic fallbacks.
    candidates.extend([Path(sys.executable), VENV_PYTHON])

    deduped = []
    seen = set()
    for c in candidates:
        key = str(c.resolve()) if c.exists() else str(c)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    compatible = [c for c in deduped if c.exists() and os.access(c, os.X_OK) and _python_has_modules(c, required_modules)]
    if compatible:
        return max(compatible, key=_python_version)

    # Final fallback to any executable candidate.
    executable = [c for c in deduped if c.exists() and os.access(c, os.X_OK)]
    if executable:
        return max(executable, key=_python_version)

    return VENV_PYTHON


def resolve_bot_python():
    """Resolve bot interpreter according to BOT_PYTHON_MODE policy.

    Modes:
    - stable (default): requires project venv interpreter with bot deps
    - newest: uses newest available compatible Python
    """
    required_modules = ("pandas", "dotenv", "requests", "schwab")
    mode = _bot_python_mode()

    # Prefer the interpreter currently running Cockpit when it can run the bot.
    current_python = Path(sys.executable)
    if current_python.exists() and os.access(current_python, os.X_OK) and _python_has_modules(current_python, required_modules):
        return current_python

    if mode == "stable":
        if VENV_PYTHON.exists() and os.access(VENV_PYTHON, os.X_OK) and _python_has_modules(VENV_PYTHON, required_modules):
            return VENV_PYTHON
        # Auto-fallback so live bot can run when .venv is present but incompatible.
        return find_newest_compatible_python()

    return find_newest_compatible_python()


SELECTED_BOT_PYTHON = resolve_bot_python() or VENV_PYTHON

# Flask app
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# ============================================================================
# Process Management
# ============================================================================

def is_bot_running():
    """Check if bot appears to be running.

    Running means an actual live process exists on this machine.
    """
    return _is_bot_process_running()


def _is_bot_process_running():
    """True when a bot process exists locally (PID file or process scan)."""
    pid = get_bot_pid()
    if pid is not None:
        try:
            # Signal 0 checks process existence without sending a signal.
            os.kill(pid, 0)
            return True
        except OSError:
            pass

    fallback_pid = _find_running_bot_pid()
    if fallback_pid is not None:
        return True

    return False


def _find_running_bot_pid():
    """Find a live bot PID by scanning process command lines for BOT_SCRIPT."""
    try:
        output = subprocess.check_output(
            ["ps", "-ax", "-o", "pid=,command="],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None

    bot_script_str = str(BOT_SCRIPT)
    for raw in output.splitlines():
        line = str(raw or "").strip()
        if not line:
            continue

        parts = line.split(None, 1)
        if len(parts) != 2:
            continue

        pid_text, command = parts
        if bot_script_str not in command:
            continue

        try:
            return int(pid_text)
        except ValueError:
            continue

    return None


def _has_fresh_bot_heartbeat(max_age_seconds=None):
    """Treat recent bot log writes as an activity heartbeat fallback."""
    if max_age_seconds is None:
        max_age_seconds = max(HEARTBEAT_STALE_SECONDS, 180)

    active_log = _resolve_active_bot_log_file()
    if not active_log.exists():
        return False

    try:
        age = time.time() - active_log.stat().st_mtime
    except OSError:
        return False

    return age <= float(max_age_seconds)


def get_bot_pid():
    """Get current bot PID"""
    if BOT_PID_FILE.exists():
        try:
            with open(BOT_PID_FILE, 'r') as f:
                return int(f.read().strip())
        except ValueError:
            pass

    return _find_running_bot_pid()


def _runtime_repo_path_allows_start() -> tuple[bool, str, str]:
    current_repo = str(PROJECT_ROOT.resolve())
    expected_repo = str(CANONICAL_REPO_PATH)
    if not ENFORCE_CANONICAL_REPO_PATH:
        return True, current_repo, expected_repo
    allowed = PROJECT_ROOT.resolve() == CANONICAL_REPO_PATH
    return allowed, current_repo, expected_repo


def _git_dirty_summary() -> tuple[bool, list[str]]:
    """Return (is_dirty, sample_lines) from git porcelain status."""
    try:
        output = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False, []

    lines = [ln.strip() for ln in str(output or "").splitlines() if ln.strip()]
    return (len(lines) > 0), lines[:8]


def start_canonical_sync_and_restart():
    """Queue a detached GitHub sync, Cockpit restart, and bot restart."""
    repo_allowed, current_repo, expected_repo = _runtime_repo_path_allows_start()
    if not repo_allowed:
        return {"status": "error", "message": f"Start blocked in repo {current_repo}; canonical repo is {expected_repo}"}

    if not CANONICAL_DEPLOY_SCRIPT.is_file() or not os.access(CANONICAL_DEPLOY_SCRIPT, os.X_OK):
        return {"status": "error", "message": f"Canonical deploy script is unavailable: {CANONICAL_DEPLOY_SCRIPT}"}

    try:
        fetch_result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "fetch", "origin", "main"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if fetch_result.returncode != 0:
            return {"status": "error", "message": f"Start blocked: {(fetch_result.stderr or 'GitHub fetch failed').strip()}"}
        local_sha = subprocess.check_output(["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"], text=True).strip()
        remote_sha = subprocess.check_output(["git", "-C", str(PROJECT_ROOT), "rev-parse", "origin/main"], text=True).strip()
    except Exception as error:
        return {"status": "error", "message": f"Start blocked: unable to inspect GitHub state ({error})"}

    is_dirty, _ = _git_dirty_summary()
    if local_sha != remote_sha and is_dirty:
        return {"status": "error", "message": "Start blocked: GitHub has newer changes while this desktop has uncommitted work. Commit or reconcile the desktop changes first; nothing was overwritten."}

    try:
        existing_pid = int(CANONICAL_DEPLOY_PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(existing_pid, 0)
        return {"status": "success", "message": f"GitHub sync and restart already running (PID: {existing_pid})", "pid": existing_pid}
    except (FileNotFoundError, ProcessLookupError, ValueError):
        CANONICAL_DEPLOY_PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        return {"status": "error", "message": "Unable to verify active GitHub sync process"}

    try:
        env = os.environ.copy()
        env["COCKPIT_PUBLIC_URL"] = COCKPIT_PUBLIC_URL
        env["PYTHONUNBUFFERED"] = "1"
        with get_memory().open_runtime_log(CANONICAL_DEPLOY_LOG_FILE, mode="a") as log_fp:
            process = subprocess.Popen(
                [str(CANONICAL_DEPLOY_SCRIPT)], cwd=str(PROJECT_ROOT), stdout=log_fp,
                stderr=subprocess.STDOUT, env=env, start_new_session=True,
            )
        get_memory().write_runtime_artifact(
            CANONICAL_DEPLOY_PID_FILE, process.pid, "canonical_deploy_pid"
        )
        return {"status": "success", "message": "GitHub sync, Cockpit restart, and bot restart started", "pid": process.pid}
    except Exception as error:
        return {"status": "error", "message": f"Failed to start GitHub sync: {error}"}


def start_bot():
    """Start the trading bot"""
    global _RUNNING_BOT_SCRIPT_SHA256

    repo_allowed, current_repo, expected_repo = _runtime_repo_path_allows_start()
    if not repo_allowed:
        return {
            "status": "error",
            "message": f"Bot start blocked in repo {current_repo}; canonical repo is {expected_repo}",
        }

    if BOT_SCRIPT.name != EXPECTED_BOT_SCRIPT_NAME:
        return {
            "status": "error",
            "message": f"Refusing to start: BOT_SCRIPT must be {EXPECTED_BOT_SCRIPT_NAME}, got {BOT_SCRIPT.name}",
        }

    if _is_bot_process_running():
        return {"status": "error", "message": "Bot is already running"}

    if ENFORCE_RUNTIME_CONFIG_ON_START:
        cfg = _validate_runtime_config()
        cfg_errors = list(cfg.get("errors") or [])
        if cfg_errors:
            joined = "; ".join(cfg_errors[:6])
            return {
                "status": "error",
                "message": f"Start blocked by runtime config preflight: {joined}",
                "config_errors": cfg_errors,
            }

    if ENFORCE_CLEAN_GIT_ON_START:
        is_dirty, dirty_sample = _git_dirty_summary()
        if is_dirty:
            return {
                "status": "error",
                "message": "Start blocked: repository has uncommitted changes (enable override with ENFORCE_CLEAN_GIT_ON_START=0)",
                "git_dirty_sample": dirty_sample,
            }

    parity_guard = _parity_start_guard_payload()
    if parity_guard is not None:
        return parity_guard
    
    try:
        selected_python = resolve_bot_python()
        if selected_python is None:
            return {
                "status": "error",
                "message": "BOT_PYTHON_MODE=stable but venv python/dependencies are unavailable. Repair venv or set BOT_PYTHON_MODE=newest for test mode."
            }

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        # Clear stale/manual stop marker before launching a new monitor.
        try:
            get_memory().clear_setting("bot_manual_stop_marker", BOT_MANUAL_STOP_MARKER_FILE)
        except Exception:
            pass

        # Start bot in background, capturing output
        with get_memory().open_runtime_log(BOT_LOG_FILE, mode="w") as log_fp:
            process = subprocess.Popen(
                [str(selected_python), "-u", str(BOT_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                env=env,
                preexec_fn=os.setsid  # Create new process group for clean shutdown
            )
        
        # Save PID
        get_memory().write_runtime_artifact(BOT_PID_FILE, process.pid, "bot_pid")

        _save_bot_stop_alert_state({
            "last_bot_running": True,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_bot_pid": process.pid,
            "last_running_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Give it a moment to start
        time.sleep(1)
        
        if is_bot_running():
            _RUNNING_BOT_SCRIPT_SHA256 = _sha256_file(BOT_SCRIPT) if BOT_SCRIPT.exists() else _RUNNING_BOT_SCRIPT_SHA256
            return {
                "status": "success",
                "message": f"Bot started successfully (PID: {process.pid}) with Python {selected_python}",
                "pid": process.pid
            }
        else:
            return {
                "status": "error",
                "message": "Bot process exited immediately - check logs"
            }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to start bot: {str(e)}"
        }


def stop_bot():
    """Stop the trading bot immediately and tolerate stale PID state."""
    # Persist the operator's intent before inspecting process state so the
    # watchdog cannot revive a bot that exited during the stop request.
    try:
        get_memory().save_setting(
            "bot_manual_stop_marker",
            {
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "source": "cockpit",
            },
            BOT_MANUAL_STOP_MARKER_FILE,
        )
    except Exception:
        pass

    pid = get_bot_pid()
    if not pid or not _is_bot_process_running():
        BOT_PID_FILE.unlink(missing_ok=True)
        return {"status": "success", "message": "Bot already stopped"}

    try:
        pre_stop_status = parse_bot_status()
    except Exception:
        pre_stop_status = {"bot_running": True, "mode": "UNKNOWN", "last_error": None}
    
    try:
        # Immediate shutdown path: SIGTERM first, then fast SIGKILL fallback.
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            BOT_PID_FILE.unlink(missing_ok=True)
            return {
                "status": "success",
                "message": "Bot already stopped (stale PID cleaned)"
            }

        for _ in range(5):
            if not _is_bot_process_running():
                BOT_PID_FILE.unlink(missing_ok=True)
                return {
                    "status": "success",
                    "message": "Bot stopped"
                }
            time.sleep(0.1)

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

        BOT_PID_FILE.unlink(missing_ok=True)
        stop_status = dict(pre_stop_status)
        stop_status["bot_running"] = False
        stop_status["bot_running_effective"] = False
        _maybe_notify_bot_stop(stop_status, reason=f"Manual stop requested from Cockpit (PID {pid})", force=True)
        return {
            "status": "success",
            "message": "Bot stopped immediately"
        }
    
    except Exception as e:
        BOT_PID_FILE.unlink(missing_ok=True)
        return {"status": "success", "message": f"Bot stop cleanup completed ({str(e)})"}


def trigger_go_live() -> dict:
    """Launch the canonical go-live sync/restart workflow in the background."""
    repo_allowed, current_repo, expected_repo = _runtime_repo_path_allows_start()
    if not repo_allowed:
        return {
            "status": "error",
            "message": f"Go-live blocked in repo {current_repo}; canonical repo is {expected_repo}",
        }

    if not GO_LIVE_SCRIPT.exists():
        return {
            "status": "error",
            "message": f"Go-live script missing: {GO_LIVE_SCRIPT}",
        }

    try:
        # Start Bot is an explicit operator override of the persistent Stop Bot
        # intent, so let the canonical stack launch the monitor again.
        get_memory().clear_setting("bot_manual_stop_marker", BOT_MANUAL_STOP_MARKER_FILE)
        env = os.environ.copy()
        env.setdefault("MCLEOD_ROOT", str(PROJECT_ROOT))
        try:
            bot_is_running = bool(parse_bot_status().get("bot_running"))
        except Exception:
            bot_is_running = True
        if not bot_is_running:
            env["MCLEOD_ALLOW_MARKET_HOURS_CHANGES"] = "1"
        with get_memory().open_runtime_log(GO_LIVE_LOG_FILE, mode="a") as log_fp:
            log_fp.write(
                f"\n===== go-live requested {datetime.now(timezone.utc).isoformat()} from cockpit =====\n"
            )
            subprocess.Popen(
                [str(GO_LIVE_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                env=env,
                preexec_fn=os.setsid,
            )
        return {
            "status": "success",
            "message": "Go-live started. Syncing latest runtime, restarting Cockpit, then restarting bot.",
            "canonical_url": COCKPIT_PUBLIC_URL,
            "log_file": str(GO_LIVE_LOG_FILE),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to launch go-live: {e}",
        }


def queue_exit_trade_command():
    """Queue a manual exit command for the running monitor process."""
    command = {
        "id": int(time.time() * 1000),
        "action": "EXIT_TRADE",
        "status": "PENDING",
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "source": "COCKPIT",
    }

    get_memory().save_setting("control_command", command, CONTROL_COMMAND_FILE)
    return command


def toggle_entry_pause_command():
    """Toggle entry admission while the monitor continues processing candles."""
    current = get_memory().load_setting(ENTRY_PAUSE_FILE, {}) or {}
    paused = not bool(current.get("paused"))
    payload = {
        "paused": paused,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "COCKPIT",
    }
    get_memory().save_setting("entry_pause", payload, ENTRY_PAUSE_FILE)
    return payload


# ============================================================================
# Status Monitoring
# ============================================================================

def _compute_candle_indicator_snapshot(now_et=None, history_path=None):
    """Read only completed candles and delegate scoring to the strategy monitor."""
    history_path = Path(history_path or PROJECT_ROOT / "data" / "spy_1min_history.csv")
    if not history_path.exists():
        return None

    try:
        import pandas as pd
        from phase3_monitor import score_closed_candle_frame

        candles = pd.read_csv(history_path)
        candles["datetime"] = pd.to_datetime(candles["datetime"], utc=True)
        current_et = now_et or datetime.now(EASTERN_TZ)
        current_minute = current_et.astimezone(timezone.utc).replace(second=0, microsecond=0)
        candles = candles[candles["datetime"] < current_minute]
    except Exception:
        return None

    if len(candles) < 2:
        return None

    score = score_closed_candle_frame(candles)
    latest_ts = candles.iloc[-1]["datetime"].astimezone(EASTERN_TZ).isoformat()
    return {
        "call_passed": max(0, int(score["call_score"])),
        "put_passed": max(0, int(score["put_score"])),
        "total": 5,
        "timestamp": latest_ts,
        "regime": score["regime"],
        "market_trend": score.get("market_trend") or "UNKNOWN",
        "call_momentum": score.get("call_momentum") or {},
        "put_momentum": score.get("put_momentum") or {},
        "spy_run": score.get("spy_run") or {},
    }


def parse_bot_status():
    """Build the current runtime status through the dedicated status service."""
    from engine.runtime_status import parse_bot_status as build_runtime_status

    return build_runtime_status(globals())


def _load_latest_schwab_transaction_export():
    search_roots = [
        PROJECT_ROOT / "data",
        Path.home() / "Downloads",
        Path.home() / "Library" / "CloudStorage" / "Dropbox",
    ]
    patterns = [
        "Guaranteed_Future_XXX903_Transactions_*.json",
        "*_Transactions_*.json",
        "Guaranteed_Future_XXX903_Transactions_*.csv",
        "*_Transactions_*.csv",
    ]

    candidates = []
    for root in search_roots:
        if not root.exists():
            continue
        for pattern in patterns:
            candidates.extend(root.glob(pattern))

    candidates = [p for p in candidates if p.is_file() and p.stat().st_size > 0]
    if not candidates:
        return None, None

    def _load_payload(path):
        suffix = path.suffix.lower()
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            payload.setdefault("SourceType", "JSON")
            return payload
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as fh:
                rows = list(csv.DictReader(fh))

            max_date = None
            min_date = None
            for row in rows:
                try:
                    d = datetime.strptime(str((row or {}).get("Date") or ""), "%m/%d/%Y").date()
                except Exception:
                    continue
                if max_date is None or d > max_date:
                    max_date = d
                if min_date is None or d < min_date:
                    min_date = d

            return {
                "BrokerageTransactions": rows,
                "ToDate": max_date.strftime("%m/%d/%Y") if max_date else None,
                "FromDate": min_date.strftime("%m/%d/%Y") if min_date else None,
                "SourceType": "CSV",
            }
        return None

    ranked = []
    for candidate in candidates:
        try:
            payload = _load_payload(candidate)
        except Exception:
            continue
        if not payload:
            continue

        try:
            to_date = datetime.strptime(str(payload.get("ToDate") or ""), "%m/%d/%Y").date()
        except Exception:
            to_date = datetime.min.date()
        try:
            from_date = datetime.strptime(str(payload.get("FromDate") or ""), "%m/%d/%Y").date()
        except Exception:
            from_date = datetime.max.date()

        source_type = str(payload.get("SourceType") or "").upper()
        source_rank = 1 if source_type == "CSV" else 0
        row_count = len(payload.get("BrokerageTransactions") or [])
        ranked.append((to_date, -from_date.toordinal(), source_rank, row_count, candidate.stat().st_mtime, candidate, payload))

    if not ranked:
        return None, None

    _, _, _, _, _, best_path, best_payload = max(ranked)
    return best_path, best_payload


def _period_pnl_from_export_payload(payload, today_date):
    """Return Today/WTD/MTD/YTD totals from Schwab export payload when available."""
    if not payload or not today_date:
        return None

    rows = payload.get("BrokerageTransactions") or []
    if not rows:
        return None

    month_start = today_date.replace(day=1)
    week_start, week_end = _monday_to_sunday_week_bounds(today_date)
    year_start = today_date.replace(month=1, day=1)
    max_row_date = None
    today_total = 0.0
    wtd_total = 0.0
    mtd_total = 0.0
    ytd_total = 0.0
    min_row_date = None

    for row in rows:
        try:
            row_date = datetime.strptime(str((row or {}).get("Date") or ""), "%m/%d/%Y").date()
        except Exception:
            continue

        if min_row_date is None or row_date < min_row_date:
            min_row_date = row_date
        if max_row_date is None or row_date > max_row_date:
            max_row_date = row_date

        if row_date > today_date or row_date < year_start:
            continue

        amount = _parse_money_text((row or {}).get("Amount"))
        ytd_total += amount
        if week_start <= row_date <= week_end:
            wtd_total += amount
        if row_date >= month_start:
            mtd_total += amount
        if row_date == today_date:
            today_total += amount

    if min_row_date is None:
        return None

    return {
        "today": round(today_total, 2),
        "wtd": round(wtd_total, 2),
        "mtd": round(mtd_total, 2),
        "ytd": round(ytd_total, 2),
        # Treat as YTD export when it includes current-year rows before this month.
        "covers_ytd": (min_row_date.year == today_date.year) and (min_row_date < month_start) and (max_row_date is not None and max_row_date <= today_date),
    }


def _load_json_file(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _derive_daily_learning_lessons(summary: dict) -> list[dict]:
    lessons = []
    overall = (summary or {}).get("overall") or {}
    broker = (summary or {}).get("broker_backed") or {}
    by_exit = (summary or {}).get("by_exit_reason") or {}

    broker_trades = int(broker.get("trades") or 0)
    broker_pnl = float(broker.get("pnl") or 0.0)
    overall_trades = int(overall.get("trades") or 0)
    overall_win_rate = float(overall.get("win_rate") or 0.0)

    if broker_trades > 0 and broker_pnl < 0:
        lessons.append({
            "priority": "high",
            "title": "Broker-backed day finished negative",
            "signal": f"broker_pnl={broker_pnl:.2f} on {broker_trades} trades",
            "action": "Tighten early-session entry selectivity and review first-loss pattern.",
        })

    worst_exit = None
    for reason, stats in by_exit.items():
        pnl = float((stats or {}).get("pnl") or 0.0)
        trades = int((stats or {}).get("trades") or 0)
        if trades <= 0:
            continue
        if worst_exit is None or pnl < worst_exit[1]:
            worst_exit = (str(reason), pnl, trades)

    if worst_exit is not None and worst_exit[1] < 0:
        lessons.append({
            "priority": "medium",
            "title": "Largest drag concentrated in one exit reason",
            "signal": f"{worst_exit[0]} pnl={worst_exit[1]:.2f} ({worst_exit[2]} trades)",
            "action": "Replay this exit bucket first and tighten invalidation/stop handling.",
        })

    if overall_trades >= 4 and overall_win_rate < 0.45:
        lessons.append({
            "priority": "medium",
            "title": "Win rate below target band",
            "signal": f"win_rate={overall_win_rate:.1%} on {overall_trades} trades",
            "action": "Require cleaner momentum alignment before new entries.",
        })

    if not lessons:
        lessons.append({
            "priority": "low",
            "title": "No major red flags detected",
            "signal": "Daily profile appears stable",
            "action": "Keep risk process unchanged and continue monitoring drift.",
        })

    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(lessons, key=lambda x: priority_order.get(str(x.get("priority", "low")), 3))


def _daily_learning_insights_payload(force_refresh: bool = False):
    now_ts = time.time()
    cached = _DAILY_LEARNING_INSIGHTS_CACHE.get("payload")
    cached_ts = float(_DAILY_LEARNING_INSIGHTS_CACHE.get("timestamp") or 0.0)
    if not force_refresh and cached is not None and (now_ts - cached_ts) < max(5.0, DAILY_LEARNING_CACHE_SECONDS):
        return cached

    payload = {
        "available": False,
        "trading_date": None,
        "generated_at": None,
        "summary": {},
        "actionable_lessons": [],
        "source_file": str(DAILY_TRADE_LEARNING_LATEST_FILE),
    }

    raw = _load_json_file(DAILY_TRADE_LEARNING_LATEST_FILE)
    if isinstance(raw, dict):
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
        lessons = raw.get("actionable_lessons")
        if not isinstance(lessons, list) or not lessons:
            lessons = _derive_daily_learning_lessons(summary)

        payload = {
            "available": True,
            "trading_date": raw.get("trading_date"),
            "generated_at": raw.get("generated_at"),
            "summary": summary,
            "actionable_lessons": lessons[:3],
            "source_file": str(DAILY_TRADE_LEARNING_LATEST_FILE),
        }

    _DAILY_LEARNING_INSIGHTS_CACHE["timestamp"] = now_ts
    _DAILY_LEARNING_INSIGHTS_CACHE["payload"] = payload
    return payload


def _parse_money_text(value):
    text = str(value or "0").strip().replace("$", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    if text.startswith("-"):
        return -float(text[1:] or "0")
    return float(text or "0")


def _parse_timestamp_to_epoch(value):
    """Parse common ISO-like timestamps to epoch seconds; returns None on failure."""
    text = str(value or "").strip()
    if not text:
        return None

    # Normalize trailing Z and offsets like +0000 for datetime.fromisoformat.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and (text[-5] in "+-") and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]

    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None

    if dt.tzinfo is None:
        # Treat naive timestamps as local machine time for ordering against export mtime.
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo or timezone.utc)

    return dt.timestamp()


def _looks_like_real_spy_option_trade(trade):
    """Heuristic: keep probable real SPY option rows if they happened after last export snapshot."""
    try:
        symbol = str(trade.get("option_symbol") or "")
        direction = str(trade.get("direction") or "").upper()
        qty = int(float(trade.get("option_quantity") or 0))
        entry = float(trade.get("entry_price") or 0)
        exit_price = float(trade.get("exit_price") or 0)
    except (TypeError, ValueError):
        return False

    # Schwab OCC option symbols look like: SPY   260724C00755000
    match = re.match(r"^SPY\s+(\d{6})([CP])(\d{8})$", symbol)
    if not match:
        return False

    contract_side = match.group(2)
    if direction == "CALL" and contract_side != "C":
        return False
    if direction == "PUT" and contract_side != "P":
        return False

    if qty <= 0:
        return False
    if entry <= 0 or exit_price <= 0:
        return False
    return True


def _is_placeholder_option_symbol(symbol):
    """Identify synthetic/legacy symbols that should not count as canonical executed trades."""
    text = str(symbol or "").strip().upper()
    if not text:
        return False

    if text in {"SPY_CALL", "SPY_PUT", "SPY CALL", "SPY PUT", "SPY"}:
        return True

    # Legacy shorthand format seen in historical synthetic rows, e.g. "SPY 07-13-26 P450".
    if re.match(r"^SPY\s+\d{2}-\d{2}-\d{2}\s+[CP]\d+$", text):
        return True

    return False


def _filter_placeholder_trade_rows(trades):
    """Drop obvious placeholder/synthetic rows from trade payloads."""
    filtered = []
    for trade in trades or []:
        symbol = trade.get("option_symbol")
        if _is_placeholder_option_symbol(symbol):
            continue
        filtered.append(trade)
    return filtered


def _looks_like_short_test_order_id(order_id):
    """Detect obviously synthetic order IDs (e.g., 111, 999) from tests."""
    text = str(order_id or "").strip()
    if not text:
        return False
    return text.isdigit() and len(text) < 8


def _is_synthetic_test_trade_row(trade):
    """Identify rows likely written by local/unit tests, not real broker executions."""
    payload_text = str((trade or {}).get("feature_payload") or "").strip().lower()
    if payload_text in {"test", "pytest", "unit-test", "unit_test"}:
        return True

    entry_id = (trade or {}).get("broker_entry_order_id")
    exit_id = (trade or {}).get("broker_exit_order_id")
    if _looks_like_short_test_order_id(entry_id) or _looks_like_short_test_order_id(exit_id):
        return True

    option_symbol = str((trade or {}).get("option_symbol") or "").strip()
    direction = str((trade or {}).get("direction") or "").strip().upper()
    if not option_symbol and not entry_id and not exit_id and direction in {"CALL", "PUT"}:
        return True

    return False


def _filter_synthetic_test_trade_rows(trades):
    """Drop rows that match local synthetic test signatures."""
    return [t for t in (trades or []) if not _is_synthetic_test_trade_row(t)]


def _indicator_labels_from_trade(trade):
    payload = {}
    for field in ("entry_diagnostic_snapshot", "feature_payload"):
        raw = str((trade or {}).get(field) or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break

    direction = str(trade.get("direction") or "").strip().lower()
    labels = []
    for key in ("entry_reasons", f"entry_reasons_{direction}", "positive_signals", "penalties"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            label = str(value or "").strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def _indicator_performance_summary(trades, minimum_sample_size=10):
    grouped = {}
    for trade in _filter_synthetic_test_trade_rows(trades):
        if not trade.get("exit_time"):
            continue
        try:
            pnl = float(trade.get("option_pnl_dollars") if trade.get("option_pnl_dollars") is not None else trade.get("pnl") or 0.0)
        except (TypeError, ValueError):
            continue
        for label in _indicator_labels_from_trade(trade):
            bucket = grouped.setdefault(label, {"indicator": label, "trades": 0, "wins": 0, "losses": 0, "breakeven": 0, "return_total": 0.0})
            bucket["trades"] += 1
            bucket["return_total"] += pnl
            if pnl > 0:
                bucket["wins"] += 1
            elif pnl < 0:
                bucket["losses"] += 1
            else:
                bucket["breakeven"] += 1

    rows = []
    for bucket in grouped.values():
        trades_count = bucket["trades"]
        win_rate = round((bucket["wins"] / trades_count) * 100.0, 1) if trades_count else 0.0
        average_return = round(bucket["return_total"] / trades_count, 2) if trades_count else 0.0
        if trades_count < minimum_sample_size:
            guidance = "Collect more data"
        elif win_rate >= 55.0 and average_return > 0:
            guidance = "Candidate to increase weight"
        elif win_rate <= 45.0 and average_return < 0:
            guidance = "Review for reduction"
        else:
            guidance = "Keep monitoring"
        rows.append({"indicator": bucket["indicator"], "trades": trades_count, "wins": bucket["wins"], "losses": bucket["losses"], "breakeven": bucket["breakeven"], "win_rate_pct": win_rate, "average_return": average_return, "guidance": guidance})
    return sorted(
        rows,
        key=lambda row: (-row["win_rate_pct"], -row["trades"], -row["average_return"], row["indicator"].lower()),
    )


def _broker_verified_trade_signatures(trading_date: str):
    _, payload = _load_latest_schwab_transaction_export()
    if not payload:
        return None

    try:
        export_date = datetime.strptime(str(payload.get("ToDate")), "%m/%d/%Y").date().isoformat()
    except Exception:
        return None

    if export_date != trading_date:
        return None

    accepted_actions = {"Buy to Open", "Buy to Close", "Sell to Open", "Sell to Close"}
    grouped = {}

    for row in payload.get("BrokerageTransactions") or []:
        action = str((row or {}).get("Action") or "")
        symbol = str((row or {}).get("Symbol") or "")
        row_date = str((row or {}).get("Date") or "")
        if action not in accepted_actions:
            continue
        if not symbol.startswith("SPY "):
            continue
        try:
            iso_date = datetime.strptime(row_date, "%m/%d/%Y").date().isoformat()
        except Exception:
            continue
        if iso_date != trading_date:
            continue

        price = round(_parse_money_text((row or {}).get("Price")), 2)
        qty = int(float((row or {}).get("Quantity") or 0))
        grouped.setdefault(symbol, {"buy": [], "sell": []})
        if action.startswith("Buy"):
            grouped[symbol]["buy"].append((price, qty))
        else:
            grouped[symbol]["sell"].append((price, qty))

    signatures = set()
    for symbol, sides in grouped.items():
        buys = sides["buy"]
        sells = sides["sell"]
        used_sells = [False] * len(sells)
        for buy_price, buy_qty in buys:
            for index, (sell_price, sell_qty) in enumerate(sells):
                if used_sells[index]:
                    continue
                if buy_qty != sell_qty:
                    continue
                used_sells[index] = True
                signatures.add((symbol, round(buy_price, 2), round(sell_price, 2), int(buy_qty)))
                break
    return signatures


def _parse_iso_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and (text[-5] in "+-") and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None

    if dt.tzinfo is None:
        # Most locally persisted trade timestamps in this repo are ET wall-clock values.
        dt = dt.replace(tzinfo=EASTERN_TZ)
    return dt


def _to_et_iso(value):
    dt = _parse_iso_datetime(value)
    if dt is None:
        return value
    return dt.astimezone(EASTERN_TZ).isoformat()


def _realized_spy_option_pnl_for_date(trading_date: str):
    """Return realized SPY option P&L for a date using paired broker transactions."""
    if not trading_date:
        return None

    now_ts = time.time()
    cache_date = _BROKER_REALIZED_DAY_CACHE.get("date")
    cache_ts = float(_BROKER_REALIZED_DAY_CACHE.get("timestamp") or 0.0)
    if cache_date == trading_date and (now_ts - cache_ts) <= max(5.0, float(MTD_PNL_CACHE_SECONDS or 60)):
        return _BROKER_REALIZED_DAY_CACHE.get("pnl")

    try:
        trades = _broker_transaction_trades_for_date(trading_date)
        realized = round(sum(float(t.get("pnl") or 0.0) for t in trades), 2) if trades else None
    except Exception:
        realized = None

    _BROKER_REALIZED_DAY_CACHE["timestamp"] = now_ts
    _BROKER_REALIZED_DAY_CACHE["date"] = trading_date
    _BROKER_REALIZED_DAY_CACHE["pnl"] = realized
    return realized


def _realized_spy_option_pnl_for_period(start_date: str, end_date: str):
    """Return realized SPY option P&L for an inclusive date range from trade_log exits."""
    if not start_date or not end_date:
        return None

    db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
    if not db_path.exists():
        return None

    con = None
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(
            """
                        SELECT ROUND(SUM(
                                COALESCE(option_pnl_dollars, pnl, 0)
                                - ABS(COALESCE(option_quantity, 0)) * ?
                        ), 2) AS realized
            FROM trade_log
            WHERE exit_time IS NOT NULL
              AND substr(exit_time, 1, 10) >= ?
              AND substr(exit_time, 1, 10) <= ?
            """,
                        (
                                (OPTION_COMMISSION_PER_CONTRACT_SIDE * 2) + OPTION_REGULATORY_FEE_PER_CONTRACT_CLOSE,
                                str(start_date),
                                str(end_date),
                        ),
        )
        row = cur.fetchone()
        value = row["realized"] if row else None
        if value is None:
            return 0.0
        return round(float(value), 2)
    except Exception:
        return None
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def _fallback_scores_from_recent_logs(entry_time_value, direction):
    """Best-effort score recovery from recent decision logs for unlogged broker rows."""
    active_log = _resolve_active_bot_log_file()
    if not active_log.exists():
        return {}

    entry_dt = _parse_iso_datetime(entry_time_value)
    if entry_dt is None:
        return {}

    try:
        lines = active_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-4000:]
    except Exception:
        return {}

    blocks = []
    current_block = None
    current_section = None

    for raw in lines:
        line = str(raw or "").strip()

        if line.startswith("CYCLE ") and "evaluation_time=" in line:
            m_time = re.search(r"evaluation_time=([^|\s]+)", line)
            eval_dt = _parse_iso_datetime(m_time.group(1)) if m_time else None
            if eval_dt is not None:
                current_block = {"evaluation_time": eval_dt, "CALL": {}, "PUT": {}}
                blocks.append(current_block)
                current_section = None
            continue

        if current_block is None:
            continue

        upper_line = line.upper()
        if "CALL" in upper_line and "════" in line:
            current_section = "CALL"
            continue
        if "PUT" in upper_line and "════" in line:
            current_section = "PUT"
            continue

        if current_section not in {"CALL", "PUT"}:
            continue

        m_stage = re.search(r"Trend Stage:\s*(\d+)", line)
        if m_stage:
            current_block[current_section]["trend_stage"] = int(m_stage.group(1))
            continue

        m_cq = re.search(r"Continuation Quality:\s*([0-9]+(?:\.[0-9]+)?)", line)
        if m_cq:
            current_block[current_section]["continuation_quality_score"] = float(m_cq.group(1))
            continue

        m_mas = re.search(r"Momentum Acceleration:\s*([0-9]+(?:\.[0-9]+)?)", line)
        if m_mas:
            current_block[current_section]["momentum_acceleration_score"] = float(m_mas.group(1))
            continue

        m_conf = re.search(r"Confidence:\s*([0-9]+(?:\.[0-9]+)?)", line)
        if m_conf:
            current_block[current_section]["confidence_score"] = float(m_conf.group(1))
            continue

        m_entry_score = re.search(r"Score:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*[0-9]+(?:\.[0-9]+)?", line)
        if m_entry_score:
            current_block[current_section]["entry_gate_score"] = float(m_entry_score.group(1))
            continue

        m_ind = re.search(r"Indicators\s*Passed:\s*(\d+)\s*/\s*(\d+)", line, re.IGNORECASE)
        if m_ind:
            current_block[current_section]["indicator_count"] = int(m_ind.group(1))
            current_block[current_section]["indicator_total"] = int(m_ind.group(2))
            continue

    if not blocks:
        return {}

    direction_key = "CALL" if str(direction or "").upper() == "CALL" else "PUT"
    candidates = [b for b in blocks if b.get("evaluation_time") and b.get("evaluation_time") <= entry_dt]
    chosen = candidates[-1] if candidates else blocks[-1]
    return chosen.get(direction_key) or {}


def _fallback_scores_from_calibration(entry_time_value, direction):
    """Recover Stage/CQ/MAS/CONF from persisted calibration history by nearest prior timestamp."""
    if not CONTINUATION_CALIBRATION_FILE.exists():
        return {}

    entry_dt = _parse_iso_datetime(entry_time_value)
    if entry_dt is None:
        return {}

    direction_key = "call" if str(direction or "").upper() == "CALL" else "put"
    chosen = None

    try:
        lines = CONTINUATION_CALIBRATION_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-5000:]
    except Exception:
        return {}

    for raw_line in lines:
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except Exception:
            continue

        ts = _parse_iso_datetime(row.get("timestamp"))
        if ts is None:
            continue
        if ts > entry_dt:
            continue
        chosen = row

    if not chosen:
        return {}

    trend_stage = int(chosen.get(f"{direction_key}_trend_stage") or 0) or None
    # Calibration rows store call_score/put_score as continuation-quality score,
    # not the discrete entry gate score. Do not treat them as checklist values.
    entry_gate_score = None
    continuation_quality_score = float(chosen.get(f"{direction_key}_continuation_quality_score") or 0) or None
    momentum_acceleration_score = float(chosen.get(f"{direction_key}_momentum_acceleration_score") or 0) or None
    confidence_score = float(chosen.get(f"{direction_key}_confidence_score") or 0) or None
    indicator_count = int(chosen.get(f"continuation_indicators_{direction_key}_passed") or 0) or None
    indicator_total = int(chosen.get("continuation_indicators_total") or 0) or None

    if continuation_quality_score is None:
        continuation_quality_score = float(chosen.get(f"{direction_key}_score") or 0) or None

    components = chosen.get(f"{direction_key}_components") or {}
    if momentum_acceleration_score is None:
        mas_component = ((components.get("macd_histogram_expansion") or {}).get("score"))
        try:
            momentum_acceleration_score = round(float(mas_component) * 5.0, 2)
        except (TypeError, ValueError):
            momentum_acceleration_score = None

    if confidence_score is None:
        conf_component = ((components.get("primary_indicators") or {}).get("score"))
        try:
            confidence_score = round(float(conf_component) * 5.0, 2)
        except (TypeError, ValueError):
            confidence_score = None

    if trend_stage is None:
        phase = str(((components.get("trend_age") or {}).get("phase") or "")).upper()
        trend_stage = {"EARLY": 2, "MID": 3, "LATE": 4}.get(phase)

    if indicator_count is None or indicator_total is None:
        primary = (components.get("primary_indicators") or {})
        if isinstance(primary, dict):
            if indicator_count is None:
                try:
                    indicator_count = int(primary.get("passed")) if primary.get("passed") is not None else None
                except (TypeError, ValueError):
                    indicator_count = None
            if indicator_total is None:
                try:
                    indicator_total = int(primary.get("total")) if primary.get("total") is not None else None
                except (TypeError, ValueError):
                    indicator_total = None

    return {
        "trend_stage": trend_stage,
        "entry_gate_score": entry_gate_score,
        "continuation_quality_score": continuation_quality_score,
        "momentum_acceleration_score": momentum_acceleration_score,
        "confidence_score": confidence_score,
        "indicator_count": indicator_count,
        "indicator_total": indicator_total,
    }


def _broker_transaction_trades_for_period(start_date: str, end_date: str):
    """Build completed SPY option trades from Schwab transaction history for an inclusive period.

    Uses transaction cash flows (netAmount) as source of truth for per-trade P&L.
    """
    if not start_date or not end_date:
        return []

    try:
        period_start = datetime.strptime(str(start_date), "%Y-%m-%d").date()
        period_end = datetime.strptime(str(end_date), "%Y-%m-%d").date()
    except Exception:
        return []
    if period_end < period_start:
        return []

    account_hash = os.getenv("SCHWAB_ACCOUNT_HASH")
    if not account_hash:
        return []

    def _tx_time_et(tx):
        for key in ("transactionDate", "tradeDate", "time"):
            raw = (tx or {}).get(key)
            if not raw:
                continue
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(EASTERN_TZ)
            except Exception:
                continue
        return None

    def _option_item(tx):
        for item in (tx or {}).get("transferItems") or []:
            inst = (item or {}).get("instrument") or {}
            if str(inst.get("assetType") or "").upper() != "OPTION":
                continue
            symbol = str(inst.get("symbol") or "")
            if not symbol.startswith("SPY"):
                continue
            pos = str((item or {}).get("positionEffect") or "").upper()
            if pos not in {"OPENING", "CLOSING"}:
                continue
            return item
        return None

    try:
        day_start = datetime.combine(period_start, datetime.min.time(), tzinfo=EASTERN_TZ)
        day_end = datetime.combine(period_end, datetime.max.time(), tzinfo=EASTERN_TZ)
        client = _get_broker_client()
        resp = client.get_transactions(
            account_hash,
            start_date=day_start,
            end_date=day_end,
            transaction_types=["TRADE"],
        )
        resp.raise_for_status()
        txs = resp.json() or []
    except Exception:
        return []

    order_type_by_id = {}
    bot_order_ids = _bot_order_ids_from_audit()
    try:
        order_resp = client.get_orders_for_account(account_hash)
        order_resp.raise_for_status()
        orders = order_resp.json() or []
        for order in orders:
            order_id = str(order.get("orderId") or "")
            if not order_id:
                continue
            order_type_by_id[order_id] = str(order.get("orderType") or "").upper()
    except Exception:
        pass

    events = []
    for tx in txs:
        tx_time = _tx_time_et(tx)
        if tx_time is None or not (period_start <= tx_time.date() <= period_end):
            continue

        item = _option_item(tx)
        if item is None:
            continue

        inst = (item or {}).get("instrument") or {}
        symbol = str(inst.get("symbol") or "")
        pos = str((item or {}).get("positionEffect") or "").upper()

        try:
            qty = abs(float((item or {}).get("amount") or 0.0))
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0:
            continue

        try:
            option_notional = abs(float((item or {}).get("cost") or 0.0))
        except (TypeError, ValueError):
            option_notional = 0.0
        option_price = (option_notional / (qty * OPTION_CONTRACT_MULTIPLIER)) if qty > 0 else 0.0

        try:
            net_amount = float((tx or {}).get("netAmount"))
        except (TypeError, ValueError):
            net_amount = 0.0

        events.append(
            {
                "time": tx_time,
                "symbol": symbol,
                "direction": _option_direction_from_symbol(symbol) or "CALL",
                "position_effect": pos,
                "qty": float(qty),
                "price": round(float(option_price), 4),
                "net_amount": float(net_amount),
                "order_id": str((tx or {}).get("orderId") or ""),
            }
        )

    events.sort(key=lambda e: e["time"])
    if not events:
        return []

    open_lots = {}
    trades = []

    for event in events:
        symbol = event["symbol"]
        open_lots.setdefault(symbol, [])

        if event["position_effect"] == "OPENING":
            open_lots[symbol].append(
                {
                    "remaining_qty": float(event["qty"]),
                    "entry_time": event["time"],
                    "entry_price": float(event["price"]),
                    "entry_net": float(event["net_amount"]),
                    "entry_qty_total": float(event["qty"]),
                    "direction": event["direction"],
                    "symbol": symbol,
                    "entry_order_id": event["order_id"],
                }
            )
            continue

        # CLOSING leg: pair FIFO against open lots for this symbol.
        remaining_close = float(event["qty"])
        close_qty_total = float(event["qty"])

        while remaining_close > 1e-9 and open_lots[symbol]:
            lot = open_lots[symbol][0]
            use_qty = min(remaining_close, float(lot["remaining_qty"]))

            open_alloc = float(lot["entry_net"]) * (use_qty / float(lot["entry_qty_total"]))
            close_alloc = float(event["net_amount"]) * (use_qty / close_qty_total)
            trade_pnl = open_alloc + close_alloc

            buy_event = {
                "price": float(lot["entry_price"]),
                "order_id": str(lot.get("entry_order_id") or ""),
            }
            sell_event = {
                "price": float(event["price"]),
                "order_id": str(event.get("order_id") or ""),
                "order_type": str(order_type_by_id.get(str(event.get("order_id") or ""), "")),
            }
            exit_reason = classify_exit_reason(buy_event, sell_event)

            manual_label = "Mason" if _is_manual_exit_trade(sell_event, bot_order_ids) else ""
            entry_et = lot["entry_time"].astimezone(EASTERN_TZ)
            exit_et = event["time"].astimezone(EASTERN_TZ)
            manual_label = _manual_label_override(exit_et.date().isoformat(), entry_et, exit_et, manual_label)
            manual_label = _local_exit_manual_label(
                lot.get("entry_order_id"),
                event.get("order_id"),
                manual_label,
            )
            if manual_label == "Mason":
                exit_reason = "MANUAL_EXIT_LIMIT"

            trades.append(
                {
                    "id": None,
                    "entry_time": lot["entry_time"].isoformat(),
                    "exit_time": event["time"].isoformat(),
                    "direction": lot["direction"],
                    "entry_price": round(float(lot["entry_price"]), 4),
                    "exit_price": round(float(event["price"]), 4),
                    "pnl": round(float(trade_pnl), 2),
                    "pnl_source": "broker_cash",
                    "option_symbol": symbol,
                    "option_entry": round(float(lot["entry_price"]), 4),
                    "option_exit": round(float(event["price"]), 4),
                    "option_quantity": float(use_qty),
                    "exit_reason": exit_reason,
                    "manual_label": manual_label,
                    "broker_entry_order_id": lot.get("entry_order_id", ""),
                    "broker_exit_order_id": event.get("order_id", ""),
                }
            )

            lot["remaining_qty"] = float(lot["remaining_qty"]) - use_qty
            remaining_close -= use_qty

            if lot["remaining_qty"] <= 1e-9:
                open_lots[symbol].pop(0)

    # Merge split fill slices (same trade split into multiple 1-contract rows)
    # into one logical trade for dashboard/reporting consistency.
    grouped = {}
    for trade in trades:
        entry_order_id = str(trade.get("broker_entry_order_id") or "")
        exit_order_id = str(trade.get("broker_exit_order_id") or "")
        if entry_order_id or exit_order_id:
            key = (
                "ORDER_PAIR",
                entry_order_id,
                exit_order_id,
                str(trade.get("option_symbol") or ""),
                str(trade.get("direction") or ""),
                str(trade.get("exit_reason") or ""),
                str(trade.get("manual_label") or ""),
            )
        else:
            key = (
                "TIME_PRICE_FALLBACK",
                str(trade.get("option_symbol") or ""),
                str(trade.get("direction") or ""),
                str(trade.get("entry_time") or ""),
                str(trade.get("exit_time") or ""),
                round(float(trade.get("entry_price") or 0.0), 4),
                round(float(trade.get("exit_price") or 0.0), 4),
                str(trade.get("exit_reason") or ""),
                str(trade.get("manual_label") or ""),
            )

        qty = float(trade.get("option_quantity") or 0.0)
        entry_px = float(trade.get("entry_price") or 0.0)
        exit_px = float(trade.get("exit_price") or 0.0)

        if key not in grouped:
            grouped[key] = dict(trade)
            grouped[key]["option_quantity"] = qty
            grouped[key]["pnl"] = float(trade.get("pnl") or 0.0)
            grouped[key]["_entry_notional"] = entry_px * qty
            grouped[key]["_exit_notional"] = exit_px * qty
            continue

        grouped[key]["option_quantity"] = float(grouped[key].get("option_quantity") or 0.0) + qty
        grouped[key]["pnl"] = float(grouped[key].get("pnl") or 0.0) + float(trade.get("pnl") or 0.0)
        grouped[key]["_entry_notional"] = float(grouped[key].get("_entry_notional") or 0.0) + (entry_px * qty)
        grouped[key]["_exit_notional"] = float(grouped[key].get("_exit_notional") or 0.0) + (exit_px * qty)

        existing_entry = _parse_iso_datetime(grouped[key].get("entry_time"))
        new_entry = _parse_iso_datetime(trade.get("entry_time"))
        if existing_entry is None or (new_entry is not None and new_entry < existing_entry):
            grouped[key]["entry_time"] = trade.get("entry_time")

        existing_exit = _parse_iso_datetime(grouped[key].get("exit_time"))
        new_exit = _parse_iso_datetime(trade.get("exit_time"))
        if existing_exit is None or (new_exit is not None and new_exit > existing_exit):
            grouped[key]["exit_time"] = trade.get("exit_time")

    merged = []
    for row in grouped.values():
        total_qty = float(row.get("option_quantity") or 0.0)
        if total_qty > 0:
            row["entry_price"] = round(float(row.get("_entry_notional") or 0.0) / total_qty, 4)
            row["exit_price"] = round(float(row.get("_exit_notional") or 0.0) / total_qty, 4)
        row["pnl"] = round(float(row.get("pnl") or 0.0), 2)
        row["option_quantity"] = total_qty
        if abs(row["option_quantity"] - round(row["option_quantity"])) < 1e-9:
            row["option_quantity"] = int(round(row["option_quantity"]))
        row.pop("_entry_notional", None)
        row.pop("_exit_notional", None)
        merged.append(row)

    return sorted(merged, key=lambda t: str(t.get("entry_time") or ""), reverse=True)


def _broker_transaction_trades_for_date(trading_date: str):
    """Build completed SPY option trades from Schwab transaction history for one day."""
    return _broker_transaction_trades_for_period(trading_date, trading_date)


def _collapse_split_trade_rows(rows):
    """Collapse split-fill rows into one logical trade row.

    Prefer broker order IDs when available; otherwise use a conservative
    time/symbol/direction fallback key.
    """
    if not rows:
        return []

    grouped = {}
    for row in rows:
        entry_order_id = str(row.get("broker_entry_order_id") or "")
        exit_order_id = str(row.get("broker_exit_order_id") or "")

        if entry_order_id or exit_order_id:
            key = (
                "ORDER_PAIR",
                entry_order_id,
                exit_order_id,
                str(row.get("option_symbol") or ""),
                str(row.get("direction") or ""),
                str(row.get("exit_reason") or ""),
            )
        else:
            key = (
                "TIME_FALLBACK",
                str(row.get("option_symbol") or ""),
                str(row.get("direction") or ""),
                str(row.get("entry_time") or ""),
                str(row.get("exit_time") or ""),
                str(row.get("exit_reason") or ""),
            )

        qty = float(row.get("option_quantity") or 0.0)
        entry_px = float(row.get("entry_price") or 0.0)
        exit_px = float(row.get("exit_price") or 0.0)

        if key not in grouped:
            grouped[key] = dict(row)
            grouped[key]["option_quantity"] = qty
            grouped[key]["pnl"] = float(row.get("pnl") or 0.0)
            grouped[key]["_entry_notional"] = entry_px * qty
            grouped[key]["_exit_notional"] = exit_px * qty
            continue

        agg = grouped[key]
        agg["option_quantity"] = float(agg.get("option_quantity") or 0.0) + qty
        agg["pnl"] = float(agg.get("pnl") or 0.0) + float(row.get("pnl") or 0.0)
        agg["_entry_notional"] = float(agg.get("_entry_notional") or 0.0) + (entry_px * qty)
        agg["_exit_notional"] = float(agg.get("_exit_notional") or 0.0) + (exit_px * qty)

        existing_entry = _parse_iso_datetime(agg.get("entry_time"))
        new_entry = _parse_iso_datetime(row.get("entry_time"))
        if existing_entry is None or (new_entry is not None and new_entry < existing_entry):
            agg["entry_time"] = row.get("entry_time")

        existing_exit = _parse_iso_datetime(agg.get("exit_time"))
        new_exit = _parse_iso_datetime(row.get("exit_time"))
        if existing_exit is None or (new_exit is not None and new_exit > existing_exit):
            agg["exit_time"] = row.get("exit_time")

        for field in ("feature_payload", "entry_diagnostic_snapshot", "exit_diagnostic_snapshot", "manual_label"):
            if not agg.get(field) and row.get(field):
                agg[field] = row.get(field)

    collapsed = []
    for agg in grouped.values():
        total_qty = float(agg.get("option_quantity") or 0.0)
        if total_qty > 0:
            agg["entry_price"] = round(float(agg.get("_entry_notional") or 0.0) / total_qty, 4)
            agg["exit_price"] = round(float(agg.get("_exit_notional") or 0.0) / total_qty, 4)
        agg["pnl"] = round(float(agg.get("pnl") or 0.0), 2)
        if abs(total_qty - round(total_qty)) < 1e-9:
            agg["option_quantity"] = int(round(total_qty))
        else:
            agg["option_quantity"] = total_qty
        agg.pop("_entry_notional", None)
        agg.pop("_exit_notional", None)
        collapsed.append(agg)

    return sorted(collapsed, key=lambda t: str(t.get("entry_time") or ""), reverse=True)


def _schwab_transaction_day_net_pnl(trading_date: str):
    """Return net SPY option cash P&L for a day from Schwab transaction history."""
    if not trading_date:
        return None

    try:
        target_day = datetime.strptime(str(trading_date), "%Y-%m-%d").date()
    except Exception:
        return None

    def _is_spy_option_trade(tx):
        transfer_items = (tx or {}).get("transferItems") or []
        for item in transfer_items:
            item = item or {}
            inst = item.get("instrument") or {}
            if str(inst.get("assetType") or "").upper() != "OPTION":
                continue
            symbol = str(inst.get("symbol") or "")
            underlying = str(inst.get("underlyingSymbol") or "")
            if "SPY" in symbol or underlying == "SPY":
                return True
        return False

    def _tx_time_et(tx):
        for key in ("transactionDate", "tradeDate", "time"):
            raw = (tx or {}).get(key)
            if not raw:
                continue
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(EASTERN_TZ)
            except Exception:
                continue
        return None

    def _tx_cash_amount(tx):
        from decimal import Decimal, InvalidOperation

        for key in ("netAmount", "amount"):
            try:
                return Decimal(str((tx or {}).get(key)))
            except (InvalidOperation, TypeError, ValueError):
                continue

        transfer_items = (tx or {}).get("transferItems") or []
        for item in transfer_items:
            try:
                return Decimal(str((item or {}).get("amount")))
            except (InvalidOperation, TypeError, ValueError):
                continue
        return None

    # 1) Preferred: live Schwab transaction API (source of truth).
    try:
        account_hash = os.getenv("SCHWAB_ACCOUNT_HASH")
        if account_hash:
            day_start = datetime.combine(target_day, datetime.min.time(), tzinfo=EASTERN_TZ)
            day_end = datetime.combine(target_day, datetime.max.time(), tzinfo=EASTERN_TZ)
            client = _get_broker_client()
            resp = client.get_transactions(
                account_hash,
                start_date=day_start,
                end_date=day_end,
                transaction_types=["TRADE"],
            )
            resp.raise_for_status()
            txs = resp.json() or []

            from decimal import Decimal

            net = Decimal("0")
            matched = 0
            for tx in txs:
                tx_ts = _tx_time_et(tx)
                if tx_ts is None or tx_ts.date() != target_day:
                    continue
                if not _is_spy_option_trade(tx):
                    continue
                amount = _tx_cash_amount(tx)
                if amount is None:
                    continue
                net += amount
                matched += 1

            if matched > 0:
                return round(float(net), 2)
    except Exception:
        pass

    realized = _realized_spy_option_pnl_for_date(trading_date)
    if realized is not None:
        return round(float(realized), 2)

    # 2) Fallback: latest Schwab transaction export in Downloads.
    try:
        _, payload = _load_latest_schwab_transaction_export()
        if not payload:
            return None

        rows = payload.get("BrokerageTransactions") or []
        accepted_actions = {"Buy to Open", "Buy to Close", "Sell to Open", "Sell to Close"}
        target_mmddyyyy = target_day.strftime("%m/%d/%Y")

        net = 0.0
        matched = 0
        for row in rows:
            action = str((row or {}).get("Action") or "")
            symbol = str((row or {}).get("Symbol") or "")
            row_date = str((row or {}).get("Date") or "")
            if action not in accepted_actions:
                continue
            if not symbol.startswith("SPY "):
                continue
            if row_date != target_mmddyyyy:
                continue

            net += _parse_money_text((row or {}).get("Amount"))
            matched += 1

        if matched > 0:
            return round(net, 2)
    except Exception:
        pass

    return None


def _option_direction_from_symbol(symbol: str):
    symbol_text = str(symbol or "")
    m = re.search(r"([CP])(\d{8})$", symbol_text)
    if m:
        return "CALL" if m.group(1) == "C" else "PUT"
    if " C" in symbol_text:
        return "CALL"
    if " P" in symbol_text:
        return "PUT"
    return None


def _position_label_from_option_symbol(symbol: str, fallback_direction: str = ""):
    """Format current position label as `$<strike> Call/Put` (e.g., `$753 Put`)."""
    symbol_text = str(symbol or "")
    direction = _option_direction_from_symbol(symbol_text) or str(fallback_direction or "").upper()

    m_occ = re.search(r"([CP])(\d{8})$", symbol_text)
    if m_occ:
        side = "Call" if m_occ.group(1) == "C" else "Put"
        strike_raw = int(m_occ.group(2)) / 1000.0
        strike_text = str(int(strike_raw)) if float(strike_raw).is_integer() else f"{strike_raw:.2f}".rstrip("0").rstrip(".")
        return f"${strike_text} {side}"

    m_legacy = re.search(r"\b([CP])(\d+(?:\.\d+)?)\b", symbol_text)
    if m_legacy:
        side = "Call" if m_legacy.group(1) == "C" else "Put"
        strike = float(m_legacy.group(2))
        strike_text = str(int(strike)) if strike.is_integer() else f"{strike:.2f}".rstrip("0").rstrip(".")
        return f"${strike_text} {side}"

    if direction in {"CALL", "PUT"}:
        return direction.title()
    return "Unknown"


def _active_broker_protective_stop_price(option_symbol: str, preferred_order_id: str = ""):
    """Return the live broker stop trigger for an open option position, if confirmed."""
    symbol = str(option_symbol or "").strip()
    preferred_id = str(preferred_order_id or "").strip()
    if not symbol or not os.getenv("SCHWAB_ACCOUNT_HASH"):
        return None

    now = time.time()
    if (
        _ACTIVE_PROTECTIVE_STOP_CACHE.get("symbol") == symbol
        and _ACTIVE_PROTECTIVE_STOP_CACHE.get("preferred_order_id") == preferred_id
        and (now - float(_ACTIVE_PROTECTIVE_STOP_CACHE.get("timestamp") or 0.0)) < 5.0
    ):
        return _ACTIVE_PROTECTIVE_STOP_CACHE.get("price")

    active_statuses = {
        "PENDING_ACTIVATION", "ACCEPTED", "QUEUED", "WORKING",
        "PENDING_REPLACEMENT", "PARTIALLY_FILLED", "AWAITING_PARENT_ORDER",
        "AWAITING_CONDITION",
    }
    stop_orders = []
    try:
        client = _get_broker_client()
        response = client.get_orders_for_account(os.getenv("SCHWAB_ACCOUNT_HASH"))
        response.raise_for_status()
        orders = response.json() if isinstance(response.json(), list) else []
        for order in orders:
            if str(order.get("status") or "").upper() not in active_statuses:
                continue
            if str(order.get("orderType") or "").upper() not in {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"}:
                continue
            for leg in order.get("orderLegCollection") or []:
                instrument = (leg or {}).get("instrument") or {}
                if str(instrument.get("assetType") or "").upper() != "OPTION":
                    continue
                if str(instrument.get("symbol") or "") != symbol:
                    continue
                if str((leg or {}).get("instruction") or "").upper() != "SELL_TO_CLOSE":
                    continue
                try:
                    stop_price = float(order.get("stopPrice"))
                except (TypeError, ValueError):
                    continue
                if stop_price > 0:
                    stop_orders.append(order)
                break
    except Exception:
        return None

    selected = next(
        (order for order in stop_orders if str(order.get("orderId") or "") == preferred_id),
        None,
    )
    if selected is None and stop_orders:
        selected = max(stop_orders, key=lambda order: str(order.get("enteredTime") or ""))

    price = round(float(selected.get("stopPrice")), 3) if selected is not None else None
    _ACTIVE_PROTECTIVE_STOP_CACHE.update({
        "timestamp": now,
        "symbol": symbol,
        "preferred_order_id": preferred_id,
        "price": price,
    })
    return price


def _filled_price_from_order(order):
    total_qty = 0.0
    total_notional = 0.0
    activities = (order or {}).get("orderActivityCollection") or []
    for activity in activities:
        for leg in activity.get("executionLegs") or []:
            try:
                qty = float(leg.get("quantity") or 0.0)
                price = float(leg.get("price"))
            except (TypeError, ValueError):
                continue
            if qty <= 0:
                continue
            total_qty += qty
            total_notional += qty * price

    if total_qty > 0:
        return total_notional / total_qty

    price = (order or {}).get("price")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


def _execution_quality_summary_for_date(trading_date: str):
    """Compute execution quality metrics for SPY option BUY_TO_OPEN orders."""
    if not trading_date:
        return {
            "trading_date": None,
            "attempt_count": 0,
            "filled_count": 0,
            "fill_rate_pct": 0.0,
            "fallback_count": 0,
            "fallback_rate_pct": 0.0,
            "avg_slippage": None,
            "avg_slippage_bps": None,
            "by_side_window": [],
        }

    cache_ttl = float(os.getenv("EXECUTION_QUALITY_CACHE_SECONDS", "10"))
    now_ts = time.time()
    if (
        _EXECUTION_QUALITY_CACHE.get("trading_date") == trading_date
        and (now_ts - float(_EXECUTION_QUALITY_CACHE.get("timestamp") or 0.0)) <= max(1.0, cache_ttl)
        and _EXECUTION_QUALITY_CACHE.get("payload") is not None
    ):
        return _EXECUTION_QUALITY_CACHE.get("payload")

    account_hash = os.getenv("SCHWAB_ACCOUNT_HASH")
    if not account_hash:
        return {
            "trading_date": trading_date,
            "attempt_count": 0,
            "filled_count": 0,
            "fill_rate_pct": 0.0,
            "fallback_count": 0,
            "fallback_rate_pct": 0.0,
            "avg_slippage": None,
            "avg_slippage_bps": None,
            "by_side_window": [],
            "error": "SCHWAB_ACCOUNT_HASH not configured",
        }

    def _order_time_et(order):
        for key in ("enteredTime", "closeTime"):
            raw = (order or {}).get(key)
            if not raw:
                continue
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(EASTERN_TZ)
            except Exception:
                continue
        return None

    def _window_label(ts):
        if ts.hour < 11:
            return "Morning"
        if ts.hour < 14:
            return "Midday"
        return "Afternoon"

    try:
        client = _get_broker_client()
        resp = client.get_orders_for_account(account_hash)
        resp.raise_for_status()
        orders = resp.json() or []
    except Exception as e:
        return {
            "trading_date": trading_date,
            "attempt_count": 0,
            "filled_count": 0,
            "fill_rate_pct": 0.0,
            "fallback_count": 0,
            "fallback_rate_pct": 0.0,
            "avg_slippage": None,
            "avg_slippage_bps": None,
            "by_side_window": [],
            "error": str(e),
        }

    attempt_count = 0
    filled_count = 0
    fallback_count = 0
    slippage_values = []
    side_window = {}

    for order in orders:
        order_ts = _order_time_et(order)
        if order_ts is None or order_ts.date().isoformat() != trading_date:
            continue

        legs = (order or {}).get("orderLegCollection") or []
        if not legs:
            continue
        leg = legs[0]
        inst = (leg or {}).get("instrument") or {}
        if str(inst.get("assetType") or "").upper() != "OPTION":
            continue
        symbol = str(inst.get("symbol") or "")
        if not symbol.startswith("SPY"):
            continue
        instruction = str((leg or {}).get("instruction") or "").upper()
        if instruction != "BUY_TO_OPEN":
            continue

        attempt_count += 1
        status = str((order or {}).get("status") or "").upper()
        order_type = str((order or {}).get("orderType") or "").upper()
        if status != "FILLED":
            continue

        filled_count += 1
        if order_type == "MARKET":
            fallback_count += 1

        fill_price = _filled_price_from_order(order)
        try:
            requested = float((order or {}).get("price")) if (order or {}).get("price") is not None else None
        except (TypeError, ValueError):
            requested = None

        if fill_price is None or requested is None or requested <= 0:
            continue

        side = _option_direction_from_symbol(symbol) or "CALL"
        window = _window_label(order_ts)
        key = f"{side}|{window}"
        slippage = float(fill_price) - float(requested)
        slippage_values.append(slippage)

        bucket = side_window.setdefault(key, {
            "side": side,
            "window": window,
            "count": 0,
            "sum_slippage": 0.0,
            "sum_slippage_bps": 0.0,
        })
        bucket["count"] += 1
        bucket["sum_slippage"] += slippage
        bucket["sum_slippage_bps"] += (slippage / requested) * 10000.0

    by_side_window = []
    for bucket in side_window.values():
        count = int(bucket.get("count") or 0)
        if count <= 0:
            continue
        by_side_window.append({
            "side": bucket["side"],
            "window": bucket["window"],
            "avg_slippage": round(float(bucket["sum_slippage"]) / count, 4),
            "avg_slippage_bps": round(float(bucket["sum_slippage_bps"]) / count, 1),
        })

    by_side_window.sort(key=lambda x: (x.get("side") or "", x.get("window") or ""))

    avg_slippage = (sum(slippage_values) / len(slippage_values)) if slippage_values else None
    avg_slippage_bps = None
    if slippage_values:
        bps_values = []
        for order in orders:
            order_ts = _order_time_et(order)
            if order_ts is None or order_ts.date().isoformat() != trading_date:
                continue
            legs = (order or {}).get("orderLegCollection") or []
            if not legs:
                continue
            leg = legs[0]
            inst = (leg or {}).get("instrument") or {}
            if str(inst.get("assetType") or "").upper() != "OPTION":
                continue
            symbol = str(inst.get("symbol") or "")
            if not symbol.startswith("SPY"):
                continue
            if str((leg or {}).get("instruction") or "").upper() != "BUY_TO_OPEN":
                continue
            if str((order or {}).get("status") or "").upper() != "FILLED":
                continue
            fill_price = _filled_price_from_order(order)
            try:
                requested = float((order or {}).get("price")) if (order or {}).get("price") is not None else None
            except (TypeError, ValueError):
                requested = None
            if fill_price is None or requested is None or requested <= 0:
                continue
            bps_values.append(((float(fill_price) - float(requested)) / float(requested)) * 10000.0)
        if bps_values:
            avg_slippage_bps = sum(bps_values) / len(bps_values)

    payload = {
        "trading_date": trading_date,
        "attempt_count": attempt_count,
        "filled_count": filled_count,
        "fill_rate_pct": round((filled_count / attempt_count) * 100.0, 1) if attempt_count > 0 else 0.0,
        "fallback_count": fallback_count,
        "fallback_rate_pct": round((fallback_count / filled_count) * 100.0, 1) if filled_count > 0 else 0.0,
        "avg_slippage": round(float(avg_slippage), 4) if avg_slippage is not None else None,
        "avg_slippage_bps": round(float(avg_slippage_bps), 1) if avg_slippage_bps is not None else None,
        "by_side_window": by_side_window,
        "goals": EXECUTION_QUALITY_GOALS,
        "generated_at": datetime.now(EASTERN_TZ).isoformat(),
    }

    _EXECUTION_QUALITY_CACHE["timestamp"] = now_ts
    _EXECUTION_QUALITY_CACHE["trading_date"] = trading_date
    _EXECUTION_QUALITY_CACHE["payload"] = payload
    return payload


@app.route('/api/execution-quality-summary', methods=['GET'])
def api_execution_quality_summary():
    """Return entry execution quality metrics for today's SPY option orders."""
    try:
        requested_date = (request.args.get("date") or "").strip()
        trading_date = requested_date or datetime.now(EASTERN_TZ).date().isoformat()
        return jsonify(_execution_quality_summary_for_date(trading_date))
    except Exception as e:
        return jsonify({
            "trading_date": None,
            "attempt_count": 0,
            "filled_count": 0,
            "fill_rate_pct": 0.0,
            "fallback_count": 0,
            "fallback_rate_pct": 0.0,
            "avg_slippage": None,
            "avg_slippage_bps": None,
            "by_side_window": [],
            "goals": EXECUTION_QUALITY_GOALS,
            "error": str(e),
        })


@app.route('/api/daily-learning-insights', methods=['GET'])
def api_daily_learning_insights():
    """Return latest daily trade-learning lessons for dashboard display."""
    try:
        force_refresh = str(request.args.get("refresh") or "").strip().lower() in {"1", "true", "yes"}
        return jsonify(_daily_learning_insights_payload(force_refresh=force_refresh))
    except Exception as e:
        return jsonify({
            "available": False,
            "trading_date": None,
            "generated_at": None,
            "summary": {},
            "actionable_lessons": [],
            "error": str(e),
        })


@app.route('/api/spy-bot-reviewer', methods=['GET'])
def api_spy_bot_reviewer():
    """Return the isolated SPY post-session review ledger for Cockpit."""
    return jsonify(SpyBotReviewer(PROJECT_ROOT).dashboard_payload((request.args.get("date") or "").strip() or None))


@app.route('/api/spy-bot-reviewer/replay/<trade_id>', methods=['GET'])
def api_spy_bot_reviewer_replay(trade_id):
    """Return one immutable trade replay bundle for Cockpit's stepper."""
    replay = SpyBotReviewer(PROJECT_ROOT).replay_bundle(trade_id)
    if replay is None:
        return jsonify({"error": "replay not found"}), 404
    return jsonify(replay)


@app.route('/api/spy-bot-reviewer/counterfactuals', methods=['GET'])
def api_spy_bot_reviewer_counterfactuals():
    """Return aggregate, advisory-only alternative-outcome evidence."""
    return jsonify(SpyBotReviewer(PROJECT_ROOT).counterfactual_summary())


@app.route('/api/spy-bot-reviewer/patterns', methods=['GET'])
def api_spy_bot_reviewer_patterns():
    """Return immutable, advisory-only replay pattern discoveries."""
    return jsonify(SpyBotReviewer(PROJECT_ROOT).dashboard_payload().get("pattern_discovery", {}))


@app.route('/api/spy-bot-reviewer/hypotheses', methods=['GET'])
def api_spy_bot_reviewer_hypotheses():
    """Return ranked advisory hypotheses and their immutable evidence state."""
    return jsonify({"hypotheses": SpyBotReviewer(PROJECT_ROOT).dashboard_payload().get("hypotheses", [])})


@app.route('/api/spy-bot-reviewer/market-memory', methods=['GET'])
def api_spy_bot_reviewer_market_memory():
    """Return the latest immutable market-memory record and historical analogs."""
    return jsonify(SpyBotReviewer(PROJECT_ROOT).dashboard_payload().get("market_memory") or {})


@app.route('/api/research-governance', methods=['GET'])
def api_research_governance():
    """Return the advisory-only Research Performance & Governance snapshot."""
    return jsonify(SpyBotReviewer(PROJECT_ROOT).dashboard_payload().get("research_governance") or {})


@app.route('/api/experiments', methods=['GET'])
def api_experiments():
    """Return replay-only experiment protocols and immutable interim analyses."""
    return jsonify({"experiments": SpyBotReviewer(PROJECT_ROOT).dashboard_payload().get("experiments", [])})


@app.route('/api/spy-bot-reviewer/hypotheses/<hypothesis_id>/promote', methods=['POST'])
def api_spy_bot_reviewer_promote_hypothesis(hypothesis_id):
    """Manual bridge from Ready for Validation to Rule Validation only."""
    try:
        return jsonify(SpyBotReviewer(PROJECT_ROOT).promote_hypothesis_to_rule_validation(hypothesis_id))
    except KeyError:
        return jsonify({"error": "hypothesis not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409


@app.route('/api/spy-bot-reviewer/validate-rule', methods=['POST'])
def api_spy_bot_reviewer_validate_rule():
    """Record expectancy evidence; this endpoint can never deploy a live rule."""
    payload = request.get_json(silent=True) or {}
    rule_id = str(payload.get("rule_id") or "").strip()
    proposal = str(payload.get("proposal") or "").strip()
    outcomes = payload.get("trade_outcomes") or []
    if not rule_id or not proposal or not isinstance(outcomes, list):
        return jsonify({"error": "rule_id, proposal, and trade_outcomes[] are required"}), 400
    return jsonify(SpyBotReviewer(PROJECT_ROOT).validate_rule(rule_id, proposal, outcomes))


@app.route('/spy-bot-reviewer', methods=['GET'])
def spy_bot_reviewer_dashboard():
    return render_template_string("""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SPY Bot Reviewer | McLeod Alpha Cockpit</title><style>
:root{--ink:#17212b;--muted:#5d6770;--line:#d8dee3;--paper:#f6f7f5;--panel:#fff;--accent:#087e8b;--good:#1d7a46;--warn:#ad5d09}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px Georgia,serif}.shell{max-width:1180px;margin:auto;padding:28px 20px 54px}header{border-bottom:2px solid var(--ink);padding-bottom:18px;display:flex;justify-content:space-between;gap:20px;align-items:end}h1{font-size:32px;margin:0}p{color:var(--muted);margin:6px 0}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}.card,.panel{background:var(--panel);border:1px solid var(--line);padding:16px;border-radius:6px}.panel{margin-top:14px}.label{font:12px ui-sans-serif,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.value{font-size:25px;margin-top:8px}.row{display:grid;grid-template-columns:150px 1fr 120px;gap:12px;border-top:1px solid var(--line);padding:12px 0}.status{font:12px ui-sans-serif,sans-serif;font-weight:bold;color:var(--warn)}.validated{color:var(--good)}pre{white-space:pre-wrap;margin:0;font:12px ui-monospace,monospace;color:var(--muted)}button{border:1px solid var(--ink);background:#fff;padding:6px 9px;margin:0 4px 8px 0;border-radius:4px;cursor:pointer}button:disabled{opacity:.4}.candle{font:13px ui-monospace,monospace;min-height:120px}@media(max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}.row{grid-template-columns:1fr}}
 </style></head><body><main class="shell"><header><div><h1>SPY Bot Reviewer</h1><p>Immutable trade replay, objective scoring, and evidence-gated learning.</p></div><a href="/">Cockpit</a></header><section class="grid" id="metrics"><div class="card">Loading reviewer history...</div></section><section class="panel"><h2>Trade Replay</h2><div id="trades">No captured trades yet.</div><div id="stepper" hidden><button id="previous">Previous</button><button id="next">Next</button><span id="step"></span><pre class="candle" id="candle"></pre></div></section><section class="panel"><h2>Alternative Outcomes</h2><div id="alternatives">Select a replay to inspect alternative outcomes.</div><div id="improvements"></div></section><section class="panel"><h2>Pattern Discovery</h2><div id="patterns">Pattern evidence is loading.</div></section><section class="panel"><h2>Historical Analogs</h2><div id="analogs">Historical market analogs are loading.</div></section><section class="panel"><h2>Latest Review</h2><pre id="review">Loading...</pre></section><section class="panel"><h2>Rule Validation Database</h2><div id="rules">Loading...</div></section></main><script>
let replay=[],index=0;function render(){const c=replay[index]||{};document.querySelector('#step').textContent=`Candle ${index+1} / ${replay.length}`;document.querySelector('#candle').textContent=JSON.stringify(c,null,2);document.querySelector('#previous').disabled=index===0;document.querySelector('#next').disabled=index>=replay.length-1}async function openReplay(id){const data=await fetch('/api/spy-bot-reviewer/replay/'+encodeURIComponent(id)).then(r=>r.json());replay=(data.candles||{})['1m']||[];index=0;document.querySelector('#stepper').hidden=!replay.length;render();const outcomes=((data.alternative_outcomes||{}).alternatives||[]);document.querySelector('#alternatives').innerHTML=outcomes.map(row=>`<div class="row"><strong>${row.name}</strong><span>P&L ${row.pnl}; MAE ${row.mae_pct}%; MFE ${row.mfe_pct}%; drawdown ${row.drawdown_pct}%; hold ${row.hold_minutes}m</span><span class="status">Delta ${row.delta_pnl}</span></div>`).join('')||'No counterfactual evidence available.'}document.querySelector('#previous').onclick=()=>{index--;render()};document.querySelector('#next').onclick=()=>{index++;render()};async function load(){const data=await fetch('/api/spy-bot-reviewer').then(r=>r.json());const latest=data.latest_review||{};const metrics=((latest.analysis||{}).metrics||{});document.querySelector('#metrics').innerHTML=`<div class="card"><div class="label">Reviews</div><div class="value">${data.review_history.length}</div></div><div class="card"><div class="label">Latest session</div><div class="value">${latest.trading_date||'--'}</div></div><div class="card"><div class="label">Expectancy</div><div class="value">${metrics.expectancy??'--'}</div></div><div class="card"><div class="label">Net P&L</div><div class="value">${metrics.net_pnl??'--'}</div></div>`;const bundles=((latest.evidence||{}).replay_bundles||[]);document.querySelector('#trades').innerHTML=bundles.map(b=>`<button onclick="openReplay('${b.trade_id}')">Replay trade ${b.trade_id}</button> ${Object.entries(b.scores||{}).filter(([k])=>k!=='note'&&k!=='method').map(([k,v])=>k+': '+v).join(' | ')}`).join('')||'No captured trades yet.';const improvements=((data.counterfactual_summary||{}).improvements||[]);document.querySelector('#improvements').innerHTML=improvements.length?'<h3>Aggregate evidence</h3>'+improvements.map(row=>`<div class="row"><strong>${row.name}</strong><span>Expectancy improvement ${row.expectancy_improvement}; trades ${row.trades_tested}</span><span class="status">${row.status}</span></div>`).join(''):'<p>Aggregate evidence is accumulating. Strategy changes remain isolated until validated.</p>';const patterns=((data.pattern_discovery||{}).patterns||[]);document.querySelector('#patterns').innerHTML=patterns.length?patterns.map(row=>`<div class="row"><strong>${row.label}</strong><span>Win ${row.win_rate_pct}%; expectancy ${row.expectancy}; MAE ${row.mae_pct}%; MFE ${row.mfe_pct}%; hold ${row.average_hold_minutes}m; confidence ${row.confidence_level}; p=${row.p_value}</span><span class="status">${row.trend}<br>${row.advisory_status}</span></div>`).join(''):'<p>No statistically meaningful pattern cohorts yet. Discoveries remain advisory-only.</p>';const analogs=(((data.market_memory||{}).analogs)||[]);document.querySelector('#analogs').innerHTML=analogs.length?analogs.map(row=>`<div class="row"><strong>${row.trading_date}<br>Similarity ${row.similarity_score}</strong><span>${row.similarity_reasons.join('; ')}<br><small>Outcome: P&L ${row.outcomes.pnl}; win rate ${row.outcomes.win_rate_pct}%; patterns: ${row.pattern_outcomes.join(', ')}; counterfactuals: ${row.counterfactual_conclusions.join(', ')||'none'}</small></span><span class="status">Hypotheses: ${(row.active_hypothesis_ids||[]).join(', ')||'none'}</span></div>`).join(''):'<p>No comparable historical sessions yet. Analogs use only pre-entry features and remain advisory.</p>';document.querySelector('#review').textContent=latest.review_id?JSON.stringify(latest.analysis,null,2):'No completed review yet.';document.querySelector('#rules').innerHTML=data.rule_validations.length?data.rule_validations.map(r=>`<div class="row"><strong>${r.rule_id}</strong><span>${r.proposal}<br><small>Expectancy improvement ${r.expectancy_improvement}; trades tested ${r.trades_tested}</small></span><span class="status ${r.status==='Validated'?'validated':''}">${r.status}</span></div>`).join(''):'No recommendation records yet.'}load().catch(e=>document.querySelector('#review').textContent='Unable to load reviewer data: '+e);
</script></body></html>""")


@app.route('/spy-bot-reviewer/hypotheses', methods=['GET'])
def spy_bot_reviewer_hypothesis_lab():
    return render_template_string("""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Hypothesis Lab | McLeod Alpha Cockpit</title><style>
:root{--ink:#17212b;--muted:#5d6770;--line:#d8dee3;--paper:#f6f7f5;--panel:#fff;--accent:#087e8b;--good:#1d7a46;--warn:#ad5d09}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px Georgia,serif}.shell{max-width:1220px;margin:auto;padding:28px 20px 54px}header{border-bottom:2px solid var(--ink);padding-bottom:18px;display:flex;justify-content:space-between;align-items:end;gap:20px}h1{margin:0;font-size:32px}p{color:var(--muted)}.panel{margin-top:20px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px}.row{display:grid;grid-template-columns:190px 1fr 145px;gap:14px;padding:14px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}.meta{font:12px ui-sans-serif,sans-serif;color:var(--muted);line-height:1.55}.state{font:12px ui-sans-serif,sans-serif;font-weight:bold;color:var(--warn)}.ready{color:var(--good)}button{background:#fff;border:1px solid var(--ink);border-radius:4px;padding:7px 10px;cursor:pointer}button:disabled{opacity:.45}a{color:var(--accent)}@media(max-width:760px){.row{grid-template-columns:1fr}}
</style></head><body><main class="shell"><header><div><h1>Hypothesis Lab</h1><p>Auditable trading ideas ranked by impact, evidence quality, confidence, and remaining evidence.</p></div><a href="/spy-bot-reviewer">SPY Bot Reviewer</a></header><section class="panel"><div id="hypotheses">Loading hypotheses...</div></section></main><script>
async function promote(id){const response=await fetch('/api/spy-bot-reviewer/hypotheses/'+encodeURIComponent(id)+'/promote',{method:'POST'});const payload=await response.json();if(!response.ok){alert(payload.error||'Promotion unavailable');return}load()}async function load(){const data=await fetch('/api/spy-bot-reviewer/hypotheses').then(r=>r.json());const rows=data.hypotheses||[];document.querySelector('#hypotheses').innerHTML=rows.length?rows.map(h=>`<div class="row"><div><strong>${h.hypothesis_id}</strong><div class="meta">${h.source}<br>Revision ${h.revision}</div></div><div><strong>${h.proposal}</strong><div class="meta">Expected improvement ${h.expected_improvement}; evidence quality ${h.evidence_quality??0}; confidence target ${h.confidence_target}; support ${h.supporting_trade_ids.length}; conflict ${h.conflicting_trade_ids.length}; remaining sample ${h.remaining_sample_size??h.minimum_sample_size}</div></div><div><div class="state ${h.status==='Ready for Validation'?'ready':''}">${h.status}</div>${h.status==='Ready for Validation'?`<button onclick="promote('${h.hypothesis_id}')">Promote to validation</button>`:'<div class="meta">Manual promotion only</div>'}</div></div>`).join(''):'No hypotheses have been registered yet.'}load()
</script></body></html>""")


@app.route('/research-governance', methods=['GET'])
def research_governance_dashboard():
    return render_template_string("""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Research Governance | McLeod Alpha</title><style>
:root{--ink:#17212b;--muted:#5d6770;--line:#d8dee3;--paper:#f4f6f3;--panel:#fff;--accent:#087e8b;--good:#1d7a46;--warn:#ad5d09;--bad:#a33636}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px Georgia,serif}.shell{max-width:1280px;margin:auto;padding:28px 20px 54px}header{border-bottom:2px solid var(--ink);padding-bottom:18px;display:flex;justify-content:space-between;align-items:end;gap:20px}h1{margin:0;font-size:32px}h2{font-size:20px;margin:0 0 12px}p{color:var(--muted)}a{color:var(--accent)}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px}.panel{margin-top:14px}.label{font:12px ui-sans-serif,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.value{font-size:25px;margin-top:8px}.row{display:grid;grid-template-columns:190px 1fr 160px;gap:14px;border-top:1px solid var(--line);padding:12px 0}.row:first-child{border-top:0}.meta{font:12px ui-sans-serif,sans-serif;color:var(--muted);line-height:1.55}.state{font:12px ui-sans-serif,sans-serif;font-weight:bold;color:var(--warn)}.good{color:var(--good)}.bad{color:var(--bad)}.graph{display:flex;flex-wrap:wrap;gap:9px;align-items:center}.node{border:1px solid var(--accent);padding:8px;border-radius:4px;background:#fff;font:12px ui-sans-serif,sans-serif}.arrow{color:var(--accent)}svg{width:100%;height:130px;background:#fbfcfa;border:1px solid var(--line)}@media(max-width:760px){.cards{grid-template-columns:1fr}.row{grid-template-columns:1fr}}
</style></head><body><main class="shell"><header><div><h1>Research Governance</h1><p>Advisory subsystem performance, lifecycle accountability, and research health.</p></div><a href="/spy-bot-reviewer">SPY Bot Reviewer</a></header><section class="cards" id="summary"><div class="card">Loading governance snapshot...</div></section><section class="panel"><h2>Subsystem Performance</h2><div id="subsystems">Loading...</div></section><section class="panel"><h2>Research Pipeline</h2><div class="graph" id="graph">Loading...</div></section><section class="panel"><h2>Governance Health</h2><div id="health">Loading...</div></section><section class="panel"><h2>Trend</h2><svg viewBox="0 0 900 130" role="img" aria-label="Hypothesis lifecycle trend"><polyline id="trend" fill="none" stroke="#087e8b" stroke-width="3" points=""/></svg></section><section class="panel"><h2>Recommendation Lifecycle</h2><div id="lifecycles">Loading...</div></section></main><script>
function n(value){return value===null||value===undefined?'--':value}function esc(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]))}async function load(){const data=await fetch('/api/research-governance').then(r=>r.json());const health=data.health||{};const subsystems=data.subsystems||[];document.querySelector('#summary').innerHTML=`<div class="card"><div class="label">Governance status</div><div class="value ${health.health_status==='HEALTHY'?'good':'bad'}">${n(health.health_status)}</div></div><div class="card"><div class="label">Lifecycle records</div><div class="value">${(data.recommendation_lifecycles||[]).length}</div></div><div class="card"><div class="label">Snapshot</div><div class="value">${esc((data.snapshot_hash||'--').slice(0,10))}</div></div>`;document.querySelector('#subsystems').innerHTML=subsystems.map(row=>`<div class="row"><strong>${esc(row.subsystem)}</strong><span class="meta">Precision ${n(row.precision)} | Validation success ${n(row.validation_success_rate)} | Rejected ${n(row.rejected_recommendation_rate)} | Avg expectancy ${n(row.average_expectancy_improvement)} | Contribution ${n(row.cumulative_contribution_to_trading_performance)}</span><span class="state">${row.recommendations_generated} recommendations<br>${row.permanent_lifecycle_records} lifecycle records</span></div>`).join('')||'No subsystem records yet.';const edges=((data.dependency_graph||{}).edges||[]).filter(edge=>!String(edge.from).startsWith('hypothesis:')&&!String(edge.to).startsWith('hypothesis:'));document.querySelector('#graph').innerHTML=edges.map(edge=>`<span class="node">${esc(edge.from)}</span><span class="arrow">&#8594; ${esc(edge.type)} &#8594;</span><span class="node">${esc(edge.to)}</span>`).join('')||'No dependency edges yet.';document.querySelector('#health').innerHTML=`<div class="meta">Stale hypotheses: ${(health.stale_hypotheses||[]).join(', ')||'none'}<br>Duplicate ideas: ${(health.duplicate_ideas||[]).length}<br>Contradictory recommendations: ${(health.contradictory_recommendations||[]).length}<br>Modules failing validation: ${(health.modules_consistently_failing_validation||[]).join(', ')||'none'}</div>`;const trend=data.trend||[];const max=Math.max(1,...trend.map(row=>row.hypotheses||0));document.querySelector('#trend').setAttribute('points',trend.map((row,index)=>`${20+index*860/Math.max(1,trend.length-1)},${115-(row.hypotheses||0)*90/max}`).join(' '));document.querySelector('#lifecycles').innerHTML=(data.recommendation_lifecycles||[]).map(row=>`<div class="row"><strong>${esc(row.originating_subsystem)}</strong><span>${esc(row.proposal)}<div class="meta">Hypothesis ${esc(row.hypothesis_status)} | Rule Validation ${esc(row.rule_validation_status||'not entered')} | ${esc(row.adoption_status)}</div></span><span class="state">Expected ${n(row.expected_improvement)}<br>Adopted: ${row.adopted}</span></div>`).join('')||'No recommendation lifecycles yet.'}load().catch(error=>document.querySelector('#subsystems').textContent='Unable to load governance data: '+error)
</script></body></html>""")


@app.route('/experiments', methods=['GET'])
def experiment_dashboard():
    return render_template_string("""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Experiments | McLeod Alpha</title><style>
:root{--ink:#17212b;--muted:#5d6770;--line:#d8dee3;--paper:#f4f6f3;--panel:#fff;--accent:#087e8b;--good:#1d7a46;--warn:#ad5d09;--bad:#a33636}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px Georgia,serif}.shell{max-width:1240px;margin:auto;padding:28px 20px 54px}header{border-bottom:2px solid var(--ink);padding-bottom:18px;display:flex;justify-content:space-between;align-items:end;gap:20px}h1{margin:0;font-size:32px}p{color:var(--muted)}a{color:var(--accent)}.panel{margin-top:20px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px}.row{display:grid;grid-template-columns:180px 1fr 180px;gap:14px;padding:14px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}.meta{font:12px ui-sans-serif,sans-serif;color:var(--muted);line-height:1.55}.state{font:12px ui-sans-serif,sans-serif;font-weight:bold;color:var(--warn)}.good{color:var(--good)}.bad{color:var(--bad)}@media(max-width:760px){.row{grid-template-columns:1fr}}
</style></head><body><main class="shell"><header><div><h1>Experiment Dashboard</h1><p>Versioned replay-only protocols with sequential testing and manual-only promotion.</p></div><a href="/research-governance">Research Governance</a></header><section class="panel"><div id="experiments">Loading experiments...</div></section></main><script>
function n(value){return value===null||value===undefined?'--':value}function esc(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]))}async function load(){const data=await fetch('/api/experiments').then(r=>r.json());const rows=data.experiments||[];document.querySelector('#experiments').innerHTML=rows.length?rows.map(row=>{const interim=row.interim||{};const protocol=row.protocol||{};const provenance=row.provenance||{};return `<div class="row"><div><strong>${esc(row.experiment_id)}</strong><div class="meta">${esc(row.mode)}<br>Revision ${n(row.revision)}<br>Hypothesis ${esc(row.hypothesis_id)}</div></div><div><strong>${esc(row.status)}</strong><div class="meta">Enrollment ${n(interim.treatment_count)}/${n(protocol.sample_size_calculation)}; remaining ${n(interim.estimated_remaining_sample_size)}<br>Effect ${n(interim.effect_size)}; CI [${(interim.confidence_interval||[]).join(', ')}]; success probability ${n(interim.probability_of_success)}<br>Raw p ${n(interim.raw_p_value)}; sequential p ${n(interim.sequential_adjusted_p_value)}; alpha improvement ${n(interim.expected_alpha_improvement)}<br>Strategy ${esc(provenance.strategy_version)}; features ${esc(provenance.feature_set)}; reviewer ${esc(provenance.reviewer_version)}; prompt ${esc(provenance.prompt_version)}; memory ${esc(provenance.market_memory_version)}; schema ${esc(provenance.data_schema_version)}</div></div><div class="state ${row.status==='Concluded Success'?'good':row.status==='Concluded Failure'?'bad':''}">${esc(row.status)}<br>Manual approval required<br>${row.contaminated?'Contamination: '+esc(JSON.stringify(row.overlaps)):'No detected contamination'}</div></div>`}).join(''):'No experiments have been created yet.'}load()
</script></body></html>""")


@app.route('/api/cio/dashboard', methods=['GET'])
def api_cio_dashboard():
    from cio_dashboard import build_cio_dashboard_payload

    return jsonify(build_cio_dashboard_payload(PROJECT_ROOT))


@app.route('/api/indicator-performance', methods=['GET'])
def api_indicator_performance():
    """Return closed-trade win rates attributed to each recorded entry indicator."""
    try:
        db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
        if not db_path.exists():
            return jsonify({"minimum_sample_size": 10, "indicators": [], "closed_trades": 0})
        with sqlite3.connect(str(db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = [dict(row) for row in con.execute("""
                SELECT id, direction, exit_time, pnl, option_pnl_dollars, option_pnl_pct,
                       feature_payload, entry_diagnostic_snapshot, option_symbol,
                       broker_entry_order_id, broker_exit_order_id
                FROM trade_log
                WHERE exit_time IS NOT NULL AND TRIM(exit_time) <> ''
            """).fetchall()]
        closed_trades = _filter_synthetic_test_trade_rows(rows)
        return jsonify({"minimum_sample_size": 10, "closed_trades": len(closed_trades), "indicators": _indicator_performance_summary(closed_trades)})
    except Exception as exc:
        return jsonify({"minimum_sample_size": 10, "closed_trades": 0, "indicators": [], "error": str(exc)})


def _bot_order_ids_from_audit():
    """Return broker order IDs known to be submitted by the bot.

    Returns None when audit data is unavailable, so attribution stays unlabelled
    rather than guessing.
    """
    db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
    if not db_path.exists():
        return None

    ids = set()
    con = None
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_order_audit' LIMIT 1"
        )
        if cur.fetchone() is None:
            return None

        cur.execute("SELECT order_id FROM bot_order_audit")
        for row in cur.fetchall():
            order_id = str(row["order_id"] or "").strip()
            if order_id:
                ids.add(order_id)
    except Exception:
        return None
    finally:
        if con is not None:
            con.close()

    return ids if ids else None


def _is_manual_exit_trade(sell_event, bot_order_ids):
    """Exact attribution: Mason when exit order ID is not in bot audit."""
    if bot_order_ids is None:
        return False
    sell_id = str(sell_event.get("order_id") or "")
    if not sell_id:
        return False
    return sell_id not in bot_order_ids


def _manual_label_override(trading_date, entry_dt_et, exit_dt_et, default_label):
    """Apply user-confirmed historical manual ownership corrections."""
    if trading_date == "2026-07-15":
        # User-confirmed correction: all exits were Mason except the 3:21-3:30 trade.
        is_excluded_trade = (
            entry_dt_et.hour == 15 and entry_dt_et.minute == 21 and
            exit_dt_et.hour == 15 and exit_dt_et.minute == 30
        )
        if is_excluded_trade:
            return ""
        return "Mason"

    if trading_date == "2026-07-16":
        # User-confirmed correction: the 2:54-3:11 ET exit-button trade was manual.
        is_confirmed_manual_exit = (
            entry_dt_et.hour == 14 and entry_dt_et.minute == 54 and
            exit_dt_et.hour == 15 and exit_dt_et.minute == 11
        )
        if is_confirmed_manual_exit:
            return "Mason"

    return default_label


def _local_exit_manual_label(broker_entry_order_id, broker_exit_order_id, default_label=""):
    """Prefer the persisted trade_log label for a broker-reconstructed trade."""
    db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
    if not db_path.exists():
        return default_label

    entry_id = str(broker_entry_order_id or "")
    exit_id = str(broker_exit_order_id or "")
    if not entry_id and not exit_id:
        return default_label

    try:
        with sqlite3.connect(str(db_path)) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                """
                SELECT exit_reason, manual_label
                FROM trade_log
                WHERE COALESCE(broker_entry_order_id, '') = ?
                  AND COALESCE(broker_exit_order_id, '') = ?
                ORDER BY entry_time DESC
                LIMIT 1
                """,
                (entry_id, exit_id),
            ).fetchone()
            if row is None:
                row = con.execute(
                    """
                    SELECT exit_reason, manual_label
                    FROM trade_log
                    WHERE COALESCE(broker_exit_order_id, '') = ?
                    ORDER BY entry_time DESC
                    LIMIT 1
                    """,
                    (exit_id,),
                ).fetchone()
    except Exception:
        return default_label

    if row is None:
        return default_label

    exit_reason = str(row["exit_reason"] or "").upper()
    manual_label = str(row["manual_label"] or "").strip()
    if manual_label:
        return manual_label
    if exit_reason.startswith("MANUAL_EXIT"):
        return "Mason"
    return default_label


def _broker_filled_today_trades(trading_date: str):
    """Build completed SPY option trades directly from filled broker orders for a day."""
    account_hash = os.getenv("SCHWAB_ACCOUNT_HASH")
    if not account_hash or not trading_date:
        return []

    try:
        client = _get_broker_client()
        resp = client.get_orders_for_account(account_hash)
        resp.raise_for_status()
        orders = resp.json() or []
    except Exception:
        return []

    by_symbol = {}
    bot_order_ids = _bot_order_ids_from_audit()
    for order in orders:
        if str(order.get("status") or "") != "FILLED":
            continue

        legs = order.get("orderLegCollection") or []
        if not legs:
            continue
        leg = legs[0]
        inst = leg.get("instrument") or {}
        symbol = str(inst.get("symbol") or "")
        if inst.get("assetType") != "OPTION":
            continue
        if not symbol.startswith("SPY"):
            continue

        instruction = str(leg.get("instruction") or "")
        if instruction not in {"BUY_TO_OPEN", "SELL_TO_CLOSE", "BUY_TO_CLOSE", "SELL_TO_OPEN"}:
            continue

        when_dt = _parse_iso_datetime(order.get("closeTime") or order.get("enteredTime"))
        if when_dt is None:
            continue
        if when_dt.astimezone(EASTERN_TZ).date().isoformat() != trading_date:
            continue

        try:
            qty = int(float(leg.get("quantity") or 0))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue

        fill_price = _filled_price_from_order(order)
        if fill_price is None or fill_price <= 0:
            continue

        by_symbol.setdefault(symbol, {"buy": [], "sell": []})
        event = {
            "order_id": str(order.get("orderId") or ""),
            "time": when_dt,
            "qty": qty,
            "price": round(fill_price, 2),
            "order_type": str(order.get("orderType") or "").upper(),
            "tag": str(order.get("tag") or ""),
        }

        if instruction.startswith("BUY"):
            by_symbol[symbol]["buy"].append(event)
        else:
            by_symbol[symbol]["sell"].append(event)

    trades = []
    for symbol, sides in by_symbol.items():
        buys = sorted(sides["buy"], key=lambda x: x["time"])
        sells = sorted(sides["sell"], key=lambda x: x["time"])
        used_sells = [False] * len(sells)
        direction = _option_direction_from_symbol(symbol) or "CALL"

        for buy in buys:
            for idx, sell in enumerate(sells):
                if used_sells[idx]:
                    continue
                if buy["qty"] != sell["qty"]:
                    continue
                if sell["time"] < buy["time"]:
                    continue

                used_sells[idx] = True
                qty = buy["qty"]
                gross = (sell["price"] - buy["price"]) * qty * OPTION_CONTRACT_MULTIPLIER
                commissions = qty * OPTION_COMMISSION_PER_CONTRACT_SIDE * 2
                pnl = round(gross - commissions, 2)
                manual_label = "Mason" if _is_manual_exit_trade(sell, bot_order_ids) else ""
                entry_et = buy["time"].astimezone(EASTERN_TZ)
                exit_et = sell["time"].astimezone(EASTERN_TZ)
                manual_label = _manual_label_override(trading_date, entry_et, exit_et, manual_label)
                manual_label = _local_exit_manual_label(
                    buy.get("order_id"),
                    sell.get("order_id"),
                    manual_label,
                )
                if manual_label == "Mason":
                    exit_reason = "MANUAL_EXIT_LIMIT"

                trades.append({
                    "id": None,
                    "entry_time": buy["time"].astimezone(EASTERN_TZ).isoformat(),
                    "exit_time": sell["time"].astimezone(EASTERN_TZ).isoformat(),
                    "direction": direction,
                    "entry_price": round(buy["price"], 2),
                    "exit_price": round(sell["price"], 2),
                    "pnl": pnl,
                    "option_entry": round(buy["price"], 2),
                    "option_exit": round(sell["price"], 2),
                    "option_quantity": qty,
                    "exit_reason": classify_exit_reason(buy, sell),
                    "manual_label": manual_label,
                    "broker_entry_order_id": buy["order_id"],
                    "broker_exit_order_id": sell["order_id"],
                })
                break

    return sorted(trades, key=lambda t: str(t.get("entry_time") or ""), reverse=True)


# ============================================================================
# API Endpoints
# ============================================================================

@app.route('/api/status', methods=['GET'])
def api_status():
    """Get current bot status"""
    return jsonify(_get_cached_status_snapshot())


@app.route('/api/bot/status', methods=['GET'])
def api_status_legacy():
    """Backward-compatible status endpoint alias."""
    return jsonify(_get_cached_status_snapshot())


@app.route('/api/architecture-health', methods=['GET'])
def api_architecture_health():
    """Expose source-derived consolidation metrics for the live runtime."""
    return jsonify(build_architecture_health(PROJECT_ROOT))


def _get_cached_status_snapshot(force_refresh: bool = False):
    """Return a short-lived cached status payload to protect the hot endpoint path."""
    now_ts = time.time()
    cache_ttl = max(0.25, float(STATUS_SNAPSHOT_CACHE_SECONDS or 1.5))
    cached = _STATUS_SNAPSHOT_CACHE.get("payload")
    cached_ts = float(_STATUS_SNAPSHOT_CACHE.get("timestamp") or 0.0)
    if not force_refresh and cached is not None and (now_ts - cached_ts) < cache_ttl:
        return cached

    payload = parse_bot_status()
    _STATUS_SNAPSHOT_CACHE["timestamp"] = now_ts
    _STATUS_SNAPSHOT_CACHE["payload"] = payload
    return payload


def _code_sync_watcher_loop():
    """Keep runtime on newest synced code without manual restarts."""
    global _RUNNING_BOT_SCRIPT_SHA256

    while True:
        try:
            time.sleep(float(CODE_SYNC_CHECK_SECONDS))

            current_cc_sha = _sha256_file(Path(__file__))
            if (
                AUTO_REEXEC_ON_COCKPIT_CHANGE
                and current_cc_sha
                and _RUNNING_COCKPIT_SHA256
                and current_cc_sha != _RUNNING_COCKPIT_SHA256
            ):
                print("Code sync watcher: cockpit.py changed; reloading to newest version")
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                except Exception:
                    pass
                os.execv(sys.executable, [sys.executable] + sys.argv)

            current_bot_sha = _sha256_file(BOT_SCRIPT) if BOT_SCRIPT.exists() else None
            if (
                AUTO_RESTART_BOT_ON_SCRIPT_CHANGE
                and current_bot_sha
                and _RUNNING_BOT_SCRIPT_SHA256
                and current_bot_sha != _RUNNING_BOT_SCRIPT_SHA256
            ):
                if _is_bot_process_running():
                    print("Code sync watcher: phase3 monitor changed; restarting bot on newest script")
                    stop_bot()
                    start_result = start_bot()
                    print(f"Code sync watcher bot restart result: {start_result.get('status')} - {start_result.get('message')}")
                else:
                    # Bot is stopped; just advance expected running hash for next start.
                    _RUNNING_BOT_SCRIPT_SHA256 = current_bot_sha
        except Exception as exc:
            print(f"Code sync watcher error: {exc}")


def _ensure_code_sync_watcher_running():
    global _CODE_SYNC_THREAD
    with _CODE_SYNC_LOCK:
        if _CODE_SYNC_THREAD is not None and _CODE_SYNC_THREAD.is_alive():
            return
        _CODE_SYNC_THREAD = threading.Thread(
            target=_code_sync_watcher_loop,
            name="code-sync-watcher",
            daemon=True,
        )
        _CODE_SYNC_THREAD.start()


@app.route('/api/parity/baseline', methods=['POST'])
def api_parity_baseline():
    """Capture current runtime as parity baseline."""
    try:
        fingerprint = _runtime_fingerprint_snapshot(force_refresh=True)
        payload = {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_on_host": fingerprint.get("hostname"),
            "fingerprint": _parity_baseline_from_fingerprint(fingerprint),
        }
        _save_parity_baseline(payload)
        parity = _parity_status_snapshot()
        return jsonify({
            "status": "success",
            "message": "Parity baseline updated",
            "parity_state": parity.get("state"),
            "parity_summary": parity.get("summary"),
            "parity_issues": parity.get("issues") or [],
            "parity_baseline_path": str(parity.get("baseline_path") or PARITY_BASELINE_FILE),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to set parity baseline: {e}"}), 500


@app.route('/api/start', methods=['POST'])
def api_start():
    """Sync GitHub, restart the Cockpit, then start the bot."""
    return jsonify(start_canonical_sync_and_restart())


@app.route('/api/start-direct', methods=['POST'])
def api_start_direct():
    """Start the bot without triggering a GitHub deployment cycle."""
    return jsonify(start_bot())


@app.route('/api/go-live', methods=['POST'])
def api_go_live():
    """Run the canonical sync/restart workflow used for live deployment."""
    result = trigger_go_live()
    status_code = 200 if result.get("status") == "success" else 400
    return jsonify(result), status_code


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop the bot"""
    result = stop_bot()
    return jsonify(result)


@app.route('/api/exit-trade', methods=['POST'])
def api_exit_trade():
    """Exit an open trade, or toggle entry pause while flat."""
    try:
        status = parse_bot_status()
        if not status.get("bot_running"):
            return jsonify({"status": "error", "message": "Bot is not running"}), 400
        if status.get("mode") != "LIVE TRADING":
            return jsonify({"status": "error", "message": "EXIT TRADE is only available in LIVE TRADING mode"}), 400
        if not status.get("has_open_position"):
            pause = toggle_entry_pause_command()
            return jsonify({
                "status": "success",
                "message": "Trade entries paused; monitor remains active" if pause["paused"] else "Trade entries resumed; monitor remains active",
                "entry_paused": pause["paused"],
            })

        command = queue_exit_trade_command()
        return jsonify({
            "status": "success",
            "message": "EXIT TRADE command queued. Bot will submit the close while protection remains active.",
            "command_id": command.get("id"),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to queue EXIT TRADE: {e}"}), 500


@app.route('/api/test-bell', methods=['POST'])
def api_test_bell():
    """Trigger a bell broadcast event for all connected dashboard sessions."""
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind") or "open").strip().lower()
    event = trigger_bell_broadcast(kind=kind, source="api")
    return jsonify({"status": "success", "event": event})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    """Get last N lines of bot logs"""
    lines = request.args.get('lines', 50, type=int)
    active_log = _resolve_active_bot_log_file()

    if not active_log.exists():
        return jsonify({"logs": [], "error": "No log file found", "log_last_modified": None})
    
    try:
        with open(active_log, 'r') as f:
            all_lines = f.readlines()

        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        source_date = datetime.fromtimestamp(active_log.stat().st_mtime, tz=local_tz).date()

        filtered_lines = []
        repeated_fill_error_count = 0

        for raw_line in all_lines:
            line = raw_line.rstrip("\n")

            # Drop extremely verbose state dumps that drown out actionable logs.
            if line.startswith("DEBUG in_trade current_position = Position("):
                continue

            # Hide legacy empty reason rows so Recent Logs stay scannable.
            if line in {
                "Positives:",
                "Negatives:",
                "Penalties:",
                "Positives: None",
                "Negatives: None",
                "Penalties: None",
            }:
                continue

            # Collapse repeated fill-check API errors into a single summary line.
            if line.startswith("ERROR checking fill:"):
                repeated_fill_error_count += 1
                if repeated_fill_error_count == 1:
                    filtered_lines.append(raw_line)
                continue

            if repeated_fill_error_count > 1:
                filtered_lines.append(
                    f"... repeated fill-check errors omitted ({repeated_fill_error_count - 1} more)\n"
                )
            repeated_fill_error_count = 0

            filtered_lines.append(raw_line)

        if repeated_fill_error_count > 1:
            filtered_lines.append(
                f"... repeated fill-check errors omitted ({repeated_fill_error_count - 1} more)\n"
            )

        recent_lines = filtered_lines[-lines:]

        signal_markers = (
            "SIGNAL SUMMARY |",
            "CYCLE ",
            "════════════ MARKET ════════════",
        )
        signal_start = None
        for idx in range(len(filtered_lines) - 1, -1, -1):
            line_text = str(filtered_lines[idx] or "").strip()
            if any(line_text.startswith(marker) for marker in signal_markers):
                signal_start = idx
                break

        if signal_start is not None and not any(str(line or "").startswith("SIGNAL SUMMARY |") for line in recent_lines):
            signal_block = filtered_lines[signal_start: min(signal_start + 32, len(filtered_lines))]
            recent_lines = recent_lines + ["\n"] + signal_block

        converted_lines = []
        previous_local_dt = None
        for raw_line in recent_lines:
            converted, previous_local_dt = _format_recent_log_line_et(
                raw_line,
                source_date=source_date,
                local_tz=local_tz,
                previous_local_dt=previous_local_dt,
            )
            converted_lines.append(converted)

        log_mtime = datetime.fromtimestamp(active_log.stat().st_mtime, tz=timezone.utc).astimezone(EASTERN_TZ).isoformat()
        return jsonify({"logs": converted_lines, "log_last_modified": log_mtime})
    except Exception as e:
        return jsonify({"logs": [], "error": str(e), "log_last_modified": None})


@app.route('/api/today-trades', methods=['GET'])
def api_today_trades():
    """Get all trades and broker net P&L for the current Eastern calendar day."""
    try:
        import sqlite3
        from datetime import date
        
        db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        is_fallback_day = False
        trade_log_columns = {row[1] for row in cur.execute("PRAGMA table_info(trade_log)").fetchall()}
        if not trade_log_columns:
            return jsonify({"trades": [], "summary": {}, "error": "trade_log is unavailable"}), 503
        absorption_select = "absorption_score" if "absorption_score" in trade_log_columns else "NULL AS absorption_score"
        momentum_phase_select = "momentum_phase" if "momentum_phase" in trade_log_columns else "NULL AS momentum_phase"
        
        # First try today's date
        today = datetime.now(EASTERN_TZ).date().isoformat()
        cur.execute("""
            SELECT
                id,
                entry_time,
                exit_time,
                direction,
                option_symbol,
                CASE WHEN option_entry IS NOT NULL THEN option_entry ELSE entry_price END AS entry_price,
                CASE WHEN option_exit IS NOT NULL THEN option_exit ELSE exit_price END AS exit_price,
                CASE WHEN option_pnl_dollars IS NOT NULL THEN option_pnl_dollars ELSE pnl END AS pnl,
                exit_reason,
                option_entry,
                option_exit,
                option_quantity,
                broker_entry_order_id,
                broker_exit_order_id,
                feature_payload,
                entry_diagnostic_snapshot,
                exit_diagnostic_snapshot,
                {absorption_select},
                {momentum_phase_select}
            FROM trade_log
            WHERE substr(entry_time, 1, 10) = ?
            ORDER BY entry_time DESC
        """.format(
            absorption_select=absorption_select,
            momentum_phase_select=momentum_phase_select,
        ), (today,))
        
        trades = [dict(row) for row in cur.fetchall()]
        trades = _filter_synthetic_test_trade_rows(trades)
        trading_date = today

        # The dashboard's Today card is never allowed to roll back to a prior
        # trading day. An empty calendar day must remain an empty, zero-P&L day.
        broker_trades = _broker_transaction_trades_for_date(today)
        using_broker_trades = bool(broker_trades)
        if using_broker_trades:
            trades = broker_trades

        # Keep one row per logical trade even when executions are split.
        trades = _collapse_split_trade_rows(trades)

        # Enrich broker-derived rows with local diagnostics persisted at entry/exit.
        if trades and trading_date:
            try:
                cur.execute(
                    """
                    SELECT
                        broker_entry_order_id,
                        broker_exit_order_id,
                        direction,
                        CASE WHEN option_entry IS NOT NULL THEN option_entry ELSE entry_price END AS entry_price,
                        CASE WHEN option_exit IS NOT NULL THEN option_exit ELSE exit_price END AS exit_price,
                        exit_reason,
                        feature_payload,
                        entry_diagnostic_snapshot,
                        exit_diagnostic_snapshot,
                        {momentum_phase_select}
                    FROM trade_log
                    WHERE substr(entry_time, 1, 10) = ?
                    """.format(momentum_phase_select=momentum_phase_select),
                    (trading_date,),
                )
                diag_rows = [dict(row) for row in cur.fetchall()]

                diag_lookup = {}
                diag_by_order_ids = {}
                diag_by_entry_order_id = {}
                diag_by_exit_order_id = {}
                for row in diag_rows:
                    entry_order_id = str(row.get("broker_entry_order_id") or "")
                    exit_order_id = str(row.get("broker_exit_order_id") or "")
                    has_diag = bool(
                        row.get("feature_payload")
                        or row.get("entry_diagnostic_snapshot")
                        or row.get("exit_diagnostic_snapshot")
                    )
                    if entry_order_id or exit_order_id:
                        diag_by_order_ids.setdefault((entry_order_id, exit_order_id), []).append(row)
                    if has_diag and entry_order_id:
                        diag_by_entry_order_id.setdefault(entry_order_id, []).append(row)
                    if has_diag and exit_order_id:
                        diag_by_exit_order_id.setdefault(exit_order_id, []).append(row)

                    key = (
                        str(row.get("direction") or "").upper(),
                        round(float(row.get("entry_price") or 0.0), 2),
                        round(float(row.get("exit_price") or 0.0), 2),
                    )
                    diag_lookup.setdefault(key, []).append(row)

                for trade in trades:
                    entry_order_id = str(trade.get("broker_entry_order_id") or "")
                    exit_order_id = str(trade.get("broker_exit_order_id") or "")
                    matches = []
                    if entry_order_id or exit_order_id:
                        matches = diag_by_order_ids.get((entry_order_id, exit_order_id)) or []

                    if not matches and entry_order_id:
                        matches = diag_by_entry_order_id.get(entry_order_id) or []
                    if not matches and exit_order_id:
                        matches = diag_by_exit_order_id.get(exit_order_id) or []

                    key = (
                        str(trade.get("direction") or "").upper(),
                        round(float(trade.get("entry_price") or 0.0), 2),
                        round(float(trade.get("exit_price") or 0.0), 2),
                    )
                    if not matches:
                        matches = diag_lookup.get(key) or []
                    if not matches:
                        continue
                    matched = matches[0]
                    trade["feature_payload"] = matched.get("feature_payload")
                    trade["entry_diagnostic_snapshot"] = matched.get("entry_diagnostic_snapshot")
                    trade["exit_diagnostic_snapshot"] = matched.get("exit_diagnostic_snapshot")
                    trade["momentum_phase"] = matched.get("momentum_phase")
                    local_exit_reason = str(matched.get("exit_reason") or "").upper()
                    if local_exit_reason.startswith("MANUAL_EXIT"):
                        trade["exit_reason"] = local_exit_reason
                        trade["manual_label"] = "Mason"
            except Exception:
                pass

        verified_signatures = _broker_verified_trade_signatures(trading_date) if trading_date else None
        export_path, export_payload = _load_latest_schwab_transaction_export()
        export_snapshot_epoch = None
        if export_path and export_payload and trading_date:
            try:
                export_date = datetime.strptime(str(export_payload.get("ToDate")), "%m/%d/%Y").date().isoformat()
            except Exception:
                export_date = None
            if export_date == trading_date:
                export_snapshot_epoch = export_path.stat().st_mtime

        if verified_signatures and not using_broker_trades and trading_date == today:
            filtered_trades = []
            for trade in trades:
                broker_entry_order_id = trade.get('broker_entry_order_id')
                broker_exit_order_id = trade.get('broker_exit_order_id')
                if broker_entry_order_id or broker_exit_order_id:
                    filtered_trades.append(trade)
                    continue

                try:
                    option_symbol = str(trade.get('option_symbol') or '')
                    entry_price = round(float(trade.get('entry_price') or 0), 2)
                    exit_price = round(float(trade.get('exit_price') or 0), 2)
                    qty = int(float(trade.get('option_quantity') or 0))
                except (TypeError, ValueError):
                    continue

                if (option_symbol, entry_price, exit_price, qty) in verified_signatures:
                    filtered_trades.append(trade)
                    continue

                # If export snapshot is same-day but stale, include probable real SPY option
                # rows that were logged after that snapshot so today's dashboard stays current.
                if export_snapshot_epoch is not None and _looks_like_real_spy_option_trade(trade):
                    trade_epoch = _parse_timestamp_to_epoch(trade.get("exit_time") or trade.get("entry_time"))
                    if trade_epoch is not None and trade_epoch > export_snapshot_epoch:
                        filtered_trades.append(trade)
            trades = filtered_trades

        # If broker-verified fills are unavailable, still avoid counting known
        # synthetic placeholder symbols as real executed trades.
        if not using_broker_trades:
            trades = _filter_placeholder_trade_rows(trades)
            trades = _filter_synthetic_test_trade_rows(trades)
        
        # Calculate per-trade net cash P&L for options (includes contract multiplier and commissions).
        abs_by_entry_order_id = {}
        abs_by_exit_order_id = {}
        if trading_date:
            try:
                cur.execute(
                    """
                    SELECT broker_entry_order_id, broker_exit_order_id, absorption_score
                    FROM trade_log
                    WHERE substr(entry_time, 1, 10) = ?
                      AND absorption_score IS NOT NULL
                    """,
                    (trading_date,),
                )
                for row in cur.fetchall():
                    entry_order_id = str(row["broker_entry_order_id"] or "")
                    exit_order_id = str(row["broker_exit_order_id"] or "")
                    try:
                        abs_value = float(row["absorption_score"])
                    except (TypeError, ValueError):
                        continue
                    if entry_order_id and entry_order_id not in abs_by_entry_order_id:
                        abs_by_entry_order_id[entry_order_id] = abs_value
                    if exit_order_id and exit_order_id not in abs_by_exit_order_id:
                        abs_by_exit_order_id[exit_order_id] = abs_value
            except Exception:
                pass

        for trade in trades:
            trade['entry_time'] = _to_et_iso(trade.get('entry_time'))
            trade['exit_time'] = _to_et_iso(trade.get('exit_time'))

            # Diagnostic values for dashboard visibility.
            trend_stage = None
            entry_gate_score = None
            continuation_quality_score = None
            momentum_acceleration_score = None
            absorption_score = trade.get('absorption_score')
            confidence_score = None
            indicator_count = None
            indicator_total = None
            momentum_phase = trade.get('momentum_phase')

            snapshot_text = trade.get('entry_diagnostic_snapshot') or trade.get('feature_payload')
            if snapshot_text:
                try:
                    if isinstance(snapshot_text, dict):
                        snap = snapshot_text
                    elif isinstance(snapshot_text, str):
                        snap = json.loads(snapshot_text)
                    else:
                        snap = {}

                    # Defensive handling for double-encoded JSON payloads.
                    if isinstance(snap, str):
                        snap = json.loads(snap)

                    if not isinstance(snap, dict):
                        snap = {}

                    if not momentum_phase:
                        momentum_phase = snap.get('momentum_phase')

                    trend_stage_obj = snap.get('trend_stage') or snap.get('trend_stage_call') or snap.get('trend_stage_put')
                    if isinstance(trend_stage_obj, dict):
                        trend_stage = trend_stage_obj.get('stage')
                    elif trend_stage_obj is not None:
                        trend_stage = trend_stage_obj

                    direction_upper = str(trade.get('direction') or '').upper()
                    if direction_upper == 'PUT':
                        entry_gate_score = snap.get('put_score')
                    else:
                        entry_gate_score = snap.get('call_score')
                    if entry_gate_score is None:
                        entry_gate_score = snap.get('entry_score')

                    continuation_quality_score = snap.get('continuation_quality_score')
                    if continuation_quality_score is None:
                        continuation_quality_score = (
                            (snap.get('continuation_quality_put') or {}).get('score')
                            if direction_upper == 'PUT'
                            else (snap.get('continuation_quality_call') or {}).get('score')
                        )
                    momentum_acceleration_score = (
                        snap.get('momentum_acceleration_score')
                        if snap.get('momentum_acceleration_score') is not None
                        else (
                            (snap.get('momentum_acceleration_put') or {}).get('score')
                            if direction_upper == 'PUT'
                            else (snap.get('momentum_acceleration_call') or {}).get('score')
                        )
                    )
                    snap_absorption_score = snap.get('absorption_score')
                    if snap_absorption_score is not None:
                        absorption_score = snap_absorption_score
                    if absorption_score is None:
                        absorption_score = (snap.get('absorption_score_put') or {}).get('score') if direction_upper == 'PUT' else (snap.get('absorption_score_call') or {}).get('score')
                    confidence_score = (
                        snap.get('confidence_score')
                        if snap.get('confidence_score') is not None
                        else (
                            (snap.get('confidence_score_put') or {}).get('score')
                            if direction_upper == 'PUT'
                            else (snap.get('confidence_score_call') or {}).get('score')
                        )
                    )

                    cq_by_side = {}
                    if direction_upper == 'PUT':
                        cq_by_side = snap.get('continuation_quality_put') or {}
                    else:
                        cq_by_side = snap.get('continuation_quality_call') or {}

                    if not isinstance(cq_by_side, dict):
                        cq_by_side = {}

                    indicator_count = cq_by_side.get('indicators_passed')
                    indicator_total = cq_by_side.get('indicators_total')

                    # Live entry snapshots record the selected-side checklist
                    # at the root; side-specific fields are legacy fallbacks.
                    if indicator_count is None:
                        indicator_count = snap.get('indicator_count')
                    if indicator_total is None:
                        indicator_total = snap.get('indicator_total')
                    checklist = snap.get('checklist')
                    if isinstance(checklist, dict):
                        if indicator_count is None:
                            indicator_count = checklist.get('passed')
                        if indicator_total is None:
                            indicator_total = checklist.get('total')

                    # Backward-compatible fallback for older snapshots.
                    if indicator_count is None or indicator_total is None:
                        primary = (cq_by_side.get('components') or {}).get('primary_indicators')
                        if isinstance(primary, dict):
                            indicator_count = primary.get('passed', indicator_count)
                            indicator_total = primary.get('total', indicator_total)
                except Exception:
                    pass

            if (
                trend_stage is None
                and entry_gate_score is None
                and continuation_quality_score is None
                and momentum_acceleration_score is None
                and confidence_score is None
            ):
                fallback_scores = _fallback_scores_from_calibration(
                    trade.get('entry_time'),
                    trade.get('direction'),
                )
                if not fallback_scores:
                    fallback_scores = _fallback_scores_from_recent_logs(
                        trade.get('entry_time'),
                        trade.get('direction'),
                    )
                trend_stage = fallback_scores.get('trend_stage', trend_stage)
                entry_gate_score = fallback_scores.get('entry_gate_score', entry_gate_score)
                continuation_quality_score = fallback_scores.get('continuation_quality_score', continuation_quality_score)
                momentum_acceleration_score = fallback_scores.get('momentum_acceleration_score', momentum_acceleration_score)
                confidence_score = fallback_scores.get('confidence_score', confidence_score)
                indicator_count = fallback_scores.get('indicator_count', indicator_count)
                indicator_total = fallback_scores.get('indicator_total', indicator_total)

            if not momentum_phase:
                phase_by_stage = {
                    1: 'INITIATION',
                    2: 'EARLY_CONTINUATION',
                    3: 'ESTABLISHED',
                    4: 'MATURE',
                    5: 'LATE_EXHAUSTION',
                }
                try:
                    momentum_phase = phase_by_stage.get(int(trend_stage))
                except (TypeError, ValueError):
                    momentum_phase = None

            if absorption_score is None:
                entry_order_id = str(trade.get('broker_entry_order_id') or '')
                exit_order_id = str(trade.get('broker_exit_order_id') or '')
                if entry_order_id in abs_by_entry_order_id:
                    absorption_score = abs_by_entry_order_id.get(entry_order_id)
                elif exit_order_id in abs_by_exit_order_id:
                    absorption_score = abs_by_exit_order_id.get(exit_order_id)

            trade['trend_stage'] = trend_stage
            trade['entry_gate_score'] = entry_gate_score
            trade['continuation_quality_score'] = continuation_quality_score
            trade['momentum_acceleration_score'] = momentum_acceleration_score
            trade['absorption_score'] = absorption_score
            trade['confidence_score'] = confidence_score
            trade['indicator_count'] = indicator_count
            trade['indicator_total'] = indicator_total
            trade['momentum_phase'] = str(momentum_phase or '').upper() or None

            option_entry = trade.get('option_entry')
            option_exit = trade.get('option_exit')
            option_qty = trade.get('option_quantity')
            option_symbol = str(trade.get('option_symbol') or '').strip()
            strike_match = re.search(r'\d{6}[CP](\d{8})$', option_symbol)
            trade['strike_price'] = int(strike_match.group(1)) / 1000 if strike_match else None

            try:
                qty_value = float(option_qty or 0)
                trade['contracts'] = int(round(qty_value)) if abs(qty_value - round(qty_value)) < 1e-9 else qty_value
            except (TypeError, ValueError):
                trade['contracts'] = None

            if str(trade.get('pnl_source') or '').lower() == 'broker_cash':
                trade['pnl'] = round(float(trade.get('pnl', 0) or 0), 2)
                try:
                    qty = max(0, float(option_qty or 0))
                    entry_px = float(option_entry or 0)
                    total_purchase_price = entry_px * qty * OPTION_CONTRACT_MULTIPLIER
                    trade['pnl_pct'] = round((trade['pnl'] / total_purchase_price) * 100, 1) if total_purchase_price > 0 else None
                except (TypeError, ValueError):
                    trade['pnl_pct'] = None
            elif option_entry is not None and option_exit is not None and option_qty is not None:
                try:
                    qty = max(0, float(option_qty))
                    entry_px = float(option_entry)
                    exit_px = float(option_exit)
                    gross = (exit_px - entry_px) * qty * OPTION_CONTRACT_MULTIPLIER
                    commissions = qty * OPTION_COMMISSION_PER_CONTRACT_SIDE * 2
                    trade['pnl'] = round(gross - commissions, 2)
                    total_purchase_price = entry_px * qty * OPTION_CONTRACT_MULTIPLIER
                    trade['pnl_pct'] = round((trade['pnl'] / total_purchase_price) * 100, 1) if total_purchase_price > 0 else None
                except (TypeError, ValueError):
                    trade['pnl'] = round(float(trade.get('pnl', 0) or 0), 2)
                    trade['pnl_pct'] = None
            else:
                trade['pnl'] = round(float(trade.get('pnl', 0) or 0), 2)
                try:
                    entry_px = float(trade.get('entry_price') or 0)
                    total_purchase_price = entry_px * OPTION_CONTRACT_MULTIPLIER
                    trade['pnl_pct'] = round((trade['pnl'] / total_purchase_price) * 100, 1) if total_purchase_price > 0 else None
                except (TypeError, ValueError):
                    trade['pnl_pct'] = None

            # These are implementation details, not needed by the UI payload.
            trade.pop('option_entry', None)
            trade.pop('option_exit', None)
            trade.pop('option_quantity', None)
            trade.pop('option_symbol', None)
            trade.pop('broker_entry_order_id', None)
            trade.pop('broker_exit_order_id', None)
            trade.pop('feature_payload', None)
            trade.pop('entry_diagnostic_snapshot', None)
            trade.pop('exit_diagnostic_snapshot', None)
            trade.pop('pnl_source', None)

        # Calculate summary from net cash P&L values.
        total_pnl = sum(float(t.get('pnl', 0) or 0) for t in trades)
        if trading_date == today:
            # Status is the canonical Schwab transaction netAmount aggregation for
            # Today/WTD/MTD/YTD, including broker commissions and fees.
            try:
                status_today_pnl = float(parse_bot_status().get('todays_pnl'))
                total_pnl = status_today_pnl
            except Exception:
                schwab_day_total = _schwab_transaction_day_net_pnl(trading_date)
                if schwab_day_total is not None:
                    total_pnl = float(schwab_day_total)
        else:
            schwab_day_total = _schwab_transaction_day_net_pnl(trading_date)
            if schwab_day_total is not None:
                total_pnl = float(schwab_day_total)
        total_pnl_points = sum(
            float(t.get('pnl_pct') or 0.0)
            for t in trades
            if t.get('pnl_pct') is not None
        )
        purchase_notionals = []
        for t in trades:
            try:
                contracts = float(t.get('contracts') or 0)
                entry_px = float(t.get('entry_price') or 0)
                notional = entry_px * contracts * OPTION_CONTRACT_MULTIPLIER
                if notional > 0:
                    purchase_notionals.append(notional)
            except (TypeError, ValueError):
                continue

        average_purchase = (sum(purchase_notionals) / len(purchase_notionals)) if purchase_notionals else 0.0
        total_return_pct = ((float(total_pnl) / float(average_purchase)) * 100.0) if average_purchase > 0 else 0.0
        win_count = sum(1 for t in trades if float(t.get('pnl', 0) or 0) > 0)
        loss_count = sum(1 for t in trades if float(t.get('pnl', 0) or 0) < 0)

        summary = {
            "total_trades": len(trades),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_points": round(total_pnl_points, 1),
            "average_purchase": round(average_purchase, 2),
            "total_return_pct": round(total_return_pct, 1),
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round((win_count / len(trades) * 100) if trades else 0, 1),
        }

        try:
            _log_daily_trades_chart_snapshot(trading_date, trades, summary, is_fallback_day)
        except Exception:
            pass
        
        con.close()
        
        return jsonify({
            "trades": trades,
            "trading_date": trading_date,
            "is_fallback_day": is_fallback_day,
            "summary": summary,
        })
    except Exception as e:
        return jsonify({"trades": [], "summary": {}, "error": str(e), "trading_date": None})


def _band_from_value(value, edges, labels):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "unknown"
    for idx, edge in enumerate(edges):
        if v < edge:
            return labels[idx]
    return labels[-1]


def _update_attribution_bucket(buckets, key, pnl):
    if key not in buckets:
        buckets[key] = {"count": 0, "wins": 0, "losses": 0, "net_pnl": 0.0, "win_rate": 0.0}
    buckets[key]["count"] += 1
    buckets[key]["net_pnl"] += float(pnl)
    if float(pnl) > 0:
        buckets[key]["wins"] += 1
    elif float(pnl) < 0:
        buckets[key]["losses"] += 1


@app.route('/api/trade-attribution-summary', methods=['GET'])
def api_trade_attribution_summary():
    """Aggregate win rate and net P&L by Stage/CQ/MAS/Confidence bands."""
    try:
        db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
        if not db_path.exists():
            return jsonify({"trading_date": None, "summary": {}, "by_stage": {}, "by_cq_band": {}, "by_mas_band": {}, "by_confidence_band": {}})

        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        requested_date = (request.args.get("date") or "").strip()
        if requested_date:
            trading_date = requested_date
        else:
            today = datetime.now(EASTERN_TZ).date().isoformat()
            cur.execute("SELECT COUNT(*) AS c FROM trade_log WHERE substr(entry_time, 1, 10)=?", (today,))
            has_today = int((cur.fetchone() or {"c": 0})["c"] or 0) > 0
            if has_today:
                trading_date = today
            else:
                cur.execute("SELECT MAX(substr(entry_time, 1, 10)) AS d FROM trade_log")
                row = cur.fetchone()
                trading_date = row["d"] if row else None

        if not trading_date:
            con.close()
            return jsonify({"trading_date": None, "summary": {}, "by_stage": {}, "by_cq_band": {}, "by_mas_band": {}, "by_confidence_band": {}})

        cur.execute(
            """
            SELECT
                direction,
                option_symbol,
                CASE WHEN option_pnl_dollars IS NOT NULL THEN option_pnl_dollars ELSE pnl END AS pnl,
                feature_payload,
                entry_diagnostic_snapshot
            FROM trade_log
            WHERE substr(entry_time, 1, 10)=?
            ORDER BY entry_time DESC
            """,
            (trading_date,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        con.close()

        # Keep attribution consistent with today-trades canonicalization.
        rows = _filter_placeholder_trade_rows(rows)

        by_stage = {}
        by_cq = {}
        by_mas = {}
        by_conf = {}
        total_pnl = 0.0

        for row in rows:
            pnl = float(row.get("pnl") or 0.0)
            total_pnl += pnl

            snapshot_text = row.get("entry_diagnostic_snapshot") or row.get("feature_payload")
            snap = {}
            if snapshot_text:
                try:
                    snap = json.loads(snapshot_text)
                except Exception:
                    snap = {}

            stage_obj = snap.get("trend_stage") or snap.get("trend_stage_call") or snap.get("trend_stage_put")
            if isinstance(stage_obj, dict):
                stage_val = stage_obj.get("stage")
            else:
                stage_val = stage_obj
            try:
                stage_key = f"S{int(stage_val)}" if stage_val is not None else "unknown"
            except Exception:
                stage_key = "unknown"

            cq_val = snap.get("continuation_quality_score")
            if cq_val is None:
                direction = str(row.get("direction") or "").upper()
                if direction == "PUT":
                    cq_val = (snap.get("continuation_quality_put") or {}).get("score")
                else:
                    cq_val = (snap.get("continuation_quality_call") or {}).get("score")

            mas_val = snap.get("momentum_acceleration_score")
            if mas_val is None:
                direction = str(row.get("direction") or "").upper()
                if direction == "PUT":
                    mas_val = (snap.get("momentum_acceleration_put") or {}).get("score")
                else:
                    mas_val = (snap.get("momentum_acceleration_call") or {}).get("score")

            conf_val = snap.get("confidence_score")
            if conf_val is None:
                direction = str(row.get("direction") or "").upper()
                if direction == "PUT":
                    conf_val = (snap.get("confidence_score_put") or {}).get("score")
                else:
                    conf_val = (snap.get("confidence_score_call") or {}).get("score")

            cq_band = _band_from_value(cq_val, [2.0, 3.0, 4.0, 5.0], ["<2", "2-3", "3-4", "4-5", "5+"])
            mas_band = _band_from_value(mas_val, [2.0, 3.0, 4.0, 5.0], ["<2", "2-3", "3-4", "4-5", "5+"])
            conf_band = _band_from_value(conf_val, [2.0, 2.5, 3.0, 4.0, 5.0], ["<2", "2-2.5", "2.5-3", "3-4", "4-5", "5+"])

            _update_attribution_bucket(by_stage, stage_key, pnl)
            _update_attribution_bucket(by_cq, cq_band, pnl)
            _update_attribution_bucket(by_mas, mas_band, pnl)
            _update_attribution_bucket(by_conf, conf_band, pnl)

        for section in (by_stage, by_cq, by_mas, by_conf):
            for key, stats in section.items():
                stats["net_pnl"] = round(float(stats["net_pnl"]), 2)
                stats["win_rate"] = round((stats["wins"] / stats["count"] * 100.0) if stats["count"] else 0.0, 1)

        return jsonify(
            {
                "trading_date": trading_date,
                "summary": {
                    "total_trades": len(rows),
                    "net_pnl": round(total_pnl, 2),
                },
                "by_stage": by_stage,
                "by_cq_band": by_cq,
                "by_mas_band": by_mas,
                "by_confidence_band": by_conf,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e), "trading_date": None, "summary": {}, "by_stage": {}, "by_cq_band": {}, "by_mas_band": {}, "by_confidence_band": {}})


# ============================================================================
# Dashboard UI
# ============================================================================

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPY Options Trader Cockpit 1.4</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: Calibri, Candara, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 12px;
        }
        
        .container {
            --hero-stack-gap: 12px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 1000px;
            width: 100%;
            padding: var(--hero-stack-gap) 18px 18px;
        }
        
        .title-rockets {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            width: 100%;
        }
        
        .header p {
            color: #666;
            font-size: 14px;
        }

        .canonical-banner {
            margin: 8px auto 0;
            padding: 8px 10px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 700;
            line-height: 1.35;
            max-width: 860px;
        }

        .canonical-banner.canonical {
            background: #eaf8ec;
            border: 1px solid #b8e3bf;
            color: #1f6a2e;
        }

        .canonical-banner.noncanonical {
            background: #fff3cd;
            border: 1px solid #ffe69c;
            color: #8a6d00;
        }

        .canonical-banner a {
            color: inherit;
            font-weight: 800;
        }
        
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 12px;
            margin-bottom: 14px;
        }

        .primary-status-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }

        .primary-status-grid .status-card {
            text-align: center;
        }

        #statusGrid.position-flat {
            grid-template-columns: repeat(6, minmax(0, 1fr));
        }

        #statusGrid.position-flat #currentPositionCard {
            display: none;
        }

        #statusGrid.position-flat #callIndicatorsCard,
        #statusGrid.position-flat #trendCard,
        #statusGrid.position-flat #putIndicatorsCard {
            grid-column: span 2;
        }

        #trendCard {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }

        #trendStatus {
            width: 100%;
        }

        #statusGrid.position-flat #wtdPnlCard,
        #statusGrid.position-flat #mtdPnlCard,
        #statusGrid.position-flat #ytdPnlCard {
            grid-column: span 2;
        }

          /* An active position replaces the six summary cards with one focused view.
              The normal grid returns as soon as the broker-reported position closes. */
        #statusGrid.position-focus-active .position-secondary-card {
            display: none;
        }

        #statusGrid.position-focus-active #currentPositionCard {
            grid-column: 1 / -1;
            min-height: 220px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        #statusGrid.position-focus-active #currentPositionCard .position-summary-main,
        #statusGrid.position-focus-active #currentPositionCard .position-summary-pnl,
        #statusGrid.position-focus-active #currentPositionCard .position-summary-stop,
        #statusGrid.position-focus-active #currentPositionCard .position-stat-label,
        #statusGrid.position-focus-active #currentPositionCard .position-stat-value,
        #statusGrid.position-focus-active #currentPositionCard .position-candle-count {
            font-size: 15px;
            line-height: 1.3;
        }

        .position-stats-grid {
            display: none;
            width: min(100%, 560px);
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            text-align: center;
        }

        #statusGrid.position-focus-active .position-stats-grid {
            display: grid;
        }

        .position-stat-column {
            display: grid;
            gap: 8px;
        }

        #statusGrid.position-focus-active #currentPositionSummary {
            gap: 0;
        }

        .position-stat {
            min-width: 0;
        }

        .position-stat-label {
            color: #59636e;
            font-size: 11px;
            font-weight: 700;
        }

        .position-stat-value {
            color: #1f2933;
            font-size: 15px;
            font-weight: 700;
            line-height: 1.3;
        }

        .position-candle-count {
            color: #1f2933;
            font-size: 18px;
            font-weight: 700;
            line-height: 1.3;
        }

        @media (max-width: 560px) {
            .position-stats-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        
        .status-card {
            background: #f8f9fa;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }

        .architecture-health-summary {
            color: #4a5568;
            font-size: 12px;
            line-height: 1.4;
            margin: 0;
        }

        .architecture-health-score {
            color: #1f2937;
            font-size: 22px;
            font-weight: 700;
            margin: 4px 0 8px;
        }

        .architecture-health-blockers {
            color: #4a5568;
            font-size: 11px;
            line-height: 1.35;
            margin: 8px 0 0;
            padding-left: 16px;
            text-align: left;
        }

        .architecture-evidence {
            margin-bottom: 14px;
        }

        .architecture-evidence summary {
            color: #34495e;
            cursor: pointer;
            font-size: 12px;
            font-weight: 700;
        }

        .architecture-evidence-list {
            color: #4a5568;
            font-size: 11px;
            line-height: 1.45;
            margin: 8px 0 0;
            max-height: 180px;
            overflow-y: auto;
            padding-left: 18px;
        }

        .indicator-performance-wrap {
            margin: 0 0 14px;
            border: 1px solid #d8dee7;
            border-radius: 8px;
            padding: 12px;
            background: #fbfcfe;
        }

        .indicator-performance-list {
            display: grid;
            gap: 0;
        }

        .indicator-performance-columns,
        .indicator-performance-row {
            display: grid;
            grid-template-columns: minmax(145px, 1.5fr) minmax(145px, 1fr) minmax(92px, 0.7fr) minmax(150px, 1.1fr);
            align-items: center;
            gap: 10px;
        }

        .indicator-performance-columns {
            color: #607083;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.04em;
            padding: 0 0 4px;
            text-transform: uppercase;
        }

        .indicator-performance-row {
            padding: 6px 0;
            border-top: 1px solid #e6eaf0;
        }

        .indicator-performance-row:first-child {
            border-top: 0;
        }

        .indicator-performance-name {
            color: #273142;
            font-size: 12px;
            font-weight: 400;
            overflow-wrap: anywhere;
        }

        .indicator-performance-stats {
            color: #4f5d70;
            font-size: 11px;
            line-height: 1.4;
        }

        .indicator-performance-stats strong { color: #273142; }
        .indicator-performance-wins { color: #1f7a41; font-weight: 700; }
        .indicator-performance-losses { color: #b23a3a; font-weight: 700; }
        .indicator-performance-average.positive { color: #1f7a41; }
        .indicator-performance-average.negative { color: #b23a3a; }
        .indicator-performance-guidance { font-weight: 700; }
        .indicator-performance-guidance.review { color: #b23a3a; }
        .indicator-performance-guidance.candidate { color: #1f7a41; }
        .indicator-performance-guidance.collect { color: #9a6b0d; }

        .status-card.position-call {
            background: #eefaf1;
            border-color: #7ed6a0;
        }

        .status-card.position-put {
            background: #fff1f1;
            border-color: #f4a7a3;
        }

        .status-card.trade-pnl-positive {
            background: #eefaf1;
            border-color: #7ed6a0;
        }

        .status-card.trade-pnl-negative {
            background: #fff1f1;
            border-color: #f4a7a3;
        }

        .status-card.pnl-positive {
            background: #eefaf1;
            border-color: #7ed6a0;
        }

        .status-card.indicator-qualified {
            background: #eefaf1;
            border-color: #7ed6a0;
        }

        .status-card.pnl-negative {
            background: #fff1f1;
            border-color: #f4a7a3;
        }

        .status-card.pnl-neutral {
            background: #f8f9fa;
            border-color: #ddd;
        }

        .status-card.position-neutral {
            background: #f8f9fa;
            border-color: #ddd;
        }

        .position-summary-main {
            font-size: 16px;
            font-weight: 600;
            color: #333;
        }

        .position-summary-main.success { color: #28a745; }
        .position-summary-main.error { color: #dc3545; }
        .position-summary-main.warning { color: #ffc107; }
        .position-summary-main.info { color: #0066cc; }

        .position-summary-pnl {
            margin-top: 5px;
            font-size: 12px;
            line-height: 1.2;
            font-weight: 600;
        }

        .position-summary-pnl.success { color: #28a745; }
        .position-summary-pnl.error { color: #dc3545; }
        .position-summary-pnl.info { color: #0066cc; }

        .position-summary-stop {
            margin-top: 5px;
            font-size: 11px;
            line-height: 1.2;
            font-weight: 600;
            color: #495057;
        }

        .position-summary-stop.active { color: #1f2933; }
        
        .status-card h3 {
            color: #666;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 6px;
            letter-spacing: 0.7px;
        }
        
        .status-value {
            font-size: 16px;
            font-weight: 600;
            color: #333;
        }

        .status-value.compound-check {
            display: grid;
            gap: 2px;
            font-size: 13px;
            line-height: 1.2;
        }
        
        .status-value.success { color: #28a745; }
        .status-value.error { color: #dc3545; }
        .status-value.warning { color: #ffc107; }
        .status-value.info { color: #0066cc; }

        .trade-summary-value.total-pnl-positive { color: #28a745; }
        .trade-summary-value.total-pnl-negative { color: #dc3545; }
        .trade-summary-value.total-pnl-neutral { color: #999; }
        .trade-summary-value.total-pnl-today-neutral { color: #0066cc; }

        .trade-summary-card.winning {
            background: #eefaf1;
            border-color: #7ed6a0;
            border-left-color: #28a745;
        }

        .trade-summary-card.losing {
            background: #fff1f1;
            border-color: #f4a7a3;
            border-left-color: #dc3545;
        }

        .trade-entry-banner {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            align-items: center;
            gap: 8px;
            border-radius: 10px;
            padding: 10px 12px;
            margin-bottom: var(--hero-stack-gap);
            border: 1px solid transparent;
        }

        .trade-entry-banner .banner-title {
            color: #333;
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 0.6px;
            text-align: center;
            white-space: nowrap;
        }

        .trade-entry-banner .banner-price-slot {
            min-width: 0;
            text-align: center;
            white-space: nowrap;
        }

        .trade-entry-banner .mobile-price-rocket {
            display: none;
        }

        .trade-entry-banner .banner-price {
            font-weight: 900;
        }

        .trade-entry-banner .banner-pct {
            font-weight: 900;
        }

        .trade-entry-banner .banner-tone-up {
            color: #1f8f3a;
        }

        .trade-entry-banner .banner-tone-down {
            color: #c62828;
        }

        .trade-entry-banner .banner-tone-flat {
            color: inherit;
        }

        .trade-entry-banner .red-stock-icon {
            color: #c62828;
            font-weight: 900;
        }

        .trade-entry-banner .trend-tone-neutral,
        #trendStatus .trend-tone-neutral {
            color: #1565c0;
        }

        .trade-entry-banner .trend-tone-bearish,
        #trendStatus .trend-tone-bearish {
            color: #c62828;
        }

        .trade-entry-banner .trend-tone-bullish,
        #trendStatus .trend-tone-bullish {
            color: #1f8f3a;
        }

        .trade-entry-banner .banner-meta {
            display: flex;
            align-items: center;
            justify-self: center;
            gap: 6px;
            text-align: right;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.2px;
            opacity: 0.95;
            line-height: 1.2;
        }

        .trade-entry-banner .banner-meta-left {
            display: inline;
        }

        .trade-entry-banner .banner-meta-divider {
            display: none;
        }

        .trade-entry-banner .banner-meta-divider.show {
            display: inline;
        }

        .trade-entry-banner .banner-meta-right {
            display: inline;
            font-size: inherit;
            font-weight: inherit;
            letter-spacing: inherit;
            text-transform: none;
            white-space: nowrap;
        }

        .trade-entry-banner .banner-meta-right .quote-source {
            font-weight: 700;
        }

        .trade-entry-banner .banner-meta-right .quote-source.live {
            color: #1f8f3a !important;
        }

        .trade-entry-banner .banner-meta-right .quote-source.mixed {
            color: #0b4ea2 !important;
        }

        .trade-entry-banner .banner-meta-right .quote-source.stale {
            color: #b71c1c !important;
        }

        .trade-entry-banner .banner-meta-right .quote-source.unknown {
            color: #6c757d !important;
        }

        .trade-entry-banner .banner-meta-right.stale {
            color: #b71c1c;
            font-weight: 700;
        }

        .trade-entry-banner.enabled {
            background: #e9f8ef;
            border-color: #7ed6a0;
            color: #1e7e34;
        }

        .trade-entry-banner.disabled {
            background: #fdecea;
            border-color: #f4a7a3;
            color: #b71c1c;
        }

        .trade-entry-banner.after-hours {
            background: #e8f1ff;
            border-color: #8cb9ff;
            color: #0b4ea2;
        }
        
        .trades-actions {
            display: grid;
            grid-template-columns: minmax(150px, 1fr) minmax(180px, 1.25fr) minmax(150px, 1fr);
            gap: 8px;
            align-items: stretch;
            margin-bottom: 14px;
        }

        .trades-actions .trade-summary-card {
            margin: 0;
        }

        .bot-toggle.running { background: #dc3545; color: white; }
        .bot-toggle.stopped { background: #28a745; color: white; }

        button {
            padding: 9px 14px;
            font-size: 13px;
            font-weight: 600;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .btn-primary {
            background: #28a745;
            color: white;
        }
        .btn-primary:hover:not(:disabled) {
            background: #218838;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(40, 167, 69, 0.3);
        }
        
        .btn-info {
            background: #007bff;
            color: white;
        }
        .btn-info:hover:not(:disabled) {
            background: #0056b3;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 123, 255, 0.3);
        }
        
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        .btn-danger:hover:not(:disabled) {
            background: #c82333;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(220, 53, 69, 0.3);
        }
        
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        .btn-secondary:hover:not(:disabled) {
            background: #5a6268;
            transform: translateY(-2px);
        }
        
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .message {
            padding: 10px;
            border-radius: 6px;
            margin-bottom: 12px;
            display: none;
        }
        
        .message.show { display: block; }
        .message.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .message.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        
        .logs {
            background: #1e1e1e;
            color: #00ff00;
            font-size: 11px;
            padding: 10px;
            border-radius: 6px;
            max-height: 240px;
            overflow-y: auto;
            margin-top: 12px;
        }

        .logs pre {
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }
        
        .logs-title {
            color: #999;
            font-weight: 600;
            margin-bottom: 6px;
        }

        .logs-meta {
            color: #aaa;
            font-size: 10px;
            margin-left: 6px;
            font-weight: 400;
        }
        
        .trades-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            font-size: 12px;
        }

        .trades-table-wrap {
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
        
        .trades-table thead {
            background: #f8f9fa;
            border-bottom: 2px solid #ddd;
        }
        
        .trades-table th {
            padding: 6px;
            text-align: center;
            font-weight: 600;
            color: #666;
            text-transform: uppercase;
            font-size: 10px;
        }
        
        .trades-table td {
            padding: 6px;
            text-align: center;
            border-bottom: 1px solid #eee;
        }
        
        .trades-table tr:hover {
            background: #f8f9fa;
        }
        
        .trade-direction.CALL { color: #28a745; }
        .trade-direction.PUT { color: #dc3545; }
        
        .trade-pnl.positive { color: #28a745; font-weight: 600; }
        .trade-pnl.negative { color: #dc3545; font-weight: 600; }
        .trade-pnl.neutral { color: #999; }
        
        .trades-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 8px;
            margin-bottom: 8px;
        }
        
        .trade-summary-card {
            background: #f8f9fa;
            border: 1px solid #ddd;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }
        
        .trade-summary-card h4 {
            color: #666;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 6px;
            letter-spacing: 0.7px;
        }
        
        .trade-summary-value {
            font-size: 16px;
            font-weight: 600;
            color: #333;
        }
        
        .trade-summary-card.neutral {
            background: #f8f9fa;
            border-color: #ddd;
        }

        .exec-quality-wrap {
            margin-bottom: 12px;
        }

        .exec-quality-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 8px;
        }

        .exec-quality-card {
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            padding: 9px;
            border-radius: 4px;
        }

        .exec-quality-card h4 {
            color: #666;
            font-size: 10px;
            text-transform: uppercase;
            margin-bottom: 4px;
            letter-spacing: 0.4px;
        }

        .exec-quality-goal {
            display: inline-block;
            margin-top: 3px;
            padding: 1px 7px;
            border-radius: 999px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.2px;
        }

        .exec-quality-goal.success {
            background: #e9f8ef;
            color: #1e7e34;
        }

        .exec-quality-goal.error {
            background: #fdecea;
            color: #b71c1c;
        }

        .exec-quality-value {
            font-size: 16px;
            font-weight: 700;
            color: #333;
        }

        .exec-quality-sub {
            margin-top: 2px;
            font-size: 11px;
            color: #666;
            line-height: 1.25;
            white-space: pre-line;
        }

        .exec-quality-sub.success { color: #28a745; }
        .exec-quality-sub.error { color: #dc3545; }
        
        .no-trades {
            text-align: center;
            padding: 20px;
            color: #999;
        }

        .no-trades-today-banner {
            background: #fff3cd;
            border: 1px solid #ffe69c;
            color: #856404;
            border-radius: 6px;
            padding: 8px 10px;
            margin-bottom: 8px;
            font-size: 12px;
            font-weight: 600;
            text-align: center;
        }
        
        .spinner {
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid #f3f3f3;
            border-top: 2px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .last-update {
            text-align: right;
            color: #999;
            font-size: 11px;
            margin-top: 12px;
        }

        .connectivity-card {
            text-align: left;
        }

        .connectivity-main {
            font-size: 17px;
            font-weight: 700;
            line-height: 1.2;
        }

        .connectivity-main.success { color: #1e7e34; }
        .connectivity-main.warning { color: #a25a00; }
        .connectivity-main.error { color: #b71c1c; }
        .connectivity-main.info { color: #0066cc; }

        .connectivity-summary-strip {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            flex-wrap: nowrap;
            margin-bottom: 6px;
        }

        .connectivity-summary-strip .connectivity-main {
            font-size: 16px;
            margin: 0;
            white-space: nowrap;
            text-align: center;
            flex: 1 1 auto;
        }

        .connectivity-summary-meta {
            flex: 0 0 auto;
            font-size: 10px;
            line-height: 1.25;
            color: #56616b;
            white-space: nowrap;
        }

        .connectivity-summary-meta.left {
            text-align: left;
        }

        .connectivity-summary-meta.right {
            text-align: right;
        }

        .connectivity-sub {
            margin-top: 6px;
            font-size: 11px;
            line-height: 1.3;
            color: #555;
        }

        .connectivity-alert {
            margin-top: 6px;
            padding: 5px 7px;
            border-radius: 6px;
            font-size: 10px;
            font-weight: 600;
            line-height: 1.25;
            display: none;
        }

        .connectivity-alert.warn {
            display: block;
            background: #fff3cd;
            border: 1px solid #ffe69c;
            color: #8a6d00;
        }

        .connectivity-chart {
            margin-top: 6px;
            height: 30px;
            border: 1px solid #e2e6ea;
            border-radius: 6px;
            background: #fff;
            padding: 3px;
            display: flex;
            align-items: flex-end;
            gap: 2px;
            overflow: hidden;
            width: 100%;
        }

        .connectivity-chart-large {
            height: 46px;
            margin-top: 0;
        }

        .connectivity-bar {
            flex: 1 1 0;
            width: auto;
            min-width: 0;
            border-radius: 2px 2px 0 0;
            background: #28a745;
            min-height: 2px;
            opacity: 0.9;
        }

        .connectivity-bar.bad { background: #dc3545; }
        .connectivity-bar.warn { background: #4b7bec; }

        .connectivity-time-axis {
            margin-top: 4px;
            display: flex;
            justify-content: space-between;
            font-size: 9px;
            color: #6c757d;
            letter-spacing: 0.2px;
        }

        .connectivity-time-tick {
            flex: 0 0 auto;
            min-width: 30px;
            text-align: center;
            font-weight: 700;
            color: #495057;
        }

        .problem-list {
            margin-top: 6px;
            font-size: 10px;
            color: #777;
            line-height: 1.25;
        }

        .problem-item.bad { color: #b71c1c; }

        .exec-quality-trend-box {
            margin-top: 8px;
            background: #f8f9fa;
            border: 1px solid #ddd;
            padding: 8px;
            border-radius: 8px;
        }

        .exec-quality-trend-box h4 {
            color: #666;
            font-size: 10px;
            text-transform: uppercase;
            margin-bottom: 4px;
            letter-spacing: 0.4px;
        }

        @media (max-width: 700px) {
            .connectivity-summary-strip {
                flex-wrap: wrap;
            }

            .connectivity-summary-strip .connectivity-main {
                order: 1;
                width: 100%;
            }

            .connectivity-summary-meta {
                text-align: left;
            }

            .connectivity-summary-meta.left {
                order: 2;
            }

            .connectivity-summary-meta.right {
                order: 3;
                margin-left: auto;
            }
        }

        .problem-item.ok { color: #1e7e34; }

        .daily-learning-meta {
            color: #4a5568;
            font-size: 12px;
            margin-bottom: 6px;
            line-height: 1.3;
        }

        .daily-learning-lessons {
            margin: 0;
            padding-left: 15px;
            color: #1f2937;
            line-height: 1.28;
            font-size: 12px;
        }

        .daily-learning-lessons li {
            margin: 3px 0;
        }

        @media (max-width: 820px) {
            body {
                align-items: flex-start;
                padding: 8px;
            }

            .container {
                padding: var(--hero-stack-gap) 14px 14px;
                border-radius: 8px;
            }

            .header h1 {
                font-size: 22px;
                line-height: 1.2;
            }

            .title-rockets {
                gap: 4px;
            }

            .title-rockets .title-rocket {
                display: none;
            }

            .trade-entry-banner .mobile-price-rocket {
                display: inline-block;
                margin: 0 6px;
            }

            .trade-entry-banner {
                display: flex;
                flex-direction: column;
                gap: 4px;
            }

            .trade-entry-banner .banner-price-slot,
            .trade-entry-banner .banner-meta {
                justify-self: center;
                text-align: center;
            }

            .primary-status-grid {
                grid-template-columns: 1fr;
            }

            #statusGrid.position-flat {
                grid-template-columns: 1fr;
            }

            .status-grid {
                grid-template-columns: 1fr;
            }

            .trades-actions {
                grid-template-columns: 1fr;
            }

            button {
                min-height: 44px;
                font-size: 14px;
            }

            .trade-entry-banner {
                padding: 10px;
            }

            .trade-entry-banner .banner-title {
                font-size: 17px;
                line-height: 1.25;
            }

            .trade-entry-banner .banner-meta {
                font-size: 10px;
            }

            .trades-summary {
                grid-template-columns: 1fr;
            }

            .last-update {
                text-align: center;
                line-height: 1.5;
            }

            .last-update span {
                display: block;
                margin-left: 0 !important;
            }
        }

        @media (max-width: 520px) {
            .container {
                padding: var(--hero-stack-gap) 12px 12px;
            }

            .header h1 {
                font-size: 19px;
            }

            .title-rockets {
                align-items: flex-start;
            }

            .canonical-banner {
                font-size: 10px;
                padding: 7px 8px;
            }

            .status-card,
            .trade-summary-card,
            .exec-quality-card,
            .exec-quality-trend-box {
                padding: 10px;
            }

            .status-value,
            .position-summary-main,
            .trade-summary-value,
            .exec-quality-value,
            .connectivity-main {
                font-size: 15px;
            }

            .trade-entry-banner .banner-meta-left,
            .trade-entry-banner .banner-meta-right {
                display: inline;
            }

            .trade-entry-banner .banner-meta-divider {
                display: none;
            }

            .trade-entry-banner .banner-meta-divider.show {
                display: inline;
            }

            .connectivity-summary-strip {
                gap: 4px;
            }

            .connectivity-summary-meta,
            .connectivity-summary-strip .connectivity-main {
                width: 100%;
                text-align: left;
                white-space: normal;
            }

            .connectivity-time-axis {
                font-size: 8px;
            }

            .logs {
                font-size: 10px;
                max-height: 200px;
            }

            .trades-table-wrap {
                overflow-x: visible;
            }

            .trades-table {
                border-collapse: separate;
                font-size: 11px;
            }

            .trades-table thead {
                display: none;
            }

            .trades-table tbody,
            .trades-table tr,
            .trades-table td {
                display: block;
                width: 100%;
            }

            .trades-table tr {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 8px 10px;
                margin-bottom: 10px;
                background: #fff;
                box-shadow: 0 3px 10px rgba(0, 0, 0, 0.05);
            }

            .trades-table td {
                display: flex;
                justify-content: space-between;
                gap: 10px;
                padding: 6px 0;
                text-align: right;
                border-bottom: 1px solid #f0f0f0;
            }

            .trades-table td:last-child {
                border-bottom: none;
                padding-bottom: 0;
            }

            .trades-table td::before {
                content: attr(data-label);
                flex: 0 0 46%;
                text-align: left;
                color: #666;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.4px;
            }
        }

    </style>
</head>
<body>
    <div class="container">
        <div id="message" class="message"></div>

        <div id="tradeEntryBanner" class="trade-entry-banner disabled">
            <div class="banner-price-slot"><span class="mobile-price-rocket" aria-hidden="true">🚀</span><span id="tradeEntryBannerPrice">--</span><span class="mobile-price-rocket" aria-hidden="true">🚀</span></div>
            <div class="banner-title"><span class="title-rockets"><span class="title-rocket">🚀</span><span>SPY Options Trader Cockpit 1.4</span><span class="title-rocket">🚀</span></span></div>
            <div class="banner-meta" id="tradeEntryBannerMeta">
                <span class="banner-meta-left" id="tradeEntryBannerMetaLeft">🛑 Schwab 903</span><span class="banner-meta-divider" id="tradeEntryBannerMetaDivider">|</span><span class="banner-meta-right" id="tradeEntryBannerMetaRight"></span>
            </div>
        </div>
        
        <div class="status-grid primary-status-grid" id="statusGrid">
            <div class="status-card position-secondary-card" id="callIndicatorsCard">
                <h3>CALL Indicators</h3>
                <div class="status-value" id="callIndicators">Loading...</div>
            </div>
            <div class="status-card position-secondary-card" id="trendCard">
                <h3>Trend</h3>
                <div class="status-value" id="trendStatus">Loading...</div>
            </div>
            <div class="status-card" id="currentPositionCard">
                <h3 id="currentPositionTitle">Current Position</h3>
                <div class="position-stats-grid" id="currentPositionStats">
                    <div class="position-stat-column" id="currentPositionSummary">
                        <div class="position-stat"><div class="position-summary-main" id="currentPosition">Loading...</div></div>
                        <div class="position-stat"><div class="position-summary-pnl" id="currentTradePnl">Loading...</div></div>
                    </div>
                    <div class="position-stat-column">
                        <div class="position-stat"><div class="position-stat-label">Stop Price</div><div class="position-stat-value" id="currentStopPrice">--</div></div>
                        <div class="position-stat"><div class="position-stat-label">Entry Price</div><div class="position-stat-value" id="currentOptionEntry">--</div></div>
                        <div class="position-stat"><div class="position-stat-label">Option Price</div><div class="position-stat-value" id="currentOptionPrice">--</div></div>
                    </div>
                    <div class="position-stat-column" id="currentCandleIndicators">
                        <div class="position-stat"><div class="position-stat-label">Call Indicators</div><div class="position-candle-count" id="currentCandleCallCount">--</div></div>
                        <div class="position-stat"><div class="position-stat-label">Put Indicators</div><div class="position-candle-count" id="currentCandlePutCount">--</div></div>
                        <div class="position-stat"><div class="position-summary-stop" id="currentStopCategory"></div></div>
                    </div>
                    <div class="position-stat-column" id="currentMarketContext">
                        <div class="position-stat"><div class="position-stat-label">Call Phase</div><div class="position-stat-value" id="currentCallPhase">--</div></div>
                        <div class="position-stat"><div class="position-stat-label">Put Phase</div><div class="position-stat-value" id="currentPutPhase">--</div></div>
                        <div class="position-stat"><div class="position-stat-label">Market Trend</div><div class="position-stat-value" id="currentMarketTrend">--</div></div>
                        <div class="position-stat"><div class="position-stat-label">Candle Trend</div><div class="position-stat-value" id="currentCandleTrend">--</div></div>
                    </div>
                </div>
            </div>
            <div class="status-card position-secondary-card" id="putIndicatorsCard">
                <h3>PUT Indicators</h3>
                <div class="status-value" id="putIndicators">Loading...</div>
            </div>
            <div class="status-card position-secondary-card" id="wtdPnlCard">
                <h3>Week-to-Date P&L</h3>
                <div class="status-value" id="wtdPnl">Loading...</div>
            </div>
            <div class="status-card position-secondary-card" id="mtdPnlCard">
                <h3>Month-to-Date P&L</h3>
                <div class="status-value" id="mtdPnl">Loading...</div>
            </div>
            <div class="status-card position-secondary-card" id="ytdPnlCard">
                <h3>Year-to-Date P&L</h3>
                <div class="status-value" id="ytdPnl">Loading...</div>
            </div>
        </div>

        <div class="trades-actions">
            <button class="bot-toggle stopped" id="botToggleBtn" onclick="toggleBot()">▶ Start Bot</button>
            <div class="trade-summary-card neutral" id="todayPnlCard"><h4>Today's P&L</h4><div class="trade-summary-value" id="todayPnl">Loading...</div></div>
            <button class="btn-info" id="exitTradeBtn" onclick="exitTrade()" disabled>⏏ Exit Trade</button>
        </div>
        
        <div style="margin-bottom: 14px;">
            <h2 id="tradesHeading" style="color: #333; font-size: 16px; margin-bottom: 8px; padding-bottom: 6px; text-align: center;">📊 Today's Trades 📊</h2>
            <div id="tradesContainer">
                <div style="text-align: center; color: #999; padding: 20px;">Loading trades...</div>
            </div>
        </div>

        <div class="exec-quality-wrap">
            <div id="executionQualityContainer">
                <div style="text-align: center; color: #999; padding: 12px;">Loading execution quality...</div>
            </div>
        </div>

        <section class="indicator-performance-wrap" aria-label="Indicator performance">
            <div class="indicator-performance-list" id="indicatorPerformanceContainer">
                <div class="indicator-performance-columns" aria-hidden="true">
                    <span>Indicator</span>
                    <span>W / L (Win %)</span>
                    <span>Avg P&amp;L</span>
                    <span>Guidance</span>
                </div>
                <div style="text-align: center; color: #999; padding: 12px;">Loading indicator performance...</div>
            </div>
        </section>
        
        <div class="logs">
            <div class="logs-title">📋 Recent Logs <span id="logsLastUpdated" class="logs-meta">(log updated: loading...)</span></div>
            <pre id="logsContent">Loading logs...</pre>
        </div>
    </div>
    
    <script>
        let statusRefreshInterval;
        let lastStatusSnapshot = null;
        let logsRefreshInFlight = false;
        let tradesRefreshInFlight = false;
        let executionQualityRefreshInFlight = false;
        let indicatorPerformanceRefreshInFlight = false;
        let lastLogsRefreshMs = 0;
        let lastTradesRefreshMs = 0;
        let lastExecutionQualityRefreshMs = 0;
        let lastIndicatorPerformanceRefreshMs = 0;
        let lastIndicatorTradeSignature = null;
        const LOGS_REFRESH_INTERVAL_MS = 500;
        const TRADES_REFRESH_INTERVAL_MS = 10000;
        const EXECUTION_QUALITY_REFRESH_INTERVAL_MS = 10000;
        const INDICATOR_PERFORMANCE_REFRESH_INTERVAL_MS = 30000;
        const STATUS_REFRESH_VISIBLE_INTERVAL_MS = 500;
        const STATUS_REFRESH_HIDDEN_INTERVAL_MS = 8000;
        const DASHBOARD_POLL_LEADER_KEY = 'mcleodAlphaDashboardPollLeader';
        const DASHBOARD_POLL_LEASE_MS = 5000;
        let isPollingLeader = false;
        let pollLeaderHeartbeatInterval = null;
        let previousHasOpenPosition = null;
        let previousOpenTradePnlDollars = null;
        let activeBellPlaybackCount = 0;
        let lastBellBroadcastId = 0;
        let bellBroadcastPrimed = false;

        const MARKET_BELL_AUDIO_PATH = '/static/audio/nyse_bell.mp3';
        const MARKET_BELL_MAX_DURATION_MS = 5000;
        const TRADE_KACHING_AUDIO_PATH = '/static/audio/trade_kaching.mp3';
        const TRADE_LOSS_TRUMPET_AUDIO_PATH = '/static/audio/trade_loss_trumpet.mp3';

        function isDashboardVisible() {
            return !document.hidden;
        }

        function currentTabId() {
            if (!window.__mcLeodTabId) {
                window.__mcLeodTabId = `tab-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
            }
            return window.__mcLeodTabId;
        }

        function readLeaderLease() {
            try {
                const raw = localStorage.getItem(DASHBOARD_POLL_LEADER_KEY);
                if (!raw) {
                    return null;
                }
                const parsed = JSON.parse(raw);
                if (!parsed || typeof parsed !== 'object') {
                    return null;
                }
                return parsed;
            } catch (_) {
                return null;
            }
        }

        function writeLeaderLease() {
            const lease = {
                tabId: currentTabId(),
                expiresAt: Date.now() + DASHBOARD_POLL_LEASE_MS,
            };
            try {
                localStorage.setItem(DASHBOARD_POLL_LEADER_KEY, JSON.stringify(lease));
            } catch (_) {
                // Ignore storage quota/unavailable errors.
            }
            return lease;
        }

        function becomeLeader(force = false) {
            if (!isDashboardVisible()) {
                isPollingLeader = false;
                return false;
            }

            const now = Date.now();
            const existing = readLeaderLease();
            const mine = currentTabId();
            const leaseExpired = !existing || Number(existing.expiresAt || 0) <= now;
            const alreadyMine = existing && existing.tabId === mine;

            if (force || leaseExpired || alreadyMine) {
                writeLeaderLease();
                isPollingLeader = true;
                return true;
            }

            isPollingLeader = false;
            return false;
        }

        function releaseLeaderLease() {
            const existing = readLeaderLease();
            if (existing && existing.tabId === currentTabId()) {
                try {
                    localStorage.removeItem(DASHBOARD_POLL_LEADER_KEY);
                } catch (_) {
                    // Ignore storage errors.
                }
            }
            isPollingLeader = false;
        }

        function refreshPollingSchedule() {
            clearInterval(statusRefreshInterval);
            const intervalMs = isDashboardVisible()
                ? STATUS_REFRESH_VISIBLE_INTERVAL_MS
                : STATUS_REFRESH_HIDDEN_INTERVAL_MS;
            statusRefreshInterval = setInterval(refreshStatus, intervalMs);
        }

        function startLeaderHeartbeat() {
            clearInterval(pollLeaderHeartbeatInterval);
            pollLeaderHeartbeatInterval = setInterval(() => {
                if (!isDashboardVisible()) {
                    releaseLeaderLease();
                    return;
                }
                becomeLeader(false);
            }, Math.max(1000, Math.floor(DASHBOARD_POLL_LEASE_MS / 2)));
        }

        function setTitleBellMode(enabled) {
            const titleWrap = document.querySelector('.title-rockets');
            if (!titleWrap || !titleWrap.children || titleWrap.children.length < 3) {
                return;
            }
            const leftIcon = titleWrap.children[0];
            const rightIcon = titleWrap.children[2];
            if (enabled) {
                leftIcon.textContent = '🔔';
                rightIcon.textContent = '🔔';
            } else {
                leftIcon.textContent = '🚀';
                rightIcon.textContent = '🚀';
            }
        }

        function markBellPlaybackStart() {
            activeBellPlaybackCount += 1;
            setTitleBellMode(true);
        }

        function markBellPlaybackEnd() {
            activeBellPlaybackCount = Math.max(0, activeBellPlaybackCount - 1);
            if (activeBellPlaybackCount === 0) {
                setTitleBellMode(false);
            }
        }

        function runBellEffect(isOpenBell, contextLabel) {
            // Force a visible icon swap even if browser audio autoplay is blocked.
            setTitleBellMode(true);
            setTimeout(() => {
                if (activeBellPlaybackCount === 0) {
                    setTitleBellMode(false);
                }
            }, 3000);
            return playMarketBell(isOpenBell, { context: contextLabel });
        }

        function maybeHandleBellBroadcast(status) {
            const rawId = Number(status && status.bell_broadcast_id);
            if (!Number.isFinite(rawId) || rawId <= 0) {
                return;
            }

            if (!bellBroadcastPrimed) {
                lastBellBroadcastId = rawId;
                bellBroadcastPrimed = true;
                return;
            }

            if (rawId <= lastBellBroadcastId) {
                return;
            }

            lastBellBroadcastId = rawId;
            const kindRaw = String(status && status.bell_broadcast_kind ? status.bell_broadcast_kind : 'open').toLowerCase();
            const isOpenBell = kindRaw !== 'close';
            runBellEffect(isOpenBell, 'broadcast');
        }

        function playMarketBell(isOpenBell, options = {}) {
            // Market bells always use the uploaded NYSE bell sample.
            const bellKind = isOpenBell ? 'open' : 'close';
            const contextLabel = String(options && options.context ? options.context : 'manual test');
            const statusStamp = new Date().toLocaleTimeString('en-US', {
                hour: 'numeric',
                minute: '2-digit',
                second: '2-digit',
                hour12: true,
                timeZone: 'America/New_York',
            });
            try {
                const bellAudio = new Audio(MARKET_BELL_AUDIO_PATH);
                bellAudio.preload = 'auto';
                bellAudio.volume = 1.0;

                let playbackFinalized = false;
                let cutoffTimer = null;
                const finalizePlayback = () => {
                    if (playbackFinalized) {
                        return;
                    }
                    playbackFinalized = true;
                    if (cutoffTimer) {
                        clearTimeout(cutoffTimer);
                    }
                    markBellPlaybackEnd();
                };

                markBellPlaybackStart();

                cutoffTimer = setTimeout(() => {
                    try {
                        bellAudio.pause();
                        bellAudio.currentTime = 0;
                    } catch (_) {}
                    finalizePlayback();
                }, MARKET_BELL_MAX_DURATION_MS);
                bellAudio.addEventListener('ended', finalizePlayback, { once: true });
                bellAudio.addEventListener('error', finalizePlayback, { once: true });

                const playAttempt = bellAudio.play();
                if (playAttempt && typeof playAttempt.then === 'function') {
                    playAttempt.catch(() => {
                        finalizePlayback();
                    });
                }
                return { played: true, source: 'NYSE bell' };
            } catch (_) {
                return { played: false, source: 'NYSE bell' };
            }
        }

        function maybePlayMarketSessionBells(status) {
            const now = status && status.server_time_et
                ? new Date(status.server_time_et)
                : new Date();

            if (status && status.nyse_is_trading_day === false) {
                return;
            }

            const dateFmt = new Intl.DateTimeFormat('en-US', {
                timeZone: 'America/New_York',
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
            });
            const timeFmt = new Intl.DateTimeFormat('en-US', {
                timeZone: 'America/New_York',
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            });
            const weekdayFmt = new Intl.DateTimeFormat('en-US', {
                timeZone: 'America/New_York',
                weekday: 'short',
            });

            const dateParts = dateFmt.formatToParts(now);
            const month = dateParts.find(p => p.type === 'month')?.value;
            const day = dateParts.find(p => p.type === 'day')?.value;
            const year = dateParts.find(p => p.type === 'year')?.value;
            const dateKey = `${year}-${month}-${day}`;
            const weekday = String(weekdayFmt.format(now) || '');
            const isWeekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].includes(weekday);
            if (!isWeekday) {
                return;
            }

            const timeText = String(timeFmt.format(now) || '00:00:00');
            const [hh, mm] = timeText.split(':').map(v => Number(v));

            const openHour = 9;
            const openMinute = 30;
            let closeHour = 16;
            let closeMinute = 0;

            if (status && status.nyse_close_time_et) {
                const closeParts = String(status.nyse_close_time_et).split(':');
                const parsedCloseHour = Number(closeParts[0]);
                const parsedCloseMinute = Number(closeParts[1]);
                if (Number.isFinite(parsedCloseHour) && Number.isFinite(parsedCloseMinute)) {
                    closeHour = parsedCloseHour;
                    closeMinute = parsedCloseMinute;
                }
            }

            // Wider window improves reliability when tab timers are throttled.
            const openWindowMinutes = 2;
            const closeWindowMinutes = 2;

            const openSeenKey = `marketBellOpen:${dateKey}`;
            const closeSeenKey = `marketBellClose:${dateKey}`;

            const inOpenWindow = (
                hh === openHour &&
                mm >= openMinute &&
                mm < (openMinute + openWindowMinutes)
            );
            const inCloseWindow = (
                hh === closeHour &&
                mm >= closeMinute &&
                mm < (closeMinute + closeWindowMinutes)
            );

            if (inOpenWindow) {
                if (localStorage.getItem(openSeenKey) !== '1') {
                    const bellResult = playMarketBell(true, { context: 'schedule' });
                    localStorage.setItem(openSeenKey, '1');
                }
            }

            if (inCloseWindow) {
                if (localStorage.getItem(closeSeenKey) !== '1') {
                    const bellResult = playMarketBell(false, { context: 'schedule' });
                    localStorage.setItem(closeSeenKey, '1');
                }
            }
        }

        function playCashRegisterNoise() {
            try {
                const sound = new Audio(TRADE_KACHING_AUDIO_PATH);
                sound.play().catch(() => {});
            } catch (_) {
                // Ignore audio failures (browser autoplay policy, unavailable context, etc.)
            }
        }

        function playLossTrumpet() {
            try {
                const sound = new Audio(TRADE_LOSS_TRUMPET_AUDIO_PATH);
                sound.play().catch(() => {});
            } catch (_) {
                // Ignore audio failures (browser autoplay policy, unavailable context, etc.)
            }
        }

        function formatTimeAMPM(dateValue) {
            const d = new Date(dateValue);
            if (Number.isNaN(d.getTime())) return '-';
            const timeText = d.toLocaleTimeString('en-US', {
                hour: 'numeric',
                minute: '2-digit',
                hour12: true,
                timeZone: 'America/New_York',
            });
            // Keep standard 12-hour clock style but remove AM/PM label for a cleaner table.
            return String(timeText).replace(/\\s?[AP]M$/i, '');
        }

        function formatDateTimeAMPM(dateValue) {
            const d = new Date(dateValue);
            if (Number.isNaN(d.getTime())) return 'unknown';
            return d.toLocaleString('en-US', {
                month: 'numeric',
                day: 'numeric',
                year: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                second: '2-digit',
                hour12: true,
                timeZone: 'America/New_York',
            });
        }

        function formatAgeSeconds(value) {
            if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
            const n = Math.max(0, Number(value));
            if (n < 60) return `${Math.round(n)}s ago`;
            const mins = Math.floor(n / 60);
            const secs = Math.round(n % 60);
            return `${mins}m ${secs}s ago`;
        }

        function formatNumber(value, digits = 0) {
            const amount = Number(value || 0);
            return new Intl.NumberFormat('en-US', {
                minimumFractionDigits: digits,
                maximumFractionDigits: digits,
            }).format(amount);
        }

        function formatMoney(value) {
            const amount = Number(value || 0);
            const absText = new Intl.NumberFormat('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }).format(Math.abs(amount));
            if (amount < 0) {
                return `($${absText})`;
            }
            return `$${absText}`;
        }

        function safeEscape(value) {
            return String(value || '')
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#39;');
        }
        
        function showMessage(text, type = 'info') {
            const msgEl = document.getElementById('message');
            msgEl.textContent = text;
            msgEl.className = `message show ${type}`;
            setTimeout(() => msgEl.classList.remove('show'), 5000);
        }
        
        async function toggleBot() {
            const btn = document.getElementById('botToggleBtn');
            const running = !!(lastStatusSnapshot && lastStatusSnapshot.bot_running);
            btn.disabled = true;
            btn.innerHTML = running ? '<span class="spinner"></span> Stopping...' : '<span class="spinner"></span> Syncing...';
            
            try {
                const res = await fetch(running ? '/api/stop' : '/api/go-live', { method: 'POST' });
                const data = await res.json();
                
                showMessage(data.message, data.status === 'success' ? 'success' : 'error');
                
                if (!running && data.status === 'success') {
                    clearInterval(statusRefreshInterval);
                    await waitForControlCenterReturn(data.canonical_url || window.location.origin);
                } else {
                    setTimeout(refreshStatus, 500);
                }
            } catch (err) {
                showMessage(`Error: ${err.message}`, 'error');
                btn.disabled = false;
                refreshStatus();
                return;
            }
        }

        async function waitForControlCenterReturn(targetUrl) {
            const baseUrl = String(targetUrl || window.location.origin || '').replace(/\\/$/, '');
            const statusUrl = `${baseUrl}/api/status`;
            const deadlineMs = Date.now() + 90000;

            while (Date.now() < deadlineMs) {
                try {
                    const res = await fetch(statusUrl, { cache: 'no-store' });
                    if (res.ok) {
                        window.location.href = baseUrl || window.location.href;
                        return;
                    }
                } catch (_) {
                    // Cockpit is still restarting.
                }
                await new Promise(resolve => setTimeout(resolve, 2000));
            }

            showMessage('Go-live was triggered, but the dashboard did not come back within 90 seconds. Refresh the page and check logs/go_live_from_cockpit.log.', 'error');
            const btn = document.getElementById('botToggleBtn');
            btn.disabled = false;
            btn.innerHTML = '▶ Start Bot';
        }

        async function exitTrade() {
            const btn = document.getElementById('exitTradeBtn');
            const hasOpenPosition = !!(lastStatusSnapshot && lastStatusSnapshot.has_open_position);
            btn.disabled = true;
            btn.innerHTML = hasOpenPosition ? '<span class="spinner"></span> Exiting...' : '<span class="spinner"></span> Updating entries...';

            try {
                const res = await fetch('/api/exit-trade', { method: 'POST' });
                const data = await res.json();
                showMessage(data.message || 'Exit request sent', data.status === 'success' ? 'success' : 'error');
            } catch (err) {
                showMessage(`Error: ${err.message}`, 'error');
            }

            setTimeout(refreshStatus, 500);
        }

        async function refreshStatus() {
            if (!isDashboardVisible()) {
                return;
            }

            if (!becomeLeader(false)) {
                return;
            }

            try {
                const res = await fetch('/api/status');
                const status = await res.json();
                lastStatusSnapshot = status;
                maybeHandleBellBroadcast(status);
                maybePlayMarketSessionBells(status);
                const closedTradeSignature = String(status.closed_trade_signature || '0:none');
                if (lastIndicatorTradeSignature !== null && lastIndicatorTradeSignature !== closedTradeSignature) {
                    lastIndicatorPerformanceRefreshMs = 0;
                    updateIndicatorPerformance();
                }
                lastIndicatorTradeSignature = closedTradeSignature;
                
                // Update the Schwab readiness status in the entry banner.
                const reconState = String(status.broker_reconciliation || '').toUpperCase();
                const botToggleBtn = document.getElementById('botToggleBtn');
                const botRunning = !!status.bot_running;
                botToggleBtn.disabled = false;
                botToggleBtn.className = `bot-toggle ${botRunning ? 'running' : 'stopped'}`;
                botToggleBtn.innerHTML = botRunning ? '⏹ Stop Bot' : '▶ Start Bot';

                const entryPauseButton = document.getElementById('exitTradeBtn');
                const canControlEntries = !!(status.bot_running && status.mode === 'LIVE TRADING');
                const entryMarketClosed = String(status.trade_entry_reason_code || '').toUpperCase() === 'MARKET_CLOSED';
                entryPauseButton.disabled = !canControlEntries;
                entryPauseButton.innerHTML = status.has_open_position
                    ? '⏏ Exit Trade'
                    : (entryMarketClosed ? 'Market Closed' : (status.entry_paused ? '▶ Resume Entries' : '⏸ Pause Entries'));
                
                // Schwab is ready only for reconciled live trading.
                const modeText = String(status.mode || '').toUpperCase();
                const accountDisplayLabel = 'Schwab 903';
                const schwabReady = modeText === 'LIVE TRADING' && reconState === 'SUCCESS';
                const checklistText = `${schwabReady ? '✅' : '🛑'} ${accountDisplayLabel}`;

                // Trade entry readiness (fast and visible)
                const tradeEntryEnabled = !!status.trade_entry_enabled;
                const tradeEntryBanner = document.getElementById('tradeEntryBanner');
                const tradeEntryBannerPrice = document.getElementById('tradeEntryBannerPrice');
                const tradeEntryBannerMeta = document.getElementById('tradeEntryBannerMeta');
                const trendRaw = String(status.market_trend || status.trend || 'UNKNOWN').toUpperCase();
                const trendMap = {
                    'BULL_TREND': 'BULL_TREND',
                    'BEAR_TREND': 'BEAR_TREND',
                    'NEUTRAL': 'NEUTRAL',
                };
                const trend = trendMap[trendRaw] || 'NEUTRAL';
                let trendText = trend.replaceAll('_', ' ');
                let trendToneClass = 'trend-tone-neutral';
                if (trend === 'BEAR_TREND') {
                    trendText = '🐻 BEAR TREND 🐻';
                    trendToneClass = 'trend-tone-bearish';
                } else if (trend === 'BULL_TREND') {
                    trendText = '🐂 BULL TREND 🐂';
                    trendToneClass = 'trend-tone-bullish';
                }

                const spyPrice = Number(status.spy_price);
                const spyChangePct = Number(status.spy_change_pct);
                const spyQuoteStale = !!status.spy_quote_stale;
                const spyQuoteAgeSeconds = Number(status.spy_quote_age_seconds);
                const spyQuoteStateRaw = String(status.spy_quote_state || 'UNAVAILABLE').toUpperCase();
                const tradeEntryReasonRaw = String(status.trade_entry_reason || '').toLowerCase();
                const tradeEntryReasonCodeRaw = String(status.trade_entry_reason_code || '').toUpperCase();
                const marketClosed = status.nyse_is_trading_day === false
                    || tradeEntryReasonRaw.includes('market closed')
                    || tradeEntryReasonRaw.includes('outside regular market hours')
                    || tradeEntryReasonRaw.includes('marked closed');
                const candleDataStale =
                    tradeEntryReasonRaw.includes('stale candle')
                    || (tradeEntryReasonCodeRaw === 'STARTUP_GUARD' && tradeEntryReasonRaw.includes('candle'));

                function prettySpySource(stateRaw) {
                    if (stateRaw === 'SCHWAB_STREAM_LIVE') return 'Schwab Stream Live';
                    if (stateRaw === 'SCHWAB_REST_LIVE') return 'Schwab REST Live';
                    if (stateRaw === 'SCHWAB_REST') return 'Schwab REST';
                    if (stateRaw === 'ALPACA') return 'Alpaca';
                    if (stateRaw === 'FRESH') return 'Fresh';
                    if (stateRaw === 'STALE') return 'Stale';
                    if (stateRaw === 'UNAVAILABLE') return 'Unavailable';
                    return stateRaw.replace(/_/g, ' ').trim() || 'Unavailable';
                }

                function spySourceToneClass(stateRaw) {
                    if (stateRaw === 'SCHWAB_STREAM_LIVE' || stateRaw === 'SCHWAB_REST_LIVE' || stateRaw === 'FRESH') return 'live';
                    if (stateRaw === 'SCHWAB_REST' || stateRaw === 'ALPACA') return 'mixed';
                    if (stateRaw === 'STALE') return 'stale';
                    return 'unknown';
                }

                const spySourceLabel = prettySpySource(spyQuoteStateRaw);
                const spySourceTone = spySourceToneClass(spyQuoteStateRaw);
                let priceBannerHtml = '--';
                const quoteNotLive = spyQuoteStale || ['STALE', 'DELAYED', 'UNAVAILABLE'].includes(spyQuoteStateRaw);
                const useRecentClosedQuote = marketClosed && Number.isFinite(spyPrice) && spyPrice > 0;
                if (candleDataStale) {
                    priceBannerHtml = '<span class="banner-price banner-tone-down">ERROR: STALE CANDLES</span>';
                } else if (useRecentClosedQuote) {
                    let pctText = null;
                    let toneClass = 'banner-tone-flat';
                    if (Number.isFinite(spyChangePct)) {
                        const pctRaw = `${Math.abs(spyChangePct).toFixed(2)}%`;
                        const pctSign = spyChangePct > 0 ? '+' : (spyChangePct < 0 ? '-' : '');
                        pctText = `(${pctSign}${pctRaw})`;
                        if (spyChangePct > 0) {
                            toneClass = 'banner-tone-up';
                        } else if (spyChangePct < 0) {
                            toneClass = 'banner-tone-down';
                        }
                    }
                    priceBannerHtml = pctText
                        ? `<span class="banner-price ${toneClass}">$${spyPrice.toFixed(2)}</span> <span class="banner-pct ${toneClass}">${pctText}</span>`
                        : `<span class="banner-price banner-tone-flat">$${spyPrice.toFixed(2)}</span>`;
                } else if (quoteNotLive) {
                    const ageSuffix = Number.isFinite(spyQuoteAgeSeconds)
                        ? ` (${Math.max(0, Math.round(spyQuoteAgeSeconds))}s old)`
                        : '';
                    priceBannerHtml = `<span class="banner-price banner-tone-down">ERROR: STALE SPY QUOTE${ageSuffix}</span>`;
                } else if (Number.isFinite(spyPrice) && spyPrice > 0) {
                    let pctText = null;
                    let toneClass = 'banner-tone-flat';
                    if (Number.isFinite(spyChangePct)) {
                        const pctRaw = `${Math.abs(spyChangePct).toFixed(2)}%`;
                        const pctSign = spyChangePct > 0 ? '+' : (spyChangePct < 0 ? '-' : '');
                        pctText = `(${pctSign}${pctRaw})`;
                        if (spyChangePct > 0) {
                            toneClass = 'banner-tone-up';
                        } else if (spyChangePct < 0) {
                            toneClass = 'banner-tone-down';
                        }
                    }
                    priceBannerHtml = pctText
                        ? `<span class="banner-price ${toneClass}">$${spyPrice.toFixed(2)}</span> <span class="banner-pct ${toneClass}">${pctText}</span>`
                        : `<span class="banner-price banner-tone-flat">$${spyPrice.toFixed(2)}</span>`;
                }
                const candleAt = status.last_candle_at || '';
                const candleTimeText = formatTimeAMPM(candleAt);

                if (tradeEntryEnabled) {
                    tradeEntryBanner.className = 'trade-entry-banner enabled';
                } else {
                    const bannerReason = String(status.trade_entry_reason || '').trim().toLowerCase();
                    const afterHoursRunning = !!status.bot_running && (
                        bannerReason.includes('marked closed') ||
                        bannerReason.includes('market closed') ||
                        bannerReason.includes('outside regular market hours')
                    );
                    if (status.has_open_position) {
                        tradeEntryBanner.className = 'trade-entry-banner disabled';
                    } else if (afterHoursRunning) {
                        tradeEntryBanner.className = 'trade-entry-banner after-hours';
                    } else {
                        tradeEntryBanner.className = 'trade-entry-banner disabled';
                    }
                }
                if (tradeEntryBannerPrice) {
                    tradeEntryBannerPrice.innerHTML = priceBannerHtml;
                }
                const tradeEntryBannerMetaLeft = document.getElementById('tradeEntryBannerMetaLeft');
                const tradeEntryBannerMetaDivider = document.getElementById('tradeEntryBannerMetaDivider');
                const tradeEntryBannerMetaRight = document.getElementById('tradeEntryBannerMetaRight');
                if (tradeEntryBannerMetaLeft) {
                    tradeEntryBannerMetaLeft.textContent = checklistText;
                }
                if (tradeEntryBannerMetaRight) {
                    const timePart = candleTimeText !== '-' ? `${candleTimeText}` : '';
                    let clockAgeSeconds = Number(status.candle_age_seconds);
                    if (!Number.isFinite(clockAgeSeconds) || clockAgeSeconds < 0) {
                        const parsedTs = Date.parse(candleAt);
                        if (Number.isFinite(parsedTs)) {
                            clockAgeSeconds = Math.max(0, (Date.now() - parsedTs) / 1000);
                        }
                    }

                    const isStaleClock = Number.isFinite(clockAgeSeconds) && clockAgeSeconds > 120;
                    const rightMetaParts = [];
                    if (timePart) {
                        rightMetaParts.push(`🕯️ ${timePart}`);
                    }
                    const hasRightMeta = rightMetaParts.length > 0;
                    tradeEntryBannerMetaRight.innerHTML = rightMetaParts.length
                        ? rightMetaParts.join(' | ')
                        : '';
                    if (tradeEntryBannerMetaDivider) {
                        tradeEntryBannerMetaDivider.classList.toggle('show', hasRightMeta);
                    }
                    tradeEntryBannerMetaRight.classList.toggle('stale', isStaleClock);
                }
                // Current position
                const posEl = document.getElementById('currentPosition');
                const posCardEl = document.getElementById('currentPositionCard');
                const rawPosition = String(status.current_position || '').trim();
                const positionSide = String(status.current_position_side || '').trim().toUpperCase();
                if (posCardEl) {
                    posCardEl.classList.remove('position-call', 'position-put', 'position-neutral');
                }
                if (rawPosition) {
                    const prettyPosition = rawPosition
                        .split(/\\s+/)
                        .filter(Boolean)
                        .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
                        .join(' ');
                    posEl.textContent = prettyPosition;

                    if (positionSide === 'CALL' || /\bCALL\b/i.test(rawPosition)) {
                        posEl.className = 'position-summary-main success';
                    } else if (positionSide === 'PUT' || /\bPUT\b/i.test(rawPosition)) {
                        posEl.className = 'position-summary-main error';
                    } else {
                        posEl.className = 'position-summary-main warning';
                    }
                } else {
                    posEl.textContent = 'None';
                    posEl.className = 'position-summary-main info';
                }

                const hasOpenPosition = !!status.has_open_position;
                const positionTitleEl = document.getElementById('currentPositionTitle');
                if (positionTitleEl) {
                    positionTitleEl.hidden = hasOpenPosition;
                }
                const statusGrid = document.getElementById('statusGrid');
                if (statusGrid) {
                    statusGrid.classList.toggle('position-focus-active', hasOpenPosition);
                    statusGrid.classList.toggle('position-flat', !hasOpenPosition);
                }
                if (previousHasOpenPosition !== null && previousHasOpenPosition !== hasOpenPosition) {
                    if (hasOpenPosition) {
                        playCashRegisterNoise();
                    } else if (Number(previousOpenTradePnlDollars) > 0) {
                        playCashRegisterNoise();
                    } else if (Number(previousOpenTradePnlDollars) < 0) {
                        playLossTrumpet();
                    }
                }
                if (hasOpenPosition && Number.isFinite(Number(status.current_trade_pnl_dollars))) {
                    previousOpenTradePnlDollars = Number(status.current_trade_pnl_dollars);
                } else if (!hasOpenPosition) {
                    previousOpenTradePnlDollars = null;
                }
                previousHasOpenPosition = hasOpenPosition;

                // Week-to-date realized P&L
                const wtdEl = document.getElementById('wtdPnl');
                const wtdCardEl = document.getElementById('wtdPnlCard');
                const wtd = Number(status.week_to_date_pnl || 0);
                wtdEl.textContent = formatMoney(wtd);
                if (wtdCardEl) {
                    wtdCardEl.classList.remove('pnl-positive', 'pnl-negative', 'pnl-neutral');
                }
                if (wtd > 0) {
                    wtdEl.className = 'status-value success';
                    if (wtdCardEl) wtdCardEl.classList.add('pnl-positive');
                } else if (wtd < 0) {
                    wtdEl.className = 'status-value error';
                    if (wtdCardEl) wtdCardEl.classList.add('pnl-negative');
                } else {
                    wtdEl.className = 'status-value info';
                    if (wtdCardEl) wtdCardEl.classList.add('pnl-neutral');
                }

                // Month-to-date realized P&L
                const mtdEl = document.getElementById('mtdPnl');
                const mtd = Number(status.month_to_date_pnl || 0);
                mtdEl.textContent = formatMoney(mtd);
                if (mtd > 0) {
                    mtdEl.className = 'status-value success';
                } else if (mtd < 0) {
                    mtdEl.className = 'status-value error';
                } else {
                    mtdEl.className = 'status-value info';
                }

                // Year-to-date realized P&L
                const ytdEl = document.getElementById('ytdPnl');
                const ytd = Number(status.year_to_date_pnl || 0);
                ytdEl.textContent = formatMoney(ytd);
                if (ytd > 0) {
                    ytdEl.className = 'status-value success';
                } else if (ytd < 0) {
                    ytdEl.className = 'status-value error';
                } else {
                    ytdEl.className = 'status-value info';
                }

                // Continuation cheat-sheet: latest passed indicators out of total.
                const indicatorTotal = Number(status.continuation_indicators_total || 5);
                const callPassed = Number(status.continuation_call_passed || 0);
                const putPassed = Number(status.continuation_put_passed || 0);
                const callMomentumStage = String(status.call_momentum_stage || '').replaceAll('_', ' ');
                const putMomentumStage = String(status.put_momentum_stage || '').replaceAll('_', ' ');
                const isNoTrade = status.last_decision === 'NO_TRADE' || (!status.has_open_position && !tradeEntryEnabled);
                const tradeEntryReason = String(status.trade_entry_reason || '').trim();
                const lastEntryCandidateDirection = String(status.last_entry_candidate_direction || '').toUpperCase();
                const lastEntryBlockReason = String(status.last_entry_block_reason || '').trim();
                const indicatorRegime = String(status.continuation_regime || 'UNKNOWN').toUpperCase();
                const candleTrend = trendMap[indicatorRegime] || 'NEUTRAL';
                const candleTrendLabel = candleTrend.replaceAll('_', ' ');
                let candleTrendToneClass = 'trend-tone-neutral';
                if (candleTrend === 'BEAR_TREND') {
                    candleTrendToneClass = 'trend-tone-bearish';
                } else if (candleTrend === 'BULL_TREND') {
                    candleTrendToneClass = 'trend-tone-bullish';
                }

                function escapeHtml(value) {
                    return String(value || '')
                        .replaceAll('&', '&amp;')
                        .replaceAll('<', '&lt;')
                        .replaceAll('>', '&gt;')
                        .replaceAll('"', '&quot;')
                        .replaceAll("'", '&#39;');
                }

                const trendStatusEl = document.getElementById('trendStatus');
                if (trendStatusEl) {
                    trendStatusEl.innerHTML = `<span class="${trendToneClass}">${escapeHtml(trendText)}</span><br><span class="${candleTrendToneClass}" style="font-size:11px;font-weight:500;opacity:0.85;">🕯️ ${escapeHtml(candleTrendLabel)} 🕯️</span>`;
                }

                function renderIndicatorText(passed, side) {
                    const base = `${passed}/${indicatorTotal} Passed`;
                    const momentumStage = side === 'CALL' ? callMomentumStage : putMomentumStage;
                    const phaseText = momentumStage
                        ? `<br><span style="font-size:11px;font-weight:500;opacity:0.85;">${escapeHtml(momentumStage)}</span>`
                        : '';
                    if (passed < 5) {
                        return `${base}${phaseText}`;
                    }

                    if (lastEntryCandidateDirection === side && lastEntryBlockReason) {
                        const blockReason = escapeHtml(lastEntryBlockReason.replaceAll('_', ' '));
                        return `${base}${phaseText}<br><span style="font-size:12px;font-weight:500;opacity:0.9;">Blocked: ${blockReason}</span>`;
                    }

                    const requiredRegime = side === 'CALL' ? 'BULL_TREND' : 'BEAR_TREND';
                    if (indicatorRegime !== requiredRegime) {
                        return `${base}${phaseText}<br><span style="font-size:12px;font-weight:500;opacity:0.9;">Blocked: ${escapeHtml(candleTrendLabel)}</span>`;
                    }

                    if (!isNoTrade) {
                        return `${base}${phaseText}`;
                    }
                    const conciseReasonRaw = tradeEntryReason
                        || status.last_decision_reason
                        || 'No entry conditions met';
                    const conciseReason = escapeHtml(conciseReasonRaw);
                    if (conciseReason) {
                        return `${base}${phaseText}<br><span style="font-size:12px;font-weight:500;opacity:0.9;">Blocked: ${conciseReason}</span>`;
                    }
                    return `${base}${phaseText}`;
                }

                const callIndEl = document.getElementById('callIndicators');
                const callIndicatorsCard = document.getElementById('callIndicatorsCard');
                callIndEl.innerHTML = renderIndicatorText(callPassed, 'CALL');
                const strongThreshold = Math.max(1, indicatorTotal);
                const midThreshold = Math.max(0, indicatorTotal - 1);
                if (callIndicatorsCard) {
                    callIndicatorsCard.classList.toggle('indicator-qualified', callPassed >= 5);
                }
                if (callPassed >= strongThreshold) {
                    callIndEl.className = 'status-value success';
                } else if (callPassed >= midThreshold) {
                    callIndEl.className = 'status-value info';
                } else {
                    callIndEl.className = 'status-value error';
                }

                const putIndEl = document.getElementById('putIndicators');
                const putIndicatorsCard = document.getElementById('putIndicatorsCard');
                putIndEl.innerHTML = renderIndicatorText(putPassed, 'PUT');
                if (putIndicatorsCard) {
                    putIndicatorsCard.classList.toggle('indicator-qualified', putPassed >= 5);
                }
                if (putPassed >= strongThreshold) {
                    putIndEl.className = 'status-value success';
                } else if (putPassed >= midThreshold) {
                    putIndEl.className = 'status-value info';
                } else {
                    putIndEl.className = 'status-value error';
                }

                // Current trade P&L (unrealized)
                const tradePnlEl = document.getElementById('currentTradePnl');
                const stopCategoryEl = document.getElementById('currentStopCategory');
                const stopPriceEl = document.getElementById('currentStopPrice');
                const optionEntryEl = document.getElementById('currentOptionEntry');
                const optionPriceEl = document.getElementById('currentOptionPrice');
                const candleCallCountEl = document.getElementById('currentCandleCallCount');
                const candlePutCountEl = document.getElementById('currentCandlePutCount');
                const callPhaseEl = document.getElementById('currentCallPhase');
                const putPhaseEl = document.getElementById('currentPutPhase');
                const marketTrendEl = document.getElementById('currentMarketTrend');
                const candleTrendEl = document.getElementById('currentCandleTrend');
                const tradePnlDollars = status.current_trade_pnl_dollars;
                const tradePnlPct = status.current_trade_pnl_pct;
                const optionEntryPrice = Number(status.current_trade_option_entry);
                const currentOptionPrice = Number(status.current_trade_mark);
                const activeStopPrice = Number(status.active_protective_stop_price);
                const activeStopCategory = String(status.active_stop_category || '').trim();
                const entryCallCount = Number(status.entry_call_indicators);
                const entryPutCount = Number(status.entry_put_indicators);
                const formatIndicatorDelta = (current, entry) => {
                    if (!Number.isFinite(entry)) return '';
                    const delta = current - entry;
                    if (delta > 0) return ` +${delta}`;
                    if (delta < 0) return ` ${delta}`;
                    return ' 0';
                };
                if (status.has_open_position && tradePnlDollars !== null && tradePnlDollars !== undefined && tradePnlPct !== null && tradePnlPct !== undefined) {
                    const dollarsText = formatMoney(tradePnlDollars);
                    const pctText = `${tradePnlPct >= 0 ? '+' : ''}${formatNumber(Math.abs(tradePnlPct), 1)}%`;
                    tradePnlEl.innerHTML = `${pctText}<br>${dollarsText}`;
                    if (Number(tradePnlDollars) > 0) {
                        tradePnlEl.className = 'position-summary-pnl success';
                        if (posCardEl) posCardEl.classList.add('position-call');
                    } else if (Number(tradePnlDollars) < 0) {
                        tradePnlEl.className = 'position-summary-pnl error';
                        if (posCardEl) posCardEl.classList.add('position-put');
                    } else {
                        tradePnlEl.className = 'position-summary-pnl info';
                        if (posCardEl) posCardEl.classList.add('position-neutral');
                    }
                } else {
                    tradePnlEl.textContent = '';
                    tradePnlEl.className = 'position-summary-pnl info';
                    if (posCardEl) posCardEl.classList.add('position-neutral');
                }

                if (status.has_open_position && Number.isFinite(activeStopPrice) && activeStopPrice > 0 && stopCategoryEl) {
                    stopCategoryEl.textContent = activeStopCategory || 'Active Stop';
                    stopCategoryEl.className = 'position-summary-stop active';
                } else if (status.has_open_position && stopCategoryEl) {
                    stopCategoryEl.textContent = 'Stop unavailable';
                    stopCategoryEl.className = 'position-summary-stop';
                } else if (stopCategoryEl) {
                    stopCategoryEl.textContent = '';
                    stopCategoryEl.className = 'position-summary-stop';
                }

                if (optionEntryEl) {
                    optionEntryEl.textContent = status.has_open_position && Number.isFinite(optionEntryPrice) && optionEntryPrice > 0
                        ? formatMoney(optionEntryPrice)
                        : '--';
                }
                if (stopPriceEl) {
                    stopPriceEl.textContent = status.has_open_position && Number.isFinite(activeStopPrice) && activeStopPrice > 0
                        ? formatMoney(activeStopPrice)
                        : '--';
                }
                if (optionPriceEl) {
                    optionPriceEl.textContent = status.has_open_position && Number.isFinite(currentOptionPrice) && currentOptionPrice > 0
                        ? formatMoney(currentOptionPrice)
                        : '--';
                }
                if (candleCallCountEl) {
                    candleCallCountEl.textContent = status.has_open_position
                        ? `${callPassed}/${indicatorTotal}${formatIndicatorDelta(callPassed, entryCallCount)}`
                        : '--';
                }
                if (candlePutCountEl) {
                    candlePutCountEl.textContent = status.has_open_position
                        ? `${putPassed}/${indicatorTotal}${formatIndicatorDelta(putPassed, entryPutCount)}`
                        : '--';
                }
                if (callPhaseEl) {
                    callPhaseEl.textContent = status.has_open_position && callMomentumStage
                        ? callMomentumStage
                        : '--';
                }
                if (putPhaseEl) {
                    putPhaseEl.textContent = status.has_open_position && putMomentumStage
                        ? putMomentumStage
                        : '--';
                }
                if (marketTrendEl) {
                    marketTrendEl.textContent = status.has_open_position
                        ? trendText
                        : '--';
                }
                if (candleTrendEl) {
                    candleTrendEl.textContent = status.has_open_position
                        ? candleTrendLabel
                        : '--';
                }

                const nowMs = Date.now();
                if ((nowMs - lastExecutionQualityRefreshMs) >= EXECUTION_QUALITY_REFRESH_INTERVAL_MS) {
                    updateExecutionQuality(status);
                }
                if ((nowMs - lastLogsRefreshMs) >= LOGS_REFRESH_INTERVAL_MS) {
                    refreshLogs();
                }
                if ((nowMs - lastTradesRefreshMs) >= TRADES_REFRESH_INTERVAL_MS) {
                    updateTodaysTrades();
                }
                if ((nowMs - lastIndicatorPerformanceRefreshMs) >= INDICATOR_PERFORMANCE_REFRESH_INTERVAL_MS) {
                    updateIndicatorPerformance();
                }
            } catch (err) {
                console.error('Error refreshing status:', err);
            }
        }

        async function refreshLogs() {
            if (logsRefreshInFlight) {
                return;
            }

            logsRefreshInFlight = true;
            try {
                // Use a large tail window and cache-bust each refresh so stale
                // browser caches cannot pin an older, smaller line count.
                const logsRes = await fetch(`/api/logs?lines=300&_=${Date.now()}`);
                const logsData = await logsRes.json();
                const logsContent = document.getElementById('logsContent');
                const logsLastUpdated = document.getElementById('logsLastUpdated');

                if (logsData.logs.length > 0) {
                    logsContent.textContent = [...logsData.logs].reverse().join('');
                } else {
                    logsContent.textContent = '(No logs yet)';
                }

                if (logsData.log_last_modified) {
                    const logModifiedTs = new Date(logsData.log_last_modified).getTime();
                    const nowTs = Date.now();
                    const logAgeSeconds = Number.isFinite(logModifiedTs) ? Math.max(0, Math.round((nowTs - logModifiedTs) / 1000)) : null;
                    const logStale = Number.isFinite(logAgeSeconds) && logAgeSeconds > 120;
                    const stalePrefix = logStale ? '🛑 ' : '';
                    const ageSuffix = Number.isFinite(logAgeSeconds) ? ` (${logAgeSeconds}s)` : '';
                    logsLastUpdated.textContent = `${stalePrefix}(log updated: ${formatDateTimeAMPM(logsData.log_last_modified)}${ageSuffix})`;
                } else {
                    logsLastUpdated.textContent = '(log updated: unknown)';
                }
                lastLogsRefreshMs = Date.now();
            } catch (err) {
                console.error('Error refreshing logs:', err);
            } finally {
                logsRefreshInFlight = false;
            }
        }

        async function updateExecutionQuality(status) {
            if (executionQualityRefreshInFlight) {
                return;
            }

            const snapshot = status || lastStatusSnapshot || {};
            executionQualityRefreshInFlight = true;
            try {
                const safeEscape = (value) => String(value || '')
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#39;');

                const tradingDate = String((snapshot && snapshot.broker_pnl_as_of_date) || '').trim();
                const url = tradingDate
                    ? `/api/execution-quality-summary?date=${encodeURIComponent(tradingDate)}`
                    : '/api/execution-quality-summary';
                const res = await fetch(url);
                const data = await res.json();
                const container = document.getElementById('executionQualityContainer');

                const fillRate = Number(data.fill_rate_pct || 0);
                const fallbackRate = Number(data.fallback_rate_pct || 0);
                const avgSlip = data.avg_slippage;
                const avgSlipBps = data.avg_slippage_bps;
                const attempts = Number(data.attempt_count || 0);
                const filled = Number(data.filled_count || 0);
                const goals = data.goals || {};
                const fillRateGoal = Number(goals.fill_rate_pct || 95.0);
                const fallbackRateGoal = Number(goals.fallback_rate_pct || 10.0);
                const avgSlipGoal = Number(goals.avg_slippage || 0.05);
                const avgSlipBpsGoal = Number(goals.avg_slippage_bps || 5.0);
                const sideWindowSlipGoal = Number(goals.side_window_avg_slippage || 0.05);
                const sideWindowSlipBpsGoal = Number(goals.side_window_avg_slippage_bps || 5.0);
                const internet = snapshot.internet_quality || {};
                const history = snapshot.internet_quality_history || {};
                const internetQuality = String(internet.quality || 'UNKNOWN').toUpperCase();

                function goalCompare(actual, goal, direction = 'lte') {
                    const actualNum = Number(actual);
                    const goalNum = Number(goal);
                    if (Number.isNaN(actualNum) || Number.isNaN(goalNum)) {
                        return false;
                    }
                    return direction === 'gte' ? actualNum >= goalNum : actualNum <= goalNum;
                }

                function goalText(actualText, goalTextValue, ok) {
                    return `<div class="exec-quality-sub ${ok ? 'success' : 'error'}">Actual: ${actualText}<br>Goal: ${goalTextValue}</div>`;
                }

                function goalBadge(label, ok) {
                    return `<div><span class="exec-quality-goal ${ok ? 'success' : 'error'}">${label}</span></div>`;
                }

                function internetQualityTone(quality) {
                    if (quality === 'EXCELLENT') return 'success';
                    if (quality === 'GOOD') return 'info';
                    if (quality === 'FAIR' || quality === 'DEGRADED') return 'warning';
                    if (quality === 'DOWN') return 'error';
                    return 'info';
                }

                function internetQualityIcon(quality) {
                    if (quality === 'EXCELLENT') return '✅';
                    if (quality === 'GOOD') return '';
                    if (quality === 'FAIR' || quality === 'DEGRADED') return '⚠';
                    if (quality === 'DOWN') return '❌';
                    return '•';
                }

                const rows = Array.isArray(data.by_side_window) ? data.by_side_window : [];
                const sideWindowOverallOk = rows.length > 0 && rows.every(r => Number(r.avg_slippage || 0) <= sideWindowSlipGoal && Number(r.avg_slippage_bps || 0) <= sideWindowSlipBpsGoal);
                const sideWindowAvgSlip = data.avg_slippage;
                const sideWindowAvgSlipBps = data.avg_slippage_bps;
                const sideWindowCardOk = goalCompare(sideWindowAvgSlip, sideWindowSlipGoal, 'lte') && goalCompare(sideWindowAvgSlipBps, sideWindowSlipBpsGoal, 'lte');
                const sideWindowActualText = `${sideWindowAvgSlip === null || sideWindowAvgSlip === undefined ? '-' : Number(sideWindowAvgSlip).toFixed(3)} / ${sideWindowAvgSlipBps === null || sideWindowAvgSlipBps === undefined ? '-' : `${formatNumber(sideWindowAvgSlipBps, 1)} bps`}`;
                const sideWindowGoalText = `<= ${sideWindowSlipGoal.toFixed(3)} / <= ${formatNumber(sideWindowSlipBpsGoal, 1)} bps`;

                let html = '';
                const internetTone = internetQualityTone(internetQuality);
                const internetSummary = safeEscape(String(internet.summary || 'Unknown'));
                const internetTitle = safeEscape(internetQuality);
                const pointsRaw = Array.isArray(history.recent_points_ms) ? history.recent_points_ms : [];
                const pointTimestampsRaw = Array.isArray(history.recent_point_timestamps) ? history.recent_point_timestamps : [];
                const points = [...pointsRaw].reverse();
                const pointTimestamps = [...pointTimestampsRaw].reverse();
                html += '<div class="exec-quality-trend-box">';
                html += `<div class="connectivity-summary-strip"><div class="connectivity-main ${internetTone}">${internetTitle}</div></div>`;
                if (snapshot.internet_market_warning) {
                    html += `<div class="connectivity-alert warn">${safeEscape(String(snapshot.internet_market_warning_message || 'Market-hours internet warning'))}</div>`;
                }
                if (points.length >= 2) {
                    const pMin = Math.min(...points);
                    const sortedPoints = [...points].sort((left, right) => left - right);
                    const p95 = sortedPoints[Math.floor((sortedPoints.length - 1) * 0.95)];
                    const visualCeiling = Math.max(pMin + 1, p95);
                    const visualSpread = Math.max(1, visualCeiling - pMin);
                    const chartHtml = points.map((value) => {
                        const n = Number(value || 0);
                        const scaled = 6 + Math.round(Math.min(1, Math.max(0, (n - pMin) / visualSpread)) * 34);
                        const cls = n > 600 ? 'bad' : (n > 250 ? 'warn' : '');
                        return `<div class="connectivity-bar ${cls}" style="height:${scaled}px" title="${safeEscape(n.toFixed(1))} ms"></div>`;
                    }).join('');
                    html += `<div class="connectivity-chart connectivity-chart-large">${chartHtml}</div>`;

                    // Add five evenly spaced ET timestamps under the chart.
                    const parseTs = (text) => {
                        if (!text) return null;
                        const d = new Date(String(text));
                        return Number.isNaN(d.getTime()) ? null : d;
                    };
                    const newestTs = parseTs(pointTimestamps.length ? pointTimestamps[0] : history.latest_checked_at);
                    const oldestTs = parseTs(pointTimestamps.length ? pointTimestamps[pointTimestamps.length - 1] : null);
                    if (newestTs && oldestTs) {
                        const newestMs = newestTs.getTime();
                        const oldestMs = oldestTs.getTime();
                        const spanMs = newestMs - oldestMs;
                        const tickOffsets = [1, 0.75, 0.5, 0.25, 0];
                        const ticks = tickOffsets.map((offset) => {
                            const tickMs = oldestMs + (spanMs * offset);
                            return Math.round(tickMs / 60000) * 60000;
                        });
                        const axisHtml = ticks.map((ms) => {
                                const text = new Date(ms).toLocaleTimeString('en-US', {
                                    timeZone: 'America/New_York',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    hour12: true,
                                });
                            return `<span class="connectivity-time-tick">${safeEscape(text)}</span>`;
                        }).join('');
                        html += `<div class="connectivity-time-axis">${axisHtml}</div>`;
                    }
                } else {
                    html += '<div class="connectivity-chart connectivity-chart-large"><div style="font-size:11px;color:#777;line-height:44px;">Collecting trend data...</div></div>';
                }
                html += '</div>';

                container.innerHTML = html;
                lastExecutionQualityRefreshMs = Date.now();
            } catch (err) {
                console.error('Error fetching execution quality:', err);
                document.getElementById('executionQualityContainer').innerHTML = '<div style="text-align: center; color: #999; padding: 12px;">Execution quality unavailable</div>';
            } finally {
                executionQualityRefreshInFlight = false;
            }
        }
        
        
        async function updateIndicatorPerformance() {
            if (indicatorPerformanceRefreshInFlight) {
                return;
            }

            indicatorPerformanceRefreshInFlight = true;
            try {
                const response = await fetch('/api/indicator-performance');
                if (!response.ok) {
                    throw new Error(`Indicator Performance request failed: HTTP ${response.status}`);
                }
                const data = await response.json();
                const rows = Array.isArray(data.indicators) ? data.indicators : [];
                const container = document.getElementById('indicatorPerformanceContainer');
                const columns = `<div class="indicator-performance-columns" aria-hidden="true">
                    <span>Indicator</span>
                    <span>W / L (Win %)</span>
                    <span>Avg P&amp;L</span>
                    <span>Guidance</span>
                </div>`;
                const escapeText = (value) => String(value || '')
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#39;');
                const money = (value) => {
                    const amount = Number(value || 0);
                    return `${amount < 0 ? '-' : ''}$${Math.abs(amount).toFixed(2)}`;
                };
                const formatIndicatorName = (value) => String(value || '')
                    .split('_')
                    .filter(Boolean)
                    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
                    .join(' ');

                if (!rows.length) {
                    container.innerHTML = `${columns}<div style="text-align: center; color: #999; padding: 12px;">No closed trades with recorded entry indicators yet.</div>`;
                    return;
                }

                container.innerHTML = columns + rows.map((row) => {
                    const averageReturn = Number(row.average_return || 0);
                    const wins = Number(row.wins || 0);
                    const losses = Number(row.losses || 0);
                    const winRate = Number(row.win_rate_pct || 0);
                    const guidance = String(row.guidance || 'Keep monitoring');
                    const tone = guidance === 'Candidate to increase weight'
                        ? 'candidate'
                        : (guidance === 'Review for reduction' ? 'review' : (guidance === 'Collect more data' ? 'collect' : ''));
                    const averageTone = averageReturn > 0 ? 'positive' : (averageReturn < 0 ? 'negative' : '');
                    return `<article class="indicator-performance-row">
                        <div class="indicator-performance-name">${escapeText(formatIndicatorName(row.indicator))}</div>
                        <div class="indicator-performance-stats"><span class="indicator-performance-wins">${wins}W</span> / <span class="indicator-performance-losses">${losses}L</span> (${winRate.toFixed(1)}%)</div>
                        <div class="indicator-performance-stats indicator-performance-average ${averageTone}">${money(averageReturn)}</div>
                        <div class="indicator-performance-stats"><span class="indicator-performance-guidance ${tone}">${escapeText(guidance)}</span></div>
                    </article>`;
                }).join('');
                lastIndicatorPerformanceRefreshMs = Date.now();
            } catch (error) {
                console.error('Error loading indicator performance:', error);
                document.getElementById('indicatorPerformanceContainer').innerHTML = '<div style="text-align: center; color: #999; padding: 12px;">Indicator performance unavailable</div>';
            } finally {
                indicatorPerformanceRefreshInFlight = false;
            }
        }

        async function updateTodaysTrades() {
            if (tradesRefreshInFlight) {
                return;
            }

            tradesRefreshInFlight = true;
            try {
                const res = await fetch('/api/today-trades');
                const data = await res.json();
                const container = document.getElementById('tradesContainer');
                const heading = document.getElementById('tradesHeading');

                function ordinalDay(day) {
                    const rem100 = day % 100;
                    if (rem100 >= 11 && rem100 <= 13) return `${day}th`;
                    const rem10 = day % 10;
                    if (rem10 === 1) return `${day}st`;
                    if (rem10 === 2) return `${day}nd`;
                    if (rem10 === 3) return `${day}rd`;
                    return `${day}th`;
                }

                function formatTradingDate(dateStr) {
                    if (!dateStr) {
                        return new Intl.DateTimeFormat('en-US', {
                            month: 'long',
                            day: 'numeric',
                            year: 'numeric',
                            timeZone: 'America/New_York',
                        }).format(new Date());
                    }

                    const [year, month, day] = dateStr.split('-').map(v => parseInt(v, 10));
                    const d = new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
                    const monthName = new Intl.DateTimeFormat('en-US', {
                        month: 'long',
                        timeZone: 'America/New_York',
                    }).format(d);
                    return `${monthName} ${ordinalDay(day)}, ${year}`;
                }

                function formatEntryTime(dateValue) {
                    const d = new Date(dateValue);
                    if (Number.isNaN(d.getTime())) return '-';
                    const timeText = d.toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                        second: '2-digit',
                        hour12: true,
                        timeZone: 'America/New_York',
                    });
                    return String(timeText).replace(/\s?[AP]M$/i, '');
                }

                const tradingDate = formatTradingDate(data.trading_date);
                if (data.is_fallback_day) {
                    heading.textContent = `📊 Most Recent Trading Day - ${tradingDate} 📊`;
                } else {
                    heading.textContent = `📊 Today's Trades - ${tradingDate} 📊`;
                }
                
                if (!data.trades || data.trades.length === 0) {
                    const todayPnlCard = document.getElementById('todayPnlCard');
                    const todayPnl = document.getElementById('todayPnl');
                    todayPnlCard.className = 'trade-summary-card neutral';
                    todayPnl.className = 'trade-summary-value total-pnl-today-neutral';
                    todayPnl.textContent = '$0.00 (+0.0%)';
                    container.innerHTML = '<div class="no-trades">📭 No trades in database</div>';
                    return;
                }
                
                const summary = data.summary || {};
                let html = '';
                const totalPnl = Number(summary.total_pnl || 0);
                const pnlClass = totalPnl > 0 ? 'winning' : totalPnl < 0 ? 'losing' : 'neutral';
                const totalReturnPct = Number(summary.total_return_pct || 0);
                const totalReturnPctText = `${totalReturnPct > 0 ? '+' : ''}${formatNumber(Math.abs(totalReturnPct), 1)}%`;
                const summaryColorClass = totalPnl > 0 ? 'positive' : totalPnl < 0 ? 'negative' : 'neutral';
                const todayPnlCard = document.getElementById('todayPnlCard');
                const todayPnl = document.getElementById('todayPnl');
                todayPnlCard.className = `trade-summary-card ${pnlClass}`;
                todayPnl.className = totalPnl === 0
                    ? 'trade-summary-value total-pnl-today-neutral'
                    : `trade-summary-value total-pnl-${summaryColorClass}`;
                const totalPnlText = totalPnl < 0
                    ? `($${Math.abs(totalPnl).toFixed(2)})`
                    : formatMoney(totalPnl);
                todayPnl.textContent = `${totalPnlText} (${totalReturnPctText})`;
                
                html += '<div class="trades-table-wrap"><table class="trades-table"><thead><tr>';
                html += '<th>Time</th><th>OPTION</th><th>#</th><th>Entry</th><th>Exit</th><th>Checklist</th><th>Phase</th><th>CQ</th><th>MAS</th><th>ABS</th><th>Conf</th><th>P&L</th><th>Exit</th>';
                html += '</tr></thead><tbody>';
                
                data.trades.forEach(trade => {
                    const entryTime = trade.entry_time ? formatEntryTime(trade.entry_time) : '-';
                    const exitTime = trade.exit_time ? formatTimeAMPM(trade.exit_time) : '-';
                    const timeRange = `${entryTime} - ${exitTime}`;
                    const pnl = trade.pnl || 0;
                    const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : 'neutral';
                    const strikePrice = Number(trade.strike_price);
                    const optionDirection = trade.direction || '-';
                    const optionLabel = Number.isFinite(strikePrice)
                        ? `$${formatNumber(strikePrice, strikePrice % 1 === 0 ? 0 : 3)} ${optionDirection}`
                        : optionDirection;
                    
                    html += '<tr>';
                    html += `<td data-label="Time">${timeRange}</td>`;
                    html += `<td data-label="Option"><span class="trade-direction ${trade.direction || ''}">${optionLabel}</span></td>`;
                    html += `<td data-label="#">${trade.contracts === null || trade.contracts === undefined ? '-' : trade.contracts}</td>`;
                    html += `<td data-label="Entry">${formatMoney(trade.entry_price || 0)}</td>`;
                    html += `<td data-label="Exit">${formatMoney(trade.exit_price || 0)}</td>`;
                    const entryGateRaw = trade.entry_gate_score;
                    const indicatorCountRaw = trade.indicator_count;
                    const indicatorTotalRaw = trade.indicator_total;
                    let indicators = '-';
                    if (entryGateRaw !== null && entryGateRaw !== undefined && !Number.isNaN(Number(entryGateRaw)) && Math.abs(Number(entryGateRaw) - Math.round(Number(entryGateRaw))) < 0.001) {
                        // Entry gate can include extra confirmation points (>5),
                        // but execution checklist pass/fail is out of 5.
                        const gateRounded = Math.round(Number(entryGateRaw));
                        const checklistPassed = Math.max(0, Math.min(5, gateRounded));
                        indicators = `${formatNumber(checklistPassed)} / 5`;
                    } else if (!(indicatorCountRaw === null || indicatorCountRaw === undefined || indicatorTotalRaw === null || indicatorTotalRaw === undefined)) {
                        indicators = `${formatNumber(indicatorCountRaw)} / ${formatNumber(indicatorTotalRaw)}`;
                    }
                    const cq = (trade.continuation_quality_score === null || trade.continuation_quality_score === undefined) ? '-' : formatNumber(trade.continuation_quality_score, 2);
                    const momentumPhase = String(trade.momentum_phase || '').replaceAll('_', ' ') || '-';
                    const mas = (trade.momentum_acceleration_score === null || trade.momentum_acceleration_score === undefined) ? '-' : formatNumber(trade.momentum_acceleration_score, 2);
                    const abs = (trade.absorption_score === null || trade.absorption_score === undefined) ? '-' : formatNumber(trade.absorption_score, 2);
                    const conf = (trade.confidence_score === null || trade.confidence_score === undefined) ? '-' : formatNumber(trade.confidence_score, 2);
                    html += `<td data-label="Checklist">${indicators}</td>`;
                    html += `<td data-label="Phase">${momentumPhase}</td>`;
                    html += `<td data-label="CQ">${cq}</td>`;
                    html += `<td data-label="MAS">${mas}</td>`;
                    html += `<td data-label="ABS">${abs}</td>`;
                    html += `<td data-label="Conf">${conf}</td>`;
                    const pnlPct = (trade.pnl_pct === null || trade.pnl_pct === undefined) ? null : Number(trade.pnl_pct);
                    let pnlPctText = '';
                    if (pnlPct !== null && !Number.isNaN(pnlPct)) {
                        if (pnlPct < 0) {
                            pnlPctText = ` (${formatNumber(Math.abs(pnlPct), 1)}%)`;
                        } else {
                            pnlPctText = ` - ${formatNumber(pnlPct, 1)}%`;
                        }
                    }
                    html += `<td data-label="P&L"><span class="trade-pnl ${pnlClass}">${formatMoney(pnl)}${pnlPctText}</span></td>`;
                    const rawReason = String(trade.exit_reason || '').toUpperCase();
                    let exitReason = '-';
                    const reasonMap = {
                        'STOP_LOSS': 'Stop',
                        'OPTION_STOP': 'Stop',
                        'STOP': 'Stop',
                        '3-5%': '4% Trail',
                        '4-5%': '4% Trail',
                        '4% TRAIL': '4% Trail',
                        '5-6%': '5% Trail',
                        '5-7%': '5% Trail',
                        '5% TRAIL': '5% Trail',
                        '6%+': '6%+ Trail',
                        '7%+': '6%+ Trail',
                        '6%+ TRAIL': '6%+ Trail',
                        '1-4% PROFIT': 'Stop',
                        'PROFIT_TAKER': 'Profit',
                        'TARGET_HIT': 'Target Hit',
                        'MANUAL_EXIT_LIMIT': 'Manual Exit (Limit)',
                        'MANUAL_EXIT_MARKET': 'Manual Exit (Market)',
                        'BROKER_RECONCILED_EXIT': 'Broker Reconciled Exit',
                        'PROTECTIVE_STOP_SYNC_FAILED': 'Protective Stop Sync Failed',
                    };

                    if (rawReason in reasonMap) {
                        exitReason = reasonMap[rawReason];
                    } else if (rawReason) {
                        const exitReasonRaw = rawReason.replaceAll('_', ' ').toLowerCase();
                        exitReason = exitReasonRaw.split(' ').filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                    }
                    html += `<td data-label="Exit">${trade.manual_label ? 'Mason' : exitReason}</td>`;
                    html += '</tr>';
                });
                
                html += '</tbody></table></div>';
                container.innerHTML = html;
                lastTradesRefreshMs = Date.now();
            } catch (err) {
                console.error('Error fetching trades:', err);
                document.getElementById('tradesContainer').innerHTML = '<div class="no-trades">Error loading trades</div>';
            } finally {
                tradesRefreshInFlight = false;
            }
        }

        // Initial load
        window.addEventListener('load', () => {
            becomeLeader(true);
            startLeaderHeartbeat();
            refreshPollingSchedule();
            refreshStatus();
            refreshLogs();
            updateTodaysTrades();
            updateIndicatorPerformance();
        });

        document.addEventListener('visibilitychange', () => {
            if (isDashboardVisible()) {
                becomeLeader(true);
            } else {
                releaseLeaderLease();
            }
            refreshPollingSchedule();

            if (!isDashboardVisible()) {
                return;
            }

            // Force immediate freshness when user returns to this tab.
            lastLogsRefreshMs = 0;
            lastTradesRefreshMs = 0;
            lastExecutionQualityRefreshMs = 0;
            lastDailyLearningRefreshMs = 0;
            lastIndicatorPerformanceRefreshMs = 0;
            refreshStatus();
            updateIndicatorPerformance();
        });

        window.addEventListener('storage', (event) => {
            if (event.key !== DASHBOARD_POLL_LEADER_KEY) {
                return;
            }
            if (isDashboardVisible()) {
                becomeLeader(false);
            }
        });

        window.addEventListener('beforeunload', () => {
            releaseLeaderLease();
        });
    </script>
</body>
</html>
"""


@app.route('/')
def dashboard():
    """Serve the main dashboard"""
    response = make_response(render_template_string(HTML_DASHBOARD))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ============================================================================
# CLI and Startup
# ============================================================================

def check_dependencies():
    """Verify all required dependencies are available"""
    missing = []

    if BOT_SCRIPT.name != EXPECTED_BOT_SCRIPT_NAME:
        missing.append(f"BOT_SCRIPT mismatch: expected {EXPECTED_BOT_SCRIPT_NAME}, got {BOT_SCRIPT.name}")
    
    try:
        import flask
    except ImportError:
        missing.append("flask")
    
    selected_python = resolve_bot_python()
    if selected_python is None:
        missing.append("stable bot python unavailable (venv missing or missing dependencies)")
    
    if not BOT_SCRIPT.exists():
        missing.append(EXPECTED_BOT_SCRIPT_NAME)
    
    return missing


if __name__ == '__main__':
    repo_path_ok, current_repo, expected_repo = _runtime_repo_path_allows_start()
    if not repo_path_ok:
        print("❌ CANONICAL REPO PATH CHECK FAILED")
        print(f"   current repo: {current_repo}")
        print(f"   required repo: {expected_repo}")
        print(f"   project root: {PROJECT_ROOT}")
        print("   Refusing to start cockpit from non-canonical repository.")
        sys.exit(2)

    # Check dependencies
    missing = check_dependencies()
    if missing:
        print("❌ MISSING DEPENDENCIES:")
        for item in missing:
            print(f"   - {item}")
        sys.exit(1)
    
    # Display startup info
    print("\n" + "="*70)
    print("🚀 McLeod SPY Options Trader Cockpit 1.4 🚀")
    print("="*70)
    print(f"Project: {PROJECT_ROOT}")
    print(f"Bot Script: {BOT_SCRIPT}")
    print(f"Bot Python Mode: {_bot_python_mode()}")
    print(f"Python (bot launch): {resolve_bot_python() or 'UNAVAILABLE'}")
    print(f"Log File: {BOT_LOG_FILE}")
    print("")
    dashboard_host = os.getenv("COCKPIT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    print(f"📱 Cockpit public URL: {COCKPIT_PUBLIC_URL}")
    print("🟢 Private origin is bound to localhost for Cloudflare Tunnel")
    print(f"🔁 Code sync watcher: {'ON' if (AUTO_REEXEC_ON_COCKPIT_CHANGE or AUTO_RESTART_BOT_ON_SCRIPT_CHANGE) else 'OFF'}")
    print("✋ Press Ctrl+C to stop the cockpit")
    print("="*70 + "\n")

    _ensure_code_sync_watcher_running()
    
    # Start Flask app
    # Note: Port 5000 is used by macOS AirPlay, so we use 5001
    app.run(
        host=dashboard_host,
        port=5001,
        debug=False,
        use_reloader=False
    )
