import pandas as pd

import phase3_monitor


def _frame(rows):
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume", "ema10", "ema20", "macd_hist"],
    )


def test_strong_continuation_call_not_rejected():
    df = _frame(
        [
            [99.0, 100.2, 98.8, 100.0, 1100, 99.8, 99.4, 0.03],
            [100.4, 101.8, 100.2, 101.4, 1300, 100.4, 99.9, 0.06],
            [101.9, 103.3, 101.7, 102.9, 1500, 101.1, 100.5, 0.11],
            [103.4, 104.9, 103.2, 104.6, 1700, 102.0, 101.3, 0.17],
        ]
    )

    result = phase3_monitor._evaluate_reject_continuation_weakening(df, direction="CALL")

    assert result["triggered"] is False
    assert result["code"] is None


def test_weak_choppy_continuation_call_is_rejected_with_all_three_reasons():
    df = _frame(
        [
            [100.0, 101.0, 99.6, 100.8, 1400, 101.3, 100.2, 0.18],
            [100.7, 101.3, 100.4, 100.9, 1300, 101.4, 100.5, 0.14],
            [100.8, 101.1, 100.5, 100.85, 1200, 101.45, 100.7, 0.13],
            [100.84, 101.0, 100.6, 100.83, 1100, 101.47, 100.85, 0.12],
        ]
    )

    result = phase3_monitor._evaluate_reject_continuation_weakening(df, direction="CALL")

    assert result["triggered"] is True
    assert result["code"] == "REJECT_CONTINUATION_WEAKENING"
    assert len(result["reasons"]) == 3
    assert all(isinstance(reason, str) and reason for reason in result["reasons"])
