from __future__ import annotations

from datetime import datetime, timedelta

from engine.portfolio_engine import PortfolioEngine, RESEARCH_NEEDED


def _iso(hours_ago: int = 0) -> str:
    return (datetime.now() - timedelta(hours=hours_ago)).isoformat()


def _build_engine() -> PortfolioEngine:
    engine = PortfolioEngine.__new__(PortfolioEngine)
    engine.equities = [
        {
            "symbol": "AAA",
            "portfolio_weight_percent": 5.0,
            "day_pl_pct": 1.2,
            "liquidity_score": 80,
            "market_value": 5000.0,
        }
    ]
    engine.eipv_blocked = []
    engine.get_portfolio_metrics = lambda: {"total_portfolio_value": 100000.0}
    return engine


def test_canonical_aliases_valuation_score():
    engine = _build_engine()
    holding = {
        "symbol": "AAA",
        "valuation": RESEARCH_NEEDED,
        "valuation_score": 78.5,
        "valuation_score_source": "Calculated",
        "valuation_score_timestamp": _iso(),
        "valuation_score_confidence": 88,
    }

    canonical = engine._build_canonical_research_record(holding, linked_options=["AAA 2027C120"])

    assert canonical["valuation"] == 78.5
    assert canonical["valuation_source"] == "Calculated"
    assert canonical["valuation_confidence"] == 88
    assert canonical["valuation_confidence_label"] == "HIGH"
    assert canonical["canonical_research_record"]["linked_option_symbols"] == ["AAA 2027C120"]


def test_eipv_uses_validated_expected_return_inputs():
    engine = _build_engine()
    now = _iso()
    engine.research_data = {
        "AAA": {
            "business_quality": 84,
            "business_quality_confidence": 85,
            "business_quality_timestamp": now,
            "valuation": 76,
            "valuation_confidence": 82,
            "valuation_timestamp": now,
            "expected_return_assumptions": {
                "explicit_company_assumptions": True,
                "starting_metric": 100.0,
                "source_timestamps": {"growth": now, "margin": now},
            },
            "expected_alpha": 11,
            "expected_alpha_confidence": 84,
            "expected_alpha_confidence_label": "HIGH",
            "expected_alpha_timestamp": now,
            "expected_2yr_cagr": 14,
            "expected_2yr_cagr_confidence": 84,
            "expected_2yr_cagr_confidence_label": "HIGH",
            "expected_2yr_cagr_timestamp": now,
            "expected_10yr_cagr": 9,
            "expected_10yr_cagr_confidence": 84,
            "expected_10yr_cagr_confidence_label": "HIGH",
            "expected_10yr_cagr_timestamp": now,
        }
    }

    rankings = engine.calculate_eipv_rankings(1000.0)

    assert len(rankings) == 1
    row = rankings[0]
    assert row["symbol"] == "AAA"
    assert row["expected_return_pct"] > 0
    assert row["expected_return_confidence_label"] == "HIGH"
    assert "alpha" in row["expected_return_formula"]


def test_eipv_blocks_low_confidence_research_inputs():
    engine = _build_engine()
    now = _iso()
    engine.research_data = {
        "AAA": {
            "business_quality": 84,
            "business_quality_confidence": 85,
            "business_quality_timestamp": now,
            "valuation": 76,
            "valuation_confidence": 82,
            "valuation_timestamp": now,
            "expected_return_assumptions": {
                "explicit_company_assumptions": True,
                "starting_metric": 100.0,
                "source_timestamps": {"growth": now, "margin": now},
            },
            "expected_alpha": 11,
            "expected_alpha_confidence": 45,
            "expected_alpha_confidence_label": "LOW",
            "expected_alpha_timestamp": now,
            "expected_2yr_cagr": 14,
            "expected_2yr_cagr_confidence": 45,
            "expected_2yr_cagr_confidence_label": "LOW",
            "expected_2yr_cagr_timestamp": now,
            "expected_10yr_cagr": 9,
            "expected_10yr_cagr_confidence": 45,
            "expected_10yr_cagr_confidence_label": "LOW",
            "expected_10yr_cagr_timestamp": now,
        }
    }

    rankings = engine.calculate_eipv_rankings(1000.0)

    assert rankings == []
    assert len(engine.eipv_blocked) == 1
    blocked = engine.eipv_blocked[0]
    assert blocked["symbol"] == "AAA"
    assert "expected_alpha" in blocked["low_confidence_fields"]
