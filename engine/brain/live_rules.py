"""Live entry and risk rules owned exclusively by the canonical Brain."""

from execution.contract_limits import MAX_OPEN_CONTRACTS


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


def calculate_entry_quantity(entry_price, stop_price) -> int:
    """Return the permitted live quantity for a valid entry-risk distance."""
    risk_per_share = abs(float(entry_price) - float(stop_price))
    if risk_per_share <= 0:
        return 0
    return MAX_OPEN_CONTRACTS