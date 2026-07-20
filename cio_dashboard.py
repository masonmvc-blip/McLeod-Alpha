"""Read-only CIO dashboard data adapter.

This module only reads reporting artifacts. It has no broker, execution, email,
or portfolio-mutation imports so the dashboard cannot alter trading state.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


CHICAGO_TZ = ZoneInfo("America/Chicago")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _read_jsonl(path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []

    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            records.append(row)
    return records[-max(1, limit):]


def _latest_pipeline_summary(project_root: Path) -> dict[str, Any]:
    candidates = list((project_root / "artifacts" / "cio" / "runs").glob("*/pipeline_summary.json"))
    if not candidates:
        return {}
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    payload = _read_json(latest)
    if payload:
        payload = dict(payload)
        payload["run_directory"] = latest.parent.name
    return payload


def _archive_rows(report_root: Path, *, limit: int = 14) -> list[dict[str, Any]]:
    archive_root = report_root / "archive"
    if not archive_root.exists():
        return []

    rows: list[dict[str, Any]] = []
    for directory in sorted((path for path in archive_root.iterdir() if path.is_dir()), reverse=True):
        payload = _read_json(directory / "morning_cio_report.json")
        rows.append(
            {
                "report_date": payload.get("report_date") or directory.name,
                "subject": payload.get("subject") or "Morning CIO Report",
                "data_quality_score": int(payload.get("data_quality_score") or 0),
                "investment_grade": bool(payload.get("investment_grade")),
                "stale": bool(payload.get("stale")),
                "content_sha256": str(payload.get("content_sha256") or "")[:12],
            }
        )
    return rows[: max(1, limit)]


def build_cio_dashboard_payload(project_root: Path) -> dict[str, Any]:
    root = Path(project_root)
    report_root = root / "data" / "reports" / "morning_cio_email"
    report = _read_json(report_root / "latest_morning_cio_report.json")
    delivery_rows = _read_jsonl(report_root / "delivery_registry.jsonl")
    delivery_history = [
        {
            "report_date": row.get("report_date"),
            "event": row.get("event"),
            "status": row.get("status"),
            "transport": row.get("transport"),
            "subject": row.get("subject"),
            "logged_at": row.get("logged_at"),
            "content_sha256": str(row.get("content_sha256") or "")[:12],
        }
        for row in reversed(delivery_rows)
    ]

    pipeline = _latest_pipeline_summary(root)
    journal = _read_json(root / "artifacts" / "cio" / "decision_journal" / "index.json")
    evidence = _read_json(root / "artifacts" / "cio" / "evidence_ledger" / "index.json")
    actions = report.get("high_conviction_actions") if isinstance(report.get("high_conviction_actions"), list) else []

    report_available = bool(report)
    investment_grade = bool(report.get("investment_grade")) if report_available else False
    stale = bool(report.get("stale")) if report_available else True
    if not report_available:
        posture = "NO REPORT"
        posture_tone = "neutral"
    elif investment_grade and not stale:
        posture = "INVESTMENT GRADE"
        posture_tone = "positive"
    else:
        posture = "ACTION REQUIRED"
        posture_tone = "warning"

    return {
        "generated_at": datetime.now(tz=CHICAGO_TZ).isoformat(),
        "read_only": True,
        "report_available": report_available,
        "posture": posture,
        "posture_tone": posture_tone,
        "report": {
            "report_date": report.get("report_date"),
            "generated_at": report.get("generated_at"),
            "data_as_of": report.get("data_as_of"),
            "source_label": report.get("source_label"),
            "stale": stale,
            "stale_reason": report.get("stale_reason"),
            "subject": report.get("subject"),
            "data_quality_score": int(report.get("data_quality_score") or 0),
            "investment_grade": investment_grade,
            "news_status": report.get("news_status"),
            "account_display": report.get("account_display"),
            "account_type": report.get("account_type"),
            "content_sha256": str(report.get("content_sha256") or "")[:12],
            "sections": report.get("sections") if isinstance(report.get("sections"), list) else [],
            "html_url": "/cio/report/latest" if report_available else None,
        },
        "actions": actions[:8],
        "delivery": {
            "latest": delivery_history[0] if delivery_history else {},
            "history": delivery_history[:10],
            "schedule": "7:00 AM America/Chicago",
            "market_gate": "XNYS sessions only",
        },
        "advisory_pipeline": {
            "run_id": pipeline.get("run_id"),
            "as_of_date": pipeline.get("as_of_date"),
            "overall_status": pipeline.get("overall_status"),
            "stage_statuses": pipeline.get("stage_statuses") if isinstance(pipeline.get("stage_statuses"), list) else [],
            "first_blocker": pipeline.get("first_blocker"),
            "content_hash": str(pipeline.get("content_hash") or "")[:12],
        },
        "decision_journal": {
            "total_records": int(journal.get("total_records") or 0),
            "open_records": int(journal.get("open_records") or 0),
            "closed_records": int(journal.get("closed_records") or 0),
            "latest_as_of_date": journal.get("latest_as_of_date"),
            "records_by_action_type": journal.get("records_by_action_type") or {},
        },
        "evidence_ledger": {
            "total_evidence": int(evidence.get("total_evidence") or 0),
            "total_lineage": int(evidence.get("total_lineage") or 0),
            "evidence_by_symbol": evidence.get("evidence_by_symbol") or {},
        },
        "archives": _archive_rows(report_root),
    }
