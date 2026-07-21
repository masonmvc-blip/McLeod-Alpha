import json

from execution.diagnostic_snapshots import extract_entry_diagnostic_snapshot


def test_entry_diagnostic_snapshot_preserves_today_trade_chart_metrics():
    payload = json.dumps(
        {
            "checklist": {"passed": 5, "total": 5},
            "indicator_count": 5,
            "indicator_total": 5,
            "trend_stage": {"stage": 3},
            "continuation_quality_score": 4.2,
            "momentum_acceleration_score": 3.7,
            "absorption_score": 2.9,
            "confidence_score": 88.0,
        }
    )

    snapshot = json.loads(extract_entry_diagnostic_snapshot(payload))

    assert snapshot["checklist"] == {"passed": 5, "total": 5}
    assert snapshot["indicator_count"] == 5
    assert snapshot["indicator_total"] == 5
    assert snapshot["trend_stage"] == {"stage": 3}
    assert snapshot["continuation_quality_score"] == 4.2
    assert snapshot["momentum_acceleration_score"] == 3.7
    assert snapshot["absorption_score"] == 2.9
    assert snapshot["confidence_score"] == 88.0