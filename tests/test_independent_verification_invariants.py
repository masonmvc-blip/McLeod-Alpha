from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path

from engine.phase3.system_validation.dependency import DependencyValidator
from engine.phase3.system_validation.model import SystemValidationModel


REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_REPORT_HASHES = {
    "reports/technical_debt_audit_v1.md": "b86dbe2975fde1517caa207743430ed5544d26a0fe955f1cc45df3e8b1413204",
    "reports/system_readiness_v1.md": "a5fbb2058d6e8bbfdc2035240f9127afb2515d9adba25b1e2a139e7b671ddc52",
}

EXPECTED_DEPENDENCY_GRAPH = {
    "research_os_release": (),
    "phase3_context": (),
    "expected_return": ("phase3_context",),
    "decision_engine": ("phase3_context", "expected_return"),
    "calibration": ("expected_return", "decision_engine"),
    "portfolio_simulation": ("expected_return", "decision_engine"),
    "shadow_portfolio": ("expected_return", "decision_engine"),
    "system_validation": (
        "research_os_release",
        "phase3_context",
        "expected_return",
        "decision_engine",
        "calibration",
        "portfolio_simulation",
        "shadow_portfolio",
    ),
}

EXPECTED_DEPENDENCY_GRAPH_HASH = "0969d7e72acc07e6f3bf94a0abb0160b5d0050db6fbaaf72b1ae187f7052958f"

EXPECTED_FROZEN_HASHES = {
    "config/research_os_manifest.json": "8133e50ecfad9dc31fc40d237c4409c4ca9573936603008b9f7ca30e3939a473",
    "engine/phase3/context.py": "2099134c8afee427adeb6b291b5f4e10c6b9f0fae9ca4313feb6018297e4c3f1",
    "engine/phase3/expected_return/model.py": "8e0d2b399872c6910bb242ccd204c3687cd7e817cc5138462d82981e1b73ceeb",
    "engine/phase3/decision_engine/model.py": "15f7a92d288314afbfcd1a2d19d1c1484bcd88beece2f8ce7aff4c3ead479beb",
    "engine/phase3/calibration/model.py": "e5977219a3abf15b34e69de0ceef05d6dfccae566934cafb77dd88156c1be367",
    "engine/phase3/portfolio_simulation/model.py": "a4565433daf6f3aa8a2673bd493f7265462109f93890b9f0c48b9965d213d385",
    "engine/phase3/shadow_portfolio_construction/model.py": "43d39d2fec949b6a6060741890e703f19341b2bce63ddce8bd6b481c37c9f53d",
    "engine/phase3/system_validation/model.py": "66b02a55a1cacf154035d9f9454eb4dc5a4c88836c525a49a68cd4de424da3ab",
    "engine/research_os_release.py": "bebb46337f73450af766b325eb6052a5a5db2276926e5166271b0be774f20a35",
    "engine/phase2_downstream.py": "7d25d7aa24be4177118ac41e209fc173e5e5c20607052a0ce4522352ad41804b",
}

FROZEN_MILESTONES = (
    "Research_OS_v1.0",
    "Phase3_Foundation_Validated",
    "ExpectedReturnEngine_Validated",
    "DecisionEngine_Validated",
    "CalibrationEngine_Validated",
    "PortfolioSimulation_Validated",
    "ShadowPortfolioConstruction_Validated",
    "SystemValidation_Complete",
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _phase3_imports() -> dict[str, set[str]]:
    imports: dict[str, set[str]] = {}
    for path in (REPO_ROOT / "engine" / "phase3").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module)
        imports[str(path.relative_to(REPO_ROOT))] = found
    return imports


def test_audit_reports_are_reproducible() -> None:
    for relative, expected_hash in EXPECTED_REPORT_HASHES.items():
        path = REPO_ROOT / relative
        assert path.exists(), f"Missing report: {relative}"
        assert _sha(path) == expected_hash


def test_dependency_graph_is_unchanged() -> None:
    result = DependencyValidator(REPO_ROOT).validate()
    assert result.passed is True
    assert result.dependency_graph == EXPECTED_DEPENDENCY_GRAPH
    payload = json.dumps({k: list(v) for k, v in sorted(result.dependency_graph.items())}, sort_keys=True, separators=(",", ":"))
    assert sha256(payload.encode("utf-8")).hexdigest() == EXPECTED_DEPENDENCY_GRAPH_HASH


def test_frozen_module_hashes_are_unchanged() -> None:
    actual = {path: _sha(REPO_ROOT / path) for path in EXPECTED_FROZEN_HASHES}
    assert actual == EXPECTED_FROZEN_HASHES


def test_no_new_architectural_violations() -> None:
    result = SystemValidationModel(REPO_ROOT).evaluate()
    assert result.passed is True
    assert result.dependency_passed is True
    assert result.audit.validation_status == "passed"


def test_phase3_modules_have_no_hidden_writes() -> None:
    forbidden_tokens = (
        "write_text(",
        "write_bytes(",
        ".to_csv(",
        ".to_json(",
        "json.dump(",
    )
    for path in (REPO_ROOT / "engine" / "phase3").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"Hidden write token {token!r} found in {path}"


def test_phase3_import_boundaries_are_unchanged() -> None:
    imports = _phase3_imports()

    for relative_path, used in imports.items():
        assert "engine.research_phase1" not in used
        assert "engine.portfolio_engine" not in used

        is_context_layer = relative_path == "engine/phase3/context.py"
        is_decision_layer = relative_path == "engine/phase3/decision_engine/model.py"
        is_system_validation = relative_path.startswith("engine/phase3/system_validation/")

        if not is_context_layer:
            assert "engine.phase2_downstream" not in used

        if not is_decision_layer:
            assert "engine.phase2_research" not in used

        if relative_path.startswith("engine/phase3/") and not is_system_validation:
            assert "engine.phase3.system_validation" not in used


def test_frozen_milestone_artifacts_exist() -> None:
    for milestone in FROZEN_MILESTONES:
        path = REPO_ROOT / "data" / "research" / "logs" / f"{milestone}.json"
        assert path.exists(), f"Missing frozen milestone artifact: {path.name}"
