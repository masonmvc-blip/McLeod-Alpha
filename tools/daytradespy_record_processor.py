#!/usr/bin/env python3
"""Validate and register replay-ready, research-only Day Trade SPY records."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION
else:
    from daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION


REQUIRED_RECORD_FIELDS = {
    "schema_version", "recording", "evidence_quality", "timeline", "claims", "reported_trades",
    "ledger_reconciliation", "market_state_timeline", "counterfactuals", "hypothesis_references",
    "instrumentation_gaps", "final_governance_decision",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object in {path}")
    return payload


def validate_record(record: dict[str, Any]) -> None:
    missing = REQUIRED_RECORD_FIELDS.difference(record)
    if missing:
        raise ValueError(f"Missing required record fields: {', '.join(sorted(missing))}")
    recording = record["recording"]
    if recording.get("analysis_protocol_version") != ANALYSIS_PROTOCOL_VERSION:
        raise ValueError("Record protocol version does not match the active protocol")
    if record["final_governance_decision"] != GOVERNANCE_DECISION:
        raise ValueError("Research record must retain the research-only governance decision")
    if record["evidence_quality"].get("option_excursion_data_pct", 0) < 100:
        if not record["instrumentation_gaps"]:
            raise ValueError("Incomplete option excursion data requires an instrumentation gap")


def coverage_complete(record: dict[str, Any]) -> bool:
    transcript = record["recording"].get("transcript", {})
    visual_review = record["recording"].get("visual_review", {})
    return transcript.get("completeness_pct") == 100 and visual_review.get("coverage_pct") == 100


def evidence_tier(record: dict[str, Any]) -> str:
    """Classify usable evidence without conflating partial coverage with a blocker."""
    transcript_pct = record["recording"].get("transcript", {}).get("completeness_pct", 0)
    visual = record["recording"].get("visual_review", {})
    visual_complete = visual.get("coverage_pct") == 100
    visual_available = visual.get("status") not in {"UNAVAILABLE_EVIDENCE", "PENDING", "UNKNOWN"}
    if transcript_pct == 100 and visual_complete:
        return "A"
    if transcript_pct >= 90 and visual_complete:
        return "B"
    if transcript_pct >= 90 and not visual_available:
        return "C"
    if transcript_pct >= 50:
        return "D"
    return "E"


def register_record(record_path: Path, registry_path: Path) -> None:
    record = load_json(record_path)
    validate_record(record)
    registry = load_json(registry_path)
    post_id = int(record["recording"]["post_id"])
    record["evidence_quality"]["tier"] = evidence_tier(record)
    for item in registry["recordings"]:
        if int(item["post_id"]) == post_id:
            item.update(
                {
                    "analysis_status": "complete" if coverage_complete(record) else "coverage_incomplete",
                    "reviewed_at": record["recording"]["reviewed_at"],
                    "duration_seconds": record["recording"].get("duration_seconds"),
                    "evidence_quality": record["evidence_quality"],
                    "analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION,
                    "reprocess_required": False,
                    "machine_record_path": str(record_path),
                    "output_bundle_path": f"data/research/daytradespy/output/{post_id}",
                    "transcript": record["recording"]["transcript"],
                }
            )
            break
    else:
        raise ValueError(f"Recording {post_id} is not in the archive registry")
    registry["generated_at"] = datetime.now(timezone.utc).isoformat()
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def reset_record(post_id: int, registry_path: Path) -> None:
    registry = load_json(registry_path)
    for item in registry["recordings"]:
        if int(item["post_id"]) == post_id:
            item.update(
                {
                    "analysis_status": "pending",
                    "reviewed_at": None,
                    "duration_seconds": None,
                    "evidence_quality": None,
                    "machine_record_path": None,
                    "transcript": {
                        "availability": "pending",
                        "completeness_pct": 0,
                        "path": "",
                        "timestamps_preserved": False,
                        "speaker_attribution_available": False,
                    },
                }
            )
            registry["generated_at"] = datetime.now(timezone.utc).isoformat()
            registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return
    raise ValueError(f"Recording {post_id} is not in the archive registry")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, nargs="?")
    parser.add_argument("--registry", type=Path, default=Path("data/research/daytradespy/recording_registry.json"))
    parser.add_argument("--reset-post-id", type=int)
    args = parser.parse_args()
    if args.reset_post_id is not None:
        reset_record(args.reset_post_id, args.registry)
        print(f"Reset pending record: {args.reset_post_id}")
        return 0
    if args.record is None:
        parser.error("record is required unless --reset-post-id is provided")
    register_record(args.record, args.registry)
    print(f"Registered research-only record: {args.record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())