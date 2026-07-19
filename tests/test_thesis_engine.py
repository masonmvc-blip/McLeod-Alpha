from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from engine.cio.thesis_engine import ThesisEngine, ThesisEngineInputs, ThesisEvaluation
from engine.cio.thesis_evidence import ThesisEvidence
from engine.cio.thesis_graph import ThesisDefinition


def _thesis() -> ThesisDefinition:
    return ThesisDefinition(
        thesis_id="TH-AAPL-2026-07-19",
        symbol="AAPL",
        as_of_date="2026-07-19",
        current_thesis="AAPL can compound free cash flow via premium mix expansion and ecosystem retention.",
        core_assumptions=(
            "Premium mix continues to expand.",
            "Installed base retention stays above prior cycle levels.",
        ),
        competitive_advantages=(
            "Ecosystem lock-in remains strong.",
            "Brand pricing power sustains margins.",
        ),
        growth_drivers=(
            "Services revenue acceleration.",
            "New category adoption.",
        ),
        valuation_assumptions=(
            "Multiple remains justified by durable cash flow growth.",
        ),
        capital_allocation_assumptions=(
            "Repurchase discipline remains consistent.",
        ),
        risks=(
            "China demand slowdown could pressure growth.",
            "Gross margin compression is a key risk.",
        ),
        disconfirming_evidence=(
            "Sustained services deceleration would weaken thesis.",
        ),
        key_metrics=(
            "Services growth above hardware growth.",
            "Gross margin trend stability.",
        ),
        expected_catalysts=(
            "Product cycle announcement.",
            "Services attach improvement disclosure.",
            "Do we have enough regional data?",
        ),
        invalidation_criteria=(
            "Two consecutive quarters of services contraction.",
            "Meaningful installed base churn increase.",
        ),
    )


def _evidence() -> tuple[ThesisEvidence, ...]:
    return (
        ThesisEvidence(
            evidence_id="E-001",
            fact="Services growth accelerated and ecosystem retention stayed strong.",
            source="10-Q",
            observed_date="2026-07-18",
            confidence=88.0,
            materiality=82.0,
            recency=95.0,
        ),
        ThesisEvidence(
            evidence_id="E-002",
            fact="Gross margin compression appeared in the latest quarter.",
            source="Earnings call",
            observed_date="2026-07-17",
            confidence=79.0,
            materiality=90.0,
            recency=90.0,
        ),
        ThesisEvidence(
            evidence_id="E-003",
            fact="No incremental detail was provided on the product launch timeline.",
            source="Prepared remarks",
            observed_date="2026-07-16",
            confidence=60.0,
            materiality=40.0,
            recency=70.0,
        ),
        ThesisEvidence(
            evidence_id="E-004",
            fact="",
            source="Unknown",
            observed_date="2026-07-15",
            confidence=10.0,
            materiality=10.0,
            recency=10.0,
        ),
    )


def test_evidence_classification_is_deterministic(tmp_path):
    engine = ThesisEngine()
    first = engine.generate(ThesisEngineInputs(thesis=_thesis(), evidence=_evidence()), report_path=tmp_path / "first" / "thesis_report.md")
    second = engine.generate(ThesisEngineInputs(thesis=_thesis(), evidence=_evidence()), report_path=tmp_path / "second" / "thesis_report.md")

    assert first.evidence_summary == second.evidence_summary
    assert len(first.evidence_summary.supporting) == 1
    assert len(first.evidence_summary.contradictory) == 1
    assert len(first.evidence_summary.neutral) == 1
    assert len(first.evidence_summary.unknown) == 1
    assert first.evidence_summary.supporting[0].classification == "supports thesis"
    assert first.evidence_summary.contradictory[0].classification == "weakens thesis"


def test_health_scoring_and_contradictory_evidence_handling(tmp_path):
    engine = ThesisEngine()

    supportive_only = (
        ThesisEvidence(
            evidence_id="S-1",
            fact="Services revenue acceleration and ecosystem lock-in improved.",
            source="10-Q",
            observed_date="2026-07-18",
            confidence=90.0,
            materiality=85.0,
            recency=95.0,
        ),
    )

    mixed = supportive_only + (
        ThesisEvidence(
            evidence_id="C-1",
            fact="Gross margin compression and demand slowdown were highlighted.",
            source="Call",
            observed_date="2026-07-18",
            confidence=90.0,
            materiality=90.0,
            recency=95.0,
        ),
    )

    eval_supportive = engine.generate(ThesisEngineInputs(thesis=_thesis(), evidence=supportive_only), report_path=tmp_path / "supportive.md")
    eval_mixed = engine.generate(ThesisEngineInputs(thesis=_thesis(), evidence=mixed), report_path=tmp_path / "mixed.md")

    assert eval_supportive.health_breakdown.health_score > eval_mixed.health_breakdown.health_score
    assert "Final thesis health score" in " ".join(eval_mixed.health_breakdown.explanation)
    assert eval_mixed.health_breakdown.contradictory_component > 0.0


def test_report_generation_and_stable_outputs(tmp_path):
    engine = ThesisEngine()

    first = engine.generate(ThesisEngineInputs(thesis=_thesis(), evidence=_evidence()), report_path=tmp_path / "run1" / "thesis_report.md")
    second = engine.generate(ThesisEngineInputs(thesis=_thesis(), evidence=_evidence()), report_path=tmp_path / "run2" / "thesis_report.md")

    assert first.markdown == second.markdown
    assert first.content_hash == second.content_hash

    markdown = (tmp_path / "run1" / "thesis_report.md").read_text(encoding="utf-8")
    assert "## Current Thesis" in markdown
    assert "## Supporting Evidence" in markdown
    assert "## Contradictory Evidence" in markdown
    assert "## Health Score" in markdown
    assert "## Recent Changes" in markdown
    assert "## Key Unanswered Questions" in markdown
    assert "## Possible Invalidation Triggers" in markdown


def test_immutable_thesis_evaluation_contract(tmp_path):
    evaluation = ThesisEngine().generate(ThesisEngineInputs(thesis=_thesis(), evidence=_evidence()), report_path=tmp_path / "thesis_report.md")

    assert isinstance(evaluation, ThesisEvaluation)
    with pytest.raises(FrozenInstanceError):
        evaluation.content_hash = "x"  # type: ignore[misc]
