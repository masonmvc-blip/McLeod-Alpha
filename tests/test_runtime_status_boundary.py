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