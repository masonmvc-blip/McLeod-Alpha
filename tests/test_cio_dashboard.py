from __future__ import annotations

import json
from pathlib import Path

from cio_dashboard import build_cio_dashboard_payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dashboard_payload_combines_reporting_artifacts_without_writes(tmp_path):
    report_root = tmp_path / "data" / "reports" / "morning_cio_email"
    latest = report_root / "latest_morning_cio_report.json"
    _write_json(
        latest,
        {
            "report_date": "2026-07-20",
            "generated_at": "2026-07-20T07:00:00-05:00",
            "data_as_of": "2026-07-20T06:59:00-05:00",
            "source_label": "live_schwab",
            "stale": False,
            "subject": "McLeod Morning CIO Report | 2026-07-20 | ACTION REQUIRED",
            "data_quality_score": 72,
            "investment_grade": False,
            "news_status": "complete",
            "sections": ["Executive Summary", "High-Conviction Actions"],
            "high_conviction_actions": [{"summary": "Fix data", "detail": "Refresh research."}],
            "content_sha256": "abcdef1234567890",
        },
    )
    archive_json = report_root / "archive" / "2026-07-20" / "morning_cio_report.json"
    _write_json(archive_json, json.loads(latest.read_text(encoding="utf-8")))
    registry = report_root / "delivery_registry.jsonl"
    registry.write_text(
        json.dumps(
            {
                "report_date": "2026-07-20",
                "event": "send_succeeded",
                "status": "accepted",
                "transport": "smtp",
                "logged_at": "2026-07-20T07:00:03-05:00",
                "content_sha256": "abcdef1234567890",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "artifacts" / "cio" / "runs" / "CIO-ABC" / "pipeline_summary.json",
        {
            "run_id": "CIO-ABC",
            "as_of_date": "2026-07-20",
            "overall_status": "success",
            "stage_statuses": [{"stage": "decision_engine", "status": "completed", "blocker": ""}],
        },
    )
    _write_json(
        tmp_path / "artifacts" / "cio" / "decision_journal" / "index.json",
        {"total_records": 6, "open_records": 4, "closed_records": 2, "latest_as_of_date": "2026-07-20"},
    )
    _write_json(
        tmp_path / "artifacts" / "cio" / "evidence_ledger" / "index.json",
        {"total_evidence": 9, "total_lineage": 12},
    )
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()}

    payload = build_cio_dashboard_payload(tmp_path)

    after = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
    assert payload["read_only"] is True
    assert payload["posture"] == "ACTION REQUIRED"
    assert payload["report"]["data_quality_score"] == 72
    assert payload["report"]["html_url"] == "/cio/report/latest"
    assert payload["actions"][0]["summary"] == "Fix data"
    assert payload["delivery"]["latest"]["status"] == "accepted"
    assert payload["advisory_pipeline"]["run_id"] == "CIO-ABC"
    assert payload["decision_journal"]["total_records"] == 6
    assert payload["evidence_ledger"]["total_lineage"] == 12
    assert payload["archives"][0]["report_date"] == "2026-07-20"


def test_dashboard_payload_fails_closed_when_artifacts_are_missing(tmp_path):
    payload = build_cio_dashboard_payload(tmp_path)
    assert payload["report_available"] is False
    assert payload["posture"] == "NO REPORT"
    assert payload["report"]["stale"] is True
    assert payload["actions"] == []
    assert payload["delivery"]["history"] == []
    assert payload["archives"] == []


def test_dashboard_payload_ignores_malformed_registry_rows(tmp_path):
    report_root = tmp_path / "data" / "reports" / "morning_cio_email"
    report_root.mkdir(parents=True)
    (report_root / "delivery_registry.jsonl").write_text(
        "not-json\n" + json.dumps({"event": "send_failed", "status": "error"}) + "\n",
        encoding="utf-8",
    )
    payload = build_cio_dashboard_payload(tmp_path)
    assert len(payload["delivery"]["history"]) == 1
    assert payload["delivery"]["latest"]["event"] == "send_failed"
