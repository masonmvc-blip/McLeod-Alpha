from __future__ import annotations

from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from backtesting.data_loader import TIMEZONE
from backtesting.option_pricer import EstimatedOptionPricer
from backtesting.historical_option_playback import (
    AlpacaHistoricalTradePlayback,
    HybridReplayOptionPricer,
    build_replay_option_pricer,
)
from backtesting.replay_engine import ReplayEngine
from backtesting.replay_trade_management import (
    evaluate_trade_management_step,
    initialize_trade_management_state,
)
from backtesting.replay_validation import ReplayValidation
from backtesting.signal_replay import SignalReplayEngine
from backtesting.trade_replay_inspector import PaperTradeSpec, inspect_trade_from_df
from backtesting.trade_simulator import TradeSimulator


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


def _write_csv(df: pd.DataFrame) -> str:
    with NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        df2 = df.copy()
        df2["timestamp"] = df2["timestamp"].astype(str)
        df2.to_csv(tmp.name, index=False)
        return tmp.name


class _SingleSignalEngine:
    def __init__(self, step_idx: int, direction: str = "CALL"):
        self.step_idx = step_idx
        self.direction = direction

    def replay(self):
        if self.direction == "CALL":
            return [{
                "_step_idx": self.step_idx,
                "call_qualified": True,
                "put_qualified": False,
                "call_score": 5,
                "put_score": 0,
                "call_reasons": ["test"],
                "put_reasons": [],
                "support_resistance": {},
                "macd_data": {},
                "volume_trend": "UNKNOWN",
                "market_regime": "BULLISH",
            }]
        return [{
            "_step_idx": self.step_idx,
            "call_qualified": False,
            "put_qualified": True,
            "call_score": 0,
            "put_score": 5,
            "call_reasons": [],
            "put_reasons": ["test"],
            "support_resistance": {},
            "macd_data": {},
            "volume_trend": "UNKNOWN",
            "market_regime": "BEARISH",
        }]


def test_inspector_and_simulator_match_for_same_trade():
    df = _build_df("2026-07-13 09:30:00", [100.0, 99.0, 99.0, 99.0, 99.0])

    spec = PaperTradeSpec(
        data_path=Path("unused.csv"),
        trade_date="2026-07-13",
        entry_time="09:30:30",
        direction="CALL",
        paper_exit_time="09:34:45",
        paper_pnl=0.0,
        paper_return=0.0,
        paper_exit_reason="OPTION_STOP",
    )
    inspected = inspect_trade_from_df(df_all=df, spec=spec)
    replay_result = inspected["summary"]["replay_result"]

    replay_engine = ReplayEngine(df, include_premarket=True)
    simulator = TradeSimulator(
        replay_engine=replay_engine,
        signal_engine=_SingleSignalEngine(step_idx=0, direction="CALL"),
        option_pricer=EstimatedOptionPricer(),
        max_trades_per_day=20,
        max_hold_minutes=15,
    )
    trades = simulator.run()
    assert len(trades) == 1
    trade = trades[0]

    assert replay_result["replay_exit_reason"] == trade.exit_reason
    assert replay_result["replay_exit_time"] == trade.exit_time.isoformat()
    expected_pnl = round((trade.option_exit_price - trade.option_entry_price) * 100, 4)
    assert replay_result["replay_pnl"] == expected_pnl


def test_validation_and_backtest_paths_identical_settings():
    df = _build_df("2026-07-13 09:30:00", [100.0 + (i * 0.03) for i in range(80)])
    csv_path = _write_csv(df)

    validator = ReplayValidation(csv_path, "2026-07-13")
    via_validation = validator.run_replay(
        call_threshold=4,
        put_threshold=4,
        max_hold_minutes=15,
        max_trades_per_day=20,
        delta=0.45,
        entry_option_price=5.0,
        slippage=0.04,
    )["summary"]

    replay_engine = ReplayEngine(validator.df_day, include_premarket=True)
    signal_engine = SignalReplayEngine(replay_engine, call_threshold=4, put_threshold=4)
    simulator = TradeSimulator(
        replay_engine=replay_engine,
        signal_engine=signal_engine,
        option_pricer=build_replay_option_pricer(
            entry_option_price=5.0,
            delta=0.45,
            slippage=0.04,
            trade_date="2026-07-13",
        ),
        max_trades_per_day=20,
        max_hold_minutes=15,
    )
    simulator.run()
    via_backtest = simulator.get_summary()

    assert via_validation["total_trades"] == via_backtest["total_trades"]
    assert via_validation["winners"] == via_backtest["winners"]
    assert via_validation["losers"] == via_backtest["losers"]
    assert via_validation["net_pnl"] == via_backtest["net_pnl"]
    assert via_validation["by_exit_reason"] == via_backtest["by_exit_reason"]


