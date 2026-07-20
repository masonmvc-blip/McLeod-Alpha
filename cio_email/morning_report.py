#!/usr/bin/env python3
"""McLeod Morning CIO report runner.

This module builds an independent morning portfolio report, optionally
refreshes the latest Schwab snapshot, and sends the result through Gmail SMTP
with a Microsoft Outlook fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import smtplib
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as datetime_time, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from dotenv import load_dotenv

from engine.portfolio_engine import PortfolioEngine, RESEARCH_NEEDED
from engine.data_sources.transcript_source import TranscriptDataSource
from engine.memory import get_memory


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = DATA_DIR / "reports" / "morning_cio_email"
ARCHIVE_DIR = REPORT_DIR / "archive"
LATEST_HTML = REPORT_DIR / "latest_morning_cio_report.html"
LATEST_TEXT = REPORT_DIR / "latest_morning_cio_report.txt"
LATEST_JSON = REPORT_DIR / "latest_morning_cio_report.json"
DELIVERY_REGISTRY_PATH = REPORT_DIR / "delivery_registry.jsonl"
LEGACY_MARKDOWN_PATH = PROJECT_ROOT / "reports" / "morning_cio_report_latest.md"
STATE_PATH = REPORT_DIR / "latest_morning_cio_state.json"
RUN_LOG_PATH = LOG_DIR / "morning_cio_email.jsonl"
LOCK_PATH = LOG_DIR / "morning_cio_email.lock"

CHICAGO_TZ = ZoneInfo("America/Chicago")
NEW_YORK_TZ = ZoneInfo("America/New_York")
CALENDAR = xcals.get_calendar("XNYS")

LIVE_REFRESH_TIMEOUT_SECONDS = 180
SMTP_TIMEOUT_SECONDS = 20
SMTP_MAX_ATTEMPTS = 3
SMTP_BACKOFF_SECONDS = 2
LOCK_STALE_SECONDS = 6 * 60 * 60
NEWS_LOOKBACK_DAYS = 3
EIPV_ALLOCATION = 1000.0
CRITICAL_RESEARCH_FIELDS = {
    "business_quality",
    "valuation",
    "expected_alpha",
    "expected_2yr_cagr",
    "expected_10yr_cagr",
}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CHICAGO_TZ)
        return parsed
    except Exception:
        return None


def _timestamp_stale(value: Any, max_age_hours: int) -> bool:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return True
    age = _now_ct().astimezone(parsed.tzinfo) - parsed
    return age.total_seconds() > max(1, max_age_hours) * 3600


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


_load_env()


@dataclass
class Section:
    title: str
    text: str
    html: str


@dataclass
class Gap:
    scope: str
    subject: str
    field_name: str
    source_expected: str
    last_updated: str
    status: str
    impact: str
    affected_calculation: str
    next_fix: str
    latest_input_age_hours: str = "n/a"
    blocks_eipv: bool = False


@dataclass
class NewsFinding:
    symbol: str
    status: str
    docs: List[Dict[str, Any]] = field(default_factory=list)
    source_timestamp: str = ""
    source_urls: List[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ReportBundle:
    report_date: str
    generated_at: str
    data_as_of: str
    source_label: str
    stale: bool
    stale_reason: str
    account_display: str
    account_type: str
    metrics: Dict[str, Any]
    core_rankings: List[Dict[str, Any]]
    eipv_rankings: List[Dict[str, Any]]
    target_weights: List[Dict[str, Any]]
    replacement_candidates: List[Dict[str, Any]]
    options_positions: List[Dict[str, Any]]
    phase2_context: Dict[str, Any]
    thesis_changes: List[Dict[str, Any]]
    news_status: str
    news_findings: List[NewsFinding]
    news_error: str
    gaps_by_holding: List[Gap]
    gaps_by_source: List[Gap]
    data_quality_score: int
    investment_grade: bool
    high_conviction_actions: List[Dict[str, Any]]
    subject: str
    previous_state: Dict[str, Any]
    current_state: Dict[str, Any]


@dataclass
class CurrentPortfolio:
    engine: PortfolioEngine
    refresh_result: Dict[str, Any]
    data_as_of: str
    stale: bool
    stale_reason: str
    source_label: str


def _now_ct() -> datetime:
    return datetime.now(tz=CHICAGO_TZ)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", RESEARCH_NEEDED):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", RESEARCH_NEEDED):
            return default
        return int(float(value))
    except Exception:
        return default


def _fmt_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "n/a"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}%"
    except Exception:
        return "n/a"


def _fmt_dt(value: Any) -> str:
    if not value:
        return "n/a"
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.astimezone(CHICAGO_TZ).isoformat(sep=" ", timespec="seconds")
    return str(value)


def _age_hours_text(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return "n/a"
    age = _now_ct().astimezone(parsed.tzinfo) - parsed
    return f"{max(0.0, age.total_seconds() / 3600.0):.1f}"


def _load_previous_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _python_has_modules(python_path: Path, modules: Sequence[str]) -> bool:
    try:
        result = subprocess.run(
            [str(python_path), "-c", "import " + ", ".join(modules)],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _pick_refresh_python() -> str:
    required_modules = ("pandas", "dotenv", "requests", "schwab")
    candidates = [
        Path("/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14"),
        Path("/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"),
        Path("/opt/homebrew/bin/python3.11"),
        Path("/usr/local/bin/python3.11"),
        Path(sys.executable),
        PROJECT_ROOT / ".venv" / "bin" / "python",
    ]

    available = [candidate for candidate in candidates if candidate.exists() and os.access(candidate, os.X_OK)]
    for candidate in available:
        if _python_has_modules(candidate, required_modules):
            return str(candidate)

    for candidate in available:
        if candidate.name.startswith("python"):
            return str(candidate)

    return sys.executable


def _save_state(state: Dict[str, Any]) -> None:
    get_memory().save_setting("morning_cio_email_state", state, STATE_PATH, source="morning_cio_email")


def _append_run_log(payload: Dict[str, Any]) -> None:
    record = dict(payload)
    record.setdefault("logged_at", _now_ct().isoformat())
    get_memory().append_report_line(RUN_LOG_PATH, json.dumps(record, sort_keys=True), "morning_cio_run_log", source="morning_cio_email")


def _append_delivery_registry(payload: Dict[str, Any]) -> None:
    """Append delivery metadata without persisting credentials or message bodies."""
    record = dict(payload)
    record.setdefault("logged_at", _now_ct().isoformat())
    allowed = {
        "run_id",
        "report_date",
        "event",
        "status",
        "transport",
        "recipient",
        "subject",
        "content_sha256",
        "error",
        "logged_at",
    }
    safe_record = {key: value for key, value in record.items() if key in allowed}
    get_memory().append_report_line(DELIVERY_REGISTRY_PATH, json.dumps(safe_record, sort_keys=True), "morning_cio_delivery_registry", source="morning_cio_email")


def _delivery_succeeded_for_date(report_date: str) -> bool:
    for line in get_memory().read_report_text(DELIVERY_REGISTRY_PATH, encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if (
            row.get("report_date") == report_date
            and row.get("event") == "send_succeeded"
            and row.get("status") == "accepted"
        ):
            return True
    return False


def _persist_report_text(path: Path, content: str) -> None:
    get_memory().write_report_text(path, content, "morning_cio_artifact", source="morning_cio_email")


class _MemoryReportLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            get_memory().append_report_line(
                LOG_DIR / "morning_cio_email.log",
                self.format(record),
                "morning_cio_runtime_log",
                source="morning_cio_email",
            )
        except Exception:
            pass


def _configure_logger(run_id: str) -> logging.Logger:
    logger = logging.getLogger(f"morning_cio_email.{run_id}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = _MemoryReportLogHandler()
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def _acquire_lock() -> None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        age_seconds = max(0.0, time.time() - LOCK_PATH.stat().st_mtime)
        if age_seconds > LOCK_STALE_SECONDS:
            LOCK_PATH.unlink(missing_ok=True)
        else:
            raise RuntimeError(f"Lock file exists: {LOCK_PATH}")

    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        payload = {
            "pid": os.getpid(),
            "created_at": _now_ct().isoformat(),
        }
        os.write(fd, json.dumps(payload).encode("utf-8"))
    finally:
        os.close(fd)


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _is_market_day(at: Optional[datetime] = None) -> bool:
    moment = at or _now_ct()
    session = pd.Timestamp(moment.date())
    return bool(CALENDAR.is_session(session))


def _run_portfolio_refresh(timeout_seconds: int = LIVE_REFRESH_TIMEOUT_SECONDS) -> Dict[str, Any]:
    cmd = [_pick_refresh_python(), str(PROJECT_ROOT / "portfolio_sync.py")]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "attempted": True,
            "succeeded": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "attempted": True,
            "succeeded": False,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"portfolio_sync timed out after {timeout_seconds}s",
        }


def get_current_portfolio(logger: Optional[logging.Logger] = None, timeout_seconds: int = LIVE_REFRESH_TIMEOUT_SECONDS) -> CurrentPortfolio:
    """Fetch the latest portfolio snapshot for Morning CIO reporting.

    Attempts a live Schwab refresh via ``portfolio_sync.py`` and falls back to the
    latest saved snapshot if refresh fails.
    """
    try:
        refresh_result = _run_portfolio_refresh(timeout_seconds=timeout_seconds)
    except TypeError:
        # Keep compatibility with tests/monkeypatches that replace this helper
        # with a zero-argument callable.
        refresh_result = _run_portfolio_refresh()
    if logger:
        # Never emit subprocess stdout/stderr here: broker tools may print account
        # identifiers or other sensitive portfolio metadata.
        logger.info(
            "portfolio refresh result: attempted=%s succeeded=%s returncode=%s",
            bool(refresh_result.get("attempted")),
            bool(refresh_result.get("succeeded")),
            refresh_result.get("returncode"),
        )

    engine = _load_engine()
    data_as_of, stale_from_file = _extract_portfolio_timestamp(engine)
    stale = (not refresh_result.get("succeeded")) or stale_from_file

    if refresh_result.get("succeeded"):
        stale_reason = "Live Schwab refresh succeeded."
    else:
        stale_reason = "Live Schwab refresh unavailable; using saved portfolio snapshot."

    source_label = "live_schwab" if refresh_result.get("succeeded") else "saved_snapshot"
    return CurrentPortfolio(
        engine=engine,
        refresh_result=refresh_result,
        data_as_of=data_as_of,
        stale=stale,
        stale_reason=stale_reason,
        source_label=source_label,
    )


def _load_engine() -> PortfolioEngine:
    return PortfolioEngine()


def _extract_portfolio_timestamp(engine: PortfolioEngine) -> Tuple[str, bool]:
    portfolio_data = getattr(engine, "portfolio_data", {}) or {}
    sync_timestamp = str(portfolio_data.get("sync_timestamp") or "").strip()
    if sync_timestamp:
        return sync_timestamp, False

    summary_data = getattr(engine, "summary_data", {}) or {}
    sync_timestamp = str(summary_data.get("sync_timestamp") or "").strip()
    if sync_timestamp:
        return sync_timestamp, False

    portfolio_file = DATA_DIR / "schwab_portfolio_latest.json"
    if portfolio_file.exists():
        mtime = datetime.fromtimestamp(portfolio_file.stat().st_mtime, tz=CHICAGO_TZ)
        return mtime.isoformat(), True

    return _now_ct().isoformat(), True


def _check_news(symbols: Sequence[str]) -> Tuple[str, List[NewsFinding], str]:
    if not symbols:
        return "unavailable", [], "No equity holdings available for live news scan."

    source = TranscriptDataSource()
    findings: List[NewsFinding] = []
    errors: List[str] = []
    saw_stale = False
    saw_any_live = False

    for symbol in symbols:
        try:
            payload = source.fetch_symbol(symbol, force_refresh=True)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue

        stale = bool(payload.get("stale"))
        if stale:
            saw_stale = True
        else:
            saw_any_live = True

        data = payload.get("data") or {}
        docs = data.get("docs") or []
        source_urls = payload.get("source_urls") or []
        note = ""
        if not docs:
            note = "No recent SEC filing material found."
        findings.append(
            NewsFinding(
                symbol=symbol,
                status="stale" if stale else "ok",
                docs=docs,
                source_timestamp=str(payload.get("timestamp") or ""),
                source_urls=list(source_urls),
                note=note,
            )
        )

    if errors and not saw_any_live:
        return "unavailable", findings, "; ".join(errors)

    if errors or saw_stale:
        return "partial", findings, "; ".join(errors)

    return "complete", findings, ""


def _previous_thesis_map(state: Dict[str, Any]) -> Dict[str, str]:
    thesis = state.get("thesis_health") or {}
    if isinstance(thesis, dict):
        return {str(k): str(v) for k, v in thesis.items()}
    return {}


def _build_thesis_changes(current: Dict[str, str], previous: Dict[str, str]) -> List[Dict[str, Any]]:
    if not previous:
        return []

    changes: List[Dict[str, Any]] = []
    for symbol, current_value in sorted(current.items()):
        previous_value = previous.get(symbol)
        if previous_value is None or previous_value == current_value:
            continue
        changes.append(
            {
                "symbol": symbol,
                "previous": previous_value,
                "current": current_value,
            }
        )
    return changes


def _build_gaps(engine: PortfolioEngine, core_rankings: Sequence[Dict[str, Any]], news_status: str, news_error: str, previous_state: Dict[str, Any], stale: bool, data_as_of: str) -> Tuple[List[Gap], List[Gap], int]:
    gaps_by_holding: List[Gap] = []
    gaps_by_source: List[Gap] = []

    research_fields = [
        ("business_quality", "business-quality research", "BLOCKS_RECOMMENDATION", "Core rankings and action ranking require this field.", "Refresh research engine outputs in data/mcleod_research_latest.json."),
        ("valuation", "valuation research", "BLOCKS_RECOMMENDATION", "Current valuation ranking and downside discipline require this field.", "Rebuild valuation metrics in the research engine."),
        ("expected_alpha", "expected alpha research", "BLOCKS_RECOMMENDATION", "EIPV and high-conviction allocation depend on this field.", "Regenerate expected-alpha estimates from the research pipeline."),
        ("expected_2yr_cagr", "2-year CAGR research", "BLOCKS_RECOMMENDATION", "Longer-horizon ranking and thesis validation use this field.", "Populate 2-year growth estimates in the research pipeline."),
        ("expected_10yr_cagr", "10-year CAGR research", "BLOCKS_RECOMMENDATION", "Long-horizon compounding and replacement discipline use this field.", "Populate 10-year growth estimates in the research pipeline."),
        ("thesis_health", "thesis-health research", "LOWERS_CONFIDENCE", "Thesis change tracking and risk review use this field.", "Refresh the thesis-health feed for the holding."),
    ]

    ranked_by_symbol = {str(row.get("symbol", "")): row for row in core_rankings}
    research_by_symbol = getattr(engine, "research_data", {})
    max_research_age_hours = int(os.getenv("MORNING_CIO_MAX_RESEARCH_AGE_HOURS", "48") or "48")
    for pos in getattr(engine, "equities", []):
        symbol = str(pos.get("symbol", "")).strip()
        if not symbol:
            continue
        ranking = ranked_by_symbol.get(symbol, {})
        research_snapshot = research_by_symbol.get(symbol, {}) if isinstance(research_by_symbol, dict) else {}
        for field_name, source_expected, impact, affected, next_fix in research_fields:
            ts_key = f"{field_name}_timestamp"
            value = ranking.get(field_name, research_snapshot.get(field_name))
            ts_value = ranking.get(ts_key, research_snapshot.get(ts_key))
            if value in (None, "", RESEARCH_NEEDED):
                gaps_by_holding.append(
                    Gap(
                        scope="holding",
                        subject=symbol,
                        field_name=field_name,
                        source_expected="mcleod_research_latest.json / mcleod_intelligence_latest.json",
                        last_updated=_fmt_dt(ts_value or pos.get("sync_timestamp") or data_as_of),
                        status="missing" if value in (None, "", RESEARCH_NEEDED) else "partial",
                        impact=impact,
                        affected_calculation=affected,
                        next_fix=next_fix,
                        latest_input_age_hours=_age_hours_text(ts_value or pos.get("sync_timestamp") or data_as_of),
                        blocks_eipv=(impact == "BLOCKS_RECOMMENDATION"),
                    )
                )
                continue

            # EIPV and action calculations require fresh timestamped critical research fields.
            if field_name in CRITICAL_RESEARCH_FIELDS:
                if _timestamp_stale(ts_value, max_research_age_hours):
                    if ts_value:
                        stale_status = "stale"
                        stale_fix = f"Refresh {field_name} so timestamp is newer than {max_research_age_hours} hours."
                    else:
                        stale_status = "missing_timestamp"
                        stale_fix = f"Populate {field_name}_timestamp in intelligence outputs when {field_name} is present."
                    gaps_by_holding.append(
                        Gap(
                            scope="holding",
                            subject=symbol,
                            field_name=field_name,
                            source_expected="mcleod_intelligence_latest.json timestamped research",
                            last_updated=_fmt_dt(ts_value) if ts_value else "n/a",
                            status=stale_status,
                            impact="BLOCKS_RECOMMENDATION",
                            affected_calculation="EIPV and high-conviction recommendations require fresh timestamped research inputs",
                            next_fix=stale_fix,
                            latest_input_age_hours=_age_hours_text(ts_value),
                            blocks_eipv=True,
                        )
                    )

        # Canonical missing assumptions are explicit blockers/risks for assumption-backed EIPV.
        research = getattr(engine, "research_data", {}).get(symbol, {})
        canonical = research.get("canonical_research_record") if isinstance(research, dict) else None
        canonical_missing = canonical.get("missing_fields", []) if isinstance(canonical, dict) else []
        if isinstance(canonical_missing, list):
            for missing_item in canonical_missing:
                if not isinstance(missing_item, dict):
                    continue
                missing_assumption = str(missing_item.get("missing_assumption") or "assumption").strip()
                if not missing_assumption:
                    continue
                expected_source = str(missing_item.get("expected_source") or "canonical research source").strip()
                blocks_eipv = bool(missing_item.get("blocks_eipv"))
                age_hours = missing_item.get("age_of_latest_available_input_hours")
                age_text = "n/a" if age_hours in (None, "", "NEEDS_RESEARCH") else str(age_hours)
                next_action = str(missing_item.get("next_action") or "Resolve missing assumption from authoritative source data.")
                gaps_by_holding.append(
                    Gap(
                        scope="holding",
                        subject=symbol,
                        field_name=missing_assumption,
                        source_expected=expected_source,
                        last_updated=_fmt_dt(research.get("data_as_of") or data_as_of),
                        status="missing_assumption",
                        impact="BLOCKS_RECOMMENDATION" if blocks_eipv else "LOWERS_CONFIDENCE",
                        affected_calculation="Expected-return forecast defensibility and EIPV eligibility",
                        next_fix=next_action,
                        latest_input_age_hours=age_text,
                        blocks_eipv=blocks_eipv,
                    )
                )

    if stale:
        gaps_by_source.append(
            Gap(
                scope="source",
                subject="Schwab portfolio snapshot",
                field_name="sync_timestamp",
                source_expected="portfolio_sync.py live Schwab refresh",
                last_updated=data_as_of,
                status="stale",
                impact="BLOCKS_RECOMMENDATION",
                affected_calculation="All holdings, weights, and portfolio-level recommendations",
                next_fix="Run a successful live Schwab refresh so the report is based on current positions.",
                latest_input_age_hours=_age_hours_text(data_as_of),
                blocks_eipv=True,
            )
        )

    if news_status != "complete":
        gaps_by_source.append(
            Gap(
                scope="source",
                subject="Overnight SEC/news scan",
                field_name="recent filings and headlines",
                source_expected="TranscriptDataSource / SEC submissions",
                last_updated=_now_ct().isoformat(),
                status=news_status,
                impact="LOWERS_CONFIDENCE" if news_status == "partial" else "BLOCKS_RECOMMENDATION",
                affected_calculation="Material overnight news review for current holdings",
                next_fix="Restore a functioning live SEC/news check before calling the report investment-grade.",
                latest_input_age_hours="n/a",
                blocks_eipv=(news_status != "partial"),
            )
        )

    previous_thesis = _previous_thesis_map(previous_state)
    if not previous_thesis:
        gaps_by_source.append(
            Gap(
                scope="source",
                subject="CIO thesis snapshot history",
                field_name="previous thesis-health snapshot",
                source_expected="cio_email.morning_report state file",
                last_updated="n/a",
                status="missing",
                impact="LOWERS_CONFIDENCE",
                affected_calculation="Thesis Health Changes",
                next_fix="Run this report again so thesis-health deltas have a prior snapshot to compare against.",
                latest_input_age_hours="n/a",
                blocks_eipv=False,
            )
        )

    blocking_count = sum(1 for gap in gaps_by_holding + gaps_by_source if gap.impact == "BLOCKS_RECOMMENDATION")
    lower_count = sum(1 for gap in gaps_by_holding + gaps_by_source if gap.impact == "LOWERS_CONFIDENCE")
    noncritical_count = sum(1 for gap in gaps_by_holding + gaps_by_source if gap.impact == "NON-CRITICAL")

    score = 100
    score -= blocking_count * 16
    score -= lower_count * 8
    score -= noncritical_count * 3
    if stale:
        score -= 10
    if news_status == "partial":
        score -= 6
    if news_status == "unavailable":
        score -= 12
    score = max(0, min(100, score))

    return gaps_by_holding, gaps_by_source, score


def _build_actions(
    core_rankings: Sequence[Dict[str, Any]],
    eipv_rankings: Sequence[Dict[str, Any]],
    target_weights: Sequence[Dict[str, Any]],
    replacement_candidates: Sequence[Dict[str, Any]],
    gaps_by_source: Sequence[Gap],
    stale: bool,
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    if eipv_rankings:
        best = eipv_rankings[0]
        actions.append(
            {
                "type": "Add capital",
                "symbol": best.get("symbol", ""),
                "summary": f"Best next $1,000 allocation is {best.get('symbol', 'n/a')}",
                "detail": f"EIPV {_safe_float(best.get('eipv_score')):.2f}, new weight {_fmt_pct(best.get('new_weight_pct'))}, potential value add {_fmt_money(best.get('potential_value_add'))}.",
                "priority": 1,
                "requires_action": True,
            }
        )

    weighted_actions = [row for row in target_weights if str(row.get("action", "HOLD")).upper() != "HOLD"]
    for row in weighted_actions[:3]:
        actions.append(
            {
                "type": row.get("action", "REBALANCE"),
                "symbol": row.get("symbol", ""),
                "summary": f"{row.get('action', 'HOLD')} {row.get('symbol', '')}",
                "detail": f"Current {_fmt_pct(row.get('current_weight_pct'))} vs target {_fmt_pct(row.get('target_weight_pct'))}; delta {_fmt_pct(row.get('diff_pct'))}.",
                "priority": 2,
                "requires_action": True,
            }
        )

    if replacement_candidates:
        lowest = replacement_candidates[-1]
        actions.append(
            {
                "type": "Review replacement",
                "symbol": lowest.get("symbol", ""),
                "summary": f"Review {lowest.get('symbol', '')} as the weakest replaceable holding",
                "detail": f"Rank #{lowest.get('rank')}, composite score {_safe_float(lowest.get('composite_score')):.2f}, current weight {_fmt_pct(lowest.get('weight_pct'))}.",
                "priority": 3,
                "requires_action": True,
            }
        )

    if stale or any(g.impact == "BLOCKS_RECOMMENDATION" for g in gaps_by_source):
        actions.append(
            {
                "type": "Fix data",
                "symbol": "",
                "summary": "Restore live data quality before treating this report as investment-grade",
                "detail": "The report is based on stale or incomplete inputs and should not be used for fresh allocation decisions.",
                "priority": 0,
                "requires_action": True,
            }
        )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for action in sorted(actions, key=lambda row: row.get("priority", 9)):
        key = (action.get("type"), action.get("symbol"), action.get("summary"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _critical_blockers(gaps_by_holding: Sequence[Gap], gaps_by_source: Sequence[Gap]) -> List[Gap]:
    blockers: List[Gap] = []
    for gap in list(gaps_by_holding) + list(gaps_by_source):
        if gap.impact != "BLOCKS_RECOMMENDATION":
            continue
        if gap.field_name in CRITICAL_RESEARCH_FIELDS or gap.scope == "source":
            blockers.append(gap)
    return blockers


def _build_bundle(
    force: bool,
    logger: logging.Logger,
    previous_state: Dict[str, Any],
    report_date: Optional[str] = None,
) -> ReportBundle:
    generated_at = _now_ct().isoformat()
    effective_report_date = report_date or generated_at[:10]
    portfolio = get_current_portfolio(logger=logger)
    refresh_result = portfolio.refresh_result
    engine = portfolio.engine
    data_as_of = portfolio.data_as_of
    stale = portfolio.stale
    stale_reason = portfolio.stale_reason

    metrics = engine.get_portfolio_metrics()
    account_number = str(metrics.get("account_number", "N/A"))
    account_display = account_number
    try:
        from utils.account_manager import AccountManager

        account_display = AccountManager.get_display_name(account_number)
    except Exception:
        pass

    core_rankings = engine.rank_core_holdings()
    target_weights = engine.estimate_target_weights(method="mcleod_optimized")
    replacement_candidates = engine.identify_replacement_candidates()

    current_thesis = {
        str(pos.get("symbol", "")): str(engine.get_research_value(str(pos.get("symbol", "")), "thesis_health"))
        for pos in getattr(engine, "equities", [])
        if str(pos.get("symbol", "")).strip()
    }

    previous_thesis = _previous_thesis_map(previous_state)
    thesis_changes = _build_thesis_changes(current_thesis, previous_thesis)

    news_symbols = [str(pos.get("symbol", "")).strip() for pos in getattr(engine, "equities", []) if str(pos.get("symbol", "")).strip()]
    news_status, news_findings, news_error = _check_news(news_symbols)

    gaps_by_holding, gaps_by_source, data_quality_score = _build_gaps(
        engine=engine,
        core_rankings=core_rankings,
        news_status=news_status,
        news_error=news_error,
        previous_state=previous_state,
        stale=stale,
        data_as_of=data_as_of,
    )

    eipv_available = bool(core_rankings) and not any(g.impact == "BLOCKS_RECOMMENDATION" for g in gaps_by_holding)
    eipv_rankings = engine.calculate_eipv_rankings(EIPV_ALLOCATION) if eipv_available else []
    if not eipv_available:
        logger.info("EIPV gated off because required research gaps remain")

    high_conviction_actions = _build_actions(
        core_rankings=core_rankings,
        eipv_rankings=eipv_rankings,
        target_weights=target_weights,
        replacement_candidates=replacement_candidates,
        gaps_by_source=gaps_by_source,
        stale=stale,
    )

    strict_reco_policy = _env_flag("MORNING_CIO_STRICT_RECOMMENDATIONS", True)
    critical_blockers = _critical_blockers(gaps_by_holding, gaps_by_source)
    if strict_reco_policy and critical_blockers:
        top = critical_blockers[:5]
        blocker_summary = ", ".join(sorted({f"{gap.subject}:{gap.field_name}" for gap in top}))
        high_conviction_actions = [
            {
                "type": "Fix data",
                "symbol": "",
                "summary": "Action recommendations restricted until critical data blockers are cleared",
                "detail": f"Blocking items: {blocker_summary}",
                "priority": 0,
                "requires_action": True,
            }
        ]
        logger.warning("strict recommendation gate enabled; recommendations restricted due to critical blockers")

    investment_grade = (
        data_quality_score >= 80
        and not stale
        and news_status == "complete"
        and not any(g.impact == "BLOCKS_RECOMMENDATION" for g in gaps_by_holding + gaps_by_source)
    )

    action_required = bool(high_conviction_actions) or not investment_grade
    subject_state = "ACTION REQUIRED" if action_required else "Daily Review"

    options_positions = [dict(pos) for pos in getattr(engine, "options", [])]
    phase2_context = {str(symbol): snapshot.to_context() for symbol, snapshot in getattr(engine, "phase2_context", {}).items()}

    # If there is no prior snapshot, the thesis change section remains explicit about that.
    current_state = {
        "report_date": effective_report_date,
        "generated_at": generated_at,
        "data_as_of": data_as_of,
        "source_label": portfolio.source_label,
        "stale": stale,
        "thesis_health": current_thesis,
    }

    return ReportBundle(
        report_date=effective_report_date,
        generated_at=generated_at,
        data_as_of=data_as_of,
        source_label=portfolio.source_label,
        stale=stale,
        stale_reason=stale_reason,
        account_display=account_display,
        account_type=str(metrics.get("account_type", "N/A")),
        metrics=metrics,
        core_rankings=core_rankings,
        eipv_rankings=eipv_rankings,
        target_weights=target_weights,
        replacement_candidates=replacement_candidates,
        options_positions=options_positions,
        phase2_context=phase2_context,
        thesis_changes=thesis_changes,
        news_status=news_status,
        news_findings=news_findings,
        news_error=news_error,
        gaps_by_holding=gaps_by_holding,
        gaps_by_source=gaps_by_source,
        data_quality_score=data_quality_score,
        investment_grade=investment_grade,
        high_conviction_actions=high_conviction_actions,
        subject=subject_state,
        previous_state=previous_state,
        current_state=current_state,
    )


def _section_html(title: str, body: str) -> str:
    return f"<section class='panel'><h2>{escape(title)}</h2>{body}</section>"


def _table_html(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _bullet_html(items: Sequence[str]) -> str:
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def _render_executive_summary(bundle: ReportBundle) -> Section:
    total_value = _fmt_money(bundle.metrics.get("total_portfolio_value"))
    equity_value = _fmt_money(bundle.metrics.get("equity_value"))
    cash_balance = _fmt_money(bundle.metrics.get("cash_balance"))
    ranked_count = len(bundle.core_rankings)
    total_equities = _safe_int(bundle.metrics.get("num_equities"))
    blocked_count = len(bundle.gaps_by_holding)
    summary_lines = [
        f"Generated at {bundle.generated_at} CT.",
        f"Data as of {bundle.data_as_of}.",
        f"Source: {bundle.source_label}{' (stale snapshot)' if bundle.stale else ''}.",
        f"Portfolio value {total_value}; equity value {equity_value}; cash {cash_balance}.",
        f"Core rankings cover {ranked_count}/{total_equities} equities; {blocked_count} missing-data gaps were identified.",
        f"News check status: {bundle.news_status}.",
        f"Data quality score: {bundle.data_quality_score}/100.",
        f"Investment grade today: {'YES' if bundle.investment_grade else 'NO' }.",
    ]

    bullets = _bullet_html([escape(line) for line in summary_lines])
    text = "\n".join(summary_lines)
    return Section("Executive Summary", text, bullets)


def _render_actions(bundle: ReportBundle) -> Section:
    if not bundle.high_conviction_actions:
        text = "No high-conviction actions were produced because the report lacks enough validated inputs."
        html = f"<p class='muted'>{escape(text)}</p>"
        return Section("High-Conviction Actions", text, html)

    text_lines = []
    html_rows = []
    for action in bundle.high_conviction_actions:
        text_lines.append(f"- {action['summary']}: {action['detail']}")
        html_rows.append(
            [
                escape(str(action.get("type", ""))),
                escape(str(action.get("symbol", "")) or "n/a"),
                escape(str(action.get("summary", ""))),
                escape(str(action.get("detail", ""))),
            ]
        )

    return Section(
        "High-Conviction Actions",
        "\n".join(text_lines),
        _table_html(["Type", "Symbol", "Summary", "Detail"], html_rows),
    )


def _render_core_rankings(bundle: ReportBundle) -> Section:
    if not bundle.core_rankings:
        text = "No ranked holdings are available."
        return Section("McLeod Core Rankings", text, f"<p class='muted'>{escape(text)}</p>")

    rows = []
    text_lines = []
    for row in bundle.core_rankings[:5]:
        symbol = row.get("symbol", "")
        text_lines.append(
            f"{row.get('rank')}. {symbol} | score {_safe_float(row.get('composite_score')):.2f} | weight {_fmt_pct(row.get('weight_pct'))} | thesis {row.get('thesis_health', 'n/a')}"
        )
        rows.append(
            [
                escape(str(row.get("rank", ""))),
                escape(str(symbol)),
                escape(f"{_safe_float(row.get('composite_score')):.2f}"),
                escape(_fmt_pct(row.get("weight_pct"))),
                escape(str(row.get("thesis_health", "n/a"))),
                escape(str(row.get("data_quality", "n/a"))),
            ]
        )

    if bundle.gaps_by_holding:
        text_lines.append(f"{len(bundle.gaps_by_holding)} holding-level data gaps remain blocked or low confidence.")

    html = _table_html(["Rank", "Symbol", "Composite", "Weight", "Thesis", "Data Quality"], rows)
    return Section("McLeod Core Rankings", "\n".join(text_lines), html)


def _render_phase2_research(bundle: ReportBundle) -> Section:
    if not bundle.phase2_context:
        text = "No validated Phase 2 artifacts are available. Phase 2 remains informational-only until a canonical adapter snapshot is present."
        return Section("Phase 2 Research", text, f"<p class='warning'>{escape(text)}</p>")

    rows = []
    text_lines = []
    warnings = []
    for ticker in sorted(bundle.phase2_context):
        snapshot = bundle.phase2_context[ticker]
        available = bool(snapshot.get("available"))
        warning = str(snapshot.get("warning") or "").strip()
        overall = snapshot.get("overall_score") or {}
        components = snapshot.get("component_scores") or {}
        component_summary = " | ".join(
            f"{components[key].get('label', key)} {float(components[key].get('score', 0) or 0):.2f}"
            for key in ["business_quality", "competitive_moat", "management", "capital_allocation", "balance_sheet", "growth", "valuation"]
            if key in components
        )
        approval_status = "approved" if snapshot.get("approved_for_eipv") else "not approved"
        mode = "portfolio-active" if snapshot.get("approved_for_eipv") else "informational-only"
        confidence = float(overall.get("confidence") or snapshot.get("confidence") or 0.0)
        score = float(overall.get("score") or 0.0)
        missing_inputs = ", ".join(overall.get("missing_inputs") or snapshot.get("missing_inputs") or []) or "none"
        integrity = "valid" if available else f"unavailable: {warning or 'adapter failed closed'}"
        tone = "very low confidence" if confidence < 10 else "low confidence" if confidence < 35 else "normal confidence"
        text_lines.append(
            f"{ticker}: score {score:.2f}, confidence {confidence:.2f} ({tone}), approval {approval_status}, mode {mode}, missing {missing_inputs}."
        )
        text_lines.append(f"{ticker} components: {component_summary}")
        if warning:
            warnings.append(f"{ticker}: {warning}")
        rows.append(
            [
                escape(ticker),
                escape(f"{score:.2f}"),
                escape(f"{confidence:.2f}"),
                escape(approval_status),
                escape(mode),
                escape(missing_inputs),
                escape(integrity),
            ]
        )

    html = _table_html(["Ticker", "Overall", "Confidence", "Approval", "Mode", "Missing Inputs", "Integrity"], rows)
    if warnings:
        html += f"<p class='warning'>{escape(' ; '.join(warnings))}</p>"
    return Section("Phase 2 Research", "\n".join(text_lines), html)


def _render_eipv(bundle: ReportBundle) -> Section:
    if not bundle.eipv_rankings:
        missing = [gap for gap in bundle.gaps_by_holding if gap.field_name in {"expected_alpha", "valuation", "expected_2yr_cagr", "expected_10yr_cagr", "business_quality"}]
        text = "Unavailable: EIPV requires validated research inputs that are still missing."
        if missing:
            text += "\nBlocking inputs: " + ", ".join(sorted({gap.field_name for gap in missing}))
        return Section("Best Next Investment Dollar by EIPV", text, f"<p class='warning'>{escape(text).replace(chr(10), '<br>')}</p>")

    top = bundle.eipv_rankings[0]
    text = (
        f"Best next $1,000 allocation: {top.get('symbol')} | EIPV {_safe_float(top.get('eipv_score')):.2f} | "
        f"new weight {_fmt_pct(top.get('new_weight_pct'))} | potential value add {_fmt_money(top.get('potential_value_add'))}."
    )
    html = _table_html(
        ["Symbol", "EIPV", "Current Weight", "Target Weight", "New Weight", "Potential Value Add"],
        [
            [
                escape(str(top.get("symbol", ""))),
                escape(f"{_safe_float(top.get('eipv_score')):.2f}"),
                escape(_fmt_pct(top.get("current_weight_pct"))),
                escape(_fmt_pct(top.get("target_weight_pct"))),
                escape(_fmt_pct(top.get("new_weight_pct"))),
                escape(_fmt_money(top.get("potential_value_add"))),
            ]
        ],
    )
    return Section("Best Next Investment Dollar by EIPV", text, html)


def _render_target_weights(bundle: ReportBundle) -> Section:
    if not bundle.target_weights:
        text = "No target weights available."
        return Section("Current Weight vs. Target Weight", text, f"<p class='muted'>{escape(text)}</p>")

    rows = []
    text_lines = []
    for row in bundle.target_weights[:8]:
        text_lines.append(
            f"{row.get('symbol')}: current {_fmt_pct(row.get('current_weight_pct'))} vs target {_fmt_pct(row.get('target_weight_pct'))} ({_fmt_pct(row.get('diff_pct'))}) -> {row.get('action')}."
        )
        rows.append(
            [
                escape(str(row.get("symbol", ""))),
                escape(_fmt_pct(row.get("current_weight_pct"))),
                escape(_fmt_pct(row.get("target_weight_pct"))),
                escape(_fmt_pct(row.get("diff_pct"))),
                escape(str(row.get("action", ""))),
                escape(_fmt_money(row.get("current_value"))),
                escape(_fmt_money(row.get("target_value"))),
            ]
        )

    return Section(
        "Current Weight vs. Target Weight",
        "\n".join(text_lines),
        _table_html(["Symbol", "Current", "Target", "Diff", "Action", "Current Value", "Target Value"], rows),
    )


def _render_replacements(bundle: ReportBundle) -> Section:
    if not bundle.replacement_candidates:
        text = "No replacement candidates available."
        return Section("Replacement Candidates, excluding SPCX", text, f"<p class='muted'>{escape(text)}</p>")

    rows = []
    text_lines = []
    for row in bundle.replacement_candidates[:5]:
        text_lines.append(
            f"{row.get('symbol')}: rank #{row.get('rank')}, score {_safe_float(row.get('composite_score')):.2f}, weight {_fmt_pct(row.get('weight_pct'))}."
        )
        rows.append(
            [
                escape(str(row.get("symbol", ""))),
                escape(str(row.get("rank", ""))),
                escape(f"{_safe_float(row.get('composite_score')):.2f}"),
                escape(_fmt_pct(row.get("weight_pct"))),
                escape(_fmt_pct(row.get("day_pl_pct"))),
                escape(str(row.get("reason", ""))),
            ]
        )

    return Section(
        "Replacement Candidates, excluding SPCX",
        "\n".join(text_lines),
        _table_html(["Symbol", "Rank", "Composite", "Weight", "Day P/L", "Reason"], rows),
    )


def _render_thesis_changes(bundle: ReportBundle) -> Section:
    if not bundle.previous_state.get("thesis_health"):
        text = "No prior CIO snapshot exists yet, so thesis-health changes are unavailable on the first run."
        return Section("Thesis Health Changes", text, f"<p class='warning'>{escape(text)}</p>")

    if not bundle.thesis_changes:
        text = "No thesis-health changes were detected versus the prior CIO snapshot."
        return Section("Thesis Health Changes", text, f"<p class='good'>{escape(text)}</p>")

    text_lines = []
    rows = []
    for row in bundle.thesis_changes:
        text_lines.append(f"{row['symbol']}: {row['previous']} -> {row['current']}")
        rows.append([escape(row["symbol"]), escape(row["previous"]), escape(row["current"])])

    return Section("Thesis Health Changes", "\n".join(text_lines), _table_html(["Symbol", "Previous", "Current"], rows))


def _render_news(bundle: ReportBundle) -> Section:
    if bundle.news_status == "complete" and not any(find.docs for find in bundle.news_findings):
        text = "Live SEC news check completed successfully and found no material overnight filing activity in the checked holdings."
        return Section("Material Overnight News Affecting Current Holdings", text, f"<p class='good'>{escape(text)}</p>")

    if bundle.news_status == "complete" and any(find.docs for find in bundle.news_findings):
        rows = []
        text_lines = []
        for finding in bundle.news_findings:
            for doc in finding.docs[:2]:
                text_lines.append(f"{finding.symbol}: {doc.get('form')} filed {doc.get('filing_date')} | {doc.get('excerpt', '')}")
                rows.append(
                    [
                        escape(finding.symbol),
                        escape(str(doc.get("form", ""))),
                        escape(str(doc.get("filing_date", ""))),
                        escape(str(doc.get("excerpt", ""))),
                    ]
                )
        return Section(
            "Material Overnight News Affecting Current Holdings",
            "\n".join(text_lines),
            _table_html(["Symbol", "Form", "Filed", "Excerpt"], rows),
        )

    text = f"News check unavailable ({bundle.news_status}). {bundle.news_error or 'The report cannot safely claim there was no material news.'}"
    html = f"<p class='warning'>{escape(text)}</p>"
    return Section("Material Overnight News Affecting Current Holdings", text, html)


def _render_options(bundle: ReportBundle) -> Section:
    if not bundle.options_positions:
        text = "No current option positions."
        return Section("Options Position Review", text, f"<p class='muted'>{escape(text)}</p>")

    rows = []
    text_lines = []
    for pos in bundle.options_positions:
        symbol = str(pos.get("symbol", ""))
        qty = _safe_int(pos.get("quantity"))
        market_value = _fmt_money(pos.get("market_value"))
        day_pl = _fmt_money(pos.get("day_pl"))
        text_lines.append(f"{symbol}: qty {qty}, value {market_value}, day P/L {day_pl}.")
        rows.append(
            [
                escape(symbol),
                escape(str(qty)),
                escape(_fmt_money(pos.get("average_price"))),
                escape(market_value),
                escape(day_pl),
                escape(_fmt_pct(pos.get("day_pl_pct"))),
            ]
        )

    return Section(
        "Options Position Review",
        "\n".join(text_lines),
        _table_html(["Symbol", "Qty", "Avg Price", "Market Value", "Day P/L", "Day P/L %"], rows),
    )


def _render_data_quality(bundle: ReportBundle) -> Section:
    text = (
        f"Overall data quality score: {bundle.data_quality_score}/100. "
        f"Investment-grade today: {'YES' if bundle.investment_grade else 'NO'}."
    )
    html = (
        f"<div class='score-wrap'><div class='score'>{bundle.data_quality_score}</div>"
        f"<div><div class='score-label'>Overall Data Quality Score</div><div class='muted'>Investment-grade today: {'YES' if bundle.investment_grade else 'NO'}</div></div></div>"
    )
    return Section("Data Quality Score", text, html)


def _render_missing_data(bundle: ReportBundle) -> Section:
    lines = []
    html_parts = []

    if bundle.gaps_by_holding:
        lines.append("By Holding:")
        holding_rows = []
        for gap in bundle.gaps_by_holding:
            blocks_eipv = "YES" if gap.blocks_eipv or gap.impact == "BLOCKS_RECOMMENDATION" else "NO"
            lines.append(
                f"- {gap.subject} | {gap.field_name} | expected {gap.source_expected} | age_hours {gap.latest_input_age_hours} | blocks_eipv {blocks_eipv} | last updated {gap.last_updated} | {gap.status} | impact {gap.impact} | affects {gap.affected_calculation} | next fix: {gap.next_fix}"
            )
            holding_rows.append(
                [
                    escape(gap.subject),
                    escape(gap.field_name),
                    escape(gap.source_expected),
                    escape(gap.latest_input_age_hours),
                    escape(blocks_eipv),
                    escape(gap.last_updated),
                    escape(gap.status),
                    escape(gap.impact),
                    escape(gap.affected_calculation),
                    escape(gap.next_fix),
                ]
            )
        html_parts.append(_table_html(["Ticker", "Missing Assumption", "Expected Source", "Age (hrs)", "Blocks EIPV", "Last Updated", "Status", "Impact", "Affected Calculation", "Next Fix"], holding_rows))
    else:
        lines.append("By Holding: none identified.")
        html_parts.append("<p class='good'>No holding-level data gaps identified.</p>")

    if bundle.gaps_by_source:
        lines.append("By Data Source:")
        source_rows = []
        for gap in bundle.gaps_by_source:
            blocks_eipv = "YES" if gap.blocks_eipv or gap.impact == "BLOCKS_RECOMMENDATION" else "NO"
            lines.append(
                f"- {gap.subject} | {gap.field_name} | expected {gap.source_expected} | age_hours {gap.latest_input_age_hours} | blocks_eipv {blocks_eipv} | last updated {gap.last_updated} | {gap.status} | impact {gap.impact} | affects {gap.affected_calculation} | next fix: {gap.next_fix}"
            )
            source_rows.append(
                [
                    escape(gap.subject),
                    escape(gap.field_name),
                    escape(gap.source_expected),
                    escape(gap.latest_input_age_hours),
                    escape(blocks_eipv),
                    escape(gap.last_updated),
                    escape(gap.status),
                    escape(gap.impact),
                    escape(gap.affected_calculation),
                    escape(gap.next_fix),
                ]
            )
        html_parts.append(_table_html(["Source", "Missing Assumption", "Expected Source", "Age (hrs)", "Blocks EIPV", "Last Updated", "Status", "Impact", "Affected Calculation", "Next Fix"], source_rows))
    else:
        lines.append("By Data Source: none identified.")
        html_parts.append("<p class='good'>No source-level data gaps identified.</p>")

    priority_gaps = sorted(
        list(bundle.gaps_by_holding) + list(bundle.gaps_by_source),
        key=lambda gap: {"BLOCKS_RECOMMENDATION": 0, "LOWERS_CONFIDENCE": 1, "NON-CRITICAL": 2}.get(gap.impact, 3),
    )[:5]
    lines.append("Top 5 highest-priority data gaps to fix next:")
    if priority_gaps:
        for gap in priority_gaps:
            lines.append(f"- {gap.subject}: {gap.field_name} ({gap.impact})")
    else:
        lines.append("- None")

    lines.append(f"Overall Data Quality Score: {bundle.data_quality_score}/100")
    lines.append(f"Investment-grade today: {'YES' if bundle.investment_grade else 'NO'}")

    html_parts.append(
        _table_html(
            ["Priority", "Subject", "Field", "Impact"],
            [
                [
                    escape(str(i + 1)),
                    escape(gap.subject),
                    escape(gap.field_name),
                    escape(gap.impact),
                ]
                for i, gap in enumerate(priority_gaps)
            ],
        )
    )
    html_parts.append(
        f"<p><strong>Overall Data Quality Score:</strong> {bundle.data_quality_score}/100<br><strong>Investment-grade today:</strong> {'YES' if bundle.investment_grade else 'NO'}</p>"
    )

    return Section("Missing Data", "\n".join(lines), "".join(html_parts))


def build_report(bundle: ReportBundle) -> Tuple[str, str, Dict[str, Any], List[Section]]:
    sections = [
        _render_executive_summary(bundle),
        _render_actions(bundle),
        _render_core_rankings(bundle),
        _render_phase2_research(bundle),
        _render_eipv(bundle),
        _render_target_weights(bundle),
        _render_replacements(bundle),
        _render_thesis_changes(bundle),
        _render_news(bundle),
        _render_options(bundle),
        _render_data_quality(bundle),
        _render_missing_data(bundle),
    ]

    text_parts = []
    html_parts = []
    for section in sections:
        text_parts.append(f"## {section.title}\n{section.text}")
        html_parts.append(_section_html(section.title, section.html))

    subject = f"McLeod Morning CIO Report | {bundle.report_date} | {bundle.subject}"
    text_body = "\n\n".join(text_parts)
    html_body = _render_html_page(bundle, html_parts)
    payload = {
        "report_date": bundle.report_date,
        "generated_at": bundle.generated_at,
        "data_as_of": bundle.data_as_of,
        "source_label": bundle.source_label,
        "stale": bundle.stale,
        "stale_reason": bundle.stale_reason,
        "account_display": bundle.account_display,
        "account_type": bundle.account_type,
        "subject": subject,
        "data_quality_score": bundle.data_quality_score,
        "investment_grade": bundle.investment_grade,
        "news_status": bundle.news_status,
        "news_error": bundle.news_error,
        "sections": [section.title for section in sections],
    }
    return text_body, html_body, payload, sections


def _render_html_page(bundle: ReportBundle, section_html: Sequence[str]) -> str:
    status_class = "good" if bundle.investment_grade else "warning"
    stale_badge = "Stale snapshot" if bundle.stale else "Live refresh"
    cards = [
        ("Generated", bundle.generated_at),
        ("Data as of", bundle.data_as_of),
        ("Source", f"{bundle.source_label} / {stale_badge}"),
        ("Data Quality", f"{bundle.data_quality_score}/100"),
        ("Investment Grade", "YES" if bundle.investment_grade else "NO"),
    ]
    card_html = "".join(
        f"<div class='card'><div class='card-label'>{escape(label)}</div><div class='card-value'>{escape(value)}</div></div>"
        for label, value in cards
    )
    body = "".join(section_html)
    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>McLeod Morning CIO Report</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #0b1220;
      --text: #e5eefb;
      --muted: #9ca3af;
      --line: rgba(148,163,184,0.2);
      --accent: #f59e0b;
      --good: #34d399;
      --warn: #fbbf24;
      --bad: #fb7185;
    }}
    body {{ margin: 0; background: radial-gradient(circle at top, #1d4ed8 0, #0f172a 40%, #020617 100%); color: var(--text); font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .shell {{ max-width: 1220px; margin: 0 auto; padding: 28px 20px 48px; }}
    header {{ background: linear-gradient(145deg, rgba(17,24,39,.96), rgba(15,23,42,.92)); border: 1px solid var(--line); border-radius: 20px; padding: 24px; box-shadow: 0 24px 80px rgba(0,0,0,.35); }}
    h1 {{ margin: 0 0 10px; font-size: clamp(1.6rem, 3vw, 2.4rem); }}
    .lede {{ color: var(--muted); line-height: 1.5; margin: 0; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 18px; }}
    .card {{ background: rgba(15, 23, 42, .85); border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px; }}
    .card-label {{ color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 6px; }}
    .card-value {{ font-size: 1.02rem; font-weight: 700; }}
    .status {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; border: 1px solid var(--line); margin-top: 14px; background: rgba(255,255,255,.04); }}
    .status.good {{ color: var(--good); }}
    .status.warning {{ color: var(--warn); }}
    .grid {{ display: grid; gap: 16px; margin-top: 18px; }}
    .panel {{ background: linear-gradient(180deg, rgba(17,24,39,.95), rgba(11,18,32,.92)); border: 1px solid var(--line); border-radius: 18px; padding: 18px; box-shadow: 0 20px 60px rgba(0,0,0,.22); }}
    .panel h2 {{ margin: 0 0 12px; font-size: 1.15rem; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; vertical-align: top; text-align: left; }}
    th {{ color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; }}
    tbody tr:hover {{ background: rgba(255,255,255,.02); }}
    ul {{ margin: 0; padding-left: 20px; }}
    li {{ margin-bottom: 6px; line-height: 1.45; }}
    .muted {{ color: var(--muted); }}
    .good {{ color: var(--good); }}
    .warning {{ color: var(--warn); }}
    .score-wrap {{ display: flex; align-items: center; gap: 16px; }}
    .score {{ font-size: 3rem; font-weight: 800; color: var(--accent); line-height: 1; }}
    @media (max-width: 720px) {{ .score-wrap {{ flex-direction: column; align-items: flex-start; }} }}
  </style>
</head>
<body>
  <div class='shell'>
    <header>
      <h1>McLeod Morning CIO Report</h1>
      <p class='lede'>Independent portfolio review generated outside the trading engine. No email or data failure in this module can affect live trading.</p>
      <div class='cards'>{card_html}</div>
      <div class='status {status_class}'>{'Investment-grade today' if bundle.investment_grade else 'Action required'}: {'YES' if bundle.investment_grade else 'NO'}</div>
    </header>
    <div class='grid'>{body}</div>
  </div>
</body>
</html>"""


