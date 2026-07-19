from __future__ import annotations

import ast
from dataclasses import asdict
from pathlib import Path

from .model import EvidenceEngineModel, EvidenceValidationError
from .types import CertificationResult, RawEvidenceRecord


class EvidenceEngineCertificationModel:
    FORBIDDEN_IMPORT_PREFIXES = (
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
        "engine.portfolio_engine",
        "engine.phase2_downstream",
        "execution",
    )

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)
        self.package_dir = self.repo_root / "engine" / "phase5" / "evidence_engine"

    def certify(self) -> CertificationResult:
        discrepancies: list[str] = []

        package_isolated = self._verify_package_isolation()
        if not package_isolated:
            discrepancies.append("PACKAGE_ISOLATION_VIOLATION")

        deterministic_replay_passed = self._verify_deterministic_replay()
        if not deterministic_replay_passed:
            discrepancies.append("DETERMINISTIC_REPLAY_FAILURE")

        traceability_passed = self._verify_traceability()
        if not traceability_passed:
            discrepancies.append("TRACEABILITY_FAILURE")

        duplicate_handling_passed = self._verify_duplicate_handling()
        if not duplicate_handling_passed:
            discrepancies.append("DUPLICATE_HANDLING_FAILURE")

        fail_closed_passed = self._verify_fail_closed()
        if not fail_closed_passed:
            discrepancies.append("FAIL_CLOSED_FAILURE")

        return CertificationResult(
            passed=not discrepancies,
            package_isolated=package_isolated,
            deterministic_replay_passed=deterministic_replay_passed,
            traceability_passed=traceability_passed,
            duplicate_handling_passed=duplicate_handling_passed,
            fail_closed_passed=fail_closed_passed,
            discrepancies=tuple(sorted(set(discrepancies))),
        )

    def _verify_package_isolation(self) -> bool:
        for py_file in self.package_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                            return False
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                        return False
        return True

    def _verify_deterministic_replay(self) -> bool:
        model = EvidenceEngineModel()
        records = self._fixture_records()
        first = model.evaluate(ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=records)
        second = model.evaluate(ticker="RKLB", as_of="2026-07-18T00:00:00+00:00", evidence_records=tuple(reversed(records)))
        return EvidenceEngineModel.to_canonical_json(first) == EvidenceEngineModel.to_canonical_json(second)

    def _verify_traceability(self) -> bool:
        model = EvidenceEngineModel()
        result = model.evaluate(
            ticker="RKLB",
            as_of="2026-07-18T00:00:00+00:00",
            evidence_records=self._fixture_records(),
        )
        known_ids = set(result.evidence_by_id.keys())
        for summary in result.conclusion.summaries:
            for evidence_id in (
                tuple(summary.supporting_evidence_ids)
                + tuple(summary.opposing_evidence_ids)
                + tuple(summary.neutral_evidence_ids)
            ):
                if evidence_id not in known_ids:
                    return False
        return True

    def _verify_duplicate_handling(self) -> bool:
        model = EvidenceEngineModel()
        result = model.evaluate(
            ticker="RKLB",
            as_of="2026-07-18T00:00:00+00:00",
            evidence_records=self._fixture_records(),
        )
        duplicate_entries = [v for v in result.duplicate_map.values() if v]
        return bool(duplicate_entries) and result.deduplicated_count < result.validated_count

    def _verify_fail_closed(self) -> bool:
        model = EvidenceEngineModel()
        try:
            model.evaluate(
                ticker="RKLB",
                as_of="2026-07-18T00:00:00+00:00",
                evidence_records=(
                    RawEvidenceRecord(
                        evidence_id="bad-1",
                        ticker="RKLB",
                        topic="valuation",
                        title="Invalid evidence",
                        publisher="Unit",
                        source_url="file:///private",
                        source_type="news",
                        published_at="2026-07-18T00:00:00+00:00",
                        claim="invalid",
                        polarity="support",
                        confidence_hint=0.6,
                        provenance={"source_document_id": "bad"},
                    ),
                ),
            )
        except EvidenceValidationError:
            return True
        return False

    @staticmethod
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
