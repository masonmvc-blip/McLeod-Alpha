#!/usr/bin/env python3
"""
McLeod SPY Options Trader Alpha 1.3 - Local dashboard for live bot management
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
from urllib.error import URLError, HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import ssl
from zoneinfo import ZoneInfo
from flask import Flask, render_template_string, jsonify, request, make_response, redirect
from dotenv import load_dotenv
from schwab.auth import easy_client
from email.message import EmailMessage

try:
    import certifi
except Exception:
    certifi = None

load_dotenv(Path(__file__).parent / ".env")

# Account management
sys.path.insert(0, str(Path(__file__).parent))
from utils.account_manager import AccountManager
from utils.decision_contract import normalize_reason_text, reason_code_from_text, quote_state_from_age
from execution.equity_stream import SchwabEquityQuoteStream

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
STATUS_FILE = PROJECT_ROOT / ".control_center_status"
BOT_STOP_ALERT_STATE_FILE = PROJECT_ROOT / "data" / "bot_stop_alert_state.json"
CONTINUATION_STATUS_FILE = PROJECT_ROOT / "data" / "continuation_last_test.json"
CONTINUATION_CALIBRATION_FILE = PROJECT_ROOT / "data" / "reports" / "continuation_calibration.jsonl"
CONTROL_COMMAND_FILE = PROJECT_ROOT / "data" / "control_command.json"
BOT_MANUAL_STOP_MARKER_FILE = PROJECT_ROOT / "data" / "bot_manual_stop_marker.json"
LATEST_REJECTION_FILE = PROJECT_ROOT / "output" / "latest_rejection_reason.json"
RUNTIME_ALERT_FLAG_FILE = PROJECT_ROOT / "data" / "runtime_alert_flag.json"
INTERNET_QUALITY_HISTORY_FILE = PROJECT_ROOT / "data" / "reports" / "internet_quality_history.jsonl"
DAILY_TRADES_CHART_DIR = PROJECT_ROOT / "data" / "reports" / "daily_trades_charts"
DAILY_TRADES_CHART_LOG = PROJECT_ROOT / "data" / "reports" / "daily_trades_charts.jsonl"
PARITY_BASELINE_FILE = PROJECT_ROOT / "data" / "parity_baseline.json"
HEARTBEAT_STALE_SECONDS = int(os.getenv("BOT_HEARTBEAT_STALE_SECONDS", "180"))
HEARTBEAT_BANNER_STOP_SECONDS = int(os.getenv("BOT_HEARTBEAT_BANNER_STOP_SECONDS", "120"))
BOT_STOP_EMAIL_CONFIRMATION_SECONDS = int(os.getenv("BOT_STOP_EMAIL_CONFIRMATION_SECONDS", "20"))
OPTION_CONTRACT_MULTIPLIER = float(os.getenv("OPTION_CONTRACT_MULTIPLIER", "100"))
OPTION_COMMISSION_PER_CONTRACT_SIDE = float(os.getenv("OPTION_COMMISSION_PER_CONTRACT_SIDE", "0.665"))
MTD_PNL_CACHE_SECONDS = int(os.getenv("MTD_PNL_CACHE_SECONDS", "60"))
_BROKER_PNL_CACHE = {
    "timestamp": 0.0,
    "today": 0.0,
    "wtd": 0.0,
    "mtd": 0.0,
    "ytd": 0.0,
    "today_source": "schwab_transactions",
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

INTERNET_QUALITY_CACHE_SECONDS = int(os.getenv("INTERNET_QUALITY_CACHE_SECONDS", "30"))
INTERNET_QUALITY_TIMEOUT_SECONDS = float(os.getenv("INTERNET_QUALITY_TIMEOUT_SECONDS", "3.5"))
INTERNET_TREND_BAR_POINTS = max(10, int(os.getenv("INTERNET_TREND_BAR_POINTS", "60")))
STATUS_SNAPSHOT_CACHE_SECONDS = float(os.getenv("STATUS_SNAPSHOT_CACHE_SECONDS", "1.5"))
BROKER_PNL_REFRESH_SECONDS = float(os.getenv("BROKER_PNL_REFRESH_SECONDS", "15"))
CANONICAL_RUNTIME_HOST = os.getenv("MCLEOD_CANONICAL_RUNTIME_HOST", "Masons-iMac.local").strip()
CANONICAL_CONTROL_CENTER_URL = os.getenv(
    "MCLEOD_CANONICAL_CONTROL_CENTER_URL",
    "https://masons-imac.tailb88bd7.ts.net/",
).strip()
CANONICAL_REPO_BASENAME = os.getenv("MCLEOD_CANONICAL_REPO_BASENAME", "McLeod-Alpha-New").strip()
ENFORCE_CANONICAL_REPO_PATH = str(
    os.getenv("MCLEOD_ENFORCE_CANONICAL_REPO_PATH", "1")
).strip().lower() in {"1", "true", "yes", "on"}
REDIRECT_NONCANONICAL_CONTROL_CENTER = str(
    os.getenv("MCLEOD_REDIRECT_NONCANONICAL_CONTROL_CENTER", "1")
).strip().lower() not in {"0", "false", "no", "off", ""}
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
AUTO_REEXEC_ON_CONTROL_CENTER_CHANGE = str(
    os.getenv("AUTO_REEXEC_ON_CONTROL_CENTER_CHANGE", "1")
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
    if not BOT_STOP_ALERT_STATE_FILE.exists():
        return {}
    try:
        loaded = json.loads(BOT_STOP_ALERT_STATE_FILE.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _save_bot_stop_alert_state(state: dict):
    BOT_STOP_ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOT_STOP_ALERT_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _bot_stop_alert_recipient():
    return (
        os.getenv("CONTROL_CENTER_ALERT_EMAIL", "").strip()
        or os.getenv("DAILY_PNL_TO_EMAIL", "").strip()
        or "MasonMVC@gmail.com"
    )


def _send_bot_stop_email(subject: str, body: str):
    to_email = _bot_stop_alert_recipient()
    transport = os.getenv("CONTROL_CENTER_ALERT_TRANSPORT", "auto").strip().lower()

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
            print(f"Control Center stop email failed (Mail.app): {err}")
            return False
        except Exception as exc:
            print(f"Control Center stop email failed (Mail.app): {exc}")
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
            print(f"Control Center stop email failed (SMTP): {exc}")
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
        subject = f"Control Center: Bot stopped - {datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %I:%M %p ET')}"
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
    subject = f"Control Center: Bot stopped - {datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %I:%M %p ET')}"
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


_RUNNING_CONTROL_CENTER_SHA256 = _sha256_file(Path(__file__))
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

    disk_control_center_sha = _sha256_file(Path(__file__))
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
        "control_center_sha256": _RUNNING_CONTROL_CENTER_SHA256,
        "bot_script_sha256": _RUNNING_BOT_SCRIPT_SHA256,
        # Disk hashes expose pending sync/restart drift.
        "control_center_disk_sha256": disk_control_center_sha,
        "bot_script_disk_sha256": disk_bot_script_sha,
        "control_center_drift": bool(
            _RUNNING_CONTROL_CENTER_SHA256 and disk_control_center_sha and _RUNNING_CONTROL_CENTER_SHA256 != disk_control_center_sha
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
        "control_center_sha256": fingerprint.get("control_center_sha256"),
        "bot_script_sha256": fingerprint.get("bot_script_sha256"),
        "python_version": fingerprint.get("python_version"),
        "dependency_hash": fingerprint.get("dependency_hash"),
        "bot_python_mode": fingerprint.get("bot_python_mode"),
    }


def _save_parity_baseline(payload: dict):
    PARITY_BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PARITY_BASELINE_FILE.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _PARITY_BASELINE_CACHE["mtime"] = PARITY_BASELINE_FILE.stat().st_mtime
    _PARITY_BASELINE_CACHE["payload"] = dict(payload)


def _load_parity_baseline(force_reload: bool = False):
    try:
        if not PARITY_BASELINE_FILE.exists():
            _PARITY_BASELINE_CACHE["mtime"] = None
            _PARITY_BASELINE_CACHE["payload"] = None
            return None

        current_mtime = PARITY_BASELINE_FILE.stat().st_mtime
        if (
            not force_reload
            and _PARITY_BASELINE_CACHE.get("payload") is not None
            and _PARITY_BASELINE_CACHE.get("mtime") == current_mtime
        ):
            return dict(_PARITY_BASELINE_CACHE["payload"])

        loaded = json.loads(PARITY_BASELINE_FILE.read_text(encoding="utf-8"))
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
        for key in ("control_center_sha256", "bot_script_sha256", "python_version", "dependency_hash", "bot_python_mode")
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
        "control_center_sha256",
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

    # Keep cache in sync for existing downstream compatibility.
    _SPY_QUOTE_CACHE["timestamp"] = quote_ts
    _SPY_QUOTE_CACHE["price"] = float(spy_price)
    _SPY_QUOTE_CACHE["change"] = float(spy_change) if spy_change is not None else None
    _SPY_QUOTE_CACHE["change_pct"] = float(spy_change_pct) if spy_change_pct is not None else None
    _SPY_QUOTE_CACHE["as_of"] = quote_as_of_iso
    _SPY_QUOTE_CACHE["source"] = source


def _spy_tracker_mark_unavailable(now_ts: float):
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
    DAILY_TRADES_CHART_DIR.mkdir(parents=True, exist_ok=True)

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

    dated_svg.write_text(svg, encoding="utf-8")
    latest_svg.write_text(svg, encoding="utf-8")
    dated_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with DAILY_TRADES_CHART_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")

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
        INTERNET_QUALITY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with INTERNET_QUALITY_HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _load_recent_internet_quality_samples(max_samples: int = 120):
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

    successful = [s for s in samples if _sample_latency(s) is not None]
    records = []
    for s in successful:
        latency = _sample_latency(s)
        checked_at = str(s.get("checked_at") or "").strip()
        records.append({"latency": latency, "checked_at": checked_at})

    latencies = [r["latency"] for r in records if r.get("latency") is not None]
    latest_latency = _sample_latency(samples[-1])
    recent = latencies[-10:]
    previous = latencies[-20:-10]
    recent_avg = round(sum(recent) / len(recent), 1) if recent else None
    prev_avg = round(sum(previous) / len(previous), 1) if previous else None
    best = round(min(recent), 1) if recent else None
    worst = round(max(recent), 1) if recent else None
    recent_records = records[-INTERNET_TREND_BAR_POINTS:]
    recent_points = [round(float(r.get("latency") or 0.0), 1) for r in recent_records]
    recent_point_timestamps = [str(r.get("checked_at") or "") for r in recent_records]

    if recent_avg is None or prev_avg is None:
        trend = "INSUFFICIENT_DATA"
    else:
        delta = recent_avg - prev_avg
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

    first_ts = str(samples[0].get("checked_at") or "").strip()
    last_ts = str(samples[-1].get("checked_at") or "").strip()
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
        ts = str(sample.get("checked_at") or "").strip()
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

    # Prefer the interpreter currently running Control Center when it can run the bot.
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


def _runtime_host_allows_bot_start() -> tuple[bool, str, str]:
    current_host = socket.gethostname().strip()
    allowed_host = CANONICAL_RUNTIME_HOST
    allowed = not allowed_host or current_host.lower() == allowed_host.lower()
    return allowed, current_host, allowed_host


def _runtime_repo_path_allows_start() -> tuple[bool, str, str]:
    current_repo = PROJECT_ROOT.name.strip()
    expected_repo = CANONICAL_REPO_BASENAME.strip()
    if not ENFORCE_CANONICAL_REPO_PATH or not expected_repo:
        return True, current_repo, expected_repo
    allowed = current_repo.lower() == expected_repo.lower()
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


def start_bot():
    """Start the trading bot"""
    global _RUNNING_BOT_SCRIPT_SHA256

    repo_allowed, current_repo, expected_repo = _runtime_repo_path_allows_start()
    if not repo_allowed:
        return {
            "status": "error",
            "message": f"Bot start blocked in repo {current_repo}; canonical repo is {expected_repo}",
        }

    host_allowed, current_host, allowed_host = _runtime_host_allows_bot_start()
    if not host_allowed:
        return {
            "status": "error",
            "message": f"Bot start blocked on host {current_host}; canonical runtime host is {allowed_host}",
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
            BOT_MANUAL_STOP_MARKER_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        # Start bot in background, capturing output
        with open(BOT_LOG_FILE, 'w', buffering=1) as log_fp:
            process = subprocess.Popen(
                [str(selected_python), "-u", str(BOT_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                env=env,
                preexec_fn=os.setsid  # Create new process group for clean shutdown
            )
        
        # Save PID
        with open(BOT_PID_FILE, 'w') as f:
            f.write(str(process.pid))

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
    pid = get_bot_pid()
    if not pid or not _is_bot_process_running():
        BOT_PID_FILE.unlink(missing_ok=True)
        return {"status": "success", "message": "Bot already stopped"}

    try:
        pre_stop_status = parse_bot_status()
    except Exception:
        pre_stop_status = {"bot_running": True, "mode": "UNKNOWN", "last_error": None}
    
    try:
        # Mark this as an intentional operator stop so the monitor can avoid
        # auto-restarting on this specific SIGTERM.
        try:
            BOT_MANUAL_STOP_MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
            BOT_MANUAL_STOP_MARKER_FILE.write_text(
                json.dumps({
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                    "source": "control_center",
                    "pid": pid,
                }, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

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
        _maybe_notify_bot_stop(stop_status, reason=f"Manual stop requested from Control Center (PID {pid})", force=True)
        return {
            "status": "success",
            "message": "Bot stopped immediately"
        }
    
    except Exception as e:
        BOT_PID_FILE.unlink(missing_ok=True)
        return {"status": "success", "message": f"Bot stop cleanup completed ({str(e)})"}


def queue_exit_trade_command():
    """Queue a manual exit command for the running monitor process."""
    command = {
        "id": int(time.time() * 1000),
        "action": "EXIT_TRADE",
        "status": "PENDING",
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "source": "CONTROL_CENTER",
    }

    CONTROL_COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = CONTROL_COMMAND_FILE.with_suffix(".tmp")
    temp_path.write_text(json.dumps(command, indent=2), encoding="utf-8")
    os.replace(temp_path, CONTROL_COMMAND_FILE)
    return command


# ============================================================================
# Status Monitoring
# ============================================================================

def _active_stop_category(option_entry, current_mark=None, stop_price=None):
    """Map the open trade into the same stop ladder used by the live engine."""
    try:
        option_entry = float(option_entry or 0.0)
    except (TypeError, ValueError):
        option_entry = 0.0

    if option_entry <= 0:
        return None

    try:
        current_mark = float(current_mark) if current_mark is not None else None
    except (TypeError, ValueError):
        current_mark = None

    if current_mark is not None and current_mark > 0:
        profit_pct = ((current_mark - option_entry) / option_entry) * 100.0
        if profit_pct >= 8.0:
            return "8% Trail"
        if profit_pct >= 7.0:
            return "7% Trail"
        if profit_pct >= 6.0:
            return "6% Trail"
        if profit_pct >= 5.0:
            return "5% Trail"
        if profit_pct >= 4.0:
            return "4% Trail"
        if profit_pct >= 3.0:
            return "3% Stop"
        if profit_pct >= 2.0:
            return "2% Stop"
        return "Stop"

    try:
        stop_price = float(stop_price or 0.0)
    except (TypeError, ValueError):
        stop_price = 0.0

    if stop_price > 0:
        stop_return_pct = ((stop_price - option_entry) / option_entry) * 100.0
        if stop_return_pct >= 6.9:
            return "8% Trail"
        if stop_return_pct >= 5.4:
            return "7% Trail"
        if stop_return_pct >= 3.9:
            return "6% Trail"
        if stop_return_pct >= 2.3:
            return "5% Trail"
        if stop_return_pct >= 0.8:
            return "4% Trail"
        if stop_return_pct >= -1.0:
            return "3% Stop"
        if stop_return_pct >= -3.0:
            return "2% Stop"

    return "Stop"


def _compute_candle_indicator_snapshot():
    """Compute CALL/PUT indicator counts directly from recent candle history."""
    history_path = PROJECT_ROOT / "data" / "spy_1min_history.csv"
    if not history_path.exists():
        return None

    candles = []
    try:
        with history_path.open("r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    candles.append(
                        {
                            "datetime": str(row.get("datetime") or "").strip(),
                            "open": float(row.get("open")),
                            "high": float(row.get("high")),
                            "low": float(row.get("low")),
                            "close": float(row.get("close")),
                            "volume": float(row.get("volume") or 0.0),
                        }
                    )
                except (TypeError, ValueError):
                    continue
    except Exception:
        return None

    if len(candles) < 2:
        return None

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [max(0.0, c["volume"]) for c in candles]

    def _ema(values, span):
        alpha = 2.0 / (float(span) + 1.0)
        out = [float(values[0])]
        for value in values[1:]:
            out.append((float(value) * alpha) + (out[-1] * (1.0 - alpha)))
        return out

    ema10 = _ema(closes, 10)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd = [a - b for a, b in zip(ema12, ema26)]
    signal = _ema(macd, 9)
    macd_hist = [m - s for m, s in zip(macd, signal)]

    vwap = []
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    for i in range(len(candles)):
        typical = (highs[i] + lows[i] + closes[i]) / 3.0
        cumulative_pv += typical * volumes[i]
        cumulative_volume += volumes[i]
        vwap.append((cumulative_pv / cumulative_volume) if cumulative_volume > 0 else closes[i])

    i_last = len(candles) - 1
    i_prev = i_last - 1

    call_score = 0
    if closes[i_last] > vwap[i_last]:
        call_score += 1
    if ema10[i_last] > ema20[i_last] > ema50[i_last]:
        call_score += 2
    if ema10[i_last] > ema10[i_prev]:
        call_score += 1
    if macd_hist[i_last] > macd_hist[i_prev]:
        call_score += 1
    if closes[i_last] > highs[i_prev]:
        call_score += 1

    put_score = 0
    if closes[i_last] < vwap[i_last]:
        put_score += 1
    if ema10[i_last] < ema20[i_last] < ema50[i_last]:
        put_score += 2
    if ema10[i_last] < ema10[i_prev]:
        put_score += 1
    if macd_hist[i_last] < macd_hist[i_prev]:
        put_score += 1
    if closes[i_last] < lows[i_prev]:
        put_score += 1

    raw_total = 6
    indicator_total = 5
    call_score = int(round((max(0, min(raw_total, int(call_score))) / raw_total) * indicator_total))
    put_score = int(round((max(0, min(raw_total, int(put_score))) / raw_total) * indicator_total))

    latest_ts = str(candles[i_last].get("datetime") or "").strip() or None
    return {
        "call_passed": call_score,
        "put_passed": put_score,
        "total": indicator_total,
        "timestamp": latest_ts,
    }

def parse_bot_status():
    """Parse bot status from logs and position file"""
    active_log = _resolve_active_bot_log_file()
    candle_indicator_snapshot = _compute_candle_indicator_snapshot()

    def calculate_broker_period_pnl() -> tuple[float, float, float, float]:
        """Compute realized Today/WTD/MTD/YTD P&L, reconciling with completed local trades."""
        global _BROKER_PNL_CACHE

        from zoneinfo import ZoneInfo

        def _safe_amount(value, fallback=0.0):
            try:
                return round(float(value), 2)
            except (TypeError, ValueError):
                return round(float(fallback), 2)

        def _prefer_external(candidate, baseline):
            """Use external value unless it is a likely stale zero against non-zero baseline."""
            c_val = _safe_amount(candidate, baseline)
            b_val = _safe_amount(baseline, 0.0)
            if abs(c_val) > 1e-9 or abs(b_val) <= 1e-9:
                return c_val, True
            return b_val, False

        def _export_to_date(payload):
            if not payload:
                return None
            try:
                return datetime.strptime(str(payload.get("ToDate") or ""), "%m/%d/%Y").date()
            except Exception:
                return None

        def _api_period_net_after(start_dt, end_dt, symbol_scope, asset_scope):
            resp = client.get_transactions(
                account_hash,
                start_date=start_dt,
                end_date=end_dt,
                transaction_types=["TRADE", "RECEIVE_AND_DELIVER"],
            )
            resp.raise_for_status()
            transactions = resp.json() or []

            period_today = 0.0
            period_wtd = 0.0
            period_mtd = 0.0
            period_ytd = 0.0

            def _tx_timestamp(tx):
                for key in ("transactionDate", "tradeDate", "time"):
                    raw = tx.get(key)
                    if not raw:
                        continue
                    try:
                        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
                    except Exception:
                        try:
                            return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%S%z").astimezone(ZoneInfo("America/New_York"))
                        except Exception:
                            continue
                return None

            def _to_float(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def _parse_cash_amount(tx):
                value = _to_float((tx or {}).get("netAmount"))
                if value is not None:
                    return value
                return _to_float((tx or {}).get("amount"))

            for tx in transactions:
                tx_ts = _tx_timestamp(tx)
                tx_type = str(tx.get("type") or "").upper()
                if tx_type and tx_type != "TRADE":
                    continue

                transfer_items = tx.get("transferItems") or []
                in_scope = False
                for item in transfer_items:
                    item = item or {}
                    inst = item.get("instrument") or {}
                    asset_type = str(inst.get("assetType") or "").upper()
                    if asset_scope and asset_type != asset_scope:
                        continue
                    symbol = str(inst.get("symbol") or "").upper()
                    underlying = str(inst.get("underlyingSymbol") or "").upper()
                    if symbol_scope and (symbol_scope not in symbol and symbol_scope != underlying):
                        continue
                    in_scope = True
                    break
                if not in_scope:
                    continue

                amount = _parse_cash_amount(tx)
                if amount is None:
                    continue

                period_ytd += amount
                if tx_ts is not None and tx_ts >= week_start_dt:
                    period_wtd += amount
                if tx_ts is not None and tx_ts >= month_start_dt:
                    period_mtd += amount
                if tx_ts is not None and tx_ts >= day_start_dt:
                    period_today += amount

            return period_today, period_wtd, period_mtd, period_ytd

        def _closed_trade_signature():
            db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
            if not db_path.exists():
                return "0:none"
            con = None
            try:
                con = sqlite3.connect(str(db_path))
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                cur.execute(
                    """
                    SELECT COUNT(1) AS closed_count, MAX(exit_time) AS max_exit_time
                    FROM trade_log
                    WHERE exit_time IS NOT NULL AND TRIM(exit_time) <> ''
                    """
                )
                row = cur.fetchone() or {}
                return f"{int(row['closed_count'] or 0)}:{str(row['max_exit_time'] or 'none')}"
            except Exception:
                return "unknown"
            finally:
                if con is not None:
                    try:
                        con.close()
                    except Exception:
                        pass

        now_et = datetime.now(ZoneInfo("America/New_York"))
        today_date = now_et.date()
        today_key = today_date.isoformat()
        now_ts = time.time()

        if (
            _BROKER_PNL_CACHE.get("as_of_date") == today_key
            and (now_ts - float(_BROKER_PNL_CACHE.get("timestamp", 0.0))) < max(1.0, BROKER_PNL_REFRESH_SECONDS)
        ):
            return (
                float(_BROKER_PNL_CACHE.get("today", 0.0)),
                float(_BROKER_PNL_CACHE.get("wtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("mtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("ytd", 0.0)),
            )

        year_start_dt = now_et.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_dt = now_et.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day_start_dt = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start_dt = day_start_dt - timedelta(days=day_start_dt.weekday())

        closed_trade_signature = _closed_trade_signature()
        if (
            _BROKER_PNL_CACHE.get("as_of_date") == today_key
            and _BROKER_PNL_CACHE.get("closed_trade_signature") == closed_trade_signature
            and (now_ts - float(_BROKER_PNL_CACHE.get("timestamp", 0.0))) < MTD_PNL_CACHE_SECONDS
        ):
            return (
                float(_BROKER_PNL_CACHE.get("today", 0.0)),
                float(_BROKER_PNL_CACHE.get("wtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("mtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("ytd", 0.0)),
            )

        # Baseline from local completed trades so dashboard always reflects actual filled exits.
        local_today = _realized_spy_option_pnl_for_period(today_key, today_key)
        local_wtd = _realized_spy_option_pnl_for_period(week_start_dt.date().isoformat(), today_key)
        local_mtd = _realized_spy_option_pnl_for_period(month_start_dt.date().isoformat(), today_key)
        local_ytd = _realized_spy_option_pnl_for_period(year_start_dt.date().isoformat(), today_key)

        today_total = _safe_amount(local_today, 0.0)
        wtd_total = _safe_amount(local_wtd, 0.0)
        mtd_total = _safe_amount(local_mtd, 0.0)
        ytd_total = _safe_amount(local_ytd, 0.0)
        today_source = "trade_log_realized"
        wtd_source = "trade_log_realized"
        mtd_source = "trade_log_realized"
        ytd_source = "trade_log_realized"

        # Try to reconcile with Schwab transactions and exports; keep local non-zero totals if external is stale zero.
        try:
            from schwab.auth import easy_client

            account_hash = os.getenv("SCHWAB_ACCOUNT_HASH")
            app_key = os.getenv("SCHWAB_APP_KEY")
            app_secret = os.getenv("SCHWAB_APP_SECRET")
            callback = os.getenv("SCHWAB_CALLBACK_URL")
            if all([account_hash, app_key, app_secret, callback]):
                client = easy_client(
                    api_key=app_key,
                    app_secret=app_secret,
                    callback_url=callback,
                    token_path=_resolve_schwab_token_path(),
                    enforce_enums=False,
                )

                pnl_scope_symbol = str(os.getenv("BROKER_PNL_SCOPE_SYMBOL", "SPY")).strip().upper()
                pnl_scope_asset = str(os.getenv("BROKER_PNL_SCOPE_ASSET", "OPTION")).strip().upper()
                ext_today, ext_wtd, ext_mtd, ext_ytd = _api_period_net_after(
                    year_start_dt,
                    now_et,
                    pnl_scope_symbol,
                    pnl_scope_asset,
                )

                source_parts = ["asset", pnl_scope_asset or "ALL"]
                if pnl_scope_symbol:
                    source_parts.extend(["symbol", pnl_scope_symbol])
                source_suffix = "_" + "_".join(source_parts)
                ext_today_source = f"schwab_transactions_net{source_suffix}"
                ext_wtd_source = f"schwab_transactions_net{source_suffix}"
                ext_mtd_source = f"schwab_transactions_net{source_suffix}"
                ext_ytd_source = f"schwab_transactions_net{source_suffix}"

                _, export_payload = _load_latest_schwab_transaction_export()
                export_periods = _period_pnl_from_export_payload(export_payload, today_date)
                export_to_date = _export_to_date(export_payload)
                export_is_current = export_to_date is not None and export_to_date >= today_date
                export_is_stale_same_year = export_to_date is not None and export_to_date.year == today_date.year and export_to_date < today_date
                if export_periods and export_is_stale_same_year:
                    delta_start_dt = datetime.combine(export_to_date + timedelta(days=1), datetime.min.time(), tzinfo=ZoneInfo("America/New_York"))
                    if delta_start_dt <= now_et:
                        delta_today, delta_wtd, delta_mtd, delta_ytd = _api_period_net_after(
                            delta_start_dt,
                            now_et,
                            pnl_scope_symbol,
                            pnl_scope_asset,
                        )
                    else:
                        delta_today = delta_wtd = delta_mtd = delta_ytd = 0.0

                    ext_today = delta_today
                    ext_wtd = _safe_amount(export_periods.get("wtd"), 0.0) + delta_wtd
                    ext_mtd = _safe_amount(export_periods.get("mtd"), 0.0) + delta_mtd
                    ext_ytd = _safe_amount(export_periods.get("ytd"), 0.0) + delta_ytd
                    ext_today_source = f"schwab_history_export_plus_live_delta_through_{export_to_date.isoformat()}"
                    ext_wtd_source = ext_today_source
                    ext_mtd_source = ext_today_source
                    ext_ytd_source = ext_today_source
                if export_periods and export_is_current:
                    ext_today = _safe_amount(export_periods.get("today"), ext_today)
                    ext_wtd = _safe_amount(export_periods.get("wtd"), ext_wtd)
                    ext_mtd = _safe_amount(export_periods.get("mtd"), ext_mtd)
                    ext_today_source = "schwab_history_export"
                    ext_wtd_source = "schwab_history_export"
                    ext_mtd_source = "schwab_history_export"
                    if export_periods.get("covers_ytd"):
                        ext_ytd = _safe_amount(export_periods.get("ytd"), ext_ytd)
                        ext_ytd_source = "schwab_history_export"

                today_total, used_ext_today = _prefer_external(ext_today, today_total)
                wtd_total, used_ext_wtd = _prefer_external(ext_wtd, wtd_total)
                mtd_total, used_ext_mtd = _prefer_external(ext_mtd, mtd_total)
                ytd_total, used_ext_ytd = _prefer_external(ext_ytd, ytd_total)

                if used_ext_today:
                    today_source = ext_today_source
                if used_ext_wtd:
                    wtd_source = ext_wtd_source
                if used_ext_mtd:
                    mtd_source = ext_mtd_source
                if used_ext_ytd:
                    ytd_source = ext_ytd_source
        except Exception:
            pass

        _BROKER_PNL_CACHE = {
            "timestamp": now_ts,
            "today": today_total,
            "wtd": wtd_total,
            "mtd": mtd_total,
            "ytd": ytd_total,
            "as_of_date": today_key,
            "today_source": today_source,
            "wtd_source": wtd_source,
            "mtd_source": mtd_source,
            "ytd_source": ytd_source,
            "closed_trade_signature": closed_trade_signature,
        }

        if _BROKER_PNL_CACHE.get("last_preflight_date") != today_key:
            print(
                "BROKER PNL PREFLIGHT "
                f"| date={today_key} "
                f"| ptd={today_total:.2f} ({today_source}) "
                f"| wtd={wtd_total:.2f} ({wtd_source}) "
                f"| mtd={mtd_total:.2f} ({mtd_source}) "
                f"| ytd={ytd_total:.2f} ({ytd_source})"
            )
            _BROKER_PNL_CACHE["last_preflight_date"] = today_key

        return today_total, wtd_total, mtd_total, ytd_total

    todays_pnl, week_to_date_pnl, month_to_date_pnl, year_to_date_pnl = calculate_broker_period_pnl()
    now_et = datetime.now(EASTERN_TZ)
    nyse_today = now_et.date()
    nyse_is_trading_day = _is_nyse_trading_day(nyse_today)

    repo_path_ok, current_repo, expected_repo = _runtime_repo_path_allows_start()

    status = {
        "status_schema_version": "2026-07-18.1",
        "bot_running": is_bot_running(),
        "bot_running_effective": False,
        "bot_stale": None,
        "last_heartbeat_at": None,
        "heartbeat_age_seconds": None,
        "heartbeat_ok": None,
        "mode": "UNKNOWN",
        "account_verified": False,
        "account_number": "33310903",
        "account_nickname": AccountManager.get_display_name("33310903"),
        "broker_reconciliation": "UNKNOWN",
        "current_position": None,
        "current_position_side": None,
        "current_trade_pnl_dollars": None,
        "current_trade_pnl_pct": None,
        "current_trade_mark": None,
        "active_stop_category": None,
        "has_open_position": False,
        "protective_stop_status": None,
        "pending_orders": 0,
        "live_trade_count": 0,
        "todays_pnl": todays_pnl,
        "week_to_date_pnl": week_to_date_pnl,
        "month_to_date_pnl": month_to_date_pnl,
        "year_to_date_pnl": year_to_date_pnl,
        "broker_pnl_source": _BROKER_PNL_CACHE.get("today_source") or "schwab_transactions",
        "broker_pnl_as_of_date": _BROKER_PNL_CACHE.get("as_of_date"),
        "broker_pnl_preflight_date": _BROKER_PNL_CACHE.get("last_preflight_date"),
        "continuation_call_passed": 0,
        "continuation_put_passed": 0,
        "continuation_indicators_total": 5,
        "continuation_last_test_at": None,
        "last_decision": None,
        "last_decision_reason": None,
        "last_no_trade_call_reason": None,
        "last_no_trade_put_reason": None,
        "latest_rejection_reason": None,
        "trade_entry_enabled": False,
        "trade_entry_state": "DISABLED",
        "trade_entry_reason": "Bot is not running",
        "trade_entry_reason_code": "NOT_RUNNING",
        "trade_entry_reason_short": "Bot is not running",
        "decision_contract": {},
        "market_trend": "UNKNOWN",
        "spy_price": None,
        "spy_change": None,
        "spy_change_pct": None,
        "spy_quote_state": "UNAVAILABLE",
        "server_time_et": now_et.isoformat(),
        "nyse_is_trading_day": nyse_is_trading_day,
        "nyse_close_time_et": _nyse_regular_close_time_for_date(nyse_today) if nyse_is_trading_day else None,
        "bot_check_at": None,
        "bot_check_age_seconds": None,
        "log_age_seconds": None,
        "log_stale": None,
        "last_error": None,
        "last_update": datetime.now().isoformat(),
        "broker_pnl_source_file": None,
        "trade_log_email_armed": False,
        "trade_log_email_last_sent_date": None,
        "trade_log_schema_ok": False,
        "preopen_dry_run_status": "NOT_RUN",
        "preopen_dry_run_message": None,
        "ops_readiness": {},
        "internet_quality": {},
        "internet_quality_history": {},
        "network_primary_interface": None,
        "network_primary_port": None,
        "config_validation": {},
        "config_snapshot": {},
        "runtime_alert_active": False,
        "runtime_alert_message": None,
        "runtime_alert_severity": None,
        "runtime_alert_updated_at": None,
        "network_summary": None,
        "on_ethernet": None,
        "wifi_power": None,
        "internet_market_warning": False,
        "internet_market_warning_message": None,
        "problem_messages": [],
        "problem_summary": None,
        "parity_state": "UNKNOWN",
        "parity_summary": None,
        "parity_issues": [],
        "parity_baseline_path": str(PARITY_BASELINE_FILE),
        "parity_enforce_on_start": _env_flag("PARITY_ENFORCE_ON_START", default=True),
        "parity_block_start": False,
        "runtime_fingerprint": {},
        "canonical_runtime_host": CANONICAL_RUNTIME_HOST,
        "canonical_control_center_url": CANONICAL_CONTROL_CENTER_URL,
        "runtime_host_is_canonical": False,
        "runtime_repo_basename": current_repo,
        "canonical_repo_basename": expected_repo,
        "runtime_repo_path_ok": bool(repo_path_ok),
        "enforce_canonical_repo_path": bool(ENFORCE_CANONICAL_REPO_PATH),
        "redirect_noncanonical_control_center": REDIRECT_NONCANONICAL_CONTROL_CENTER,
        "bell_broadcast_id": int(_BELL_BROADCAST.get("id") or 0),
        "bell_broadcast_kind": str(_BELL_BROADCAST.get("kind") or "open"),
        "bell_broadcast_at": _BELL_BROADCAST.get("triggered_at"),
        "bell_broadcast_source": _BELL_BROADCAST.get("source"),
    }

    if candle_indicator_snapshot:
        status["continuation_call_passed"] = int(candle_indicator_snapshot.get("call_passed") or 0)
        status["continuation_put_passed"] = int(candle_indicator_snapshot.get("put_passed") or 0)
        status["continuation_indicators_total"] = int(candle_indicator_snapshot.get("total") or 5)
        status["continuation_last_test_at"] = candle_indicator_snapshot.get("timestamp")

    try:
        parity = _parity_status_snapshot()
        status["parity_state"] = str(parity.get("state") or "UNKNOWN")
        status["parity_summary"] = parity.get("summary")
        status["parity_issues"] = list(parity.get("issues") or [])
        status["parity_baseline_path"] = str(parity.get("baseline_path") or PARITY_BASELINE_FILE)
        status["runtime_fingerprint"] = dict(parity.get("runtime_fingerprint") or {})
        status["parity_block_start"] = bool(
            status.get("parity_enforce_on_start")
            and str(status.get("parity_state") or "UNKNOWN").upper() != "MATCH"
        )
        current_host = str((status.get("runtime_fingerprint") or {}).get("hostname") or "").strip()
        allowed_host = str(status.get("canonical_runtime_host") or "").strip()
        status["runtime_host_is_canonical"] = bool(
            current_host and allowed_host and current_host.lower() == allowed_host.lower()
        )
    except Exception:
        pass

    try:
        status["internet_quality"] = _get_internet_quality_snapshot()
    except Exception as e:
        status["internet_quality"] = {
            "quality": "UNKNOWN",
            "summary": f"Probe error: {e}",
            "avg_latency_ms": None,
            "max_latency_ms": None,
            "ok_count": 0,
            "target_count": len(INTERNET_QUALITY_TARGETS),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "targets": [],
        }
    try:
        status["internet_quality_history"] = _summarize_internet_quality_history(
            _load_recent_internet_quality_samples()
        )
    except Exception:
        status["internet_quality_history"] = {}

    try:
        network = _get_primary_network_status()
        status["network_primary_interface"] = network.get("primary_interface")
        status["network_primary_port"] = network.get("primary_port")
        status["network_summary"] = network.get("summary")
        status["on_ethernet"] = bool(network.get("on_ethernet"))
        status["wifi_power"] = network.get("wifi_power")
    except Exception:
        pass

    # SPY banner pricing now comes only from the dedicated background tracker.
    try:
        _ensure_spy_tracker_running()
        tracker = _spy_tracker_snapshot()
        status["spy_quote_refresh_seconds_current"] = round(float(SPY_TRACKER_REFRESH_SECONDS), 2)
        status["spy_price"] = tracker.get("price")
        status["spy_change"] = tracker.get("change")
        status["spy_change_pct"] = tracker.get("change_pct")
        status["spy_quote_stale"] = bool(tracker.get("stale"))
        status["spy_quote_age_seconds"] = tracker.get("quote_age_seconds")
        status["spy_quote_as_of"] = tracker.get("quote_as_of")
        status["spy_quote_state"] = str(tracker.get("state") or "UNAVAILABLE")
    except Exception:
        status["spy_quote_refresh_seconds_current"] = round(float(SPY_TRACKER_REFRESH_SECONDS), 2)
        status["spy_quote_stale"] = True
        status["spy_quote_state"] = "UNAVAILABLE"

    _apply_spy_close_baseline(status)

    # Trend hints from historical logs are intentionally disabled to avoid stale banner context.

    if active_log.exists():
        try:
            mtime = active_log.stat().st_mtime
            age = max(0.0, time.time() - mtime)
            status["last_heartbeat_at"] = datetime.fromtimestamp(mtime).isoformat()
            status["heartbeat_age_seconds"] = round(age, 1)
            status["bot_check_at"] = status["last_heartbeat_at"]
            status["bot_check_age_seconds"] = status["heartbeat_age_seconds"]
            status["log_age_seconds"] = status["heartbeat_age_seconds"]
            status["log_stale"] = bool(age > HEARTBEAT_BANNER_STOP_SECONDS)
            if status["bot_running"]:
                status["heartbeat_ok"] = age <= HEARTBEAT_STALE_SECONDS
            status["bot_stale"] = bool(age > HEARTBEAT_BANNER_STOP_SECONDS)
            status["bot_running_effective"] = bool(status["bot_running"] and age <= HEARTBEAT_BANNER_STOP_SECONDS)
        except Exception:
            pass
    else:
        status["bot_stale"] = bool(status["bot_running"])
        status["bot_running_effective"] = False
    
    # Try to load current position from disk
    try:
        position_file = PROJECT_ROOT / "data" / "open_position.json"
        if position_file.exists():
            with open(position_file, 'r') as f:
                pos_data = json.load(f)
                status["current_position_side"] = str(pos_data.get("direction") or "").upper() or None
                status["current_position"] = _position_label_from_option_symbol(
                    pos_data.get("option_symbol"),
                    fallback_direction=pos_data.get("direction"),
                )
                status["has_open_position"] = True

                option_symbol = str(pos_data.get("option_symbol") or "").strip()
                try:
                    option_entry = float(pos_data.get("option_entry") or 0.0)
                except (TypeError, ValueError):
                    option_entry = 0.0
                try:
                    quantity = abs(float(pos_data.get("quantity") or 0.0))
                except (TypeError, ValueError):
                    quantity = 0.0
                try:
                    option_stop = float(pos_data.get("option_stop") or 0.0)
                except (TypeError, ValueError):
                    option_stop = 0.0

                status["protective_stop_status"] = str(pos_data.get("protective_stop_status") or "").strip() or None
                status["active_stop_category"] = _active_stop_category(option_entry, stop_price=option_stop)

                if option_symbol and option_entry > 0 and quantity > 0:
                    try:
                        client = _get_broker_client()
                        resp = client.get_quote(option_symbol)
                        resp.raise_for_status()
                        payload = resp.json() or {}
                        symbol_blob = payload.get(option_symbol) or next(iter(payload.values()), {})
                        quote = symbol_blob.get("quote") or {}

                        def _to_float(value):
                            try:
                                return float(value)
                            except (TypeError, ValueError):
                                return None

                        current_mark = None
                        for candidate in (
                            quote.get("mark"),
                            quote.get("lastPrice"),
                            quote.get("bidPrice"),
                            quote.get("askPrice"),
                        ):
                            current_mark = _to_float(candidate)
                            if current_mark is not None and current_mark > 0:
                                break

                        if current_mark is not None and current_mark > 0:
                            pnl_dollars = (current_mark - option_entry) * quantity * OPTION_CONTRACT_MULTIPLIER
                            pnl_pct = ((current_mark - option_entry) / option_entry) * 100.0
                            status["current_trade_mark"] = round(current_mark, 3)
                            status["current_trade_pnl_dollars"] = round(pnl_dollars, 2)
                            status["current_trade_pnl_pct"] = round(pnl_pct, 1)
                            status["active_stop_category"] = _active_stop_category(
                                option_entry,
                                current_mark=current_mark,
                                stop_price=option_stop,
                            )
                    except Exception:
                        pass
    except Exception as e:
        pass

    # Load latest continuation cheat-sheet snapshot from strategy monitor.
    # Use as fallback only when candle-derived scoring is unavailable.
    try:
        if (not candle_indicator_snapshot) and CONTINUATION_STATUS_FILE.exists():
            snap = json.loads(CONTINUATION_STATUS_FILE.read_text())
            status["continuation_call_passed"] = int(((snap.get("call") or {}).get("passed") or 0))
            status["continuation_put_passed"] = int(((snap.get("put") or {}).get("passed") or 0))
            status["continuation_indicators_total"] = int(
                ((snap.get("call") or {}).get("total")
                or ((snap.get("put") or {}).get("total")
                or 5)
            ))
            status["continuation_last_test_at"] = snap.get("timestamp")
    except Exception:
        pass

    try:
        if LATEST_REJECTION_FILE.exists():
            latest_reject = json.loads(LATEST_REJECTION_FILE.read_text())
            reason_text = str((latest_reject or {}).get("exact_rejection_reason") or "").strip()
            side_text = str((latest_reject or {}).get("side") or "").strip().upper()
            if reason_text:
                if side_text in {"CALL", "PUT"}:
                    status["latest_rejection_reason"] = f"{side_text}: {reason_text}"
                else:
                    status["latest_rejection_reason"] = reason_text
    except Exception:
        pass

    try:
        export_path, _ = _load_latest_schwab_transaction_export()
        if export_path is not None:
            status["broker_pnl_source_file"] = export_path.name
    except Exception:
        pass

    try:
        email_state = _load_json_file(PROJECT_ROOT / "data" / "daily_trade_log_email_state.json") or {}
        status["trade_log_email_armed"] = str(os.getenv("DAILY_TRADE_LOG_EMAIL_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}
        status["trade_log_email_last_sent_date"] = email_state.get("last_sent_date")
    except Exception:
        pass

    try:
        db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
        if db_path.exists():
            with sqlite3.connect(str(db_path)) as con:
                cols = {row[1] for row in con.execute("PRAGMA table_info(trade_log)").fetchall()}
            status["trade_log_schema_ok"] = "absorption_score" in cols
    except Exception:
        pass

    try:
        dry_run_state = _load_json_file(PROJECT_ROOT / "data" / "preopen_dry_run_state.json") or {}
        status["preopen_dry_run_status"] = str(dry_run_state.get("status") or "NOT_RUN")
        status["preopen_dry_run_message"] = dry_run_state.get("message")
    except Exception:
        pass
    
    active_log = _resolve_active_bot_log_file()
    if not active_log.exists():
        return status
    
    try:
        with open(active_log, 'r') as f:
            lines = f.readlines()[-200:]  # Read last 200 lines for recent activity
            file_all = open(active_log, 'r').read()  # Read entire file for startup messages
        
        log_text = ''.join(lines)

        # Keep continuation indicator cards in sync with decision logs only when
        # candle-derived scoring is unavailable.
        if not candle_indicator_snapshot:
            current_indicator_section = None
            for raw_line in lines:
                line_text = str(raw_line or "").strip()
                upper_line = line_text.upper()
                if "CALL" in upper_line and "════" in line_text:
                    current_indicator_section = "CALL"
                    continue
                if "PUT" in upper_line and "════" in line_text:
                    current_indicator_section = "PUT"
                    continue

                score_match = re.search(r"Score:\s*(\d+)\s*/\s*(\d+)", line_text)
                if score_match and current_indicator_section in {"CALL", "PUT"}:
                    passed = int(score_match.group(1))
                    total = int(score_match.group(2))
                    status["continuation_indicators_total"] = total
                    if current_indicator_section == "CALL":
                        status["continuation_call_passed"] = passed
                    else:
                        status["continuation_put_passed"] = passed
        
        # Parse status indicators - startup messages that appear early, check entire file
        file_all_upper = file_all.upper()
        if "MODE: LIVE TRADING" in file_all_upper or "LIVE ENGINE CONFIGURED" in file_all_upper:
            status["mode"] = "LIVE TRADING"
        elif "MODE: PAPER TRADING" in file_all_upper:
            status["mode"] = "PAPER TRADING"
        
        # For account verification, check entire file since it only prints at startup
        if "Account Verified:" in file_all and "33310903" in file_all:
            status["account_verified"] = True
        
        # For broker reconciliation, check entire file since it's a startup process
        if "Broker reconciliation successful" in file_all:
            status["broker_reconciliation"] = "SUCCESS"
        elif "BROKER RECONCILIATION FAILED" in file_all:
            status["broker_reconciliation"] = "FAILED"
        elif "SAFE MODE ACTIVATED" in file_all:
            status["broker_reconciliation"] = "SAFE MODE"
        
        # Count pending orders
        if "pending SPY option order" in log_text:
            match = re.search(r'(\d+) pending SPY option order', log_text)
            if match:
                status["pending_orders"] = int(match.group(1))

        # Parse latest decision line + no-trade reason from recent logs.
        recent_lines = [ln.strip() for ln in lines if ln.strip()]

        # Parse market trend from explicit market line and normalize to
        # BULLISH/BEARISH/NEUTRAL for banner clarity.
        for line in reversed(recent_lines):
            text = str(line or "").strip()
            if not text or text.lower().startswith("volume trend:"):
                continue
            if not text.lower().startswith("trend:"):
                continue

            m_trend = re.search(r"^Trend:\s*([A-Z_]+)", text, re.IGNORECASE)
            if not m_trend:
                continue

            raw_trend = str(m_trend.group(1) or "UNKNOWN").upper()
            if raw_trend in {"BULL", "BULLISH", "UP", "INCREASING", "UPTREND"}:
                status["market_trend"] = "BULLISH"
            elif raw_trend in {"BEAR", "BEARISH", "DOWN", "DECREASING", "DOWNTREND"}:
                status["market_trend"] = "BEARISH"
            elif raw_trend in {"NEUTRAL", "SIDEWAYS", "RANGE", "FLAT"}:
                status["market_trend"] = "NEUTRAL"
            else:
                status["market_trend"] = "NEUTRAL"
            break

        def _extract_side_reasons(reason_text: str):
            text = str(reason_text or "").strip()
            if not text:
                return None, None

            call_reason = None
            put_reason = None

            m_call = re.search(r"CALL\s+(.+?)(?:;\s*PUT\s+|$)", text, re.IGNORECASE)
            if m_call:
                call_reason = m_call.group(1).strip()

            m_put = re.search(r"PUT\s+(.+?)(?:;\s*CALL\s+|$)", text, re.IGNORECASE)
            if m_put:
                put_reason = m_put.group(1).strip()

            # If reason is global (not side-tagged), show same reason for both sides.
            if call_reason is None and put_reason is None:
                return text, text

            return call_reason, put_reason

        for i in range(len(recent_lines) - 1, -1, -1):
            line_text = recent_lines[i]
            if line_text.startswith("NO TRADE "):
                status["last_decision"] = "NO_TRADE"
                for j in range(i + 1, min(i + 6, len(recent_lines))):
                    if recent_lines[j].startswith("Reason:"):
                        reason_text = recent_lines[j].replace("Reason:", "", 1).strip()
                        status["last_decision_reason"] = reason_text
                        call_reason, put_reason = _extract_side_reasons(reason_text)
                        status["last_no_trade_call_reason"] = call_reason
                        status["last_no_trade_put_reason"] = put_reason
                        break
                break
            if line_text.startswith("ENTER CALL ") or line_text.startswith("ENTER PUT "):
                status["last_decision"] = "ENTER"
                break
        
        # Get last actionable error (ignore DEBUG/state dump noise).
        error_markers = (
            "ERROR",
            "❌",
            "BROKER RECONCILIATION FAILED",
            "SAFE MODE ACTIVATED",
            "ENTRY BLOCKED",
            "blocked",
        )
        for line in reversed(lines):
            line_text = line.strip()
            if not line_text:
                continue
            if line_text.startswith("DEBUG") or "current_position = Position(" in line_text:
                continue
            if any(marker in line_text for marker in error_markers):
                status["last_error"] = line_text
                break

        # Compute quick, explicit trade-entry readiness state.
        enabled = True
        reason = "Ready for new entries"

        market_open_now = _is_market_hours_now_et()

        if not status["bot_running"]:
            enabled = False
            reason = "Bot is not running"
        elif not market_open_now:
            enabled = False
            reason = "Market Closed"
        elif status.get("heartbeat_ok") is False:
            enabled = False
            reason = "Bot heartbeat is stale"
        elif status.get("mode") != "LIVE TRADING":
            enabled = False
            reason = f"Mode is {status.get('mode', 'UNKNOWN')}"
        elif not status.get("account_verified"):
            enabled = False
            reason = "Trading account is not verified"
        elif status.get("broker_reconciliation") in {"FAILED", "SAFE MODE"}:
            enabled = False
            reason = f"Broker reconciliation is {status.get('broker_reconciliation')}"
        elif status.get("on_ethernet") is False:
            enabled = False
            reason = "Primary network is not Ethernet"
        elif status.get("current_position"):
            enabled = False
            reason = "Already in an open position"
        else:
            # Check only most recent lines so stale historical lock messages don't dominate.
            recent = [ln.strip() for ln in lines[-80:] if ln.strip()]
            for i in range(len(recent) - 1, -1, -1):
                text = recent[i]
                if "LIVE ENTRY DISABLED" in text:
                    enabled = False
                    reason = text.replace("🔒", "").strip()
                    for j in range(i + 1, min(i + 4, len(recent))):
                        if recent[j].startswith("Reason:"):
                            reason = recent[j].replace("Reason:", "").strip()
                            break
                    break
                if "ENTRY_PENDING LOCK ACTIVATED" in text:
                    enabled = False
                    reason = "Previous entry order is still pending fill"
                    break

        normalized_reason = normalize_reason_text(reason)
        status["trade_entry_enabled"] = enabled
        status["trade_entry_state"] = "ENABLED" if enabled else "DISABLED"
        status["trade_entry_reason"] = normalized_reason
        status["trade_entry_reason_code"] = reason_code_from_text(normalized_reason)
        status["trade_entry_reason_short"] = normalized_reason
        status["decision_contract"] = {
            "decision": "ENTER" if enabled else "NO_ENTRY",
            "reason": normalized_reason,
            "reason_code": status["trade_entry_reason_code"],
            "source": "control_center_trade_entry_gate",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    except Exception as e:
        status["last_error"] = f"Error reading status: {str(e)}"

    today_key = datetime.now(EASTERN_TZ).date().isoformat()
    preopen_status = str(status.get("preopen_dry_run_status") or "NOT_RUN").upper()
    config_validation = _validate_runtime_config()
    status["config_validation"] = config_validation
    status["config_snapshot"] = {
        "spy_quote_refresh_seconds_open": SPY_QUOTE_REFRESH_SECONDS_OPEN,
        "spy_quote_refresh_seconds_closed": SPY_QUOTE_REFRESH_SECONDS_CLOSED,
        "broker_pnl_refresh_seconds": BROKER_PNL_REFRESH_SECONDS,
        "status_snapshot_cache_seconds": STATUS_SNAPSHOT_CACHE_SECONDS,
    }
    runtime_alert = _load_runtime_alert_flag()
    status["runtime_alert_active"] = bool(runtime_alert.get("active"))
    status["runtime_alert_message"] = str(runtime_alert.get("message") or "").strip() or None
    status["runtime_alert_severity"] = str(runtime_alert.get("severity") or "").strip() or None
    status["runtime_alert_updated_at"] = runtime_alert.get("updated_at")
    status["ops_readiness"] = {
        "pnl_source_current": bool(status.get("broker_pnl_source_file")) and str(status.get("broker_pnl_as_of_date") or "") == today_key,
        "daily_email_armed": bool(status.get("trade_log_email_armed")),
        "no_orphan_orders": int(status.get("pending_orders") or 0) == 0,
        "local_position_clear": not bool(status.get("has_open_position")),
        "latest_export_found": bool(status.get("broker_pnl_source_file")),
        "schema_ok": bool(status.get("trade_log_schema_ok")),
        "preopen_dry_run_ok": preopen_status == "SUCCESS",
        "config_ok": bool(config_validation.get("ok")),
        "runtime_alert_clear": not bool(status.get("runtime_alert_active")),
    }
    status["problem_messages"] = _build_problem_messages(status)
    status["problem_summary"] = status["problem_messages"][0] if status["problem_messages"] else None
    hist = status.get("internet_quality_history") or {}
    internet_quality = str((status.get("internet_quality") or {}).get("quality") or "UNKNOWN").upper()
    stability = str(hist.get("stability") or "UNKNOWN").upper()
    if _is_market_hours_now_et() and (stability == "CHOPPY" or internet_quality in {"DEGRADED", "DOWN"}):
        status["internet_market_warning"] = True
        status["internet_market_warning_message"] = (
            f"Market-hours internet warning: {internet_quality}, {stability.replace('_', ' ').lower()} latency"
        )
    else:
        status["internet_market_warning"] = False
        status["internet_market_warning_message"] = None

    try:
        _maybe_notify_bot_stop(status)
    except Exception:
        pass
    
    return status


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
    week_start = today_date - timedelta(days=today_date.weekday())
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
        if row_date >= week_start:
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
            SELECT ROUND(SUM(COALESCE(option_pnl_dollars, pnl, 0)), 2) AS realized
            FROM trade_log
            WHERE exit_time IS NOT NULL
              AND substr(exit_time, 1, 10) >= ?
              AND substr(exit_time, 1, 10) <= ?
            """,
            (str(start_date), str(end_date)),
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


