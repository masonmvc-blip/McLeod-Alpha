from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.phase5.evidence_engine import CertificationResult, EvidenceEngineCertificationModel


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_phase5_evidence_engine_certification_passes() -> None:
    result = EvidenceEngineCertificationModel(REPO_ROOT).certify()

    assert result.passed
    assert result.package_isolated
    assert result.deterministic_replay_passed
    assert result.traceability_passed
    assert result.duplicate_handling_passed
    assert result.fail_closed_passed
    assert not result.discrepancies


def test_certification_result_immutable() -> None:
    result = CertificationResult(
        passed=True,
        package_isolated=True,
        deterministic_replay_passed=True,
        traceability_passed=True,
        duplicate_handling_passed=True,
        fail_closed_passed=True,
        discrepancies=(),
    )
    with pytest.raises(FrozenInstanceError):
        result.passed = False  # type: ignore[misc]
