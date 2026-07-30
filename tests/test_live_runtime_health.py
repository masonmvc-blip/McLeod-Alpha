from ops import check_live_runtime_health as health


def test_canonical_health_probe_uses_local_cockpit():
    assert health.STATUS_URL == "http://127.0.0.1:5001/api/status"


def test_preflight_skips_candle_freshness_outside_entry_window(monkeypatch):
    monkeypatch.setattr("sys.argv", ["check_live_runtime_health.py", "--preflight"])
    monkeypatch.setattr(
        health,
        "_status",
        lambda: {
            "bot_running_effective": True,
            "heartbeat_ok": True,
            "broker_reconciliation": "SUCCESS",
            "account_verified": True,
            "parity_state": "MATCH",
            "parity_block_start": False,
            "last_error": None,
        },
    )
    monkeypatch.setattr(health, "_is_entry_window", lambda: False)
    monkeypatch.setattr(
        health,
        "_latest_candle_issue",
        lambda: (_ for _ in ()).throw(AssertionError("premarket candle check must be skipped")),
    )
    monkeypatch.setattr(health, "_record", lambda issues: None)

    assert health.main() == 0


def test_normal_admission_blocks_are_not_runtime_failures():
    assert health._actionable_last_error(
        "ENTRY BLOCKED: Forecast: weak continuation quality"
    ) is None
    assert health._actionable_last_error(
        "STARTUP GUARD: blocked open_trade 1/1"
    ) is None
    assert health._actionable_last_error("ENTRY BLOCKED: Cooling Period") is None
    assert health._actionable_last_error(
        "PROTECTIVE STOP SUBMISSION FAILED"
    ) == "PROTECTIVE STOP SUBMISSION FAILED"


def test_main_ignores_normal_admission_last_error(monkeypatch):
    monkeypatch.setattr("sys.argv", ["check_live_runtime_health.py"])
    monkeypatch.setattr(health, "_is_entry_window", lambda: True)
    monkeypatch.setattr(
        health,
        "_status",
        lambda: {
            "bot_running_effective": True,
            "heartbeat_ok": True,
            "broker_reconciliation": "SUCCESS",
            "account_verified": True,
            "parity_state": "MATCH",
            "parity_block_start": False,
            "last_error": "ENTRY BLOCKED: Forecast: weak efficiency",
        },
    )
    monkeypatch.setattr(health, "_latest_candle_issue", lambda: None)
    recorded = []
    monkeypatch.setattr(health, "_record", lambda issues: recorded.append(issues))

    assert health.main() == 0
    assert recorded == [[]]
