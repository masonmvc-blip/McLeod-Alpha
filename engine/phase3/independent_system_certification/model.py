from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import ast
import json
import re
import subprocess
import tempfile
from typing import Any, Mapping

from engine.phase3.paper_portfolio_engine import PaperPortfolioEngine
from engine.phase3.paper_portfolio_governance import PaperPortfolioState, PaperRecommendationPolicy, PaperRecommendationStatus
from engine.phase3.paper_portfolio_governance.types import PaperRecommendationRecord
from engine.phase3.paper_portfolio_persistence import (
    HumanApprovalDecision,
    HumanApprovalRecord,
    HumanApprovalStatus,
    PaperPortfolioLedger,
    PaperPortfolioPersistenceModel,
    PaperPortfolioReplayModel,
    PaperPortfolioRepository,
)

from .types import CertificationResult


class IndependentCertificationError(ValueError):
    pass


class IndependentSystemCertificationModel:
    REQUIRED_MARKERS = (
        "data/research/logs/Research_OS_v1.0.json",
        "data/research/logs/Phase3_Foundation_Validated.json",
        "data/research/logs/ExpectedReturnEngine_Validated.json",
        "data/research/logs/DecisionEngine_Validated.json",
        "data/research/logs/CalibrationEngine_Validated.json",
        "data/research/logs/PortfolioSimulation_Validated.json",
        "data/research/logs/ShadowPortfolioConstruction_Validated.json",
        "data/research/logs/SystemValidation_Complete.json",
        "data/research/logs/SystemAudit_Complete.json",
        "data/research/logs/RepositoryHygiene_Validated.json",
        "data/research/logs/PaperPortfolioGovernance_Validated.json",
        "data/research/logs/PaperPortfolioEngine_Validated.json",
        "data/research/logs/PaperPortfolioPersistenceReplay_Validated.json",
        "data/research/logs/PaperPortfolioOperationsReadiness_Validated.json",
    )

    REQUIRED_REPORTS = (
        "reports/research_os_v1_release.md",
        "reports/system_validation_v1.md",
        "reports/technical_debt_audit_v1.md",
        "reports/repository_hygiene_remediation_v1.md",
        "reports/paper_portfolio_governance_v1.md",
        "reports/paper_portfolio_engine_v1.md",
        "reports/paper_portfolio_persistence_replay_v1.md",
        "reports/paper_portfolio_operations_readiness_v1.md",
        "reports/paper_portfolio_operations_runbook_v1.md",
    )

    REQUIRED_SUITES = (
        "tests/test_repository_hygiene_invariants.py",
        "tests/test_phase3_invariants.py",
        "tests/test_paper_portfolio_governance_invariants.py",
        "tests/test_paper_portfolio_engine_invariants.py",
        "tests/test_paper_portfolio_persistence_replay_invariants.py",
        "tests/test_paper_portfolio_operations_readiness_invariants.py",
        "tests/test_independent_verification_invariants.py",
        "tests/test_system_validation_invariants.py",
        "tests/test_research_os_release.py",
    )

    REQUIRED_PACKAGES = (
        "engine/phase3/expected_return",
        "engine/phase3/decision_engine",
        "engine/phase3/calibration",
        "engine/phase3/portfolio_simulation",
        "engine/phase3/shadow_portfolio_construction",
        "engine/phase3/system_validation",
        "engine/phase3/paper_portfolio_governance",
        "engine/phase3/paper_portfolio_engine",
        "engine/phase3/paper_portfolio_persistence",
        "engine/phase3/paper_portfolio_operations",
    )

    REQUIRED_LIFECYCLE_MODULE_PREFIXES = (
        "engine.phase3.expected_return",
        "engine.phase3.decision_engine",
        "engine.phase3.calibration",
        "engine.phase3.portfolio_simulation",
        "engine.phase3.shadow_portfolio_construction",
        "engine.phase3.system_validation",
        "engine.phase3.paper_portfolio_governance",
        "engine.phase3.paper_portfolio_engine",
        "engine.phase3.paper_portfolio_persistence",
        "engine.phase3.paper_portfolio_operations",
    )

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

    FORBIDDEN_IMPORT_PREFIXES = (
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
        "engine.phase2_research",
        "engine.phase2_downstream",
        "engine.research_phase1",
    )

    TARGET_MODULE_ROOTS = (
        "engine/phase3/paper_portfolio_governance",
        "engine/phase3/paper_portfolio_engine",
        "engine/phase3/paper_portfolio_persistence",
        "engine/phase3/paper_portfolio_operations",
    )

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)

    def certify(self, *, python_executable: str) -> CertificationResult:
        discrepancies: list[str] = []
        observations: list[str] = []
        risks: list[str] = []

        milestone_ok, markers = self._verify_markers()
        if not milestone_ok:
            discrepancies.append("MISSING_OR_INVALID_MILESTONE_MARKER")

        report_ok = self._verify_required_paths_exist(self.REQUIRED_REPORTS)
        if not report_ok:
            discrepancies.append("MISSING_REQUIRED_REPORT")

        suite_ok = self._verify_required_paths_exist(self.REQUIRED_SUITES)
        if not suite_ok:
            discrepancies.append("MISSING_REQUIRED_INVARIANT_SUITE")

        package_ok = self._verify_required_paths_exist(self.REQUIRED_PACKAGES)
        if not package_ok:
            discrepancies.append("MISSING_REQUIRED_PACKAGE")

        frozen_checks = self._recompute_frozen_hashes()
        if not all(frozen_checks.values()):
            discrepancies.append("FROZEN_HASH_MISMATCH")

        lifecycle_ok = self._recompute_lifecycle_registry()
        if not lifecycle_ok:
            discrepancies.append("LIFECYCLE_REGISTRY_MISMATCH")

        dependency_ok = self._recompute_dependency_graph()
        if not dependency_ok:
            discrepancies.append("DEPENDENCY_GRAPH_INVALID")

        isolation_ok = self._verify_package_isolation()
        if not isolation_ok:
            discrepancies.append("PACKAGE_ISOLATION_VIOLATION")

        report_refs_ok = self._verify_report_references_exist()
        if not report_refs_ok:
            discrepancies.append("BROKEN_REPORT_ARTIFACT_REFERENCE")

        marker_consistency_ok = self._verify_marker_validation_consistency(markers)
        if not marker_consistency_ok:
            discrepancies.append("MARKER_VALIDATION_INCONSISTENT")

        replay_ok = self._verify_deterministic_replay_from_clean_repository()
        if not replay_ok:
            discrepancies.append("DETERMINISTIC_REPLAY_FAILURE")

        suites_still_pass = self._verify_invariant_suites_pass(python_executable=python_executable)
        if not suites_still_pass:
            discrepancies.append("INVARIANT_SUITE_EXECUTION_FAILED")

        if not discrepancies:
            observations.append("All independently recomputed checks passed.")
        else:
            risks.append("Certification failed with blocking discrepancies.")

        return CertificationResult(
            passed=not discrepancies,
            verified_milestones=tuple(sorted(markers.keys())),
            checked_reports=tuple(self.REQUIRED_REPORTS),
            checked_suites=tuple(self.REQUIRED_SUITES),
            checked_packages=tuple(self.REQUIRED_PACKAGES),
            frozen_hash_checks=frozen_checks,
            dependency_graph_valid=dependency_ok,
            lifecycle_registry_valid=lifecycle_ok,
            package_isolation_valid=isolation_ok,
            report_references_valid=report_refs_ok,
            marker_validation_consistent=marker_consistency_ok,
            deterministic_replay_from_clean_repo=replay_ok,
            discrepancies=tuple(sorted(set(discrepancies))),
            unresolved_risks=tuple(sorted(set(risks))),
            observations=tuple(sorted(set(observations))),
        )

    def _verify_markers(self) -> tuple[bool, Mapping[str, Mapping[str, Any]]]:
        markers: dict[str, Mapping[str, Any]] = {}
        ok = True
        for rel_path in self.REQUIRED_MARKERS:
            path = self.repo_root / rel_path
            if not path.exists():
                ok = False
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                ok = False
                continue
            if not isinstance(payload, dict) or "milestone" not in payload or "recorded_at" not in payload:
                ok = False
                continue
            markers[payload["milestone"]] = payload
        return ok and len(markers) == len(self.REQUIRED_MARKERS), markers

    def _verify_required_paths_exist(self, relative_paths: tuple[str, ...]) -> bool:
        for rel_path in relative_paths:
            if not (self.repo_root / rel_path).exists():
                return False
        return True

    def _recompute_frozen_hashes(self) -> Mapping[str, bool]:
        results: dict[str, bool] = {}
        for rel_path, expected in self.FROZEN_HASHES.items():
            path = self.repo_root / rel_path
            if not path.exists():
                results[rel_path] = False
                continue
            actual = sha256(path.read_bytes()).hexdigest()
            results[rel_path] = actual == expected
        return dict(sorted(results.items()))

    def _recompute_lifecycle_registry(self) -> bool:
        registry_path = self.repo_root / "config/phase3_module_lifecycle.json"
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        registry_modules = set(data.get("modules", {}).keys())
        expected_modules: set[str] = set()
        phase3_root = self.repo_root / "engine" / "phase3"
        for py_file in phase3_root.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            rel = py_file.relative_to(self.repo_root).as_posix()
            module_name = rel[:-3].replace("/", ".")
            expected_modules.add(module_name)
        missing = [m for m in expected_modules if m.startswith("engine.phase3") and m not in registry_modules]
        if missing:
            return False
        for prefix in self.REQUIRED_LIFECYCLE_MODULE_PREFIXES:
            if not any(name.startswith(prefix) for name in registry_modules):
                return False
        return True

    def _recompute_dependency_graph(self) -> bool:
        module_to_deps: dict[str, set[str]] = {}
        phase3_root = self.repo_root / "engine" / "phase3"
        for py_file in phase3_root.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue
            rel = py_file.relative_to(self.repo_root).as_posix()
            module = rel[:-3].replace("/", ".")
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
            deps: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("engine.phase3"):
                            deps.add(alias.name)
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith("engine.phase3"):
                        deps.add(node.module)
            module_to_deps[module] = deps

        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(module: str) -> bool:
            if module in visited:
                return True
            if module in visiting:
                return False
            visiting.add(module)
            for dep in module_to_deps.get(module, set()):
                if dep in module_to_deps and not dfs(dep):
                    return False
            visiting.remove(module)
            visited.add(module)
            return True

        for module in sorted(module_to_deps):
            if not dfs(module):
                return False
        return True

    def _verify_package_isolation(self) -> bool:
        for root in self.TARGET_MODULE_ROOTS:
            package_path = self.repo_root / root
            for py_file in package_path.rglob("*.py"):
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                                return False
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if node.module.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                            return False
        return True

    def _verify_report_references_exist(self) -> bool:
        path_regex = re.compile(r"(?:data|reports|tests|engine|config|scripts)/[A-Za-z0-9_./\-]+")
        for rel_path in self.REQUIRED_REPORTS:
            text = (self.repo_root / rel_path).read_text(encoding="utf-8")
            references = set(path_regex.findall(text))
            for ref in references:
                normalized = ref.rstrip(".,:;)")
                full = self.repo_root / normalized
                if not full.exists():
                    return False
        return True

    def _verify_marker_validation_consistency(self, markers: Mapping[str, Mapping[str, Any]]) -> bool:
        if not markers:
            return False

        for payload in markers.values():
            validation = payload.get("validation_matrix")
            if validation is not None:
                if not isinstance(validation, dict):
                    return False
                failed = int(validation.get("failed", 0))
                total = int(validation.get("total_passed", validation.get("post_refresh_tests_passed", 1)))
                if failed != 0 or total <= 0:
                    return False

        marker_names = set(markers.keys())
        for name, payload in markers.items():
            for prereq in payload.get("prerequisite_milestones", []):
                if prereq in marker_names:
                    prereq_at = markers[prereq].get("recorded_at")
                    this_at = payload.get("recorded_at")
                    if prereq_at and this_at and prereq_at > this_at:
                        return False
        return True

    def _verify_deterministic_replay_from_clean_repository(self) -> bool:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "clean.sqlite"
            repo = PaperPortfolioRepository(db_path)
            ledger = PaperPortfolioLedger(repo)
            persistence = PaperPortfolioPersistenceModel(repo, ledger)
            replay = PaperPortfolioReplayModel(repo, ledger)
            try:
                base_policy = PaperRecommendationPolicy.default()
                policy = PaperRecommendationPolicy(
                    **{
                        **base_policy.__dict__,
                        "maximum_position_weight": 1.0,
                        "maximum_sector_weight": 1.0,
                        "maximum_portfolio_turnover": 1.0,
                        "minimum_cash_reserve": 0.0,
                        "shadow_allocation_requirements": ("WEIGHTS_RECONCILE",),
                        "required_approvals": ("risk",),
                    }
                )
                state = PaperPortfolioState(
                    as_of_timestamp="2026-07-18T23:58:00+00:00",
                    paper_cash=1000.0,
                    paper_holdings={"RKLB": 1000.0},
                    paper_weights={"RKLB": 0.5},
                    total_paper_value=2000.0,
                    provenance={"source": "independent_certification"},
                    version="1.0",
                )
                rec = PaperRecommendationRecord(
                    recommendation_id=sha256(b"cert-r1").hexdigest(),
                    ticker="RKLB",
                    recommendation_type="INCREASE_WEIGHT",
                    current_paper_weight=0.5,
                    proposed_paper_weight=0.7,
                    expected_return=0.12,
                    confidence_adjusted_return=0.10,
                    confidence=90.0,
                    decision_eligibility=True,
                    policy_status="passed",
                    blocking_reasons=(),
                    source_audit_references={"decision": "cert-decision"},
                    created_timestamp="2026-07-18T23:58:00+00:00",
                    expiration_timestamp="2026-07-21T23:58:00+00:00",
                    status=PaperRecommendationStatus.APPROVED_FOR_PAPER,
                )
                approval = HumanApprovalRecord(
                    approval_id=sha256(f"cert|{rec.recommendation_id}".encode("utf-8")).hexdigest(),
                    recommendation_id=rec.recommendation_id,
                    approver_identity="risk",
                    approval_decision=HumanApprovalDecision.APPROVE_FOR_PAPER,
                    approval_timestamp="2026-07-18T23:58:10+00:00",
                    approval_scope="single_recommendation",
                    policy_version="paper-governance-v1",
                    source_audit_reference="certification",
                    reason="manual",
                    expiration_timestamp="2026-07-21T23:58:10+00:00",
                    superseded_by_reference=None,
                    status=HumanApprovalStatus.ACTIVE,
                )
                engine_result = PaperPortfolioEngine().evaluate(
                    recommendation_records=(replace_status(rec, PaperRecommendationStatus.APPROVED_FOR_PAPER),),
                    paper_portfolio_state=state,
                    policy=policy,
                    historical_market_prices={"RKLB": {"2026-07-18T23:58:00+00:00": 100.0}},
                    benchmark_prices={"start": 100.0, "end": 101.0},
                    as_of_timestamp="2026-07-18T23:58:00+00:00",
                )

                persistence.persist_recommendation_lifecycle(
                    recommendation=replace_status(rec, PaperRecommendationStatus.DRAFT),
                    source_audit_references={"cert": "g1"},
                    provenance={"source": "certification"},
                    created_timestamp="2026-07-18T23:58:00+00:00",
                )
                persistence.persist_recommendation_lifecycle(
                    recommendation=replace_status(rec, PaperRecommendationStatus.PENDING_APPROVAL),
                    source_audit_references={"cert": "g1"},
                    provenance={"source": "certification"},
                    created_timestamp="2026-07-18T23:58:05+00:00",
                )
                persistence.persist_approval(
                    approval=approval,
                    source_audit_references={"cert": "g1"},
                    provenance={"source": "certification"},
                    created_timestamp="2026-07-18T23:58:10+00:00",
                )
                persistence.persist_recommendation_lifecycle(
                    recommendation=replace_status(rec, PaperRecommendationStatus.APPROVED_FOR_PAPER),
                    source_audit_references={"cert": "g1"},
                    provenance={"source": "certification"},
                    created_timestamp="2026-07-18T23:58:15+00:00",
                )
                persistence.persist_engine_result(
                    recommendations=(replace_status(rec, PaperRecommendationStatus.APPROVED_FOR_PAPER),),
                    engine_result=engine_result,
                    source_audit_references={"cert": "e1"},
                    provenance={"source": "certification"},
                    created_timestamp="2026-07-18T23:58:20+00:00",
                )
                replay.build_checkpoint(
                    created_timestamp="2026-07-18T23:58:25+00:00",
                    source_audit_references={"cert": "r1"},
                )
                first = replay.replay_from_event_zero()
                second = replay.replay_from_event_zero()
                if first != second:
                    return False
                return replay.validate_canonical_state().canonical_match
            finally:
                repo.close()

    def _verify_invariant_suites_pass(self, *, python_executable: str) -> bool:
        cmd = [python_executable, "-m", "pytest", *self.REQUIRED_SUITES, "-q"]
        proc = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            text=True,
            capture_output=True,
        )
        return proc.returncode == 0


def replace_status(record, status):
    payload = {**record.__dict__, "status": status}
    return record.__class__(**payload)
