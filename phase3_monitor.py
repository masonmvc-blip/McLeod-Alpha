from execution.option_selector import (
    find_option_contract,
    find_option_bid,
    find_option_mark,
    option_selection_block_reason,
    select_option_from_chain,
)
from execution.equity_stream import SchwabEquityQuoteStream
from execution.daily_trade_log_email import maybe_send_daily_trade_log_email
from execution.opportunity_logger import log_evaluated_setups
from execution.signal_logger import log_signal
from reports.daily_strategy_effectiveness import maybe_generate_daily_strategy_effectiveness_report
from reports.morning_readiness import maybe_generate_morning_readiness
from reports.scheduler_health import maybe_generate_scheduler_health_dashboard
from engine.brain import Brain, LIVE_ENTRY_MIN_SCORE, classify_entry_regime as market_regime
from engine.brain.candidate_controls import candidate_entry_block_reasons, load_candidate_controls
from execution.accepted_breakout_observer import observe_candidate, record_candidate_observation
from execution.day_trade_spy_shadow import record_day_trade_spy_shadow
from engine.memory import get_memory
from spy_bot_reviewer import SpyBotReviewer
from strategy.live_candle_builder import LiveMinuteCandleBuilder
from strategy.monitor_cycle import plan_signal_cycle
from strategy.signals import build_feature_snapshot
from strategy.trend_lifecycle_v2 import classify_trend_lifecycle_v2
from strategy.day_trade_spy_shadow_suite import evaluate_day_trade_spy_shadow_suite
from execution.trend_lifecycle_shadow import record_lifecycle_shadow_snapshot
from backtesting.signal_replay import confidence_score_engine

import os
import sys
import time
import json
import importlib
import requests
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from schwab.auth import easy_client

sys.path.append(str(Path("execution").resolve()))

