from __future__ import annotations

import ast
import importlib
import json
from hashlib import sha256
from pathlib import Path

from engine.phase3.system_validation.model import SystemValidationModel


REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_EXCLUDES = ("archive/", "backups/", ".venv/", "venv/")

FROZEN_HASHES = {
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
    "engine/portfolio_engine.py": "4d39683c3a0fee762bf028f748216388aef5b68ed3b5ac149478f6e2f8afb63b",
}

APPROVED_BOUNDARY_FIXES = {
    "engine/phase3/decision_engine/model.py": "Remove direct import of Phase 2 schema constant and use Phase 3 version contract.",
}


def _is_active_path(path: Path) -> bool:
    rel = path.as_posix().lstrip("./")
    return not any(rel.startswith(prefix) for prefix in ACTIVE_EXCLUDES)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_zero_conflicted_copy_files_in_active_paths() -> None:
    conflicted = [
        p
        for p in REPO_ROOT.rglob("*")
        if p.is_file() and "conflicted copy" in p.name.lower() and _is_active_path(p.relative_to(REPO_ROOT))
    ]
    assert not conflicted


def test_quarantined_files_cannot_be_imported() -> None:
    quarantine_dirs = [
        REPO_ROOT / "archive" / "2026-07-18_cleanup" / "repository_hygiene_quarantine" / "conflicted_unresolved",
        REPO_ROOT / "archive" / "2026-07-18_cleanup" / "repository_hygiene_quarantine" / "noncanonical_backup_code",
    ]

    for directory in quarantine_dirs:
        if not directory.exists():
            continue

        for init_file in directory.rglob("__init__.py"):
            raise AssertionError(f"Quarantine directory must not be importable: {init_file}")

        for py_file in directory.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).with_suffix("")
            parts = rel.parts
            if not all(part.isidentifier() for part in parts):
                continue
            module_name = ".".join(parts)
            try:
                importlib.import_module(module_name)
            except Exception:
                continue
            raise AssertionError(f"Quarantined module unexpectedly importable: {module_name}")


def test_no_duplicate_canonical_engine_implementations_in_active_paths() -> None:
    backup_py = [
        p
        for p in REPO_ROOT.rglob("*.py")
        if "backup" in p.name.lower() and _is_active_path(p.relative_to(REPO_ROOT))
    ]
    assert not backup_py

    assert (REPO_ROOT / "execution" / "live_engine.py").exists()
    assert (REPO_ROOT / "backtesting" / "stop_policy_simulator.py").exists()
    assert (REPO_ROOT / "backtesting" / "signal_replay.py").exists()
    assert (REPO_ROOT / "strategy" / "signals.py").exists()


def test_no_phase3_direct_imports_of_phase2_internals() -> None:
    for path in (REPO_ROOT / "engine" / "phase3").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("engine.phase2_research")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("engine.phase2_research")


def test_no_ambiguous_strategy_package_imports() -> None:
    assert not (REPO_ROOT / "strategies").exists()

    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if not _is_active_path(rel):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "strategies"
                assert not node.module.startswith("strategies.")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "strategies"
                    assert not alias.name.startswith("strategies.")


def test_all_phase3_modules_have_explicit_lifecycle_status() -> None:
    lifecycle_path = REPO_ROOT / "config" / "phase3_module_lifecycle.json"
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    modules = lifecycle["modules"]

    discovered = {
        ".".join(p.relative_to(REPO_ROOT).with_suffix("").parts)
        for p in (REPO_ROOT / "engine" / "phase3").rglob("*.py")
    }
    registered = set(modules.keys())

    assert discovered == registered
    allowed_status = {"public_entrypoint", "active_core", "active_contract", "public_standalone", "validation_only"}
    for module_name, metadata in modules.items():
        assert metadata["status"] in allowed_status
        assert metadata["rationale"]


def test_frozen_hashes_unchanged_except_approved_boundary_fixes() -> None:
    assert "engine/phase3/decision_engine/model.py" in APPROVED_BOUNDARY_FIXES

    actual = {path: _sha(REPO_ROOT / path) for path in FROZEN_HASHES}
    assert actual == FROZEN_HASHES


def test_validation_path_is_deterministic() -> None:
    first = SystemValidationModel(REPO_ROOT).evaluate()
    second = SystemValidationModel(REPO_ROOT).evaluate()

    assert first.passed is True
    assert second.passed is True
    assert first.audit == second.audit
    assert first.replay.replay_hash == second.replay.replay_hash
