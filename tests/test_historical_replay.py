from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from engine.replay.replay_engine import run_replay_engine
from engine.replay.replay_report import render_replay_report
from engine.replay.replay_runner import ReplayLookaheadError, run_historical_replay
from engine.replay.snapshot_loader import (
    compute_snapshot_content_hash,
    load_historical_snapshots,
)


def _snapshot_payload(*, snapshot_id: str, snapshot_date: str, alpha: float, recommendation_signal: float) -> dict:
    payload = {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "content_hash": "",
        "company_fundamentals": {"symbol": "ABC", "revenue_growth": 0.12},
        "sec_filings": [{"filing_type": "10-Q", "filing_date": snapshot_date}],
        "macro_data": {"cpi": 3.1, "rates": 4.5},
        "valuation": {"signal": recommendation_signal, "realized_alpha": alpha},
        "analyst_estimates": {"eps_next_q": 1.23},
        "evidence": [{"evidence_id": f"E-{snapshot_id}", "date": snapshot_date, "detail": "news"}],
        "thesis_state": {"health_score": 65.0 + (alpha * 10.0), "status": "ACTIVE"},
        "portfolio_state": {
            "turnover": abs(recommendation_signal) * 0.2,
            "cash_weight": 0.10,
            "holdings_count": 8,
            "replacement_quality": 0.7,
        },
    }
    payload["content_hash"] = compute_snapshot_content_hash(payload)
    return payload


def _write_snapshot(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_dataset(root: Path) -> tuple[Path, tuple[dict, ...]]:
    snapshots_dir = root / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    snapshots = (
        _snapshot_payload(snapshot_id="S-002", snapshot_date="2026-01-02", alpha=0.02, recommendation_signal=0.30),
        _snapshot_payload(snapshot_id="S-001", snapshot_date="2026-01-01", alpha=0.01, recommendation_signal=0.10),
        _snapshot_payload(snapshot_id="S-003", snapshot_date="2026-01-03", alpha=-0.01, recommendation_signal=-0.30),
    )

    for payload in snapshots:
        _write_snapshot(snapshots_dir / f"{payload['snapshot_id']}.json", payload)

    return snapshots_dir, snapshots


def test_deterministic_snapshot_loading(tmp_path: Path) -> None:
    snapshots_dir, _ = _build_dataset(tmp_path)

    loaded = load_historical_snapshots(snapshots_dir)

    assert tuple(item.snapshot_id for item in loaded) == ("S-001", "S-002", "S-003")
    assert loaded[0].snapshot_date == "2026-01-01"
    assert loaded[0].content_hash == compute_snapshot_content_hash(loaded[0].to_dict())


def test_no_future_leakage_hard_fail(tmp_path: Path) -> None:
    snapshots_dir, snapshots = _build_dataset(tmp_path)
    broken = dict(snapshots[0])
    broken["evidence"] = [{"evidence_id": "E-future", "date": "2026-01-10", "detail": "future leak"}]
    broken["content_hash"] = compute_snapshot_content_hash(broken)
    _write_snapshot(snapshots_dir / "S-002.json", broken)

    with pytest.raises(ReplayLookaheadError):
        run_replay_engine(snapshot_root=snapshots_dir, output_root=tmp_path / "out", write_artifacts=True)


def test_byte_identical_replay_outputs(tmp_path: Path) -> None:
    snapshots_dir, _ = _build_dataset(tmp_path)
    output_root = tmp_path / "artifacts" / "replay"

    first = run_replay_engine(snapshot_root=snapshots_dir, output_root=output_root, write_artifacts=True)
    first_json = (output_root / "replay_result.json").read_bytes()
    first_timeline = (output_root / "replay_timeline.json").read_bytes()
    first_report = (output_root / "replay_report.md").read_bytes()
    first_manifest = (output_root / "replay_manifest.json").read_bytes()

    second = run_replay_engine(snapshot_root=snapshots_dir, output_root=output_root, write_artifacts=True)
    second_json = (output_root / "replay_result.json").read_bytes()
    second_timeline = (output_root / "replay_timeline.json").read_bytes()
    second_report = (output_root / "replay_report.md").read_bytes()
    second_manifest = (output_root / "replay_manifest.json").read_bytes()

    assert first.replay.content_hash == second.replay.content_hash
    assert first.replay.metrics.to_dict() == second.replay.metrics.to_dict()
    assert first_json == second_json
    assert first_timeline == second_timeline
    assert first_report == second_report
    assert first_manifest == second_manifest


def test_stable_replay_metrics(tmp_path: Path) -> None:
    snapshots_dir, _ = _build_dataset(tmp_path)
    loaded = load_historical_snapshots(snapshots_dir)

    result = run_historical_replay(snapshots=loaded, output_root=tmp_path / "out", write_artifacts=False)

    assert result.metrics.decision_stability == 0.0
    assert result.metrics.recommendation_changes == 2
    assert result.metrics.portfolio_turnover == pytest.approx(0.046667, abs=1e-6)
    assert result.metrics.max_drawdown == pytest.approx(0.01, abs=1e-6)
    assert len(result.metrics.alpha_over_time) == 3


def test_report_generation_sections(tmp_path: Path) -> None:
    snapshots_dir, _ = _build_dataset(tmp_path)
    result = run_replay_engine(snapshot_root=snapshots_dir, output_root=tmp_path / "out", write_artifacts=True)

    report_path = tmp_path / "out" / "replay_report.md"
    text = report_path.read_text(encoding="utf-8")

    assert "## Replay Summary" in text
    assert "## Timeline" in text
    assert "## Decision Timeline" in text
    assert "## Portfolio Timeline" in text
    assert "## Thesis Timeline" in text
    assert "## Performance Timeline" in text
    assert "## Failures" in text
    assert "## Successes" in text

    # renderer remains deterministic for identical result object
    assert render_replay_report(result.replay) == render_replay_report(result.replay)


def test_replay_integrity_manifest_hashes(tmp_path: Path) -> None:
    snapshots_dir, _ = _build_dataset(tmp_path)
    output_root = tmp_path / "out"
    run_replay_engine(snapshot_root=snapshots_dir, output_root=output_root, write_artifacts=True)

    manifest = json.loads((output_root / "replay_manifest.json").read_text(encoding="utf-8"))
    artifact_hashes = dict(manifest["artifact_hashes"])

    for filename, expected_hash in artifact_hashes.items():
        content = (output_root / filename).read_bytes()
        observed = sha256(content).hexdigest()
        assert observed == expected_hash
