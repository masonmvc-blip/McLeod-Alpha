from __future__ import annotations

import json

from reports.trend_quality_report import build_trend_quality_report


def _event(*, entered: bool, mfe: float, mae: float) -> dict:
    return {
        "entered": entered,
        "adx_14": 27.0,
        "candle_relative_volume_20": 1.4,
        "shadow_market_state": {
            "state": "FRESH_TREND",
            "metrics": {
                "directional_efficiency_10": 0.7,
                "relative_volume_20": 1.4,
                "ema10_ema20_separation_in_avg_range": 0.8,
                "extension_from_ema10_in_avg_range": 0.4,
            },
        },
        "cq": {
            "trend_lifecycle": {"trend_age_candles": 2},
            "components": {"pullback_depth": {"depth_candles": 1}},
        },
        "estimated_option_outcome": {
            "estimated_option_mfe_pct": mfe,
            "estimated_option_mae_pct": mae,
        },
    }


def test_trend_quality_report_includes_entered_rejected_features_and_combinations(tmp_path):
    payload = {"evaluated_setups": [_event(entered=True, mfe=4.0, mae=-1.0), _event(entered=False, mfe=2.0, mae=-3.0)]}
    (tmp_path / "daily_opportunity_review_2026-07-21.json").write_text(json.dumps(payload), encoding="utf-8")

    output_path = build_trend_quality_report(tmp_path)
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["research_only"] is True
    assert report["promotion_eligible"] is False
    assert report["observations"] == 2
    assert report["entered"] == 1
    assert report["rejected"] == 1
    assert report["feature_buckets"]["adx_14"][0]["observations"] == 2
    assert report["market_states"][0]["cohort"] == "FRESH_TREND"
    assert report["quality_combinations"][0]["avg_estimated_option_mfe_pct"] == 3.0
    assert report["quality_combinations"][0]["research_status"] == "exploratory_insufficient_sample"
    assert report["market_state_adx_trend_age_interactions"] == []
    assert report["market_state_adx_trend_age_deferred_sparse_combinations"] == 1


def test_state_adx_trend_age_interactions_require_minimum_sample(tmp_path):
    payload = {"evaluated_setups": [_event(entered=index % 2 == 0, mfe=4.0, mae=-1.0) for index in range(10)]}
    (tmp_path / "daily_opportunity_review_2026-07-21.json").write_text(json.dumps(payload), encoding="utf-8")

    report = json.loads(build_trend_quality_report(tmp_path).read_text(encoding="utf-8"))

    interaction = report["market_state_adx_trend_age_interactions"]
    assert len(interaction) == 1
    assert interaction[0]["cohort"] == "FRESH_TREND | ADX <30 | trend_age <3"
    assert interaction[0]["observations"] == 10
    assert interaction[0]["entered"] == 5
    assert interaction[0]["research_status"] == "candidate_for_validation"
    assert report["market_state_adx_trend_age_deferred_sparse_combinations"] == 0