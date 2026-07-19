from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.phase2_research import PHASE2_ONBOARDING_ALLOWLIST, PHASE2_SCHEMA_VERSION, PHASE2_TICKER_REGISTRY
from engine.research_os_release import (
    REQUIRED_RELEASE_SUITES,
    RESEARCH_OS_MANIFEST_PATH,
    ResearchOSReleaseError,
    ResearchOSReleaseValidationResult,
    load_research_os_manifest,
    release_summary,
    validate_research_os_release,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _suite_results() -> dict[str, bool]:
    return {suite_name: True for suite_name in REQUIRED_RELEASE_SUITES}


def test_research_os_v1_manifest_exists_and_is_consistent() -> None:
    manifest = load_research_os_manifest()
    result = validate_research_os_release(manifest, suite_results=_suite_results(), fail_closed=False)

    assert manifest["Research_OS_version"] == "1.0"
    assert result.passed is True
    assert result.manifest["Phase1_Framework_Locked"] is True
    assert result.manifest["Phase2_Framework_Locked"] is True
    assert result.manifest["Phase2_MultiCompany_Validated"] is True
    assert result.manifest["Phase2_Downstream_Integration_Validated"] is True
    assert result.manifest["Architecture_Frozen_PrePhase3"] is True
    assert result.manifest["schema_versions"]["phase2_canonical_score"] == PHASE2_SCHEMA_VERSION


def test_supported_company_registry_matches_configuration() -> None:
    manifest = load_research_os_manifest()
    result = validate_research_os_release(manifest, suite_results=_suite_results(), fail_closed=False)

    assert list(manifest["supported_companies"]) == list(PHASE2_TICKER_REGISTRY.keys())
    assert list(manifest["approved_phase2_companies"]) == list(PHASE2_ONBOARDING_ALLOWLIST)
    assert result.passed is True


def test_release_validator_detects_corrupted_manifests(tmp_path) -> None:
    manifest = load_research_os_manifest()
    manifest["Research_OS_version"] = "9.9"
    manifest_path = tmp_path / "research_os_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ResearchOSReleaseError):
        validate_research_os_release(load_research_os_manifest(manifest_path), suite_results=_suite_results())


def test_release_validator_detects_schema_mismatches(tmp_path) -> None:
    manifest = load_research_os_manifest()
    manifest["schema_versions"]["phase2_canonical_score"] = "broken"
    manifest_path = tmp_path / "research_os_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ResearchOSReleaseError):
        validate_research_os_release(load_research_os_manifest(manifest_path), suite_results=_suite_results())


def test_release_validator_detects_missing_lock_milestones(tmp_path) -> None:
    manifest = load_research_os_manifest()
    manifest["Phase2_Framework_Locked"] = False
    manifest_path = tmp_path / "research_os_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ResearchOSReleaseError):
        validate_research_os_release(load_research_os_manifest(manifest_path), suite_results=_suite_results())


def test_release_validator_detects_unsupported_companies(tmp_path) -> None:
    manifest = load_research_os_manifest()
    manifest["supported_companies"] = ["RKLB", "NBIS", "FAKE"]
    manifest_path = tmp_path / "research_os_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ResearchOSReleaseError):
        validate_research_os_release(load_research_os_manifest(manifest_path), suite_results=_suite_results())


def test_release_validator_is_deterministic() -> None:
    manifest = load_research_os_manifest()
    suite_results = _suite_results()

    first = validate_research_os_release(manifest, suite_results=suite_results, fail_closed=False)
    second = validate_research_os_release(manifest, suite_results=suite_results, fail_closed=False)

    assert isinstance(first, ResearchOSReleaseValidationResult)
    assert first == second
    assert release_summary(first) == release_summary(second)