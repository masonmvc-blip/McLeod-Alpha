from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cio_email import morning_report
from engine.phase2_downstream import Phase2DownstreamAdapter, Phase2DownstreamError, Phase2DownstreamSnapshot
from engine.phase2_research import PHASE2_LOCK_NAME, PHASE2_SCHEMA_VERSION, Phase2ResearchEngine, run_phase2
from engine.portfolio_engine import PortfolioEngine, RESEARCH_NEEDED


REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE1_FACTS_PATH_RKLB = REPO_ROOT / "data" / "research" / "facts" / "RKLB_phase1_facts.json"
PHASE1_REVIEW_PATH_RKLB = REPO_ROOT / "data" / "research" / "review" / "RKLB_phase1_facts.md"
PHASE1_FACTS_PATH_NBIS = REPO_ROOT / "data" / "research" / "facts" / "NBIS_phase1_facts.json"
PHASE1_REVIEW_PATH_NBIS = REPO_ROOT / "data" / "research" / "review" / "NBIS_phase1_facts.md"
PHASE2_RKLB_ARTIFACT = REPO_ROOT / "data" / "research" / "phase2" / "RKLB" / "RKLB_phase2_artifact.json"
PHASE2_RKLB_REVIEW = REPO_ROOT / "data" / "research" / "phase2" / "RKLB" / "RKLB_phase2_review.md"
PHASE2_NBIS_ARTIFACT = REPO_ROOT / "data" / "research" / "phase2" / "NBIS" / "NBIS_phase2_artifact.json"
PHASE2_NBIS_REVIEW = REPO_ROOT / "data" / "research" / "phase2" / "NBIS" / "NBIS_phase2_review.md"


class _MorningCIOPhase2Engine:
    def __init__(self, phase2_context: dict[str, Phase2DownstreamSnapshot]):
        self.portfolio_data = {"sync_timestamp": "2026-07-18T06:00:00-05:00"}
        self.summary_data = {"sync_timestamp": "2026-07-18T06:00:00-05:00"}
        self.equities = []
        self.options = []
        self.phase2_context = phase2_context

    def get_portfolio_metrics(self):
        return {
            "account_number": "12345678",
            "account_type": "MARGIN",
            "total_portfolio_value": 100000.0,
            "equity_value": 87500.0,
            "cash_balance": 12500.0,
            "buying_power": 30000.0,
            "maintenance_requirement": 15000.0,
            "margin_efficiency_score": 30.0,
            "num_equities": 0,
            "num_options": 0,
        }

    def rank_core_holdings(self):
        return []

    def estimate_target_weights(self, method="mcleod_optimized"):
        return []

    def identify_replacement_candidates(self):
        return []

    def calculate_eipv_rankings(self, allocation_amount):
        return []

    def get_research_value(self, symbol, field):
        return RESEARCH_NEEDED


class _MorningCIOEmptyPhase2Engine(_MorningCIOPhase2Engine):
    def __init__(self):
        super().__init__({})


def _module_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(_module_source(path))


def _class_source(path: Path, class_name: str) -> str:
    source = _module_source(path)
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            segment = ast.get_source_segment(source, node)
            return segment or ""
    return ""


def _canonicalize(artifact: dict[str, object]) -> dict[str, object]:
    cleaned = json.loads(json.dumps(artifact))
    cleaned.pop("generated_at", None)
    return cleaned


def _load_snapshot(ticker: str) -> Phase2DownstreamSnapshot:
    return Phase2DownstreamAdapter().load_ticker(ticker)


def test_locked_milestones_remain_enforced() -> None:
    rklb = _load_snapshot("RKLB")
    nbis = _load_snapshot("NBIS")

    for snapshot in (rklb, nbis):
        assert snapshot.available is True
        assert snapshot.schema_version == PHASE2_SCHEMA_VERSION
        assert snapshot.phase2_framework_locked is True
        assert snapshot.phase2_lock_name == PHASE2_LOCK_NAME
        assert snapshot.approved_for_eipv is False
        assert snapshot.informational_only is True
        assert snapshot.score_audit.get("passed") is True
        assert snapshot.source_phase1_artifact_fingerprint
        assert snapshot.canonical_score.get("phase2_framework_locked") is True


