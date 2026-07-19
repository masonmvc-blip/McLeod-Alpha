from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from engine.phase3.system_validation.dependency import DependencyValidator
from engine.phase3.system_validation.model import SystemValidationModel, SystemValidationValidationError


REPO_ROOT = Path(__file__).resolve().parent.parent


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _frozen_files() -> list[Path]:
    return [
        REPO_ROOT / "config" / "research_os_manifest.json",
        REPO_ROOT / "engine" / "phase3" / "expected_return" / "model.py",
        REPO_ROOT / "engine" / "phase3" / "decision_engine" / "model.py",
        REPO_ROOT / "engine" / "phase3" / "calibration" / "model.py",
        REPO_ROOT / "engine" / "phase3" / "portfolio_simulation" / "model.py",
        REPO_ROOT / "engine" / "phase3" / "shadow_portfolio_construction" / "model.py",
        REPO_ROOT / "engine" / "portfolio_engine.py",
    ]


def test_complete_pipeline_deterministic() -> None:
    model = SystemValidationModel(REPO_ROOT)
    first = model.evaluate()
    second = model.evaluate()

    assert first.passed is True
    assert second.passed is True
    assert first.audit == second.audit
    assert first.replay.replay_hash == second.replay.replay_hash


def test_every_audit_is_immutable() -> None:
    result = SystemValidationModel(REPO_ROOT).evaluate()

    with pytest.raises(AttributeError):
        result.audit.steps.append(None)  # type: ignore[attr-defined]

    with pytest.raises(FrozenInstanceError):
        result.audit.steps[0].detail = "tamper"  # type: ignore[misc]


def test_dependency_graph_acyclic_and_valid() -> None:
    dependency = DependencyValidator(REPO_ROOT).validate()

    assert dependency.passed is True
    assert not dependency.errors
    assert "system_validation" in dependency.dependency_graph


def test_frozen_module_hashes_unchanged() -> None:
    before = {str(path): _file_hash(path) for path in _frozen_files()}
    _ = SystemValidationModel(REPO_ROOT).evaluate()
    after = {str(path): _file_hash(path) for path in _frozen_files()}

    assert before == after


def test_replay_hashes_identical() -> None:
    result = SystemValidationModel(REPO_ROOT).evaluate()

    assert result.replay.passed is True
    assert result.replay.outputs_identical is True
    assert result.replay.audits_identical is True
    assert result.replay.hashes_identical is True
    assert result.replay.execution_order_identical is True


def test_production_portfolio_isolated() -> None:
    portfolio_path = REPO_ROOT / "engine" / "portfolio_engine.py"
    before = _file_hash(portfolio_path)
    _ = SystemValidationModel(REPO_ROOT).evaluate()
    after = _file_hash(portfolio_path)

    assert before == after


def test_public_interfaces_respected() -> None:
    source = (REPO_ROOT / "engine" / "phase3" / "system_validation" / "model.py").read_text(encoding="utf-8")

    assert "engine.research_phase1" not in source
    assert "engine.phase2_downstream" not in source
    assert "phase2_artifact.json" not in source
    assert "phase2_review.md" not in source


def test_configuration_hashes_deterministic() -> None:
    model = SystemValidationModel(REPO_ROOT)
    first = model.evaluate()
    second = model.evaluate()

    assert first.audit.configuration_hash == second.audit.configuration_hash


def test_missing_artifacts_fail_closed() -> None:
    model = SystemValidationModel(REPO_ROOT)

    with pytest.raises(SystemValidationValidationError):
        model.evaluate(force_missing_artifact=True)


def test_schema_mismatches_fail_closed() -> None:
    model = SystemValidationModel(REPO_ROOT)

    with pytest.raises(SystemValidationValidationError):
        model.evaluate(force_schema_mismatch=True)
