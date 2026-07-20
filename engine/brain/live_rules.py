"""Live entry and risk rules owned exclusively by the canonical Brain."""

from execution.contract_limits import MAX_OPEN_CONTRACTS


LIVE_ENTRY_MIN_SCORE = 5


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


def build_entry_risk_plan(direction: str, entry_price: float) -> tuple[float, float, int]:
    """Build the canonical live entry stop, target, and permitted quantity."""
    entry = float(entry_price)
    normalized_direction = str(direction or "").upper()
    if normalized_direction == "CALL":
        stop = entry - 0.75
        target = entry + 1.50
    elif normalized_direction == "PUT":
        stop = entry + 0.75
        target = entry - 1.50
    else:
        raise ValueError(f"Unsupported live entry direction: {direction!r}")
    return stop, target, calculate_entry_quantity(entry, stop)


def is_entry_eligible(direction: str, regime: str, score: int | float) -> bool:
    """Return whether a scored live signal satisfies the canonical entry gate."""
    normalized_direction = str(direction or "").upper()
    normalized_regime = str(regime or "").upper()
    try:
        normalized_score = float(score)
    except (TypeError, ValueError):
        return False

    expected_regime = {"CALL": "BULL_TREND", "PUT": "BEAR_TREND"}.get(normalized_direction)
    return expected_regime == normalized_regime and normalized_score >= LIVE_ENTRY_MIN_SCORE