
from __future__ import annotations

import ast
import importlib
import threading
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from engine.brain import Brain


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pending_cockpit_exit_uses_near_market_limit_with_fallback(monkeypatch):
    module = importlib.import_module("phase3_monitor")

    class Memory:
        def __init__(self):
            self.command = {"action": "EXIT_TRADE", "status": "PENDING"}

        def load_setting(self, *_args):
            return dict(self.command)

        def save_setting(self, _name, value, *_args):
            self.command = dict(value)

        def clear_setting(self, *_args):
            self.command = {}

    memory = Memory()
    close_calls = []
    monkeypatch.setattr(module, "get_memory", lambda: memory)
    monkeypatch.setattr(
        module,
        "ENGINE_MODULE",
        type("Engine", (), {
            "current_position": object(),
            "close_trade": staticmethod(lambda *args, **kwargs: close_calls.append((args, kwargs)) or True),
        }),
    )

    assert module._process_manual_exit_command(750.0, 5.25) is True
    assert close_calls == [
        ((750.0, "MANUAL_EXIT_LIMIT", 5.25), {"execution_mode": "limit_near_market", "fallback_to_market": True})
    ]
    assert memory.command["status"] == "COMPLETED"


def test_post_exit_cooling_blocks_one_qualifying_entry(monkeypatch):
    module = importlib.import_module("phase3_monitor")

    class Memory:
        state = {"pending": True}
        cleared = 0

        def load_setting(self, *_args):
            return dict(self.state)

        def clear_setting(self, *_args):
            self.cleared += 1
            self.state = {}

    memory = Memory()
    engine_calls = []
    monkeypatch.setattr(module, "get_memory", lambda: memory)
    monkeypatch.setattr(module, "_entries_are_paused", lambda: False)
    monkeypatch.setattr(module, "original_open_trade", lambda *args: engine_calls.append(args) or True)

    assert module.open_trade("CALL", 500.0, 497.0, 506.0, 1, "test", {}, "") is False
    assert memory.cleared == 1
    assert engine_calls == []
    assert module.LAST_ENTRY_EXECUTION_METRICS["block_reason"] == "Cooling Period"


def test_directional_spy_run_resets_after_a_reversal():
    module = importlib.import_module("phase3_monitor")
    candles = pd.DataFrame({"close": [700.00, 700.30, 700.55, 700.40, 700.75, 701.10]})

    assert module._directional_spy_run(candles) == {
        "direction": "UP", "dollars": 0.7, "call_dollars": 0.7, "put_dollars": 0.0,
    }


def test_session_market_trend_uses_today_open_and_session_vwap():
    module = importlib.import_module("phase3_monitor")
    candles = pd.DataFrame(
        {
            "open": [100.0, 100.1, 100.4],
            "high": [100.2, 100.5, 100.8],
            "low": [99.9, 100.0, 100.3],
            "close": [100.1, 100.4, 100.7],
            "volume": [1000, 1200, 1400],
        },
        index=pd.to_datetime(
            ["2026-07-20T13:30:00Z", "2026-07-20T13:31:00Z", "2026-07-20T13:32:00Z"], utc=True
        ),
    )

    assert module._session_market_trend(candles) == "BULL_TREND"
    candles.loc[candles.index[-1], "close"] = 99.8
    assert module._session_market_trend(candles) == "BEAR_TREND"


def test_continuation_forecast_requires_strong_confirmation_for_initiation():
    module = importlib.import_module("phase3_monitor")
    metrics = {
        "base_score": 5.0,
        "aligned": True,
        "continuation_quality": 5.0,
        "acceleration": 5.0,
        "efficiency": 5.0,
        "expansion": 5.0,
        "confidence": 5.0,
    }

    assert module._continuation_forecast_admission({**metrics, "stage": 1}) == (True, "Forecast: initiation approved")
    assert module._continuation_forecast_admission({**metrics, "stage": 1, "expansion": 3.0}) == (
        False,
        "Forecast: initiation not confirmed (expansion)",
    )
    assert module._continuation_forecast_admission({**metrics, "stage": 5}) == (False, "Forecast: Late Exhaustion")


