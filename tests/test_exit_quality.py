from datetime import datetime
from types import SimpleNamespace

from engine.memory.service import Memory
from execution.daily_trade_log_email import _exit_quality_summary
from execution.exit_quality import executable_option_price, exit_quality_metrics, update_option_extrema


def test_extrema_use_bid_before_last_or_mark():
    assert executable_option_price(bid=4.80, last=4.95, mark=5.00) == (4.80, "bid")
    assert executable_option_price(last=4.95, mark=5.00) == (4.95, "last")
    assert executable_option_price(mark=5.00) == (5.00, "mark")


def test_extrema_capture_timestamps_and_underlying_prices():
    position = SimpleNamespace(option_high_since_entry=5.0, option_low_since_entry=5.0)
    high_at = datetime(2026, 7, 21, 10, 4, 0)
    low_at = datetime(2026, 7, 21, 10, 6, 0)

    assert update_option_extrema(position, spy_price=750.25, bid=5.75, observed_at=high_at)
    assert update_option_extrema(position, spy_price=749.80, bid=4.60, observed_at=low_at)

    assert position.option_high_since_entry == 5.75
    assert position.option_high_timestamp == high_at.isoformat()
    assert position.spy_price_at_option_high == 750.25
    assert position.option_low_since_entry == 4.60
    assert position.option_low_timestamp == low_at.isoformat()
    assert position.spy_price_at_option_low == 749.80


def test_exit_quality_metrics_include_peak_capture_and_time_fields():
    metrics = exit_quality_metrics(
        option_entry=5.0,
        option_exit=5.5,
        option_high=6.0,
        option_low=4.5,
        quantity=2,
        entry_time="2026-07-21T10:00:00-04:00",
        exit_time="2026-07-21T10:10:00-04:00",
        high_timestamp="2026-07-21T10:05:00-04:00",
    )

    assert metrics == {
        "mfe_pct": 20.0,
        "mae_pct": -10.0,
        "exit_efficiency_pct": 66.6667,
        "peak_capture_pct": 50.0,
        "profit_left_on_table_dollars": 100.0,
        "minutes_to_peak": 5.0,
        "minutes_after_peak_until_exit": 5.0,
    }


def test_memory_persists_exit_quality_fields_for_exports(tmp_path):
    memory = Memory(db_path=tmp_path / "mcleod_alpha.db")
    memory.record_trade(
        entry_time="2026-07-21T10:00:00-04:00",
        exit_time="2026-07-21T10:10:00-04:00",
        direction="CALL",
        entry_price=750.0,
        exit_price=751.0,
        pnl=100.0,
        exit_reason="TARGET_HIT",
        option_symbol="SPY  260721C00750000",
        option_entry=5.0,
        option_exit=5.5,
        option_quantity=2,
        option_high_since_entry=6.0,
        option_low_since_entry=4.5,
        option_high_timestamp="2026-07-21T10:05:00-04:00",
        option_low_timestamp="2026-07-21T10:02:00-04:00",
        spy_price_at_option_high=751.0,
        spy_price_at_option_low=749.0,
        mfe_pct=20.0,
        mae_pct=-10.0,
        exit_efficiency_pct=66.6667,
        peak_capture_pct=50.0,
        profit_left_on_table_dollars=100.0,
        minutes_to_peak=5.0,
        minutes_after_peak_until_exit=5.0,
        entry_efficiency_pct=None,
        trade_quality_grade=None,
    )

    rows = memory.load_exit_quality_export_inputs("2026-07-21", "2026-07-21")
    assert len(rows) == 1
    assert rows[0]["option_high_since_entry"] == 6.0
    assert rows[0]["exit_efficiency_pct"] == 66.6667
    assert rows[0]["entry_efficiency_pct"] is None
    assert rows[0]["trade_quality_grade"] is None


def test_actionable_exit_quality_summary_flags_capture_extremes():
    rows = [
        {"id": 1, "exit_efficiency_pct": 20.0, "peak_capture_pct": 25.0, "profit_left_on_table_dollars": 50.0},
        {"id": 2, "exit_efficiency_pct": 95.0, "peak_capture_pct": 95.0, "profit_left_on_table_dollars": 5.0},
    ]

    summary = _exit_quality_summary(rows)

    assert summary["average_exit_efficiency_pct"] == 57.5
    assert summary["median_exit_efficiency_pct"] == 57.5
    assert summary["aggregate_profit_left_on_table_dollars"] == 55.0
    assert summary["best_exit"]["trade_id"] == 2
    assert summary["worst_exit"]["trade_id"] == 1
    assert [row["trade_id"] for row in summary["trades_below_30_pct_capture"]] == [1]
    assert [row["trade_id"] for row in summary["trades_above_90_pct_capture"]] == [2]
