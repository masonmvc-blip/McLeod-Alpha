from __future__ import annotations

import ast
import json
from copy import deepcopy
from pathlib import Path

from engine.phase2_research import Phase2ResearchEngine, run_phase2_rklb


REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE1_FACTS_PATH = REPO_ROOT / "data" / "research" / "facts" / "RKLB_phase1_facts.json"
PHASE1_REVIEW_PATH = REPO_ROOT / "data" / "research" / "review" / "RKLB_phase1_facts.md"


def _module_tree() -> ast.Module:
    source_path = Path(__import__("engine.phase2_research", fromlist=["__file__"]).__file__)
    return ast.parse(source_path.read_text(encoding="utf-8"))


def _canonical_score(artifact: dict[str, object]) -> dict[str, object]:
    return artifact["canonical_score"]


def test_exactly_one_canonical_score_builder_exists() -> None:
    module = _module_tree()
    builders = [node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == "build_canonical_score"]
    assert len(builders) == 1


def test_every_artifact_consumes_canonical_score_object(tmp_path):
    engine = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )
    canonical_score = engine.build_canonical_score()
    canonical_before = deepcopy(canonical_score)
    review_text = engine.render_review(canonical_score)
    audit = engine._build_score_audit(canonical_score, review_text)

    assert canonical_score == canonical_before
    assert audit["passed"] is True
    assert audit["overall"]["canonical"] == canonical_score["overall_score"]["score"]
    assert canonical_score["schema_version"] == "2026-07-18.phase2.v2"
    assert canonical_score["phase2_framework_locked"] is True
    for component in canonical_score["component_scores"].values():
        component_label = component["label"]
        assert audit["components"][component_label]["canonical"] == component["score"]


def test_no_raw_scraping_occurs_inside_phase2(monkeypatch, tmp_path):
    touched: list[str] = []
    original_read_text = Path.read_text

    def spy_read_text(self: Path, *args, **kwargs):
        touched.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    artifact = run_phase2_rklb(
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )

    assert artifact["canonical_score"]["source_phase1_fact_path"] == str(PHASE1_FACTS_PATH)
    assert artifact["canonical_score"]["source_phase1_review_path"] == str(PHASE1_REVIEW_PATH)
    assert set(touched) <= {str(PHASE1_FACTS_PATH), str(PHASE1_REVIEW_PATH)}


def test_only_verified_phase1_facts_are_consumed(tmp_path):
    artifact = run_phase2_rklb(
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )
    canonical_score = _canonical_score(artifact)
    for component in canonical_score["component_scores"].values():
        for metric in component["submetrics"]:
            if metric["provenance"]:
                assert metric["provenance"][0]["fact_status"] == "verified"


def test_identical_phase1_inputs_always_produce_identical_phase2_outputs(tmp_path):
    first = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "first",
    ).build_canonical_score()
    second = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "second",
    ).build_canonical_score()

    assert first == second


def test_every_displayed_score_has_provenance(tmp_path):
    artifact = run_phase2_rklb(
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )
    audit = artifact["score_audit"]
    canonical_score = artifact["canonical_score"]

    assert audit["passed"] is True
    assert audit["overall"]["match"] is True
    for component in canonical_score["component_scores"].values():
        label = component["label"]
        for metric in component["submetrics"]:
            audit_entry = audit["component_metrics"][label][metric["name"]]
            assert audit_entry["match"] is True
            assert audit_entry["has_provenance"] is bool(metric["provenance"])


def test_confidence_decreases_when_verified_inputs_are_removed(tmp_path):
    full = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "full",
    ).build_canonical_score()

    reduced_payload = json.loads(PHASE1_FACTS_PATH.read_text(encoding="utf-8"))
    reduced_payload["facts"] = [
        fact
        for fact in reduced_payload.get("facts", [])
        if str(fact.get("normalized_field") or fact.get("field") or "").lower() != "free_cash_flow_margin"
    ]
    reduced_fact_path = tmp_path / "RKLB_phase1_reduced.json"
    reduced_review_path = tmp_path / "RKLB_phase1_reduced.md"
    reduced_fact_path.write_text(json.dumps(reduced_payload, indent=2) + "\n", encoding="utf-8")
    reduced_review_path.write_text(PHASE1_REVIEW_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    reduced = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=reduced_fact_path,
        phase1_review_path=reduced_review_path,
        output_dir=tmp_path / "reduced",
    ).build_canonical_score()

    assert reduced["component_scores"]["business_quality"]["confidence"] < full["component_scores"]["business_quality"]["confidence"]


def test_changing_artifact_formatting_cannot_change_scores(tmp_path):
    engine = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )
    canonical_score = engine.build_canonical_score()
    before = deepcopy(canonical_score)
    review_text = engine.render_review(canonical_score)
    _ = review_text.replace("- Score:", "- Displayed Score:").replace("|", "|")

    assert canonical_score == before


def test_schema_version_present_and_validated(tmp_path):
    artifact = run_phase2_rklb(
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )

    canonical_score = _canonical_score(artifact)
    assert artifact["schema_version"] == "2026-07-18.phase2.v2"
    assert canonical_score["schema_version"] == artifact["schema_version"]
    assert canonical_score["phase2_lock_name"] == "Phase2_Framework_Locked"
