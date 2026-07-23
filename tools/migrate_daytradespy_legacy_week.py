#!/usr/bin/env python3
"""Convert the June 15-18 legacy research week into complete-schema evidence records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION
else:
    from daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION


WEEK = (
    (45147, "2026-06-15", 4311, "https://daytradespy.com/45147/trading-room-video-recording-june-15-2026/", "Confirmation after moving-average retest and structural room are candidate research features."),
    (45158, "2026-06-16", 4366, "https://daytradespy.com/45158/trading-room-video-recording-june-16-2026/", "Volume expansion requires displacement and structural acceptance; failed downside breaks require separate labels."),
    (45169, "2026-06-17", 4266, "https://daytradespy.com/45169/trading-room-video-recording-june-17-2026/", "Event risk raises uncertainty but cannot lower confirmation requirements; premarket extremes define room."),
    (45194, "2026-06-18", 5681, "https://daytradespy.com/45194/trading-room-video-recording-june-18-2026/", "Level discussion is not acceptance evidence; retain test, close-through, retest, and hold sequence."),
)
UNAVAILABLE_WINDOWS = {f"{minutes}m": "UNAVAILABLE_EVIDENCE" for minutes in (1, 3, 5, 10, 15)} | {"remainder_session": "UNAVAILABLE_EVIDENCE"}


def record_for(post_id: int, day: str, duration: int, source_url: str, observation: str) -> dict[str, Any]:
    report_path = f"docs/research/{day}_daytradespy_trading_room_research.md"
    return {
        "schema_version": "daytradespy-record.v2", "recording": {
            "post_id": post_id, "title": f"Trading Room Video Recording - {day}", "publication_date": day,
            "duration_seconds": duration, "source_url": source_url,
            "reviewed_at": datetime.now(timezone.utc).isoformat(), "reviewer_version": "legacy-report-migration.v1",
            "analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION,
            "transcript": {"availability": "REVIEWED_IN_BROWSER_NO_EXPORT", "completeness_pct": 0, "path": "", "timestamps_preserved": False, "speaker_attribution_available": False},
            "visual_review": {"coverage_pct": 0, "status": "UNAVAILABLE_EVIDENCE", "chart_references": [], "notes": "Legacy report exists, but no retained visual-review evidence is available for schema verification."},
        },
        "legacy_evidence": {"report_path": report_path, "status": "LEGACY_REPORT_AVAILABLE", "fact_classification": "SOURCE_OBSERVATION"},
        "evidence_quality": {"transcript_completeness_pct": 0, "trade_details_captured_pct": 0, "ledger_reconciliation_pct": 0, "underlying_market_data_pct": 0, "option_excursion_data_pct": 0, "overall_grade": "INCOMPLETE"},
        "timeline": [{"timestamp": "UNKNOWN", "classification": "SOURCE_OBSERVATION", "fact_classification": "SOURCE_OBSERVATION", "claim": observation, "chart_reference": "UNKNOWN"}],
        "market_state_timeline": [{"timestamp": "UNKNOWN", "market_direction": "UNKNOWN", "volatility": "UNKNOWN", "trend_strength": "UNKNOWN", "trend_quality": "UNKNOWN", "trend_stage": "UNKNOWN", "session_bias": "UNKNOWN", "five_minute_context": "UNKNOWN", "vwap_state": "UNKNOWN", "ema_alignment": "UNKNOWN", "congestion": "UNKNOWN", "breakout": "UNKNOWN", "reclaim": "UNKNOWN", "rejection": "UNKNOWN", "event_risk": "UNKNOWN", "room_to_target": "UNKNOWN"}],
        "claims": [{"id": f"DTS-{day.replace('-', '')}-C01", "timestamp": "UNKNOWN", "label": "LEGACY_OBSERVATION", "status": "NEEDS_INSTRUMENTATION", "fact_classification": "SOURCE_OBSERVATION", "claim": observation, "forward_outcomes": UNAVAILABLE_WINDOWS, "disconfirming_evidence_required": "Replay against an existing McLeod Alpha baseline with price, option, and negative-control data."}],
        "trade_discussions": [], "reported_trades": [], "no_trade_decisions": [],
        "plan_consistency": [{"source_trade_id": "NONE", "plan_before_entry": "UNAVAILABLE_EVIDENCE", "actual_execution": "UNAVAILABLE_EVIDENCE", "label": "INSUFFICIENT_EVIDENCE"}],
        "ledger_reconciliation": {"source_reported_trades": 0, "mcleod_alpha_trades": "UNAVAILABLE_EVIDENCE", "confirmed_matches": [], "possible_matches": [], "conflicts": [], "unavailable_evidence": ["No canonical ledger mapping retained for this legacy report.", "No option MFE/MAE, bid/ask/mark, or contract-level data retained."]},
        "counterfactuals": [{"timestamp": "UNKNOWN", "type": "UNAVAILABLE_EVIDENCE", "detail": "Cannot assess source-rule impact without baseline replay, underlying bars, option marks, and friction."}],
        "hypothesis_references": [], "knowledge_graph": {"parent_ideas": [], "related_ideas": ["DTS-HYP-RANGE-REENTRY-001"], "supporting_recordings": [post_id], "contradicting_recordings": [], "dependent_hypotheses": [], "replay_experiments": [], "shadow_experiments": [], "production_rules": []},
        "expected_value_tracking": {"replay_improvement": "UNAVAILABLE_EVIDENCE", "out_of_sample_improvement": "UNAVAILABLE_EVIDENCE", "shadow_improvement": "UNAVAILABLE_EVIDENCE", "production_improvement": "UNAVAILABLE_EVIDENCE", "confidence": "LOW", "evidence_count": 1, "current_lifecycle_stage": "OBSERVATION_ONLY", "expected_future_value": "UNKNOWN", "engineering_complexity": "UNKNOWN"},
        "instrumentation_gaps": ["DTS-INST-001"],
        "adversarial_review": {"why_wrong": "Legacy prose may omit contrary conditions, exact timestamps, and failed examples.", "contradicting_evidence": "UNAVAILABLE_EVIDENCE", "profitable_trades_blocked": "UNAVAILABLE_EVIDENCE", "existing_idea_overlap": "POSSIBLE; requires feature-level replay comparison."},
        "final_governance_decision": GOVERNANCE_DECISION,
    }


def write_week(root: Path) -> list[Path]:
    records = root / "records"
    records.mkdir(parents=True, exist_ok=True)
    written = []
    for post_id, day, duration, source_url, observation in WEEK:
        path = records / f"{day}.json"
        path.write_text(json.dumps(record_for(post_id, day, duration, source_url, observation), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for output in write_week(Path("data/research/daytradespy")):
        print(output)