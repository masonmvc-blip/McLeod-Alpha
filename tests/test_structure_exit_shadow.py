from __future__ import annotations

import pandas as pd

from backtesting.structure_exit_shadow import simulate_structure_exit_shadow


class _LinearOptionPricer:
    def simulate_price_change(self, *, direction, entry_spy_price, current_spy_price, **_kwargs):
        delta = float(current_spy_price) - float(entry_spy_price)
        return 5.0 + (delta if direction == "CALL" else -delta)


def _candles(closes: list[float]) -> pd.DataFrame:
    start = pd.Timestamp("2026-07-21 09:30", tz="America/New_York")
    return pd.DataFrame(
        [
            {
                "timestamp": start + pd.Timedelta(minutes=index),
                "high": close + 0.05,
                "low": close - 0.05,
                "close": close,
            }
            for index, close in enumerate(closes)
        ]
    )


def _simulate(direction: str, closes: list[float], policy_id: str = "SWING_2"):
    return simulate_structure_exit_shadow(
        candles=_candles(closes),
        direction=direction,
        entry_spy_price=100.0,
        entry_option_price=5.0,
        entry_time=pd.Timestamp("2026-07-21 09:30", tz="America/New_York"),
        pricer=_LinearOptionPricer(),
        policy_id=policy_id,
        initial_option_stop=4.8,
    )


def test_call_swing_stop_uses_prior_completed_lows_and_exits_on_close_invalidation():
    result = _simulate("CALL", [100.0, 101.0, 102.0, 100.9])

    assert result.active_structure_stop == 100.95
    assert result.exit_index == 3
    assert result.exit_reason == "SHADOW_SWING_2_STRUCTURE_STOP"
    assert result.realized_r == 4.5


def test_put_swing_stop_mirrors_prior_completed_highs_and_exits_on_close_invalidation():
    result = _simulate("PUT", [100.0, 99.0, 98.0, 99.1])

    assert result.active_structure_stop == 99.05
    assert result.exit_index == 3
    assert result.exit_reason == "SHADOW_SWING_2_STRUCTURE_STOP"
    assert result.realized_r == 4.5


def test_structure_stop_does_not_arm_until_option_is_profitable():
    result = _simulate("CALL", [100.0, 99.8, 99.9, 99.7])

    assert result.active_structure_stop is None
    assert result.exit_reason == "SHADOW_INITIAL_OPTION_STOP"


def test_swing_three_requires_three_prior_completed_candles():
    result = _simulate("CALL", [100.0, 101.0, 102.0, 100.9], policy_id="SWING_3")

    assert result.active_structure_stop == 99.95
    assert result.exit_reason == "SHADOW_WINDOW_END"