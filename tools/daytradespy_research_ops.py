#!/usr/bin/env python3
"""Research-only Day Trade SPY evidence normalization and registry aggregation."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION
else:
    from daytradespy_research_registry import ANALYSIS_PROTOCOL_VERSION, GOVERNANCE_DECISION


FORWARD_WINDOWS = (1, 3, 5, 10, 15)
REQUIRED_OUTPUTS = ("transcript.md", "record_summary.md", "report.md", "handoff.md", "evidence.json", "claims.json", "observations.json", "hypotheses.json", "lessons.json", "entities.json", "relationships.json", "trade_comparison.csv", "replay_candidates.json", "unknowns.json", "recording_metadata.json", "claim_registry_update.json")
VTT_CUE = re.compile(r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})")


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_vtt(vtt_text: str, recording_post_id: int) -> list[dict[str, Any]]:
    """Convert WebVTT to timestamp-preserving cues without retaining video."""
    cues: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", vtt_text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if VTT_CUE.fullmatch(line)), None)
        if timing_index is None:
            continue
        match = VTT_CUE.fullmatch(lines[timing_index])
        assert match is not None
        text = " ".join(lines[timing_index + 1:])
        speaker, separator, spoken = text.partition(":")
        cues.append({
            "recording_post_id": recording_post_id,
            "start": match.group("start"), "end": match.group("end"),
            "speaker": speaker if separator and len(speaker) < 50 else "UNKNOWN",
            "text": spoken.strip() if separator and len(speaker) < 50 else text,
            "chart_reference": "UNKNOWN",
        })
    return cues


def load_underlying_bars(path: Path) -> list[dict[str, Any]]:
    """Load explicit CSV bars; unavailable paths remain unavailable evidence."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"timestamp", "close"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Underlying bar CSV requires timestamp and close columns")
    return rows


