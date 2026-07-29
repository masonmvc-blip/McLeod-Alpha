#!/usr/bin/env python3
"""Build evidence-honest v2 records from existing substantive research reports."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

GOVERNANCE = "RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE"
PROTOCOL = "2026-07-22.1"


def section(text: str, heading_pattern: str) -> str:
    match = re.search(
        rf"(?ms)^##+\s+(?:{heading_pattern})\s*$\n(.*?)(?=^##+\s|\Z)", text
    )
    return match.group(1).strip() if match else ""


def table_rows(body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows[1:] if len(rows) > 1 else []


def bullets(body: str) -> list[str]:
    found: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", line)
        if match:
            found.append(match.group(1).strip())
    return found


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def probe_from_report(text: str, transcript: dict[str, Any]) -> dict[str, Any]:
    cue_match = re.search(r"([\d,]+)\s+cues", text, re.I)
    spans = re.findall(
        r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*(?:through|to|-)\s*"
        r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)",
        text,
        re.I,
    )
    first, last = spans[0] if spans else ("UNKNOWN", "UNKNOWN")
    availability = str(transcript.get("availability", "UNKNOWN"))
    return {
        "source": "EXISTING_SOURCE_DERIVED_REPORT_AND_REGISTRY_BACKFILL",
        "cue_count": int(cue_match.group(1).replace(",", "")) if cue_match else 0,
        "first_timestamp": first,
        "last_timestamp": last,
        "raw_transcript_persisted": False,
        "coverage_note": (
            "Machine record backfilled from the existing substantive report and "
            f"registry evidence; transcript availability retained as {availability}. "
            "No new source facts were inferred."
        ),
    }


def derive_observations(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    timeline_body = section(text, r"(?:Timestamped\s+)?Evidence Timeline")
    rows = table_rows(timeline_body)
    observations: list[dict[str, Any]] = []
    if rows:
        for row in rows[:12]:
            timestamp = row[0] if row else "UNKNOWN"
            evidence = row[1] if len(row) > 1 else ""
            interpretation = row[2] if len(row) > 2 else ""
            observations.append(
                {
                    "timestamp": timestamp or "UNKNOWN",
                    "classification": "REPORT_DERIVED_SOURCE_SUMMARY",
                    "claim": compact(
                        evidence
                        + (f" Research interpretation: {interpretation}" if interpretation else "")
                    ),
                }
            )
    else:
        candidates: list[str] = []
        for heading in (
            r"[^\n]*(?:Entries|Entry|Trade|Outcome|Management|Setup|Decision Logic)[^\n]*",
            r"Executive Assessment",
        ):
            candidates.extend(bullets(section(text, heading)))
            if candidates:
                break
        if not candidates:
            executive = compact(section(text, r"(?:Executive Assessment|Scope and Evidence)"))
            if executive:
                candidates = [executive.split("\n\n")[0]]
        for item in candidates[:8]:
            observations.append(
                {
                    "timestamp": "UNKNOWN",
                    "classification": "REPORT_DERIVED_SOURCE_SUMMARY",
                    "claim": compact(item),
                }
            )
    return observations, [item["claim"] for item in observations]


def build_record(item: dict[str, Any], report_text: str) -> dict[str, Any]:
    post_id = int(item["post_id"])
    date = str(item["recording_date"])[:10]
    evidence = dict(item.get("evidence_quality") or {})
    evidence.setdefault("transcript_completeness_pct", 0)
    evidence.setdefault("trade_details_captured_pct", 0)
    evidence.setdefault("ledger_reconciliation_pct", 0)
    evidence.setdefault("underlying_market_data_pct", 0)
    evidence.setdefault("option_excursion_data_pct", 0)
    evidence.setdefault("overall_grade", "UNAVAILABLE_EVIDENCE")
    transcript = dict(item.get("transcript") or {})
    transcript.setdefault("availability", "UNKNOWN")
    transcript.setdefault("completeness_pct", 0)
    transcript.setdefault("path", "")
    transcript.setdefault("timestamps_preserved", False)
    transcript.setdefault("speaker_attribution_available", False)

    observations, claim_texts = derive_observations(report_text)
    tier_e = evidence.get("tier") == "E"
    if tier_e and not observations:
        observations = [
            {
                "timestamp": "UNKNOWN",
                "classification": "UNAVAILABLE_EVIDENCE",
                "claim": "The existing report establishes an access or source-evidence gap; no trade content is inferred.",
            }
        ]
    claims = []
    if not tier_e:
        for index, observation in enumerate(observations[:5], 1):
            claims.append(
                {
                    "id": f"DTS-{date.replace('-', '')}-P{post_id}-C{index:02d}",
                    "timestamp": observation["timestamp"],
                    "label": "REPORT_BACKED_OBSERVATION",
                    "fact_classification": "REPORT_DERIVED_SOURCE_SUMMARY",
                    "status": "SOURCE_SUPPORTED_BY_EXISTING_REPORT",
                    "claim": observation["claim"],
                    "forward_outcomes": {
                        "1m": "UNKNOWN",
                        "3m": "UNKNOWN",
                        "5m": "UNKNOWN",
                        "10m": "UNKNOWN",
                        "15m": "UNKNOWN",
                        "remainder_session": "UNKNOWN",
                    },
                    "disconfirming_evidence_required": (
                        "Original transcript timestamps, visual review, executable option path, and ledger."
                    ),
                }
            )

    trade_terms = re.compile(
        r"\b(?:calls?|puts?|trade|position|entry|exit|fill|target|stop|OMG)\b", re.I
    )
    reported_trades = []
    if not tier_e:
        for observation in observations:
            if not trade_terms.search(observation["claim"]):
                continue
            reported_trades.append(
                {
                    "source_trade_id": (
                        f"DTS-{date.replace('-', '')}-P{post_id}-T"
                        f"{len(reported_trades) + 1:02d}"
                    ),
                    "type": "REPORT_DERIVED_TRADE_OBSERVATION",
                    "setup": observation["claim"],
                    "entry_time": observation["timestamp"],
                    "entry_premium": None,
                    "exit_time": None,
                    "exit_premium": None,
                    "stop_or_invalidation": (
                        "Retain the report text; normalized lifecycle fields unavailable."
                    ),
                }
            )
            if len(reported_trades) == 8:
                break

    hypothesis_text: list[str] = []
    for heading in (
        r"(?:Falsifiable Replay|Candidate) Hypotheses",
        r"Reusable Research Observations",
    ):
        hypothesis_text = bullets(section(report_text, heading))
        if hypothesis_text:
            break
    counterfactuals = [
        {
            "timestamp": "UNKNOWN",
            "type": "REPORT_DERIVED_REPLAY_HYPOTHESIS",
            "detail": compact(value),
        }
        for value in hypothesis_text[:5]
    ]
    if not counterfactuals:
        counterfactuals = [
            {
                "timestamp": "UNKNOWN",
                "type": "EVIDENCE_COMPLETION",
                "detail": "Retain the report as research-only until independent replay evidence is available.",
            }
        ]

    return {
        "schema_version": "daytradespy-record.v2",
        "recording": {
            "analysis_protocol_version": PROTOCOL,
            "post_id": post_id,
            "title": item["title"],
            "publication_date": date,
            "post_publication_date": date,
            "source_url": item["source_url"],
            "duration_seconds": item.get("duration_seconds"),
            "reviewed_at": item.get("reviewed_at") or "2026-07-28T00:00:00+00:00",
            "reviewer_version": "report-backed-machine-record-backfill.v1",
            "report_path": item["report_path"],
            "transcript": transcript,
            "transcript_probe": probe_from_report(report_text, transcript),
            "visual_review": {
                "status": "UNAVAILABLE_EVIDENCE",
                "coverage_pct": 0,
                "chart_references": [],
            },
        },
        "evidence_quality": evidence,
        "timeline": observations,
        "claims": claims,
        "reported_trades": reported_trades,
        "ledger_reconciliation": {
            "source_reported_trades": len(reported_trades),
            "mcleod_alpha_trades": "UNAVAILABLE_EVIDENCE",
            "confirmed_matches": [],
            "possible_matches": [],
            "conflicts": [
                "Backfill preserves report language without inventing normalized lifecycle fields."
            ],
            "unavailable_evidence": [
                "Independent ledger",
                "Visual chart review",
                "Executable underlying and option paths",
                "Greeks, MFE, MAE, slippage, and complete fees",
            ],
        },
        "market_state_timeline": [
            {
                "timestamp": "UNKNOWN",
                "market_direction": "UNKNOWN",
                "trend_strength": "UNKNOWN",
                "volatility": "UNKNOWN",
                "vwap_state": "UNKNOWN",
                "room_to_target": "UNKNOWN",
                "evidence": (
                    claim_texts[0]
                    if claim_texts
                    else "No source-derived market-state claim available."
                ),
            }
        ],
        "counterfactuals": counterfactuals,
        "hypothesis_references": [claim["id"] for claim in claims],
        "expected_value_tracking": {
            "confidence": "NONE" if tier_e else "LOW",
            "evidence_count": len(claims),
            "current_lifecycle_stage": (
                "OBSERVATION_ONLY" if tier_e else "SOURCE_DERIVED_HYPOTHESES"
            ),
            "replay_improvement": "PENDING",
        },
        "instrumentation_gaps": [
            "Independent ledger",
            "Visual chart review",
            "Executable underlying and option paths",
            "Greeks, MFE, MAE, slippage, and complete fees",
        ],
        "final_governance_decision": GOVERNANCE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("data/research/daytradespy/recording_registry.json"))
    parser.add_argument("--records-dir", type=Path, default=Path("data/research/daytradespy/records"))
    parser.add_argument("--post-id", type=int, action="append", required=True)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    by_id = {int(item["post_id"]): item for item in registry["recordings"]}
    args.records_dir.mkdir(parents=True, exist_ok=True)
    for post_id in args.post_id:
        item = by_id[post_id]
        report_path = Path(item["report_path"])
        report_text = report_path.read_text(encoding="utf-8")
        record = build_record(item, report_text)
        date = str(item["recording_date"])[:10]
        output = args.records_dir / f"{date}.json"
        if output.exists():
            existing = json.loads(output.read_text(encoding="utf-8"))
            existing_post = int(existing["recording"]["post_id"])
            if existing_post != post_id:
                output = args.records_dir / f"{date}_post-{post_id}.json"
        output.write_text(json.dumps(record, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
