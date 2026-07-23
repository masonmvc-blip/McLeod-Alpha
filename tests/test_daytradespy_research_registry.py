from __future__ import annotations

import json
from pathlib import Path

from tools import run_daytradespy_daily_ingestion
from tools.daytradespy_research_registry import (
    ANALYSIS_PROTOCOL_VERSION,
    GOVERNANCE_DECISION,
    bootstrap_governance,
    build_registry,
)


def test_registry_is_chronological_idempotent_and_research_only(tmp_path: Path) -> None:
    manifest = {
        "recordings": [
            {"post_id": 2, "recording_date": "2026-07-22T09:30:00", "title": "Later", "source_url": "https://example.test/2"},
            {"post_id": 1, "recording_date": "2026-07-21T09:30:00", "title": "Earlier", "source_url": "https://example.test/1"},
        ]
    }
    existing = {
        "recordings": [
            {
                "post_id": 1,
                "analysis_status": "complete",
                "analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION,
                "reviewed_at": "2026-07-22T12:00:00Z",
            }
        ]
    }
    registry = build_registry(manifest, existing)

    assert [record["post_id"] for record in registry["recordings"]] == [1, 2]
    assert registry["recordings"][0]["analysis_status"] == "complete"
    assert registry["recordings"][0]["reprocess_required"] is False
    assert registry["governance_decision"] == GOVERNANCE_DECISION

    artifacts = bootstrap_governance(tmp_path, manifest)
    registry_payload = json.loads(artifacts["recording_registry"].read_text())
    backlog = json.loads(artifacts["instrumentation_backlog"].read_text())
    assert registry_payload["recording_count"] == 2
    assert backlog["items"][0]["priority"] == "P0"
    assert backlog["items"][0]["production_change_authorized"] is False


def test_daily_ingestion_reports_research_only(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(run_daytradespy_daily_ingestion, "Path", lambda value: tmp_path)
    monkeypatch.setattr(
        run_daytradespy_daily_ingestion,
        "build_manifest",
        lambda existing: {"recording_count": 1, "recordings": [{"post_id": 1, "recording_date": "2026-07-22", "analysis_status": "pending"}]},
    )

    assert run_daytradespy_daily_ingestion.main() == 0
    assert "no live behavior changed" in capsys.readouterr().out