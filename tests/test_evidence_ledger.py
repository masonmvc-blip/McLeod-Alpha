from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.cio.decision_record import DecisionRecord, build_decision_id
from engine.cio.evidence_ledger import EvidenceLedger
from engine.cio.evidence_lineage import (
    evidence_from_thesis_input,
    lineage_from_decision_record,
    lineage_from_portfolio_plan,
    lineage_from_realized_outcome,
    lineage_from_thesis_evaluation,
)
from engine.cio.evidence_record import (
    EvidenceConflictError,
    EvidenceRecord,
    EvidenceValidationError,
    create_evidence_record,
)
from engine.cio.evidence_replay import EvidenceReplay
from engine.cio.outcome_reconciliation import RealizedOutcome
from engine.cio.portfolio_plan import PortfolioPlan
from engine.cio.thesis_engine import ThesisEngine, ThesisEngineInputs
from engine.cio.thesis_evidence import ThesisEvidence
from engine.cio.thesis_graph import ThesisDefinition
from engine.cio.risk_budget import RiskBudget


def _thesis() -> ThesisDefinition:
    return ThesisDefinition(
        thesis_id="TH-XYZ-2026-07-19",
        symbol="XYZ",
        as_of_date="2026-07-19",
        current_thesis="XYZ can sustain growth through share gains in its core segment.",
        core_assumptions=("Share gains continue.",),
        competitive_advantages=("Distribution moat.",),
        growth_drivers=("New customer cohort expansion.",),
        valuation_assumptions=("Multiple stays stable.",),
        capital_allocation_assumptions=("Buyback pace stays disciplined.",),
        risks=("Execution miss could slow demand.",),
        disconfirming_evidence=("Sustained churn increase would weaken thesis.",),
        key_metrics=("Net retention above 110%.",),
        expected_catalysts=("Guidance raise.",),
        invalidation_criteria=("Two sequential revenue misses.",),
    )


def _thesis_evidence() -> tuple[ThesisEvidence, ...]:
    return (
        ThesisEvidence(
            evidence_id="seed-1",
            fact="Guidance raise and share gains were confirmed.",
            source="Earnings",
            observed_date="2026-07-18",
            confidence=82.0,
            materiality=80.0,
            recency=90.0,
        ),
        ThesisEvidence(
            evidence_id="seed-2",
            fact="Possible churn increase flagged by management.",
            source="Call",
            observed_date="2026-07-19",
            confidence=77.0,
            materiality=85.0,
            recency=95.0,
        ),
    )


def _decision_record() -> DecisionRecord:
    decision_id = build_decision_id(
        as_of_date="2026-07-19",
        symbol="XYZ",
        action_type="buy",
        recommendation="Buy XYZ",
        source_brief_id="BRIEF-XYZ-2026-07-19",
    )
    return DecisionRecord(
        decision_id=decision_id,
        created_at="2026-07-19T00:00:00+00:00",
        as_of_date="2026-07-19",
        symbol="XYZ",
        action_type="buy",
        priority=1,
        recommendation="Buy XYZ",
        confidence=75.0,
        expected_benefit="Upside from share gains.",
        expected_risk="Execution risk.",
        supporting_evidence=("Share gains",),
        conflicting_evidence=(),
        assumptions=("Demand stable",),
        invalidation_conditions=("Two misses",),
        source_brief_id="BRIEF-XYZ-2026-07-19",
        status="OPEN",
    )


def _portfolio_plan() -> PortfolioPlan:
    return PortfolioPlan(
        date="2026-07-19",
        current_portfolio=(),
        target_portfolio=(),
        required_actions=(),
        replacement_candidates=(),
        allocation_changes=(),
        cash_target=0.15,
        risk_budget=RiskBudget(
            concentration=0.20,
            sector_exposure=(("Tech", 0.20),),
            cash_exposure=0.15,
            expected_volatility=20.0,
            largest_risks=("Execution",),
            largest_opportunities=("Share gains",),
        ),
        expected_portfolio_alpha=0.04,
        expected_portfolio_risk=0.20,
        confidence=70.0,
        executive_summary="Portfolio plan.",
    )


def _outcome(decision_id: str) -> RealizedOutcome:
    return RealizedOutcome(
        absolute_return=0.08,
        benchmark_adjusted_return=0.04,
        directionally_correct=True,
        confidence_bucket="HIGH",
        thesis_outcome="validated",
        evaluation_date="2026-07-25",
        notes=("holding_period_days=6",),
        decision_id=decision_id,
    )


