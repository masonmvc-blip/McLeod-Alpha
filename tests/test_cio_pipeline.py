from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from engine.cio.pipeline import (
    CIOPipelineConflictError,
    CIOPipelineError,
    CIOPipelineValidationError,
    load_pipeline_inputs,
    run_cio_pipeline,
)
from tools.run_cio_pipeline import main as cli_main


def _payload(*, output_root: Path, journal_root: Path) -> dict:
    return {
        "decision_engine_inputs": {
            "date": "2026-07-19",
            "holdings": [
                {
                    "symbol": "AAPL",
                    "quantity": 120,
                    "market_value": 42000,
                    "sector": "Technology",
                    "thesis_health_score": 78,
                    "valuation_score": 72,
                    "conviction_score": 80,
                    "risk_score": 28,
                    "liquidity_score": 94,
                },
                {
                    "symbol": "MSFT",
                    "quantity": 80,
                    "market_value": 36000,
                    "sector": "Technology",
                    "thesis_health_score": 75,
                    "valuation_score": 68,
                    "conviction_score": 76,
                    "risk_score": 30,
                    "liquidity_score": 96,
                },
                {
                    "symbol": "XOM",
                    "quantity": 140,
                    "market_value": 25000,
                    "sector": "Energy",
                    "thesis_health_score": 41,
                    "valuation_score": 44,
                    "conviction_score": 37,
                    "risk_score": 74,
                    "liquidity_score": 70,
                },
            ],
            "cash_balance": 12000,
            "watchlist": [
                {
                    "symbol": "SNOW",
                    "thesis": "Strong revenue reacceleration",
                    "valuation_score": 84,
                    "conviction_score": 88,
                    "risk_score": 22,
                    "sector": "Software",
                },
                {
                    "symbol": "TSM",
                    "thesis": "Foundry leadership intact",
                    "valuation_score": 80,
                    "conviction_score": 83,
                    "risk_score": 27,
                    "sector": "Semiconductors",
                },
            ],
            "thesis_health_scores": {
                "AAPL": 78,
                "MSFT": 75,
                "XOM": 41,
                "SNOW": 82,
                "TSM": 76,
            },
            "valuation_scores": {
                "AAPL": 72,
                "MSFT": 68,
                "XOM": 44,
                "SNOW": 84,
                "TSM": 80,
            },
            "conviction_scores": {
                "AAPL": 80,
                "MSFT": 76,
                "XOM": 37,
                "SNOW": 88,
                "TSM": 83,
            },
            "risk_scores": {
                "AAPL": 28,
                "MSFT": 30,
                "XOM": 74,
                "SNOW": 22,
                "TSM": 27,
            },
            "recent_material_news": [
                {
                    "symbol": "XOM",
                    "headline": "Refining margins compress",
                    "summary": "Margins weakened on lower crack spreads.",
                    "impact": "negative",
                    "materiality_score": 78,
                    "source": "Reuters",
                    "published_at": "2026-07-19T08:15:00-05:00",
                },
                {
                    "symbol": "SNOW",
                    "headline": "Cloud spend normalization shows signs of reversal",
                    "summary": "Enterprise spend recovery appears to be broadening.",
                    "impact": "positive",
                    "materiality_score": 74,
                    "source": "Bloomberg",
                    "published_at": "2026-07-19T08:30:00-05:00",
                },
            ],
            "constraints": {
                "min_cash_weight": 0.10,
                "target_cash_weight": 0.15,
                "max_single_name_weight": 0.25,
                "max_sector_weight": 0.40,
                "max_portfolio_risk": 60.0,
                "min_diversification_score": 55.0,
                "min_liquidity_score": 50.0,
            },
        },
        "journal_root": str(journal_root),
        "portfolio_os_settings": {
            "max_position_size": 0.20,
            "min_position_size": 0.02,
            "max_cash_allocation": 0.25,
            "margin_settings": {
                "buying_power": 100000.0,
                "maintenance_requirement": 12000.0,
            },
        },
        "realized_outcomes": [],
        "output_root": str(output_root),
    }