def _ensure_email_config() -> Tuple[bool, List[str], Dict[str, str]]:
    required = ["EMAIL_ADDRESS", "EMAIL_APP_PASSWORD", "EMAIL_TO"]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    cfg = {
        "address": os.getenv("EMAIL_ADDRESS", "").strip(),
        "password": os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip(),
        "to": os.getenv("EMAIL_TO", "").strip(),
        "from_name": os.getenv("EMAIL_FROM_NAME", "McLeod Alpha").strip() or "McLeod Alpha",
    }
    return not missing, missing, cfg


def _validate_email_secret_hygiene(logger: logging.Logger) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    address = os.getenv("EMAIL_ADDRESS", "").strip().lower()
    normalized_password = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip().strip('"\'')
    expected_address = os.getenv("EXPECTED_EMAIL_ADDRESS", "").strip().lower()

    if not address:
        issues.append("EMAIL_ADDRESS is missing")
    if expected_address and address != expected_address:
        issues.append("EMAIL_ADDRESS does not match EXPECTED_EMAIL_ADDRESS")
    if len(normalized_password) != 16:
        issues.append("EMAIL_APP_PASSWORD must be 16 characters after removing spaces")

    # Non-fatal hygiene warning (recorded in logs, does not reveal secret values).
    if address and not address.endswith("@gmail.com"):
        logger.warning("EMAIL_ADDRESS does not end with @gmail.com; verify SMTP account provider")

    return len(issues) == 0, issues


