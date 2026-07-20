from __future__ import annotations

import sqlite3

from engine.memory import Memory
from execution import daily_pnl_email


def test_memory_owns_daily_trade_performance_query_and_event(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.sqlite")
    memory.record_trade(
        entry_time="2026-07-20T09:30:00", exit_time="2026-07-20T09:35:00",
        direction="CALL", entry_price=1.0, exit_price=1.5, pnl=5.0,
        option_pnl_dollars=50.0, exit_reason="TARGET", option_symbol="SPY  CALL",
    )
    memory.record_trade(
        entry_time="2026-07-20T10:00:00", exit_time="2026-07-20T10:05:00",
        direction="PUT", entry_price=1.0, exit_price=0.5, pnl=-5.0,
        option_pnl_dollars=-20.0, exit_reason="STOP", option_symbol="SPY  PUT",
    )

    snapshot = memory.load_daily_trade_performance("2026-07-20")
    event = memory.record_daily_performance(snapshot)

    assert snapshot["trades"] == 2
    assert snapshot["wins"] == 1
    assert snapshot["losses"] == 1
    assert snapshot["net_pnl"] == 30.0
    assert event.correlation_id == "daily-performance:2026-07-20"
    with sqlite3.connect(memory.db_path) as connection:
        row = connection.execute(
            "SELECT category, event_type, source, correlation_id FROM memory_events WHERE event_id = ?",
            (event.event_id,),
        ).fetchone()
    assert row == ("performance", "performance_recorded", "daily_pnl_email", "daily-performance:2026-07-20")


def test_daily_pnl_adapter_delegates_state_and_performance_to_memory(monkeypatch, tmp_path):
    calls = []

    class _Memory:
        def load_setting(self, projection_path, default):
            calls.append(("load_setting", projection_path, default))
            return {"last_sent_date": "2026-07-19"}

        def save_setting(self, name, state, projection_path, source):
            calls.append(("save_setting", name, state, projection_path, source))

        def load_daily_trade_performance(self, date_str):
            calls.append(("load_daily_trade_performance", date_str))
            return {"date": date_str, "trades": 0, "wins": 0, "losses": 0, "net_pnl": 0.0, "rows": []}

    monkeypatch.setattr(daily_pnl_email, "STATE_PATH", tmp_path / "daily_pnl_email_state.json")
    monkeypatch.setattr(daily_pnl_email, "get_memory", lambda: _Memory())
    monkeypatch.setattr(daily_pnl_email, "_broker_today_net_pnl", lambda _: None)

    assert daily_pnl_email._load_state()["last_sent_date"] == "2026-07-19"
    daily_pnl_email._save_state({"last_sent_date": "2026-07-20"})
    assert daily_pnl_email._daily_stats("2026-07-20")["net_pnl"] == 0.0
    assert [call[0] for call in calls] == ["load_setting", "save_setting", "load_daily_trade_performance"]


def test_daily_pnl_adapter_has_no_direct_persistence_calls():
    source = daily_pnl_email.Path(daily_pnl_email.__file__).read_text(encoding="utf-8")

    assert "sqlite3.connect" not in source
    assert "STATE_PATH.write_text" not in source
    assert "STATE_PATH.read_text" not in source


def test_daily_pnl_success_records_performance_through_memory(monkeypatch):
    calls = []

    class _Memory:
        def load_setting(self, projection_path, default):
            return {}

        def save_setting(self, name, state, projection_path, source):
            calls.append(("save_setting", name, state))

        def record_daily_performance(self, snapshot):
            calls.append(("record_daily_performance", snapshot))

    snapshot = {"date": "2026-07-20", "trades": 1, "wins": 1, "losses": 0, "net_pnl": 12.5, "rows": []}
    monkeypatch.setattr(daily_pnl_email, "get_memory", lambda: _Memory())
    monkeypatch.setattr(daily_pnl_email, "_enabled", lambda: True)
    monkeypatch.setattr(daily_pnl_email, "_send_time_et", lambda: daily_pnl_email.dt_time.min)
    monkeypatch.setattr(daily_pnl_email, "_recipient", lambda: "operator@example.com")
    monkeypatch.setattr(daily_pnl_email, "_daily_stats", lambda _: dict(snapshot))
    monkeypatch.setattr(daily_pnl_email, "_transport", lambda: "smtp")
    monkeypatch.setattr(daily_pnl_email, "_send_via_smtp", lambda *args: True)

    assert daily_pnl_email.maybe_send_daily_pnl_email() is True
    assert calls[0] == ("record_daily_performance", snapshot)
    assert calls[1][0:2] == ("save_setting", "daily_pnl_email_state")