def _write_input(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact_dir(inputs) -> Path:
    run_id = "CIO-" + inputs.input_hash[:16].upper()
    return inputs.output_root / "artifacts" / "cio" / "runs" / run_id


def test_valid_end_to_end_pipeline(tmp_path):
    input_path = tmp_path / "input.json"
    _write_input(input_path, _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal"))

    inputs = load_pipeline_inputs(input_path)
    result = run_cio_pipeline(inputs)

    assert result.overall_status == "success"
    assert result.run_id.startswith("CIO-")
    assert [status.stage for status in result.stage_statuses] == [
        "decision_engine",
        "decision_journal",
        "portfolio_os",
        "performance_lab",
    ]
    assert all(status.status == "completed" for status in result.stage_statuses)

    artifact_dir = _artifact_dir(inputs)
    expected = {
        "daily_cio_brief.md",
        "decision_records.json",
        "portfolio_plan.md",
        "performance_report.md",
        "pipeline_summary.json",
        "pipeline_manifest.json",
    }
    assert expected == {path.name for path in artifact_dir.iterdir() if path.is_file()}


def test_input_validation_failure(tmp_path):
    input_path = tmp_path / "bad_input.json"
    payload = _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal")
    payload.pop("decision_engine_inputs")
    _write_input(input_path, payload)

    with pytest.raises(CIOPipelineValidationError):
        load_pipeline_inputs(input_path)


def test_stage_ordering_and_downstream_suppression(tmp_path, monkeypatch):
    input_path = tmp_path / "input.json"
    _write_input(input_path, _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal"))
    inputs = load_pipeline_inputs(input_path)

    import engine.cio.pipeline as pipeline_mod

    order: list[str] = []

    original_decision_engine = pipeline_mod.DecisionEngine.generate
    original_journal = pipeline_mod.DecisionJournal.record_brief

    def wrapped_decision_engine(self, *args, **kwargs):
        order.append("decision_engine")
        return original_decision_engine(self, *args, **kwargs)

    def wrapped_journal(self, *args, **kwargs):
        order.append("decision_journal")
        return original_journal(self, *args, **kwargs)

    def fail_portfolio_os(self, *args, **kwargs):
        order.append("portfolio_os")
        raise RuntimeError("portfolio stage failed")

    monkeypatch.setattr(pipeline_mod.DecisionEngine, "generate", wrapped_decision_engine)
    monkeypatch.setattr(pipeline_mod.DecisionJournal, "record_brief", wrapped_journal)
    monkeypatch.setattr(pipeline_mod.PortfolioOS, "generate_plan", fail_portfolio_os)

    with pytest.raises(CIOPipelineError):
        run_cio_pipeline(inputs)

    assert order == ["decision_engine", "decision_journal", "portfolio_os"]


def test_deterministic_run_id_and_byte_stable_rerun(tmp_path):
    input_path = tmp_path / "input.json"
    _write_input(input_path, _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal"))

    first_inputs = load_pipeline_inputs(input_path)
    second_inputs = load_pipeline_inputs(input_path)

    assert first_inputs.input_hash == second_inputs.input_hash

    first_result = run_cio_pipeline(first_inputs)
    second_result = run_cio_pipeline(second_inputs)

    assert first_result.run_id == second_result.run_id
    assert first_result.content_hash == second_result.content_hash

    artifact_dir = _artifact_dir(first_inputs)
    first_manifest = (artifact_dir / "pipeline_manifest.json").read_bytes()
    second_manifest = (artifact_dir / "pipeline_manifest.json").read_bytes()
    assert first_manifest == second_manifest


def test_idempotent_identical_rerun(tmp_path):
    input_path = tmp_path / "input.json"
    _write_input(input_path, _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal"))
    inputs = load_pipeline_inputs(input_path)

    run_cio_pipeline(inputs)
    rerun = run_cio_pipeline(inputs)

    assert rerun.overall_status == "success"


def test_conflicting_artifact_detection(tmp_path):
    input_path = tmp_path / "input.json"
    _write_input(input_path, _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal"))
    inputs = load_pipeline_inputs(input_path)

    run_cio_pipeline(inputs)

    artifact_dir = _artifact_dir(inputs)
    (artifact_dir / "portfolio_plan.md").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(CIOPipelineConflictError):
        run_cio_pipeline(inputs)


def test_atomic_artifact_creation(tmp_path, monkeypatch):
    input_path = tmp_path / "input.json"
    _write_input(input_path, _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal"))
    inputs = load_pipeline_inputs(input_path)

    import engine.cio.pipeline as pipeline_mod

    calls: list[tuple[str, str]] = []
    original_replace = pipeline_mod.os.replace

    def tracking_replace(src, dst):
        calls.append((str(src), str(dst)))
        return original_replace(src, dst)

    monkeypatch.setattr(pipeline_mod.os, "replace", tracking_replace)
    run_cio_pipeline(inputs)

    # One atomic replacement per generated artifact file.
    assert len(calls) == 6


def test_manifest_hash_correctness(tmp_path):
    input_path = tmp_path / "input.json"
    _write_input(input_path, _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal"))
    inputs = load_pipeline_inputs(input_path)

    run_cio_pipeline(inputs)
    artifact_dir = _artifact_dir(inputs)
    manifest = json.loads((artifact_dir / "pipeline_manifest.json").read_text(encoding="utf-8"))

    assert manifest["input_hash"] == inputs.input_hash

    for name, expected_hash in manifest["output_hashes"].items():
        observed_hash = hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest()
        assert observed_hash == expected_hash


def test_cli_exit_codes_and_validate_only_no_writes(tmp_path, capsys):
    input_path = tmp_path / "input.json"
    payload = _payload(output_root=tmp_path / "out", journal_root=tmp_path / "journal")
    _write_input(input_path, payload)

    exit_code = cli_main(["--input", str(input_path), "--validate-only", "--print-summary"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "overall_status: validated" in output
    assert not (tmp_path / "out" / "artifacts" / "cio" / "runs").exists()

    bad_input = tmp_path / "bad_input.json"
    bad_payload = _payload(output_root=tmp_path / "out2", journal_root=tmp_path / "journal2")
    bad_payload.pop("journal_root")
    _write_input(bad_input, bad_payload)

    bad_exit_code = cli_main(["--input", str(bad_input), "--print-summary"])
    assert bad_exit_code == 2

    ok_exit_code = cli_main(["--input", str(input_path), "--print-summary"])
    assert ok_exit_code == 0

    # Conflict path
    inputs = load_pipeline_inputs(input_path)
    artifact_dir = _artifact_dir(inputs)
    (artifact_dir / "daily_cio_brief.md").write_text("tampered\n", encoding="utf-8")
    conflict_exit = cli_main(["--input", str(input_path), "--print-summary"])
    assert conflict_exit == 4
