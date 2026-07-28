#!/usr/bin/env python3
"""Generate a source-of-truth DayTradeSPY corpus coverage report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .daytradespy_record_processor import validate_record
else:
    from daytradespy_record_processor import validate_record


YEARS = {"2023", "2024", "2025"}
TERMINAL_STATUSES = {"COMPLETE", "PERMANENTLY_UNAVAILABLE"}
PENDING_STATUS = "PENDING_AUTHORIZED_ACCESS"
QUALITY_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0}


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _session(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    post_id = int(item["post_id"])
    transcript = item.get("transcript") or {}
    raw_record_path = str(item.get("machine_record_path") or "").strip()
    record_path = Path(raw_record_path) if raw_record_path else None
    if record_path is not None and not record_path.is_absolute():
        record_path = root.parent.parent.parent / record_path
    record = _read(record_path, None) if record_path is not None and record_path.exists() else None
    validation = "NOT_PROCESSED"
    if isinstance(record, dict):
        try:
            validate_record(record)
            validation = "VALIDATED"
        except ValueError as exc:
            validation = f"INVALID: {exc}"
    transcript_pct = int(transcript.get("completeness_pct") or 0)
    analysis_status = str(item.get("analysis_status") or "pending")
    visual_review = (record or {}).get("recording", {}).get("visual_review", {})
    visual_complete = int(visual_review.get("coverage_pct") or 0) == 100
    bundle_path = Path(str(item.get("output_bundle_path") or ""))
    if bundle_path and not bundle_path.is_absolute():
        bundle_path = root.parent.parent.parent / bundle_path
    bundle_complete = bundle_path.is_dir() and any(bundle_path.iterdir())
    complete = (
        analysis_status == "complete" and transcript_pct == 100 and visual_complete
        and validation == "VALIDATED" and bundle_complete
    )
    documented_unavailable = str(item.get("acquisition_terminal_status") or "") == "PERMANENTLY_UNAVAILABLE"
    if complete:
        corpus_status = "COMPLETE"
    elif documented_unavailable:
        corpus_status = "PERMANENTLY_UNAVAILABLE"
    else:
        corpus_status = PENDING_STATUS
    return {
        "post_id": post_id,
        "recording_date": str(item.get("recording_date") or ""),
        "title": str(item.get("title") or ""),
        "source_url": str(item.get("source_url") or ""),
        "expected": True,
        "corpus_status": corpus_status,
        "analysis_status": analysis_status,
        "processing_status": "COMPLETE" if complete else ("PROCESSED_COVERAGE_INCOMPLETE" if isinstance(record, dict) else "PENDING_ACQUISITION"),
        "transcript_availability": str(transcript.get("availability") or "pending"),
        "transcript_completeness_pct": transcript_pct,
        "transcript_quality_tier": (item.get("evidence_quality") or {}).get("tier", "UNAVAILABLE"),
        "visual_review_status": visual_review.get("status", PENDING_STATUS),
        "validation_status": validation,
        "record_path": str(record_path) if isinstance(record, dict) else None,
        "recoverable_action": None if corpus_status in TERMINAL_STATUSES else "Import an authorized full VTT and complete timestamped visual review; then process and validate the record.",
    }


def build_report(root: Path) -> dict[str, Any]:
    registry = _read(root / "recording_registry.json", {"recordings": []})
    schema_lock = _read(root / "schema_lock.json", {})
    sessions = [_session(root, item) for item in registry.get("recordings", []) if str(item.get("recording_date") or "")[:4] in YEARS]
    sessions.sort(key=lambda item: (item["recording_date"], item["post_id"]))
    counts = Counter(session["recording_date"][:4] for session in sessions)
    complete = [session for session in sessions if session["corpus_status"] == "COMPLETE"]
    pending = [session for session in sessions if session["corpus_status"] == PENDING_STATUS]
    unavailable = [session for session in sessions if session["corpus_status"] == "PERMANENTLY_UNAVAILABLE"]
    validated = [session for session in sessions if session["validation_status"] == "VALIDATED"]
    validation_failures = [session for session in sessions if session["validation_status"].startswith("INVALID:")]
    today = datetime.now(timezone.utc).date().isoformat()
    new_complete_today = sum(
        session["corpus_status"] == "COMPLETE" and str(next(
            (item.get("reviewed_at") for item in registry.get("recordings", []) if int(item.get("post_id") or 0) == session["post_id"]), ""
        ) or "").startswith(today)
        for session in sessions
    )
    quality_values = [QUALITY_POINTS[session["transcript_quality_tier"]] for session in validated if session["transcript_quality_tier"] in QUALITY_POINTS]
    average_quality = round(sum(quality_values) / len(quality_values), 2) if quality_values else None
    coverage_pct = round((len(complete) + len(unavailable)) / len(sessions) * 100, 2) if sessions else 0.0
    locked_protocol = str(schema_lock.get("analysis_protocol_version") or "")
    active_protocol = str(registry.get("analysis_protocol_version") or "")
    if coverage_pct < 95 and locked_protocol and locked_protocol != active_protocol:
        raise ValueError(f"Research schema is locked at {locked_protocol}; active protocol is {active_protocol}")
    return {
        "schema_version": "daytradespy-coverage-report.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"years": sorted(YEARS), "source": "refreshed public archive manifest and local research registry"},
        "schema_lock": {
            "active_protocol_version": active_protocol,
            "locked_protocol_version": locked_protocol,
            "locked": coverage_pct < 95,
            "unlock_threshold_coverage_pct": 95,
        },
        "summary": {
            "expected_sessions": len(sessions),
            "expected_sessions_by_year": dict(sorted(counts.items())),
            "complete_sessions": len(complete),
            "pending_authorized_access": len(pending),
            "permanently_unavailable": len(unavailable),
            "coverage_pct": coverage_pct,
            "new_sessions_completed_today": new_complete_today,
            "validation_failures": len(validation_failures),
            "average_evidence_quality_score": average_quality,
            "average_evidence_quality_band": next((tier for tier, points in QUALITY_POINTS.items() if average_quality is not None and average_quality >= points), "UNAVAILABLE"),
            "validated_records": len(validated),
            "corpus_complete": len(sessions) == len(complete) + len(unavailable),
        },
        "sessions": sessions,
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DayTradeSPY Corpus Coverage: 2023-2025", "",
        f"Generated: {report['generated_at']}", "",
        "## Summary", "",
        f"- Expected sessions: {summary['expected_sessions']}",
        f"- Complete sessions: {summary['complete_sessions']}",
        f"- Pending authorized access: {summary['pending_authorized_access']}",
        f"- Permanently unavailable: {summary['permanently_unavailable']}",
        f"- Coverage: {summary['coverage_pct']}%",
        f"- New sessions completed today: {summary['new_sessions_completed_today']}",
        f"- Validation failures: {summary['validation_failures']}",
        f"- Average evidence quality: {summary['average_evidence_quality_band']} ({summary['average_evidence_quality_score']})",
        f"- Validated records: {summary['validated_records']}",
        f"- Corpus complete: {summary['corpus_complete']}",
        "",
        "## By Year", "",
        "| Year | Expected | Complete | Pending Access | Permanently Unavailable | Validated |", "|---:|---:|---:|---:|---:|---:|",
    ]
    for year, expected in summary["expected_sessions_by_year"].items():
        sessions = [item for item in report["sessions"] if item["recording_date"].startswith(year)]
        lines.append(
            f"| {year} | {expected} | {sum(item['corpus_status'] == 'COMPLETE' for item in sessions)} | "
            f"{sum(item['corpus_status'] == PENDING_STATUS for item in sessions)} | "
            f"{sum(item['corpus_status'] == 'PERMANENTLY_UNAVAILABLE' for item in sessions)} | {sum(item['validation_status'] == 'VALIDATED' for item in sessions)} |"
        )
    lines.extend(["", "## Acquired But Incomplete", "", "| Date | Post ID | Transcript Quality | Processing | Validation |", "|---|---:|---|---|---|"])
    for item in report["sessions"]:
        if item["processing_status"] == "PROCESSED_COVERAGE_INCOMPLETE":
            lines.append(f"| {item['recording_date'][:10]} | {item['post_id']} | {item['transcript_completeness_pct']}% / Tier {item['transcript_quality_tier']} | {item['processing_status']} | {item['validation_status']} |")
    lines.extend([
        "", "## Missing Session Register", "",
        "The machine-readable JSON companion contains every pending session with its public source URL and recovery action. "
        "A session may be PERMANENTLY_UNAVAILABLE only after all authorized acquisition paths are exhausted and documented in the registry.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/research/daytradespy"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = args.output_dir or root
    output_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(root)
    json_path = output_dir / "coverage_report_2023_2025.json"
    markdown_path = output_dir / "coverage_report_2023_2025.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    summary = report["summary"]
    print(
        f"{json_path}: expected={summary['expected_sessions']} complete={summary['complete_sessions']} "
        f"pending={summary['pending_authorized_access']} unavailable={summary['permanently_unavailable']} "
        f"coverage_pct={summary['coverage_pct']} validated={summary['validated_records']}"
    )
    print(f"{markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())