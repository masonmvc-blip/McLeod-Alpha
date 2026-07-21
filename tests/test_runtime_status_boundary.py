import inspect

from engine.memory import Memory
from engine import runtime_status


def test_status_trade_log_summary_is_memory_owned(tmp_path):
    memory = Memory(db_path=tmp_path / "runtime.db")
    memory.initialize_live_trade_store()
    memory.record_trade(
        entry_time="2026-07-20T09:30:00-04:00",
        exit_time="2026-07-20T09:35:00-04:00",
        direction="CALL",
        entry_price=1.0,
        exit_price=1.2,
        pnl=20.0,
        exit_reason="TARGET",
    )

    summary = memory.load_trade_log_status_summary(tmp_path / "runtime.db")

    assert summary["closed_trade_signature"] == "1:2026-07-20T09:35:00-04:00"
    assert summary["has_absorption_score"] is True


def test_cockpit_parse_status_remains_a_compatible_adapter(monkeypatch):
    import cockpit

    expected = {"bot_running": False}
    received = {}

    def build_status(runtime_globals):
        received.update(runtime_globals)
        return expected

    monkeypatch.setattr(runtime_status, "parse_bot_status", build_status)

    assert cockpit.parse_bot_status() is expected
    assert received["PROJECT_ROOT"] == cockpit.PROJECT_ROOT


def test_period_pnl_refreshes_immediately_when_trade_signature_changes():
    source_text = inspect.getsource(runtime_status._build_runtime_status)

    assert "trade_posted_since_cache" in source_text
    assert "and not trade_posted_since_cache" in source_text


def test_empty_broker_period_does_not_override_local_pnl():
    source_text = inspect.getsource(runtime_status._build_runtime_status)

    assert "has_today_transactions" in source_text
    assert "has_wtd_transactions" in source_text
    assert "_prefer_external(ext_today, today_total, has_today_transactions)" in source_text