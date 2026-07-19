from execution.option_selector import select_option_from_chain, find_option_mark, find_option_bid
from execution.equity_stream import SchwabEquityQuoteStream
from execution.signal_logger import log_signal
from reports.daily_strategy_effectiveness import maybe_generate_daily_strategy_effectiveness_report

from execution.position_sizing import calculate_quantity
from strategy.live_candle_builder import LiveMinuteCandleBuilder

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
MARKET_POLL_SECONDS = max(1.0, float(os.getenv("MARKET_POLL_SECONDS", "2")))
OFF_HOURS_POLL_SECONDS = max(MARKET_POLL_SECONDS, float(os.getenv("OFF_HOURS_POLL_SECONDS", "60")))
TOKEN_PATH = "token.json"
EASTERN_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")
CANDLE_CACHE_PATH = Path("data/spy_1min_history.csv")
LAST_NONEMPTY_CANDLES = None
LAST_CANDLE_SOURCE = "empty"
LAST_QUOTE_SOURCE = "none"
LIVE_CANDLE_BUILDER = LiveMinuteCandleBuilder(symbol=SYMBOL, max_candles=5)
SCHWAB_QUOTE_FRESHNESS_SECONDS = int(os.getenv("SCHWAB_QUOTE_FRESHNESS_SECONDS", "180"))
SCHWAB_AUTH_RETRY_SECONDS = max(5, int(os.getenv("SCHWAB_AUTH_RETRY_SECONDS", "20")))
CANDLE_HISTORY_REFRESH_SECONDS = max(30, int(os.getenv("CANDLE_HISTORY_REFRESH_SECONDS", "180")))
_LAST_HISTORY_REFRESH_EPOCH = 0.0
LATENCY_METRICS_ENABLED = str(os.getenv("LATENCY_METRICS_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
LATENCY_METRICS_PATH = Path(os.getenv("LATENCY_METRICS_PATH", "data/reports/latency_cycle_history.jsonl"))
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
        LATENCY_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LATENCY_METRICS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    except Exception as exc:
        print(f"Latency metrics write error: {exc}")


def _append_latency_skip_event(*, reason, cycle_start_ms, candles_fetch_ms=None, indicators_ms=None):
    cycle_total_ms = _elapsed_ms(cycle_start_ms)
    _append_latency_event({
        "ts_utc": datetime.now(UTC_TZ).isoformat(),
        "ts_et": datetime.now(EASTERN_TZ).isoformat(),
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

USE_LIVE_ENGINE = True
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
    ENGINE_MODULE = importlib.import_module("execution.live_engine" if USE_LIVE_ENGINE else "execution.paper_engine")
    original_open_trade = ENGINE_MODULE.open_trade
    manage_trade = ENGINE_MODULE.manage_trade
    in_trade = ENGINE_MODULE.in_trade
    if USE_LIVE_ENGINE:
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
        normalized["datetime"] = pd.to_datetime(normalized["datetime"], errors="coerce")
        normalized = normalized.dropna(subset=["datetime"]).set_index("datetime")

    if normalized.index.name != "datetime":
        normalized.index = pd.to_datetime(normalized.index, errors="coerce")

    normalized = normalized[~normalized.index.isna()]
    normalized = normalized.sort_index()
    return normalized


def _load_cached_candles():
    if not CANDLE_CACHE_PATH.exists():
        return pd.DataFrame()

    try:
        cached = pd.read_csv(CANDLE_CACHE_PATH)
        cached = _normalize_candles_frame(cached)
        return cached.tail(390).copy()
    except Exception as exc:
        print(f"Candle cache read error: {exc}")
        return pd.DataFrame()


def _persist_cached_candles(df):
    try:
        CANDLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        output = df.reset_index().rename(columns={"index": "datetime"}).tail(390)
        output.to_csv(CANDLE_CACHE_PATH, index=False)
    except Exception as exc:
        print(f"Candle cache write error: {exc}")


def _candles_with_datetime_column(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    working = df.copy()
    if "datetime" not in working.columns:
        working = working.reset_index().rename(columns={"index": "datetime"})
    return working


def _is_regular_market_hours_now():
    now_et = datetime.now(EASTERN_TZ)
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def _cycle_sleep_seconds():
    return MARKET_POLL_SECONDS if _is_regular_market_hours_now() else OFF_HOURS_POLL_SECONDS


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
    global LAST_NONEMPTY_CANDLES, LAST_CANDLE_SOURCE, _LAST_HISTORY_REFRESH_EPOCH

    def _fetch_window(start=None, end=None, include_previous_close=False):
        request_kwargs = {
            "need_extended_hours_data": include_previous_close,
        }
        if start is not None:
            request_kwargs["start_datetime"] = start
        if end is not None:
            request_kwargs["end_datetime"] = end
        if include_previous_close:
            request_kwargs["need_previous_close"] = True

        resp = client.get_price_history_every_minute(
            SYMBOL,
            **request_kwargs,
        )
        resp.raise_for_status()

        candles = resp.json().get("candles", [])
        frame = pd.DataFrame(candles)
        if frame.empty:
            return pd.DataFrame()

        frame["datetime"] = pd.to_datetime(frame["datetime"], unit="ms", errors="coerce")
        frame = frame.dropna(subset=["datetime"]).set_index("datetime")
        return frame.sort_index()

    end = datetime.now(EASTERN_TZ)

    # Fast path: when we already have a non-empty candle set, use direct quote
    # continuity between scheduled REST refreshes to avoid repeated heavy
    # historical pulls each loop.
    now_epoch = time.time()
    refresh_due = (now_epoch - float(_LAST_HISTORY_REFRESH_EPOCH or 0.0)) >= float(CANDLE_HISTORY_REFRESH_SECONDS)
    if not refresh_due and LAST_NONEMPTY_CANDLES is not None and not LAST_NONEMPTY_CANDLES.empty:
        quote_continuity = _quote_continuity_candles(LAST_NONEMPTY_CANDLES.tail(390).copy(), "fast_path")
        if not quote_continuity.empty:
            return quote_continuity

    # Primary window for live/extended market activity.
    df = _fetch_window(end - timedelta(hours=4), end)
    if not df.empty:
        LAST_CANDLE_SOURCE = "live_window"
        LAST_NONEMPTY_CANDLES = df.tail(390).copy()
        _LAST_HISTORY_REFRESH_EPOCH = now_epoch
        _persist_cached_candles(LAST_NONEMPTY_CANDLES)
        return LAST_NONEMPTY_CANDLES

    # Fallback window for weekends/holidays/API gaps.
    fallback = _fetch_window(end - timedelta(days=5), end, include_previous_close=True)
    if not fallback.empty:
        _LAST_HISTORY_REFRESH_EPOCH = now_epoch
        quote_continuity = _quote_continuity_candles(fallback.tail(390).copy(), "recent_history")
        if not quote_continuity.empty:
            return quote_continuity
        LAST_CANDLE_SOURCE = "stale_recent_historical_window"
        print("Candle feed stale: using last direct Schwab historical window")
        LAST_NONEMPTY_CANDLES = fallback.tail(390).copy()
        _persist_cached_candles(LAST_NONEMPTY_CANDLES)
        return LAST_NONEMPTY_CANDLES

    session_fallback = _fetch_window(include_previous_close=True)
    if not session_fallback.empty:
        _LAST_HISTORY_REFRESH_EPOCH = now_epoch
        quote_continuity = _quote_continuity_candles(session_fallback.tail(390).copy(), "previous_close")
        if not quote_continuity.empty:
            return quote_continuity
        LAST_CANDLE_SOURCE = "stale_previous_close_session"
        print("Candle feed stale: using last direct Schwab previous-close session")
        LAST_NONEMPTY_CANDLES = session_fallback.tail(390).copy()
        _persist_cached_candles(LAST_NONEMPTY_CANDLES)
        return LAST_NONEMPTY_CANDLES

    if LAST_NONEMPTY_CANDLES is not None and not LAST_NONEMPTY_CANDLES.empty:
        quote_continuity = _quote_continuity_candles(LAST_NONEMPTY_CANDLES.tail(390).copy(), "in_memory")
        if not quote_continuity.empty:
            return quote_continuity
        LAST_CANDLE_SOURCE = "stale_in_memory_cache"
        print("Candle feed stale: using in-memory direct Schwab cache")
        return LAST_NONEMPTY_CANDLES.tail(390).copy()

    disk_cached = _load_cached_candles()
    if not disk_cached.empty:
        quote_continuity = _quote_continuity_candles(disk_cached.tail(390).copy(), "disk_cache")
        if not quote_continuity.empty:
            return quote_continuity
        LAST_CANDLE_SOURCE = "stale_disk_cache"
        print("Candle feed stale: using disk direct Schwab cache")
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


def market_regime(last, prev):
    if last.close > last.vwap and last.ema10 > last.ema20 > last.ema50 and last.ema10 > prev.ema10:
        return "BULL_TREND"

    if last.close < last.vwap and last.ema10 < last.ema20 < last.ema50 and last.ema10 < prev.ema10:
        return "BEAR_TREND"

    return "NO_TRADE"




def volume_momentum(df):
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


def score_call(last, prev):
    score = 0
    reasons = []

    if last.close > last.vwap:
        score += 1
        reasons.append("price_above_vwap")
    if last.ema10 > last.ema20 > last.ema50:
        score += 2
        reasons.append("bull_ema_stack")
    if last.ema10 > prev.ema10:
        score += 1
        reasons.append("ema10_rising")
    if last.macd_hist > prev.macd_hist:
        score += 1
        reasons.append("macd_improving")
    if last.close > prev.high:
        score += 1
        reasons.append("breaks_prev_high")

    return score, reasons


def score_put(last, prev):
    score = 0
    reasons = []

    if last.close < last.vwap:
        score += 1
        reasons.append("price_below_vwap")
    if last.ema10 < last.ema20 < last.ema50:
        score += 2
        reasons.append("bear_ema_stack")
    if last.ema10 < prev.ema10:
        score += 1
        reasons.append("ema10_falling")
    if last.macd_hist < prev.macd_hist:
        score += 1
        reasons.append("macd_weakening")
    if last.close < prev.low:
        score += 1
        reasons.append("breaks_prev_low")

    return score, reasons

def get_option_chain():
    resp = client.get_option_chain(
        symbol="SPY",
        contract_type="ALL",
        strike_count=10,
        strategy="SINGLE",
    )
    resp.raise_for_status()
    return resp.json()

    log_signal(float(last.close), regime, call_score, put_score)

    if regime == "BULL_TREND" and call_score >= 5:
        entry = float(last.close)
        stop = entry - 0.75
        target = entry + 1.50
        quantity = calculate_quantity(entry, stop)

        chain = get_option_chain()
        option = select_option_from_chain(chain, "CALL", entry)
        print(f"Selected option: {option}")

        open_trade(
            direction="CALL",
            price=entry,
            stop=stop,
            target=target,
            quantity=quantity,
            reason="PHASE2_BULL_CALL",
            option=option,
        )

    elif regime == "BEAR_TREND" and put_score >= 5:
        entry = float(last.close)
        stop = entry + 0.75
        target = entry - 1.50
        quantity = calculate_quantity(entry, stop)

        chain = get_option_chain()
        option = select_option_from_chain(chain, "PUT", entry)
        print(f"Selected option: {option}")

        open_trade(
            direction="PUT",
            price=entry,
            stop=stop,
            target=target,
            quantity=quantity,
            reason="PHASE2_BEAR_PUT",
            option=option,
        )



startup_entry_attempts = 0

def open_trade(*args, **kwargs):
    global startup_entry_attempts, LAST_ENTRY_EXECUTION_METRICS

    start_ms = _perf_ms_now()

    if startup_entry_attempts < 5:
        startup_entry_attempts += 1
        print(f"STARTUP GUARD: blocked open_trade {startup_entry_attempts}/5")
        LAST_ENTRY_EXECUTION_METRICS = {
            "attempted": True,
            "opened": False,
            "open_trade_ms": _elapsed_ms(start_ms),
            "block_reason": "startup_guard",
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

def maybe_enter_trade(last, prev, regime):
    cycle_entry_start_ms = _perf_ms_now()

    if in_trade():
        print("Entry skipped: already in trade")
        return {
            "attempted": False,
            "opened": False,
            "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "already_in_trade",
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

    call_score, call_reasons = score_call(last, prev)
    put_score, put_reasons = score_put(last, prev)

    vol = volume_momentum(df)

    if vol["trend"] == "INCREASING":
        if float(last.close) > float(last.open):
            call_score += 1
            call_reasons.append("volume_confirming_bullish_move")
        elif float(last.close) < float(last.open):
            put_score += 1
            put_reasons.append("volume_confirming_bearish_move")

    elif vol["trend"] == "DECREASING":
        if float(last.close) > float(last.open):
            call_score -= 1
            call_reasons.append("volume_weakening_bullish_move")
        elif float(last.close) < float(last.open):
            put_score -= 1
            put_reasons.append("volume_weakening_bearish_move")

    print(f"Volume-adjusted scores: CALL={call_score} | PUT={put_score}")

    print(f"Call score: {call_score} | Put score: {put_score}")
    print(f"Call reasons: {call_reasons}")
    print(f"Put reasons: {put_reasons}")

    log_signal(float(last.close), regime, call_score, put_score)

    if regime == "BULL_TREND" and call_score >= 5:
        entry = float(last.close)
        stop = entry - 0.75
        target = entry + 1.50
        quantity = calculate_quantity(entry, stop)

        chain_start_ms = _perf_ms_now()
        chain = get_option_chain()
        chain_fetch_ms = _elapsed_ms(chain_start_ms)

        select_start_ms = _perf_ms_now()
        option = select_option_from_chain(chain, "CALL", entry)
        option_select_ms = _elapsed_ms(select_start_ms)

        open_start_ms = _perf_ms_now()
        opened = bool(open_trade("CALL", entry, stop, target, quantity, "PHASE2_BULL_CALL", option))
        open_trade_call_ms = _elapsed_ms(open_start_ms)
        return {
            "attempted": True,
            "opened": opened,
            "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "bull_call_signal",
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

    elif regime == "BEAR_TREND" and put_score >= 5:
        entry = float(last.close)
        stop = entry + 0.75
        target = entry - 1.50
        quantity = calculate_quantity(entry, stop)

        chain_start_ms = _perf_ms_now()
        chain = get_option_chain()
        chain_fetch_ms = _elapsed_ms(chain_start_ms)

        select_start_ms = _perf_ms_now()
        option = select_option_from_chain(chain, "PUT", entry)
        option_select_ms = _elapsed_ms(select_start_ms)

        open_start_ms = _perf_ms_now()
        opened = bool(open_trade("PUT", entry, stop, target, quantity, "PHASE2_BEAR_PUT", option))
        open_trade_call_ms = _elapsed_ms(open_start_ms)
        return {
            "attempted": True,
            "opened": opened,
            "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
            "decision_reason": "bear_put_signal",
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

    return {
        "attempted": False,
        "opened": False,
        "entry_eval_ms": _elapsed_ms(cycle_entry_start_ms),
        "decision_reason": "no_entry_signal",
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
    print("McLeod Alpha Phase 3 monitor started.")
    print("Mode: LIVE TRADING" if USE_LIVE_ENGINE else "Mode: PAPER TRADING")
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

        if last_processed_candle_time is None:
            last_processed_candle_time = df.iloc[-1].name
            if LAST_CANDLE_SOURCE == "live_window":
                print(f"Startup last candle time: {last_processed_candle_time}")
            else:
                print(
                    "Historical candle context loaded: "
                    f"source={LAST_CANDLE_SOURCE} latest={last_processed_candle_time}"
                )


        last = df.iloc[-1]
        prev = df.iloc[-2]

        regime = market_regime(last, prev)
        quality = candle_quality(last)
        vol = volume_momentum(df)

        print(f"\n{datetime.now(EASTERN_TZ).strftime('%H:%M:%S')} ET | {SYMBOL} {last.close:.2f} | {regime}")

        option_mark = None
        option_bid = None

        try:
            current_position = getattr(ENGINE_MODULE, "current_position", None)
            if current_position and getattr(current_position, "option_symbol", None):
                chain = get_option_chain()
                option_mark = find_option_mark(chain, current_position.option_symbol)
                option_bid = find_option_bid(chain, current_position.option_symbol)

        except Exception as e:
            print(f"Option mark error: {e}")
        print(f"DEBUG option_mark before manage_trade = {option_mark} | option_bid = {option_bid}")
        manage_start_ms = _perf_ms_now()
        manage_trade(float(last.close), option_mark, option_bid)
        manage_trade_ms = _elapsed_ms(manage_start_ms)
        if last.name <= last_processed_candle_time:
            if LAST_CANDLE_SOURCE == "live_window":
                print("Ignoring duplicate live candle")
            else:
                print(
                    "Waiting for next live candle: "
                    f"latest cached candle is {last.name} from {LAST_CANDLE_SOURCE}"
                )
            _append_latency_skip_event(
                reason="duplicate_or_stale_candle",
                cycle_start_ms=cycle_start_ms,
                candles_fetch_ms=candles_fetch_ms,
                indicators_ms=indicators_ms,
            )
            sleep_fn(_cycle_sleep_seconds())
            continue

        if not _is_regular_market_hours_now() and LAST_CANDLE_SOURCE != "live_window":
            print(
                "Off-hours candle heartbeat active; skipping new entry evaluation until regular market hours"
            )
            last_processed_candle_time = last.name
            _append_latency_skip_event(
                reason="off_hours_skip",
                cycle_start_ms=cycle_start_ms,
                candles_fetch_ms=candles_fetch_ms,
                indicators_ms=indicators_ms,
            )
            sleep_fn(_cycle_sleep_seconds())
            continue

        entry_metrics = maybe_enter_trade(last, prev, regime)

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

        last_processed_candle_time = last.name

        sleep_fn(_cycle_sleep_seconds())


if __name__ == "__main__":
    run_monitor()
