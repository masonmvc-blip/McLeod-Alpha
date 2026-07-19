from __future__ import annotations

import ast
import json
from copy import deepcopy
from pathlib import Path

from engine.phase2_research import Phase2ResearchEngine, run_phase2_rklb


REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE1_FACTS_PATH = REPO_ROOT / "data" / "research" / "facts" / "RKLB_phase1_facts.json"
PHASE1_REVIEW_PATH = REPO_ROOT / "data" / "research" / "review" / "RKLB_phase1_facts.md"


def _canonicalize_artifact(artifact: dict[str, object]) -> dict[str, object]:
    cleaned = json.loads(json.dumps(artifact))
    cleaned.pop("generated_at", None)
    return cleaned


def _canonical_score(artifact: dict[str, object]) -> dict[str, object]:
    return artifact["canonical_score"]


def _write_reduced_phase1_fixture(tmp_path: Path, removed_field: str) -> tuple[Path, Path]:
    payload = json.loads(PHASE1_FACTS_PATH.read_text(encoding="utf-8"))
    payload["facts"] = [
        fact
        for fact in payload.get("facts", [])
        if str(fact.get("normalized_field") or fact.get("field") or "").lower() != removed_field.lower()
    ]
    facts_path = tmp_path / "RKLB_phase1_facts_reduced.json"
    review_path = tmp_path / "RKLB_phase1_facts_reduced.md"
    facts_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    review_path.write_text(PHASE1_REVIEW_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return facts_path, review_path


def test_phase2_consumes_only_phase1_artifacts(monkeypatch, tmp_path):
    allowed_reads: list[str] = []
    original_read_text = Path.read_text

    def spy_read_text(self: Path, *args, **kwargs):
        path_str = str(self)
        allowed_reads.append(path_str)
        assert path_str in {str(PHASE1_FACTS_PATH), str(PHASE1_REVIEW_PATH)}
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)

    output_dir = tmp_path / "phase2"
    artifact = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=output_dir,
    ).score()

    assert artifact["ticker"] == "RKLB"
    assert artifact["schema_version"] == "2026-07-18.phase2.v2"
    assert output_dir.joinpath("RKLB_phase2_artifact.json").exists()
    assert output_dir.joinpath("RKLB_phase2_review.md").exists()
    assert set(allowed_reads) == {str(PHASE1_FACTS_PATH), str(PHASE1_REVIEW_PATH)}


def test_missing_phase1_facts_reduce_confidence(tmp_path):
    full_output = tmp_path / "full"
    full_artifact = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=full_output,
    ).score()

    reduced_fact_path, reduced_review_path = _write_reduced_phase1_fixture(tmp_path, "free_cash_flow_margin")
    reduced_output = tmp_path / "reduced"
    reduced_artifact = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=reduced_fact_path,
        phase1_review_path=reduced_review_path,
        output_dir=reduced_output,
    ).score()

    reduced_score = _canonical_score(reduced_artifact)
    full_score = _canonical_score(full_artifact)
    assert reduced_score["component_scores"]["business_quality"]["confidence"] < full_score["component_scores"]["business_quality"]["confidence"]
    assert "free_cash_flow_margin" in reduced_score["component_scores"]["business_quality"]["missing_inputs"]


def test_phase2_is_deterministic_from_identical_inputs(tmp_path):
    first = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "first",
    ).score()
    second = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "second",
    ).score()

    assert _canonicalize_artifact(first) == _canonicalize_artifact(second)


def test_canonical_score_object_drives_artifacts_and_review(tmp_path):
    artifact = run_phase2_rklb(
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )

    canonical_score = _canonical_score(artifact)
    assert artifact["score_audit"]["passed"] is True
    assert artifact["score_audit"]["overall"]["match"] is True
    assert canonical_score["schema_version"] == "2026-07-18.phase2.v2"
    assert canonical_score["phase2_framework_locked"] is True
    assert canonical_score["overall_score"]["score"] == artifact["score_audit"]["overall"]["canonical"]
    assert canonical_score["overall_score"]["confidence"] == canonical_score["confidence"]
    assert canonical_score["weights"] == artifact["canonical_score"]["weights"]


def test_every_displayed_metric_has_provenance(tmp_path):
    artifact = run_phase2_rklb(
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )

    canonical_score = _canonical_score(artifact)

    for component in canonical_score["component_scores"].values():
        assert component["submetrics"]
        for metric in component["submetrics"]:
            if metric["provenance"]:
                provenance = metric["provenance"][0]
                assert provenance["fact_status"] == "verified"
                assert provenance["field"]
                assert provenance["source_document_id"]
                assert provenance["source_url"]
            else:
                assert metric["missing_inputs"]


def test_score_audit_matches_displayed_values(tmp_path):
    artifact = run_phase2_rklb(
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )

    score_audit = artifact["score_audit"]
    canonical_score = artifact["canonical_score"]

    assert score_audit["passed"] is True
    assert score_audit["overall"]["canonical"] == canonical_score["overall_score"]["score"]
    for component in canonical_score["component_scores"].values():
        label = component["label"]
        assert score_audit["components"][label]["canonical"] == component["score"]
        for metric in component["submetrics"]:
            assert score_audit["component_metrics"][label][metric["name"]]["canonical"] == metric["score"]


def test_review_formatting_does_not_change_scores(tmp_path):
    engine = Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=PHASE1_FACTS_PATH,
        phase1_review_path=PHASE1_REVIEW_PATH,
        output_dir=tmp_path / "phase2",
    )
    canonical_score = engine.build_canonical_score()
    before = deepcopy(canonical_score)
    review_text = engine.render_review(canonical_score)
    modified_review = review_text.replace("- Score:", "- Displayed Score:")

    assert canonical_score == before
    assert modified_review != review_text


def test_phase2_module_avoids_raw_source_imports() -> None:
    source_path = Path(__import__("engine.phase2_research", fromlist=["__file__"]).__file__)
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden = [name for name in imported_modules if name.startswith("requests") or name.startswith("engine.data_sources") or name.startswith("pandas")]
    assert not forbidden


def test_exactly_one_canonical_score_builder_exists() -> None:
    source_path = Path(__import__("engine.phase2_research", fromlist=["__file__"]).__file__)
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    builder_defs = [node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == "build_canonical_score"]
    assert len(builder_defs) == 1

    score_method = next(node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == "score")
    calls = [node for node in ast.walk(score_method) if isinstance(node, ast.Call)]
    call_names = []
    for call in calls:
        if isinstance(call.func, ast.Attribute):
            call_names.append(call.func.attr)
        elif isinstance(call.func, ast.Name):
            call_names.append(call.func.id)

    assert call_names.count("build_canonical_score") == 1
    assert "render_review" in call_names