def test_continuation_forecast_approves_healthy_established_trend():
    module = importlib.import_module("phase3_monitor")
    forecast = {
        "stage": 3,
        "aligned": True,
        "continuation_quality": 3.0,
        "acceleration": 3.0,
        "efficiency": 3.0,
        "expansion": 3.0,
        "confidence": 3.0,
    }

    assert module._continuation_forecast_admission(forecast) == (True, "Forecast: continuation approved")


def test_import_has_no_runtime_initialization(monkeypatch) -> None:
    import execution.equity_stream
    import schwab.auth

    calls: list[str] = []
    monkeypatch.setattr(schwab.auth, "easy_client", lambda **_: calls.append("client"))
    monkeypatch.setattr(execution.equity_stream.SchwabEquityQuoteStream, "start", lambda *_: calls.append("stream"))
    before = {thread.ident for thread in threading.enumerate()}
    module = importlib.import_module("phase3_monitor")
    assert module.client is None
    assert module.ENGINE_MODULE is None
    assert calls == []
    assert {thread.ident for thread in threading.enumerate()} == before


def test_bounded_runner_uses_injected_runtime_and_never_sleeps(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    initialized: list[bool] = []
    sleeps: list[float] = []
    monkeypatch.setattr(module, "get_candles", lambda: pd.DataFrame())
    module.run_monitor(max_cycles=1, runtime_initializer=lambda: initialized.append(True), sleep_fn=sleeps.append)
    assert initialized == [True]
    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_market_cycle_wakes_at_closed_candle_evaluation_second(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    eastern = ZoneInfo("America/New_York")
    monkeypatch.setattr(module, "_is_regular_market_hours_now", lambda: True)
    monkeypatch.setattr(module, "MARKET_POLL_SECONDS", 2.0)
    monkeypatch.setattr(module, "CANDLE_POLL_SECONDS", 1.0)

    assert module._cycle_sleep_seconds(datetime(2026, 7, 20, 10, 15, 0, 800_000, tzinfo=eastern)) == 0.2
    assert module._cycle_sleep_seconds(datetime(2026, 7, 20, 10, 15, 1, 100_000, tzinfo=eastern)) == 1.0


def test_entry_window_closes_at_345_pm_eastern() -> None:
    module = importlib.import_module("phase3_monitor")
    eastern = ZoneInfo("America/New_York")

    assert module._is_entry_window_now(datetime(2026, 7, 20, 15, 44, 59, tzinfo=eastern)) is True
    assert module._is_entry_window_now(datetime(2026, 7, 20, 15, 45, 0, tzinfo=eastern)) is False


def test_open_option_quote_uses_held_contract_direct_quote(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"SPY   260731C00750000": {"quote": {"bidPrice": 2.4, "mark": 2.5}}}

    class Client:
        def get_quote(self, symbol):
            assert symbol == "SPY   260731C00750000"
            return Response()

    monkeypatch.setattr(module, "client", Client())

    assert module.get_open_option_quote("SPY   260731C00750000") == (2.5, 2.4, None)


def test_authoritative_history_fetch_runs_once_after_each_closed_market_minute(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    eastern = ZoneInfo("America/New_York")
    minute = datetime(2026, 7, 20, 10, 15, 0, tzinfo=eastern)
    monkeypatch.setattr(module, "_is_regular_market_hours_now", lambda: True)
    monkeypatch.setattr(module, "_LAST_HISTORY_FETCH_MINUTE", None)

    assert module._history_fetch_due(minute.replace(second=0)) is False
    assert module._history_fetch_due(minute.replace(second=1)) is True

    module._LAST_HISTORY_FETCH_MINUTE = minute
    assert module._history_fetch_due(minute.replace(second=30)) is False
    assert module._history_fetch_due(minute.replace(minute=16, second=1)) is True


def test_regular_session_history_starts_at_market_open() -> None:
    module = importlib.import_module("phase3_monitor")
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 7, 20, 13, 45, 12, tzinfo=eastern)

    assert module._regular_session_start(now) == datetime(2026, 7, 20, 9, 30, tzinfo=eastern)


def test_schwab_history_datetime_is_naive_without_changing_epoch() -> None:
    module = importlib.import_module("phase3_monitor")
    eastern = ZoneInfo("America/New_York")
    aware = datetime(2026, 7, 20, 9, 30, 1, tzinfo=eastern)

    converted = module._schwab_history_datetime(aware)

    assert converted.tzinfo is None
    assert int(converted.timestamp()) == int(aware.timestamp())


def test_candles_between_minute_fetches_use_closed_cache_without_quote_requests(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    timestamps = pd.date_range("2026-07-20 13:30:00", periods=3, freq="min", tz="UTC")
    cached = pd.DataFrame({"close": [100.0, 101.0, 102.0]}, index=timestamps)
    monkeypatch.setattr(module, "_history_fetch_due", lambda _: False)
    monkeypatch.setattr(module, "_load_cached_candles", lambda: cached.copy())
    monkeypatch.setattr(module, "LAST_NONEMPTY_CANDLES", cached.copy())
    monkeypatch.setattr(module, "_quote_continuity_candles", lambda *_: (_ for _ in ()).throw(AssertionError("quote fetch")))

    result = module.get_candles()

    assert result.equals(cached)
    assert module.LAST_CANDLE_SOURCE == "closed_candle_cache"


def test_extended_market_hours_use_minute_boundary_schedule(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    premarket = datetime(2026, 7, 21, 8, 52, 30, tzinfo=ZoneInfo("America/New_York"))

    assert module._is_extended_market_hours_now(premarket)
    assert module._cycle_sleep_seconds(premarket) == 0.5

    monkeypatch.setattr(module, "_LAST_HISTORY_FETCH_MINUTE", None)
    assert module._history_fetch_due(premarket.replace(second=1))


def test_history_fetch_requests_extended_hours_candles(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candles": [
                    {"datetime": 1784581200000, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1_000},
                ],
            }

    class Client:
        def get_price_history_every_minute(self, symbol, **kwargs):
            calls.append((symbol, kwargs))
            return Response()

    monkeypatch.setattr(module, "client", Client())
    monkeypatch.setattr(module, "_history_fetch_due", lambda _: True)
    monkeypatch.setattr(module, "_load_cached_candles", lambda: pd.DataFrame())
    monkeypatch.setattr(module, "_persist_cached_candles", lambda _: None)
    monkeypatch.setattr(module, "_is_regular_market_hours_now", lambda: False)
    monkeypatch.setattr(module, "LAST_NONEMPTY_CANDLES", None)

    result = module.get_candles()

    assert not result.empty
    assert calls[0][0] == module.SYMBOL
    assert calls[0][1]["need_extended_hours_data"] is True
    assert calls[0][1]["need_previous_close"] is True


def test_shared_closed_candle_score_does_not_emit_volume_log(capsys) -> None:
    module = importlib.import_module("phase3_monitor")
    timestamps = pd.date_range("2026-07-20 13:30:00", periods=6, freq="min", tz="UTC")
    candles = pd.DataFrame(
        {
            "open": [100, 99, 98, 97, 96, 95],
            "high": [101, 100, 99, 98, 97, 96],
            "low": [99, 98, 97, 96, 95, 94],
            "close": [99, 98, 97, 96, 95, 94],
            "volume": [100, 100, 100, 100, 100, 200],
        },
        index=timestamps,
    )

    assert module.score_closed_candle_frame(candles) is not None
    assert capsys.readouterr().out == ""


def test_entry_payload_persists_closed_candle_support_resistance() -> None:
    module = importlib.import_module("phase3_monitor")
    from strategy.signals import build_feature_snapshot
    timestamps = pd.date_range("2026-07-20 13:30:00", periods=25, freq="min", tz="UTC")
    candles = pd.DataFrame(
        {
            "open": [100.0 + index * 0.1 for index in range(25)],
            "high": [100.2 + index * 0.1 for index in range(25)],
            "low": [99.8 + index * 0.1 for index in range(25)],
            "close": [100.1 + index * 0.1 for index in range(25)],
            "volume": [1_000 + index * 10 for index in range(25)],
        },
        index=timestamps,
    )
    indicators = module.add_indicators(candles)
    payload = module._build_entry_feature_payload(
        indicators, "CALL", "BULL_TREND", 5, 0, ["test"], []
    )
    snapshot = __import__("json").loads(payload)
    expected = build_feature_snapshot(
        indicators.reset_index().rename(columns={"index": "datetime"}),
        exclude_last_candle=False,
    )

    assert set(snapshot["support_resistance"]) >= {
        "prior_day_high",
        "prior_day_low",
        "premarket_high",
        "premarket_low",
        "nearest_recent_swing_high",
        "nearest_recent_swing_low",
        "nearest_resistance",
        "nearest_support",
        "distance_to_resistance_dollars",
        "distance_to_support_dollars",
        "closed_above_resistance",
        "closed_below_support",
        "psychological_levels",
    }
    assert snapshot["support_resistance"] == expected["support_resistance"]
    assert snapshot["support_resistance"]["psychological_levels"] == {
        "half_dollar_support": 102.5,
        "half_dollar_resistance": 102.5,
        "whole_dollar_support": 102.0,
        "whole_dollar_resistance": 103.0,
    }
    assert snapshot["fibonacci_levels"] == expected["fibonacci_levels"]
    assert snapshot["vwap"]["value"] == float(indicators.iloc[-1]["vwap"])
    assert snapshot["vwap"]["underlying_close"] == float(indicators.iloc[-1]["close"])
    assert "fibonacci_levels" in snapshot
    assert snapshot["momentum_phase"] in {
        "INITIATION",
        "EARLY_CONTINUATION",
        "ESTABLISHED",
        "MATURE",
        "LATE_EXHAUSTION",
    }


def test_entry_snapshot_preserves_support_resistance() -> None:
    from execution.live_engine import _extract_entry_diagnostic_snapshot

    payload = {
        "captured_at": "2026-07-20T10:00:00-04:00",
        "vwap": {"value": 100.25, "underlying_close": 100.5, "position": "ABOVE"},
        "support_resistance": {"nearest_support": 100.0, "nearest_resistance": 101.0},
        "fibonacci_levels": {"retracement_50": 100.5},
    }

    snapshot = __import__("json").loads(_extract_entry_diagnostic_snapshot(__import__("json").dumps(payload)))

    assert snapshot["vwap"] == payload["vwap"]
    assert snapshot["support_resistance"] == payload["support_resistance"]
    assert snapshot["fibonacci_levels"] == payload["fibonacci_levels"]


def test_startup_guard_blocks_one_entry_then_releases_to_engine(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    engine_calls = []
    admissions = []
    monkeypatch.setattr(module, "startup_entry_attempts", 0)
    monkeypatch.setattr(module, "original_open_trade", lambda *args, **kwargs: engine_calls.append((args, kwargs)) or True)
    monkeypatch.setattr(module, "ENGINE_MODULE", SimpleNamespace())
    monkeypatch.setattr(
        module.LIVE_BRAIN,
        "evaluate_startup_entry_admission",
        lambda **facts: admissions.append(facts) or Brain().evaluate_startup_entry_admission(**facts),
    )

    assert module.open_trade("CALL") is False
    assert module.open_trade("CALL") is True
    assert len(engine_calls) == 1
    assert [item["attempted_entries"] for item in admissions] == [0, 1]


def test_candle_history_merge_preserves_cached_context_and_fresh_values() -> None:
    module = importlib.import_module("phase3_monitor")
    timestamps = pd.date_range("2026-07-20 13:30:00", periods=15, freq="min")
    cached = pd.DataFrame({"close": range(100, 115)}, index=timestamps)
    fresh = pd.DataFrame(
        {"close": [999.0, 1000.0]},
        index=[timestamps[-1], timestamps[-1] + pd.Timedelta(minutes=1)],
    )

    merged = module._merge_candle_history(cached, fresh)

    assert len(merged) == 16
    assert float(merged.loc[timestamps[-1].tz_localize("UTC"), "close"]) == 999.0
    assert float(merged.iloc[-1]["close"]) == 1000.0


def test_candle_history_merge_normalizes_mixed_timestamp_timezones() -> None:
    module = importlib.import_module("phase3_monitor")
    utc = ZoneInfo("UTC")
    cached = pd.DataFrame(
        {"close": [100.0]},
        index=[datetime(2026, 7, 20, 13, 30)],
    )
    fresh = pd.DataFrame(
        {"close": [101.0]},
        index=[datetime(2026, 7, 20, 13, 31, tzinfo=utc)],
    )

    merged = module._merge_candle_history(cached, fresh)

    assert len(merged) == 2
    assert str(merged.index.tz) == "UTC"


def test_runner_manages_each_cycle_but_enters_only_on_completed_candle(monkeypatch) -> None:
    module = importlib.import_module("phase3_monitor")
    candle_times = pd.date_range("2026-07-20 14:00:00", periods=15, freq="min")
    candles = pd.DataFrame(
        {
            "open": range(100, 115),
            "high": range(101, 116),
            "low": range(99, 114),
            "close": range(100, 115),
            "volume": range(1_000, 1_015),
            "vwap": range(100, 115),
            "ema10": range(100, 115),
            "ema20": range(99, 114),
            "ema50": range(98, 113),
            "macd_hist": [1.0] * 15,
        },
        index=candle_times,
    )

    completed = candles.iloc[:-1].copy()
    cycle_results = iter(
        [
            SimpleNamespace(candle_timestamp=candles.index[-2], should_evaluate=False, reason="startup"),
            SimpleNamespace(candle_timestamp=candles.index[-2], should_evaluate=False, reason="duplicate candle already evaluated"),
            SimpleNamespace(
                candle_timestamp=candles.index[-1],
                should_evaluate=True,
                reason="closed candle ready",
                last_row=completed.iloc[-1],
                prev_row=completed.iloc[-2],
                completed_df=completed,
            ),
        ]
    )
    managed = []
    entry_calls = []

    monkeypatch.setattr(module, "get_candles", lambda: candles.copy())
    monkeypatch.setattr(module, "add_indicators", lambda frame: frame)
    monkeypatch.setattr(module, "plan_signal_cycle", lambda *_args, **_kwargs: next(cycle_results))
    monkeypatch.setattr(module, "market_regime", lambda *_args: "BULL_TREND")
    monkeypatch.setattr(module, "manage_trade", lambda *args: managed.append(args), raising=False)
    monkeypatch.setattr(module, "maybe_generate_daily_strategy_effectiveness_report", lambda: None)
    monkeypatch.setattr(module, "_append_latency_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_append_decision_audit_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_is_regular_market_hours_now", lambda: True)
    monkeypatch.setattr(module, "LAST_CANDLE_SOURCE", "live_window")
    monkeypatch.setattr(module, "ENGINE_MODULE", SimpleNamespace(current_position=None))
    monkeypatch.setattr(
        module,
        "maybe_enter_trade",
        lambda last, prev, regime, completed_candles: entry_calls.append((last, prev, regime, completed_candles))
        or {"attempted": False, "opened": False},
    )

    module.run_monitor(max_cycles=3, runtime_initializer=lambda: None, sleep_fn=lambda _: None)

    assert len(managed) == 3
    assert len(entry_calls) == 1
    assert entry_calls[0][0].equals(completed.iloc[-1])
    assert entry_calls[0][1].equals(completed.iloc[-2])
    assert entry_calls[0][2] == "BULL_TREND"
    assert entry_calls[0][3].equals(completed)


def test_direct_entrypoint_calls_monitor_runner() -> None:
    tree = ast.parse((REPO_ROOT / "phase3_monitor.py").read_text(encoding="utf-8"))
    guards = [node for node in tree.body if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)]
    assert any(any(isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and getattr(item.value.func, "id", None) == "run_monitor" for item in guard.body) for guard in guards)