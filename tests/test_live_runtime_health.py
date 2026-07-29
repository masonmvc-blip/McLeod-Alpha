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
