from execution.option_selector import select_option_from_chain, find_option_mark, find_option_bid
from execution.equity_stream import SchwabEquityQuoteStream
from execution.opportunity_logger import log_evaluated_setups
from execution.signal_logger import log_signal
from reports.daily_strategy_effectiveness import maybe_generate_daily_strategy_effectiveness_report
from engine.brain import Brain, LIVE_ENTRY_MIN_SCORE, classify_entry_regime as market_regime
from engine.memory import get_memory
from spy_bot_reviewer import SpyBotReviewer
from strategy.live_candle_builder import LiveMinuteCandleBuilder
from strategy.monitor_cycle import plan_signal_cycle
from strategy.signals import build_feature_snapshot
from backtesting.signal_replay import confidence_score_engine

import os
import sys
import time
import json
import importlib
import requests
from datetime import datetime, timedelta
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
_LAST_HISTORY_REFRESH_EPOCH = 0.0
_LAST_HISTORY_FETCH_MINUTE = None
OPTION_CHAIN_CACHE_REFRESH_SECONDS = max(1.0, float(os.getenv("OPTION_CHAIN_CACHE_REFRESH_SECONDS", "10")))
_LAST_OPTION_CHAIN_REFRESH_EPOCH = 0.0
_CACHED_OPTION_CHAIN = None
LATENCY_METRICS_ENABLED = str(os.getenv("LATENCY_METRICS_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
LATENCY_METRICS_PATH = Path(os.getenv("LATENCY_METRICS_PATH", "data/reports/latency_cycle_history.jsonl"))
DECISION_AUDIT_ENABLED = str(os.getenv("DECISION_AUDIT_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
DECISION_AUDIT_PATH = Path(os.getenv("DECISION_AUDIT_PATH", "data/reports/decision_audit_history.jsonl"))
CONTROL_COMMAND_PATH = Path("data") / "control_command.json"
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
):
    """Capture evaluated setups as non-blocking research telemetry."""
    try:
        payload = json.loads(feature_payload) if isinstance(feature_payload, str) else feature_payload
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
            feature_payload=payload,
            selected_option_call=selected_option_call,
            selected_option_put=selected_option_put,
        )
    except Exception as exc:
        print(f"Shadow opportunity logging error: {exc}")


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


def _is_regular_market_hours_now():
    now_et = datetime.now(EASTERN_TZ)
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


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
    mark = _positive_float(quote.get("mark")) or _positive_float(quote.get("lastPrice"))
    return mark, bid


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
        }

    return {
        "call_score": decision["call_score"],
        "put_score": decision["put_score"],
        "regime": decision["regime"],
        "timestamp": indicators.index[-1],
        "call_momentum": momentum_snapshot("CALL"),
        "put_momentum": momentum_snapshot("PUT"),
    }


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

    return json.dumps({
        "captured_at": datetime.now(EASTERN_TZ).isoformat(),
        "direction": direction,
        "regime": regime,
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
        "continuation_quality_score": continuation_quality.get("score"),
        "momentum_acceleration_score": momentum_acceleration.get("score"),
        "absorption_score": absorption.get("score"),
        "confidence_score": confidence.get("score"),
        "trend_lifecycle": lifecycle,
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



STARTUP_GUARD_BLOCKED_ATTEMPTS = 1
startup_entry_attempts = 0


def _entries_are_paused():
    try:
        pause_file = Path("data") / "entry_pause.json"
        return bool((get_memory().load_setting(pause_file, {}) or {}).get("paused"))
    except Exception:
        return False

def _process_manual_exit_command(current_price, option_mark):
    """Consume Cockpit's pending exit command before normal trade management."""
    try:
        command = get_memory().load_setting(CONTROL_COMMAND_PATH, {}) or {}
    except Exception:
        return False

    if str(command.get("action") or "").upper() != "EXIT_TRADE":
        return False
    if str(command.get("status") or "").upper() not in {"PENDING", "RETRYING"}:
        return False
    if not getattr(ENGINE_MODULE, "current_position", None):
        get_memory().clear_setting("control_command", CONTROL_COMMAND_PATH)
        return False

    command["status"] = "SUBMITTING"
    command["last_attempt_at"] = datetime.now(UTC_TZ).isoformat()
    get_memory().save_setting("control_command", command, CONTROL_COMMAND_PATH)
    print("MANUAL EXIT: submitting near-market limit close with market fallback")

    closed = bool(ENGINE_MODULE.close_trade(
        float(current_price),
        "MANUAL_EXIT_LIMIT",
        option_mark,
        execution_mode="limit_near_market",
        fallback_to_market=True,
    ))
    if closed:
        command["status"] = "COMPLETED"
        command["completed_at"] = datetime.now(UTC_TZ).isoformat()
        get_memory().save_setting("control_command", command, CONTROL_COMMAND_PATH)
        return True

    command["status"] = "RETRYING"
    command["last_error"] = "Exit was not accepted or filled; protective stop remains active"
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
        "precheck_ms": engine_metrics.get("precheck_ms"),
        "quote_compute_ms": engine_metrics.get("quote_compute_ms"),
        "submit_order_ms": engine_metrics.get("submit_order_ms"),
        "wait_fill_ms": engine_metrics.get("wait_fill_ms"),
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
        feature_payload = _build_entry_feature_payload(
            completed_candles, "CALL", regime, call_score, put_score, call_reasons, put_reasons
        )

        open_start_ms = _perf_ms_now()
        opened = bool(open_trade("CALL", entry, stop, target, quantity, trade_plan["reason"], option, feature_payload))
        open_trade_call_ms = _elapsed_ms(open_start_ms)
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
        feature_payload = _build_entry_feature_payload(
            completed_candles, "PUT", regime, call_score, put_score, call_reasons, put_reasons
        )

        open_start_ms = _perf_ms_now()
        opened = bool(open_trade("PUT", entry, stop, target, quantity, trade_plan["reason"], option, feature_payload))
        open_trade_call_ms = _elapsed_ms(open_start_ms)
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
        try:
            candles_fetch_start_ms = _perf_ms_now()
            df = get_candles()
            candles_fetch_ms = _elapsed_ms(candles_fetch_start_ms)
        except Exception as e:
            print(f"Candle fetch error: {e}")
            _append_latency_skip_event(reason="candle_fetch_error", cycle_start_ms=cycle_start_ms)
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

        option_mark = None
        option_bid = None

        try:
            current_position = getattr(ENGINE_MODULE, "current_position", None)
            if current_position and getattr(current_position, "option_symbol", None):
                option_mark, option_bid = get_open_option_quote(current_position.option_symbol)

        except Exception as e:
            print(f"Option mark error: {e}")
        manage_start_ms = _perf_ms_now()
        manual_exit_requested = _process_manual_exit_command(float(latest.close), option_mark)
        if not manual_exit_requested:
            manage_trade(float(latest.close), option_mark, option_bid)
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
        if last_processed_candle_time is None:
            startup_cycle = plan_signal_cycle(df, now_et, force_attempt=True)
            last_processed_candle_time = startup_cycle.candle_timestamp
            print(
                "Closed-candle startup baseline established: "
                f"{last_processed_candle_time or 'awaiting closed candle'}"
            )
            _append_latency_skip_event(
                reason="startup_candle_baseline",
                cycle_start_ms=cycle_start_ms,
                candles_fetch_ms=candles_fetch_ms,
                indicators_ms=indicators_ms,
            )
            sleep_fn(_cycle_sleep_seconds())
            continue

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
            "entry_market_fallback_submit_ms": entry_metrics.get("market_fallback_submit_ms"),
            "entry_market_fallback_wait_ms": entry_metrics.get("market_fallback_wait_ms"),
            "entry_protective_stop_ms": entry_metrics.get("protective_stop_ms"),
            "entry_persist_ms": entry_metrics.get("persist_ms"),
            "open_trade_ms": entry_metrics.get("open_trade_ms"),
            "report_ms": report_ms,
            "cycle_total_ms": cycle_total_ms,
        })

        last_processed_candle_time = signal_cycle.candle_timestamp

        sleep_fn(_cycle_sleep_seconds())


if __name__ == "__main__":
    run_monitor()