def _broker_transaction_trades_for_date(trading_date: str):
    """Build completed SPY option trades from Schwab transaction history for a day.

    Uses transaction cash flows (netAmount) as source of truth for per-trade P&L.
    """
    if not trading_date:
        return []

    try:
        target_day = datetime.strptime(str(trading_date), "%Y-%m-%d").date()
    except Exception:
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
        if tx_time is None or tx_time.date() != target_day:
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
            exit_reason = _classify_exit_reason(buy_event, sell_event)

            manual_label = "Mason" if _is_manual_exit_trade(sell_event, bot_order_ids) else ""
            entry_et = lot["entry_time"].astimezone(EASTERN_TZ)
            exit_et = event["time"].astimezone(EASTERN_TZ)
            manual_label = _manual_label_override(trading_date, entry_et, exit_et, manual_label)
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

    realized = _realized_spy_option_pnl_for_date(trading_date)
    if realized is not None:
        return round(float(realized), 2)

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
        for key in ("netAmount", "amount"):
            try:
                value = float((tx or {}).get(key))
                return value
            except (TypeError, ValueError):
                continue

        transfer_items = (tx or {}).get("transferItems") or []
        for item in transfer_items:
            try:
                value = float((item or {}).get("amount"))
                return value
            except (TypeError, ValueError):
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

            net = 0.0
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
                net += float(amount)
                matched += 1

            if matched > 0:
                return round(net, 2)
    except Exception:
        pass

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


