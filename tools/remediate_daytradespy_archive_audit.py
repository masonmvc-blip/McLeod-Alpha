#!/usr/bin/env python3
"""Remediate bounded Day Trade SPY archive coverage gaps without inventing evidence."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .daytradespy_record_processor import validate_record
    from .daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION
else:
    from daytradespy_record_processor import validate_record
    from daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION


APRIL_DATES = (
    "2026-04-01", "2026-04-02", "2026-04-06", "2026-04-07", "2026-04-08",
    "2026-04-09", "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16",
    "2026-04-17",
)
NEW_REPORT_DATES = (
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
    "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-06",
    "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-22",
)
TARGET_DATES = APRIL_DATES + NEW_REPORT_DATES
REPORT_SUFFIX = "_daytradespy_trading_room_research.md"
OBSERVATIONS_HEADING = "## Observations"
NEXT_HEADING = re.compile(r"^## ", re.MULTILINE)
TITLE_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, 2026)")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def report_path(docs_root: Path, recording_date: str) -> Path:
    return docs_root / f"{recording_date}{REPORT_SUFFIX}"


def source_by_date(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for source in manifest.get("recordings", []):
        if not isinstance(source, dict):
            continue
        recording_date = str(source.get("recording_date") or "")[:10]
        if recording_date and recording_date not in sources:
            sources[recording_date] = source
    return sources


def extract_observations(path: Path) -> list[str]:
    """Return the existing report's literal observation bullets, with no inference."""
    content = path.read_text(encoding="utf-8")
    if OBSERVATIONS_HEADING not in content:
        return []
    section = content.split(OBSERVATIONS_HEADING, 1)[1]
    next_heading = NEXT_HEADING.search(section)
    if next_heading:
        section = section[:next_heading.start()]
    return [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]


def metadata_finding(source: dict[str, Any]) -> dict[str, str]:
    return {
        "classification": "ARCHIVE_METADATA",
        "evidence": "archive_manifest",
        "observation": (
            f"The Day Trade SPY public archive lists post {source['post_id']} as "
            f"'{source['title']}' published {str(source['recording_date'])}."
        ),
    }


def legacy_findings(source: dict[str, Any], path: Path) -> list[dict[str, str]]:
    observations = extract_observations(path)
    return [
        {
            "classification": "LEGACY_REPORT_OBSERVATION",
            "evidence": f"{path.as_posix()}",
            "observation": observation,
        }
        for observation in observations
    ] or [metadata_finding(source)]


