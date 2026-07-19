from pathlib import Path

import pandas as pd

from backtesting.data_loader import TIMEZONE
from backtesting.trade_replay_inspector import PaperTradeSpec, inspect_trade_from_df


def _build_df(start_ts: str, closes: list[float]) -> pd.DataFrame:
    ts0 = pd.Timestamp(start_ts).tz_localize(TIMEZONE)
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        ts = ts0 + pd.Timedelta(minutes=i)
        o = prev
        h = max(o, c) + 0.05
        l = min(o, c) - 0.05
        rows.append(
            {
                "timestamp": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": 1000 + i,
            }
        )
        prev = c
    return pd.DataFrame(rows)


def _run(df: pd.DataFrame, direction: str, entry: str = "09:30:30", exit_time: str = "09:35:45"):
    spec = PaperTradeSpec(
        data_path=Path("unused.csv"),
        trade_date="2026-07-13",
        entry_time=entry,
        direction=direction,
        paper_exit_time=exit_time,
        paper_pnl=0.0,
        paper_return=0.0,
        paper_exit_reason="OPTION_STOP",
    )
    return inspect_trade_from_df(df_all=df, spec=spec)


def test_favorable_put_path_can_produce_winner():
    # Entry candle closes at 100. Subsequent falling prices should benefit PUT.
    df = _build_df("2026-07-13 09:30:00", [100.0, 99.7, 99.5, 99.2, 99.1, 98.9, 98.8])
    out = _run(df, "PUT")
    replay = out["summary"]["replay_result"]
    assert replay["replay_pnl"] > 0


def test_favorable_call_path_can_produce_winner():
    df = _build_df("2026-07-13 09:30:00", [100.0, 100.3, 100.6, 100.8, 101.0, 101.1, 101.2])
    out = _run(df, "CALL")
    replay = out["summary"]["replay_result"]
    assert replay["replay_pnl"] > 0


def test_trailing_stop_exit_can_be_profitable():
    # Rally to arm trailing, then pull back through trailing stop while still profitable.
    df = _build_df("2026-07-13 09:30:00", [100.0, 100.7, 101.2, 101.4, 101.0, 100.95, 100.9])
    out = _run(df, "CALL", exit_time="09:36:45")
    replay = out["summary"]["replay_result"]
    assert replay["replay_exit_reason"] == "TRAILING_STOP"
    assert replay["replay_pnl"] > 0


def test_initial_stop_exit_is_negative():
    df = _build_df("2026-07-13 09:30:00", [100.0, 99.7, 99.5, 99.3, 99.2, 99.1])
    out = _run(df, "CALL")
    replay = out["summary"]["replay_result"]
    assert replay["replay_exit_reason"] == "INITIAL_STOP"
    assert replay["replay_pnl"] < 0


def test_slippage_not_charged_every_candle():
    df = _build_df("2026-07-13 09:30:00", [100.0, 100.1, 100.2, 100.15, 100.25, 100.3])
    out = _run(df, "CALL")
    replay_df = out["replay_df"]
    assert int((replay_df["entry_slippage"] > 0).sum()) == 0
    assert int((replay_df["exit_slippage"] > 0).sum()) <= 1


def test_time_decay_not_compounded_incorrectly():
    df = _build_df("2026-07-13 09:30:00", [100.0, 100.05, 100.05, 100.05, 100.05, 100.05])
    out = _run(df, "CALL")
    replay_df = out["replay_df"]
    assert out["summary"]["validations"]["5_time_decay_once_per_minute_only"] is True
    # Cumulative decay must be monotonic non-decreasing.
    cd = replay_df["cumulative_time_decay"].astype(float)
    assert bool((cd.diff().fillna(0.0) >= -1e-9).all())


def test_same_inputs_produce_identical_output():
    df = _build_df("2026-07-13 09:30:00", [100.0, 99.8, 99.6, 99.7, 99.5, 99.4, 99.45])
    out1 = _run(df, "PUT", exit_time="09:36:45")
    out2 = _run(df, "PUT", exit_time="09:36:45")

    assert out1["summary"] == out2["summary"]
    assert out1["replay_df"].to_json() == out2["replay_df"].to_json()


def test_non_exit_rows_do_not_lag_final_price():
    df = _build_df("2026-07-13 09:30:00", [100.0, 100.2, 100.1, 100.25, 100.2, 100.3])
    out = _run(df, "CALL", exit_time="09:35:45")
    replay_df = out["replay_df"]

    non_exit = replay_df[replay_df["exit_decision"] == "HOLD"]
    assert not non_exit.empty
    assert bool(
        (
            non_exit["final_estimated_option_price"].astype(float)
            == non_exit["estimated_option_price_before_slippage"].astype(float)
        ).all()
    )
    assert "stop_evaluation_price" in replay_df.columns
    assert "stop_comparison" in replay_df.columns
