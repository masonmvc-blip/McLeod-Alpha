from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.phase5.evidence_engine import EvidenceEngineModel, EvidenceValidationError, RawEvidenceRecord


REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "engine" / "phase5" / "evidence_engine"
FROZEN_FILES = (
    REPO_ROOT / "engine" / "phase2_downstream.py",
    REPO_ROOT / "engine" / "portfolio_engine.py",
    REPO_ROOT / "engine" / "phase3" / "context.py",
    REPO_ROOT / "engine" / "phase4" / "research_lab" / "model.py",
)


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_records() -> tuple[RawEvidenceRecord, ...]:
    return (
        RawEvidenceRecord(
            evidence_id="ev-003",
            ticker="RKLB",
            topic="quality",
            title="Factory utilization improving",
            publisher="Manufacturing Journal",
            source_url="https://example.com/quality-1",
            source_type="industry",
            published_at="2026-07-10T00:00:00+00:00",
            claim="Utilization reached multi-quarter highs.",
            polarity="support",
            confidence_hint=0.70,
            provenance={"source_document_id": "doc-q1"},
        ),
        RawEvidenceRecord(
            evidence_id="ev-001",
            ticker="RKLB",
            topic="valuation",
            title="Discounted cash flow indicates upside",
            publisher="Public Research Desk",
            source_url="https://example.com/value-1",
            source_type="research",
            published_at="2026-07-15T00:00:00+00:00",
            claim="Intrinsic value estimate above market.",
            polarity="support",
            confidence_hint=0.80,
            provenance={"source_document_id": "doc-v1"},
        ),
        RawEvidenceRecord(
            evidence_id="ev-004",
            ticker="RKLB",
            topic="quality",
            title="Factory utilization improving",
            publisher="Manufacturing Journal",
            source_url="https://example.com/quality-1",
            source_type="industry",
            published_at="2026-07-10T00:00:00+00:00",
            claim="Utilization reached multi-quarter highs.",
            polarity="support",
            confidence_hint=0.70,
            provenance={"source_document_id": "doc-q1-dup"},
        ),
        RawEvidenceRecord(
            evidence_id="ev-002",
            ticker="RKLB",
            topic="growth",
            title="Order backlog growth slows",
            publisher="Public Newswire",
            source_url="https://example.com/growth-1",
            source_type="news",
            published_at="2026-07-12T00:00:00+00:00",
            claim="Backlog growth decelerated compared to prior quarter.",
            polarity="oppose",
            confidence_hint=0.75,
            provenance={"source_document_id": "doc-g1"},
        ),
        RawEvidenceRecord(
            evidence_id="ev-005",
            ticker="RKLB",
            topic="valuation",
            title="Peer multiple compression risk",
            publisher="Public Newswire",
            source_url="https://example.com/value-2",
            source_type="news",
            published_at="2026-07-14T00:00:00+00:00",
            claim="Comparable multiples may contract.",
            polarity="oppose",
            confidence_hint=0.65,
            provenance={"source_document_id": "doc-v2"},
        ),
    )


def test_determinism_and_input_order_independence() -> None:
    model = EvidenceEngineModel()
    first = model.evaluate(ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=_fixture_records())
    second = model.evaluate(
        ticker="RKLB",
        as_of="2026-07-18T00:00:00+00:00",
        evidence_records=tuple(reversed(_fixture_records())),
    )

    assert EvidenceEngineModel.to_canonical_json(first) == EvidenceEngineModel.to_canonical_json(second)


def test_traceability_of_every_conclusion_reference() -> None:
    result = EvidenceEngineModel().evaluate(
        ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=_fixture_records()
    )
    known_ids = set(result.evidence_by_id)

    for summary in result.conclusion.summaries:
        for evidence_id in summary.supporting_evidence_ids + summary.opposing_evidence_ids + summary.neutral_evidence_ids:
            assert evidence_id in known_ids


def test_duplicate_handling_preserves_duplicate_map() -> None:
    result = EvidenceEngineModel().evaluate(
        ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=_fixture_records()
    )

    assert result.validated_count == 5
    assert result.deduplicated_count == 4
    assert result.duplicate_map["ev-003"] == ("ev-004",)


def test_conflicting_evidence_preserved_and_fail_closed() -> None:
    result = EvidenceEngineModel().evaluate(
        ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=_fixture_records()
    )

    assert "valuation" in result.conclusion.unresolved_conflict_topics
    assert result.conclusion.fail_closed is True
    assert any(reason.startswith("UNRESOLVED_CONFLICTS:") for reason in result.conclusion.fail_reasons)


def test_incomplete_evidence_fails_closed() -> None:
    incomplete = tuple(row for row in _fixture_records() if row.topic != "growth")
    result = EvidenceEngineModel().evaluate(
        ticker="RKLB",
        as_of="2026-07-18T00:00:00+00:00",
        evidence_records=incomplete,
    )

    assert result.conclusion.fail_closed is True
    assert any(reason.startswith("MISSING_REQUIRED_TOPICS:") for reason in result.conclusion.fail_reasons)


def test_invalid_evidence_rejected() -> None:
    invalid = RawEvidenceRecord(
        evidence_id="bad",
        ticker="RKLB",
        topic="valuation",
        title="Bad",
        publisher="Bad",
        source_url="file:///private",
        source_type="news",
        published_at="2026-07-18T00:00:00+00:00",
        claim="Bad",
        polarity="support",
        confidence_hint=0.5,
        provenance={"source_document_id": "bad"},
    )

    with pytest.raises(EvidenceValidationError):
        EvidenceEngineModel().evaluate(ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=(invalid,))


def test_phase5_package_isolation_firewalls() -> None:
    forbidden = (
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
        "engine.portfolio_engine",
        "engine.phase2_downstream",
        "execution",
    )
    for py_file in PACKAGE_DIR.rglob("*.py"):
        module = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden)


def test_frozen_phase_files_unchanged_after_phase5_run() -> None:
    before = {str(path): _sha(path) for path in FROZEN_FILES}
    _ = EvidenceEngineModel().evaluate(ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=_fixture_records())
    after = {str(path): _sha(path) for path in FROZEN_FILES}
    assert before == after


def test_dataclasses_are_immutable() -> None:
    record = _fixture_records()[0]
    with pytest.raises(FrozenInstanceError):
        record.title = "tamper"  # type: ignore[misc]
