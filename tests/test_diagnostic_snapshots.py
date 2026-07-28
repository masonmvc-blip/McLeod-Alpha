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
            "momentum_phase": "ESTABLISHED",
            "support_resistance": {"nearest_support": 100.0, "nearest_resistance": 101.0},
            "fibonacci_levels": {"retracement_50": 100.5},
            "checklist_reason": "all_entry_conditions_met",
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
    assert snapshot["momentum_phase"] == "ESTABLISHED"
    assert snapshot["support_resistance"]["nearest_support"] == 100.0
    assert snapshot["fibonacci_levels"]["retracement_50"] == 100.5
    assert snapshot["checklist_reason"] == "all_entry_conditions_met"