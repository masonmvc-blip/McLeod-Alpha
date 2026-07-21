import json

from reports.daily_research_advisory import build_daily_research_advisory


def test_daily_advisory_preserves_live_governance_and_prioritizes_debt(tmp_path):
    (tmp_path / "validation_dashboard.json").write_text(json.dumps({
        "focus_pattern": "CALL missed by 1 point",
        "cohorts": [{
            "pattern": "CALL missed by 1 point",
            "trading_days_observed": 1,
            "shadow_promotion_blockers": ["observations below 100", "manual review not completed"],
        }],
        "research_debt": [{"dimension": "Volatility Regime", "impact": "high", "status": "not instrumented"}],
    }), encoding="utf-8")
    (tmp_path / "research_pipeline.json").write_text(json.dumps({
        "backlog": [{"pattern": "CALL missed by 1 point"}],
    }), encoding="utf-8")

    json_path, html_path = build_daily_research_advisory("2026-07-21", tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    advice = " ".join(row["advice"] for row in payload["recommendations"])

    assert payload["research_only"] is True
    assert payload["live_policy_change_recommended"] is False
    assert "Maintain current live entry rules" in advice
    assert "Volatility Regime" in advice
    assert "Do not start shadow trading yet" in advice
    assert "Daily Research Advisory" in html_path.read_text(encoding="utf-8")