def _record(recorded_at: str = "2026-07-19") -> EvidenceRecord:
    return create_evidence_record(
        symbol="XYZ",
        observed_at="2026-07-18",
        recorded_at=recorded_at,
        source="Earnings",
        source_type="filing",
        headline="Guidance raised",
        summary="Management raised guidance.",
        raw_fact="Guidance was raised with stronger cohort retention.",
        classification="supports thesis",
        confidence=84.0,
        materiality=80.0,
        recency_score=90.0,
        related_thesis_component="growth_drivers",
        metadata={"section": "guidance", "run": "alpha"},
    )


def test_immutable_evidence_record_and_deterministic_ids_hashes():
    record_a = _record()
    record_b = _record()

    assert record_a.evidence_id == record_b.evidence_id
    assert record_a.content_hash == record_b.content_hash
    assert record_a.recorded_at == "2026-07-19"

    with pytest.raises(FrozenInstanceError):
        record_a.summary = "x"  # type: ignore[misc]


def test_idempotent_duplicate_append_and_conflict_rejection(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger")
    record = _record()

    first = ledger.append_evidence(record)
    second = ledger.append_evidence(record)
    assert first == second

    conflict = EvidenceRecord(
        evidence_id=record.evidence_id,
        symbol=record.symbol,
        observed_at=record.observed_at,
        recorded_at=record.recorded_at,
        source=record.source,
        source_type=record.source_type,
        headline=record.headline,
        summary="tampered",
        raw_fact=record.raw_fact,
        classification=record.classification,
        confidence=record.confidence,
        materiality=record.materiality,
        recency_score=record.recency_score,
        related_thesis_component=record.related_thesis_component,
        content_hash=record.content_hash,
        supersedes_evidence_id=record.supersedes_evidence_id,
        metadata=record.metadata,
    )

    with pytest.raises(EvidenceConflictError):
        ledger.append_evidence(conflict)


def test_append_only_persistence_and_deterministic_index_rebuild(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger")
    first = _record(recorded_at="2026-07-19")
    second = create_evidence_record(
        symbol="XYZ",
        observed_at="2026-07-20",
        recorded_at="2026-07-20",
        source="Call",
        source_type="transcript",
        headline="Follow-up",
        summary="Follow-up summary",
        raw_fact="Follow-up evidence",
        classification="neutral",
        confidence=50.0,
        materiality=40.0,
        recency_score=85.0,
        related_thesis_component="key_metrics",
        supersedes_evidence_id=first.evidence_id,
        metadata={"k": "v"},
    )

    ledger.append_evidence(first)
    text_before = ledger.evidence_path.read_text(encoding="utf-8")
    ledger.append_evidence(second)
    text_after = ledger.evidence_path.read_text(encoding="utf-8")

    assert text_after.startswith(text_before)

    index_one = ledger.rebuild_index()
    index_two = ledger.rebuild_index()
    assert index_one == index_two


def test_manifest_hash_verification(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger")
    ledger.append_evidence(_record())

    integrity_ok = ledger.verify_integrity()
    assert integrity_ok.ok is True

    ledger.evidence_path.write_text(ledger.evidence_path.read_text(encoding="utf-8") + "#", encoding="utf-8")
    integrity_bad = ledger.verify_integrity()
    assert integrity_bad.ok is False
    assert "evidence.jsonl" in integrity_bad.hash_mismatches


def test_explicit_lineage_linking_and_lookups(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger")
    record = ledger.append_evidence(_record())

    decision = _decision_record()
    links = lineage_from_decision_record(decision_record=decision, evidence_ids=(record.evidence_id,))
    ledger.link_many(links)

    evidence_links = ledger.get_lineage_for_evidence(record.evidence_id)
    target_links = ledger.get_lineage_for_target("DecisionRecord", decision.decision_id)

    assert len(evidence_links) == 1
    assert len(target_links) == 1
    assert evidence_links[0].relationship == "triggered"

    with pytest.raises(EvidenceValidationError):
        lineage_from_decision_record(decision_record=decision, evidence_ids=())


def test_point_in_time_replay_and_superseded_handling(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger")
    old_record = create_evidence_record(
        symbol="XYZ",
        observed_at="2026-07-10",
        recorded_at="2026-07-10",
        source="Old",
        source_type="note",
        headline="Old thesis note",
        summary="Old summary",
        raw_fact="Old fact",
        classification="supports thesis",
        confidence=70.0,
        materiality=60.0,
        recency_score=40.0,
        related_thesis_component="core_assumptions",
        metadata={"v": "1"},
    )
    new_record = create_evidence_record(
        symbol="XYZ",
        observed_at="2026-07-15",
        recorded_at="2026-07-15",
        source="New",
        source_type="note",
        headline="Replacement thesis note",
        summary="Replacement summary",
        raw_fact="Replacement fact",
        classification="supports thesis",
        confidence=80.0,
        materiality=70.0,
        recency_score=85.0,
        related_thesis_component="core_assumptions",
        supersedes_evidence_id=old_record.evidence_id,
        metadata={"v": "2"},
    )
    ledger.append_many((old_record, new_record))

    replay = EvidenceReplay(ledger)
    snap_before = replay.snapshot("XYZ", "2026-07-12")
    snap_after = replay.snapshot("XYZ", "2026-07-20")

    assert [row.evidence_id for row in snap_before] == [old_record.evidence_id]
    assert [row.evidence_id for row in snap_after] == [new_record.evidence_id]


def test_full_chain_reconstruction_and_stable_markdown(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger")

    thesis_eval = ThesisEngine().generate(
        ThesisEngineInputs(thesis=_thesis(), evidence=_thesis_evidence()),
        report_path=tmp_path / "thesis_report.md",
    )
    classified = thesis_eval.evidence_summary.supporting[0]
    evidence_record = evidence_from_thesis_input(
        classified_evidence=classified,
        recorded_at="2026-07-19",
        metadata={"symbol": "XYZ", "component": "growth_drivers"},
    )
    evidence_record = EvidenceRecord(
        evidence_id=evidence_record.evidence_id,
        symbol="XYZ",
        observed_at=evidence_record.observed_at,
        recorded_at=evidence_record.recorded_at,
        source=evidence_record.source,
        source_type=evidence_record.source_type,
        headline=evidence_record.headline,
        summary=evidence_record.summary,
        raw_fact=evidence_record.raw_fact,
        classification=evidence_record.classification,
        confidence=evidence_record.confidence,
        materiality=evidence_record.materiality,
        recency_score=evidence_record.recency_score,
        related_thesis_component="growth_drivers",
        content_hash=evidence_record.content_hash,
        supersedes_evidence_id=evidence_record.supersedes_evidence_id,
        metadata=evidence_record.metadata,
    )
    ledger.append_evidence(evidence_record)

    decision = _decision_record()
    plan = _portfolio_plan()
    outcome = _outcome(decision.decision_id)

    ledger.link_many(
        lineage_from_thesis_evaluation(evaluation=thesis_eval, evidence_ids=(evidence_record.evidence_id,))
        + lineage_from_decision_record(decision_record=decision, evidence_ids=(evidence_record.evidence_id,))
        + lineage_from_portfolio_plan(portfolio_plan=plan, evidence_ids=(evidence_record.evidence_id,))
        + lineage_from_realized_outcome(
            realized_outcome=outcome,
            evidence_ids=(evidence_record.evidence_id,),
            relationship="validated",
        )
    )

    replay = EvidenceReplay(ledger)
    chain = replay.reconstruct_chain("DecisionRecord", decision.decision_id)

    assert chain["target_type"] == "DecisionRecord"
    assert chain["target_id"] == decision.decision_id
    assert len(chain["evidence"]) == 1
    assert chain["evidence"][0]["classification"] in {"supports thesis", "weakens thesis", "neutral", "unknown"}

    first_report = replay.write_chain_report("DecisionRecord", decision.decision_id, report_path=tmp_path / "a" / "report.md")
    second_report = replay.write_chain_report("DecisionRecord", decision.decision_id, report_path=tmp_path / "b" / "report.md")

    assert first_report.markdown == second_report.markdown
    assert "## Audit Target" in first_report.markdown
    assert "## Integrity Status" in first_report.markdown


def test_no_mutation_of_existing_cio_objects(tmp_path):
    ledger = EvidenceLedger(tmp_path / "ledger")
    record = ledger.append_evidence(_record())

    decision = _decision_record()
    decision_before = decision.to_dict()

    _ = lineage_from_decision_record(decision_record=decision, evidence_ids=(record.evidence_id,))

    assert decision.to_dict() == decision_before
