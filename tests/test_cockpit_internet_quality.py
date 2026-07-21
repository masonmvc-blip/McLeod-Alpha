from datetime import datetime, timedelta, timezone

import cockpit


def test_internet_quality_title_uses_rolling_thirty_minute_average(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    history_path = tmp_path / "internet_quality_history.jsonl"
    samples = [
        {"checked_at": (now - timedelta(minutes=25)).isoformat(), "avg_latency_ms": 100.0},
        {"checked_at": (now - timedelta(minutes=15)).isoformat(), "avg_latency_ms": 120.0},
    ]
    history_path.write_text(
        "".join(f'{cockpit.json.dumps(sample)}\n' for sample in samples), encoding="utf-8"
    )

    monkeypatch.setattr(cockpit, "INTERNET_QUALITY_HISTORY_FILE", history_path)
    monkeypatch.setattr(cockpit, "INTERNET_QUALITY_TARGETS", [("test", "https://example.test")])
    monkeypatch.setattr(
        cockpit,
        "_probe_url_latency",
        lambda *_: {"ok": True, "latency_ms": 900.0, "tls_cert_issue": False},
    )
    monkeypatch.setattr(cockpit, "_INTERNET_QUALITY_CACHE", {"timestamp": 0.0, "payload": None})

    snapshot = cockpit._get_internet_quality_snapshot(force=True)

    assert snapshot["avg_latency_ms"] == 900.0
    assert snapshot["rolling_avg_latency_ms"] == 373.3
    assert snapshot["quality"] == "GOOD"
    assert snapshot["summary"] == "Good (373 ms 30 min avg)"