def test_max_hold_not_converted_to_stop():
    pricer = EstimatedOptionPricer()
    entry_time = datetime(2026, 7, 13, 9, 30, tzinfo=TIMEZONE)
    state = initialize_trade_management_state(
        entry_time=entry_time,
        direction="CALL",
        entry_spy_price=100.0,
        entry_option_price=5.0,
    )

    result = None
    for minute in range(1, 16):
        now = entry_time + timedelta(minutes=minute)
        result = evaluate_trade_management_step(
            state=state,
            pricer=pricer,
            current_spy_price=101.0,
            current_time=now,
            eod_exit_time=dt_time(15, 59),
            max_hold_minutes=15,
        )
    assert result is not None
    assert result.exit_reason == "MAX_HOLD_15_MIN"


def test_end_of_day_exit_occurs_correctly():
    pricer = EstimatedOptionPricer()
    entry_time = datetime(2026, 7, 13, 15, 58, tzinfo=TIMEZONE)
    state = initialize_trade_management_state(
        entry_time=entry_time,
        direction="PUT",
        entry_spy_price=100.0,
        entry_option_price=5.0,
    )

    result = evaluate_trade_management_step(
        state=state,
        pricer=pricer,
        current_spy_price=100.0,
        current_time=datetime(2026, 7, 13, 15, 59, tzinfo=TIMEZONE),
        eod_exit_time=dt_time(15, 59),
        max_hold_minutes=15,
    )
    assert result.exit_reason == "END_OF_DAY_EXIT"


def test_option_price_path_shared_between_inspector_and_manager():
    df = _build_df("2026-07-13 09:30:00", [100.0, 100.1, 100.2, 100.3, 100.4, 100.5])
    spec = PaperTradeSpec(
        data_path=Path("unused.csv"),
        trade_date="2026-07-13",
        entry_time="09:30:30",
        direction="CALL",
        paper_exit_time="09:35:45",
        paper_pnl=0.0,
        paper_return=0.0,
        paper_exit_reason="OPTION_STOP",
    )
    inspected = inspect_trade_from_df(df_all=df, spec=spec)
    replay_df = inspected["replay_df"]

    entry_dt = pd.Timestamp("2026-07-13 09:30:00").tz_localize(TIMEZONE)
    state = initialize_trade_management_state(
        entry_time=entry_dt,
        direction="CALL",
        entry_spy_price=100.0,
        entry_option_price=5.0,
    )
    pricer = EstimatedOptionPricer()

    manual_marks = []
    for _, row in replay_df.iterrows():
        ts = pd.Timestamp(row["timestamp"]).tz_convert(TIMEZONE)
        result = evaluate_trade_management_step(
            state=state,
            pricer=pricer,
            current_spy_price=float(row["spy_close"]),
            current_time=ts,
            eod_exit_time=dt_time(15, 59),
            max_hold_minutes=15,
        )
        manual_marks.append(round(result.option_mark, 6))

    assert manual_marks == replay_df["estimated_option_price_before_slippage"].astype(float).round(6).tolist()


def test_max_hold_preempts_stop_update_order():
    pricer = EstimatedOptionPricer()
    entry_time = datetime(2026, 7, 13, 9, 30, tzinfo=TIMEZONE)
    state = initialize_trade_management_state(
        entry_time=entry_time,
        direction="CALL",
        entry_spy_price=100.0,
        entry_option_price=5.0,
    )

    # Create a state where stop would otherwise update/hit, but max hold must win first.
    state.active_stop = 4.75
    before_peak = state.peak_option_price
    before_stop = state.active_stop

    result = evaluate_trade_management_step(
        state=state,
        pricer=pricer,
        current_spy_price=90.0,
        current_time=entry_time + timedelta(minutes=15),
        eod_exit_time=dt_time(15, 59),
        max_hold_minutes=15,
    )

    assert result.exit_reason == "MAX_HOLD_15_MIN"
    assert state.peak_option_price == before_peak
    assert state.active_stop == before_stop