def _backfill_trade_log_from_broker_rows(con, broker_rows):
    """Insert broker-derived trades missing from trade_log by broker order IDs."""
    if not broker_rows:
        return 0

    cur = con.cursor()
    inserted = 0

    for trade in broker_rows:
        entry_order_id = str(trade.get("broker_entry_order_id") or "")
        exit_order_id = str(trade.get("broker_exit_order_id") or "")
        if not entry_order_id and not exit_order_id:
            continue

        cur.execute(
            """
            SELECT 1
            FROM trade_log
            WHERE COALESCE(broker_entry_order_id, '') = ?
              AND COALESCE(broker_exit_order_id, '') = ?
            LIMIT 1
            """,
            (entry_order_id, exit_order_id),
        )
        if cur.fetchone() is not None:
            continue

        cur.execute(
            """
            INSERT INTO trade_log (
                entry_time,
                exit_time,
                direction,
                entry_price,
                exit_price,
                pnl,
                exit_reason,
                option_symbol,
                option_entry,
                option_exit,
                option_quantity,
                option_pnl_dollars,
                option_return,
                option_pnl_pct,
                broker_entry_order_id,
                broker_exit_order_id,
                feature_payload,
                entry_diagnostic_snapshot,
                exit_diagnostic_snapshot
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("entry_time"),
                trade.get("exit_time"),
                trade.get("direction"),
                trade.get("entry_price"),
                trade.get("exit_price"),
                trade.get("pnl"),
                trade.get("exit_reason"),
                trade.get("option_symbol"),
                trade.get("option_entry"),
                trade.get("option_exit"),
                trade.get("option_quantity"),
                trade.get("pnl"),
                None,
                None,
                entry_order_id,
                exit_order_id,
                None,
                None,
                None,
            ),
        )
        inserted += 1

    if inserted:
        con.commit()
    return inserted


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


def _classify_exit_reason(buy_event, sell_event):
    """Classify completed exit into canonical stop/trailing labels."""
    order_type = str(sell_event.get("order_type") or "").upper()
    try:
        entry_px = float(buy_event.get("price") or 0)
        exit_px = float(sell_event.get("price") or 0)
        realized_pct = ((exit_px - entry_px) / entry_px) * 100.0 if entry_px > 0 else 0.0
    except (TypeError, ValueError):
        realized_pct = 0.0

    # Canonical taxonomy requested by user: STOP, 4% TRAIL, 5% TRAIL, 6%+ TRAIL.
    # We classify by realized return so broker order-type differences do not drift labels.
    if realized_pct >= 6.0:
        return "6%+ TRAIL"
    if realized_pct >= 5.0:
        return "5% TRAIL"
    if realized_pct >= 4.0:
        return "4% TRAIL"
    if order_type in {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"}:
        # Mechanism-aware fallback: if a stop-order exit is still profitable but
        # below 4%, treat it as the first trailing tier rather than STOP.
        if realized_pct > 0.0:
            return "4% TRAIL"
        return "STOP"

    # Fallback for MARKET/other order types: infer from realized option move.
    return "STOP"


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
                    "exit_reason": _classify_exit_reason(buy, sell),
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
                AUTO_REEXEC_ON_CONTROL_CENTER_CHANGE
                and current_cc_sha
                and _RUNNING_CONTROL_CENTER_SHA256
                and current_cc_sha != _RUNNING_CONTROL_CENTER_SHA256
            ):
                print("Code sync watcher: control_center.py changed; reloading to newest version")
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
    """Start the bot"""
    result = start_bot()
    return jsonify(result)


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop the bot"""
    result = stop_bot()
    return jsonify(result)


@app.route('/api/exit-trade', methods=['POST'])
def api_exit_trade():
    """Queue a manual EXIT TRADE request for the running monitor."""
    try:
        status = parse_bot_status()
        if not status.get("bot_running"):
            return jsonify({"status": "error", "message": "Bot is not running"}), 400
        if status.get("mode") != "LIVE TRADING":
            return jsonify({"status": "error", "message": "EXIT TRADE is only available in LIVE TRADING mode"}), 400
        if not status.get("has_open_position"):
            return jsonify({"status": "error", "message": "No open trade to exit"}), 400

        command = queue_exit_trade_command()
        return jsonify({
            "status": "success",
            "message": "EXIT TRADE command queued. Bot will cancel stop and submit fast limit exit.",
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
    """Get all trades from the most recent trading day (defaults to today, falls back to previous day if no trades)"""
    try:
        import sqlite3
        from datetime import date
        
        db_path = PROJECT_ROOT / "data" / "mcleod_alpha.db"
        if not db_path.exists():
            return jsonify({"trades": [], "summary": {"total_trades": 0, "total_pnl": 0, "win_count": 0, "loss_count": 0}, "trading_date": None})
        
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        is_fallback_day = False
        trade_log_columns = {row[1] for row in cur.execute("PRAGMA table_info(trade_log)").fetchall()}
        absorption_select = "absorption_score" if "absorption_score" in trade_log_columns else "NULL AS absorption_score"
        
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
                {absorption_select}
            FROM trade_log
            WHERE substr(entry_time, 1, 10) = ?
            ORDER BY entry_time DESC
        """.format(absorption_select=absorption_select), (today,))
        
        trades = [dict(row) for row in cur.fetchall()]
        trades = _filter_synthetic_test_trade_rows(trades)
        trading_date = today
        
        # If no trades today, get the most recent trading day
        if not trades:
            is_fallback_day = True
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
                    {absorption_select}
                FROM trade_log
                WHERE substr(entry_time, 1, 10) = (SELECT MAX(substr(entry_time, 1, 10)) FROM trade_log)
                ORDER BY entry_time DESC
            """.format(absorption_select=absorption_select))
            trades = [dict(row) for row in cur.fetchall()]
            trades = _filter_synthetic_test_trade_rows(trades)
            if not trades:
                cur.execute(
                    """
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
                        {absorption_select}
                    FROM trade_log
                    ORDER BY entry_time DESC
                    """.format(absorption_select=absorption_select)
                )
                candidate_rows = _filter_synthetic_test_trade_rows([dict(row) for row in cur.fetchall()])
                candidate_by_day = {}
                for row in candidate_rows:
                    dt = _parse_iso_datetime(row.get("entry_time"))
                    if dt is None:
                        continue
                    day_key = dt.astimezone(EASTERN_TZ).date().isoformat()
                    candidate_by_day.setdefault(day_key, []).append(row)

                if candidate_by_day:
                    trading_date = max(candidate_by_day.keys())
                    trades = candidate_by_day.get(trading_date) or []
            
            # Get the actual trading date
            if trades:
                try:
                    parsed_dates = []
                    for trade in trades:
                        dt = _parse_iso_datetime(trade.get("entry_time"))
                        if dt is None:
                            continue
                        parsed_dates.append(dt.astimezone(EASTERN_TZ).date().isoformat())
                    trading_date = max(parsed_dates) if parsed_dates else None
                except Exception:
                    cur.execute("SELECT MAX(substr(entry_time, 1, 10)) as max_date FROM trade_log")
                    result = cur.fetchone()
                    trading_date = result['max_date'] if result else None

        # Canonical source for same-day rows: broker-filled pairings for today.
        # For fallback days, keep DB rows and canonicalize through export verification below.
        broker_trades = _broker_transaction_trades_for_date(trading_date) if trading_date else []
        using_broker_trades = bool(broker_trades)
        if using_broker_trades:
            try:
                _backfill_trade_log_from_broker_rows(con, broker_trades)
            except Exception:
                pass
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
                        feature_payload,
                        entry_diagnostic_snapshot,
                        exit_diagnostic_snapshot
                    FROM trade_log
                    WHERE substr(entry_time, 1, 10) = ?
                    """,
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

            option_entry = trade.get('option_entry')
            option_exit = trade.get('option_exit')
            option_qty = trade.get('option_quantity')

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
        schwab_day_total = _schwab_transaction_day_net_pnl(trading_date)
        if schwab_day_total is not None:
            total_pnl = float(schwab_day_total)
        elif trading_date == today:
            # Keep dashboard totals aligned: use the same canonical Today P&L
            # source as status when Schwab day-net lookup is temporarily unavailable.
            try:
                status_today_pnl = float(parse_bot_status().get('todays_pnl') or 0.0)
                total_pnl = status_today_pnl
            except Exception:
                pass
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
    <title>McLeod SPY Options Trader Alpha 1.3</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 1000px;
            width: 100%;
            padding: 30px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 14px;
            padding-bottom: 8px;
        }
        
        .header h1 {
            color: #333;
            font-size: 32px;
            margin-bottom: 5px;
        }

        .title-rockets {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            width: 100%;
        }
        
        .header p {
            color: #666;
            font-size: 14px;
        }

        .canonical-banner {
            margin: 14px auto 0;
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 700;
            line-height: 1.45;
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
            gap: 20px;
            margin-bottom: 30px;
        }

        .primary-status-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }

        .primary-status-grid .status-card {
            text-align: center;
        }
        
        .status-card {
            background: #f8f9fa;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
        }

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
            font-size: 18px;
            font-weight: 600;
            color: #333;
        }

        .position-summary-main.success { color: #28a745; }
        .position-summary-main.error { color: #dc3545; }
        .position-summary-main.warning { color: #ffc107; }
        .position-summary-main.info { color: #0066cc; }

        .position-summary-pnl {
            margin-top: 8px;
            font-size: 13px;
            line-height: 1.3;
            font-weight: 600;
        }

        .position-summary-pnl.success { color: #28a745; }
        .position-summary-pnl.error { color: #dc3545; }
        .position-summary-pnl.info { color: #0066cc; }

        .position-summary-stop {
            margin-top: 8px;
            font-size: 12px;
            line-height: 1.3;
            font-weight: 600;
            color: #495057;
        }

        .position-summary-stop.active { color: #1f2933; }
        
        .status-card h3 {
            color: #666;
            font-size: 12px;
            text-transform: uppercase;
            margin-bottom: 10px;
            letter-spacing: 1px;
        }
        
        .status-value {
            font-size: 18px;
            font-weight: 600;
            color: #333;
        }

        .status-value.compound-check {
            display: grid;
            gap: 4px;
            font-size: 14px;
            line-height: 1.2;
        }
        
        .status-value.success { color: #28a745; }
        .status-value.error { color: #dc3545; }
        .status-value.warning { color: #ffc107; }
        .status-value.info { color: #0066cc; }

        .trade-summary-value.total-pnl-positive { color: #28a745; }
        .trade-summary-value.total-pnl-negative { color: #dc3545; }
        .trade-summary-value.total-pnl-neutral { color: #999; }

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
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 18px;
            border: 1px solid transparent;
            text-align: center;
        }

        .trade-entry-banner .banner-title {
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 0.8px;
            margin-bottom: 4px;
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

        .trade-entry-banner .trend-tone-neutral {
            color: #1565c0;
        }

        .trade-entry-banner .trend-tone-bearish {
            color: #c62828;
        }

        .trade-entry-banner .trend-tone-bullish {
            color: #1f8f3a;
        }

        .trade-entry-banner .banner-meta {
            display: block;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.2px;
            opacity: 0.95;
            line-height: 1.35;
        }

        .trade-entry-banner .banner-meta-left {
            display: inline;
        }

        .trade-entry-banner .banner-meta-divider {
            display: none;
            margin: 0 4px;
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
            white-space: normal;
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
        
        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 30px;
        }

        button {
            padding: 12px 20px;
            font-size: 14px;
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
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            display: none;
        }
        
        .message.show { display: block; }
        .message.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .message.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        
        .logs {
            background: #1e1e1e;
            color: #00ff00;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 12px;
            padding: 15px;
            border-radius: 6px;
            max-height: 300px;
            overflow-y: auto;
            margin-top: 20px;
        }
        
        .logs-title {
            color: #999;
            font-weight: 600;
            margin-bottom: 10px;
        }

        .logs-meta {
            color: #aaa;
            font-size: 11px;
            margin-left: 8px;
            font-weight: 400;
        }
        
        .trades-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            font-size: 13px;
        }
        
        .trades-table thead {
            background: #f8f9fa;
            border-bottom: 2px solid #ddd;
        }
        
        .trades-table th {
            padding: 12px;
            text-align: center;
            font-weight: 600;
            color: #666;
            text-transform: uppercase;
            font-size: 11px;
        }
        
        .trades-table td {
            padding: 12px;
            text-align: center;
            border-bottom: 1px solid #eee;
        }
        
        .trades-table tr:hover {
            background: #f8f9fa;
        }
        
        .trade-direction.CALL { color: #28a745; font-weight: 600; }
        .trade-direction.PUT { color: #dc3545; font-weight: 600; }
        
        .trade-pnl.positive { color: #28a745; font-weight: 600; }
        .trade-pnl.negative { color: #dc3545; font-weight: 600; }
        .trade-pnl.neutral { color: #999; }
        
        .trades-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 15px;
        }
        
        .trade-summary-card {
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            padding: 15px;
            border-radius: 4px;
        }
        
        .trade-summary-card h4 {
            color: #666;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 8px;
            letter-spacing: 0.5px;
        }
        
        .trade-summary-value {
            font-size: 20px;
            font-weight: 600;
            color: #333;
        }
        
        .trade-summary-card.neutral {
            background: #f8f9fa;
            border-color: #ddd;
        }

        .exec-quality-wrap {
            margin-bottom: 20px;
        }

        .exec-quality-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
        }

        .exec-quality-card {
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            padding: 12px;
            border-radius: 4px;
        }

        .exec-quality-card h4 {
            color: #666;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 6px;
            letter-spacing: 0.4px;
        }

        .exec-quality-goal {
            display: inline-block;
            margin-top: 4px;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 11px;
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
            font-size: 18px;
            font-weight: 700;
            color: #333;
        }

        .exec-quality-sub {
            margin-top: 4px;
            font-size: 12px;
            color: #666;
            line-height: 1.35;
            white-space: pre-line;
        }

        .exec-quality-sub.success { color: #28a745; }
        .exec-quality-sub.error { color: #dc3545; }
        
        .no-trades {
            text-align: center;
            padding: 30px;
            color: #999;
        }

        .no-trades-today-banner {
            background: #fff3cd;
            border: 1px solid #ffe69c;
            color: #856404;
            border-radius: 6px;
            padding: 10px 12px;
            margin-bottom: 12px;
            font-size: 13px;
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
            font-size: 12px;
            margin-top: 20px;
        }

        .connectivity-card {
            text-align: left;
        }

        .connectivity-main {
            font-size: 20px;
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
            gap: 12px;
            flex-wrap: nowrap;
            margin-bottom: 8px;
        }

        .connectivity-summary-strip .connectivity-main {
            font-size: 18px;
            margin: 0;
            white-space: nowrap;
            text-align: center;
            flex: 1 1 auto;
        }

        .connectivity-summary-meta {
            flex: 0 0 auto;
            font-size: 11px;
            line-height: 1.35;
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
            margin-top: 8px;
            font-size: 12px;
            line-height: 1.45;
            color: #555;
        }

        .connectivity-alert {
            margin-top: 8px;
            padding: 6px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            line-height: 1.35;
            display: none;
        }

        .connectivity-alert.warn {
            display: block;
            background: #fff3cd;
            border: 1px solid #ffe69c;
            color: #8a6d00;
        }

        .connectivity-chart {
            margin-top: 8px;
            height: 34px;
            border: 1px solid #e2e6ea;
            border-radius: 6px;
            background: #fff;
            padding: 4px;
            display: flex;
            align-items: flex-end;
            gap: 2px;
            overflow: hidden;
            width: 100%;
        }

        .connectivity-chart-large {
            height: 54px;
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
            margin-top: 6px;
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            color: #6c757d;
            letter-spacing: 0.2px;
        }

        .connectivity-time-tick {
            flex: 0 0 auto;
            min-width: 34px;
            text-align: center;
            font-weight: 700;
            color: #495057;
        }

        .problem-list {
            margin-top: 8px;
            font-size: 11px;
            color: #777;
            line-height: 1.4;
        }

        .problem-item.bad { color: #b71c1c; }

        .exec-quality-trend-box {
            margin-top: 12px;
            background: #f8f9fa;
            border-left: 4px solid #007bff;
            padding: 12px;
            border-radius: 4px;
        }

        .exec-quality-trend-box h4 {
            color: #666;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 6px;
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

        .parity-warning {
            margin-top: 8px;
            padding: 6px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            line-height: 1.35;
            display: none;
        }

        .parity-warning.show {
            display: block;
        }

        .parity-warning.match {
            background: #eaf8ec;
            border: 1px solid #b8e3bf;
            color: #1f6a2e;
        }

        .parity-warning.mismatch {
            background: #fff3cd;
            border: 1px solid #ffe69c;
            color: #8a6d00;
        }

        .parity-warning.unset {
            background: #f8f9fa;
            border: 1px solid #e2e6ea;
            color: #495057;
        }

    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><span class="title-rockets"><span>🚀</span><span>McLeod SPY Options Trader Alpha 1.3</span><span>🚀</span></span></h1>
        </div>
        
        <div id="message" class="message"></div>

        <div id="tradeEntryBanner" class="trade-entry-banner disabled">
            <div class="banner-title" id="tradeEntryBannerTitle">⛔ TRADE ENTRY DISABLED ⛔</div>
            <div class="banner-meta" id="tradeEntryBannerMeta">
                <span class="banner-meta-left" id="tradeEntryBannerMetaLeft">❌ Broker UNKNOWN | ⚪ Unknown Account</span><span class="banner-meta-divider" id="tradeEntryBannerMetaDivider">|</span><span class="banner-meta-right" id="tradeEntryBannerMetaRight"></span>
            </div>
            <div class="parity-warning" id="parityWarning"></div>
        </div>
        
        <div class="status-grid primary-status-grid" id="statusGrid">
            <div class="status-card">
                <h3>CALL Indicators</h3>
                <div class="status-value" id="callIndicators">Loading...</div>
            </div>
            <div class="status-card" id="currentPositionCard">
                <h3>Current Position</h3>
                <div class="position-summary-main" id="currentPosition">Loading...</div>
                <div class="position-summary-pnl" id="currentTradePnl">Loading...</div>
                <div class="position-summary-stop" id="currentStopCategory"></div>
            </div>
            <div class="status-card">
                <h3>PUT Indicators</h3>
                <div class="status-value" id="putIndicators">Loading...</div>
            </div>
        </div>

        <div class="status-grid primary-status-grid">
            <div class="status-card" id="wtdPnlCard">
                <h3>Week-to-Date P&L</h3>
                <div class="status-value" id="wtdPnl">Loading...</div>
            </div>
            <div class="status-card">
                <h3>Month-to-Date P&L</h3>
                <div class="status-value" id="mtdPnl">Loading...</div>
            </div>
            <div class="status-card">
                <h3>Year-to-Date P&L</h3>
                <div class="status-value" id="ytdPnl">Loading...</div>
            </div>
        </div>

        <div class="controls">
            <button class="btn-primary" id="startBtn" onclick="startBot()">▶ Start Bot</button>
            <button class="btn-info" id="exitTradeBtn" onclick="exitTrade()" disabled>⏏ Exit Trade</button>
            <button class="btn-danger" id="stopBtn" onclick="stopBot()" disabled>⏹ Stop Bot</button>
        </div>
        
        <div style="margin-bottom: 30px;">
            <h2 id="tradesHeading" style="color: #333; font-size: 18px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #ddd; text-align: center;">📊 Today's Trades 📊</h2>
            <div id="tradesContainer">
                <div style="text-align: center; color: #999; padding: 20px;">Loading trades...</div>
            </div>
        </div>

        <div class="exec-quality-wrap">
            <div id="executionQualityContainer">
                <div style="text-align: center; color: #999; padding: 12px;">Loading execution quality...</div>
            </div>
        </div>
        
        <div class="logs">
            <div class="logs-title">📋 Recent Logs <span id="logsLastUpdated" class="logs-meta">(log updated: loading...)</span></div>
            <pre id="logsContent">Loading logs...</pre>
        </div>
        
        <div class="last-update">
            <span id="lastUpdate">Last updated: never</span>
            <span id="marketBellStatus" style="margin-left: 12px;">Bell status: waiting</span>
        </div>
    </div>
    
    <script>
        let statusRefreshInterval;
        let lastStatusSnapshot = null;
        let logsRefreshInFlight = false;
        let tradesRefreshInFlight = false;
        let executionQualityRefreshInFlight = false;
        let lastLogsRefreshMs = 0;
        let lastTradesRefreshMs = 0;
        let lastExecutionQualityRefreshMs = 0;
        const LOGS_REFRESH_INTERVAL_MS = 5000;
        const TRADES_REFRESH_INTERVAL_MS = 10000;
        const EXECUTION_QUALITY_REFRESH_INTERVAL_MS = 10000;
        const STATUS_REFRESH_VISIBLE_INTERVAL_MS = 1500;
        const STATUS_REFRESH_HIDDEN_INTERVAL_MS = 8000;
        const DASHBOARD_POLL_LEADER_KEY = 'mcleodAlphaDashboardPollLeader';
        const DASHBOARD_POLL_LEASE_MS = 5000;
        let isPollingLeader = false;
        let pollLeaderHeartbeatInterval = null;
        let previousHasOpenPosition = null;
        let activeBellPlaybackCount = 0;
        let lastBellBroadcastId = 0;
        let bellBroadcastPrimed = false;

        const MARKET_BELL_AUDIO_PATH = '/static/audio/nyse_bell.mp3';
        const MARKET_BELL_MAX_DURATION_MS = 5000;

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
            const bellStatusEl = document.getElementById('marketBellStatus');
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
                        if (bellStatusEl) {
                            bellStatusEl.textContent = `Bell status: ${bellKind} bell blocked (${contextLabel}) ${statusStamp} ET`;
                        }
                    });
                }
                if (bellStatusEl) {
                    bellStatusEl.textContent = `Bell status: ${bellKind} bell played (NYSE bell, ${contextLabel}) ${statusStamp} ET`;
                }
                return { played: true, source: 'NYSE bell' };
            } catch (_) {
                if (bellStatusEl) {
                    bellStatusEl.textContent = `Bell status: ${bellKind} bell error (${contextLabel}) ${statusStamp} ET`;
                }
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
            const bellStatusEl = document.getElementById('marketBellStatus');

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
                    if (bellStatusEl) {
                        bellStatusEl.textContent = bellResult.played
                            ? `Bell status: open bell played (${bellResult.source}) ${dateKey}`
                            : `Bell status: open bell blocked ${dateKey}`;
                    }
                }
            }

            if (inCloseWindow) {
                if (localStorage.getItem(closeSeenKey) !== '1') {
                    const bellResult = playMarketBell(false, { context: 'schedule' });
                    localStorage.setItem(closeSeenKey, '1');
                    if (bellStatusEl) {
                        bellStatusEl.textContent = bellResult.played
                            ? `Bell status: close bell played (${bellResult.source}) ${dateKey}`
                            : `Bell status: close bell blocked ${dateKey}`;
                    }
                }
            }
        }

        function playCashRegisterNoise(isBuy) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            try {
                const ctx = new AudioCtx();
                const start = ctx.currentTime;

                function tone(freq, at, duration, gainValue) {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'triangle';
                    osc.frequency.setValueAtTime(freq, at);
                    gain.gain.setValueAtTime(0.0001, at);
                    gain.gain.exponentialRampToValueAtTime(gainValue, at + 0.01);
                    gain.gain.exponentialRampToValueAtTime(0.0001, at + duration);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(at);
                    osc.stop(at + duration);
                }

                // Two-tone "cha-ching" effect. Slightly higher pitch for buy, lower for sell.
                const base = isBuy ? 880 : 740;
                tone(base, start, 0.12, 0.15);
                tone(base * 1.35, start + 0.09, 0.18, 0.18);
                setTimeout(() => {
                    try { ctx.close(); } catch (_) {}
                }, 500);
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
                second: '2-digit',
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
        
        async function startBot() {
            const btn = document.getElementById('startBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Starting...';
            
            try {
                const res = await fetch('/api/start', { method: 'POST' });
                const data = await res.json();
                
                showMessage(data.message, data.status === 'success' ? 'success' : 'error');
                
                if (data.status === 'success') {
                    // Start polling status
                    clearInterval(statusRefreshInterval);
                    statusRefreshInterval = setInterval(refreshStatus, 1000);
                }
            } catch (err) {
                showMessage(`Error: ${err.message}`, 'error');
            }
            
            btn.disabled = false;
            btn.innerHTML = '▶ Start Bot';
            refreshStatus();
        }
        
        async function stopBot() {
            const btn = document.getElementById('stopBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Stopping...';
            
            try {
                const res = await fetch('/api/stop', { method: 'POST' });
                const data = await res.json();
                
                showMessage(data.message, data.status === 'success' ? 'success' : 'error');
                clearInterval(statusRefreshInterval);
            } catch (err) {
                showMessage(`Error: ${err.message}`, 'error');
            }
            
            btn.disabled = false;
            btn.innerHTML = '⏹ Stop Bot';
            setTimeout(refreshStatus, 500);
        }

        async function exitTrade() {
            const btn = document.getElementById('exitTradeBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Exiting...';

            try {
                const res = await fetch('/api/exit-trade', { method: 'POST' });
                const data = await res.json();
                showMessage(data.message || 'Exit request sent', data.status === 'success' ? 'success' : 'error');
            } catch (err) {
                showMessage(`Error: ${err.message}`, 'error');
            }

            btn.innerHTML = '⏏ Exit Trade';
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
                
                // Update combined bot/reconciliation/mode status in entry banner.
                const reconState = String(status.broker_reconciliation || '').toUpperCase();
                const parityState = String(status.parity_state || 'UNKNOWN').toUpperCase();
                const parityEnforced = status.parity_enforce_on_start !== false;
                const parityBlockStart = !!status.parity_block_start;
                document.getElementById('startBtn').disabled = !!status.bot_running || parityBlockStart;
                document.getElementById('stopBtn').disabled = !status.bot_running;

                const canManualExit = !!(status.bot_running && status.mode === 'LIVE TRADING' && status.has_open_position);
                document.getElementById('exitTradeBtn').disabled = !canManualExit;
                
                // Build concise checklist summary for banner meta line.
                const modeText = String(status.mode || '').toUpperCase();
                const accountLabel = String(status.account_nickname || status.account_number || 'Unknown Account').trim();
                const accountDisplayLabel = 'Schwab 903';
                const liveTradingOk = modeText.includes('LIVE');
                const modeOk = liveTradingOk;
                const modeLabel = 'Live';
                const accountOk = accountLabel.length > 0 && !/^unknown account$/i.test(accountLabel);
                const explicitReconFailure = reconState === 'FAILED' || reconState === 'SAFE MODE';
                const inferredBrokerOk = !explicitReconFailure && !!status.account_verified && liveTradingOk;
                const reconOk = reconState === 'SUCCESS' || inferredBrokerOk;
                const parityOk = parityState === 'MATCH' && !parityBlockStart;
                const runtimeFingerprint = status.runtime_fingerprint || {};
                const runtimeHost = String(runtimeFingerprint.hostname || '').trim();
                const runtimeHostLower = runtimeHost.toLowerCase();
                let runtimeBadge = '☐ Runtime Unknown';
                if (runtimeHostLower.includes('imac') || runtimeHostLower.includes('desktop')) {
                    runtimeBadge = '🖥️ Desktop';
                } else if (runtimeHostLower.includes('macbook') || runtimeHostLower.includes('laptop')) {
                    runtimeBadge = '✅ 💻 laptop';
                }
                const checklistText = `${runtimeBadge} | ${modeOk ? '✅' : '☐'} ${modeLabel} | ${reconOk ? '✅' : '☐'} Broker | ${parityOk ? '✅' : '🛑'} Parity | ${accountOk ? '✅' : '☐'} ${accountDisplayLabel}`;

                // Trade entry readiness (fast and visible)
                const tradeEntryEnabled = !!status.trade_entry_enabled;
                const tradeEntryBanner = document.getElementById('tradeEntryBanner');
                const tradeEntryBannerTitle = document.getElementById('tradeEntryBannerTitle');
                const tradeEntryBannerMeta = document.getElementById('tradeEntryBannerMeta');
                const marketTrendRaw = String(status.market_trend || 'NEUTRAL').toUpperCase();
                const trendMap = {
                    'INCREASING': 'BULLISH',
                    'UP': 'BULLISH',
                    'BULL': 'BULLISH',
                    'BULLISH': 'BULLISH',
                    'DECREASING': 'BEARISH',
                    'DOWN': 'BEARISH',
                    'BEAR': 'BEARISH',
                    'BEARISH': 'BEARISH',
                    'NEUTRAL': 'NEUTRAL',
                    'SIDEWAYS': 'NEUTRAL',
                    'RANGE': 'NEUTRAL',
                    'FLAT': 'NEUTRAL',
                    'UNKNOWN': 'NEUTRAL',
                };
                const marketTrend = trendMap[marketTrendRaw] || 'NEUTRAL';
                let trendText = `${marketTrend}`;
                let trendToneClass = 'trend-tone-neutral';
                if (marketTrend === 'BEARISH') {
                    trendText = `🐻 BEARISH 🐻`;
                    trendToneClass = 'trend-tone-bearish';
                } else if (marketTrend === 'BULLISH') {
                    trendText = `🐂 BULLISH 🐂`;
                    trendToneClass = 'trend-tone-bullish';
                }

                const spyPrice = Number(status.spy_price);
                const spyChangePct = Number(status.spy_change_pct);
                const spyQuoteStale = !!status.spy_quote_stale;
                const spyQuoteAgeSeconds = Number(status.spy_quote_age_seconds);
                const spyQuoteStateRaw = String(status.spy_quote_state || 'UNAVAILABLE').toUpperCase();
                const tradeEntryReasonRaw = String(status.trade_entry_reason || '').toLowerCase();
                const tradeEntryReasonCodeRaw = String(status.trade_entry_reason_code || '').toUpperCase();
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
                if (candleDataStale) {
                    priceBannerHtml = '<span class="banner-price banner-tone-down">ERROR: STALE CANDLES</span>';
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
                        pctText = spyChangePct < 0 ? `(${pctRaw})` : pctRaw;
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
                const botCheckAt = status.bot_check_at || status.last_heartbeat_at || status.last_update || new Date().toISOString();
                const botCheckTimeText = formatTimeAMPM(botCheckAt);
                const trendWithTimestamp = `<span class="${trendToneClass}">${trendText}</span>`;

                if (tradeEntryEnabled) {
                    tradeEntryBanner.className = 'trade-entry-banner enabled';
                    tradeEntryBannerTitle.innerHTML = `${priceBannerHtml} | 💰 OPEN FOR BUSINESS 💰 | ${trendWithTimestamp}`;
                } else {
                    const bannerReason = String(status.trade_entry_reason || '').trim().toLowerCase();
                    const afterHoursRunning = !!status.bot_running && (
                        bannerReason.includes('marked closed') ||
                        bannerReason.includes('market closed') ||
                        bannerReason.includes('outside regular market hours')
                    );
                    if (status.has_open_position) {
                        tradeEntryBanner.className = 'trade-entry-banner disabled';
                        tradeEntryBannerTitle.textContent = '⛔ CURRENTLY IN A TRADE ⛔';
                    } else if (afterHoursRunning) {
                        tradeEntryBanner.className = 'trade-entry-banner after-hours';
                        tradeEntryBannerTitle.innerHTML = `${priceBannerHtml} | 🔵 MARKET CLOSED 🔵 | ${trendWithTimestamp}`;
                    } else {
                        tradeEntryBanner.className = 'trade-entry-banner disabled';
                        tradeEntryBannerTitle.innerHTML = `${priceBannerHtml} | ⛔ TRADE ENTRY DISABLED ⛔ | ${trendWithTimestamp}`;
                    }
                }
                const tradeEntryBannerMetaLeft = document.getElementById('tradeEntryBannerMetaLeft');
                const tradeEntryBannerMetaDivider = document.getElementById('tradeEntryBannerMetaDivider');
                const tradeEntryBannerMetaRight = document.getElementById('tradeEntryBannerMetaRight');
                if (tradeEntryBannerMetaLeft) {
                    tradeEntryBannerMetaLeft.textContent = checklistText;
                }
                if (tradeEntryBannerMetaRight) {
                    const timePart = botCheckTimeText !== '-' ? `${botCheckTimeText}` : '';
                    let clockAgeSeconds = Number(status.heartbeat_age_seconds);
                    if (!Number.isFinite(clockAgeSeconds) || clockAgeSeconds < 0) {
                        const parsedTs = Date.parse(botCheckAt);
                        if (Number.isFinite(parsedTs)) {
                            clockAgeSeconds = Math.max(0, (Date.now() - parsedTs) / 1000);
                        }
                    }

                    const isStaleClock = Number.isFinite(clockAgeSeconds) && clockAgeSeconds > 120;
                    const clockAgeMinutes = Number.isFinite(clockAgeSeconds)
                        ? Math.max(1, Math.floor(clockAgeSeconds / 60))
                        : null;
                    const rightMetaParts = [];
                    if (timePart) {
                        rightMetaParts.push(`🕯️ ${timePart}`);
                    }
                    if (isStaleClock) {
                        rightMetaParts.push(`🛑 ${clockAgeMinutes}m`);
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
                const parityWarningEl = document.getElementById('parityWarning');
                if (parityWarningEl) {
                    const issues = Array.isArray(status.parity_issues) ? status.parity_issues : [];
                    if (parityState === 'MISMATCH') {
                        const firstIssue = String(issues[0] || status.parity_summary || 'Runtime differs from baseline').trim();
                        const lockText = parityEnforced ? ' Start is locked until baseline is updated.' : '';
                        parityWarningEl.textContent = `⚠ ENVIRONMENT MISMATCH: ${firstIssue}.${lockText}`;
                        parityWarningEl.className = 'parity-warning show mismatch';
                    } else if (parityState === 'UNSET') {
                        const lockText = parityEnforced ? ' Start is locked until a baseline is set.' : '';
                        parityWarningEl.textContent = `Parity baseline not set yet.${lockText}`;
                        parityWarningEl.className = 'parity-warning show unset';
                    } else {
                        parityWarningEl.textContent = '';
                        parityWarningEl.className = 'parity-warning';
                    }
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
                    posEl.textContent = 'No Open Trade';
                    posEl.className = 'position-summary-main info';
                }

                const hasOpenPosition = !!status.has_open_position;
                if (previousHasOpenPosition !== null && previousHasOpenPosition !== hasOpenPosition) {
                    playCashRegisterNoise(hasOpenPosition);
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
                const isNoTrade = status.last_decision === 'NO_TRADE' || (!status.has_open_position && !tradeEntryEnabled);
                const tradeEntryReason = String(status.trade_entry_reason || '').trim();
                const startupGuardReason = /startup guard/i.test(tradeEntryReason) ? tradeEntryReason : '';

                function escapeHtml(value) {
                    return String(value || '')
                        .replaceAll('&', '&amp;')
                        .replaceAll('<', '&lt;')
                        .replaceAll('>', '&gt;')
                        .replaceAll('"', '&quot;')
                        .replaceAll("'", '&#39;');
                }

                function renderIndicatorText(passed, side) {
                    const base = `${passed}/${indicatorTotal} Passed`;
                    if (passed < 5) {
                        return base;
                    }

                    if (!isNoTrade) {
                        return base;
                    }
                    const conciseReasonRaw = startupGuardReason
                        || tradeEntryReason
                        || status.last_decision_reason
                        || 'No entry conditions met';
                    const conciseReason = escapeHtml(conciseReasonRaw);
                    if (conciseReason) {
                        return `${base}<br><span style="font-size:12px;font-weight:500;opacity:0.9;">${conciseReason}</span>`;
                    }
                    return base;
                }

                const callIndEl = document.getElementById('callIndicators');
                callIndEl.innerHTML = renderIndicatorText(callPassed, 'CALL');
                const strongThreshold = Math.max(1, indicatorTotal);
                const midThreshold = Math.max(0, indicatorTotal - 1);
                if (callPassed >= strongThreshold) {
                    callIndEl.className = 'status-value success';
                } else if (callPassed >= midThreshold) {
                    callIndEl.className = 'status-value info';
                } else {
                    callIndEl.className = 'status-value error';
                }

                const putIndEl = document.getElementById('putIndicators');
                putIndEl.innerHTML = renderIndicatorText(putPassed, 'PUT');
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
                const tradePnlDollars = status.current_trade_pnl_dollars;
                const tradePnlPct = status.current_trade_pnl_pct;
                const activeStopCategory = String(status.active_stop_category || '').trim();
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

                if (status.has_open_position && activeStopCategory && stopCategoryEl) {
                    stopCategoryEl.textContent = `Stop Category: ${activeStopCategory}`;
                    stopCategoryEl.className = 'position-summary-stop active';
                } else if (stopCategoryEl) {
                    stopCategoryEl.textContent = '';
                    stopCategoryEl.className = 'position-summary-stop';
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
                
                // Update timestamp
                document.getElementById('lastUpdate').textContent = 
                    'Last updated: ' + formatTimeAMPM(new Date());
                
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
                const avgLatency = internet.avg_latency_ms;
                const onEthernet = snapshot.on_ethernet === true;
                const onWifi = snapshot.on_ethernet === false;
                const connectionSource = onEthernet ? 'Ethernet' : (onWifi ? 'Wi-Fi' : 'Unknown');

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
                const internetIcon = internetQualityIcon(internetQuality);
                const internetTitle = internetQuality === 'EXCELLENT'
                    ? `${internetIcon} ${safeEscape(internetQuality)} ${internetIcon}`
                    : (internetIcon ? `${internetIcon} ${safeEscape(internetQuality)}` : safeEscape(internetQuality));
                const latencyText = avgLatency !== null && avgLatency !== undefined
                    ? `${safeEscape(Number(avgLatency).toFixed(0))} MS`
                    : 'Latency unavailable';
                const connectionText = connectionSource;

                const pointsRaw = Array.isArray(history.recent_points_ms) ? history.recent_points_ms : [];
                const pointTimestampsRaw = Array.isArray(history.recent_point_timestamps) ? history.recent_point_timestamps : [];
                const points = [...pointsRaw].reverse();
                const pointTimestamps = [...pointTimestampsRaw].reverse();
                html += '<div class="exec-quality-trend-box">';
                html += `<div class="connectivity-summary-strip"><div class="connectivity-summary-meta left">${latencyText}</div><div class="connectivity-main ${internetTone}">${internetTitle}</div><div class="connectivity-summary-meta right">${safeEscape(connectionText)}</div></div>`;
                if (snapshot.internet_market_warning) {
                    html += `<div class="connectivity-alert warn">${safeEscape(String(snapshot.internet_market_warning_message || 'Market-hours internet warning'))}</div>`;
                }
                if (points.length >= 2) {
                    const pMin = Math.min(...points);
                    const pMax = Math.max(...points);
                    const spread = Math.max(1, pMax - pMin);
                    const chartHtml = points.map((value) => {
                        const n = Number(value || 0);
                        const scaled = 8 + Math.round(((n - pMin) / spread) * 44);
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

                const tradingDate = formatTradingDate(data.trading_date);
                if (data.is_fallback_day) {
                    heading.textContent = `📊 Most Recent Trading Day - ${tradingDate} 📊`;
                } else {
                    heading.textContent = `📊 Today's Trades - ${tradingDate} 📊`;
                }
                
                if (!data.trades || data.trades.length === 0) {
                    container.innerHTML = '<div class="no-trades">📭 No trades in database</div>';
                    return;
                }
                
                const summary = data.summary || {};
                let html = '';
                if (data.is_fallback_day) {
                    html += '<div class="no-trades-today-banner">No trades yet today - showing most recent trading day</div>';
                }
                html += '<div class="trades-summary">';
                const totalPnl = Number(summary.total_pnl || 0);
                const pnlClass = totalPnl > 0 ? 'winning' : totalPnl < 0 ? 'losing' : 'neutral';
                const totalReturnPct = Number(summary.total_return_pct || 0);
                const totalReturnPctText = `${totalReturnPct >= 0 ? '+' : '-'}${formatNumber(Math.abs(totalReturnPct), 1)}%`;
                const summaryColorClass = totalPnl > 0 ? 'positive' : totalPnl < 0 ? 'negative' : 'neutral';
                html += `<div class="trade-summary-card neutral"><h4>Total Trades</h4><div class="trade-summary-value">${formatNumber(summary.total_trades || 0)} Trades (${formatNumber(summary.win_rate || 0, 1)}%)</div></div>`;
                html += `<div class="trade-summary-card ${pnlClass}"><h4>Today's P&L</h4><div class="trade-summary-value total-pnl-${summaryColorClass}">${formatMoney(totalPnl)} (${totalReturnPctText})</div></div>`;
                
                html += `<div class="trade-summary-card neutral"><h4>Wins</h4><div class="trade-summary-value">${formatNumber(summary.win_count || 0)}</div></div>`;
                html += `<div class="trade-summary-card neutral"><h4>Losses</h4><div class="trade-summary-value">${formatNumber(summary.loss_count || 0)}</div></div>`;
                html += '</div>';
                
                html += '<table class="trades-table"><thead><tr>';
                html += '<th>Time</th><th>OPTION</th><th>Contracts</th><th>Entry</th><th>Exit</th><th>Entry Checklist</th><th>Stage</th><th>CQ</th><th>MAS</th><th>ABS</th><th>Conf</th><th>P&L</th><th>Exit Reason</th>';
                html += '</tr></thead><tbody>';
                
                data.trades.forEach(trade => {
                    // Use shared AM/PM formatter so trade time stays in regular time format.
                    const entryTime = trade.entry_time ? formatTimeAMPM(trade.entry_time) : '-';
                    const exitTime = trade.exit_time ? formatTimeAMPM(trade.exit_time) : '-';
                    const timeRange = `${entryTime} - ${exitTime}`;
                    const pnl = trade.pnl || 0;
                    const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : 'neutral';
                    
                    html += '<tr>';
                    html += `<td>${timeRange}</td>`;
                    html += `<td><span class="trade-direction ${trade.direction || ''}">${trade.direction || '-'}</span></td>`;
                    html += `<td>${trade.contracts === null || trade.contracts === undefined ? '-' : trade.contracts}</td>`;
                    html += `<td>${formatMoney(trade.entry_price || 0)}</td>`;
                    html += `<td>${formatMoney(trade.exit_price || 0)}</td>`;
                    const stage = (trade.trend_stage === null || trade.trend_stage === undefined) ? '-' : String(trade.trend_stage);
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
                    const mas = (trade.momentum_acceleration_score === null || trade.momentum_acceleration_score === undefined) ? '-' : formatNumber(trade.momentum_acceleration_score, 2);
                    const abs = (trade.absorption_score === null || trade.absorption_score === undefined) ? '-' : formatNumber(trade.absorption_score, 2);
                    const conf = (trade.confidence_score === null || trade.confidence_score === undefined) ? '-' : formatNumber(trade.confidence_score, 2);
                    html += `<td>${indicators}</td>`;
                    html += `<td>${stage}</td>`;
                    html += `<td>${cq}</td>`;
                    html += `<td>${mas}</td>`;
                    html += `<td>${abs}</td>`;
                    html += `<td>${conf}</td>`;
                    const pnlPct = (trade.pnl_pct === null || trade.pnl_pct === undefined) ? null : Number(trade.pnl_pct);
                    let pnlPctText = '';
                    if (pnlPct !== null && !Number.isNaN(pnlPct)) {
                        if (pnlPct < 0) {
                            pnlPctText = ` (${formatNumber(Math.abs(pnlPct), 1)}%)`;
                        } else {
                            pnlPctText = ` - ${formatNumber(pnlPct, 1)}%`;
                        }
                    }
                    html += `<td><span class="trade-pnl ${pnlClass}">${formatMoney(pnl)}${pnlPctText}</span></td>`;
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
                    html += `<td>${trade.manual_label ? 'Mason' : exitReason}</td>`;
                    html += '</tr>';
                });
                
                html += '</tbody></table>';
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
            updateExecutionQuality(lastStatusSnapshot);
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
            refreshStatus();
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
    canonical_host = (urlsplit(CANONICAL_CONTROL_CENTER_URL).hostname or "").strip().lower()
    incoming_host = str(request.headers.get("X-Forwarded-Host") or request.host or "").strip().lower()
    incoming_host = incoming_host.split(",", 1)[0].strip()
    if "]" in incoming_host and incoming_host.startswith("["):
        incoming_host = incoming_host.rsplit(":", 1)[0]
        incoming_host = incoming_host.lstrip("[").rstrip("]")
    else:
        incoming_host = incoming_host.split(":", 1)[0].strip()

    if (
        REDIRECT_NONCANONICAL_CONTROL_CENTER
        and canonical_host
        and incoming_host
        and incoming_host != canonical_host
    ):
        canonical_base = CANONICAL_CONTROL_CENTER_URL.rstrip("/")
        target_url = f"{canonical_base}{request.path}"
        if request.query_string:
            target_url = f"{target_url}?{request.query_string.decode('utf-8', errors='ignore')}"
        return redirect(target_url, code=308)

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
        print("   Refusing to start control center from non-canonical repository.")
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
    print("🚀 McLeod SPY Options Trader Alpha 1.3 🚀")
    print("="*70)
    print(f"Project: {PROJECT_ROOT}")
    print(f"Bot Script: {BOT_SCRIPT}")
    print(f"Bot Python Mode: {_bot_python_mode()}")
    print(f"Python (bot launch): {resolve_bot_python() or 'UNAVAILABLE'}")
    print(f"Log File: {BOT_LOG_FILE}")
    print("")
    dashboard_host = os.getenv("CONTROL_CENTER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    print(f"📱 Dashboard URL (canonical): {CANONICAL_CONTROL_CENTER_URL}")
    if REDIRECT_NONCANONICAL_CONTROL_CENTER:
        print("🔒 Local non-canonical dashboard access redirects to canonical URL")
    else:
        print("🟢 Local non-canonical dashboard access is allowed (redirect disabled)")
    print(f"🔁 Code sync watcher: {'ON' if (AUTO_REEXEC_ON_CONTROL_CENTER_CHANGE or AUTO_RESTART_BOT_ON_SCRIPT_CHANGE) else 'OFF'}")
    print("✋ Press Ctrl+C to stop the control center")
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
