"""Tests for market-regime entry filter integration across live and replay paths."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from backtesting.option_pricer import EstimatedOptionPricer
from backtesting.replay_engine import ReplayEngine
from backtesting.signal_replay import SignalReplayEngine
from backtesting.trade_simulator import SimulatedTrade, TradeSimulator
from strategy.signals import (
    add_indicators,
    classify_market_regime,
    is_regime_aligned,
    market_regime,
)


def _row(close, vwap, ema20, ema50):
    return pd.Series({
        "close": float(close),
        "vwap": float(vwap),
        "ema20": float(ema20),
        "ema50": float(ema50),
    })


def test_1_bullish_classification():
    last = _row(close=101, vwap=100, ema20=110, ema50=105)
    prev = _row(close=100, vwap=100, ema20=109, ema50=104)

    snapshot = classify_market_regime(last, prev)

    assert snapshot["market_regime"] == "BULLISH"
    assert snapshot["price_above_vwap"] is True
    assert snapshot["ema20_above_ema50"] is True
    assert snapshot["ema50_rising"] is True


def test_2_bearish_classification():
    last = _row(close=99, vwap=100, ema20=90, ema50=95)
    prev = _row(close=100, vwap=100, ema20=91, ema50=96)

    snapshot = classify_market_regime(last, prev)

    assert snapshot["market_regime"] == "BEARISH"
    assert snapshot["price_above_vwap"] is False
    assert snapshot["ema20_above_ema50"] is False
    assert snapshot["ema50_rising"] is False


def test_3_mixed_is_neutral():
    last = _row(close=101, vwap=100, ema20=90, ema50=95)
    prev = _row(close=100, vwap=100, ema20=91, ema50=94)

    snapshot = classify_market_regime(last, prev)

    assert snapshot["market_regime"] == "NEUTRAL"


def test_3b_bearish_when_only_slightly_above_vwap():
    last = _row(close=100.20, vwap=100.00, ema20=90, ema50=95)
    prev = _row(close=100.30, vwap=100.00, ema20=91, ema50=96)

    snapshot = classify_market_regime(last, prev)

    assert snapshot["price_above_vwap"] is True
    assert snapshot["ema20_above_ema50"] is False
    assert snapshot["ema50_rising"] is False
    assert snapshot["market_regime"] == "BEARISH"


def test_3c_still_neutral_when_meaningfully_above_vwap():
    last = _row(close=101.00, vwap=100.00, ema20=90, ema50=95)
    prev = _row(close=101.10, vwap=100.00, ema20=91, ema50=96)

    snapshot = classify_market_regime(last, prev)

    assert snapshot["price_above_vwap"] is True
    assert snapshot["ema20_above_ema50"] is False
    assert snapshot["ema50_rising"] is False
    assert snapshot["market_regime"] == "NEUTRAL"


def test_4_call_allowed_only_in_bullish():
    assert is_regime_aligned("CALL", "BULLISH") is True


def test_5_call_blocked_in_bearish_and_neutral():
    assert is_regime_aligned("CALL", "BEARISH") is False
    assert is_regime_aligned("CALL", "NEUTRAL") is False


def test_6_put_allowed_only_in_bearish():
    assert is_regime_aligned("PUT", "BEARISH") is True


def test_7_put_blocked_in_bullish_and_neutral():
    assert is_regime_aligned("PUT", "BULLISH") is False
    assert is_regime_aligned("PUT", "NEUTRAL") is False


def test_8_existing_position_still_managed_after_regime_change():
    simulator = TradeSimulator(
        replay_engine=None,
        signal_engine=None,
        option_pricer=EstimatedOptionPricer(),
    )

    entry_time = datetime(2026, 7, 13, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    simulator.open_trade = SimulatedTrade(
        entry_time=entry_time,
        direction="CALL",
        spy_entry_price=100.0,
        option_entry_price=5.0,
        entry_score=5,
        entry_reasons=["test"],
        feature_snapshot={},
        market_regime="BULLISH",
        entry_candle_idx=0,
        delta=simulator.option_pricer.delta,
    )

    # A later candle can be considered a regime change context, but management must continue.
    candle_row = pd.Series({"close": 100.5})
    simulator._update_open_trade(step=1, candle_row=candle_row, current_time=entry_time + timedelta(minutes=1))

    assert simulator.open_trade is not None


def test_9_live_and_replay_classifications_match_identical_data():
    rows = []
    base = datetime(2026, 7, 13, 13, 30, tzinfo=ZoneInfo("UTC"))
    for i in range(40):
        close = 100 + i * 0.08
        rows.append(
            {
                "timestamp": base + timedelta(minutes=i),
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 5000 + i * 10,
            }
        )

    df = pd.DataFrame(rows)
    replay = ReplayEngine(df, include_premarket=True)
    signals = SignalReplayEngine(replay, call_threshold=5, put_threshold=5).replay()

    df_ind = add_indicators(df)
    manual_regime_by_ts = {}
    for i in range(1, len(df_ind)):
        last = df_ind.iloc[i]
        prev = df_ind.iloc[i - 1]
        manual_regime_by_ts[last["timestamp"]] = market_regime(last, prev)

    for signal in signals:
        assert signal["market_regime"] == manual_regime_by_ts[signal["timestamp"]]


def test_10_production_exit_and_risk_paths_unchanged_structurally():
    phase3_path = Path(__file__).resolve().parent.parent / "phase3_monitor.py"
    text = phase3_path.read_text(encoding="utf-8")

    # Exit/management paths still present.
    assert "equity_stream = SchwabEquityQuoteStream(client, SYMBOL)" in text
    assert "equity_stream.get_latest_quote_payload()" in text
    assert "live_quote_payload = get_spy_live_quote()" in text
    assert "live_candle_builder = LiveMinuteCandleBuilder(symbol=SYMBOL, max_candles=3)" in text
    assert "builder_snapshot = live_candle_builder.update_from_quote_payload(live_quote_payload)" in text
    assert "if equity_stream is not None:\n            equity_stream.stop()" in text
    assert "option_quote_cache = ActiveOptionQuoteCache(fetch_func=get_option_quote, ttl_seconds=1.0)" in text
    assert "snapshot = option_quote_cache.get(current_option_symbol, now=now_et)" in text
    assert "manage_trade(float(live_price), option_mark, option_bid)" in text
    assert "if not should_attempt_evaluation(now_et, last_signal_cycle_minute):" in text
    assert "df = add_indicators(live_candle_builder.merge_with_history(candle_cache.raw_df))" in text
    assert text.count("maybe_enter_trade(last, prev, regime_snapshot, completed_df") == 1

    # Existing entry risk settings preserved.
    assert "ENTRY_SCORE_THRESHOLD = 5" in text
    assert "if call_score >= ENTRY_SCORE_THRESHOLD" in text
    assert "if put_score >= ENTRY_SCORE_THRESHOLD" in text
    assert "stop = entry - 0.75" in text
    assert "target = entry + 1.50" in text
    assert "stop = entry + 0.75" in text
    assert "target = entry - 1.50" in text

    # Existing sizing and option selection/order submission hooks preserved.
    assert "quantity = calculate_quantity(entry, stop)" in text
    assert "select_option_from_chain(chain, \"CALL\", entry)" in text
    assert "select_option_from_chain(chain, \"PUT\", entry)" in text
    assert "open_trade(\"CALL\"" in text
    assert "open_trade(\"PUT\"" in text
