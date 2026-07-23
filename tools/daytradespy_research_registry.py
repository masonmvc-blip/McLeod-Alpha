#!/usr/bin/env python3
"""Maintain research-only Day Trade SPY ingestion governance artifacts.

This module deliberately contains no production-trading integration. It tracks
archive coverage, protocol versions, evidence quality, and research queues.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "daytradespy-research-registry.v1"
ANALYSIS_PROTOCOL_VERSION = "2026-07-22.1"
EVIDENCE_GRADE = "B-"
EVIDENCE_QUALITY = {
    "transcript_completeness_pct": 100,
    "trade_details_captured_pct": 70,
    "ledger_reconciliation_pct": 90,
    "underlying_market_data_pct": 100,
    "option_excursion_data_pct": 20,
    "overall_grade": EVIDENCE_GRADE,
}
GOVERNANCE_DECISION = "RESEARCH_ONLY_NO_LIVE_BEHAVIOR_CHANGE"


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _report_path_for(recording_date: str) -> str:
    return f"docs/research/{recording_date[:10]}_daytradespy_trading_room_research.md"


def build_registry(manifest: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge archive recordings into a chronological, protocol-aware registry."""
    existing_by_post_id = {
        int(record["post_id"]): record
        for record in (existing or {}).get("recordings", [])
        if isinstance(record, dict) and record.get("post_id") is not None
    }
    recordings: list[dict[str, Any]] = []
    for source in manifest.get("recordings", []):
        if not isinstance(source, dict) or source.get("post_id") is None:
            continue
        post_id = int(source["post_id"])
        previous = existing_by_post_id.get(post_id, {})
        recording_date = str(source.get("recording_date") or "")
        analysis_protocol = str(previous.get("analysis_protocol_version") or ANALYSIS_PROTOCOL_VERSION)
        prior_status = str(previous.get("analysis_status") or source.get("analysis_status") or "pending")
        recordings.append(
            {
                "post_id": post_id,
                "recording_date": recording_date,
                "title": str(source.get("title") or ""),
                "source_url": str(source.get("source_url") or ""),
                "duration_seconds": previous.get("duration_seconds"),
                "transcript": {
                    "availability": str(previous.get("transcript", {}).get("availability") or source.get("transcript_status") or "pending"),
                    "completeness_pct": int(previous.get("transcript", {}).get("completeness_pct") or 0),
                    "path": str(previous.get("transcript", {}).get("path") or source.get("transcript_path") or ""),
                    "timestamps_preserved": bool(previous.get("transcript", {}).get("timestamps_preserved", False)),
                    "speaker_attribution_available": bool(previous.get("transcript", {}).get("speaker_attribution_available", False)),
                },
                "report_path": str(previous.get("report_path") or _report_path_for(recording_date)),
                "analysis_protocol_version": analysis_protocol,
                "analysis_status": prior_status,
                "reviewed_at": previous.get("reviewed_at"),
                "evidence_quality": previous.get("evidence_quality"),
                "machine_record_path": previous.get("machine_record_path"),
                "output_bundle_path": previous.get("output_bundle_path"),
                "governance_decision": GOVERNANCE_DECISION,
                "reprocess_required": analysis_protocol != ANALYSIS_PROTOCOL_VERSION,
            }
        )
    recordings.sort(key=lambda item: (item["recording_date"], item["post_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "governance_decision": GOVERNANCE_DECISION,
        "recording_count": len(recordings),
        "recordings": recordings,
    }


def bootstrap_governance(root: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    """Create idempotent registry artifacts; existing records are never discarded."""
    registry_path = root / "recording_registry.json"
    registry = build_registry(manifest, _read_json(registry_path, {}))
    for recording in registry["recordings"]:
        if recording["analysis_status"] == "pending" and Path(recording["report_path"]).exists():
            recording["analysis_status"] = "legacy_report_available"
    _write_json(registry_path, registry)
    artifacts = {
        "recording_registry": registry_path,
        "hypothesis_registry": root / "hypothesis_registry.json",
        "claim_registry": root / "claim_registry.json",
        "instrumentation_backlog": root / "instrumentation_backlog.json",
        "unresolved_conflicts": root / "unresolved_conflicts.json",
        "source_scorecard": root / "source_scorecard.json",
        "knowledge_graph": root / "knowledge_graph.json",
        "evolution_log": root / "evolution_log.json",
    }
    defaults = {
        "hypothesis_registry": {"schema_version": "daytradespy-hypothesis-registry.v1", "hypotheses": []},
        "claim_registry": {"schema_version": "daytradespy-claim-registry.v1", "claims": []},
        "instrumentation_backlog": {
            "schema_version": "daytradespy-instrumentation-backlog.v1",
            "items": [
                {
                    "id": "DTS-INST-001",
                    "priority": "P0",
                    "status": "NEEDS_INSTRUMENTATION",
                    "gap": "Option bid, ask, mark, MFE, MAE, high/low timestamps, and Greeks are insufficient for exit-quality research.",
                    "why": "Without executable intratrade excursion data, source or ledger exits cannot support valid missed-opportunity conclusions.",
                    "production_change_authorized": False,
                }
            ],
        },
        "unresolved_conflicts": {"schema_version": "daytradespy-unresolved-conflicts.v1", "conflicts": []},
        "source_scorecard": {
            "schema_version": "daytradespy-source-scorecard.v1",
            "source": "Day Trade SPY",
            "assessment_rule": "Measure incremental replay value of claims; do not score reported winning trades as source quality.",
            "observations": [],
        },
        "knowledge_graph": {"schema_version": "daytradespy-knowledge-graph.v1", "relationships": []},
        "evolution_log": {
            "schema_version": "daytradespy-evolution-log.v1",
            "governance_decision": GOVERNANCE_DECISION,
            "promotions": [],
        },
    }
    for name, path in artifacts.items():
        if name != "recording_registry" and not path.exists():
            _write_json(path, defaults[name])
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/research/daytradespy/archive_manifest.json"))
    parser.add_argument("--root", type=Path, default=Path("data/research/daytradespy"))
    args = parser.parse_args(argv)
    manifest = _read_json(args.manifest, {})
    if not manifest.get("recordings"):
        raise SystemExit(f"No recordings in manifest: {args.manifest}")
    artifacts = bootstrap_governance(args.root, manifest)
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())