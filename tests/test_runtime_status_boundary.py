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


def test_period_pnl_uses_paired_schwab_closed_trades():
    source_text = inspect.getsource(runtime_status._build_runtime_status)

    assert "_broker_transaction_trades_for_period(" in source_text
    assert "schwab_paired_closed_spy_options" in source_text
    assert "_broker_total_since(today_date)" in source_text
    assert "schwab_transactions_net" not in source_text


def test_local_period_pnl_includes_commissions_and_closing_regulatory_fee():
    import cockpit

    source_text = inspect.getsource(cockpit._realized_spy_option_pnl_for_period)

    assert "OPTION_COMMISSION_PER_CONTRACT_SIDE * 2" in source_text
    assert "OPTION_REGULATORY_FEE_PER_CONTRACT_CLOSE" in source_text


def test_runtime_status_exposes_closed_trade_signature():
    source_text = inspect.getsource(runtime_status._build_runtime_status)

    assert '"closed_trade_signature": _BROKER_PNL_CACHE.get("closed_trade_signature")' in source_text


def test_active_stop_category_is_not_derived_from_current_option_mark():
    source_text = inspect.getsource(runtime_status._build_runtime_status)

    assert "active_stop_category(\n                                option_entry,\n                                current_mark=current_mark," not in source_text


def test_runtime_status_exposes_entry_time_indicator_baselines():
    source_text = inspect.getsource(runtime_status._build_runtime_status)

    assert '"entry_call_indicators": None' in source_text
    assert '"entry_put_indicators": None' in source_text
    assert 'status["entry_call_indicators"] = feature_payload.get("call_score"' in source_text