SYMBOL = "SPY"
LIVE_BRAIN = Brain()
MARKET_POLL_SECONDS = max(1.0, float(os.getenv("MARKET_POLL_SECONDS", "2")))
CANDLE_POLL_SECONDS = max(0.05, float(os.getenv("CANDLE_POLL_SECONDS", "0.5")))
OPEN_POSITION_POLL_SECONDS = max(
    0.5,
    float(os.getenv("OPEN_POSITION_POLL_SECONDS", "0.75")),
)
OFF_HOURS_POLL_SECONDS = max(MARKET_POLL_SECONDS, float(os.getenv("OFF_HOURS_POLL_SECONDS", "60")))
TOKEN_PATH = "token.json"
EASTERN_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")
CANDLE_CACHE_PATH = Path("data/spy_1min_history.csv")
LAST_NONEMPTY_CANDLES = None
LAST_CANDLE_SOURCE = "empty"
LAST_QUOTE_SOURCE = "none"
LIVE_CANDLE_BUILDER = LiveMinuteCandleBuilder(symbol=SYMBOL, max_candles=390)
SCHWAB_QUOTE_FRESHNESS_SECONDS = int(os.getenv("SCHWAB_QUOTE_FRESHNESS_SECONDS", "180"))
SCHWAB_AUTH_RETRY_SECONDS = max(5, int(os.getenv("SCHWAB_AUTH_RETRY_SECONDS", "20")))
CANDLE_HISTORY_REFRESH_SECONDS = max(30, int(os.getenv("CANDLE_HISTORY_REFRESH_SECONDS", "180")))
END_OF_DAY_EXIT_TIME = dt_time(15, 45)
DAILY_LEARNING_TIME = dt_time(16, 5)
DAILY_LEARNING_RUNTIME_STATE = Path("data/daily_learning_runtime_state.json")
DAILY_LEARNING_MAX_ATTEMPTS = max(1, int(os.getenv("DAILY_LEARNING_MAX_ATTEMPTS", "8")))
DAILY_LEARNING_RETRY_MINUTES = max(1, int(os.getenv("DAILY_LEARNING_RETRY_MINUTES", "15")))
DAILY_TRADES_CHART_TIME = dt_time(16, 5)
DAILY_TRADES_CHART_RUNTIME_STATE = Path("data/daily_trades_chart_runtime_state.json")
_LAST_HISTORY_REFRESH_EPOCH = 0.0
_LAST_HISTORY_FETCH_MINUTE = None
OPTION_CHAIN_CACHE_REFRESH_SECONDS = max(1.0, float(os.getenv("OPTION_CHAIN_CACHE_REFRESH_SECONDS", "10")))
_LAST_OPTION_CHAIN_REFRESH_EPOCH = 0.0
_CACHED_OPTION_CHAIN = None
_MISSED_OPPORTUNITY_OPTION_WATCHLIST = {}
LATENCY_METRICS_ENABLED = str(os.getenv("LATENCY_METRICS_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
LATENCY_METRICS_PATH = Path(os.getenv("LATENCY_METRICS_PATH", "data/reports/latency_cycle_history.jsonl"))
DECISION_AUDIT_ENABLED = str(os.getenv("DECISION_AUDIT_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
DECISION_AUDIT_PATH = Path(os.getenv("DECISION_AUDIT_PATH", "data/reports/decision_audit_history.jsonl"))
CONTROL_COMMAND_PATH = Path("data") / "control_command.json"
POST_EXIT_COOLING_PATH = Path("data") / "post_exit_cooling.json"
SPY_RUN_ENTRY_MIN_DOLLARS = max(0.01, float(os.getenv("SPY_RUN_ENTRY_MIN_DOLLARS", "0.70")))
LAST_ENTRY_EXECUTION_METRICS = {
    "attempted": False,
    "opened": False,
    "open_trade_ms": None,
    "block_reason": None,
}


def _perf_ms_now():
    return time.perf_counter() * 1000.0


def _elapsed_ms(start_ms):
    return round(max(0.0, _perf_ms_now() - float(start_ms or 0.0)), 2)


def _append_latency_event(payload):
    if not LATENCY_METRICS_ENABLED:
        return
    try:
        get_memory().record_latency(payload, LATENCY_METRICS_PATH)
    except Exception as exc:
        print(f"Latency metrics write error: {exc}")


def _append_decision_audit_event(payload):
    if not DECISION_AUDIT_ENABLED:
        return
    try:
        get_memory().record_decision(payload, DECISION_AUDIT_PATH, source="monitor")
    except Exception as exc:
        print(f"Decision audit write error: {exc}")


def _publish_indicator_scores(last, regime, call_score, put_score, call_reasons, put_reasons, volume_trend):
    """Publish the exact logged scores before slower entry handling continues."""
    _append_decision_audit_event({
        "ts_utc": datetime.now(UTC_TZ).isoformat(),
        "ts_et": datetime.now(EASTERN_TZ).isoformat(),
        "symbol": SYMBOL,
        "event_type": "entry_evaluation",
        "event_phase": "scores_published",
        "candle_source": LAST_CANDLE_SOURCE,
        "candle_time": str(last.name),
        "spy_open": float(last.open),
        "spy_high": float(last.high),
        "spy_low": float(last.low),
        "spy_close": float(last.close),
        "spy_volume": float(last.volume),
        "regime": regime,
        "call_score": call_score,
        "put_score": put_score,
        "call_reasons": call_reasons or [],
        "put_reasons": put_reasons or [],
        "volume_trend": volume_trend,
    })


def _candidate_control_block_reasons(feature_payload, option):
    """Evaluate every opt-in control while preserving configured precedence."""
    try:
        features = json.loads(feature_payload) if isinstance(feature_payload, str) else feature_payload
    except (TypeError, json.JSONDecodeError):
        return []
    return candidate_entry_block_reasons(features or {}, option, load_candidate_controls())


def _prior_shadow_attempts(candle_time, direction):
    """Count earlier qualified same-direction attempts from append-only telemetry."""
    try:
        candle_at = pd.to_datetime(candle_time, utc=True)
        trading_date = candle_at.tz_convert(EASTERN_TZ).date().isoformat()
        path = Path("data/reports/opportunity_logs") / f"opportunity_setups_{trading_date}.jsonl"
        if not path.exists():
            return 0
        seen = set()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            row = json.loads(line)
            if str(row.get("direction") or "").upper() != str(direction).upper():
                continue
            if not bool((row.get("research") or {}).get("current_engine_qualified")):
                continue
            event_id = str(row.get("event_id") or "")
            if event_id:
                seen.add(event_id)
        return len(seen)
    except Exception:
        return None


def _log_shadow_opportunities(
    *,
    last,
    prev,
    completed_candles,
    regime,
    call_score,
    call_reasons,
    put_score,
    put_reasons,
    entered_call,
    entered_put,
    feature_payload=None,
    selected_option_call=None,
    selected_option_put=None,
    blocked_entry=None,
):
    """Capture evaluated setups as non-blocking research telemetry."""
    try:
        if _CACHED_OPTION_CHAIN:
            underlying_price = float(getattr(last, "close", 0.0) or 0.0)
            if selected_option_call is None:
                selected_option_call = select_option_from_chain(
                    _CACHED_OPTION_CHAIN,
                    "CALL",
                    underlying_price,
                    emit_log=False,
                )
            if selected_option_put is None:
                selected_option_put = select_option_from_chain(
                    _CACHED_OPTION_CHAIN,
                    "PUT",
                    underlying_price,
                    emit_log=False,
                )
        candle_at = pd.to_datetime(getattr(last, "name", None), utc=True, errors="coerce")
        if pd.isna(candle_at):
            candle_at = pd.Timestamp.now(tz="UTC")
        watch_until = candle_at + pd.Timedelta(minutes=16)
        for option in (selected_option_call, selected_option_put):
            if isinstance(option, dict) and option.get("symbol"):
                _MISSED_OPPORTUNITY_OPTION_WATCHLIST[str(option["symbol"])] = watch_until
        for symbol, expires_at in list(_MISSED_OPPORTUNITY_OPTION_WATCHLIST.items()):
            if candle_at > expires_at:
                _MISSED_OPPORTUNITY_OPTION_WATCHLIST.pop(symbol, None)
        option_watch_quotes = []
        if _CACHED_OPTION_CHAIN:
            for symbol in sorted(_MISSED_OPPORTUNITY_OPTION_WATCHLIST):
                contract = find_option_contract(_CACHED_OPTION_CHAIN, symbol)
                if isinstance(contract, dict):
                    option_watch_quotes.append({
                        "symbol": symbol,
                        "bid": contract.get("bid"),
                        "ask": contract.get("ask"),
                        "mark": contract.get("mark"),
                        "last": contract.get("last"),
                        "quote_provenance": "cached_live_option_chain_watchlist",
                    })
        payload = json.loads(feature_payload) if isinstance(feature_payload, str) else feature_payload
        payload = payload if isinstance(payload, dict) else {}
        directional_payloads = {}
        for direction in ("CALL", "PUT"):
            if str(payload.get("direction") or "").upper() == direction:
                directional_payloads[direction] = payload
                continue
            try:
                directional_payloads[direction] = json.loads(
                    _build_entry_feature_payload(
                        completed_candles,
                        direction,
                        regime,
                        call_score,
                        put_score,
                        call_reasons,
                        put_reasons,
                    )
                )
            except Exception:
                directional_payloads[direction] = {}

        combined_payload = dict(payload)
        session_market_trend_snapshot = _session_market_trend_snapshot(completed_candles)
        combined_payload["session_market_trend"] = session_market_trend_snapshot["trend"]
        combined_payload["session_market_trend_snapshot"] = session_market_trend_snapshot
        field_map = {
            "trend_stage": "trend_stage",
            "continuation_quality": "continuation_quality",
            "momentum_acceleration": "momentum_acceleration",
            "trend_efficiency_score": "trend_efficiency",
            "micro_efficiency_score": "momentum_expansion",
            "confidence": "confidence_score",
            "absorption_score": "absorption_score",
        }
        for direction, direction_payload in directional_payloads.items():
            suffix = direction.lower()
            for destination, source in field_map.items():
                if source in direction_payload:
                    combined_payload[f"{destination}_{suffix}"] = direction_payload[source]
        suites = {}
        for direction, option in (
            ("CALL", selected_option_call),
            ("PUT", selected_option_put),
        ):
            direction_payload = directional_payloads.get(direction) or {}
            captured_suite = (direction_payload or {}).get("day_trade_spy_shadow_suite")
            suites[direction] = (
                captured_suite
                if isinstance(captured_suite, dict)
                else evaluate_day_trade_spy_shadow_suite(
                    completed_candles,
                    direction,
                    feature_payload=direction_payload,
                    option=option,
                    same_regime_attempt_count=_prior_shadow_attempts(last.name, direction),
                    provenance="captured_live",
                )
            )
            record_day_trade_spy_shadow(
                suites[direction],
                event_phase="opportunity_evaluated",
                entered=entered_call if direction == "CALL" else entered_put,
                option_symbol=(option or {}).get("symbol") if isinstance(option, dict) else None,
            )
        log_evaluated_setups(
            last=last,
            prev=prev,
            df=completed_candles,
            regime=regime,
            call_score=call_score,
            call_reasons=call_reasons,
            put_score=put_score,
            put_reasons=put_reasons,
            entry_threshold=LIVE_ENTRY_MIN_SCORE,
            allow_entry=True,
            in_position=False,
            in_market_hours=True,
            entered_call=entered_call,
            entered_put=entered_put,
            feature_payload=combined_payload,
            selected_option_call=selected_option_call,
            selected_option_put=selected_option_put,
            blocked_entry=blocked_entry,
            day_trade_spy_shadow_suites=suites,
            option_watch_quotes=option_watch_quotes,
        )
    except Exception as exc:
        print(f"Shadow opportunity logging error: {exc}")


def _record_shadow_pair(completed_candles, *, event_phase):
    """Record both directional research labels when live entry is not evaluated."""
    for direction in ("CALL", "PUT"):
        try:
            snapshot = evaluate_day_trade_spy_shadow_suite(
                completed_candles,
                direction,
                provenance="captured_live",
            )
            record_day_trade_spy_shadow(snapshot, event_phase=event_phase)
        except Exception as exc:
            print(f"Day Trade SPY shadow logging error: {exc}")


def _append_latency_skip_event(*, reason, cycle_start_ms, candles_fetch_ms=None, indicators_ms=None):
    cycle_total_ms = _elapsed_ms(cycle_start_ms)
    ts_utc = datetime.now(UTC_TZ).isoformat()
    ts_et = datetime.now(EASTERN_TZ).isoformat()
    _append_latency_event({
        "ts_utc": ts_utc,
        "ts_et": ts_et,
        "symbol": SYMBOL,
        "candle_source": LAST_CANDLE_SOURCE,
        "regime": None,
        "candles_count": None,
        "candles_fetch_ms": candles_fetch_ms,
        "indicators_ms": indicators_ms,
        "manage_trade_ms": None,
        "entry_attempted": False,
        "entry_opened": False,
        "entry_decision_reason": reason,
        "entry_eval_ms": None,
        "chain_fetch_ms": None,
        "option_select_ms": None,
        "entry_precheck_ms": None,
        "entry_quote_compute_ms": None,
        "entry_submit_order_ms": None,
        "entry_wait_fill_ms": None,
        "entry_market_fallback_submit_ms": None,
        "entry_market_fallback_wait_ms": None,
        "entry_protective_stop_ms": None,
        "entry_persist_ms": None,
        "entry_block_reason": reason,
        "entry_filled_via": None,
        "open_trade_ms": None,
        "report_ms": None,
        "cycle_total_ms": cycle_total_ms,
    })
    _append_decision_audit_event({
        "ts_utc": ts_utc,
        "ts_et": ts_et,
        "symbol": SYMBOL,
        "event_type": "cycle_skip",
        "skip_reason": reason,
        "candle_source": LAST_CANDLE_SOURCE,
        "entry_attempted": False,
        "entry_opened": False,
        "entry_decision_reason": reason,
        "entry_block_reason": reason,
        "candles_fetch_ms": candles_fetch_ms,
        "indicators_ms": indicators_ms,
        "cycle_total_ms": cycle_total_ms,
    })


def _run_noncritical_schedulers():
    try:
        maybe_send_daily_trade_log_email()
    except Exception as exc:
        print(f"Daily trade-log scheduler warning: {exc}")
    try:
        maybe_generate_daily_trades_chart()
    except Exception as exc:
        print(f"Daily trades chart scheduler warning: {exc}")
    try:
        maybe_generate_morning_readiness(ENGINE_MODULE.get_schwab_positions)
    except Exception as exc:
        print(f"Morning readiness warning: {exc}")
    try:
        maybe_generate_scheduler_health_dashboard()
    except Exception as exc:
        print(f"Scheduler health warning: {exc}")
    try:
        maybe_run_after_close_daily_learning()
    except Exception as exc:
        print(f"Daily learning scheduler warning: {exc}")


def _resolve_schwab_callback_url() -> str:
    """Return a Schwab callback URL with an allowed localhost hostname."""
    raw = str(os.getenv("SCHWAB_CALLBACK_URL", "")).strip()
    if raw:
        parsed = urlparse(raw)
        # schwab-py login flow only allows callback hostname 127.0.0.1.
        if parsed.hostname == "127.0.0.1":
            return raw
        print(
            "SCHWAB_CALLBACK_URL is missing 127.0.0.1 hostname; "
            "falling back to https://127.0.0.1"
        )
    else:
        print("SCHWAB_CALLBACK_URL not set; falling back to https://127.0.0.1")
    return "https://127.0.0.1"


def _resolve_token_path() -> str:
    configured = str(os.getenv("SCHWAB_TOKEN_PATH", "")).strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())

    project_root = Path(__file__).resolve().parent
    candidates.extend(
        [
            project_root / TOKEN_PATH,
            Path.cwd() / TOKEN_PATH,
            Path.home() / TOKEN_PATH,
            Path.home() / "Documents" / "GitHub" / "McLeod-Alpha" / TOKEN_PATH,
            Path.home() / "Documents" / "GitHub" / "McLeod-Alpha-New" / TOKEN_PATH,
        ]
    )

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
        except Exception:
            continue

    return str((project_root / TOKEN_PATH).resolve())


def _build_schwab_client():
    callback_url = _resolve_schwab_callback_url()
    token_path = _resolve_token_path()

    attempt = 0
    while True:
        attempt += 1
        try:
            return easy_client(
                api_key=os.getenv("SCHWAB_APP_KEY"),
                app_secret=os.getenv("SCHWAB_APP_SECRET"),
                callback_url=callback_url,
                token_path=token_path,
                enforce_enums=False,
            )
        except Exception as exc:
            print(
                "Schwab auth bootstrap failed "
                f"(attempt {attempt}, token_path={token_path}): {exc}"
            )
            print(f"Retrying Schwab auth in {SCHWAB_AUTH_RETRY_SECONDS}s...")
            time.sleep(SCHWAB_AUTH_RETRY_SECONDS)

client = None
EQUITY_STREAM = None
ENGINE_MODULE = None
original_open_trade = None


def _initialize_live_runtime():
    """Perform broker and engine startup only for an explicit monitor run."""
    global client, EQUITY_STREAM, ENGINE_MODULE, original_open_trade, manage_trade, in_trade
    load_dotenv()
    if str(os.getenv("ACCOUNT_MODE", "paper")).strip().lower() != "live":
        raise RuntimeError("LIVE trading only: set ACCOUNT_MODE=live")
    client = _build_schwab_client()
    EQUITY_STREAM = SchwabEquityQuoteStream(client, SYMBOL)
    try:
        EQUITY_STREAM.start()
    except Exception as exc:
        print(f"Equity quote stream startup failed: {exc}")
    ENGINE_MODULE = importlib.import_module("execution.live_engine")
    original_open_trade = ENGINE_MODULE.open_trade
    manage_trade = ENGINE_MODULE.manage_trade
    in_trade = ENGINE_MODULE.in_trade
    account_number = str(os.getenv("SCHWAB_ACCOUNT_NUMBER", "")).strip()
    account_hash = str(os.getenv("SCHWAB_ACCOUNT_HASH", "")).strip()
    if hasattr(ENGINE_MODULE, "set_schwab_client"):
        ENGINE_MODULE.set_schwab_client(client, account_number, account_hash)
    print(f"Account Verified: {account_number}")
    print("Mode: LIVE TRADING")
    print(f"Live engine configured with account {account_number}")
    if hasattr(ENGINE_MODULE, "reconcile_startup"):
        print("Broker reconciliation successful" if ENGINE_MODULE.reconcile_startup() else "BROKER RECONCILIATION FAILED")


def _normalize_candles_frame(frame):
    if frame is None or frame.empty:
        return pd.DataFrame()

    normalized = frame.copy()
    if "datetime" in normalized.columns:
        normalized["datetime"] = pd.to_datetime(normalized["datetime"], errors="coerce", utc=True)
        normalized = normalized.dropna(subset=["datetime"]).set_index("datetime")

    if normalized.index.name != "datetime":
        normalized.index = pd.to_datetime(normalized.index, errors="coerce", utc=True)

    normalized = normalized[~normalized.index.isna()]
    normalized = normalized.sort_index()
    return normalized


def _load_cached_candles():
    if not CANDLE_CACHE_PATH.exists():
        return pd.DataFrame()

    try:
        cached = get_memory().load_csv_projection(CANDLE_CACHE_PATH)
        cached = _normalize_candles_frame(cached)
        return cached.tail(390).copy()
    except Exception as exc:
        print(f"Candle cache read error: {exc}")
        return pd.DataFrame()


def _persist_cached_candles(df):
    try:
        output = df.reset_index().rename(columns={"index": "datetime"}).tail(390)
        get_memory().save_csv_projection(CANDLE_CACHE_PATH, output)
    except Exception as exc:
        print(f"Candle cache write error: {exc}")


def _candles_with_datetime_column(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    working = df.copy()
    if "datetime" not in working.columns:
        working = working.reset_index().rename(columns={"index": "datetime"})
    return working


def _merge_candle_history(*frames):
    normalized_frames = [
        _normalize_candles_frame(frame)
        for frame in frames
        if frame is not None and not frame.empty
    ]
    if not normalized_frames:
        return pd.DataFrame()

    merged = pd.concat(normalized_frames)
    merged = merged[~merged.index.duplicated(keep="last")]
    return merged.sort_index().tail(390).copy()


def _is_regular_market_hours_now(now_et=None):
    now_et = now_et or datetime.now(EASTERN_TZ)
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def _is_entry_window_now(now_et=None):
    now_et = now_et or datetime.now(EASTERN_TZ)
    if not _is_regular_market_hours_now(now_et):
        return False
    return now_et.time() < dt_time(15, 45)


def _is_extended_market_hours_now(now_et=None):
    now_et = now_et or datetime.now(EASTERN_TZ)
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return (4 * 60) <= minutes < (20 * 60)


def _cycle_sleep_seconds(now_et=None):
    now_et = now_et or datetime.now(EASTERN_TZ)
    if not _is_extended_market_hours_now(now_et):
        return OFF_HOURS_POLL_SECONDS

    next_evaluation = now_et.replace(second=1, microsecond=0)
    if now_et >= next_evaluation:
        next_evaluation += timedelta(minutes=1)

    seconds_until_closed_candle = max(0.05, (next_evaluation - now_et).total_seconds())
    return min(MARKET_POLL_SECONDS, CANDLE_POLL_SECONDS, seconds_until_closed_candle)


def _history_fetch_due(now_et):
    """Fetch authoritative candles once after each regular or extended minute closes."""
    global _LAST_HISTORY_FETCH_MINUTE

    minute = now_et.replace(second=0, microsecond=0)
    if _is_extended_market_hours_now(now_et):
        return now_et.second >= 1 and _LAST_HISTORY_FETCH_MINUTE != minute

    return (time.time() - float(_LAST_HISTORY_REFRESH_EPOCH or 0.0)) >= float(CANDLE_HISTORY_REFRESH_SECONDS)


def _regular_session_start(now_et):
    return now_et.replace(hour=9, minute=30, second=0, microsecond=0)


def _extended_session_start(now_et):
    return now_et.replace(hour=4, minute=0, second=0, microsecond=0)


def _schwab_history_datetime(value):
    """Return a Schwab-compatible naive datetime for the same absolute instant."""
    if value is None or value.tzinfo is None:
        return value
    return datetime.fromtimestamp(value.timestamp())


def get_spy_live_quote():
    global LAST_QUOTE_SOURCE

    try:
        stream_payload = EQUITY_STREAM.get_latest_quote_payload() if EQUITY_STREAM.is_healthy() else None
    except Exception:
        stream_payload = None

    if stream_payload:
        LAST_QUOTE_SOURCE = "schwab_stream"
        return stream_payload

    resp = client.get_quote(SYMBOL)
    resp.raise_for_status()
    LAST_QUOTE_SOURCE = "schwab_rest_quote"
    return resp.json() or {}


def get_open_option_quote(option_symbol):
    """Fetch the held option directly so stop management never waits on a chain."""
    resp = client.get_quote(option_symbol)
    resp.raise_for_status()
    payload = resp.json() or {}
    quote_blob = payload.get(option_symbol) or next(iter(payload.values()), {})
    quote = quote_blob.get("quote") or {}

    def _positive_float(value):
        try:
            value = float(value)
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    bid = _positive_float(quote.get("bidPrice") or quote.get("bid"))
    ask = _positive_float(quote.get("askPrice") or quote.get("ask"))
    last = _positive_float(quote.get("lastPrice"))
    mark = _positive_float(quote.get("mark"))
    quote_epoch = _positive_float(quote.get("quoteTime") or quote.get("tradeTime"))
    if quote_epoch and quote_epoch > 10_000_000_000:
        quote_epoch /= 1000.0
    quote_age_seconds = max(0.0, time.time() - quote_epoch) if quote_epoch else None
    mid = ((bid + ask) / 2.0) if bid and ask and ask >= bid else None
    spread_pct = (((ask - bid) / mid) * 100.0) if mid else None
    return mark, bid, last, {
        "bid": bid,
        "ask": ask,
        "mark": mark,
        "last": last,
        "quote_age_seconds": quote_age_seconds,
        "quote_spread_pct": spread_pct,
        "quote_source": "schwab_direct_option_quote",
    }


def _enforce_end_of_day_exit(now_et=None):
    """Attempt the hard 3:45 PM ET exit without depending on candle availability."""
    now_et = now_et or datetime.now(EASTERN_TZ)
    position = getattr(ENGINE_MODULE, "current_position", None)
    if (
        position is None
        or now_et.weekday() >= 5
        or now_et.time() < END_OF_DAY_EXIT_TIME
    ):
        return False

    spy_price = float(getattr(position, "entry_price", 0.0) or 0.0)
    option_mark = None
    option_bid = None
    option_last = None
    quote_metadata = None

    try:
        quote_snapshot = LIVE_CANDLE_BUILDER.update_from_quote_payload(get_spy_live_quote())
        if quote_snapshot.price is not None:
            spy_price = float(quote_snapshot.price)
    except Exception as exc:
        print(f"END-OF-DAY EXIT: SPY quote unavailable; using position fallback price: {exc}")

    try:
        if getattr(position, "option_symbol", None):
            option_mark, option_bid, option_last, quote_metadata = get_open_option_quote(position.option_symbol)
    except Exception as exc:
        print(f"END-OF-DAY EXIT: option quote unavailable; submitting market exit anyway: {exc}")

    print("END-OF-DAY EXIT: enforcing mandatory 3:45 PM ET market close")
    manage_trade(spy_price, option_mark, option_bid, option_last, quote_metadata)
    return True


def _manage_open_position_priority():
    """Manage an open position from direct broker quotes before candle processing."""
    position = getattr(ENGINE_MODULE, "current_position", None)
    if position is None:
        return False

    spy_price = float(getattr(position, "entry_price", 0.0) or 0.0)
    option_mark = None
    option_bid = None
    option_last = None
    quote_metadata = None

    try:
        quote_snapshot = LIVE_CANDLE_BUILDER.update_from_quote_payload(get_spy_live_quote())
        if quote_snapshot.price is not None:
            spy_price = float(quote_snapshot.price)
    except Exception as exc:
        print(f"POSITION MANAGEMENT: SPY quote unavailable; using position fallback price: {exc}")

    try:
        if getattr(position, "option_symbol", None):
            option_mark, option_bid, option_last, quote_metadata = get_open_option_quote(position.option_symbol)
    except Exception as exc:
        print(f"POSITION MANAGEMENT: option quote unavailable: {exc}")

    manual_exit_requested = _process_manual_exit_command(
        spy_price,
        option_mark,
        option_bid,
        option_last,
        quote_metadata,
    )
    if not manual_exit_requested:
        manage_trade(spy_price, option_mark, option_bid, option_last, quote_metadata)
    return True


def maybe_run_after_close_daily_learning(now_et=None, runner=None):
    """Run daily learning after close, retrying until broker truth is complete."""
    now_et = now_et or datetime.now(EASTERN_TZ)
    if now_et.weekday() >= 5 or now_et.time() < DAILY_LEARNING_TIME:
        return False

    trading_date = now_et.date().isoformat()
    memory = get_memory()
    state = memory.load_setting(DAILY_LEARNING_RUNTIME_STATE, {})
    if state.get("last_success_date") == trading_date:
        return False
    attempts = int(state.get("attempt_count") or 0) if state.get("attempt_date") == trading_date else 0
    if attempts >= DAILY_LEARNING_MAX_ATTEMPTS:
        return False
    if attempts:
        try:
            last_attempt_at = datetime.fromisoformat(str(state.get("last_attempt_at") or ""))
        except ValueError:
            last_attempt_at = None
        if (
            last_attempt_at is not None
            and now_et < last_attempt_at + timedelta(minutes=DAILY_LEARNING_RETRY_MINUTES)
        ):
            return False

    state.update({
        "attempt_date": trading_date,
        "attempt_count": attempts + 1,
        "last_attempt_at": now_et.isoformat(),
    })
    memory.save_setting(
        "daily_learning_runtime_state",
        state,
        DAILY_LEARNING_RUNTIME_STATE,
        source="phase3_monitor",
    )

    try:
        if runner is None:
            from run_daily_trade_learning import run_daily_learning
            runner = run_daily_learning
        result = int(runner(trading_date))
    except Exception as exc:
        print(f"Daily learning runtime warning: {exc}")
        state["last_result"] = "exception"
        state["last_error"] = f"{type(exc).__name__}: {exc}"
        memory.save_setting(
            "daily_learning_runtime_state",
            state,
            DAILY_LEARNING_RUNTIME_STATE,
            source="phase3_monitor",
        )
        return False
    if result != 0:
        print(f"Daily learning runtime warning: runner returned {result}")
        state["last_result"] = f"retryable_exit_{result}"
        state["last_error"] = None
        memory.save_setting(
            "daily_learning_runtime_state",
            state,
            DAILY_LEARNING_RUNTIME_STATE,
            source="phase3_monitor",
        )
        return False

    state["last_success_date"] = trading_date
    state["last_success_at"] = datetime.now(EASTERN_TZ).isoformat()
    state["last_result"] = "success"
    state["last_error"] = None
    memory.save_setting(
        "daily_learning_runtime_state",
        state,
        DAILY_LEARNING_RUNTIME_STATE,
        source="phase3_monitor",
    )
    return True


def maybe_generate_daily_trades_chart(now_et=None, runner=None):
    """Create the Cockpit daily-trades chart once after each regular close."""
    now_et = now_et or datetime.now(EASTERN_TZ)
    if now_et.weekday() >= 5 or now_et.time() < DAILY_TRADES_CHART_TIME:
        return False

    trading_date = now_et.date().isoformat()
    memory = get_memory()
    state = memory.load_setting(DAILY_TRADES_CHART_RUNTIME_STATE, {})
    if state.get("last_success_date") == trading_date:
        return False

    if state.get("attempt_date") == trading_date:
        try:
            last_attempt_at = datetime.fromisoformat(str(state.get("last_attempt_at") or ""))
        except ValueError:
            last_attempt_at = None
        if (
            last_attempt_at is not None
            and now_et < last_attempt_at + timedelta(minutes=DAILY_LEARNING_RETRY_MINUTES)
        ):
            return False

    state.update({
        "attempt_date": trading_date,
        "last_attempt_at": now_et.isoformat(),
    })
    memory.save_setting(
        "daily_trades_chart_runtime_state",
        state,
        DAILY_TRADES_CHART_RUNTIME_STATE,
        source="phase3_monitor",
    )

    try:
        if runner is None:
            def runner(day):
                response = requests.get(
                    "http://127.0.0.1:5001/api/today-trades",
                    params={"date": day},
                    timeout=5,
                )
                response.raise_for_status()
                payload = response.json()
                if str(payload.get("trading_date") or "") != day:
                    raise RuntimeError("Cockpit returned a chart for a different trading date")
        runner(trading_date)
    except Exception as exc:
        state["last_result"] = "retryable_failure"
        state["last_error"] = f"{type(exc).__name__}: {exc}"
        memory.save_setting(
            "daily_trades_chart_runtime_state",
            state,
            DAILY_TRADES_CHART_RUNTIME_STATE,
            source="phase3_monitor",
        )
        return False

    state["last_success_date"] = trading_date
    state["last_success_at"] = datetime.now(EASTERN_TZ).isoformat()
    state["last_result"] = "success"
    state["last_error"] = None
    memory.save_setting(
        "daily_trades_chart_runtime_state",
        state,
        DAILY_TRADES_CHART_RUNTIME_STATE,
        source="phase3_monitor",
    )
    return True


def _quote_continuity_candles(history_df, source_label):
    global LAST_NONEMPTY_CANDLES, LAST_CANDLE_SOURCE

    try:
        quote_payload = get_spy_live_quote()
        builder_snapshot = LIVE_CANDLE_BUILDER.update_from_quote_payload(quote_payload)
        if builder_snapshot.price is None or builder_snapshot.quote_time_utc is None:
            print(f"Quote continuity unavailable: no direct Schwab quote timestamp from {LAST_QUOTE_SOURCE}")
            return pd.DataFrame()

        quote_age_seconds = max(0.0, (datetime.now(UTC_TZ) - builder_snapshot.quote_time_utc).total_seconds())
        # During off-hours, allow sparse updates without hard stale blocks.
        if _is_regular_market_hours_now() and quote_age_seconds > SCHWAB_QUOTE_FRESHNESS_SECONDS:
            print(
                "Quote continuity blocked: Schwab quote is stale "
                f"({quote_age_seconds:.1f}s old) from {LAST_QUOTE_SOURCE}"
            )
            return pd.DataFrame()

        merged = LIVE_CANDLE_BUILDER.merge_with_history(_candles_with_datetime_column(history_df))
        merged = _normalize_candles_frame(merged).tail(390).copy()
        if merged.empty:
            return pd.DataFrame()

        LAST_CANDLE_SOURCE = f"quote_heartbeat_{source_label}"
        LAST_NONEMPTY_CANDLES = merged.copy()
        _persist_cached_candles(LAST_NONEMPTY_CANDLES)
        print(
            "Candle continuity active: using direct Schwab quote heartbeat "
            f"from {LAST_QUOTE_SOURCE} on {source_label}"
        )
        return LAST_NONEMPTY_CANDLES
    except Exception as exc:
        print(f"Quote heartbeat continuity unavailable: {exc}")
        return pd.DataFrame()


def get_candles():
    global LAST_NONEMPTY_CANDLES, LAST_CANDLE_SOURCE, _LAST_HISTORY_REFRESH_EPOCH, _LAST_HISTORY_FETCH_MINUTE

    def _fetch_window(start=None, end=None, include_previous_close=False):
        request_kwargs = {
            "need_extended_hours_data": include_previous_close,
        }
        if start is not None:
            request_kwargs["start_datetime"] = _schwab_history_datetime(start)
        if end is not None:
            request_kwargs["end_datetime"] = _schwab_history_datetime(end)
        if include_previous_close:
            request_kwargs["need_previous_close"] = True

        try:
            resp = client.get_price_history_every_minute(
                SYMBOL,
                **request_kwargs,
            )
            resp.raise_for_status()
        except Exception as exc:
            print(f"Candle fetch error: {exc}")
            return pd.DataFrame()

        try:
            candles = resp.json().get("candles", [])
        except Exception as exc:
            print(f"Candle fetch response error: {exc}")
            return pd.DataFrame()
        frame = pd.DataFrame(candles)
        if frame.empty:
            return pd.DataFrame()

        frame["datetime"] = pd.to_datetime(frame["datetime"], unit="ms", errors="coerce", utc=True)
        frame = frame.dropna(subset=["datetime"]).set_index("datetime")
        return frame.sort_index()

    end = datetime.now(EASTERN_TZ)
    cached_history = _load_cached_candles()

    now_epoch = time.time()
    refresh_due = _history_fetch_due(end)
    if not refresh_due:
        if LAST_NONEMPTY_CANDLES is not None and not LAST_NONEMPTY_CANDLES.empty:
            LAST_CANDLE_SOURCE = "closed_candle_cache"
            return LAST_NONEMPTY_CANDLES.tail(390).copy()
        if not cached_history.empty:
            LAST_CANDLE_SOURCE = "closed_candle_disk_cache"
            LAST_NONEMPTY_CANDLES = cached_history.tail(390).copy()
            return LAST_NONEMPTY_CANDLES
        LAST_CANDLE_SOURCE = "waiting_for_closed_candle_fetch"
        return pd.DataFrame()

    # Pull official Schwab OHLCV bars, including extended-hours candles for
    # continuous overnight diagnostics and the next regular-session context.
    if _is_regular_market_hours_now():
        primary_start = _regular_session_start(end)
    elif _is_extended_market_hours_now(end):
        primary_start = _extended_session_start(end)
    else:
        primary_start = end - timedelta(days=5)
    _LAST_HISTORY_FETCH_MINUTE = end.replace(second=0, microsecond=0)
    df = _fetch_window(primary_start, end, include_previous_close=True)
    if not df.empty:
        df = _merge_candle_history(cached_history, df)
        LAST_CANDLE_SOURCE = "live_window"
        LAST_NONEMPTY_CANDLES = df.tail(390).copy()
        _LAST_HISTORY_REFRESH_EPOCH = now_epoch
        _persist_cached_candles(LAST_NONEMPTY_CANDLES)
        return LAST_NONEMPTY_CANDLES

    if LAST_NONEMPTY_CANDLES is not None and not LAST_NONEMPTY_CANDLES.empty:
        LAST_CANDLE_SOURCE = "stale_in_memory_cache"
        print("Candle fetch unavailable: using last closed-candle cache")
        return LAST_NONEMPTY_CANDLES.tail(390).copy()

    disk_cached = _load_cached_candles()
    if not disk_cached.empty:
        LAST_CANDLE_SOURCE = "stale_disk_cache"
        print("Candle fetch unavailable: using disk closed-candle cache")
        LAST_NONEMPTY_CANDLES = disk_cached.copy()
        return LAST_NONEMPTY_CANDLES

    LAST_CANDLE_SOURCE = "empty"
    return pd.DataFrame()


def add_indicators(df):
    df["ema10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    df["macd_hist"] = macd - signal

    return df


def _indicators_ready(df):
    required = ["vwap", "ema10", "ema20", "ema50", "macd_hist"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        return False, f"missing columns: {', '.join(missing)}"

    tail = df[required].tail(2)
    if tail.isnull().any().any():
        return False, "indicator values contain NaN in latest rows"

    return True, "ok"


def volume_momentum(df, *, emit_log=True):
    if len(df) < 6:
        return {
            "trend": "UNKNOWN",
            "current_volume": 0,
            "avg_volume": 0,
            "volume_ratio": 0,
            "score_adjustment": 0,
        }

    current_volume = float(df.iloc[-1]["volume"])
    avg_volume = float(df.iloc[-6:-1]["volume"].mean())

    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

    if volume_ratio >= 1.25:
        trend = "INCREASING"
        score_adjustment = 1
    elif volume_ratio <= 0.80:
        trend = "DECREASING"
        score_adjustment = -1
    else:
        trend = "NEUTRAL"
        score_adjustment = 0

    if emit_log:
        print(
            f"Volume: current={current_volume:.0f} | "
            f"avg5={avg_volume:.0f} | "
            f"ratio={volume_ratio:.2f} | "
            f"{trend}"
        )

    return {
        "trend": trend,
        "current_volume": current_volume,
        "avg_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "score_adjustment": score_adjustment,
    }


def absorption_score(df, direction="CALL"):
    """Score 0-5 opposing-pressure absorption from closed candles only."""
    if df is None or len(df) < 3:
        return {"score": 0.0, "components": {"insufficient_candles": True}}

    recent = df.tail(3)
    direction = str(direction or "CALL").upper()
    score = 0.0
    absorbed_pressure = 0
    for _, candle in recent.iterrows():
        candle_range = max(float(candle.high) - float(candle.low), 0.01)
        close_location = (float(candle.close) - float(candle.low)) / candle_range
        if direction == "CALL" and close_location >= 0.6:
            absorbed_pressure += 1
        elif direction == "PUT" and close_location <= 0.4:
            absorbed_pressure += 1

    score = round((absorbed_pressure / len(recent)) * 5.0, 2)
    return {
        "score": score,
        "components": {"absorbed_pressure": absorbed_pressure, "sample_size": len(recent)},
    }

def candle_quality(last):
    open_price = float(last.open)
    high = float(last.high)
    low = float(last.low)
    close = float(last.close)

    body = abs(close - open_price)
    candle_range = max(high - low, 0.01)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    if close > open_price:
        direction = "BULLISH"
    elif close < open_price:
        direction = "BEARISH"
    else:
        direction = "DOJI"

    body_pct = body / candle_range

    print(
        f"OHLC: O={open_price:.2f} H={high:.2f} L={low:.2f} C={close:.2f} | "
        f"{direction} | Body={body:.2f} | Body%={body_pct:.2f} | "
        f"UpperWick={upper_wick:.2f} | LowerWick={lower_wick:.2f}"
    )

    return {
        "direction": direction,
        "body": body,
        "range": candle_range,
        "body_pct": body_pct,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
    }


def score_closed_candle_frame(candles):
    """Return the strategy's CALL/PUT scores for an already closed candle frame."""
    if not isinstance(candles, pd.DataFrame):
        candles = pd.DataFrame(candles)
    normalized = _normalize_candles_frame(candles)
    if len(normalized) < 2:
        return None

    indicators = add_indicators(normalized.copy())
    ready, _ = _indicators_ready(indicators)
    if not ready:
        return None

    last = indicators.iloc[-1]
    prev = indicators.iloc[-2]
    decision = LIVE_BRAIN.evaluate_entry(last, prev, indicators)
    from backtesting.signal_replay import (
        confidence_score_engine,
        continuation_quality_score,
        momentum_acceleration_score,
        momentum_expansion_score_engine,
        trend_efficiency_score,
        trend_lifecycle_engine,
        trend_stage_engine,
    )

    def momentum_snapshot(direction):
        lifecycle = trend_lifecycle_engine(indicators, direction=direction)
        stage = trend_stage_engine(lifecycle)
        continuation = continuation_quality_score(indicators, direction=direction)
        acceleration = momentum_acceleration_score(indicators, direction=direction)
        efficiency = trend_efficiency_score(indicators, direction=direction)
        expansion = momentum_expansion_score_engine(indicators, direction=direction)
        score = decision["call_score"] if direction == "CALL" else decision["put_score"]
        aligned = (direction == "CALL" and decision["regime"] == "BULL_TREND") or (
            direction == "PUT" and decision["regime"] == "BEAR_TREND"
        )
        strength = confidence_score_engine(
            score, aligned, continuation, acceleration, efficiency, expansion, lifecycle, stage
        )
        return {
            "strength": strength.get("score"),
            "stage": stage.get("label"),
            "stage_number": stage.get("stage"),
            "trend_age_minutes": lifecycle.get("trend_age_minutes"),
            "continuation_legs": lifecycle.get("continuation_legs"),
            "acceleration": acceleration.get("score"),
            "lifecycle_v2_shadow": classify_trend_lifecycle_v2(indicators, direction),
        }

    return {
        "call_score": decision["call_score"],
        "put_score": decision["put_score"],
        "regime": decision["regime"],
        "market_trend": _session_market_trend(indicators),
        "timestamp": indicators.index[-1],
        "call_momentum": momentum_snapshot("CALL"),
        "put_momentum": momentum_snapshot("PUT"),
        "spy_run": _directional_spy_run(indicators),
    }


def _session_market_trend_snapshot(candles):
    """Return the completed-candle session trend and its immutable inputs."""
    unavailable = {
        "trend": "NEUTRAL",
        "session_open": None,
        "session_close": None,
        "session_vwap": None,
        "close_vs_open_dollars": None,
        "close_vs_vwap_dollars": None,
        "session_candle_count": 0,
        "provenance": "completed_regular_session_candles",
    }
    if candles is None or len(candles) < 2:
        return unavailable

    local = candles.copy()
    local.index = pd.to_datetime(local.index, errors="coerce", utc=True)
    local = local[~local.index.isna()]
    if local.empty or any(column not in local.columns for column in ("open", "high", "low", "close", "volume")):
        return unavailable

    et_index = local.index.tz_convert(EASTERN_TZ)
    session_date = et_index[-1].date()
    session_mask = (
        (et_index.date == session_date)
        & (et_index.time >= dt_time(9, 30))
        & (et_index.time <= dt_time(16, 0))
    )
    session = local.loc[session_mask]
    if len(session) < 2:
        return {
            **unavailable,
            "session_candle_count": int(len(session)),
        }

    typical_price = (session["high"].astype(float) + session["low"].astype(float) + session["close"].astype(float)) / 3.0
    cumulative_volume = session["volume"].astype(float).cumsum()
    if float(cumulative_volume.iloc[-1]) <= 0:
        return {
            **unavailable,
            "session_candle_count": int(len(session)),
        }
    session_vwap = float((typical_price * session["volume"].astype(float)).cumsum().iloc[-1] / cumulative_volume.iloc[-1])
    session_open = float(session["open"].iloc[0])
    session_close = float(session["close"].iloc[-1])

    trend = "NEUTRAL"
    if session_close > session_open and session_close > session_vwap:
        trend = "BULL_TREND"
    elif session_close < session_open and session_close < session_vwap:
        trend = "BEAR_TREND"
    return {
        "trend": trend,
        "session_open": round(session_open, 6),
        "session_close": round(session_close, 6),
        "session_vwap": round(session_vwap, 6),
        "close_vs_open_dollars": round(session_close - session_open, 6),
        "close_vs_vwap_dollars": round(session_close - session_vwap, 6),
        "session_candle_count": int(len(session)),
        "provenance": "completed_regular_session_candles",
    }


def _session_market_trend(candles):
    """Classify the regular-session direction from today's completed candles."""
    return _session_market_trend_snapshot(candles)["trend"]


def _directional_spy_run(candles):
    """Measure the uninterrupted latest one-minute close-to-close run."""
    closes = pd.to_numeric(candles.get("close"), errors="coerce").dropna().tolist()
    if len(closes) < 2:
        return {"direction": "NONE", "dollars": 0.0, "call_dollars": 0.0, "put_dollars": 0.0}

    latest_move = closes[-1] - closes[-2]
    if latest_move == 0:
        return {"direction": "NONE", "dollars": 0.0, "call_dollars": 0.0, "put_dollars": 0.0}

    direction = 1 if latest_move > 0 else -1
    run_start = closes[-2]
    for index in range(len(closes) - 1, 0, -1):
        move = closes[index] - closes[index - 1]
        if move == 0 or (move > 0) != (direction > 0):
            break
        run_start = closes[index - 1]

    dollars = round(abs(closes[-1] - run_start), 2)
    return {
        "direction": "UP" if direction > 0 else "DOWN",
        "dollars": dollars,
        "call_dollars": dollars if direction > 0 else 0.0,
        "put_dollars": dollars if direction < 0 else 0.0,
    }


def _continuation_forecast(candles, direction, base_score, regime):
    """Estimate whether a qualified trend is likely to continue before entry."""
    from backtesting.signal_replay import (
        confidence_score_engine,
        continuation_quality_score,
        momentum_acceleration_score,
        momentum_expansion_score_engine,
        trend_efficiency_score,
        trend_lifecycle_engine,
        trend_stage_engine,
    )

    lifecycle = trend_lifecycle_engine(candles, direction=direction)
    stage = trend_stage_engine(lifecycle)
    continuation = continuation_quality_score(candles, direction=direction)
    acceleration = momentum_acceleration_score(candles, direction=direction)
    efficiency = trend_efficiency_score(candles, direction=direction)
    expansion = momentum_expansion_score_engine(candles, direction=direction)
    aligned = (direction == "CALL" and regime == "BULL_TREND") or (direction == "PUT" and regime == "BEAR_TREND")
    confidence = confidence_score_engine(
        base_score, aligned, continuation, acceleration, efficiency, expansion, lifecycle, stage
    )
    return {
        "base_score": float(base_score or 0.0),
        "stage": int(stage.get("stage") or 5),
        "stage_label": str(stage.get("label") or "UNKNOWN"),
        "continuation_quality": float(continuation.get("score") or 0.0),
        "acceleration": float(acceleration.get("score") or 0.0),
        "efficiency": float(efficiency.get("score") or 0.0),
        "expansion": float(expansion.get("score") or 0.0),
        "confidence": float(confidence.get("score") or 0.0),
        "aligned": aligned,
    }


def _continuation_forecast_admission(forecast):
    """Apply stage-aware forward continuation thresholds to a trade candidate."""
    stage = int(forecast.get("stage") or 5)
    if not forecast.get("aligned"):
        return False, "Forecast: regime is not aligned"
    if stage <= 1:
        floors = {
            "base_score": 5.0,
            "continuation_quality": 3.5,
            "acceleration": 3.5,
            "efficiency": 3.5,
            "expansion": 3.5,
            "confidence": 3.5,
        }
        weak = [name for name, floor in floors.items() if float(forecast.get(name) or 0.0) < floor]
        if weak:
            return False, f"Forecast: initiation not confirmed ({', '.join(weak)})"
        return True, "Forecast: initiation approved"
    if stage >= 5:
        return False, "Forecast: Late Exhaustion"

    minimum = 3.0 if stage == 4 else 2.4
    floors = {
        "continuation_quality": 3.0 if stage == 4 else 2.5,
        "acceleration": 2.5 if stage == 4 else 2.0,
        "efficiency": 3.0 if stage == 4 else 2.5,
        "expansion": 2.5 if stage == 4 else 2.0,
        "confidence": minimum,
    }
    weak = [name for name, floor in floors.items() if float(forecast.get(name) or 0.0) < floor]
    if weak:
        return False, f"Forecast: weak {', '.join(weak)}"
    return True, "Forecast: continuation approved"


def _build_entry_feature_payload(completed_candles, direction, regime, call_score, put_score, call_reasons, put_reasons):
    """Capture the exact decision diagnostics before submitting a live order."""
    from backtesting.signal_replay import (
        continuation_quality_score,
        momentum_acceleration_score,
        momentum_expansion_score_engine,
        trend_efficiency_score,
        trend_lifecycle_engine,
        trend_stage_engine,
    )

    direction = str(direction).upper()
    frame = completed_candles.copy()
    lifecycle = trend_lifecycle_engine(frame, direction=direction)
    stage = trend_stage_engine(lifecycle)
    phase_by_stage = {
        1: "INITIATION",
        2: "EARLY_CONTINUATION",
        3: "ESTABLISHED",
        4: "MATURE",
        5: "LATE_EXHAUSTION",
    }
    try:
        momentum_phase = phase_by_stage.get(int(stage.get("stage")), str(stage.get("label") or "").upper() or None)
    except (TypeError, ValueError):
        momentum_phase = str(stage.get("label") or "").upper() or None
    continuation_quality = continuation_quality_score(frame, direction=direction)
    momentum_acceleration = momentum_acceleration_score(frame, direction=direction)
    trend_efficiency = trend_efficiency_score(frame, direction=direction)
    momentum_expansion = momentum_expansion_score_engine(frame, direction=direction)
    absorption = absorption_score(frame, direction=direction)
    decision_candle = frame.iloc[-1]
    close_price = float(decision_candle.get("close", 0.0) or 0.0)
    vwap_value = decision_candle.get("vwap")
    try:
        vwap_value = float(vwap_value) if pd.notna(vwap_value) else None
    except (TypeError, ValueError):
        vwap_value = None
    vwap_distance = (close_price - vwap_value) if vwap_value is not None else None
    vwap_snapshot = {
        "value": vwap_value,
        "underlying_close": close_price,
        "distance_dollars": vwap_distance,
        "distance_pct": (vwap_distance / vwap_value * 100.0) if vwap_value else None,
        "position": "ABOVE" if vwap_distance and vwap_distance > 0 else "BELOW" if vwap_distance and vwap_distance < 0 else "AT" if vwap_value is not None else "UNAVAILABLE",
    }
    snapshot_frame = frame.reset_index()
    if "datetime" not in snapshot_frame.columns:
        snapshot_frame = snapshot_frame.rename(columns={snapshot_frame.columns[0]: "datetime"})
    market_structure = build_feature_snapshot(snapshot_frame, exclude_last_candle=False)
    entry_score = call_score if direction == "CALL" else put_score
    confidence = confidence_score_engine(
        entry_score,
        (direction == "CALL" and regime == "BULL_TREND") or (direction == "PUT" and regime == "BEAR_TREND"),
        continuation_quality,
        momentum_acceleration,
        trend_efficiency,
        momentum_expansion,
        lifecycle,
        stage,
    )
    lifecycle_v2_shadow = classify_trend_lifecycle_v2(frame, direction)
    session_market_trend_snapshot = _session_market_trend_snapshot(frame)

    return json.dumps({
        "captured_at": datetime.now(EASTERN_TZ).isoformat(),
        "direction": direction,
        "regime": regime,
        "session_market_trend": session_market_trend_snapshot["trend"],
        "session_market_trend_snapshot": session_market_trend_snapshot,
        "checklist": {
            "call_score": call_score,
            "put_score": put_score,
            "entry_score": entry_score,
            "passed": entry_score,
            "total": 5,
            "entry_reasons": call_reasons if direction == "CALL" else put_reasons,
        },
        "call_score": call_score,
        "put_score": put_score,
        "entry_score": entry_score,
        "indicator_count": entry_score,
        "indicator_total": 5,
        "trend_stage": stage,
        "momentum_phase": momentum_phase,
        "continuation_quality_score": continuation_quality.get("score"),
        "momentum_acceleration_score": momentum_acceleration.get("score"),
        "absorption_score": absorption.get("score"),
        "confidence_score": confidence.get("score"),
        "trend_lifecycle": lifecycle,
        "trend_lifecycle_v2_shadow": lifecycle_v2_shadow,
        "continuation_quality": continuation_quality,
        "momentum_acceleration": momentum_acceleration,
        "trend_efficiency": trend_efficiency,
        "momentum_expansion": momentum_expansion,
        "absorption": absorption,
        "vwap": vwap_snapshot,
        "support_resistance": market_structure.get("support_resistance", {}),
        "fibonacci_levels": market_structure.get("fibonacci_levels", {}),
        "diagnostic_provenance": "closed_candle_decision",
    }, default=str)

def get_option_chain():
    resp = client.get_option_chain(
        symbol="SPY",
        contract_type="ALL",
        strike_count=10,
        strategy="SINGLE",
    )
    resp.raise_for_status()
    return resp.json()


def _refresh_option_chain_cache(*, force=False):
    """Keep contract selection off the post-close order-submission path."""
    global _CACHED_OPTION_CHAIN, _LAST_OPTION_CHAIN_REFRESH_EPOCH

    now_epoch = time.time()
    if (
        not force
        and _CACHED_OPTION_CHAIN is not None
        and (now_epoch - _LAST_OPTION_CHAIN_REFRESH_EPOCH) < OPTION_CHAIN_CACHE_REFRESH_SECONDS
    ):
        return _CACHED_OPTION_CHAIN

    chain = get_option_chain()
    _CACHED_OPTION_CHAIN = chain
    _LAST_OPTION_CHAIN_REFRESH_EPOCH = now_epoch
    return chain


def _prewarm_entry_exposure(now_et):
    """Keep broker exposure preflight off the post-close entry critical path."""
    if (
        getattr(ENGINE_MODULE, "current_position", None) is None
        and _is_regular_market_hours_now(now_et)
        and 57 <= now_et.second <= 59
        and hasattr(ENGINE_MODULE, "preflight_entry_exposure")
    ):
        ENGINE_MODULE.preflight_entry_exposure()



STARTUP_GUARD_BLOCKED_ATTEMPTS = 1
startup_entry_attempts = 0


def _entries_are_paused():
    try:
        pause_file = Path("data") / "entry_pause.json"
        return bool((get_memory().load_setting(pause_file, {}) or {}).get("paused"))
    except Exception:
        return False


def _consume_post_exit_cooling_period():
    """Skip exactly one otherwise-qualified entry after a completed exit."""
    try:
        cooling_state = get_memory().load_setting(POST_EXIT_COOLING_PATH, {}) or {}
    except Exception:
        return False
    if not bool(cooling_state.get("pending")):
        return False

    get_memory().clear_setting("post_exit_cooling", POST_EXIT_COOLING_PATH)
    return True

def _process_manual_exit_command(
    current_price,
    option_mark,
    option_bid=None,
    option_last=None,
    quote_metadata=None,
):
    """Consume Cockpit's pending exit command before normal trade management."""
    try:
        command = get_memory().load_setting(CONTROL_COMMAND_PATH, {}) or {}
    except Exception:
        return False

    if str(command.get("action") or "").upper() != "EXIT_TRADE":
        return False
    command_status = str(command.get("status") or "").upper()
    if command_status == "SUBMITTING":
        try:
            last_attempt = datetime.fromisoformat(str(command.get("last_attempt_at") or ""))
            if last_attempt.tzinfo is None:
                last_attempt = last_attempt.replace(tzinfo=UTC_TZ)
            if (datetime.now(UTC_TZ) - last_attempt).total_seconds() < 45:
                return False
        except (TypeError, ValueError):
            pass
        command_status = "RETRYING"
    if command_status not in {"PENDING", "RETRYING"}:
        return False
    if not getattr(ENGINE_MODULE, "current_position", None):
        get_memory().clear_setting("control_command", CONTROL_COMMAND_PATH)
        return False

    command["status"] = "SUBMITTING"
    command["last_attempt_at"] = datetime.now(UTC_TZ).isoformat()
    get_memory().save_setting("control_command", command, CONTROL_COMMAND_PATH)
    print("MANUAL EXIT: submitting immediate full-position market close")

    try:
        closed = bool(ENGINE_MODULE.close_trade(
            float(current_price),
            "MANUAL_EXIT_MARKET",
            option_mark,
            execution_mode="market",
            fallback_to_market=False,
            option_bid=option_bid,
            option_last=option_last,
            quote_metadata=quote_metadata,
        ))
    except Exception as exc:
        command["status"] = "RETRYING"
        command["last_error"] = f"Exit attempt raised {type(exc).__name__}; retry remains active"
        get_memory().save_setting("control_command", command, CONTROL_COMMAND_PATH)
        print(f"MANUAL EXIT ERROR: {exc}")
        return False
    if closed:
        command["status"] = "COMPLETED"
        command["completed_at"] = datetime.now(UTC_TZ).isoformat()
        get_memory().save_setting("control_command", command, CONTROL_COMMAND_PATH)
        return True

    command["status"] = "RETRYING"
    command["last_error"] = "Schwab has not confirmed a full exit yet; retry remains active"
    get_memory().save_setting("control_command", command, CONTROL_COMMAND_PATH)
    return False

def open_trade(*args, **kwargs):
    global startup_entry_attempts, LAST_ENTRY_EXECUTION_METRICS

    start_ms = _perf_ms_now()

    if _entries_are_paused():
        print("ENTRY PAUSED: Cockpit is monitoring but new trade entries are disabled")
        LAST_ENTRY_EXECUTION_METRICS = {
            "attempted": True,
            "opened": False,
            "open_trade_ms": _elapsed_ms(start_ms),
            "block_reason": "entry_paused",
            "gate_evaluations": [{
                "code": "ENTRY_PAUSED",
                "status": "failed",
                "reason": "entry_paused",
                "source": "cockpit_control",
            }],
            "downstream_gates_not_evaluated": [
                "COOLING_PERIOD",
                "STARTUP_GUARD",
                "EXECUTION_PREFLIGHT",
            ],
        }
        return False

    if _consume_post_exit_cooling_period():
        print("ENTRY BLOCKED: Cooling Period")
        LAST_ENTRY_EXECUTION_METRICS = {
            "attempted": True,
            "opened": False,
            "open_trade_ms": _elapsed_ms(start_ms),
            "block_reason": "Cooling Period",
            "gate_evaluations": [
                {
                    "code": "ENTRY_PAUSED",
                    "status": "passed",
                    "reason": None,
                    "source": "cockpit_control",
                },
                {
                    "code": "COOLING_PERIOD",
                    "status": "failed",
                    "reason": "Cooling Period",
                    "source": "post_exit_cooling",
                },
            ],
            "downstream_gates_not_evaluated": ["STARTUP_GUARD", "EXECUTION_PREFLIGHT"],
        }
        return False

    startup_admission = LIVE_BRAIN.evaluate_startup_entry_admission(
        attempted_entries=startup_entry_attempts,
        blocked_attempts=STARTUP_GUARD_BLOCKED_ATTEMPTS,
    )
    if not startup_admission.allowed:
        startup_entry_attempts += 1
        print(f"STARTUP GUARD: blocked open_trade {startup_entry_attempts}/{STARTUP_GUARD_BLOCKED_ATTEMPTS}")
        LAST_ENTRY_EXECUTION_METRICS = {
            "attempted": True,
            "opened": False,
            "open_trade_ms": _elapsed_ms(start_ms),
            "block_reason": startup_admission.reason,
            "gate_evaluations": [
                {
                    "code": "ENTRY_PAUSED",
                    "status": "passed",
                    "reason": None,
                    "source": "cockpit_control",
                },
                {
                    "code": "COOLING_PERIOD",
                    "status": "passed",
                    "reason": None,
                    "source": "post_exit_cooling",
                },
                {
                    "code": "STARTUP_GUARD",
                    "status": "failed",
                    "reason": startup_admission.reason,
                    "source": "startup_guard",
                },
            ],
            "downstream_gates_not_evaluated": ["EXECUTION_PREFLIGHT"],
            "precheck_ms": None,
            "quote_compute_ms": None,
            "submit_order_ms": None,
            "wait_fill_ms": None,
            "market_fallback_submit_ms": None,
            "market_fallback_wait_ms": None,
            "protective_stop_ms": None,
            "persist_ms": None,
            "filled_via": None,
        }
        return False

    opened = bool(original_open_trade(*args, **kwargs))
    engine_metrics = {}
    if hasattr(ENGINE_MODULE, "get_last_open_trade_metrics"):
        try:
            engine_metrics = ENGINE_MODULE.get_last_open_trade_metrics() or {}
        except Exception:
            engine_metrics = {}
    LAST_ENTRY_EXECUTION_METRICS = {
        "attempted": True,
        "opened": opened,
        "open_trade_ms": float(engine_metrics.get("total_open_trade_ms") or _elapsed_ms(start_ms)),
        "block_reason": engine_metrics.get("block_reason") or (None if opened else "engine_block_or_reject"),
        "gate_evaluations": [
            {
                "code": "ENTRY_PAUSED",
                "status": "passed",
                "reason": None,
                "source": "cockpit_control",
            },
            {
                "code": "COOLING_PERIOD",
                "status": "passed",
                "reason": None,
                "source": "post_exit_cooling",
            },
            {
                "code": "STARTUP_GUARD",
                "status": "passed",
                "reason": None,
                "source": "startup_guard",
            },
            {
                "code": "EXECUTION_PREFLIGHT",
                "status": "passed" if opened else "failed",
                "reason": engine_metrics.get("block_reason") or (None if opened else "engine_block_or_reject"),
                "source": "live_engine",
            },
        ],
        "downstream_gates_not_evaluated": [],
        "precheck_ms": engine_metrics.get("precheck_ms"),
        "quote_compute_ms": engine_metrics.get("quote_compute_ms"),
        "submit_order_ms": engine_metrics.get("submit_order_ms"),
        "wait_fill_ms": engine_metrics.get("wait_fill_ms"),
        "reprice_submit_ms": engine_metrics.get("reprice_submit_ms"),
        "reprice_wait_ms": engine_metrics.get("reprice_wait_ms"),
        "initial_limit_price": engine_metrics.get("initial_limit_price"),
        "final_limit_price": engine_metrics.get("final_limit_price"),
        "entry_price_cap": engine_metrics.get("entry_price_cap"),
        "market_fallback_submit_ms": engine_metrics.get("market_fallback_submit_ms"),
        "market_fallback_wait_ms": engine_metrics.get("market_fallback_wait_ms"),
        "protective_stop_ms": engine_metrics.get("protective_stop_ms"),
        "persist_ms": engine_metrics.get("persist_ms"),
        "filled_via": engine_metrics.get("filled_via"),
    }
    return opened

def maybe_enter_trade(last, prev, regime, completed_candles):
    cycle_entry_start_ms = _perf_ms_now()
    min_score_threshold = LIVE_ENTRY_MIN_SCORE

    if in_trade():
        print("Entry skipped: already in trade")
        _record_shadow_pair(completed_candles, event_phase="already_in_trade")
        return {
            "attempted": False,
            "opened": False,
            "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "already_in_trade",
            "regime": regime,
            "call_score": None,
            "put_score": None,
            "call_reasons": [],
            "put_reasons": [],
            "volume_trend": None,
            "signal_threshold": min_score_threshold,
            "candidate_direction": None,
            "candidate_entry": None,
            "candidate_stop": None,
            "candidate_target": None,
            "candidate_quantity": None,
            "candidate_option_symbol": None,
            "chain_fetch_ms": None,
            "option_select_ms": None,
            "open_trade_ms": None,
            "precheck_ms": None,
            "quote_compute_ms": None,
            "submit_order_ms": None,
            "wait_fill_ms": None,
            "market_fallback_submit_ms": None,
            "market_fallback_wait_ms": None,
            "protective_stop_ms": None,
            "persist_ms": None,
            "entry_block_reason": None,
            "filled_via": None,
        }

    entry_decision = LIVE_BRAIN.evaluate_entry(last, prev, completed_candles)
    regime = entry_decision["regime"]
    call_score = entry_decision["call_score"]
    put_score = entry_decision["put_score"]
    call_reasons = entry_decision["call_reasons"]
    put_reasons = entry_decision["put_reasons"]
    vol = entry_decision["volume"]

    trend = "NEUTRAL" if regime == "NO_TRADE" else regime
    print(f"Trend: {trend}")

    print(f"Volume-adjusted scores: CALL={call_score} | PUT={put_score}")

    print(f"Call score: {call_score} | Put score: {put_score}")
    print(f"Call reasons: {call_reasons}")
    print(f"Put reasons: {put_reasons}")

    log_signal(float(last.close), regime, call_score, put_score)
    _publish_indicator_scores(
        last,
        regime,
        call_score,
        put_score,
        call_reasons,
        put_reasons,
        vol.get("trend"),
    )
    lifecycle_v2_shadow = classify_trend_lifecycle_v2(
        completed_candles,
        entry_decision.get("direction"),
    )
    record_lifecycle_shadow_snapshot(
        candle_time=last.name,
        lifecycle=lifecycle_v2_shadow,
        regime=regime,
        call_score=call_score,
        put_score=put_score,
        candidate_direction=entry_decision.get("direction"),
        candle_source=LAST_CANDLE_SOURCE,
    )

    if not _is_entry_window_now():
        candidate_direction = entry_decision.get("direction")
        _log_shadow_opportunities(
            last=last, prev=prev, completed_candles=completed_candles, regime=regime,
            call_score=call_score, call_reasons=call_reasons, put_score=put_score,
            put_reasons=put_reasons, entered_call=False, entered_put=False,
            blocked_entry={
                "direction": candidate_direction,
                "reason": "No new entries at or after 3:45 PM ET",
                "source": "entry_window",
                "gate_evaluations": [{
                    "code": "ENTRY_WINDOW_CLOSED",
                    "status": "failed",
                    "reason": "No new entries at or after 3:45 PM ET",
                    "source": "entry_window",
                }],
                "downstream_gates_not_evaluated": [
                    "CONTINUATION_FORECAST",
                    "OPTION_SELECTION",
                    "CANDIDATE_CONTROLS",
                    "EXECUTION_PREFLIGHT",
                ],
            } if candidate_direction in {"CALL", "PUT"} else None,
        )
        return {
            "attempted": False,
            "opened": False,
            "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "post_market_learning_only",
            "entry_block_reason": "No new entries at or after 3:45 PM ET",
            "regime": regime,
            "call_score": call_score,
            "put_score": put_score,
            "call_reasons": call_reasons,
            "put_reasons": put_reasons,
            "volume_trend": vol.get("trend"),
            "signal_threshold": min_score_threshold,
            "candidate_direction": entry_decision["direction"],
            "candidate_entry": float(last.close),
            "candidate_stop": None,
            "candidate_target": None,
            "candidate_quantity": None,
            "candidate_option_symbol": None,
            "chain_fetch_ms": None,
            "option_select_ms": None,
            "open_trade_ms": None,
            "precheck_ms": None,
            "quote_compute_ms": None,
            "submit_order_ms": None,
            "wait_fill_ms": None,
            "market_fallback_submit_ms": None,
            "market_fallback_wait_ms": None,
            "protective_stop_ms": None,
            "persist_ms": None,
            "filled_via": None,
        }

    candidate_direction = entry_decision["direction"]
    if candidate_direction in {"CALL", "PUT"}:
        candidate_score = call_score if candidate_direction == "CALL" else put_score
        forecast = _continuation_forecast(completed_candles, candidate_direction, candidate_score, regime)
        forecast_allowed, forecast_reason = _continuation_forecast_admission(forecast)
    else:
        forecast_allowed, forecast_reason = True, None
    if candidate_direction in {"CALL", "PUT"} and not forecast_allowed:
        print(f"ENTRY BLOCKED: {forecast_reason}")
        _log_shadow_opportunities(
            last=last, prev=prev, completed_candles=completed_candles, regime=regime,
            call_score=call_score, call_reasons=call_reasons, put_score=put_score,
            put_reasons=put_reasons, entered_call=False, entered_put=False,
            blocked_entry={
                "direction": candidate_direction,
                "reason": forecast_reason,
                "source": "continuation_forecast",
                "gate_evaluations": [{
                    "code": "CONTINUATION_FORECAST",
                    "status": "failed",
                    "reason": forecast_reason,
                    "source": "continuation_forecast",
                }],
                "downstream_gates_not_evaluated": [
                    "OPTION_SELECTION",
                    "CANDIDATE_CONTROLS",
                    "EXECUTION_PREFLIGHT",
                ],
            },
        )
        return {
            "attempted": False, "opened": False, "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "continuation_forecast_filter", "entry_block_reason": forecast_reason,
            "regime": regime, "call_score": call_score, "put_score": put_score,
            "call_reasons": call_reasons, "put_reasons": put_reasons, "volume_trend": vol.get("trend"),
            "signal_threshold": min_score_threshold, "candidate_direction": candidate_direction,
            "candidate_entry": float(last.close), "candidate_stop": None, "candidate_target": None,
            "candidate_quantity": None, "candidate_option_symbol": None, "chain_fetch_ms": None,
            "option_select_ms": None, "open_trade_ms": None, "precheck_ms": None,
            "quote_compute_ms": None, "submit_order_ms": None, "wait_fill_ms": None,
            "market_fallback_submit_ms": None, "market_fallback_wait_ms": None,
            "protective_stop_ms": None, "persist_ms": None, "filled_via": None,
        }

    if entry_decision["direction"] == "CALL":
        trade_plan = LIVE_BRAIN.build_trade("CALL", float(last.close))
        entry, stop, target, quantity = (
            trade_plan["entry"], trade_plan["stop"], trade_plan["target"], trade_plan["quantity"]
        )

        chain_start_ms = _perf_ms_now()
        chain = _CACHED_OPTION_CHAIN or _refresh_option_chain_cache(force=True)
        chain_fetch_ms = _elapsed_ms(chain_start_ms)

        select_start_ms = _perf_ms_now()
        option = select_option_from_chain(chain, "CALL", entry)
        option_select_ms = _elapsed_ms(select_start_ms)
        option_block_reason = option_selection_block_reason(chain, "CALL") if option is None else None
        feature_payload = _build_entry_feature_payload(
            completed_candles, "CALL", regime, call_score, put_score, call_reasons, put_reasons
        )
        feature_payload_data = json.loads(feature_payload)
        observation = observe_candidate(completed_candles, "CALL")
        feature_payload_data.update(observation)
        shadow_suite = evaluate_day_trade_spy_shadow_suite(
            completed_candles,
            "CALL",
            feature_payload=feature_payload_data,
            option=option,
            trade_plan={
                "entry": entry,
                "stop": stop,
                "target": target,
                "quantity": quantity,
            },
            same_regime_attempt_count=_prior_shadow_attempts(last.name, "CALL"),
            provenance="captured_live",
        )
        feature_payload_data["day_trade_spy_shadow_suite"] = shadow_suite
        record_candidate_observation(observation, feature_payload=feature_payload_data, option=option)
        feature_payload = json.dumps(feature_payload_data, default=str)
        control_block_reasons = _candidate_control_block_reasons(feature_payload, option)
        control_block_reason = control_block_reasons[0] if control_block_reasons else None
        candidate_block_reason = option_block_reason or control_block_reason
        if candidate_block_reason:
            print(f"ENTRY BLOCKED: {candidate_block_reason}")
            _log_shadow_opportunities(
                last=last, prev=prev, completed_candles=completed_candles, regime=regime,
                call_score=call_score, call_reasons=call_reasons, put_score=put_score,
                put_reasons=put_reasons, entered_call=False, entered_put=False,
                feature_payload=feature_payload, selected_option_call=option,
                blocked_entry={
                    "direction": "CALL",
                    "reason": candidate_block_reason,
                    "source": "candidate_admission",
                    "gate_evaluations": [
                        {
                            "code": "OPTION_SELECTION",
                            "status": "failed" if option_block_reason else "passed",
                            "reason": option_block_reason,
                            "source": "option_selector",
                        },
                        *[
                            {
                                "code": str(reason or "CANDIDATE_CONTROLS").upper(),
                                "status": "failed" if reason else "passed",
                                "reason": reason,
                                "source": "candidate_controls",
                            }
                            for reason in (control_block_reasons or [None])
                        ],
                    ],
                    "downstream_gates_not_evaluated": ["EXECUTION_PREFLIGHT"],
                },
            )
            return {
                "attempted": False, "opened": False, "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
                "decision_reason": "candidate_entry_control", "entry_block_reason": candidate_block_reason,
                "regime": regime, "call_score": call_score, "put_score": put_score,
                "call_reasons": call_reasons, "put_reasons": put_reasons, "volume_trend": vol.get("trend"),
                "signal_threshold": min_score_threshold, "candidate_direction": "CALL", "candidate_entry": entry,
                "candidate_stop": stop, "candidate_target": target, "candidate_quantity": quantity,
                "candidate_option_symbol": option.get("symbol") if isinstance(option, dict) else None, "chain_fetch_ms": chain_fetch_ms,
                "option_select_ms": option_select_ms, "open_trade_ms": None, "precheck_ms": None,
                "quote_compute_ms": None, "submit_order_ms": None, "wait_fill_ms": None,
                "market_fallback_submit_ms": None, "market_fallback_wait_ms": None,
                "protective_stop_ms": None, "persist_ms": None, "filled_via": None,
            }

        open_start_ms = _perf_ms_now()
        opened = bool(open_trade("CALL", entry, stop, target, quantity, trade_plan["reason"], option, feature_payload))
        open_trade_call_ms = _elapsed_ms(open_start_ms)
        blocked_entry = None
        if not opened and LAST_ENTRY_EXECUTION_METRICS.get("block_reason"):
            blocked_entry = {
                "direction": "CALL",
                "reason": LAST_ENTRY_EXECUTION_METRICS["block_reason"],
                "source": "open_trade",
                "gate_evaluations": LAST_ENTRY_EXECUTION_METRICS.get("gate_evaluations") or [],
                "downstream_gates_not_evaluated": LAST_ENTRY_EXECUTION_METRICS.get("downstream_gates_not_evaluated") or [],
                "intended_trade": {
                    "underlying_entry": entry, "underlying_stop": stop, "underlying_target": target,
                    "quantity": quantity, "reason": trade_plan["reason"],
                    "option_symbol": option.get("symbol") if isinstance(option, dict) else None,
                    "option_mark": option.get("mark") if isinstance(option, dict) else None,
                    "option_bid": option.get("bid") if isinstance(option, dict) else None,
                    "option_ask": option.get("ask") if isinstance(option, dict) else None,
                },
            }
        _log_shadow_opportunities(
            last=last,
            prev=prev,
            completed_candles=completed_candles,
            regime=regime,
            call_score=call_score,
            call_reasons=call_reasons,
            put_score=put_score,
            put_reasons=put_reasons,
            entered_call=opened,
            entered_put=False,
            feature_payload=feature_payload,
            selected_option_call=option,
            blocked_entry=blocked_entry,
        )
        return {
            "attempted": True,
            "opened": opened,
            "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "bull_call_signal",
            "regime": regime,
            "call_score": call_score,
            "put_score": put_score,
            "call_reasons": call_reasons,
            "put_reasons": put_reasons,
            "volume_trend": vol.get("trend"),
            "signal_threshold": min_score_threshold,
            "candidate_direction": "CALL",
            "candidate_entry": entry,
            "candidate_stop": stop,
            "candidate_target": target,
            "candidate_quantity": quantity,
            "candidate_option_symbol": option.get("symbol") if isinstance(option, dict) else None,
            "chain_fetch_ms": chain_fetch_ms,
            "option_select_ms": option_select_ms,
            "open_trade_ms": LAST_ENTRY_EXECUTION_METRICS.get("open_trade_ms") or open_trade_call_ms,
            "precheck_ms": LAST_ENTRY_EXECUTION_METRICS.get("precheck_ms"),
            "quote_compute_ms": LAST_ENTRY_EXECUTION_METRICS.get("quote_compute_ms"),
            "submit_order_ms": LAST_ENTRY_EXECUTION_METRICS.get("submit_order_ms"),
            "wait_fill_ms": LAST_ENTRY_EXECUTION_METRICS.get("wait_fill_ms"),
            "reprice_submit_ms": LAST_ENTRY_EXECUTION_METRICS.get("reprice_submit_ms"),
            "reprice_wait_ms": LAST_ENTRY_EXECUTION_METRICS.get("reprice_wait_ms"),
            "initial_limit_price": LAST_ENTRY_EXECUTION_METRICS.get("initial_limit_price"),
            "final_limit_price": LAST_ENTRY_EXECUTION_METRICS.get("final_limit_price"),
            "entry_price_cap": LAST_ENTRY_EXECUTION_METRICS.get("entry_price_cap"),
            "market_fallback_submit_ms": LAST_ENTRY_EXECUTION_METRICS.get("market_fallback_submit_ms"),
            "market_fallback_wait_ms": LAST_ENTRY_EXECUTION_METRICS.get("market_fallback_wait_ms"),
            "protective_stop_ms": LAST_ENTRY_EXECUTION_METRICS.get("protective_stop_ms"),
            "persist_ms": LAST_ENTRY_EXECUTION_METRICS.get("persist_ms"),
            "entry_block_reason": LAST_ENTRY_EXECUTION_METRICS.get("block_reason"),
            "filled_via": LAST_ENTRY_EXECUTION_METRICS.get("filled_via"),
        }

    elif entry_decision["direction"] == "PUT":
        trade_plan = LIVE_BRAIN.build_trade("PUT", float(last.close))
        entry, stop, target, quantity = (
            trade_plan["entry"], trade_plan["stop"], trade_plan["target"], trade_plan["quantity"]
        )

        chain_start_ms = _perf_ms_now()
        chain = _CACHED_OPTION_CHAIN or _refresh_option_chain_cache(force=True)
        chain_fetch_ms = _elapsed_ms(chain_start_ms)

        select_start_ms = _perf_ms_now()
        option = select_option_from_chain(chain, "PUT", entry)
        option_select_ms = _elapsed_ms(select_start_ms)
        option_block_reason = option_selection_block_reason(chain, "PUT") if option is None else None
        feature_payload = _build_entry_feature_payload(
            completed_candles, "PUT", regime, call_score, put_score, call_reasons, put_reasons
        )
        feature_payload_data = json.loads(feature_payload)
        observation = observe_candidate(completed_candles, "PUT")
        feature_payload_data.update(observation)
        shadow_suite = evaluate_day_trade_spy_shadow_suite(
            completed_candles,
            "PUT",
            feature_payload=feature_payload_data,
            option=option,
            trade_plan={
                "entry": entry,
                "stop": stop,
                "target": target,
                "quantity": quantity,
            },
            same_regime_attempt_count=_prior_shadow_attempts(last.name, "PUT"),
            provenance="captured_live",
        )
        feature_payload_data["day_trade_spy_shadow_suite"] = shadow_suite
        record_candidate_observation(observation, feature_payload=feature_payload_data, option=option)
        feature_payload = json.dumps(feature_payload_data, default=str)
        control_block_reasons = _candidate_control_block_reasons(feature_payload, option)
        control_block_reason = control_block_reasons[0] if control_block_reasons else None
        candidate_block_reason = option_block_reason or control_block_reason
        if candidate_block_reason:
            print(f"ENTRY BLOCKED: {candidate_block_reason}")
            _log_shadow_opportunities(
                last=last, prev=prev, completed_candles=completed_candles, regime=regime,
                call_score=call_score, call_reasons=call_reasons, put_score=put_score,
                put_reasons=put_reasons, entered_call=False, entered_put=False,
                feature_payload=feature_payload, selected_option_put=option,
                blocked_entry={
                    "direction": "PUT",
                    "reason": candidate_block_reason,
                    "source": "candidate_admission",
                    "gate_evaluations": [
                        {
                            "code": "OPTION_SELECTION",
                            "status": "failed" if option_block_reason else "passed",
                            "reason": option_block_reason,
                            "source": "option_selector",
                        },
                        *[
                            {
                                "code": str(reason or "CANDIDATE_CONTROLS").upper(),
                                "status": "failed" if reason else "passed",
                                "reason": reason,
                                "source": "candidate_controls",
                            }
                            for reason in (control_block_reasons or [None])
                        ],
                    ],
                    "downstream_gates_not_evaluated": ["EXECUTION_PREFLIGHT"],
                },
            )
            return {
                "attempted": False, "opened": False, "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
                "decision_reason": "candidate_entry_control", "entry_block_reason": candidate_block_reason,
                "regime": regime, "call_score": call_score, "put_score": put_score,
                "call_reasons": call_reasons, "put_reasons": put_reasons, "volume_trend": vol.get("trend"),
                "signal_threshold": min_score_threshold, "candidate_direction": "PUT", "candidate_entry": entry,
                "candidate_stop": stop, "candidate_target": target, "candidate_quantity": quantity,
                "candidate_option_symbol": option.get("symbol") if isinstance(option, dict) else None, "chain_fetch_ms": chain_fetch_ms,
                "option_select_ms": option_select_ms, "open_trade_ms": None, "precheck_ms": None,
                "quote_compute_ms": None, "submit_order_ms": None, "wait_fill_ms": None,
                "market_fallback_submit_ms": None, "market_fallback_wait_ms": None,
                "protective_stop_ms": None, "persist_ms": None, "filled_via": None,
            }

        open_start_ms = _perf_ms_now()
        opened = bool(open_trade("PUT", entry, stop, target, quantity, trade_plan["reason"], option, feature_payload))
        open_trade_call_ms = _elapsed_ms(open_start_ms)
        blocked_entry = None
        if not opened and LAST_ENTRY_EXECUTION_METRICS.get("block_reason"):
            blocked_entry = {
                "direction": "PUT",
                "reason": LAST_ENTRY_EXECUTION_METRICS["block_reason"],
                "source": "open_trade",
                "gate_evaluations": LAST_ENTRY_EXECUTION_METRICS.get("gate_evaluations") or [],
                "downstream_gates_not_evaluated": LAST_ENTRY_EXECUTION_METRICS.get("downstream_gates_not_evaluated") or [],
                "intended_trade": {
                    "underlying_entry": entry, "underlying_stop": stop, "underlying_target": target,
                    "quantity": quantity, "reason": trade_plan["reason"],
                    "option_symbol": option.get("symbol") if isinstance(option, dict) else None,
                    "option_mark": option.get("mark") if isinstance(option, dict) else None,
                    "option_bid": option.get("bid") if isinstance(option, dict) else None,
                    "option_ask": option.get("ask") if isinstance(option, dict) else None,
                },
            }
        _log_shadow_opportunities(
            last=last,
            prev=prev,
            completed_candles=completed_candles,
            regime=regime,
            call_score=call_score,
            call_reasons=call_reasons,
            put_score=put_score,
            put_reasons=put_reasons,
            entered_call=False,
            entered_put=opened,
            feature_payload=feature_payload,
            selected_option_put=option,
            blocked_entry=blocked_entry,
        )
        return {
            "attempted": True,
            "opened": opened,
            "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "bear_put_signal",
            "regime": regime,
            "call_score": call_score,
            "put_score": put_score,
            "call_reasons": call_reasons,
            "put_reasons": put_reasons,
            "volume_trend": vol.get("trend"),
            "signal_threshold": min_score_threshold,
            "candidate_direction": "PUT",
            "candidate_entry": entry,
            "candidate_stop": stop,
            "candidate_target": target,
            "candidate_quantity": quantity,
            "candidate_option_symbol": option.get("symbol") if isinstance(option, dict) else None,
            "chain_fetch_ms": chain_fetch_ms,
            "option_select_ms": option_select_ms,
            "open_trade_ms": LAST_ENTRY_EXECUTION_METRICS.get("open_trade_ms") or open_trade_call_ms,
            "precheck_ms": LAST_ENTRY_EXECUTION_METRICS.get("precheck_ms"),
            "quote_compute_ms": LAST_ENTRY_EXECUTION_METRICS.get("quote_compute_ms"),
            "submit_order_ms": LAST_ENTRY_EXECUTION_METRICS.get("submit_order_ms"),
            "wait_fill_ms": LAST_ENTRY_EXECUTION_METRICS.get("wait_fill_ms"),
            "reprice_submit_ms": LAST_ENTRY_EXECUTION_METRICS.get("reprice_submit_ms"),
            "reprice_wait_ms": LAST_ENTRY_EXECUTION_METRICS.get("reprice_wait_ms"),
            "initial_limit_price": LAST_ENTRY_EXECUTION_METRICS.get("initial_limit_price"),
            "final_limit_price": LAST_ENTRY_EXECUTION_METRICS.get("final_limit_price"),
            "entry_price_cap": LAST_ENTRY_EXECUTION_METRICS.get("entry_price_cap"),
            "market_fallback_submit_ms": LAST_ENTRY_EXECUTION_METRICS.get("market_fallback_submit_ms"),
            "market_fallback_wait_ms": LAST_ENTRY_EXECUTION_METRICS.get("market_fallback_wait_ms"),
            "protective_stop_ms": LAST_ENTRY_EXECUTION_METRICS.get("protective_stop_ms"),
            "persist_ms": LAST_ENTRY_EXECUTION_METRICS.get("persist_ms"),
            "entry_block_reason": LAST_ENTRY_EXECUTION_METRICS.get("block_reason"),
            "filled_via": LAST_ENTRY_EXECUTION_METRICS.get("filled_via"),
        }

    _log_shadow_opportunities(
        last=last,
        prev=prev,
        completed_candles=completed_candles,
        regime=regime,
        call_score=call_score,
        call_reasons=call_reasons,
        put_score=put_score,
        put_reasons=put_reasons,
        entered_call=False,
        entered_put=False,
    )
    return {
        "attempted": False,
        "opened": False,
        "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
        "decision_reason": "no_entry_signal",
        "regime": regime,
        "call_score": call_score,
        "put_score": put_score,
        "call_reasons": call_reasons,
        "put_reasons": put_reasons,
        "volume_trend": vol.get("trend"),
        "signal_threshold": min_score_threshold,
        "candidate_direction": None,
        "candidate_entry": float(last.close),
        "candidate_stop": None,
        "candidate_target": None,
        "candidate_quantity": None,
        "candidate_option_symbol": None,
        "chain_fetch_ms": None,
        "option_select_ms": None,
        "open_trade_ms": None,
        "precheck_ms": None,
        "quote_compute_ms": None,
        "submit_order_ms": None,
        "wait_fill_ms": None,
        "market_fallback_submit_ms": None,
        "market_fallback_wait_ms": None,
        "protective_stop_ms": None,
        "persist_ms": None,
        "entry_block_reason": None,
        "filled_via": None,
    }


def run_monitor(*, max_cycles=None, runtime_initializer=_initialize_live_runtime, sleep_fn=time.sleep):
    """Run the production monitor; bounded cycles are for deterministic tests only."""
    global last_processed_candle_time
    runtime_initializer()
    if client is not None:
        try:
            _refresh_option_chain_cache(force=True)
        except Exception as exc:
            print(f"Option-chain prewarm unavailable: {exc}")
    print("McLeod Alpha Phase 3 monitor started.")
    print("Mode: LIVE TRADING")
    last_processed_candle_time = None
    completed_cycles = 0
    while max_cycles is None or completed_cycles < max_cycles:
        completed_cycles += 1
        cycle_start_ms = _perf_ms_now()
        position_management_ran = False
        try:
            position_management_ran = _enforce_end_of_day_exit()
            if not position_management_ran:
                position_management_ran = _manage_open_position_priority()
        except Exception as exc:
            print(f"Priority position management error: {exc}")
        if (
            position_management_ran
            and getattr(ENGINE_MODULE, "current_position", None) is not None
        ):
            # An open option needs fast quote/stop attention more than another
            # candle-history refresh. Entry evaluation is impossible while a
            # position is open, so keep this loop dedicated to execution until
            # Schwab confirms the position is flat.
            sleep_fn(OPEN_POSITION_POLL_SECONDS)
            continue
        try:
            candles_fetch_start_ms = _perf_ms_now()
            df = get_candles()
            candles_fetch_ms = _elapsed_ms(candles_fetch_start_ms)
        except Exception as e:
            print(f"Candle fetch error: {e}")
            _append_latency_skip_event(reason="candle_fetch_error", cycle_start_ms=cycle_start_ms)
            _run_noncritical_schedulers()
            sleep_fn(_cycle_sleep_seconds())
            continue
        latest_candle_time = df.iloc[-1].name if not df.empty else None
        latest_candle_text = latest_candle_time.strftime("%Y-%m-%d %H:%M:%S") if latest_candle_time is not None else "none"
        fetched_closed_candle = LAST_CANDLE_SOURCE == "live_window"
        if fetched_closed_candle:
            print(f"Candles received: {len(df)} | source={LAST_CANDLE_SOURCE} | latest={latest_candle_text}")
        if len(df) < 15:
            print("Waiting for enough candle data...")
            _append_latency_skip_event(
                reason="insufficient_candles",
                cycle_start_ms=cycle_start_ms,
                candles_fetch_ms=candles_fetch_ms,
            )
            _run_noncritical_schedulers()
            sleep_fn(_cycle_sleep_seconds())
            continue

        indicators_start_ms = _perf_ms_now()
        df = add_indicators(df)
        indicators_ms = _elapsed_ms(indicators_start_ms)
        ready, reason = _indicators_ready(df)
        if not ready:
            print(f"Indicator guard: {reason}; skipping cycle")
            _append_latency_skip_event(
                reason=f"indicator_guard:{reason}",
                cycle_start_ms=cycle_start_ms,
                candles_fetch_ms=candles_fetch_ms,
                indicators_ms=indicators_ms,
            )
            _run_noncritical_schedulers()
            sleep_fn(_cycle_sleep_seconds())
            continue

        latest = df.iloc[-1]
        latest_prev = df.iloc[-2]
        latest_regime = market_regime(latest, latest_prev)

        if fetched_closed_candle:
            print(
                f"\n{datetime.now(EASTERN_TZ).strftime('%H:%M:%S')} ET | "
                f"{SYMBOL} {latest.close:.2f} | {latest_regime}"
            )

        manage_start_ms = _perf_ms_now()
        if not position_management_ran and getattr(ENGINE_MODULE, "current_position", None) is None:
            manage_trade(float(latest.close), None, None, None, None)
        manage_trade_ms = _elapsed_ms(manage_start_ms)
        try:
            SpyBotReviewer(Path(__file__).resolve().parent).maybe_run_after_session()
        except Exception as exc:
            print(f"SPY Bot Reviewer scheduling warning: {exc}")

        now_et = datetime.now(EASTERN_TZ)
        if (
            not getattr(ENGINE_MODULE, "current_position", None)
            and _is_regular_market_hours_now()
            and 5 <= now_et.second <= 55
        ):
            try:
                _refresh_option_chain_cache()
            except Exception as exc:
                print(f"Option-chain cache refresh unavailable: {exc}")
        try:
            _prewarm_entry_exposure(now_et)
        except Exception as exc:
            print(f"Entry exposure preflight unavailable: {exc}")
        signal_cycle = plan_signal_cycle(
            df,
            now_et,
            last_evaluated_candle_time=last_processed_candle_time,
        )
        if not signal_cycle.should_evaluate:
            _append_latency_skip_event(
                reason=f"closed_candle:{signal_cycle.reason}",
                cycle_start_ms=cycle_start_ms,
                candles_fetch_ms=candles_fetch_ms,
                indicators_ms=indicators_ms,
            )
            _run_noncritical_schedulers()
            sleep_fn(_cycle_sleep_seconds())
            continue

        last = signal_cycle.last_row
        prev = signal_cycle.prev_row
        regime = market_regime(last, prev)

        if not _is_regular_market_hours_now() and LAST_CANDLE_SOURCE != "live_window":
            print(
                "Off-hours candle heartbeat active; skipping new entry evaluation until regular market hours"
            )
            last_processed_candle_time = signal_cycle.candle_timestamp
            _append_latency_skip_event(
                reason="off_hours_skip",
                cycle_start_ms=cycle_start_ms,
                candles_fetch_ms=candles_fetch_ms,
                indicators_ms=indicators_ms,
            )
            _run_noncritical_schedulers()
            sleep_fn(_cycle_sleep_seconds())
            continue

        entry_metrics = maybe_enter_trade(last, prev, regime, signal_cycle.completed_df)

        report_start_ms = _perf_ms_now()
        maybe_generate_daily_strategy_effectiveness_report()
        report_ms = _elapsed_ms(report_start_ms)

        cycle_total_ms = _elapsed_ms(cycle_start_ms)
        print(
            "LATENCY(ms): "
            f"candles={candles_fetch_ms:.2f} "
            f"indicators={indicators_ms:.2f} "
            f"manage={manage_trade_ms:.2f} "
            f"entry_eval={float(entry_metrics.get('entry_eval_ms') or 0.0):.2f} "
            f"entry_precheck={float(entry_metrics.get('precheck_ms') or 0.0):.2f} "
            f"entry_quote={float(entry_metrics.get('quote_compute_ms') or 0.0):.2f} "
            f"entry_submit={float(entry_metrics.get('submit_order_ms') or 0.0):.2f} "
            f"entry_wait={float(entry_metrics.get('wait_fill_ms') or 0.0):.2f} "
            f"entry_reprice_submit={float(entry_metrics.get('reprice_submit_ms') or 0.0):.2f} "
            f"entry_reprice_wait={float(entry_metrics.get('reprice_wait_ms') or 0.0):.2f} "
            f"entry_fallback_submit={float(entry_metrics.get('market_fallback_submit_ms') or 0.0):.2f} "
            f"entry_fallback_wait={float(entry_metrics.get('market_fallback_wait_ms') or 0.0):.2f} "
            f"entry_stop={float(entry_metrics.get('protective_stop_ms') or 0.0):.2f} "
            f"entry_persist={float(entry_metrics.get('persist_ms') or 0.0):.2f} "
            f"open_trade={float(entry_metrics.get('open_trade_ms') or 0.0):.2f} "
            f"report={report_ms:.2f} "
            f"cycle_total={cycle_total_ms:.2f}"
        )

        _append_latency_event({
            "ts_utc": datetime.now(UTC_TZ).isoformat(),
            "ts_et": datetime.now(EASTERN_TZ).isoformat(),
            "symbol": SYMBOL,
            "candle_source": LAST_CANDLE_SOURCE,
            "regime": regime,
            "candles_count": int(len(df)),
            "candles_fetch_ms": candles_fetch_ms,
            "indicators_ms": indicators_ms,
            "manage_trade_ms": manage_trade_ms,
            "entry_attempted": bool(entry_metrics.get("attempted")),
            "entry_opened": bool(entry_metrics.get("opened")),
            "entry_decision_reason": entry_metrics.get("decision_reason"),
            "entry_eval_ms": entry_metrics.get("entry_eval_ms"),
            "chain_fetch_ms": entry_metrics.get("chain_fetch_ms"),
            "option_select_ms": entry_metrics.get("option_select_ms"),
            "entry_precheck_ms": entry_metrics.get("precheck_ms"),
            "entry_quote_compute_ms": entry_metrics.get("quote_compute_ms"),
            "entry_submit_order_ms": entry_metrics.get("submit_order_ms"),
            "entry_wait_fill_ms": entry_metrics.get("wait_fill_ms"),
            "entry_reprice_submit_ms": entry_metrics.get("reprice_submit_ms"),
            "entry_reprice_wait_ms": entry_metrics.get("reprice_wait_ms"),
            "entry_initial_limit_price": entry_metrics.get("initial_limit_price"),
            "entry_final_limit_price": entry_metrics.get("final_limit_price"),
            "entry_price_cap": entry_metrics.get("entry_price_cap"),
            "entry_market_fallback_submit_ms": entry_metrics.get("market_fallback_submit_ms"),
            "entry_market_fallback_wait_ms": entry_metrics.get("market_fallback_wait_ms"),
            "entry_protective_stop_ms": entry_metrics.get("protective_stop_ms"),
            "entry_persist_ms": entry_metrics.get("persist_ms"),
            "entry_block_reason": entry_metrics.get("entry_block_reason"),
            "entry_filled_via": entry_metrics.get("filled_via"),
            "open_trade_ms": entry_metrics.get("open_trade_ms"),
            "report_ms": report_ms,
            "cycle_total_ms": cycle_total_ms,
        })

        _append_decision_audit_event({
            "ts_utc": datetime.now(UTC_TZ).isoformat(),
            "ts_et": datetime.now(EASTERN_TZ).isoformat(),
            "symbol": SYMBOL,
            "event_type": "entry_evaluation",
            "candle_source": LAST_CANDLE_SOURCE,
            "candle_time": str(last.name),
            "spy_open": float(last.open),
            "spy_high": float(last.high),
            "spy_low": float(last.low),
            "spy_close": float(last.close),
            "spy_volume": float(last.volume),
            "regime": regime,
            "entry_attempted": bool(entry_metrics.get("attempted")),
            "entry_opened": bool(entry_metrics.get("opened")),
            "entry_decision_reason": entry_metrics.get("decision_reason"),
            "entry_block_reason": entry_metrics.get("entry_block_reason"),
            "entry_filled_via": entry_metrics.get("filled_via"),
            "call_score": entry_metrics.get("call_score"),
            "put_score": entry_metrics.get("put_score"),
            "call_reasons": entry_metrics.get("call_reasons") or [],
            "put_reasons": entry_metrics.get("put_reasons") or [],
            "volume_trend": entry_metrics.get("volume_trend"),
            "signal_threshold": entry_metrics.get("signal_threshold"),
            "candidate_direction": entry_metrics.get("candidate_direction"),
            "candidate_entry": entry_metrics.get("candidate_entry"),
            "candidate_stop": entry_metrics.get("candidate_stop"),
            "candidate_target": entry_metrics.get("candidate_target"),
            "candidate_quantity": entry_metrics.get("candidate_quantity"),
            "candidate_option_symbol": entry_metrics.get("candidate_option_symbol"),
            "candles_fetch_ms": candles_fetch_ms,
            "indicators_ms": indicators_ms,
            "manage_trade_ms": manage_trade_ms,
            "entry_eval_ms": entry_metrics.get("entry_eval_ms"),
            "entry_precheck_ms": entry_metrics.get("precheck_ms"),
            "entry_quote_compute_ms": entry_metrics.get("quote_compute_ms"),
            "entry_submit_order_ms": entry_metrics.get("submit_order_ms"),
            "entry_wait_fill_ms": entry_metrics.get("wait_fill_ms"),
            "entry_reprice_submit_ms": entry_metrics.get("reprice_submit_ms"),
            "entry_reprice_wait_ms": entry_metrics.get("reprice_wait_ms"),
            "entry_initial_limit_price": entry_metrics.get("initial_limit_price"),
            "entry_final_limit_price": entry_metrics.get("final_limit_price"),
            "entry_price_cap": entry_metrics.get("entry_price_cap"),
            "entry_market_fallback_submit_ms": entry_metrics.get("market_fallback_submit_ms"),
            "entry_market_fallback_wait_ms": entry_metrics.get("market_fallback_wait_ms"),
            "entry_protective_stop_ms": entry_metrics.get("protective_stop_ms"),
            "entry_persist_ms": entry_metrics.get("persist_ms"),
            "open_trade_ms": entry_metrics.get("open_trade_ms"),
            "report_ms": report_ms,
            "cycle_total_ms": cycle_total_ms,
        })

        _run_noncritical_schedulers()

        last_processed_candle_time = signal_cycle.candle_timestamp

        sleep_fn(_cycle_sleep_seconds())


if __name__ == "__main__":
    run_monitor()
