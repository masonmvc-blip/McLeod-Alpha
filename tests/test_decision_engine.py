from __future__ import annotations

from pathlib import Path

from engine.cio import (
    DecisionEngine,
    DecisionEngineInputs,
    MaterialNewsItem,
    PortfolioConstraint,
    PortfolioHolding,
    WatchlistItem,
)


def _sample_inputs() -> DecisionEngineInputs:
    return DecisionEngineInputs(
        date="2026-07-19",
        holdings=(
            PortfolioHolding(
                symbol="AAPL",
                quantity=120,
                market_value=42000,
                sector="Technology",
                thesis_health_score=78,
                valuation_score=72,
                conviction_score=80,
                risk_score=28,
                liquidity_score=94,
            ),
            PortfolioHolding(
                symbol="MSFT",
                quantity=80,
                market_value=36000,
                sector="Technology",
                thesis_health_score=75,
                valuation_score=68,
                conviction_score=76,
                risk_score=30,
                liquidity_score=96,
            ),
            PortfolioHolding(
                symbol="XOM",
                quantity=140,
                market_value=25000,
                sector="Energy",
                thesis_health_score=41,
                valuation_score=44,
                conviction_score=37,
                risk_score=74,
                liquidity_score=70,
            ),
        ),
        cash_balance=12000,
        watchlist=(
            WatchlistItem(symbol="SNOW", thesis="Strong revenue reacceleration", valuation_score=84, conviction_score=88, risk_score=22, sector="Software"),
            WatchlistItem(symbol="TSM", thesis="Foundry leadership intact", valuation_score=80, conviction_score=83, risk_score=27, sector="Semiconductors"),
            WatchlistItem(symbol="XYZ", thesis="Speculative and noisy", valuation_score=40, conviction_score=30, risk_score=60, sector="Small Cap"),
        ),
        thesis_health_scores={"AAPL": 78, "MSFT": 75, "XOM": 41, "SNOW": 82, "TSM": 76, "XYZ": 35},
        valuation_scores={"AAPL": 72, "MSFT": 68, "XOM": 44, "SNOW": 84, "TSM": 80, "XYZ": 40},
        conviction_scores={"AAPL": 80, "MSFT": 76, "XOM": 37, "SNOW": 88, "TSM": 83, "XYZ": 30},
        risk_scores={"AAPL": 28, "MSFT": 30, "XOM": 74, "SNOW": 22, "TSM": 27, "XYZ": 60},
        recent_material_news=(
            MaterialNewsItem(
                symbol="XOM",
                headline="Refining margins compress",
                summary="Margins weakened on lower crack spreads.",
                impact="negative",
                materiality_score=78,
                source="Reuters",
                published_at="2026-07-19T08:15:00-05:00",
            ),
            MaterialNewsItem(
                symbol="SNOW",
                headline="Cloud spend normalization shows signs of reversal",
                summary="Enterprise spend recovery appears to be broadening.",
                impact="positive",
                materiality_score=74,
                source="Bloomberg",
                published_at="2026-07-19T08:30:00-05:00",
            ),
        ),
        constraints=PortfolioConstraint(
            min_cash_weight=0.10,
            target_cash_weight=0.15,
            max_single_name_weight=0.25,
            max_sector_weight=0.40,
            max_portfolio_risk=60.0,
            min_diversification_score=55.0,
            min_liquidity_score=50.0,
        ),
    )


def test_generate_brief_is_deterministic(tmp_path):
    engine = DecisionEngine()
    report_path = tmp_path / "artifacts" / "cio" / "daily_cio_brief.md"

    brief = engine.generate(_sample_inputs(), report_path=report_path)

    assert brief.date == "2026-07-19"
    assert brief.portfolio_health_score == 70.76
    assert brief.overall_risk == "MODERATE"
    assert len(brief.top_actions) == 3
    assert [action.priority for action in brief.top_actions] == [1, 2, 3]
    assert len({action.title for action in brief.top_actions}) == 3
    assert brief.top_actions[0].title == "Trim XOM"
    assert brief.top_actions[1].title == "Trim MSFT"
    assert brief.top_actions[2].title == "Trim AAPL"
    assert [action.symbol for action in brief.recommended_buys] == ["SNOW", "TSM"]
    assert [action.symbol for action in brief.recommended_trims] == ["XOM", "MSFT", "AAPL"]
    assert not brief.holds
    assert [change.symbol for change in brief.thesis_changes] == ["XOM", "SNOW"]
    assert report_path.exists()


def test_markdown_generation_is_stable(tmp_path):
    engine = DecisionEngine()
    first_path = tmp_path / "run_one" / "artifacts" / "cio" / "daily_cio_brief.md"
    second_path = tmp_path / "run_two" / "artifacts" / "cio" / "daily_cio_brief.md"

    first_brief = engine.generate(_sample_inputs(), report_path=first_path)
    second_brief = engine.generate(_sample_inputs(), report_path=second_path)

    assert first_brief == second_brief
    assert first_path.read_text(encoding="utf-8") == second_path.read_text(encoding="utf-8")


def test_report_contains_expected_sections(tmp_path):
    engine = DecisionEngine()
    report_path = tmp_path / "artifacts" / "cio" / "daily_cio_brief.md"

    engine.generate(_sample_inputs(), report_path=report_path)
    markdown = report_path.read_text(encoding="utf-8")

    assert "# Daily CIO Brief - 2026-07-19" in markdown
    assert "## Executive Summary" in markdown
    assert "## Portfolio Health" in markdown
    assert "## Top Three Actions" in markdown
    assert "## Recommended Buys" in markdown
    assert "## Recommended Trims" in markdown
    assert "## Risk Summary" in markdown
    assert "## Cash Recommendation" in markdown
    assert "## Open Questions" in markdown