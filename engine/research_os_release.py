from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from engine import phase2_downstream, phase2_research


WORKSPACE = Path(__file__).resolve().parent.parent
RESEARCH_OS_MANIFEST_PATH = WORKSPACE / "config" / "research_os_manifest.json"
PHASE1_LOCK_MILESTONE_PATH = WORKSPACE / "data" / "research" / "logs" / "Phase1_Framework_Locked.json"
RESEARCH_OS_MILESTONE_PATH = WORKSPACE / "data" / "research" / "logs" / "Research_OS_v1.0.json"
REQUIRED_RELEASE_SUITES = (
    "Phase 1 framework invariants",
    "Phase 1 regression suite",
    "Phase 2 framework invariants",
    "Phase 2 regression suite",
    "Phase 2 multi-company suite",
    "Phase 2 downstream integration suite",
    "Architecture invariant suite",
    "Release invariant suite",
    "Portfolio engine tests",
    "EIPV tests",
    "Morning CIO tests",
    "IBD integration tests",
)


class ResearchOSReleaseError(ValueError):
    pass


@dataclass(frozen=True)
class ResearchOSReleaseValidationResult:
    passed: bool
    errors: tuple[str, ...]
    manifest: dict[str, Any]
    suite_results: dict[str, bool]


def load_research_os_manifest(path: Path = RESEARCH_OS_MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _phase2_module_source() -> str:
    return Path(phase2_research.__file__).read_text(encoding="utf-8")


def _canonical_build_count() -> int:
    module = ast.parse(_phase2_module_source())
    return sum(1 for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == "build_canonical_score")


def _company_registry_is_valid(manifest: Mapping[str, Any]) -> bool:
    supported = list(manifest.get("supported_companies", []))
    approved = list(manifest.get("approved_phase2_companies", []))
    registry_keys = list(phase2_research.PHASE2_TICKER_REGISTRY.keys())
    return supported == registry_keys and approved == list(phase2_research.PHASE2_ONBOARDING_ALLOWLIST)


def _check_manifest_structure(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    if str(manifest.get("Research_OS_version", "")) != "1.0":
        errors.append("Research_OS_version must be 1.0.")

    required_milestones = [
        "Phase1_Framework_Locked",
        "Phase2_Framework_Locked",
        "Phase2_MultiCompany_Validated",
        "Phase2_Downstream_Integration_Validated",
        "Architecture_Frozen_PrePhase3",
    ]
    for milestone in required_milestones:
        if manifest.get(milestone) is not True:
            errors.append(f"Required release milestone is not enabled: {milestone}.")

    schema_versions = manifest.get("schema_versions", {})
    if not isinstance(schema_versions, dict):
        errors.append("schema_versions must be a mapping.")
    else:
        if schema_versions.get("phase2_canonical_score") != phase2_research.PHASE2_SCHEMA_VERSION:
            errors.append("Phase 2 schema version does not match the configured canonical score schema.")
        if schema_versions.get("phase2_lock_name") != phase2_research.PHASE2_LOCK_NAME:
            errors.append("Phase 2 lock name does not match the configured lock.")

    artifact_versions = manifest.get("artifact_versions", {})
    if not isinstance(artifact_versions, dict):
        errors.append("artifact_versions must be a mapping.")
    else:
        if artifact_versions.get("phase2_artifact") != phase2_research.PHASE2_SCHEMA_VERSION:
            errors.append("Phase 2 artifact version does not match the configured schema version.")
        if artifact_versions.get("research_os_release_report") != "Research_OS_v1.0":
            errors.append("Research OS release report version is inconsistent.")

    if not isinstance(manifest.get("compatibility_rules", []), list) or not manifest.get("compatibility_rules"):
        errors.append("compatibility_rules must be a non-empty list.")

    if not _company_registry_is_valid(manifest):
        errors.append("Supported company registry does not match the configured Phase 2 registry.")

    if list(manifest.get("supported_companies", [])) != list(dict.fromkeys(manifest.get("supported_companies", []))):
        errors.append("supported_companies contains duplicates.")

    if list(manifest.get("approved_phase2_companies", [])) != list(dict.fromkeys(manifest.get("approved_phase2_companies", []))):
        errors.append("approved_phase2_companies contains duplicates.")

    if set(manifest.get("approved_phase2_companies", [])) - set(manifest.get("supported_companies", [])):
        errors.append("approved_phase2_companies must be a subset of supported_companies.")

    return errors


def validate_research_os_release(
    manifest: Optional[Mapping[str, Any]] = None,
    *,
    suite_results: Optional[Mapping[str, bool]] = None,
    manifest_path: Path = RESEARCH_OS_MANIFEST_PATH,
    milestone_path: Path = RESEARCH_OS_MILESTONE_PATH,
    fail_closed: bool = True,
) -> ResearchOSReleaseValidationResult:
    errors: list[str] = []
    loaded_manifest = dict(manifest) if manifest is not None else load_research_os_manifest(manifest_path)

    errors.extend(_check_manifest_structure(loaded_manifest))

    if not PHASE1_LOCK_MILESTONE_PATH.exists():
        errors.append("Phase 1 lock milestone record is missing.")
    if not milestone_path.exists():
        errors.append("Research_OS_v1.0 milestone record is missing.")

    if not hasattr(phase2_downstream, "Phase2DownstreamAdapter"):
        errors.append("Phase 2 downstream adapter is missing.")

    if _canonical_build_count() != 1:
        errors.append("Phase 2 canonical score builder count is invalid.")

    suite_map = dict(suite_results or {})
    for suite_name in REQUIRED_RELEASE_SUITES:
        if suite_map.get(suite_name) is not True:
            errors.append(f"Required suite did not pass: {suite_name}.")

    adapter = phase2_downstream.Phase2DownstreamAdapter()
    for ticker in phase2_research.PHASE2_ONBOARDING_ALLOWLIST:
        try:
            snapshot = adapter.load_ticker(ticker)
        except Exception as exc:  # pragma: no cover - fail closed path
            errors.append(f"Unable to load validated Phase 2 snapshot for {ticker}: {exc}.")
            continue
        if snapshot.available is not True:
            errors.append(f"Validated Phase 2 snapshot is unavailable for {ticker}.")
        if snapshot.schema_version != phase2_research.PHASE2_SCHEMA_VERSION:
            errors.append(f"Validated Phase 2 snapshot schema mismatch for {ticker}.")
        if snapshot.phase2_framework_locked is not True:
            errors.append(f"Validated Phase 2 snapshot is not framework locked for {ticker}.")
        if snapshot.approved_for_eipv is not False or snapshot.informational_only is not True:
            errors.append(f"Approval gate is not disabled for {ticker}.")

    passed = not errors
    result = ResearchOSReleaseValidationResult(
        passed=passed,
        errors=tuple(errors),
        manifest=loaded_manifest,
        suite_results=dict(suite_map),
    )
    if fail_closed and not passed:
        raise ResearchOSReleaseError("Research_OS_v1.0 validation failed: " + "; ".join(errors))
    return result


def release_summary(result: ResearchOSReleaseValidationResult) -> dict[str, Any]:
    manifest = result.manifest
    return {
        "Research_OS_version": manifest.get("Research_OS_version"),
        "passed": result.passed,
        "error_count": len(result.errors),
        "suite_count": len(result.suite_results),
        "supported_companies": list(manifest.get("supported_companies", [])),
        "approved_phase2_companies": list(manifest.get("approved_phase2_companies", [])),
        "schema_versions": dict(manifest.get("schema_versions", {})),
        "artifact_versions": dict(manifest.get("artifact_versions", {})),
    }