import pandas as pd

from strategy.trend_lifecycle_v2 import classify_trend_lifecycle_v2


def _frame(closes, *, bearish=False):
    closes = [float(value) for value in closes]
    series = pd.Series(closes)
    index = pd.date_range("2026-07-28 09:30", periods=len(series), freq="min")
    frame = pd.DataFrame(
        {
            "open": series.shift(1).fillna(series.iloc[0]).to_numpy(),
            "high": (series + 0.10).to_numpy(),
            "low": (series - 0.10).to_numpy(),
            "close": series.to_numpy(),
            "ema10": series.ewm(span=3, adjust=False).mean().to_numpy(),
            "ema20": series.ewm(span=6, adjust=False).mean().to_numpy(),
            "vwap": series.rolling(4, min_periods=1).mean().to_numpy(),
            "macd_hist": series.diff().fillna(0).diff().fillna(0).to_numpy(),
        },
        index=index,
    )
    if bearish:
        pivot = 200.0
        old_high = frame["high"].copy()
        frame["high"] = pivot - frame["low"]
        frame["low"] = pivot - old_high
        for column in ("open", "close", "ema10", "ema20", "vwap"):
            frame[column] = pivot - frame[column]
        frame["macd_hist"] = -frame["macd_hist"]
    return frame


def test_unknown_without_confirmed_direction():
    result = classify_trend_lifecycle_v2(_frame([100] * 10))
    assert result["phase"] == "UNKNOWN"
    assert result["trend_origin_index"] is None


def test_initiation_requires_confirmed_direction_and_tracks_origin():
    result = classify_trend_lifecycle_v2(
        _frame([100, 100, 100.02, 100.08, 100.16, 100.24, 100.33, 100.43, 100.54, 100.66]),
        "CALL",
    )
    assert result["valid"] is True
    assert result["direction"] == "CALL"
    assert result["phase"] == "INITIATION"
    assert result["trend_origin_index"] is not None
    assert result["direction_hint_aligned"] is True


def test_confirmed_pullback_rebreak_creates_new_leg():
    closes = [
        100, 100.05, 100.12, 100.22, 100.34, 100.48, 100.62,
        100.42, 100.30, 100.72, 100.84, 100.96,
    ]
    result = classify_trend_lifecycle_v2(_frame(closes), "CALL")
    assert result["active_leg"] >= 2
    assert result["phase"] in {"EARLY_CONTINUATION", "ESTABLISHED", "MATURE"}


def test_age_alone_does_not_force_exhaustion():
    result = classify_trend_lifecycle_v2(
        _frame([100 + (idx * 0.08) for idx in range(80)]),
        "CALL",
    )
    assert result["phase"] != "LATE_EXHAUSTION"


def test_mirrored_prices_produce_mirrored_direction():
    closes = [100, 100.02, 100.06, 100.12, 100.20, 100.30, 100.42, 100.55, 100.69, 100.84]
    call = classify_trend_lifecycle_v2(_frame(closes), "CALL")
    put = classify_trend_lifecycle_v2(_frame(closes, bearish=True), "PUT")
    assert call["direction"] == "CALL"
    assert put["direction"] == "PUT"
    assert call["phase"] == put["phase"]
    assert call["active_leg"] == put["active_leg"]
