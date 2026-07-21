from __future__ import annotations

import json

from reports.state_performance_report import build_state_performance_report


def test_report_groups_shadow_states_and_keeps_actual_pnl_unavailable(tmp_path):
    payload = {
        "evaluated_setups": [
            {
                "research": {"trend_state": "FRESH_TREND", "current_engine_entered": True},
                "adx_14": 12.0,
                "estimated_option_outcome": {"estimated_option_mfe_pct": 5.0, "estimated_option_mae_pct": -1.0},
            },
            {
                "research": {"trend_state": "CHOP", "current_engine_entered": False},
                "adx_14": 27.0,
                "estimated_option_outcome": {"estimated_option_mfe_pct": 1.0, "estimated_option_mae_pct": -4.0},
            },
        ]
    }
    (tmp_path / "daily_opportunity_review_2026-07-21.json").write_text(json.dumps(payload), encoding="utf-8")

    output_path = build_state_performance_report(tmp_path)
    report = json.loads(output_path.read_text(encoding="utf-8"))

    rows = {row["market_state"]: row for row in report["states"]}
    assert rows["FRESH_TREND"]["entered"] == 1
    assert rows["CHOP"]["rejected"] == 1
    assert rows["FRESH_TREND"]["actual_reconciled_pnl"] is None
    adx_buckets = {row["adx_bucket"]: row for row in report["adx_buckets"]}
    assert adx_buckets["<15"]["observations"] == 1
    assert adx_buckets["25-30"]["rejected"] == 1
    assert adx_buckets["<15"]["reconciled_expectancy"] is None
    assert report["promotion_eligible"] is False