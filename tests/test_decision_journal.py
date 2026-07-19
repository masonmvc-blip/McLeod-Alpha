from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.cio import DecisionEngine, DecisionEngineInputs, DecisionJournal, PortfolioConstraint, PortfolioHolding, WatchlistItem, MaterialNewsItem
from engine.cio.decision_record import DecisionJournalConflictError
from engine.cio.outcome_reconciliation import confidence_bucket_from_confidence, reconcile_decision


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
            WatchlistItem(symbol="XYZ", thesis="Speculative and noisy", valuation_score=40, conviction_score=30, risk_score=60, sector="Small Cap"),
        ),
        thesis_health_scores={"AAPL": 78, "MSFT": 75, "XOM": 41, "SNOW": 82, "TSM": 76, "XYZ": 35},
        valuation_scores={"AAPL": 72, "MSFT": 68, "XOM": 44, "SNOW": 84, "TSM": 80, "XYZ": 40},
        conviction_scores={"AAPL": 80, "MSFT": 76, "XOM": 37, "SNOW": 88, "TSM": 83, "XYZ": 30},
        risk_scores={"AAPL": 28, "MSFT": 30, "XOM": 74, "SNOW": 22, "TSM": 27, "XYZ": 60},
        recent_material_news=(
            MaterialNewsItem(symbol="XOM", headline="Refining margins compress", summary="Margins weakened on lower crack spreads.", impact="negative", materiality_score=78, source="Reuters", published_at="2026-07-19T08:15:00-05:00"),
            MaterialNewsItem(symbol="SNOW", headline="Cloud spend normalization shows signs of reversal", summary="Enterprise spend recovery appears to be broadening.", impact="positive", materiality_score=74, source="Bloomberg", published_at="2026-07-19T08:30:00-05:00"),
        ),
        constraints=PortfolioConstraint(min_cash_weight=0.10, target_cash_weight=0.15, max_single_name_weight=0.25, max_sector_weight=0.40, max_portfolio_risk=60.0, min_diversification_score=55.0, min_liquidity_score=50.0),
    )


def _build_brief(tmp_path: Path):
    engine = DecisionEngine()
    return engine.generate(_sample_inputs(), report_path=tmp_path / "brief.md")


def test_deterministic_ids_and_idempotent_write(tmp_path):
    brief = _build_brief(tmp_path)
    journal = DecisionJournal(tmp_path / "journal")

    first_records = journal.record_brief(brief)
    second_records = journal.record_brief(brief)

    assert first_records == second_records
    assert len(first_records) == 6
    assert len({record.decision_id for record in first_records}) == 6
    assert [record.priority for record in first_records] == [1, 2, 3, 4, 5, 6]

    decisions_text = journal.decisions_path.read_text(encoding="utf-8")
    assert decisions_text == journal.decisions_path.read_text(encoding="utf-8")
    index_payload = json.loads(journal.index_path.read_text(encoding="utf-8"))
    assert index_payload["total_records"] == 6
    assert index_payload["open_records"] == 6
    assert index_payload["closed_records"] == 0
    assert index_payload["records_by_action_type"] == {"buy": 2, "cash": 1, "trim": 3}
    assert index_payload["records_by_symbol"] == {"AAPL": 1, "CASH": 1, "MSFT": 1, "SNOW": 1, "TSM": 1, "XOM": 1}


def test_conflicting_duplicate_rejection(tmp_path):
    brief = _build_brief(tmp_path)
    journal = DecisionJournal(tmp_path / "journal")
    records = journal.record_brief(brief)

    lines = journal.decisions_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["recommendation"] = "tampered"
    lines[0] = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    journal.decisions_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(DecisionJournalConflictError):
        journal.record_brief(brief)

    assert records[0].decision_id == payload["decision_id"]


def test_outcome_reconciliation_and_confidence_bucket(tmp_path):
    brief = _build_brief(tmp_path)
    record = DecisionJournal(tmp_path / "journal").record_brief(brief)[0]

    outcome = reconcile_decision(
        record=record,
        evaluation_date="2026-07-20",
        entry_price=100.0,
        current_price=92.0,
        benchmark_return=-0.03,
        holding_period_days=1,
        thesis_status="impaired",
    )

    assert outcome.decision_id == record.decision_id
    assert outcome.absolute_return == -0.08
    assert outcome.benchmark_adjusted_return == -0.05
    assert outcome.directionally_correct is True
    assert outcome.confidence_bucket == confidence_bucket_from_confidence(record.confidence)
    assert outcome.thesis_outcome == "impaired"
    assert outcome.evaluation_date == "2026-07-20"


def test_analytics_aggregation_and_stable_reports(tmp_path):
    brief = _build_brief(tmp_path)
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

    summary_first = journal.generate_performance_summary()
    summary_second = journal.generate_performance_summary()

    assert summary_first == summary_second
    assert summary_first["recommendation_count"] == 6
    assert summary_first["open_decision_count"] == 4
    assert summary_first["closed_decision_count"] == 2
    assert summary_first["win_rate"] == 0.5
    assert summary_first["directional_accuracy"] == 0.5
    assert summary_first["results_by_action_type"]["trim"]["count"] == 2
    assert summary_first["results_by_confidence_bucket"]["HIGH"]["count"] == 2

    summary_text = journal.summary_path.read_text(encoding="utf-8")
    report_text = journal.report_path.read_text(encoding="utf-8")
    index_text = journal.index_path.read_text(encoding="utf-8")

    assert summary_text == journal.summary_path.read_text(encoding="utf-8")
    assert report_text == journal.report_path.read_text(encoding="utf-8")
    assert index_text == journal.index_path.read_text(encoding="utf-8")
    assert "# Decision Journal Performance Report" in report_text
    assert "Results By Action Type" in report_text
    assert "Results By Confidence Bucket" in report_text