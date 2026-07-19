from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from engine.phase2_research import (
    PHASE2_SCHEMA_VERSION,
    Phase2OnboardingError,
    Phase2ReadinessError,
    Phase2ResearchEngine,
    run_phase2,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE1_FACTS_PATH_RKLB = REPO_ROOT / "data" / "research" / "facts" / "RKLB_phase1_facts.json"
PHASE1_REVIEW_PATH_RKLB = REPO_ROOT / "data" / "research" / "review" / "RKLB_phase1_facts.md"
PHASE1_FACTS_PATH_NBIS = REPO_ROOT / "data" / "research" / "facts" / "NBIS_phase1_facts.json"
PHASE1_REVIEW_PATH_NBIS = REPO_ROOT / "data" / "research" / "review" / "NBIS_phase1_facts.md"


def _canonicalize(artifact: dict[str, object]) -> dict[str, object]:
    cleaned = json.loads(json.dumps(artifact))
    cleaned.pop("generated_at", None)
    return cleaned


def test_rklb_parity_locked_under_generic_runner(tmp_path):
    artifact = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH_RKLB,
        phase1_review_path=PHASE1_REVIEW_PATH_RKLB,
        output_dir=tmp_path / "rklb",
    ).score()
    canonical = artifact["canonical_score"]

    assert artifact["schema_version"] == PHASE2_SCHEMA_VERSION
    assert canonical["schema_version"] == PHASE2_SCHEMA_VERSION
    assert canonical["ticker"] == "RKLB"
    assert round(canonical["overall_score"]["score"], 2) == 47.36
    assert round(canonical["overall_score"]["confidence"], 2) == 78.41

    expected_components = {
        "business_quality": (24.86, 89.50),
        "competitive_moat": (19.87, 62.53),
        "management": (44.01, 81.67),
        "capital_allocation": (61.01, 93.60),
        "balance_sheet": (94.94, 94.00),
        "growth": (17.74, 75.93),
        "valuation": (67.77, 31.50),
    }
    for name, (score, confidence) in expected_components.items():
        component = canonical["component_scores"][name]
        assert round(component["score"], 2) == score
        assert round(component["confidence"], 2) == confidence

    gross_margin_provenance = canonical["component_scores"]["business_quality"]["submetrics"][0]["provenance"][0]
    assert gross_margin_provenance["field"] == "gross_margin"
    assert gross_margin_provenance["source_document_id"] == "CIK0001819994:companyfacts"
    assert canonical["overall_score"]["missing_inputs"] == ["backlog", "customer_concentration", "guidance", "market_cap", "price"]


def test_ticker_isolation_and_artifact_isolation(tmp_path):
    results = run_phase2(["RKLB", "NBIS"])

    assert set(results) == {"RKLB", "NBIS"}
    for ticker, artifact in results.items():
        canonical = artifact["canonical_score"]
        assert canonical["ticker"] == ticker
        assert canonical["source_phase1_fact_path"].endswith(f"{ticker}_phase1_facts.json")
        assert canonical["source_phase1_review_path"].endswith(f"{ticker}_phase1_facts.md")
        assert artifact["score_audit"]["passed"] is True


def test_unapproved_tickers_are_rejected():
    with pytest.raises(Phase2OnboardingError):
        Phase2ResearchEngine(ticker="SPCX").score()


def test_phase1_not_ready_tickers_are_rejected(tmp_path):
    facts_path = tmp_path / "fake_phase1_facts.json"
    review_path = tmp_path / "fake_phase1_review.md"
    facts_path.write_text(PHASE1_FACTS_PATH_RKLB.read_text(encoding="utf-8"), encoding="utf-8")
    review_path.write_text("# RKLB Phase 1 Facts\n- Phase 2 readiness: False\n", encoding="utf-8")

    with pytest.raises(Phase2ReadinessError):
        Phase2ResearchEngine(
            ticker="RKLB",
            phase1_fact_path=facts_path,
            phase1_review_path=review_path,
            output_dir=tmp_path / "out",
        ).score()


def test_identical_ticker_inputs_remain_deterministic(tmp_path):
    first = Phase2ResearchEngine(
        ticker="NBIS",
        output_dir=tmp_path / "first",
    ).score()
    second = Phase2ResearchEngine(
        ticker="NBIS",
        output_dir=tmp_path / "second",
    ).score()

    assert _canonicalize(first) == _canonicalize(second)


def test_multi_ticker_execution_matches_separate_single_runs(tmp_path):
    combined = run_phase2(["RKLB", "NBIS"])
    single_rklb = Phase2ResearchEngine(ticker="RKLB", output_dir=tmp_path / "single_rklb").score()
    single_nbis = Phase2ResearchEngine(ticker="NBIS", output_dir=tmp_path / "single_nbis").score()

    assert _canonicalize(combined["RKLB"]) == _canonicalize(single_rklb)
    assert _canonicalize(combined["NBIS"]) == _canonicalize(single_nbis)


def test_schema_version_present_and_validated(tmp_path):
    artifact = Phase2ResearchEngine(ticker="RKLB", output_dir=tmp_path / "schema").score()
    canonical = artifact["canonical_score"]

    assert artifact["schema_version"] == PHASE2_SCHEMA_VERSION
    assert canonical["schema_version"] == PHASE2_SCHEMA_VERSION
    assert canonical["phase2_framework_locked"] is True
    assert canonical["phase2_lock_name"] == "Phase2_Framework_Locked"


def test_no_ticker_specific_scoring_logic_exists_outside_config() -> None:
    source_path = Path(__import__("engine.phase2_research", fromlist=["__file__"]).__file__)
    source_text = source_path.read_text(encoding="utf-8")
    module = ast.parse(source_text)

    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_score_"):
            segment = ast.get_source_segment(source_text, node) or ""
            assert "RKLB" not in segment
            assert "NBIS" not in segment
            assert "ticker ==" not in segment
            assert "ticker in" not in segment


def test_no_raw_source_access_occurs(monkeypatch, tmp_path):
    touched: list[str] = []
    original_read_text = Path.read_text

    def spy_read_text(self: Path, *args, **kwargs):
        touched.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    Phase2ResearchEngine(ticker="RKLB", output_dir=tmp_path / "out").score()

    allowed = {
        str(PHASE1_FACTS_PATH_RKLB),
        str(PHASE1_REVIEW_PATH_RKLB),
    }
    assert set(touched) <= allowed
