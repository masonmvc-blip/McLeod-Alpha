from __future__ import annotations

import json
from pathlib import Path

from engine.cio import (
    DecisionEngine,
    DecisionEngineInputs,
    DecisionJournal,
    MaterialNewsItem,
    PortfolioConstraint,
    PortfolioHolding,
    PortfolioOS,
    PortfolioOSInputs,
    WatchlistItem,
)
from engine.cio.outcome_reconciliation import reconcile_decision


def _sample_inputs() -> DecisionEngineInputs:
    return DecisionEngineInputs(
        date="2026-07-19",
        holdings=(
            PortfolioHolding(symbol="AAPL", quantity=120, market_value=42000, sector="Technology", thesis_health_score=78, valuation_score=72, conviction_score=80, risk_score=28, liquidity_score=94),
            PortfolioHolding(symbol="MSFT", quantity=80, market_value=36000, sector="Technology", thesis_health_score=75, valuation_score=68, conviction_score=76, risk_score=30, liquidity_score=96),
            PortfolioHolding(symbol="XOM", quantity=140, market_value=25000, sector="Energy", thesis_health_score=41, valuation_score=44, conviction_score=37, risk_score=74, liquidity_score=70),
        ),
        cash_balance=12000,
        watchlist=(
            WatchlistItem(symbol="SNOW", thesis="Strong revenue reacceleration", valuation_score=84, conviction_score=88, risk_score=22, sector="Software"),
            WatchlistItem(symbol="TSM", thesis="Foundry leadership intact", valuation_score=80, conviction_score=83, risk_score=27, sector="Semiconductors"),
            WatchlistItem(symbol="MELI", thesis="Latin America commerce strength", valuation_score=82, conviction_score=79, risk_score=25, sector="Consumer Internet"),
        ),
        thesis_health_scores={"AAPL": 78, "MSFT": 75, "XOM": 41, "SNOW": 82, "TSM": 76, "MELI": 79},
        valuation_scores={"AAPL": 72, "MSFT": 68, "XOM": 44, "SNOW": 84, "TSM": 80, "MELI": 82},
        conviction_scores={"AAPL": 80, "MSFT": 76, "XOM": 37, "SNOW": 88, "TSM": 83, "MELI": 79},
        risk_scores={"AAPL": 28, "MSFT": 30, "XOM": 74, "SNOW": 22, "TSM": 27, "MELI": 25},
        recent_material_news=(
            MaterialNewsItem(symbol="XOM", headline="Refining margins compress", summary="Margins weakened on lower crack spreads.", impact="negative", materiality_score=78, source="Reuters", published_at="2026-07-19T08:15:00-05:00"),
            MaterialNewsItem(symbol="SNOW", headline="Cloud spend normalization shows signs of reversal", summary="Enterprise spend recovery appears to be broadening.", impact="positive", materiality_score=74, source="Bloomberg", published_at="2026-07-19T08:30:00-05:00"),
            MaterialNewsItem(symbol="MELI", headline="Payments mix improves", summary="New merchant activity accelerates.", impact="positive", materiality_score=68, source="Bloomberg", published_at="2026-07-19T08:35:00-05:00"),
        ),
        constraints=PortfolioConstraint(min_cash_weight=0.10, target_cash_weight=0.15, max_single_name_weight=0.25, max_sector_weight=0.40, max_portfolio_risk=60.0, min_diversification_score=55.0, min_liquidity_score=50.0),
    )


def _build_plan(tmp_path: Path):
    engine = DecisionEngine()
    brief = engine.generate(_sample_inputs(), report_path=tmp_path / "brief.md")
    journal = DecisionJournal(tmp_path / "journal")
    records = journal.record_brief(brief)

    journal.record_outcome(
        reconcile_decision(
            record=records[0],
            evaluation_date="2026-07-20",
            entry_price=100.0,
            current_price=92.0,
            benchmark_return=-0.03,
            holding_period_days=1,
            thesis_status="impaired",
        )
    )
    journal.record_outcome(
        reconcile_decision(
            record=records[1],
            evaluation_date="2026-07-20",
            entry_price=100.0,
            current_price=108.0,
            benchmark_return=0.02,
            holding_period_days=1,
            thesis_status="validated",
        )
    )

    return PortfolioOS().generate_plan(
        PortfolioOSInputs(
            date="2026-07-19",
            decision_brief=brief,
            decision_records=records,
            realized_outcomes=(
                journal._load_outcomes()[0],
                journal._load_outcomes()[1],
            ),
            current_portfolio=_sample_inputs().holdings,
            cash_balance=_sample_inputs().cash_balance,
            watchlist=_sample_inputs().watchlist,
            risk_limits=_sample_inputs().constraints,
            max_position_size=0.20,
            min_position_size=0.02,
            max_cash_allocation=0.25,
            margin_settings={"buying_power": 100000.0, "maintenance_requirement": 12000.0},
        ),
        report_path=tmp_path / "artifacts" / "cio" / "portfolio_plan.md",
    )


def test_portfolio_os_generates_deterministic_plan(tmp_path):
    first = _build_plan(tmp_path / "first")
    second = _build_plan(tmp_path / "second")

    assert first == second
    assert first.date == "2026-07-19"
    assert first.cash_target == 0.15
    assert first.required_actions
    assert first.replacement_candidates
    assert first.expected_portfolio_alpha > 0
    assert first.expected_portfolio_risk >= 0


def test_allocation_and_replacement_logic(tmp_path):
    plan = _build_plan(tmp_path)

    assert plan.target_portfolio[0].symbol in {"SNOW", "MELI", "TSM", "AAPL", "MSFT"}
    assert any(action.text.startswith("Increase") for action in plan.required_actions)
    assert any(action.text.startswith("Replace") for action in plan.required_actions)
    assert any(candidate.symbol_to_buy in {"SNOW", "MELI", "TSM"} for candidate in plan.replacement_candidates)


def test_cash_allocation_and_risk_budget(tmp_path):
    plan = _build_plan(tmp_path)

    assert plan.cash_target == 0.15
    assert plan.risk_budget.cash_exposure == 0.15
    assert plan.risk_budget.concentration > 0
    assert plan.risk_budget.sector_exposure
    assert plan.risk_budget.largest_risks


def test_stable_markdown_and_plan_generation(tmp_path):
    first = _build_plan(tmp_path / "alpha")
    second = _build_plan(tmp_path / "beta")

    first_md = (tmp_path / "alpha" / "artifacts" / "cio" / "portfolio_plan.md").read_text(encoding="utf-8")
    second_md = (tmp_path / "beta" / "artifacts" / "cio" / "portfolio_plan.md").read_text(encoding="utf-8")

    assert first_md == second_md
    assert first.to_dict() == second.to_dict()
    assert "## Executive Summary" in first_md
    assert "## Target Portfolio" in first_md
    assert "## Allocation Changes" in first_md
    assert "## Replacement Candidates" in first_md
    assert "## Risk Budget" in first_md
    assert "## Cash Recommendation" in first_md
    assert "## Expected Improvement" in first_md
    assert json.loads(json.dumps(first.to_dict(), sort_keys=True))