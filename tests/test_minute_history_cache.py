from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from strategy.minute_history_cache import RollingMinuteHistoryCache


def _frame(rows):
    return pd.DataFrame(rows)


def _identity_indicators(df):
    out = df.copy()
    out["ema20"] = out["close"]
    return out


def test_refresh_bootstraps_and_populates_latest_close():
    calls = []

    def fetch(start, end):
        calls.append((start, end))
        return _frame(
            [
                {"datetime": datetime(2026, 7, 15, 10, 0), "close": 100.0},
                {"datetime": datetime(2026, 7, 15, 10, 1), "close": 101.0},
            ]
        )

    cache = RollingMinuteHistoryCache(fetch_func=fetch, indicator_func=_identity_indicators)
    df = cache.refresh(now=datetime(2026, 7, 15, 10, 2))

    assert len(calls) == 1
    assert len(df) == 2
    assert cache.latest_close() == 101.0


def test_refresh_merges_overlap_and_keeps_latest_duplicate():
    first = _frame(
        [
            {"datetime": datetime(2026, 7, 15, 10, 0), "close": 100.0},
            {"datetime": datetime(2026, 7, 15, 10, 1), "close": 101.0},
        ]
    )
    second = _frame(
        [
            {"datetime": datetime(2026, 7, 15, 10, 1), "close": 101.5},
            {"datetime": datetime(2026, 7, 15, 10, 2), "close": 102.0},
        ]
    )
    payloads = [first, second]

    def fetch(start, end):
        return payloads.pop(0)

    cache = RollingMinuteHistoryCache(fetch_func=fetch, indicator_func=_identity_indicators)
    cache.refresh(now=datetime(2026, 7, 15, 10, 2))
    df = cache.refresh(now=datetime(2026, 7, 15, 10, 3))

    assert len(df) == 3
    assert float(df.iloc[1]["close"]) == 101.5
    assert cache.latest_close() == 102.0


def test_incremental_refresh_uses_short_overlap_window_after_bootstrap():
    calls = []

    def fetch(start, end):
        calls.append((start, end))
        minute = datetime(2026, 7, 15, 10, 0) + timedelta(minutes=len(calls) - 1)
        return _frame([{"datetime": minute, "close": 100.0 + len(calls)}])

    cache = RollingMinuteHistoryCache(
        fetch_func=fetch,
        indicator_func=_identity_indicators,
        refresh_lookback=timedelta(minutes=15),
    )

    cache.refresh(now=datetime(2026, 7, 15, 10, 20))
    cache.refresh(now=datetime(2026, 7, 15, 10, 21))

    assert len(calls) == 2
    second_start, second_end = calls[1]
    assert second_end == datetime(2026, 7, 15, 10, 21, tzinfo=ZoneInfo("UTC"))
    assert second_start <= datetime(2026, 7, 15, 10, 0, tzinfo=ZoneInfo("UTC"))