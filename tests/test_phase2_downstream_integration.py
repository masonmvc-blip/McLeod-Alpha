from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cio_email import morning_report
from engine.phase2_downstream import Phase2DownstreamAdapter, Phase2DownstreamSnapshot
from engine.phase2_research import PHASE2_LOCK_NAME, PHASE2_SCHEMA_VERSION, PHASE2_TICKER_REGISTRY
from engine.portfolio_engine import PortfolioEngine, RESEARCH_NEEDED


REPO_ROOT = Path(__file__).resolve().parent.parent
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


def _canonicalize(artifact: dict[str, object]) -> dict[str, object]:
    cleaned = json.loads(json.dumps(artifact))
    cleaned.pop("generated_at", None)
    return cleaned


def test_adapter_loads_validated_rklb_and_nbis_snapshots():
    adapter = Phase2DownstreamAdapter()
    rklb = adapter.load_ticker("RKLB")
    nbis = adapter.load_ticker("NBIS")

    for snapshot in (rklb, nbis):
        assert snapshot.available is True
        assert snapshot.schema_version == PHASE2_SCHEMA_VERSION
        assert snapshot.phase2_framework_locked is True
        assert snapshot.phase2_lock_name == PHASE2_LOCK_NAME
        assert snapshot.approved_for_eipv is False
        assert snapshot.informational_only is True
        assert snapshot.score_audit.get("passed") is True
        assert snapshot.generated_at
        assert len(snapshot.source_phase1_artifact_fingerprint) == 64

    assert rklb.overall_score["score"] == rklb.canonical_score["overall_score"]["score"]
    assert nbis.overall_score["score"] == nbis.canonical_score["overall_score"]["score"]
    assert rklb.confidence == rklb.canonical_score["overall_score"]["confidence"]
    assert nbis.confidence == nbis.canonical_score["overall_score"]["confidence"]
    assert 0.0 <= float(rklb.confidence) <= 100.0
    assert 0.0 <= float(nbis.confidence) <= 100.0


@pytest.mark.parametrize(
    "mutator, expected_reason",
    [
        (lambda artifact: artifact.__setitem__("generated_at", "2000-01-01T00:00:00+00:00"), "stale"),
        (lambda artifact: artifact.__setitem__("schema_version", "broken"), "Unsupported schema version"),
        (lambda artifact: artifact.__setitem__("ticker", "ZZZZ"), "Ticker mismatch"),
        (lambda artifact: artifact.__setitem__("score_audit", {"passed": False}), "score audit failed"),
    ],
)
def test_adapter_fails_closed_on_integrity_breaks(monkeypatch, tmp_path, mutator, expected_reason):
    outdir = tmp_path / "phase2" / "RKLB"
    outdir.mkdir(parents=True, exist_ok=True)
    artifact = json.loads(PHASE2_RKLB_ARTIFACT.read_text(encoding="utf-8"))
    review = PHASE2_RKLB_REVIEW.read_text(encoding="utf-8")
    mutator(artifact)
    (outdir / "RKLB_phase2_artifact.json").write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    (outdir / "RKLB_phase2_review.md").write_text(review, encoding="utf-8")

    monkeypatch.setitem(PHASE2_TICKER_REGISTRY["RKLB"], "output_dir", outdir)
    snapshot = Phase2DownstreamAdapter(max_artifact_age_hours=1).load_ticker("RKLB")

    assert snapshot.available is False
    assert expected_reason.lower() in snapshot.warning.lower()


def test_portfolio_engine_blocks_eipv_when_phase2_is_unapproved():
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
    engine.portfolio_data = {"account": {}, "metrics": {"total_market_value": 100000.0}}
    engine.summary_data = {}
    now = datetime.now(timezone.utc).isoformat()
    engine.research_data = {
        "AAA": {
            "business_quality": 84,
            "business_quality_confidence": 85,
            "business_quality_timestamp": now,
            "valuation": 76,
            "valuation_confidence": 82,
            "valuation_timestamp": now,
            "expected_return_assumptions": {
                "explicit_company_assumptions": True,
                "starting_metric": 100.0,
                "source_timestamps": {"growth": now, "margin": now},
            },
            "expected_alpha": 11,
            "expected_alpha_confidence": 84,
            "expected_alpha_confidence_label": "HIGH",
            "expected_alpha_timestamp": now,
            "expected_2yr_cagr": 14,
            "expected_2yr_cagr_confidence": 84,
            "expected_2yr_cagr_confidence_label": "HIGH",
            "expected_2yr_cagr_timestamp": now,
            "expected_10yr_cagr": 9,
            "expected_10yr_cagr_confidence": 84,
            "expected_10yr_cagr_confidence_label": "HIGH",
            "expected_10yr_cagr_timestamp": now,
        }
    }
    engine.phase2_context = {
        "AAA": Phase2DownstreamSnapshot(
            ticker="AAA",
            available=True,
            status="valid",
            approved_for_eipv=False,
            informational_only=True,
            canonical_score={
                "ticker": "AAA",
                "schema_version": PHASE2_SCHEMA_VERSION,
                "phase2_framework_locked": True,
                "phase2_lock_name": PHASE2_LOCK_NAME,
                "overall_score": {"score": 12.0, "confidence": 5.0, "missing_inputs": []},
                "component_scores": {},
                "confidence": 5.0,
                "missing_inputs": [],
                "provenance": {},
            },
            score_audit={"passed": True},
        )
    }
    engine.get_portfolio_metrics = lambda: {"total_portfolio_value": 100000.0}

    rankings = engine.calculate_eipv_rankings(1000.0)

    assert rankings == []
    assert engine.eipv_blocked
    assert "approved_for_eipv" in engine.eipv_blocked[0]["missing_assumptions"]


def test_morning_report_surfaces_phase2_context_and_low_confidence(monkeypatch, tmp_path):
    phase2_context = {
        "RKLB": Phase2DownstreamAdapter().load_ticker("RKLB"),
        "NBIS": Phase2DownstreamAdapter().load_ticker("NBIS"),
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

    bundle = morning_report._build_bundle(force=True, logger=morning_report._configure_logger("phase2-test"), previous_state={})
    text_body, html_body, payload, sections = morning_report.build_report(bundle)

    assert "Phase 2 Research" in text_body
    assert "informational-only" in text_body
    assert "confidence" in text_body.lower()
    assert "Phase 2 Research" in payload["sections"]
    assert any(section.title == "Phase 2 Research" for section in sections)
    assert "NBIS" in text_body
    assert "RKLB" in text_body
    assert html_body.startswith("<!DOCTYPE html>")


def test_morning_report_succeeds_without_phase2_artifacts(monkeypatch, tmp_path):
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

    bundle = morning_report._build_bundle(force=True, logger=morning_report._configure_logger("phase2-empty"), previous_state={})
    text_body, _, _, _ = morning_report.build_report(bundle)

    assert "Phase 2 Research" in text_body
    assert "No validated Phase 2 artifacts are available" in text_body