def forward_outcomes(observation_time: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate only supplied underlying bars, with no inferred option results."""
    if not bars:
        return {f"{minutes}m": "UNAVAILABLE_EVIDENCE" for minutes in FORWARD_WINDOWS} | {"remainder_session": "UNAVAILABLE_EVIDENCE"}
    parsed = [(datetime.fromisoformat(row["timestamp"]), float(row["close"])) for row in bars]
    start_time = datetime.fromisoformat(observation_time)
    prior = next((close for timestamp, close in parsed if timestamp >= start_time), None)
    if prior is None:
        return {f"{minutes}m": "UNAVAILABLE_EVIDENCE" for minutes in FORWARD_WINDOWS} | {"remainder_session": "UNAVAILABLE_EVIDENCE"}
    result: dict[str, Any] = {}
    for minutes in FORWARD_WINDOWS:
        target = start_time + timedelta(minutes=minutes)
        close = next((price for timestamp, price in parsed if timestamp >= target), None)
        result[f"{minutes}m"] = "UNAVAILABLE_EVIDENCE" if close is None else {"underlying_return": round((close - prior) / prior, 6), "close": close}
    remaining = [price for timestamp, price in parsed if timestamp >= start_time]
    result["remainder_session"] = "UNAVAILABLE_EVIDENCE" if not remaining else {"high": max(remaining), "low": min(remaining), "close": remaining[-1]}
    return result


def _output_directory(record: dict[str, Any], root: Path) -> Path:
    return root / str(record["recording"]["post_id"])


def write_output_bundle(record: dict[str, Any], root: Path) -> Path:
    """Write the mandated review bundle from an already validated evidence record."""
    directory = _output_directory(record, root)
    directory.mkdir(parents=True, exist_ok=True)
    metadata = record["recording"]
    visual = metadata.get("visual_review", {"coverage_pct": 0, "status": "PENDING"})
    coverage = metadata["transcript"].get("completeness_pct", 0)
    probe = metadata.get("transcript_probe", {})
    cutoff = probe.get("last_timestamp", "UNKNOWN")
    transcript_artifact = "\n".join((
        f"# Transcript Metadata: {metadata['title']}", "", f"- Recording ID: {metadata['post_id']}",
        f"- Recording date: {metadata.get('publication_date', 'UNKNOWN')}", f"- Source URL: {metadata.get('source_url', 'UNKNOWN')}",
        f"- Player duration seconds: {metadata.get('duration_seconds', 'UNKNOWN')}", f"- Transcript start: {probe.get('first_timestamp', 'UNKNOWN')}",
        f"- Transcript cutoff: {cutoff}", f"- Transcript coverage: {coverage}%", f"- Cue count: {probe.get('cue_count', 'UNKNOWN')}",
        f"- Evidence tier: {record['evidence_quality'].get('tier', 'UNKNOWN')}", f"- Extraction method: {probe.get('source', 'UNAVAILABLE_EVIDENCE')}", f"- Extraction timestamp: {metadata.get('reviewed_at', 'UNKNOWN')}", "",
        "Transcript text is not retained because no authorized transcript export is available.", f"UNKNOWN_AFTER_CUTOFF: {cutoff}", "",
    ))
    report = "\n".join((
        f"# {metadata['title']}", "", f"- Recording: {metadata['post_id']}", f"- Coverage: transcript {coverage}%; visual {visual.get('coverage_pct', 0)}% ({visual.get('status', 'UNKNOWN')})",
        f"- Evidence grade: {record['evidence_quality'].get('overall_grade', 'UNKNOWN')}", f"- Governance: {GOVERNANCE_DECISION}", "", "## Evidence", "", "Structured evidence is stored in `evidence.json`. No production behavior changed.", "",
    ))
    handoff = "\n".join((
        "# Research Handoff", "", f"- Recording: {metadata['title']}", f"- Coverage: transcript {coverage}%; visual {visual.get('coverage_pct', 0)}%", f"- Evidence grade: {record['evidence_quality'].get('overall_grade', 'UNKNOWN')}",
        f"- Key lesson: {record['claims'][0]['claim'] if record['claims'] else 'NONE'}", "- Biggest contradiction: NONE_RECORDED", f"- Largest data gap: {record['instrumentation_gaps'][0] if record['instrumentation_gaps'] else 'NONE'}",
        f"- Best new hypothesis: {record['hypothesis_references'][0]['id'] if record['hypothesis_references'] else 'NONE'}", "- Strengthened hypotheses: NONE_RECORDED", "- Weakened hypotheses: NONE_RECORDED", "- Highest priority replay: NONE_QUEUED", "- Live changes: NONE", "",
    ))
    (directory / "report.md").write_text(report, encoding="utf-8")
    (directory / "handoff.md").write_text(handoff, encoding="utf-8")
    (directory / "transcript.md").write_text(transcript_artifact, encoding="utf-8")
    (directory / "record_summary.md").write_text("\n".join((f"# {metadata['title']} Summary", "", f"- Evidence tier: {record['evidence_quality'].get('tier', 'UNKNOWN')}", f"- Confidence: {record['expected_value_tracking'].get('confidence', 'UNKNOWN')}", f"- Market regime: {record['market_state_timeline'][0] if record['market_state_timeline'] else 'UNKNOWN'}", "- Major lessons: see `lessons.json`.", "- Trade ideas, avoided trades, and mistakes: see `claims.json` and `unknowns.json`.", "")), encoding="utf-8")
    _write_json(directory / "evidence.json", record)
    _write_json(directory / "claims.json", {"claims": record["claims"]})
    _write_json(directory / "observations.json", {"observations": record.get("timeline", [])})
    _write_json(directory / "hypotheses.json", {"analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION, "hypotheses": record["hypothesis_references"]})
    _write_json(directory / "lessons.json", {"lesson_references": record.get("lesson_references", [])})
    _write_json(directory / "entities.json", {"entity_references": record.get("entity_references", [])})
    _write_json(directory / "relationships.json", {"relationship_references": record.get("relationship_references", [])})
    _write_json(directory / "replay_candidates.json", {"replay_candidates": record.get("replay_candidates", [])})
    _write_json(directory / "unknowns.json", {"unknowns": record.get("instrumentation_gaps", []) + [f"Transcript content after {cutoff}"]})
    _write_json(directory / "recording_metadata.json", {"recording": metadata, "evidence_quality": record["evidence_quality"]})
    _write_json(directory / "claim_registry_update.json", {"analysis_protocol_version": ANALYSIS_PROTOCOL_VERSION, "claims": record["claims"]})
    fields = ("source_trade_id", "type", "entry_time", "entry_premium", "exit_time", "exit_premium", "setup", "stop_or_invalidation")
    with (directory / "trade_comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(record["reported_trades"])
    return directory


def aggregate_record(record: dict[str, Any], root: Path) -> None:
    """Idempotently aggregate claims and hypotheses by stable IDs only."""
    for name, key, entries in (("claim_registry.json", "claims", record["claims"]), ("hypothesis_registry.json", "hypotheses", record["hypothesis_references"])):
        path = root / name
        registry = _read_json(path, {"schema_version": f"daytradespy-{key}-registry.v1", key: []})
        existing = {str(item.get("id")): item for item in registry[key]}
        for item in entries:
            entry = {**item, "supporting_recordings": sorted(set(item.get("supporting_recordings", []) + [record["recording"]["post_id"]])), "lifecycle_stage": item.get("status", "NEW")}
            existing[str(item["id"])] = {**existing.get(str(item["id"]), {}), **entry}
        registry[key] = [existing[entry_id] for entry_id in sorted(existing)]
        _write_json(path, registry)


def write_synthesis(records_root: Path, destination: Path, period: str) -> None:
    records = []
    for evidence in sorted(records_root.glob("*/evidence.json")):
        record = _read_json(evidence)
        if record and str(record["recording"].get("publication_date", "")).startswith(period):
            records.append(record)
    claims = Counter(claim.get("label", "UNKNOWN") for record in records for claim in record.get("claims", []))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join((f"# DayTradeSPY {period} Synthesis", "", f"Completed structured records: {len(records)}", f"Claim labels: {dict(claims)}", "Coverage constraint: only completed structured evidence bundles are summarized.", "No live behavior changed.", "")), encoding="utf-8")