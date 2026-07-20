"""Live entry rules owned exclusively by the canonical Brain."""


def classify_entry_regime(last, previous) -> str:
    """Classify a closed candle for the live SPY entry gate."""
    if (
        last.close > last.vwap
        and last.ema10 > last.ema20 > last.ema50
        and last.ema10 > previous.ema10
    ):
        return "BULL_TREND"

    if (
        last.close < last.vwap
        and last.ema10 < last.ema20 < last.ema50
        and last.ema10 < previous.ema10
    ):
        return "BEAR_TREND"

    return "NO_TRADE"