def _smtp_send(report: ReportBundle, html_body: str, text_body: str, subject: str, logger: logging.Logger) -> Dict[str, Any]:
    ok, missing, cfg = _ensure_email_config()
    if not ok:
        raise RuntimeError("Missing email configuration: " + ", ".join(missing))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{cfg['from_name']} <{cfg['address']}>"
    message["To"] = cfg["to"]
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    password = cfg["password"]
    last_error: Optional[Exception] = None
    for attempt in range(1, SMTP_MAX_ATTEMPTS + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
                smtp.login(cfg["address"], password)
                refused = smtp.send_message(message)
            if refused:
                raise RuntimeError(f"SMTP refused recipients: {refused}")
            logger.info("smtp send accepted on attempt %s", attempt)
            return {"accepted": True, "attempt": attempt, "refused": {}}
        except Exception as exc:
            last_error = exc
            logger.exception("smtp attempt %s failed", attempt)
            if attempt < SMTP_MAX_ATTEMPTS:
                time.sleep(SMTP_BACKOFF_SECONDS ** attempt)
    raise RuntimeError(f"SMTP delivery failed after {SMTP_MAX_ATTEMPTS} attempts: {last_error}")


def _outlook_send(to_email: str, subject: str, text_body: str, logger: logging.Logger) -> Dict[str, Any]:
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    applescript = f'''
    tell application "Microsoft Outlook"
        set newMessage to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(text_body)}", visible:false}}
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
            timeout=20,
        )
        if result.returncode != 0:
            err = (result.stderr or "").strip() or (result.stdout or "").strip()
            raise RuntimeError(err or "Microsoft Outlook send failed")
        logger.info("outlook send accepted")
        return {"accepted": True, "transport": "outlook"}
    except Exception as exc:
        logger.exception("outlook send failed")
        raise RuntimeError(f"Microsoft Outlook delivery failed: {exc}")


def _write_artifacts(bundle: ReportBundle, text_body: str, html_body: str, payload: Dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LEGACY_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    archive_dir = ARCHIVE_DIR / bundle.report_date
    archive_dir.mkdir(parents=True, exist_ok=True)
    json_body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    legacy_md = (
        "# McLeod Morning CIO Report\n\n"
        f"Report date: {bundle.report_date}\n"
        f"Generated: {bundle.generated_at}\n"
        f"Data as of: {bundle.data_as_of}\n"
        f"Source: {bundle.source_label}{' (stale snapshot)' if bundle.stale else ''}\n\n"
        "---\n\n"
        f"{text_body}\n"
    )
    _persist_report_text(LATEST_TEXT, text_body)
    _persist_report_text(LATEST_HTML, html_body)
    _persist_report_text(LATEST_JSON, json_body)
    _persist_report_text(LEGACY_MARKDOWN_PATH, legacy_md)
    _persist_report_text(archive_dir / "morning_cio_report.md", legacy_md)
    _persist_report_text(archive_dir / "morning_cio_report.html", html_body)
    _persist_report_text(archive_dir / "morning_cio_report.json", json_body)


def _update_state(bundle: ReportBundle) -> None:
    _save_state(bundle.current_state)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and send the McLeod Morning CIO report.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Generate the report without sending email.")
    mode.add_argument("--send", action="store_true", help="Send the report by email.")
    parser.add_argument("--date", dest="report_date", help="Logical report date in YYYY-MM-DD format (defaults to today in Chicago).")
    parser.add_argument("--force", action="store_true", help="Ignore market-calendar gating for manual tests.")
    return parser.parse_args(argv)


def _validated_report_date(value: Optional[str]) -> str:
    if not value:
        return _now_ct().date().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("--date must use YYYY-MM-DD format") from exc


def _market_gate_datetime(report_date: str) -> datetime:
    parsed = date.fromisoformat(report_date)
    return datetime.combine(parsed, datetime_time(hour=7), tzinfo=CHICAGO_TZ)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    if not args.dry_run and not args.send:
        args.dry_run = True

    try:
        report_date = _validated_report_date(args.report_date)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    run_id = uuid.uuid4().hex[:12]
    logger = _configure_logger(run_id)
    started_at = _now_ct().isoformat()
    _append_run_log({"run_id": run_id, "report_date": report_date, "event": "run_started", "started_at": started_at, "mode": "send" if args.send else "dry_run", "force": bool(args.force)})

    try:
        _acquire_lock()
    except Exception as exc:
        logger.error("could not acquire lock: %s", exc)
        _append_run_log({"run_id": run_id, "event": "lock_failed", "error": str(exc)})
        return 2

    try:
        if args.send and not args.force:
            if not _is_market_day(_market_gate_datetime(report_date)):
                logger.info("market-day gate skipped send because today is not an XNYS session")
                _append_run_log({"run_id": run_id, "report_date": report_date, "event": "market_day_skipped", "status": "skipped"})
                return 0

        previous_state = _load_previous_state()
        bundle = _build_bundle(
            force=args.force,
            logger=logger,
            previous_state=previous_state,
            report_date=report_date,
        )
        text_body, html_body, payload, sections = build_report(bundle)
        message_subject = str(payload.get("subject") or f"McLeod Morning CIO Report | {bundle.report_date} | {bundle.subject}")
        content_sha256 = hashlib.sha256((text_body + "\n" + html_body).encode("utf-8")).hexdigest()
        payload.update(
            {
                "run_id": run_id,
                "report_date": report_date,
                "content_sha256": content_sha256,
                "sections": [section.title for section in sections],
                "account_display": bundle.account_display,
                "account_type": bundle.account_type,
                "stale": bundle.stale,
                "stale_reason": bundle.stale_reason,
                "high_conviction_actions": bundle.high_conviction_actions,
            }
        )
        _write_artifacts(bundle, text_body, html_body, payload)
        _update_state(bundle)

        if args.send:
            recipient = os.getenv("EMAIL_TO", "").strip()
            if not args.force and _delivery_succeeded_for_date(report_date):
                logger.info("delivery skipped because report date %s was already accepted", report_date)
                event = {
                    "run_id": run_id,
                    "report_date": report_date,
                    "event": "send_skipped_duplicate",
                    "status": "skipped",
                    "recipient": recipient,
                    "subject": message_subject,
                    "content_sha256": content_sha256,
                }
                _append_run_log(event)
                _append_delivery_registry(event)
                return 0

            smtp_only_mode = _env_flag("MORNING_CIO_REQUIRE_SMTP_ONLY", True)
            hygiene_ok, hygiene_issues = _validate_email_secret_hygiene(logger)
            if not hygiene_ok:
                event = {
                    "run_id": run_id,
                    "report_date": report_date,
                    "event": "send_failed",
                    "status": "secret_hygiene_failed",
                    "error": "; ".join(hygiene_issues),
                    "recipient": recipient,
                    "subject": message_subject,
                    "content_sha256": content_sha256,
                    "data_as_of": bundle.data_as_of,
                }
                _append_run_log({**event, "issues": hygiene_issues})
                _append_delivery_registry(event)
                logger.error("email secret hygiene validation failed: %s", "; ".join(hygiene_issues))
                return 3

            if not recipient:
                ok, missing, _ = _ensure_email_config()
                msg = "Missing required email lines in .env: " + ", ".join(missing)
                logger.error(msg)
                event = {"run_id": run_id, "report_date": report_date, "event": "send_failed", "status": "missing_credentials", "error": msg, "subject": message_subject, "content_sha256": content_sha256, "data_as_of": bundle.data_as_of}
                _append_run_log({**event, "missing": missing})
                _append_delivery_registry(event)
                return 3

            ok, missing, _ = _ensure_email_config()
            try:
                if ok:
                    send_result = _smtp_send(bundle, html_body, text_body, message_subject, logger)
                    transport = "smtp"
                else:
                    if smtp_only_mode:
                        raise RuntimeError("SMTP-only mode enabled and SMTP credentials are incomplete")
                    logger.warning("SMTP config missing (%s); attempting Outlook fallback", ", ".join(missing))
                    send_result = _outlook_send(recipient, message_subject, text_body, logger)
                    transport = "outlook"
                event = {
                        "run_id": run_id,
                        "report_date": report_date,
                        "event": "send_succeeded",
                        "status": "accepted",
                        "recipient": recipient,
                        "data_as_of": bundle.data_as_of,
                        "subject": message_subject,
                        "transport": transport,
                        "smtp_result": send_result,
                        "content_sha256": content_sha256,
                    }
                _append_run_log(event)
                _append_delivery_registry(event)
                logger.info("email accepted via %s for %s", transport, recipient)
            except Exception as exc:
                if ok:
                    if smtp_only_mode:
                        logger.exception("smtp send failed in SMTP-only mode")
                        event = {"run_id": run_id, "report_date": report_date, "event": "send_failed", "status": "smtp_only_failure", "error": str(exc), "recipient": recipient, "subject": message_subject, "content_sha256": content_sha256, "data_as_of": bundle.data_as_of}
                        _append_run_log(event)
                        _append_delivery_registry(event)
                        return 4

                    logger.exception("smtp send failed; attempting Outlook fallback")
                    try:
                        send_result = _outlook_send(recipient, message_subject, text_body, logger)
                        event = {
                                "run_id": run_id,
                                "report_date": report_date,
                                "event": "send_succeeded",
                                "status": "accepted",
                                "recipient": recipient,
                                "data_as_of": bundle.data_as_of,
                                "subject": message_subject,
                                "transport": "outlook_fallback",
                                "smtp_result": send_result,
                                "fallback_from": "smtp",
                                "content_sha256": content_sha256,
                            }
                        _append_run_log(event)
                        _append_delivery_registry(event)
                        logger.info("email accepted via Outlook fallback for %s", recipient)
                    except Exception as outlook_exc:
                        logger.exception("send failed")
                        event = {"run_id": run_id, "report_date": report_date, "event": "send_failed", "status": "error", "error": str(outlook_exc), "recipient": recipient, "subject": message_subject, "content_sha256": content_sha256, "data_as_of": bundle.data_as_of}
                        _append_run_log(event)
                        _append_delivery_registry(event)
                        return 4
                else:
                    logger.exception("send failed")
                    event = {"run_id": run_id, "report_date": report_date, "event": "send_failed", "status": "error", "error": str(exc), "recipient": recipient, "subject": message_subject, "content_sha256": content_sha256, "data_as_of": bundle.data_as_of}
                    _append_run_log(event)
                    _append_delivery_registry(event)
                    return 4
        else:
            _append_run_log(
                {
                    "run_id": run_id,
                    "report_date": report_date,
                    "event": "dry_run_completed",
                    "status": "ok",
                    "data_as_of": bundle.data_as_of,
                    "subject": message_subject,
                }
            )

        logger.info("report generated successfully | data_as_of=%s | recipient=%s | stale=%s", bundle.data_as_of, os.getenv("EMAIL_TO", "").strip() or "n/a", bundle.stale)
        return 0
    except Exception as exc:
        logger.exception("morning CIO run failed")
        _append_run_log({"run_id": run_id, "event": "run_failed", "error": str(exc), "data_as_of": _now_ct().isoformat()})
        return 1
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
