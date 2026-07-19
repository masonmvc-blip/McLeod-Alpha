from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.phase3.independent_system_certification import (
    CertificationResult,
    IndependentSystemCertificationModel,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_EXECUTABLE = str(REPO_ROOT / ".venv" / "bin" / "python")


def test_certification_model_independently_verifies_system() -> None:
    model = IndependentSystemCertificationModel(REPO_ROOT)
    result = model.certify(python_executable=PYTHON_EXECUTABLE)

    assert result.passed
    assert result.dependency_graph_valid
    assert result.lifecycle_registry_valid
    assert result.package_isolation_valid
    assert result.report_references_valid
    assert result.marker_validation_consistent
    assert result.deterministic_replay_from_clean_repo
    assert all(result.frozen_hash_checks.values())
    assert not result.discrepancies


def test_certification_result_immutable() -> None:
    sample = CertificationResult(
        passed=True,
        verified_milestones=("a",),
        checked_reports=("b",),
        checked_suites=("c",),
        checked_packages=("d",),
        frozen_hash_checks={"x": True},
        dependency_graph_valid=True,
        lifecycle_registry_valid=True,
        package_isolation_valid=True,
        report_references_valid=True,
        marker_validation_consistent=True,
        deterministic_replay_from_clean_repo=True,
    )
    with pytest.raises(FrozenInstanceError):
        sample.passed = False  # type: ignore[misc]
