from execution.option_selector import select_option_from_chain, find_option_mark
from execution.equity_stream import SchwabEquityQuoteStream
from execution.signal_logger import log_signal
from reports.daily_strategy_effectiveness import maybe_generate_daily_strategy_effectiveness_report

from execution.position_sizing import calculate_quantity
from strategy.live_candle_builder import LiveMinuteCandleBuilder

import os
import sys
import time
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

load_dotenv()

SYMBOL = "SPY"
SLEEP_SECONDS = 60
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

client = _build_schwab_client()

EQUITY_STREAM = SchwabEquityQuoteStream(client, SYMBOL)
try:
    EQUITY_STREAM.start()
except Exception as exc:
    print(f"Equity quote stream startup failed: {exc}")

ACCOUNT_MODE = str(os.getenv("ACCOUNT_MODE", "paper")).strip().lower()
if ACCOUNT_MODE != "live":
    raise RuntimeError("LIVE trading only: set ACCOUNT_MODE=live")

USE_LIVE_ENGINE = True
ENGINE_MODULE = importlib.import_module("execution.live_engine" if USE_LIVE_ENGINE else "execution.paper_engine")

open_trade = ENGINE_MODULE.open_trade
manage_trade = ENGINE_MODULE.manage_trade
in_trade = ENGINE_MODULE.in_trade

if USE_LIVE_ENGINE:
    account_number = str(os.getenv("SCHWAB_ACCOUNT_NUMBER", "")).strip()
    account_hash = str(os.getenv("SCHWAB_ACCOUNT_HASH", "")).strip()

    if hasattr(ENGINE_MODULE, "set_schwab_client"):
        ENGINE_MODULE.set_schwab_client(client, account_number, account_hash)

    print(f"Account Verified: {account_number}")
    print(f"Mode: LIVE TRADING")
    print(f"Live engine configured with account {account_number}")

    if hasattr(ENGINE_MODULE, "reconcile_startup"):
        reconciliation_ok = bool(ENGINE_MODULE.reconcile_startup())
        if reconciliation_ok:
            print("Broker reconciliation successful")
        else:
            print("BROKER RECONCILIATION FAILED")


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
    global LAST_NONEMPTY_CANDLES, LAST_CANDLE_SOURCE

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

    # Primary window for live/extended market activity.
    df = _fetch_window(end - timedelta(hours=4), end)
    if not df.empty:
        LAST_CANDLE_SOURCE = "live_window"
        LAST_NONEMPTY_CANDLES = df.tail(390).copy()
        _persist_cached_candles(LAST_NONEMPTY_CANDLES)
        return LAST_NONEMPTY_CANDLES

    # Fallback window for weekends/holidays/API gaps.
    fallback = _fetch_window(end - timedelta(days=5), end, include_previous_close=True)
    if not fallback.empty:
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
original_open_trade = open_trade

def open_trade(*args, **kwargs):
    global startup_entry_attempts

    if startup_entry_attempts < 5:
        startup_entry_attempts += 1
        print(f"STARTUP GUARD: blocked open_trade {startup_entry_attempts}/5")
        return False

    return original_open_trade(*args, **kwargs)

print("McLeod Alpha Phase 3 monitor started.")
print("Mode: LIVE TRADING" if USE_LIVE_ENGINE else "Mode: PAPER TRADING")


def maybe_enter_trade(last, prev, regime):
    if in_trade():
        print("Entry skipped: already in trade")
        return

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
        chain = get_option_chain()
        option = select_option_from_chain(chain, "CALL", entry)

        open_trade("CALL", entry, stop, target, quantity, "PHASE2_BULL_CALL", option)

    elif regime == "BEAR_TREND" and put_score >= 5:
        entry = float(last.close)
        stop = entry + 0.75
        target = entry - 1.50
        quantity = calculate_quantity(entry, stop)
        chain = get_option_chain()
        option = select_option_from_chain(chain, "PUT", entry)

        open_trade("PUT", entry, stop, target, quantity, "PHASE2_BEAR_PUT", option)


last_processed_candle_time = None

while True:
        try:
            df = get_candles()
        except Exception as e:
            print(f"Candle fetch error: {e}")
            time.sleep(SLEEP_SECONDS)
            continue
        latest_candle_time = df.iloc[-1].name if not df.empty else None
        latest_candle_text = latest_candle_time.strftime("%Y-%m-%d %H:%M:%S") if latest_candle_time is not None else "none"
        print(f"Candles received: {len(df)} | source={LAST_CANDLE_SOURCE} | latest={latest_candle_text}")
        if len(df) < 15:
            print("Waiting for enough candle data...")
            time.sleep(SLEEP_SECONDS)
            continue

        df = add_indicators(df)
        ready, reason = _indicators_ready(df)
        if not ready:
            print(f"Indicator guard: {reason}; skipping cycle")
            time.sleep(SLEEP_SECONDS)
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

        try:
            current_position = getattr(ENGINE_MODULE, "current_position", None)
            if current_position and getattr(current_position, "option_symbol", None):
                chain = get_option_chain()
                option_mark = find_option_mark(chain, current_position.option_symbol)

        except Exception as e:
            print(f"Option mark error: {e}")
        print(f"DEBUG option_mark before manage_trade = {option_mark}")
        manage_trade(float(last.close), option_mark)
        if last.name <= last_processed_candle_time:
            if LAST_CANDLE_SOURCE == "live_window":
                print("Ignoring duplicate live candle")
            else:
                print(
                    "Waiting for next live candle: "
                    f"latest cached candle is {last.name} from {LAST_CANDLE_SOURCE}"
                )
            time.sleep(SLEEP_SECONDS)
            continue

        if not _is_regular_market_hours_now() and LAST_CANDLE_SOURCE != "live_window":
            print(
                "Off-hours candle heartbeat active; skipping new entry evaluation until regular market hours"
            )
            last_processed_candle_time = last.name
            time.sleep(SLEEP_SECONDS)
            continue

        maybe_enter_trade(last, prev, regime)
        maybe_enter_trade(last, prev, regime)
        maybe_generate_daily_strategy_effectiveness_report()
        last_processed_candle_time = last.name

        time.sleep(SLEEP_SECONDS)
