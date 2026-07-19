from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from strategy.monitor_cycle import _to_eastern, compute_completed_candles, normalize_timestamp, plan_signal_cycle


ET = ZoneInfo("America/New_York")


def _make_df(candle_times):
    rows = []
    for idx, ts in enumerate(candle_times):
        rows.append(
            {
                "datetime": ts.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
                "open": 100.0 + idx,
                "high": 100.5 + idx,
                "low": 99.5 + idx,
                "close": 100.25 + idx,
                "volume": 1000 + idx,
                "ema20": 100.0 + idx,
                "ema50": 99.0 + idx,
                "vwap": 99.5 + idx,
            }
        )
    return pd.DataFrame(rows)


def test_evaluation_occurs_at_01():
    now_et = datetime(2026, 7, 15, 10, 16, 1, tzinfo=ET)
    df = _make_df(
        [
            datetime(2026, 7, 15, 10, 14, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 16, 0, tzinfo=ET),
        ]
    )

    decision = plan_signal_cycle(df, now_et)

    assert decision.attempted is True
    assert decision.should_evaluate is True
    assert decision.status == "EVALUATED"
    assert decision.candle_timestamp == datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET)


def test_naive_source_timestamps_are_localized_correctly():
    naive_utc = datetime(2026, 7, 15, 15, 35, 0)

    normalized = normalize_timestamp(naive_utc)
    eastern = _to_eastern(naive_utc)

    assert normalized.tzinfo == ZoneInfo("UTC")
    assert eastern == datetime(2026, 7, 15, 11, 35, 0, tzinfo=ET)


def test_aware_utc_timestamps_convert_correctly_to_et():
    aware_utc = datetime(2026, 7, 15, 15, 35, 0, tzinfo=ZoneInfo("UTC"))

    eastern = _to_eastern(aware_utc)

    assert eastern == datetime(2026, 7, 15, 11, 35, 0, tzinfo=ET)


def test_1135_candle_is_accepted_at_113601_et():
    now_et = datetime(2026, 7, 15, 11, 36, 1, tzinfo=ET)
    df = _make_df(
        [
            datetime(2026, 7, 15, 11, 34, 0, tzinfo=ET),
            datetime(2026, 7, 15, 11, 35, 0, tzinfo=ET),
            datetime(2026, 7, 15, 11, 36, 0, tzinfo=ET),
        ]
    )

    decision = plan_signal_cycle(df, now_et)

    assert decision.status == "EVALUATED"
    assert decision.candle_timestamp == datetime(2026, 7, 15, 11, 35, 0, tzinfo=ET)


def test_valid_closed_candle_does_not_produce_closed_candle_unavailable():
    now_et = datetime(2026, 7, 15, 11, 36, 1, tzinfo=ET)
    df = _make_df(
        [
            datetime(2026, 7, 15, 11, 34, 0, tzinfo=ET),
            datetime(2026, 7, 15, 11, 35, 0, tzinfo=ET),
            datetime(2026, 7, 15, 11, 36, 0, tzinfo=ET),
        ]
    )

    decision = plan_signal_cycle(df, now_et)

    assert decision.reason != "closed candle unavailable"
    assert decision.should_evaluate is True


def test_evaluation_still_occurs_if_first_poll_is_after_01():
    now_et = datetime(2026, 7, 15, 10, 16, 2, tzinfo=ET)
    df = _make_df(
        [
            datetime(2026, 7, 15, 10, 14, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 16, 0, tzinfo=ET),
        ]
    )

    decision = plan_signal_cycle(df, now_et)

    assert decision.attempted is True
    assert decision.should_evaluate is True
    assert decision.candle_timestamp == datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET)


def test_forming_candle_is_excluded():
    df = _make_df(
        [
            datetime(2026, 7, 15, 10, 14, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 16, 0, tzinfo=ET),
        ]
    )

    completed_df = compute_completed_candles(df, now_et=datetime(2026, 7, 15, 10, 16, 1, tzinfo=ET))

    assert len(completed_df) == 2
    assert completed_df.iloc[-1]["datetime"] == df.iloc[-2]["datetime"]


def test_closed_last_candle_is_not_dropped_when_feed_has_no_forming_bar():
    df = _make_df(
        [
            datetime(2026, 7, 15, 10, 13, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 14, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET),
        ]
    )

    completed_df = compute_completed_candles(df, now_et=datetime(2026, 7, 15, 10, 16, 1, tzinfo=ET))

    assert len(completed_df) == 3
    assert completed_df.iloc[-1]["datetime"] == df.iloc[-1]["datetime"]


def test_one_candle_cannot_trigger_multiple_entries():
    now_et = datetime(2026, 7, 15, 10, 16, 1, tzinfo=ET)
    candle_ts = datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET)
    df = _make_df(
        [
            datetime(2026, 7, 15, 10, 14, 0, tzinfo=ET),
            candle_ts,
            datetime(2026, 7, 15, 10, 16, 0, tzinfo=ET),
        ]
    )

    decision = plan_signal_cycle(df, now_et, last_evaluated_candle_time=candle_ts)

    assert decision.attempted is True
    assert decision.should_evaluate is False
    assert decision.status == "SKIPPED"
    assert decision.reason == "duplicate candle already evaluated"


def test_missing_candle_data_causes_skipped_cycle():
    now_et = datetime(2026, 7, 15, 10, 16, 1, tzinfo=ET)
    df = _make_df(
        [
            datetime(2026, 7, 15, 10, 13, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 14, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 16, 0, tzinfo=ET),
        ]
    )

    decision = plan_signal_cycle(df, now_et)

    assert decision.attempted is True
    assert decision.should_evaluate is False
    assert decision.status == "SKIPPED"
    assert decision.reason == "closed candle unavailable"


def test_position_management_remains_active_between_entry_evaluations():
    now_et = datetime(2026, 7, 15, 10, 16, 30, tzinfo=ET)
    df = _make_df(
        [
            datetime(2026, 7, 15, 10, 14, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 15, 0, tzinfo=ET),
            datetime(2026, 7, 15, 10, 16, 0, tzinfo=ET),
        ]
    )

    decision = plan_signal_cycle(
        df,
        now_et,
        last_cycle_minute=datetime(2026, 7, 15, 10, 16, 0, tzinfo=ET),
    )

    assert decision.should_manage_position is True
    assert decision.should_evaluate is False
    assert decision.status == "WAITING"