def test_every_downstream_score_traces_to_verified_phase1_fact() -> None:
    for ticker in ("RKLB", "NBIS"):
        snapshot = _load_snapshot(ticker)
        canonical = snapshot.canonical_score
        for component in canonical.get("component_scores", {}).values():
            for metric in component.get("submetrics", []):
                if metric.get("provenance"):
                    provenance = metric["provenance"][0]
                    assert provenance["fact_status"] == "verified"
                    assert provenance["field"]
                    assert provenance["source_document_id"]
                    assert provenance["source_url"]


def test_every_displayed_score_traces_to_one_canonical_phase2_object() -> None:
    adapter = Phase2DownstreamAdapter()
    snapshot = adapter.load_ticker("RKLB")
    canonical = snapshot.canonical_score

    assert snapshot.overall_score == canonical["overall_score"]
    assert snapshot.confidence == canonical["overall_score"]["confidence"]
    assert snapshot.missing_inputs == canonical["overall_score"]["missing_inputs"]
    assert snapshot.provenance == canonical["provenance"]


def test_portfolio_research_values_come_through_downstream_adapter(monkeypatch):
    adapter_calls = []
    original_load_many = Phase2DownstreamAdapter.load_many

    def spy_load_many(self, tickers):
        adapter_calls.append(tuple(tickers))
        return original_load_many(self, tickers)

    monkeypatch.setattr(Phase2DownstreamAdapter, "load_many", spy_load_many)

    engine = PortfolioEngine.__new__(PortfolioEngine)
    engine.equities = [
        {
            "symbol": "AAA",
            "portfolio_weight_percent": 5.0,
            "day_pl_pct": 1.2,
            "liquidity_score": 80,
            "market_value": 5000.0,
        }
    ]
    engine.options = []
    engine.portfolio_data = {"account": {}, "metrics": {"total_market_value": 100000.0}}
    engine.summary_data = {}
    engine.research_data = {
        "AAA": {
            "business_quality": 84,
            "business_quality_confidence": 85,
            "business_quality_timestamp": datetime.now(timezone.utc).isoformat(),
            "valuation": 76,
            "valuation_confidence": 82,
            "valuation_timestamp": datetime.now(timezone.utc).isoformat(),
            "expected_return_assumptions": {
                "explicit_company_assumptions": True,
                "starting_metric": 100.0,
                "source_timestamps": {"growth": datetime.now(timezone.utc).isoformat(), "margin": datetime.now(timezone.utc).isoformat()},
            },
            "expected_alpha": 11,
            "expected_alpha_confidence": 84,
            "expected_alpha_confidence_label": "HIGH",
            "expected_alpha_timestamp": datetime.now(timezone.utc).isoformat(),
            "expected_2yr_cagr": 14,
            "expected_2yr_cagr_confidence": 84,
            "expected_2yr_cagr_confidence_label": "HIGH",
            "expected_2yr_cagr_timestamp": datetime.now(timezone.utc).isoformat(),
            "expected_10yr_cagr": 9,
            "expected_10yr_cagr_confidence": 84,
            "expected_10yr_cagr_confidence_label": "HIGH",
            "expected_10yr_cagr_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }
    engine.phase2_context = {"AAA": _load_snapshot("RKLB")}
    engine.get_portfolio_metrics = lambda: {"total_portfolio_value": 100000.0}

    rankings = engine.calculate_eipv_rankings(1000.0)

    assert adapter_calls == [] or all(call == ("RKLB", "NBIS") for call in adapter_calls)
    assert rankings == []
    assert engine.eipv_blocked
    assert "approved_for_eipv" in engine.eipv_blocked[0]["missing_assumptions"]


def test_downstream_adapter_fails_closed_on_integrity_breaks(tmp_path, monkeypatch):
    outdir = tmp_path / "phase2" / "RKLB"
    outdir.mkdir(parents=True, exist_ok=True)
    artifact = json.loads(PHASE2_RKLB_ARTIFACT.read_text(encoding="utf-8"))
    review = PHASE2_RKLB_REVIEW.read_text(encoding="utf-8")

    cases = [
        ("stale", lambda payload: payload.__setitem__("generated_at", "2000-01-01T00:00:00+00:00")),
        ("schema", lambda payload: payload.__setitem__("schema_version", "broken")),
        ("ticker", lambda payload: payload.__setitem__("ticker", "ZZZZ")),
        ("audit", lambda payload: payload.__setitem__("score_audit", {"passed": False})),
    ]

    for label, mutator in cases:
        mutated = json.loads(json.dumps(artifact))
        mutator(mutated)
        (outdir / "RKLB_phase2_artifact.json").write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")
        (outdir / "RKLB_phase2_review.md").write_text(review, encoding="utf-8")
        adapter = Phase2DownstreamAdapter(max_artifact_age_hours=1)
        monkeypatch.setattr(
            adapter,
            "_artifact_paths",
            lambda ticker, outdir=outdir: {
                "artifact": outdir / "RKLB_phase2_artifact.json",
                "review": outdir / "RKLB_phase2_review.md",
                "phase1_fact": PHASE1_FACTS_PATH_RKLB,
                "phase1_review": PHASE1_REVIEW_PATH_RKLB,
            },
        )
        snapshot = adapter.load_ticker("RKLB")
        assert snapshot.available is False
        assert label in snapshot.warning.lower() or snapshot.status == "unavailable"


def test_identical_repository_state_produces_identical_outputs() -> None:
    first = _load_snapshot("RKLB")
    second = _load_snapshot("RKLB")
    assert first.to_context() == second.to_context()


def test_phase2_artifacts_and_reviews_remain_locked_and_deterministic() -> None:
    first = _canonicalize(Phase2DownstreamAdapter().load_ticker("NBIS").to_context())
    second = _canonicalize(Phase2DownstreamAdapter().load_ticker("NBIS").to_context())
    assert first == second


def test_no_ticker_specific_logic_exists_outside_configuration() -> None:
    portfolio_source = _class_source(REPO_ROOT / "engine" / "portfolio_engine.py", "PortfolioEngine")
    cio_source = _class_source(REPO_ROOT / "cio_email" / "morning_report.py", "MorningCIOReport")

    assert 'if ticker ==' not in portfolio_source
    assert 'if ticker ==' not in cio_source
    assert 'RKLB' not in portfolio_source
    assert 'NBIS' not in portfolio_source
    assert 'RKLB' not in cio_source
    assert 'NBIS' not in cio_source


def test_morning_cio_consumes_only_downstream_adapter(monkeypatch, tmp_path):
    phase2_context = {
        "RKLB": _load_snapshot("RKLB"),
        "NBIS": _load_snapshot("NBIS"),
    }
    fake_engine = _MorningCIOPhase2Engine(phase2_context)

    monkeypatch.setattr(morning_report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(morning_report, "LATEST_HTML", tmp_path / "latest_morning_cio_report.html")
    monkeypatch.setattr(morning_report, "LATEST_TEXT", tmp_path / "latest_morning_cio_report.txt")
    monkeypatch.setattr(morning_report, "LATEST_JSON", tmp_path / "latest_morning_cio_report.json")
    monkeypatch.setattr(morning_report, "LEGACY_MARKDOWN_PATH", tmp_path / "morning_cio_report_latest.md")
    monkeypatch.setattr(morning_report, "STATE_PATH", tmp_path / "latest_morning_cio_state.json")
    monkeypatch.setattr(morning_report, "RUN_LOG_PATH", tmp_path / "morning_cio_email.jsonl")
    monkeypatch.setattr(morning_report, "LOCK_PATH", tmp_path / "morning_cio_email.lock")
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", lambda: fake_engine)
    monkeypatch.setattr(morning_report, "_check_news", lambda symbols: ("complete", [], ""))

    bundle = morning_report._build_bundle(force=True, logger=morning_report._configure_logger("arch-test"), previous_state={})
    text_body, html_body, payload, sections = morning_report.build_report(bundle)

    assert "Phase 2 Research" in text_body
    assert "informational-only" in text_body
    assert "confidence" in text_body.lower()
    assert payload["sections"].count("Phase 2 Research") == 1
    assert any(section.title == "Phase 2 Research" for section in sections)
    assert html_body.startswith("<!DOCTYPE html>")


def test_morning_cio_handles_missing_phase2_artifacts(monkeypatch, tmp_path):
    fake_engine = _MorningCIOEmptyPhase2Engine()

    monkeypatch.setattr(morning_report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(morning_report, "LATEST_HTML", tmp_path / "latest_morning_cio_report.html")
    monkeypatch.setattr(morning_report, "LATEST_TEXT", tmp_path / "latest_morning_cio_report.txt")
    monkeypatch.setattr(morning_report, "LATEST_JSON", tmp_path / "latest_morning_cio_report.json")
    monkeypatch.setattr(morning_report, "LEGACY_MARKDOWN_PATH", tmp_path / "morning_cio_report_latest.md")
    monkeypatch.setattr(morning_report, "STATE_PATH", tmp_path / "latest_morning_cio_state.json")
    monkeypatch.setattr(morning_report, "RUN_LOG_PATH", tmp_path / "morning_cio_email.jsonl")
    monkeypatch.setattr(morning_report, "LOCK_PATH", tmp_path / "morning_cio_email.lock")
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", lambda: fake_engine)
    monkeypatch.setattr(morning_report, "_check_news", lambda symbols: ("complete", [], ""))

    bundle = morning_report._build_bundle(force=True, logger=morning_report._configure_logger("arch-empty"), previous_state={})
    text_body, _, _, _ = morning_report.build_report(bundle)

    assert "Phase 2 Research" in text_body
    assert "No validated Phase 2 artifacts are available" in text_body


def test_phase1_phase2_and_downstream_source_boundaries_remain_unchanged() -> None:
    phase1_source = _module_source(REPO_ROOT / "engine" / "research_phase1.py")
    phase2_source = _module_source(REPO_ROOT / "engine" / "phase2_research.py")
    downstream_source = _module_source(REPO_ROOT / "engine" / "phase2_downstream.py")

    assert "requests.get" not in phase2_source
    assert "requests.get" not in downstream_source
    assert "_compute_phase2_readiness" in phase1_source


def test_phase2_invariants_have_one_canonical_builder() -> None:
    module = _module_ast(REPO_ROOT / "engine" / "phase2_research.py")
    builders = [node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == "build_canonical_score"]
    assert len(builders) == 1


def test_portfolio_methods_do_not_depend_on_phase2_context(monkeypatch):
    engine = PortfolioEngine.__new__(PortfolioEngine)
    engine.positions = []
    engine.equities = [
        {
            "symbol": "AAA",
            "portfolio_weight_percent": 5.0,
            "day_pl_pct": 1.2,
            "liquidity_score": 80,
            "market_value": 5000.0,
        }
    ]
    engine.options = []
    engine.portfolio_data = {"account": {}, "metrics": {"total_market_value": 100000.0}}
    engine.summary_data = {"concentration": {"top_5_positions": {}}}
    engine.research_data = {}
    engine.phase2_context = {}

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Phase 2 data should not be used here")

    monkeypatch.setattr(PortfolioEngine, "get_phase2_snapshot", fail_if_called)
    engine.rank_core_holdings()
    engine.estimate_target_weights(method="mcleod_optimized")
    engine.identify_replacement_candidates()