def build_record(source: dict[str, Any], recording_date: str, findings: list[dict[str, str]]) -> dict[str, Any]:
    post_id = int(source["post_id"])
    manifest_claim = metadata_finding(source)["observation"]
    return {
        "schema_version": "daytradespy-record.v2",
        "recording": {
            "analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION,
            "duration_seconds": "UNAVAILABLE_EVIDENCE",
            "post_id": post_id,
            "publication_date": recording_date,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer_version": "archive-audit-remediation.v1",
            "source_url": str(source["source_url"]),
            "title": str(source["title"]),
            "transcript": {
                "availability": "UNAVAILABLE_EVIDENCE",
                "completeness_pct": 0,
                "path": "",
                "speaker_attribution_available": False,
                "timestamps_preserved": False,
            },
            "transcript_probe": {
                "source": "UNAVAILABLE_EVIDENCE",
                "coverage_note": "No transcript coverage, cue count, or cutoff was retained by this archive-metadata migration.",
                "raw_transcript_persisted": False,
            },
            "visual_review": {
                "chart_references": [],
                "coverage_pct": 0,
                "notes": "UNAVAILABLE_EVIDENCE: no visual review was retained by this migration.",
                "status": "UNAVAILABLE_EVIDENCE",
            },
        },
        "derived_findings": findings,
        "findings": findings,
        "claims": [
            {
                "id": f"DTS-{recording_date.replace('-', '')}-C01",
                "claim": manifest_claim,
                "label": "ARCHIVE_METADATA",
                "status": "OBSERVATION_ONLY",
                "timestamp": "UNKNOWN",
                "fact_classification": "ARCHIVE_METADATA",
                "disconfirming_evidence_required": "Authorized transcript, visual review, market data, and execution evidence.",
                "forward_outcomes": {key: "UNAVAILABLE_EVIDENCE" for key in ("1m", "3m", "5m", "10m", "15m", "remainder_session")},
            }
        ],
        "timeline": [
            {
                "timestamp": "UNKNOWN",
                "claim": manifest_claim,
                "classification": "ARCHIVE_METADATA",
                "fact_classification": "ARCHIVE_METADATA",
                "chart_reference": "UNKNOWN",
            }
        ],
        "reported_trades": [],
        "trade_discussions": [],
        "no_trade_decisions": [],
        "ledger_reconciliation": {
            "confirmed_matches": [],
            "conflicts": [],
            "mcleod_alpha_trades": "UNAVAILABLE_EVIDENCE",
            "possible_matches": [],
            "source_reported_trades": 0,
            "unavailable_evidence": ["No source trade, option, or canonical ledger evidence was retained by this migration."],
        },
        "market_state_timeline": [{key: "UNKNOWN" for key in (
            "timestamp", "market_direction", "session_bias", "five_minute_context", "trend_quality",
            "trend_stage", "trend_strength", "volatility", "vwap_state", "ema_alignment", "breakout",
            "reclaim", "rejection", "congestion", "room_to_target", "event_risk",
        )}],
        "counterfactuals": [{
            "timestamp": "UNKNOWN",
            "type": "UNAVAILABLE_EVIDENCE",
            "detail": "No replay, market, option, or execution telemetry was retained for counterfactual analysis.",
        }],
        "hypothesis_references": [],
        "instrumentation_gaps": ["DTS-INST-001"],
        "evidence_quality": {
            "transcript_completeness_pct": 0,
            "trade_details_captured_pct": 0,
            "ledger_reconciliation_pct": 0,
            "underlying_market_data_pct": 0,
            "option_excursion_data_pct": 0,
            "overall_grade": "INCOMPLETE",
        },
        "expected_value_tracking": {
            "confidence": "NONE",
            "current_lifecycle_stage": "OBSERVATION_ONLY",
            "engineering_complexity": "UNKNOWN",
            "evidence_count": len(findings),
            "expected_future_value": "UNAVAILABLE_EVIDENCE",
            "out_of_sample_improvement": "UNAVAILABLE_EVIDENCE",
            "production_improvement": "UNAVAILABLE_EVIDENCE",
            "replay_improvement": "UNAVAILABLE_EVIDENCE",
            "shadow_improvement": "UNAVAILABLE_EVIDENCE",
        },
        "adversarial_review": {
            "contradicting_evidence": "UNAVAILABLE_EVIDENCE",
            "existing_idea_overlap": "UNAVAILABLE_EVIDENCE",
            "profitable_trades_blocked": "UNAVAILABLE_EVIDENCE",
            "why_wrong": "Archive metadata and legacy report prose cannot establish a replayable or executable conclusion.",
        },
        "legacy_evidence": {
            "fact_classification": "ARCHIVE_METADATA",
            "status": "ARCHIVE_AUDIT_MIGRATION",
        },
        "knowledge_graph": {
            "contradicting_recordings": [], "dependent_hypotheses": [], "parent_ideas": [],
            "production_rules": [], "related_ideas": [], "replay_experiments": [],
            "shadow_experiments": [], "supporting_recordings": [post_id],
        },
        "plan_consistency": [{
            "actual_execution": "UNAVAILABLE_EVIDENCE", "label": "INSUFFICIENT_EVIDENCE",
            "plan_before_entry": "UNAVAILABLE_EVIDENCE", "source_trade_id": "NONE",
        }],
        "final_governance_decision": GOVERNANCE_DECISION,
    }


def build_report(source: dict[str, Any], recording_date: str) -> str:
    title = str(source["title"])
    return "\n".join((
        f"# McLeod Alpha Research Report: {recording_date} Trading Room", "",
        "## Scope", "",
        f"Research-only archive coverage for Day Trade SPY post {source['post_id']}: [{title}]({source['source_url']}).", "",
        "## Evidence / Observations", "",
        f"- The archive manifest identifies this recording as published on {source['recording_date']}.",
        "- No transcript coverage, cue count, visual review, trade detail, or market outcome was retained for this remediation.", "",
        "## Research Implications", "",
        "- Obtain authorized transcript and visual-review evidence before extracting setup, trade, or market-state observations.",
        "- Do not evaluate execution quality or outcomes without synchronized underlying, option, and ledger data.", "",
        "## Decision", "",
        "No live entry, exit, stop, sizing, direction, or other trading-policy change is authorized. This archive record remains research-only.", "",
    ))


