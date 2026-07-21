from __future__ import annotations

import pandas as pd

from strategy.market_state import CHOP, EXHAUSTION, FRESH_TREND, classify_market_state


def _frame(*, close_step: float, ema_gap: float, hist_step: float, final_close_offset: float = 0.0, final_volume: float = 2_000.0):
    rows = []
    for index in range(21):
        close = 100.0 + (index * close_step)
        rows.append({
            "open": close - 0.05,
            "high": close + 0.15,
            "low": close - 0.15,
            "close": close,
            "volume": 1_000.0,
            "ema10": close - (ema_gap / 2),
            "ema20": close - ema_gap,
            "ema50": close - (ema_gap * 1.5),
            "vwap": close - 0.20,
            "macd_hist": index * hist_step,
        })
    rows[-1]["close"] += final_close_offset
    rows[-1]["volume"] = final_volume
    return pd.DataFrame(rows)


def test_fresh_trend_requires_aligned_expansion_without_future_candles():
    state = classify_market_state(_frame(close_step=0.20, ema_gap=0.40, hist_step=0.01))
    assert state["state"] == FRESH_TREND
    assert state["trend_direction"] == "BULLISH"
    assert state["metrics"]["candle_count"] == 21


def test_chop_when_emas_are_compressed_and_price_has_low_efficiency():
    frame = _frame(close_step=0.0, ema_gap=0.01, hist_step=0.0)
    frame.loc[::2, "close"] += 0.05
    frame.loc[1::2, "close"] -= 0.05
    state = classify_market_state(frame)
    assert state["state"] == CHOP


def test_exhaustion_requires_extension_and_fading_momentum():
    frame = _frame(close_step=0.20, ema_gap=0.20, hist_step=0.01, final_close_offset=0.60, final_volume=500.0)
    frame.loc[17:, "macd_hist"] = [0.20, 0.18, 0.15, 0.10]
    state = classify_market_state(frame)
    assert state["state"] == EXHAUSTION