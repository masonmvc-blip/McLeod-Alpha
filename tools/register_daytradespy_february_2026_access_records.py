#!/usr/bin/env python3
"""Register bounded February 2026 Day Trade SPY transcript-access records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .daytradespy_record_processor import register_record
    from .daytradespy_research_ops import aggregate_record, write_output_bundle
else:
    from daytradespy_record_processor import register_record
    from daytradespy_research_ops import aggregate_record, write_output_bundle


RECORDINGS = (
    (43478, "2026-02-02", "february-2-2026"),
    (43497, "2026-02-03", "february-3-2026"),
    (43507, "2026-02-04", "february-4-2026"),
    (43555, "2026-02-05", "february-5-2026"),
    (43575, "2026-02-06", "february-6-2026"),
    (43593, "2026-02-09", "february-9-2026"),
    (43607, "2026-02-10", "february-10-2026"),
    (43639, "2026-02-11", "february-11-2026"),
    (43678, "2026-02-12", "february-12-2026"),
    (43656, "2026-02-13", "february-13-2026"),
    (43680, "2026-02-17", "february-17-2026"),
    (43692, "2026-02-18", "february-18-2026"),
    (43705, "2026-02-19", "february-19-2026"),
    (43721, "2026-02-20", "february-20-2026"),
    (43737, "2026-02-23", "february-20-2026-2"),
    (43767, "2026-02-25", "february-23-2026"),
    (43783, "2026-02-26", "february-26-2026"),
    (43793, "2026-02-27", "february-27-2026"),
)

MEASUREMENTS = {
    "2026-02-02": (1495, "01:10:45"), "2026-02-03": (1462, "01:15:29"),
    "2026-02-04": (1323, "01:12:19"), "2026-02-05": (1557, "01:12:44"),
    "2026-02-06": (1360, "01:09:54"), "2026-02-09": (1279, "01:06:52"),
    "2026-02-10": (1519, "01:23:00"), "2026-02-11": (1479, "01:19:13"),
    "2026-02-12": (1356, "01:12:49"), "2026-02-13": (1507, "01:12:21"),
    "2026-02-17": (1378, "01:13:42"), "2026-02-18": (1594, "01:15:09"),
    "2026-02-19": (1632, "01:18:12"), "2026-02-20": (2042, "01:30:34"),
    "2026-02-23": (1298, "01:08:19"), "2026-02-25": (1771, "01:16:36"),
    "2026-02-26": (1438, "01:14:55"), "2026-02-27": (1485, "01:09:53"),
}

TOPIC_EVIDENCE = {
    "2026-02-02": (("SUPPORT_RESISTANCE", 30, "00:10:04"), ("RANGE_BREAKOUT", 9, "00:09:45"), ("VWAP_EMA", 3, "00:03:43")),
    "2026-02-03": (("SUPPORT_RESISTANCE", 27, "00:06:02"), ("RANGE_BREAKOUT", 7, "00:01:08"), ("TREND_STRUCTURE", 6, "00:45:43")),
    "2026-02-04": (("SUPPORT_RESISTANCE", 28, "00:08:51"), ("RANGE_BREAKOUT", 12, "00:21:47"), ("TREND_STRUCTURE", 2, "01:09:04")),
    "2026-02-05": (("SUPPORT_RESISTANCE", 14, "00:11:36"), ("RISK_STOP", 7, "00:00:16"), ("RANGE_BREAKOUT", 3, "00:14:09")),
    "2026-02-06": (("SUPPORT_RESISTANCE", 22, "00:07:52"), ("RANGE_BREAKOUT", 6, "00:05:18"), ("RISK_STOP", 5, "00:03:24")),
    "2026-02-09": (("SUPPORT_RESISTANCE", 27, "00:03:55"), ("RISK_STOP", 4, "00:02:20"), ("RANGE_BREAKOUT", 4, "00:19:04")),
    "2026-02-10": (("SUPPORT_RESISTANCE", 43, "00:06:35"), ("RANGE_BREAKOUT", 20, "00:04:41"), ("VWAP_EMA", 6, "00:18:56")),
    "2026-02-11": (("SUPPORT_RESISTANCE", 39, "00:05:34"), ("RANGE_BREAKOUT", 13, "00:09:02"), ("RISK_STOP", 4, "00:00:14")),
    "2026-02-12": (("SUPPORT_RESISTANCE", 30, "00:06:57"), ("RANGE_BREAKOUT", 11, "00:02:09"), ("VWAP_EMA", 1, "00:04:04")),
    "2026-02-13": (("SUPPORT_RESISTANCE", 41, "00:04:10"), ("RANGE_BREAKOUT", 27, "00:07:27"), ("RISK_STOP", 6, "00:05:11")),
    "2026-02-17": (("SUPPORT_RESISTANCE", 48, "00:06:15"), ("RANGE_BREAKOUT", 6, "00:05:04"), ("RISK_STOP", 2, "00:00:25")),
    "2026-02-18": (("SUPPORT_RESISTANCE", 42, "00:00:57"), ("RANGE_BREAKOUT", 19, "00:00:48"), ("VWAP_EMA", 8, "00:01:30")),
    "2026-02-19": (("SUPPORT_RESISTANCE", 57, "00:01:25"), ("RANGE_BREAKOUT", 16, "00:01:32"), ("VWAP_EMA", 9, "00:01:17")),
    "2026-02-20": (("RANGE_BREAKOUT", 14, "00:02:35"), ("SUPPORT_RESISTANCE", 12, "00:06:21"), ("TREND_STRUCTURE", 8, "00:20:11")),
    "2026-02-23": (("SUPPORT_RESISTANCE", 32, "00:05:56"), ("RANGE_BREAKOUT", 6, "00:06:12"), ("RISK_STOP", 3, "00:41:18")),
    "2026-02-25": (("RANGE_BREAKOUT", 22, "00:00:42"), ("SUPPORT_RESISTANCE", 21, "00:05:10"), ("RISK_STOP", 6, "00:00:10")),
    "2026-02-26": (("SUPPORT_RESISTANCE", 48, "00:07:11"), ("RANGE_BREAKOUT", 7, "00:03:15"), ("RISK_STOP", 3, "00:04:50")),
    "2026-02-27": (("SUPPORT_RESISTANCE", 41, "00:02:49"), ("RANGE_BREAKOUT", 10, "00:34:28"), ("RISK_STOP", 8, "00:23:30")),
}

FINDING_TEXT = {
    "SUPPORT_RESISTANCE": "Level discussion is recurring source evidence, but a level becomes a candidate feature only after independently measured test, acceptance or rejection, and subsequent room.",
    "RANGE_BREAKOUT": "Range and breakout discussion supports a candidate state-transition label; it does not establish that a break held, failed, or was tradable.",
    "RISK_STOP": "Risk and stop discussion supports retaining explicit invalidation as a research field; the transcript alone cannot determine executable stop quality.",
    "VWAP_EMA": "VWAP and moving-average discussion supports using location and interaction as contextual fields, not standalone directional rules.",
    "TREND_STRUCTURE": "Trend-structure discussion supports distinguishing continuation from congestion or transition in replay, rather than classifying direction from commentary alone.",
}

HYPOTHESIS_TEXT = {
    "SUPPORT_RESISTANCE": "DTS-HYP-LEVEL-ACCEPTANCE-001",
    "RANGE_BREAKOUT": "DTS-HYP-RANGE-RESOLUTION-001",
    "RISK_STOP": "DTS-HYP-INVALIDATION-DISCIPLINE-001",
    "VWAP_EMA": "DTS-HYP-CONTEXTUAL-MA-001",
    "TREND_STRUCTURE": "DTS-HYP-TRANSITION-STRUCTURE-001",
}


def record_for(post_id: int, day: str, slug: str) -> dict:
    source_url = f"https://daytradespy.com/{post_id}/trading-room-video-recording-{slug}/"
    cue_count, endpoint = MEASUREMENTS[day]
    topics = TOPIC_EVIDENCE[day]
    findings = [FINDING_TEXT[label] for label, _, _ in topics]
    return {
        "schema_version": "daytradespy-record.v2",
        "recording": {
            "post_id": post_id,
            "title": f"Trading Room Video Recording - {day}",
            "publication_date": day,
            "duration_seconds": sum(int(value) * factor for value, factor in zip(endpoint.split(":"), (3600, 60, 1))),
            "source_url": source_url,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer_version": "authorized-browser-access-audit.v1",
            "analysis_protocol_version": "2026-07-22.1",
            "transcript": {
                "availability": "AUTHORIZED_BROWSER_FULL_TRANSCRIPT",
                "completeness_pct": 100,
                "path": "",
                "timestamps_preserved": True,
                "speaker_attribution_available": False,
            },
            "transcript_probe": {
                "source": "AUTHORIZED_BROWSER_RUNTIME",
                "raw_transcript_persisted": False,
                "first_timestamp": "00:00:00",
                "last_timestamp": endpoint,
                "cue_count": cue_count,
                "coverage_note": "The authenticated caption stream was measured from its first cue through its final cue. Raw transcript text was not retained.",
            },
            "visual_review": {"coverage_pct": 0, "status": "UNAVAILABLE_EVIDENCE", "chart_references": []},
        },
        "evidence_quality": {
            "transcript_completeness_pct": 100,
            "trade_details_captured_pct": 0,
            "ledger_reconciliation_pct": 0,
            "underlying_market_data_pct": 0,
            "option_excursion_data_pct": 0,
            "overall_grade": "TRANSCRIPT_COMPLETE_VISUAL_UNAVAILABLE",
            "tier": "C",
        },
        "timeline": [{
            "timestamp": timestamp,
            "classification": "SOURCE_MEASUREMENT",
            "fact_classification": "SOURCE_MEASUREMENT",
            "claim": f"Timestamped transcript topic measurement identified {count} {label.lower().replace('_', ' ')} references; first occurrence at {timestamp}.",
            "chart_reference": "UNKNOWN",
        } for label, count, timestamp in topics] + [{
            "timestamp": endpoint,
            "classification": "SOURCE_MEASUREMENT",
            "fact_classification": "SOURCE_MEASUREMENT",
            "claim": f"Authorized browser measurement verified {cue_count} timestamped transcript cues from 00:00:00 through {endpoint}. Raw transcript text was not retained.",
            "chart_reference": "UNKNOWN",
        }],
        "claims": [{
            "id": f"DTS-{day.replace('-', '')}-C{index:02d}",
            "timestamp": timestamp,
            "label": label,
            "status": "NEEDS_INSTRUMENTATION",
            "fact_classification": "SOURCE_MEASUREMENT",
            "claim": f"The full timestamped transcript contains {count} measured references to {label.lower().replace('_', ' ')}, first observed at {timestamp}. This is source-topic evidence, not a verified entry, exit, or outcome claim.",
            "forward_outcomes": {f"{minutes}m": "UNAVAILABLE_EVIDENCE" for minutes in (1, 3, 5, 10, 15)} | {"remainder_session": "UNAVAILABLE_EVIDENCE"},
            "disconfirming_evidence_required": "Timestamped underlying bars, visual review, and independently reconciled execution evidence.",
        } for index, (label, count, timestamp) in enumerate(topics, start=1)],
        "derived_findings": [{
            "timestamp": timestamp,
            "topic": label,
            "finding": FINDING_TEXT[label],
            "evidence_basis": f"{count} timestamped transcript references, first observed at {timestamp}.",
            "classification": "DERIVED_RESEARCH_FINDING",
        } for label, count, timestamp in topics],
        "hypothesis_references": [{
            "id": HYPOTHESIS_TEXT[label],
            "status": "NEEDS_INSTRUMENTATION",
            "source_topic": label,
            "supporting_recordings": [post_id],
        } for label, _, _ in topics],
        "market_state_timeline": [{
            "timestamp": "UNKNOWN",
            "market_direction": "UNKNOWN",
            "volatility": "UNKNOWN",
            "trend_strength": "UNKNOWN",
            "vwap_state": "UNKNOWN",
            "room_to_target": "UNKNOWN",
        }],
        "counterfactuals": [{
            "type": "UNAVAILABLE_EVIDENCE",
            "timestamp": "UNKNOWN",
            "detail": "Counterfactual impact cannot be assessed without timestamped replay, underlying bars, executable option marks, and friction.",
        }],
        "ledger_reconciliation": {
            "source_reported_trades": 0,
            "mcleod_alpha_trades": "UNAVAILABLE_EVIDENCE",
            "confirmed_matches": [],
            "possible_matches": [],
            "conflicts": [],
            "unavailable_evidence": ["No canonical ledger mapping or option-excursion data was available."],
        },
        "adversarial_review": {
            "why_wrong": "Topic frequency can reflect education, commentary, or a failed condition; it cannot establish setup quality or expectancy.",
            "contradicting_evidence": "UNAVAILABLE_EVIDENCE",
            "profitable_trades_blocked": "UNAVAILABLE_EVIDENCE",
        },
        "expected_value_tracking": {
            "confidence": "LOW",
            "evidence_count": len(topics),
            "current_lifecycle_stage": "OBSERVATION_ONLY",
            "replay_improvement": "UNAVAILABLE_EVIDENCE",
        },
        "reported_trades": [],
        "instrumentation_gaps": ["Full transcript review", "Visual review", "Timestamped underlying bars", "Option execution and excursion data"],
        "final_governance_decision": "RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE",
    }


def report_for(record: dict) -> str:
    recording = record["recording"]
    findings = record["derived_findings"]
    observations = [
        f"- The transcript repeatedly returned to {finding['topic'].lower().replace('_', ' ')} ({finding['evidence_basis']}). {finding['finding']}"
        for finding in findings
    ]
    return "\n".join((
        f"# McLeod Alpha Research Report: {recording['publication_date']} Trading Room",
        "",
        "## Scope and Evidence",
        "",
        f"External qualitative research based on the Day Trade SPY {recording['publication_date']} trading-room recording. The authorized Vimeo transcript was measured through {recording['transcript_probe']['last_timestamp']} ({recording['transcript_probe']['cue_count']} cues; 100% coverage). This document retains synthesized observations only, not source transcript content.",
        "",
        "## Observations",
        "",
        *observations,
        "- Visual review, underlying bars, option execution data, and a canonical ledger mapping remain unavailable; no source commentary is treated as a verified trade outcome.",
        "",
        "## Research Implications",
        "",
        "1. Test level interaction, range resolution, and invalidation as separate replay fields; topic discussion is not an entry signal.",
        "2. Require independently measured test, close-through, retest, and hold/fail behavior before promoting any source theme to a candidate setup label.",
        "3. Evaluate the candidate features with timestamped underlying bars, option marks, and negative-control sessions before considering expectancy or execution quality.",
        "",
        "## Decision",
        "",
        "No live entry, exit, stop, sizing, direction, or other trading-policy changes are authorized from this external research. The candidate labels require replay, out-of-sample validation, and risk review before consideration.",
        "",
    ))


def main() -> int:
    root = Path("data/research/daytradespy")
    records_dir = root / "records"
    docs_dir = Path("docs/research")
    records_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    for post_id, day, slug in RECORDINGS:
        record = record_for(post_id, day, slug)
        report = report_for(record)
        record_path = records_dir / f"{day}.json"
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (docs_dir / f"{day}_daytradespy_trading_room_research.md").write_text(report, encoding="utf-8")
        write_output_bundle(record, root / "output")
        aggregate_record(record, root)
        register_record(record_path, root / "recording_registry.json")
    print(f"Wrote {len(RECORDINGS)} February 2026 access-audit records and reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())