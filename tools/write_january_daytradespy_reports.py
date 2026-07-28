#!/usr/bin/env python3
"""Upgrade January 2026 Day Trade SPY research records without storing transcripts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JANUARY_DAYS = (
    "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
    "2026-01-09", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16",
    "2026-01-20", "2026-01-21", "2026-01-22", "2026-01-23", "2026-01-26",
    "2026-01-27", "2026-01-28", "2026-01-29", "2026-01-30",
)
UNAVAILABLE_WINDOWS = {
    **{f"{minutes}m": "UNAVAILABLE_EVIDENCE" for minutes in (1, 3, 5, 10, 15)},
    "remainder_session": "UNAVAILABLE_EVIDENCE",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def legacy_findings(record: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    findings: list[dict[str, str]] = []
    claims: list[dict[str, Any]] = []
    day = record["recording"]["publication_date"]
    for index, legacy_claim in enumerate(record.get("claims", []), start=1):
        presenter_observation = legacy_claim.get("fact_classification") == "PRESENTER_CLAIM"
        topic = "PRESENTER_OBSERVATION" if presenter_observation else "TRANSCRIPT_COVERAGE"
        timestamp = str(legacy_claim.get("timestamp", "UNKNOWN"))
        source_claim = str(legacy_claim.get("claim", ""))
        finding = (
            "A bounded presenter observation was retained for this session. It is source evidence only and does not establish an executable setup or outcome."
            if presenter_observation
            else "Timestamped transcript coverage was retained, but no independently classified source-content topic was preserved from the measured segment."
        )
        findings.append({
            "timestamp": timestamp,
            "topic": topic,
            "finding": finding,
            "evidence_basis": "Retained authorized-browser measurement: " + source_claim,
            "classification": "DERIVED_RESEARCH_FINDING",
        })
        claims.append({
            "id": f"DTS-{day.replace('-', '')}-C{index:02d}",
            "timestamp": timestamp,
            "label": topic,
            "status": "NEEDS_INSTRUMENTATION",
            "fact_classification": legacy_claim.get("fact_classification", "SOURCE_MEASUREMENT"),
            "claim": source_claim,
            "forward_outcomes": UNAVAILABLE_WINDOWS,
            "disconfirming_evidence_required": "Timestamped underlying bars, visual review, and independently reconciled execution evidence.",
        })
    return findings, claims


def unmeasured_findings() -> list[dict[str, str]]:
    return [{
        "timestamp": "UNKNOWN",
        "topic": "TRANSCRIPT_MEASUREMENT_UNAVAILABLE",
        "finding": "Archive lineage confirms the recording, but no durable timestamped transcript measurement or source-content topic was retained for this session.",
        "evidence_basis": "Archive manifest source lineage only; authenticated access must be measured again before content findings are registered.",
        "classification": "DERIVED_RESEARCH_FINDING",
    }]


def record_for(day: str, source: dict[str, Any], legacy: dict[str, Any] | None) -> dict[str, Any]:
    if legacy:
        legacy_recording = legacy["recording"]
        transcript = legacy_recording.get("transcript", {})
        probe = legacy_recording.get("transcript_probe", {})
        coverage = int(transcript.get("completeness_pct", 0))
        cue_count = probe.get("cue_count", "UNKNOWN")
        last_timestamp = probe.get("last_timestamp", "UNKNOWN")
        findings, claims = legacy_findings(legacy)
        availability = "PARTIAL_AUTHORIZED_BROWSER_TRANSCRIPT"
        duration_seconds = legacy_recording.get("duration_seconds")
        source_type = "AUTHORIZED_BROWSER_RUNTIME"
        timestamps_preserved = True
        grade = "PARTIAL_TRANSCRIPT_VISUAL_UNAVAILABLE"
        tier = "D" if coverage >= 50 else "E"
        coverage_note = "Only the retained measured segment is eligible for analysis; all unmeasured transcript content is UNKNOWN."
    else:
        coverage, cue_count, last_timestamp = 0, "UNKNOWN", "UNKNOWN"
        findings, claims = unmeasured_findings(), []
        availability = "ACCESS_CONFIRMED_MEASUREMENT_NOT_RETAINED"
        duration_seconds = None
        source_type = "ARCHIVE_METADATA"
        timestamps_preserved = False
        grade, tier = "TRANSCRIPT_MEASUREMENT_UNAVAILABLE", "E"
        coverage_note = "Authenticated access was confirmed externally, but no timestamped measurement was retained locally. Content findings require a new authorized measurement."

    return {
        "schema_version": "daytradespy-record.v2",
        "recording": {
            "post_id": source["post_id"],
            "title": source["title"].replace("\u2013", "-"),
            "publication_date": day,
            "duration_seconds": duration_seconds,
            "source_url": source["source_url"],
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer_version": "january-archive-upgrade.v1",
            "analysis_protocol_version": "2026-07-23.1",
            "transcript": {
                "availability": availability,
                "completeness_pct": coverage,
                "path": "",
                "timestamps_preserved": timestamps_preserved,
                "speaker_attribution_available": False,
            },
            "transcript_probe": {
                "source": source_type,
                "raw_transcript_persisted": False,
                "first_timestamp": "00:00" if legacy else "UNKNOWN",
                "last_timestamp": last_timestamp,
                "cue_count": cue_count,
                "coverage_note": coverage_note,
            },
            "visual_review": {"coverage_pct": 0, "status": "UNAVAILABLE_EVIDENCE", "chart_references": []},
        },
        "evidence_quality": {
            "transcript_completeness_pct": coverage,
            "trade_details_captured_pct": 0,
            "ledger_reconciliation_pct": 0,
            "underlying_market_data_pct": 0,
            "option_excursion_data_pct": 0,
            "overall_grade": grade,
            "tier": tier,
        },
        "timeline": [{
            "timestamp": finding["timestamp"],
            "classification": "SOURCE_MEASUREMENT",
            "fact_classification": "SOURCE_MEASUREMENT",
            "claim": finding["evidence_basis"],
            "chart_reference": "UNKNOWN",
        } for finding in findings],
        "claims": claims,
        "derived_findings": findings,
        "hypothesis_references": [],
        "market_state_timeline": [{
            "timestamp": "UNKNOWN", "market_direction": "UNKNOWN", "volatility": "UNKNOWN",
            "trend_strength": "UNKNOWN", "vwap_state": "UNKNOWN", "room_to_target": "UNKNOWN",
        }],
        "ledger_reconciliation": {
            "source_reported_trades": 0, "mcleod_alpha_trades": "UNAVAILABLE_EVIDENCE",
            "confirmed_matches": [], "possible_matches": [], "conflicts": [],
            "unavailable_evidence": ["No canonical ledger mapping or option-excursion data was available."],
        },
        "adversarial_review": {
            "why_wrong": "Transcript coverage or a source observation cannot establish setup quality, trade execution, or expectancy.",
            "contradicting_evidence": "UNAVAILABLE_EVIDENCE",
            "profitable_trades_blocked": "UNAVAILABLE_EVIDENCE",
        },
        "expected_value_tracking": {
            "confidence": "LOW", "evidence_count": len(findings),
            "current_lifecycle_stage": "OBSERVATION_ONLY", "replay_improvement": "UNAVAILABLE_EVIDENCE",
        },
        "reported_trades": [],
        "instrumentation_gaps": [
            "Full timestamped transcript measurement", "Visual review", "Timestamped underlying bars",
            "Option execution and excursion data", "Canonical ledger mapping",
        ],
        "final_governance_decision": "RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE",
    }


def report_for(record: dict[str, Any]) -> str:
    recording = record["recording"]
    probe = recording["transcript_probe"]
    if probe["cue_count"] == "UNKNOWN":
        measurement = "No locally retained timestamped transcript measurement is available."
    else:
        measurement = (
            f"The authorized transcript was measured through {probe['last_timestamp']} "
            f"({probe['cue_count']} cues; {record['evidence_quality']['transcript_completeness_pct']}% coverage)."
        )
    observations = [
        f"- {finding['topic'].replace('_', ' ').title()} ({finding['timestamp']}): {finding['finding']}"
        for finding in record["derived_findings"]
    ]
    return "\n".join((
        f"# McLeod Alpha Research Report: {recording['publication_date']} Trading Room", "",
        "## Scope and Evidence", "",
        f"External qualitative research based on the Day Trade SPY {recording['publication_date']} trading-room recording. {measurement} This document retains synthesized observations only, not source transcript content.",
        "", "## Observations", "", *observations,
        "- Visual review, underlying bars, option execution data, and a canonical ledger mapping remain unavailable; no source commentary is treated as a verified trade outcome.",
        "", "## Research Implications", "",
        "1. Treat retained source observations as candidate replay features only; none is an entry signal by itself.",
        "2. Require independently measured test, close-through, retest, and hold/fail behavior before promoting any source theme to a setup label.",
        "3. Evaluate candidate features with timestamped underlying bars, option marks, and negative-control sessions before considering expectancy or execution quality.",
        "", "## Decision", "",
        "No live entry, exit, stop, sizing, direction, or other trading-policy changes are authorized from this external research. The candidate labels require replay, out-of-sample validation, and risk review before consideration.", "",
    ))


def main() -> int:
    root = Path("data/research/daytradespy")
    records_dir = root / "records"
    docs_dir = Path("docs/research")
    sources = {item["recording_date"][:10]: item for item in load_json(root / "archive_manifest.json")["recordings"]}
    records_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    for day in JANUARY_DAYS:
        path = records_dir / f"{day}.json"
        legacy = load_json(path) if path.exists() else None
        record = record_for(day, sources[day], legacy)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (docs_dir / f"{day}_daytradespy_trading_room_research.md").write_text(report_for(record), encoding="utf-8")
    print(f"Wrote {len(JANUARY_DAYS)} January 2026 research records and reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

'''
#!/usr/bin/env python3
"""Write readable January Day Trade SPY research reports from governed records."""

from __future__ import annotations



    JANUARY_DAYS = (
        "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
        "2026-01-09", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16",
        "2026-01-20", "2026-01-21", "2026-01-22", "2026-01-23", "2026-01-26",
        "2026-01-27", "2026-01-28", "2026-01-29", "2026-01-30",
    )

    UNAVAILABLE_WINDOWS = {
        **{f"{minutes}m": "UNAVAILABLE_EVIDENCE" for minutes in (1, 3, 5, 10, 15)},
        "remainder_session": "UNAVAILABLE_EVIDENCE",
    }


    def _load_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))


    def _topic_for_claim(claim: dict[str, Any]) -> str:
        if claim.get("fact_classification") == "PRESENTER_CLAIM":
            return "PRESENTER_OBSERVATION"
        return "TRANSCRIPT_COVERAGE"


    def _findings_from_legacy(legacy: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        findings: list[dict[str, str]] = []
        claims: list[dict[str, Any]] = []
        for index, legacy_claim in enumerate(legacy.get("claims", []), start=1):
            topic = _topic_for_claim(legacy_claim)
            timestamp = str(legacy_claim.get("timestamp", "UNKNOWN"))
            source_claim = str(legacy_claim.get("claim", ""))
            if topic == "PRESENTER_OBSERVATION":
                finding = "A bounded presenter observation was retained for this session. It is source evidence only and does not establish an executable setup or outcome."
            else:
                finding = "Timestamped transcript coverage was retained, but no independently classified source-content topic was preserved from the measured segment."
            findings.append({
                "timestamp": timestamp,
                "topic": topic,
                "finding": finding,
                "evidence_basis": "Retained authorized-browser measurement: " + source_claim,
                "classification": "DERIVED_RESEARCH_FINDING",
            })
            claims.append({
                "id": f"DTS-{legacy['recording']['publication_date'].replace('-', '')}-C{index:02d}",
                "timestamp": timestamp,
                "label": topic,
                "status": "NEEDS_INSTRUMENTATION",
                "fact_classification": legacy_claim.get("fact_classification", "SOURCE_MEASUREMENT"),
                "claim": source_claim,
                "forward_outcomes": UNAVAILABLE_WINDOWS,
                "disconfirming_evidence_required": "Timestamped underlying bars, visual review, and independently reconciled execution evidence.",
            })
        return findings, claims


    def _unmeasured_finding() -> list[dict[str, str]]:
        return [{
            "timestamp": "UNKNOWN",
            "topic": "TRANSCRIPT_MEASUREMENT_UNAVAILABLE",
            "finding": "Archive lineage confirms the recording, but no durable timestamped transcript measurement or source-content topic was retained for this session.",
            "evidence_basis": "Archive manifest source lineage only; authenticated access must be measured again before content findings are registered.",
            "classification": "DERIVED_RESEARCH_FINDING",
        }]


    def _record_for(day: str, source: dict[str, Any], legacy: dict[str, Any] | None) -> dict[str, Any]:
        post_id = source["post_id"]
        if legacy:
            recording = legacy["recording"]
            transcript = recording.get("transcript", {})
            probe = recording.get("transcript_probe", {})
            coverage = int(transcript.get("completeness_pct", 0))
            cue_count = probe.get("cue_count", "UNKNOWN")
            last_timestamp = probe.get("last_timestamp", "UNKNOWN")
            findings, claims = _findings_from_legacy(legacy)
            availability = "PARTIAL_AUTHORIZED_BROWSER_TRANSCRIPT"
            duration_seconds: int | None = recording.get("duration_seconds")
            tier = "D" if coverage >= 50 else "E"
            grade = "PARTIAL_TRANSCRIPT_VISUAL_UNAVAILABLE"
            coverage_note = "Only the retained measured segment is eligible for analysis; all unmeasured transcript content is UNKNOWN."
        else:
            coverage = 0
            cue_count = "UNKNOWN"
            last_timestamp = "UNKNOWN"
            findings, claims = _unmeasured_finding(), []
            availability = "ACCESS_CONFIRMED_MEASUREMENT_NOT_RETAINED"
            duration_seconds = None
            tier = "E"
            grade = "TRANSCRIPT_MEASUREMENT_UNAVAILABLE"
            coverage_note = "Authenticated access was confirmed externally, but no timestamped measurement was retained locally. Content findings require a new authorized measurement."

        return {
            "schema_version": "daytradespy-record.v2",
            "recording": {
                "post_id": post_id,
                "title": source["title"].replace("\u2013", "-"),
                "publication_date": day,
                "duration_seconds": duration_seconds,
                "source_url": source["source_url"],
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "reviewer_version": "january-archive-upgrade.v1",
                "analysis_protocol_version": "2026-07-23.1",
                "transcript": {
                    "availability": availability,
                    "completeness_pct": coverage,
                    "path": "",
                    "timestamps_preserved": legacy is not None,
                    "speaker_attribution_available": False,
                },
                "transcript_probe": {
                    "source": "AUTHORIZED_BROWSER_RUNTIME" if legacy else "ARCHIVE_METADATA",
                    "raw_transcript_persisted": False,
                    "first_timestamp": "00:00" if legacy else "UNKNOWN",
                    "last_timestamp": last_timestamp,
                    "cue_count": cue_count,
                    "coverage_note": coverage_note,
                },
                "visual_review": {"coverage_pct": 0, "status": "UNAVAILABLE_EVIDENCE", "chart_references": []},
            },
            "evidence_quality": {
                "transcript_completeness_pct": coverage,
                "trade_details_captured_pct": 0,
                "ledger_reconciliation_pct": 0,
                "underlying_market_data_pct": 0,
                "option_excursion_data_pct": 0,
                "overall_grade": grade,
                "tier": tier,
            },
            "timeline": [{
                "timestamp": finding["timestamp"],
                "classification": "SOURCE_MEASUREMENT",
                "fact_classification": "SOURCE_MEASUREMENT",
                "claim": finding["evidence_basis"],
                "chart_reference": "UNKNOWN",
            } for finding in findings],
            "claims": claims,
            "derived_findings": findings,
            "hypothesis_references": [],
            "market_state_timeline": [{
                "timestamp": "UNKNOWN", "market_direction": "UNKNOWN", "volatility": "UNKNOWN",
                "trend_strength": "UNKNOWN", "vwap_state": "UNKNOWN", "room_to_target": "UNKNOWN",
            }],
            "ledger_reconciliation": {
                "source_reported_trades": 0, "mcleod_alpha_trades": "UNAVAILABLE_EVIDENCE",
                "confirmed_matches": [], "possible_matches": [], "conflicts": [],
                "unavailable_evidence": ["No canonical ledger mapping or option-excursion data was available."],
            },
            "adversarial_review": {
                "why_wrong": "Transcript coverage or a source observation cannot establish setup quality, trade execution, or expectancy.",
                "contradicting_evidence": "UNAVAILABLE_EVIDENCE",
                "profitable_trades_blocked": "UNAVAILABLE_EVIDENCE",
            },
            "expected_value_tracking": {
                "confidence": "LOW", "evidence_count": len(findings),
                "current_lifecycle_stage": "OBSERVATION_ONLY", "replay_improvement": "UNAVAILABLE_EVIDENCE",
            },
            "reported_trades": [],
            "instrumentation_gaps": [
                "Full timestamped transcript measurement", "Visual review", "Timestamped underlying bars",
                "Option execution and excursion data", "Canonical ledger mapping",
            ],
            "final_governance_decision": "RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE",
        }


    def _report_for(record: dict[str, Any]) -> str:
        recording = record["recording"]
        probe = recording["transcript_probe"]
        findings = record["derived_findings"]
        observations = [
            f"- {finding['topic'].replace('_', ' ').title()} ({finding['timestamp']}): {finding['finding']}"
            for finding in findings
        ]
        if probe["cue_count"] == "UNKNOWN":
            measurement = "No locally retained timestamped transcript measurement is available."
        else:
            measurement = (
                f"The authorized transcript was measured through {probe['last_timestamp']} "
                f"({probe['cue_count']} cues; {record['evidence_quality']['transcript_completeness_pct']}% coverage)."
            )
        return "\n".join((
            f"# McLeod Alpha Research Report: {recording['publication_date']} Trading Room", "",
            "## Scope and Evidence", "",
            f"External qualitative research based on the Day Trade SPY {recording['publication_date']} trading-room recording. {measurement} This document retains synthesized observations only, not source transcript content.",
            "", "## Observations", "", *observations,
            "- Visual review, underlying bars, option execution data, and a canonical ledger mapping remain unavailable; no source commentary is treated as a verified trade outcome.",
            "", "## Research Implications", "",
            "1. Treat retained source observations as candidate replay features only; none is an entry signal by itself.",
            "2. Require independently measured test, close-through, retest, and hold/fail behavior before promoting any source theme to a setup label.",
            "3. Evaluate candidate features with timestamped underlying bars, option marks, and negative-control sessions before considering expectancy or execution quality.",
            "", "## Decision", "",
            "No live entry, exit, stop, sizing, direction, or other trading-policy changes are authorized from this external research. The candidate labels require replay, out-of-sample validation, and risk review before consideration.", "",
        ))


    def main() -> int:
        root = Path("data/research/daytradespy")
        records_dir = root / "records"
        docs_dir = Path("docs/research")
        manifest = _load_json(root / "archive_manifest.json")
        sources = {item["recording_date"][:10]: item for item in manifest["recordings"]}
        records_dir.mkdir(parents=True, exist_ok=True)
        docs_dir.mkdir(parents=True, exist_ok=True)

        for day in JANUARY_DAYS:
            source = sources[day]
            path = records_dir / f"{day}.json"
            legacy = _load_json(path) if path.exists() else None
            record = _record_for(day, source, legacy)
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (docs_dir / f"{day}_daytradespy_trading_room_research.md").write_text(_report_for(record), encoding="utf-8")
        print(f"Wrote {len(JANUARY_DAYS)} January 2026 research records and reports.")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())

'''


if __name__ == "__main__":
    raise SystemExit(main())