#!/usr/bin/env python3
"""Migrate the March 9, 2026 legacy report for archive post 43901."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .daytradespy_record_processor import register_record
    from .daytradespy_research_ops import aggregate_record, write_output_bundle
    from .daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION
else:
    from daytradespy_record_processor import register_record
    from daytradespy_research_ops import aggregate_record, write_output_bundle
    from daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION


POST_ID = 43901
DAY = "2026-03-09"
SOURCE_URL = "https://daytradespy.com/43901/trading-room-video-recording-march-6-2026/"
RECORD_STEM = f"{DAY}-post-{POST_ID}"


def record_for() -> dict:
    return {
        "schema_version": "daytradespy-record.v2",
        "recording": {
            "post_id": POST_ID,
            "title": "Trading Room Video Recording - March 9, 2026 (legacy archive entry)",
            "publication_date": DAY,
            "duration_seconds": None,
            "source_url": SOURCE_URL,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer_version": "legacy-report-migration.v1",
            "analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION,
            "transcript": {
                "availability": "LEGACY_REPORT_MIGRATION",
                "completeness_pct": 0,
                "path": "",
                "timestamps_preserved": False,
                "speaker_attribution_available": False,
            },
            "transcript_probe": {
                "source": "AUTHORIZED_BROWSER_RUNTIME",
                "raw_transcript_persisted": False,
                "first_timestamp": "UNKNOWN",
                "last_timestamp": "UNKNOWN",
                "cue_count": 0,
                "coverage_note": "The legacy report provides synthesized observations but retains no exportable transcript or visual-review evidence.",
            },
            "visual_review": {
                "coverage_pct": 0,
                "status": "UNAVAILABLE_EVIDENCE",
                "chart_references": [],
            },
        },
        "evidence_quality": {
            "transcript_completeness_pct": 0,
            "trade_details_captured_pct": 0,
            "ledger_reconciliation_pct": 0,
            "underlying_market_data_pct": 0,
            "option_excursion_data_pct": 0,
            "overall_grade": "LEGACY_SYNTHESIS_ONLY",
            "tier": "E",
        },
        "timeline": [{
            "timestamp": "UNKNOWN",
            "classification": "SOURCE_OBSERVATION",
            "fact_classification": "SOURCE_OBSERVATION",
            "claim": "Legacy report observation: oil-price shock, yields, and upcoming CPI and PCE releases were treated as event context rather than a directional trigger.",
            "chart_reference": "UNKNOWN",
        }],
        "claims": [{
            "id": "DTS-20260309-43901-C01",
            "timestamp": "UNKNOWN",
            "label": "LEGACY_EVENT_CONTEXT",
            "status": "NEEDS_INSTRUMENTATION",
            "fact_classification": "SOURCE_OBSERVATION",
            "claim": "Legacy report observation: event context was discussed without establishing a standalone directional trigger.",
            "forward_outcomes": {f"{minutes}m": "UNAVAILABLE_EVIDENCE" for minutes in (1, 3, 5, 10, 15)} | {"remainder_session": "UNAVAILABLE_EVIDENCE"},
            "disconfirming_evidence_required": "Timestamped underlying bars, visual review, and independently reconciled execution evidence.",
        }],
        "reported_trades": [],
        "ledger_reconciliation": {
            "source_reported_trades": 0,
            "mcleod_alpha_trades": "UNAVAILABLE_EVIDENCE",
            "confirmed_matches": [],
            "possible_matches": [],
            "conflicts": [],
            "unavailable_evidence": ["No exportable transcript, chart review, or canonical ledger mapping was retained with the legacy report."],
        },
        "market_state_timeline": [{
            "timestamp": "UNKNOWN",
            "market_direction": "UNKNOWN",
            "volatility": "UNKNOWN",
            "trend_strength": "UNKNOWN",
            "vwap_state": "UNKNOWN",
            "room_to_target": "UNKNOWN",
        }],
        "counterfactuals": [{
            "timestamp": "UNKNOWN",
            "type": "UNAVAILABLE_EVIDENCE",
            "detail": "Counterfactual impact cannot be assessed without replay, underlying bars, option marks, and friction.",
        }],
        "hypothesis_references": [],
        "instrumentation_gaps": [
            "Exportable transcript or timestamped observation log",
            "Visual review",
            "Timestamped underlying bars",
            "Option bid, ask, mark, MFE, and MAE telemetry",
            "Canonical ledger mapping",
        ],
        "adversarial_review": {
            "why_wrong": "Legacy prose can omit contrary conditions, exact timestamps, failed examples, and execution details.",
            "contradicting_evidence": "UNAVAILABLE_EVIDENCE",
            "profitable_trades_blocked": "UNAVAILABLE_EVIDENCE",
        },
        "expected_value_tracking": {
            "confidence": "LOW",
            "evidence_count": 1,
            "current_lifecycle_stage": "OBSERVATION_ONLY",
            "replay_improvement": "UNAVAILABLE_EVIDENCE",
        },
        "final_governance_decision": GOVERNANCE_DECISION,
    }


def report_for() -> str:
    return "\n".join((
        "# McLeod Alpha Research Report: 2026-03-09 Trading Room (Post 43901)",
        "",
        "## Scope and Evidence",
        "",
        "This governed migration preserves only the synthesized observations from the legacy March 9 report for archive post 43901. No exportable transcript, chart review, underlying bars, option marks, or ledger reconciliation is retained.",
        "",
        "## Observations",
        "",
        "- Macro and policy discussion was event context, not a standalone directional trigger.",
        "- Support, pivot resistance, and range structure required acceptance or rejection evidence before use as a candidate setup condition.",
        "- A level touch was distinguished from a usable break; replay must separately measure closes and retests.",
        "- Source-described option management has no contract, fill, mark, or outcome evidence and cannot be evaluated as execution quality.",
        "",
        "## Decision",
        "",
        "The recording remains research-only and coverage-incomplete. No live entry, exit, stop, sizing, direction, or trading-policy change is authorized.",
        "",
    ))


def main() -> int:
    root = Path("data/research/daytradespy")
    record_path = root / "records" / f"{RECORD_STEM}.json"
    report_path = Path("docs/research") / f"{RECORD_STEM}_daytradespy_trading_room_research.md"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    record = record_for()
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(report_for(), encoding="utf-8")
    write_output_bundle(record, root / "output")
    aggregate_record(record, root)
    register_record(record_path, root / "recording_registry.json")
    registry_path = root / "recording_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for item in registry["recordings"]:
        if int(item["post_id"]) == POST_ID:
            item["recording_date"] = DAY
            item["report_path"] = str(report_path)
            break
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Registered March 9, 2026 legacy research record: {record_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())