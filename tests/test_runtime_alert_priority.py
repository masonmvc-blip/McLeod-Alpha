import json


def test_lower_severity_alert_cannot_hide_active_critical_alert(tmp_path, monkeypatch):
    from ops import runtime_alerts

    alert_path = tmp_path / "runtime_alert.json"
    monkeypatch.setattr(runtime_alerts, "ALERT_PATH", alert_path)

    runtime_alerts.set_runtime_alert(
        "protective_stop_missing",
        "No broker-verified protection",
        severity="critical",
    )
    runtime_alerts.set_runtime_alert(
        "entry_latency_over_goal",
        "Entry exceeded latency goal",
        severity="warning",
    )

    payload = json.loads(alert_path.read_text(encoding="utf-8"))
    assert payload["event_type"] == "protective_stop_missing"
    assert payload["severity"] == "critical"
    assert payload["active"] is True


def test_same_alert_type_can_refresh_and_lower_severity(tmp_path, monkeypatch):
    from ops import runtime_alerts

    alert_path = tmp_path / "runtime_alert.json"
    monkeypatch.setattr(runtime_alerts, "ALERT_PATH", alert_path)

    runtime_alerts.set_runtime_alert("broker_health", "down", severity="critical")
    runtime_alerts.set_runtime_alert("broker_health", "degraded", severity="warning")

    payload = json.loads(alert_path.read_text(encoding="utf-8"))
    assert payload["event_type"] == "broker_health"
    assert payload["severity"] == "warning"
    assert payload["message"] == "degraded"