def test_stop_hit_uses_bid_and_lte_operator():
    pricer = EstimatedOptionPricer()
    entry_time = datetime(2026, 7, 13, 9, 30, tzinfo=TIMEZONE)
    state = initialize_trade_management_state(
        entry_time=entry_time,
        direction="CALL",
        entry_spy_price=100.0,
        entry_option_price=5.0,
    )
    state.active_stop = 5.0

    result = evaluate_trade_management_step(
        state=state,
        pricer=pricer,
        current_spy_price=100.0,
        current_time=entry_time + timedelta(minutes=1),
        eod_exit_time=dt_time(15, 59),
        max_hold_minutes=15,
    )

    assert result.stop_evaluation_price == result.option_bid
    assert "<=" in result.stop_comparison


def test_no_hardcoded_trade_specific_timestamp():
    module_text = Path("backtesting/replay_trade_management.py").read_text(encoding="utf-8")
    assert "2026-07-13" not in module_text
    assert "trade4" not in module_text.lower()


def test_historical_trade_price_precedes_synthetic_when_available():
    entry_time = datetime(2026, 7, 13, 9, 30, tzinfo=TIMEZONE)

    call_trades = pd.DataFrame(
        {
            "timestamp_et": [
                "2026-07-13 09:30:10-04:00",
                "2026-07-13 09:31:10-04:00",
            ],
            "p": [6.25, 7.75],
        }
    )
    playback = AlpacaHistoricalTradePlayback(call_trades=call_trades, put_trades=None)
    hybrid = HybridReplayOptionPricer(
        synthetic_pricer=EstimatedOptionPricer(entry_option_price=5.0, delta=0.45, slippage=0.04),
        historical_playback=playback,
    )

    entry_option = hybrid.get_entry_price(direction="CALL", entry_time=entry_time, entry_spy_price=100.0)
    state = initialize_trade_management_state(
        entry_time=entry_time,
        direction="CALL",
        entry_spy_price=100.0,
        entry_option_price=entry_option,
    )

    result = evaluate_trade_management_step(
        state=state,
        pricer=hybrid,
        current_spy_price=101.0,
        current_time=entry_time + timedelta(minutes=1, seconds=30),
        eod_exit_time=dt_time(15, 59),
        max_hold_minutes=15,
    )

    assert round(result.option_mark, 6) == 7.75
    assert round(result.option_bid, 6) == 7.75
    assert result.price_source == "HISTORICAL_TRADE"


def test_historical_trade_pricer_falls_back_to_synthetic_when_missing():
    entry_time = datetime(2026, 7, 13, 9, 30, tzinfo=TIMEZONE)

    # First available historical trade is after evaluation timestamp, so lookup should fail.
    call_trades = pd.DataFrame(
        {
            "timestamp_et": ["2026-07-13 09:40:10-04:00"],
            "p": [9.99],
        }
    )
    playback = AlpacaHistoricalTradePlayback(call_trades=call_trades, put_trades=None)
    synthetic = EstimatedOptionPricer(entry_option_price=5.0, delta=0.45, slippage=0.04)
    hybrid = HybridReplayOptionPricer(
        synthetic_pricer=synthetic,
        historical_playback=playback,
    )

    state = initialize_trade_management_state(
        entry_time=entry_time,
        direction="CALL",
        entry_spy_price=100.0,
        entry_option_price=5.0,
    )

    now = entry_time + timedelta(minutes=1)
    result = evaluate_trade_management_step(
        state=state,
        pricer=hybrid,
        current_spy_price=101.0,
        current_time=now,
        eod_exit_time=dt_time(15, 59),
        max_hold_minutes=15,
    )

    expected_mark = synthetic.simulate_price_change(
        direction="CALL",
        entry_spy_price=100.0,
        current_spy_price=101.0,
        entry_time=entry_time,
        current_time=now,
        position="mid",
    )
    assert round(result.option_mark, 6) == round(expected_mark, 6)
    assert result.price_source == "ESTIMATED_FALLBACK"
