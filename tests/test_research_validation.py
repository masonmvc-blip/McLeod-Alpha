import json

from reports.research_validation import build_research_validation_reports


def test_validation_dashboard_and_pipeline_are_research_only(tmp_path):
    reviews = tmp_path / "daily_opportunity_review_2026-07-21.json"
    events = []
    for index in range(10):
        events.append({
            "entered": False,
            "direction": "CALL",
            "rejection_reason": "CALL score below threshold by 1",
            "market_regime": "BULL_TREND",
            "estimated_option_outcome": {"estimated_option_mfe_pct": 12.0, "estimated_option_mae_pct": -4.0},
            "post_rejection_tracking": {"fixed_horizon_outcomes": {"15": {"estimated_option_return_pct": 6.8}}},
        })
    reviews.write_text(json.dumps({"trade_date": "2026-07-21", "evaluated_setups": events}), encoding="utf-8")

    dashboard_path, pipeline_path, dashboard_html_path, pipeline_html_path = build_research_validation_reports(tmp_path)
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
    cohort = dashboard["cohorts"][0]

    assert dashboard["research_only"] is True
    assert dashboard["promotion_eligible"] is False
    assert cohort["pattern"] == "CALL missed by 1 point"
    assert cohort["current_observations"] == 10
    assert cohort["estimated_expectancy_pct"] == 6.8
    assert cohort["estimated_win_rate_pct"] == 100.0
    assert cohort["similarity_to_executed_trades_pct"] is None
    assert cohort["governance_status"] == "candidate_cohort"
    assert cohort["shadow_trading_status"].startswith("not_started")
    assert pipeline["backlog"][0]["promotion_eligible"] is False
    assert "Validation Dashboard" in dashboard_html_path.read_text(encoding="utf-8")
    assert "Research Pipeline" in pipeline_html_path.read_text(encoding="utf-8")