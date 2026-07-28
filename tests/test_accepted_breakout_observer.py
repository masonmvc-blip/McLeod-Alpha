from datetime import datetime

import pandas as pd

from execution.accepted_breakout_observer import observe_candidate


def _candles(rows):
    return pd.DataFrame(rows)


def test_observer_labels_break_then_retest_hold_without_execution_instruction():
    breakout = _candles([
        {"high": 100, "low": 99, "close": 99.5}, {"high": 101, "low": 99, "close": 100},
        {"high": 102, "low": 100, "close": 101}, {"high": 103, "low": 101, "close": 102},
        {"high": 104, "low": 102, "close": 103}, {"high": 106, "low": 104, "close": 105},
    ])
    first = observe_candidate(breakout, "CALL", captured_at=datetime(2026, 7, 27, 10, 0))
    assert first["accepted_breakout_admit"] is False
    assert first["accepted_breakout_reason"] == "breakout_observed_awaiting_retest"

    retest = breakout.copy()
    retest.loc[len(retest)] = {"high": 106, "low": 104, "close": 105.5}
    second = observe_candidate(retest, "CALL", captured_at=datetime(2026, 7, 27, 10, 1))
    assert second["accepted_breakout_admit"] is True
    assert second["accepted_breakout_reason"] == "retest_hold_confirmed"