def manifest_dates(manifest: dict[str, Any]) -> set[str]:
    return {
        str(source.get("recording_date") or "")[:10]
        for source in manifest.get("recordings", [])
        if str(source.get("recording_date") or "").startswith("2026-")
        and int(str(source["recording_date"])[5:7]) <= 7
    }


def title_date(source: dict[str, Any]) -> str | None:
    """Extract an archive title date when present; publication date remains canonical."""
    match = TITLE_DATE.search(str(source.get("title") or ""))
    return datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat() if match else None


def validate_coverage(manifest: dict[str, Any], docs_root: Path, records_root: Path) -> None:
    dates = manifest_dates(manifest)
    sources = [
        source for source in manifest.get("recordings", [])
        if isinstance(source, dict) and str(source.get("recording_date") or "")[:10] in dates
    ]
    publication_counts: dict[str, int] = {}
    title_date_mismatches: list[tuple[str, str, int]] = []
    for source in sources:
        publication_date = str(source["recording_date"])[:10]
        publication_counts[publication_date] = publication_counts.get(publication_date, 0) + 1
        source_title_date = title_date(source)
        if source_title_date and source_title_date != publication_date:
            title_date_mismatches.append((publication_date, source_title_date, int(source["post_id"])))
    missing_docs = sorted(date for date in dates if not report_path(docs_root, date).exists())
    missing_records = sorted(date for date in dates if not (records_root / f"{date}.json").exists())
    markdown_records = sorted(path.as_posix() for path in records_root.glob("*.md"))
    title_dates = {source_date for _, source_date, _ in title_date_mismatches}
    title_dates_in_manifest = title_dates.intersection(dates)
    title_date_gaps = sorted(
        date for date in title_dates_in_manifest
        if not report_path(docs_root, date).exists() or not (records_root / f"{date}.json").exists()
    )
    if missing_docs or missing_records or markdown_records or title_date_gaps:
        raise ValueError(
            f"Coverage validation failed: missing_docs={missing_docs}; "
            f"missing_records={missing_records}; markdown_records={markdown_records}; "
            f"title_date_gaps={title_date_gaps}"
        )
    for date in TARGET_DATES:
        if not report_path(docs_root, date).exists() or not (records_root / f"{date}.json").exists():
            raise ValueError(f"Targeted remediation date remains incomplete: {date}")
    print(f"coverage_dates={len(dates)} missing_docs=[] missing_records=[] markdown_records=[]")
    print(
        f"duplicate_publication_dates={sum(count > 1 for count in publication_counts.values())} "
        f"title_date_mismatches={title_date_mismatches} "
        f"nonpublication_title_dates={sorted(title_dates.difference(dates))} title_date_gaps=[]"
    )
    print(f"targeted_dates={len(TARGET_DATES)} complete={list(TARGET_DATES)}")


def remediate(root: Path) -> None:
    manifest = read_json(root / "data/research/daytradespy/archive_manifest.json")
    docs_root = root / "docs/research"
    records_root = root / "data/research/daytradespy/records"
    sources = source_by_date(manifest)
    missing_sources = sorted(set(TARGET_DATES).difference(sources))
    if missing_sources:
        raise ValueError(f"Manifest is missing requested dates: {missing_sources}")

    created_records: list[str] = []
    created_reports: list[str] = []
    for recording_date in APRIL_DATES:
        path = report_path(docs_root, recording_date)
        if not path.exists():
            raise ValueError(f"Required readable legacy report is missing: {path}")
        destination = records_root / f"{recording_date}.json"
        if not destination.exists():
            record = build_record(sources[recording_date], recording_date, legacy_findings(sources[recording_date], path))
            validate_record(record)
            write_json(destination, record)
            created_records.append(recording_date)

    for recording_date in NEW_REPORT_DATES:
        destination = records_root / f"{recording_date}.json"
        if not destination.exists():
            findings = [metadata_finding(sources[recording_date])]
            record = build_record(sources[recording_date], recording_date, findings)
            validate_record(record)
            write_json(destination, record)
            created_records.append(recording_date)
        destination_report = report_path(docs_root, recording_date)
        if not destination_report.exists():
            destination_report.write_text(build_report(sources[recording_date], recording_date), encoding="utf-8")
            created_reports.append(recording_date)

    print(f"created_records={created_records}")
    print(f"created_reports={created_reports}")
    validate_coverage(manifest, docs_root, records_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = read_json(root / "data/research/daytradespy/archive_manifest.json")
    if args.validate_only:
        validate_coverage(manifest, root / "docs/research", root / "data/research/daytradespy/records")
    else:
        remediate(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())