#!/usr/bin/env python3
"""Register bounded partial research from authorized browser transcript observations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .daytradespy_knowledge_corpus import record_entity_evidence
    from .daytradespy_research_ops import aggregate_record, write_output_bundle
    from .daytradespy_record_processor import evidence_tier, register_record
    from .migrate_daytradespy_legacy_week import UNAVAILABLE_WINDOWS, record_for
else:
    from daytradespy_knowledge_corpus import record_entity_evidence
    from daytradespy_research_ops import aggregate_record, write_output_bundle
    from daytradespy_record_processor import evidence_tier, register_record
    from migrate_daytradespy_legacy_week import UNAVAILABLE_WINDOWS, record_for


RECORDINGS = (
    (43092, "2026-01-02", 4270, 3133, 308, "52:13", "51:41-51:48", "PRESENTER_CLAIM", "At 51:41 through 51:48, the presenter said they would wait to see the trend reverse and framed the decision as distinguishing a pullback from a trend reversal."),
    (43099, "2026-01-05", 4295, 3354, 381, "55:54", "55:26", "PRESENTER_CLAIM", "At 55:26, the presenter stated uncertainty about the market; this is a source observation, not a trade or expectancy conclusion."),
    (43135, "2026-01-06", 4651, 3612, 426, "1:00:12", "00:00-1:00:12", "SOURCE_MEASUREMENT", "Authorized browser measurement found 426 transcript cues spanning 00:00 through 1:00:12; no presenter claim is registered from this coverage measurement alone."),
    (43147, "2026-01-07", 4420, 3384, 342, "56:24", "00:02-56:24", "SOURCE_MEASUREMENT", "Authorized browser measurement found 342 transcript cues spanning 00:02 through 56:24; no presenter claim is registered from this coverage measurement alone."),
    (43167, "2026-01-08", 5035, 3753, 375, "1:02:33", "00:01-1:02:33", "SOURCE_MEASUREMENT", "Authorized browser measurement found 375 transcript cues spanning 00:01 through 1:02:33; no presenter claim is registered from this coverage measurement alone."),
    (43204, "2026-01-09", 4530, 3525, 399, "58:45", "00:00-58:45", "SOURCE_MEASUREMENT", "Authorized browser measurement found 399 transcript cues spanning 00:00 through 58:45; no presenter claim is registered from this coverage measurement alone."),
    (43247, "2026-01-13", 5351, 3828, 431, "1:03:48", "00:01-1:03:48", "SOURCE_MEASUREMENT", "Authorized browser measurement found 431 transcript cues spanning 00:01 through 1:03:48; no presenter claim is registered from this coverage measurement alone."),
    (43258, "2026-01-14", 4735, 3540, 417, "59:00", "00:01-59:00", "SOURCE_MEASUREMENT", "Authorized browser measurement found 417 transcript cues spanning 00:01 through 59:00; no presenter claim is registered from this coverage measurement alone."),
    (43276, "2026-01-15", 4417, 3539, 367, "58:59", "00:00-58:59", "SOURCE_MEASUREMENT", "Authorized browser measurement found 367 transcript cues spanning 00:00 through 58:59; no presenter claim is registered from this coverage measurement alone."),
    (43286, "2026-01-16", 4139, 3117, 317, "51:57", "00:00-51:57", "SOURCE_MEASUREMENT", "Authorized browser measurement found 317 transcript cues spanning 00:00 through 51:57; no presenter claim is registered from this coverage measurement alone."),
    (43311, "2026-01-20", 4539, 3646, 358, "1:00:46", "00:00-1:00:46", "SOURCE_MEASUREMENT", "Authorized browser measurement found 358 transcript cues spanning 00:00 through 1:00:46; no presenter claim is registered from this coverage measurement alone."),
    (43359, "2026-01-21", 4727, 3712, 392, "1:01:52", "00:00-1:01:52", "SOURCE_MEASUREMENT", "Authorized browser measurement found 392 transcript cues spanning 00:00 through 1:01:52; no presenter claim is registered from this coverage measurement alone."),
    (43820, "2026-03-02", 4303, 3634, 391, "1:00:34", "1:00:27-1:00:34", "PRESENTER_CLAIM", "At 1:00:27 through 1:00:34, the presenter described waiting for a later trade rather than forcing participation and said that a transition move can set up a larger pattern to trade."),
    (43838, "2026-03-03", 4444, 4432, 435, "1:13:52", "00:00-1:13:52", "SOURCE_MEASUREMENT", "Authorized browser measurement found 435 transcript cues spanning 00:00 through 1:13:52; no presenter claim is registered from this coverage measurement alone."),
    (43848, "2026-03-04", 4446, 3961, 401, "1:06:01", "00:00-1:06:01", "SOURCE_MEASUREMENT", "Authorized browser measurement found 401 transcript cues spanning 00:00 through 1:06:01; no presenter claim is registered from this coverage measurement alone."),
    (43867, "2026-03-05", 4287, 4229, 364, "1:10:29", "00:00-1:10:29", "SOURCE_MEASUREMENT", "Authorized browser measurement found 364 transcript cues spanning 00:00 through 1:10:29; no presenter claim is registered from this coverage measurement alone."),
    (43921, "2026-03-09", 5120, 5102, 434, "1:25:02", "00:00-1:25:02", "SOURCE_MEASUREMENT", "Authorized browser measurement found 434 transcript cues spanning 00:00 through 1:25:02; no presenter claim is registered from this coverage measurement alone."),
    (43940, "2026-03-10", 4362, 3619, 401, "1:00:19", "00:00-1:00:19", "SOURCE_MEASUREMENT", "Authorized browser measurement found 401 transcript cues spanning 00:00 through 1:00:19; no presenter claim is registered from this coverage measurement alone."),
    (43959, "2026-03-11", 4256, 4187, 407, "1:09:47", "00:00-1:09:47", "SOURCE_MEASUREMENT", "Authorized browser measurement found 407 transcript cues spanning 00:00 through 1:09:47; no presenter claim is registered from this coverage measurement alone."),
    (43993, "2026-03-12", 4213, 3905, 398, "1:05:05", "00:01-1:05:05", "SOURCE_MEASUREMENT", "Authorized browser measurement found 398 transcript cues spanning 00:01 through 1:05:05; no presenter claim is registered from this coverage measurement alone."),
    (44027, "2026-03-13", 4572, 3401, 380, "56:41", "00:00-56:41", "SOURCE_MEASUREMENT", "Authorized browser measurement found 380 transcript cues spanning 00:00 through 56:41; no presenter claim is registered from this coverage measurement alone."),
    (44047, "2026-03-16", 4232, 3452, 387, "57:32", "00:00-57:32", "SOURCE_MEASUREMENT", "Authorized browser measurement found 387 transcript cues spanning 00:00 through 57:32; no presenter claim is registered from this coverage measurement alone."),
    (44061, "2026-03-17", 4522, 3452, 385, "57:32", "00:02-57:32", "SOURCE_MEASUREMENT", "Authorized browser measurement found 385 transcript cues spanning 00:02 through 57:32; no presenter claim is registered from this coverage measurement alone."),
    (44076, "2026-03-18", 4389, 3363, 392, "56:03", "00:00-56:03", "SOURCE_MEASUREMENT", "Authorized browser measurement found 392 transcript cues spanning 00:00 through 56:03; no presenter claim is registered from this coverage measurement alone."),
    (44093, "2026-03-19", 4715, 3942, 379, "1:05:42", "00:00-1:05:42", "SOURCE_MEASUREMENT", "Authorized browser measurement found 379 transcript cues spanning 00:00 through 1:05:42; no presenter claim is registered from this coverage measurement alone."),
    (44106, "2026-03-20", 4729, 4298, 387, "1:11:38", "00:02-1:11:38", "SOURCE_MEASUREMENT", "Authorized browser measurement found 387 transcript cues spanning 00:02 through 1:11:38; no presenter claim is registered from this coverage measurement alone."),
    (44131, "2026-03-23", 4448, 3456, 383, "57:36", "00:01-57:36", "SOURCE_MEASUREMENT", "Authorized browser measurement found 383 transcript cues spanning 00:01 through 57:36; no presenter claim is registered from this coverage measurement alone."),
    (44145, "2026-03-24", 4784, 3815, 381, "1:03:35", "00:01-1:03:35", "SOURCE_MEASUREMENT", "Authorized browser measurement found 381 transcript cues spanning 00:01 through 1:03:35; no presenter claim is registered from this coverage measurement alone."),
    (44157, "2026-03-25", 5308, 4340, 385, "1:12:20", "00:00-1:12:20", "SOURCE_MEASUREMENT", "Authorized browser measurement found 385 transcript cues spanning 00:00 through 1:12:20; no presenter claim is registered from this coverage measurement alone."),
    (44171, "2026-03-26", 4500, 3984, 387, "1:06:24", "00:02-1:06:24", "SOURCE_MEASUREMENT", "Authorized browser measurement found 387 transcript cues spanning 00:02 through 1:06:24; no presenter claim is registered from this coverage measurement alone."),
    (44185, "2026-03-27", 4747, 3870, 387, "1:04:30", "00:00-1:04:30", "SOURCE_MEASUREMENT", "Authorized browser measurement found 387 transcript cues spanning 00:00 through 1:04:30; no presenter claim is registered from this coverage measurement alone."),
    (44208, "2026-03-30", 4251, 3845, 383, "1:04:05", "00:02-1:04:05", "SOURCE_MEASUREMENT", "Authorized browser measurement found 383 transcript cues spanning 00:02 through 1:04:05; no presenter claim is registered from this coverage measurement alone."),
    (44222, "2026-03-31", 4787, 4771, 395, "1:19:31", "00:02-1:19:31", "SOURCE_MEASUREMENT", "Authorized browser measurement found 395 transcript cues spanning 00:02 through 1:19:31; no presenter claim is registered from this coverage measurement alone."),
    (28746, "2023-03-16", 4558, 4113, 400, "1:08:33", "46:04", "PRESENTER_CLAIM", "At 46:04, the presenter discussed a 387 strike filter/configuration while answering a participant question."),
    (28750, "2023-03-17", 4365, 3177, 298, "52:57", "52:49", "PRESENTER_CLAIM", "At 52:49, the presenter conditionally described directional continuation when an upward or downward bias is present."),
    (28752, "2023-03-20", 4102, 3252, 279, "54:12", "53:39", "PRESENTER_CLAIM", "At 53:39, the presenter described watching 392.50 and 393.25 as possible support and discussed an ABC pattern."),
)


def _write_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_note_sheet(record: dict, docs_dir: Path) -> None:
    """Write a derived note sheet without retaining browser-rendered transcript text."""
    recording = record["recording"]
    probe = recording["transcript_probe"]
    day = recording["publication_date"]
    evidence = record["evidence_quality"]
    observations = [
        f"- Authorized browser review observed {probe['cue_count']} transcript cues from {probe['first_timestamp']} through {probe['last_timestamp']} ({evidence['transcript_completeness_pct']}% coverage; Tier {evidence['tier']}).",
        "- Visual review, market data, trade reconciliation, and post-cutoff transcript evidence remain unavailable.",
    ]
    presenter_claims = [claim["claim"] for claim in record["claims"] if claim["fact_classification"] == "PRESENTER_CLAIM"]
    if presenter_claims:
        observations.append(f"- Bounded source observation: {presenter_claims[0]}")
    else:
        observations.append("- No standalone presenter lesson was registered from the coverage measurement alone.")
    note = "\n".join(
        [
            f"# McLeod Alpha Research Report: {day} Trading Room",
            "",
            "## Scope and Evidence",
            "",
            f"Source recording: Day Trade SPY, \"{recording['title']}\". This bounded review covers the authorized browser transcript through {probe['last_timestamp']}; raw transcript text was not retained. This is external qualitative research, not a live trading instruction.",
            "",
            "## Observations",
            "",
            *observations,
            "",
            "## Research Implications",
            "",
            "1. Do not generalize coverage measurements into an entry, exit, or expectancy rule.",
            "2. Obtain timestamped underlying bars, option execution data, and visual review before testing any source observation.",
            "3. Treat all evidence after the observed cutoff as unknown.",
            "",
            "## Decision",
            "",
            "No live entry, exit, stop, sizing, or directional policy changes. The record remains research-only pending independently verifiable replay evidence.",
            "",
        ]
    )
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / f"{day}_daytradespy_trading_room_research.md").write_text(note, encoding="utf-8")


def process(root: Path) -> list[Path]:
    """Create one governed partial record and checkpoint before advancing."""
    checkpoint_path = root / "recording_checkpoints.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    written: list[Path] = []
    for post_id, day, duration, cutoff, cue_count, last_timestamp, observation_timestamp, fact_classification, observation in RECORDINGS:
        path = root / "records" / f"{day}.json"
        if path.exists():
            if day.startswith("2026-03-"):
                write_note_sheet(json.loads(path.read_text(encoding="utf-8")), root.parents[2] / "docs" / "research")
            continue
        source_url = checkpoint.get("recordings", {}).get(str(post_id), {}).get("source_url")
        if not source_url:
            month = {"01": "january", "03": "march"}[day[5:7]]
            source_url = f"https://daytradespy.com/{post_id}/trading-room-video-recording-{month}-{day[-2:]}-{day[:4]}/"
        record = record_for(post_id, day, duration, source_url, observation)
        coverage = int(cutoff / duration * 100)
        recording = record["recording"]
        recording["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        recording["reviewer_version"] = "authorized-browser-partial-research.v1"
        recording["transcript"] = {"availability": "PARTIAL_AUTHORIZED_BROWSER_TRANSCRIPT", "completeness_pct": coverage, "path": "", "timestamps_preserved": True, "speaker_attribution_available": False}
        recording["transcript_probe"] = {"source": "AUTHORIZED_BROWSER_RUNTIME", "cue_count": cue_count, "first_timestamp": "00:00", "last_timestamp": last_timestamp, "coverage_end_seconds": cutoff, "raw_transcript_persisted": False, "coverage_note": "Only the observed portion is eligible for analysis; all post-cutoff material is UNKNOWN."}
        record["evidence_quality"].update({"transcript_completeness_pct": coverage, "overall_grade": "PARTIAL", "tier": evidence_tier(record)})
        record["timeline"] = [{"timestamp": observation_timestamp, "classification": fact_classification, "fact_classification": fact_classification, "claim": observation, "chart_reference": "UNKNOWN"}, {"timestamp": f"> {last_timestamp}", "classification": "UNKNOWN", "fact_classification": "UNAVAILABLE_EVIDENCE", "claim": "Post-cutoff transcript, trade, and market-state evidence is UNKNOWN.", "chart_reference": "UNKNOWN"}]
        record["claims"] = [{"id": f"DTS-{day.replace('-', '')}-C01", "timestamp": observation_timestamp, "label": "PARTIAL_TRANSCRIPT_OBSERVATION" if fact_classification == "PRESENTER_CLAIM" else "PARTIAL_TRANSCRIPT_MEASUREMENT", "status": "NEEDS_INSTRUMENTATION", "fact_classification": fact_classification, "claim": observation, "forward_outcomes": UNAVAILABLE_WINDOWS, "disconfirming_evidence_required": "Timestamped underlying bars and independently reconciled trade evidence."}]
        record["lesson_references"] = [{"lesson_id": "LESSON-0017", "timestamp": "51:41-51:48", "relationship": "SUPPORTS", "evidence_tier": evidence_tier(record)}] if post_id == 43092 else []
        record["entity_references"] = ["LESSON-0017"] if post_id == 43092 else []
        record["relationship_references"] = []
        record["replay_candidates"] = [{"id": f"DTS-REPLAY-{day.replace('-', '')}-PULLBACK-VS-REVERSAL", "timestamp": "51:41-51:48", "status": "NEEDS_MARKET_DATA", "description": "Evaluate the classification of pullback versus trend reversal before re-entry."}] if post_id == 43092 else []
        record["instrumentation_gaps"] = ["DTS-INST-001", "Full caption coverage after the measured cutoff", "Visual review", "Canonical McLeod Alpha signal, trade, rejection, and ledger mapping", "Timestamped underlying bars"]
        _write_atomic(path, record)
        register_record(path, root / "recording_registry.json")
        aggregate_record(record, root)
        write_output_bundle(record, root / "output")
        write_note_sheet(record, root.parents[2] / "docs" / "research")
        if post_id == 43092:
            record_entity_evidence(root / "knowledge_corpus.json", "LESSON-0017", post_id, day, "SUPPORTS", observation)
        checkpoint["recordings"][str(post_id)] = {**checkpoint["recordings"].get(str(post_id), {}), "status": "PARTIAL_RESEARCH_REGISTERED", "day": day, "source_url": source_url, "evidence_tier": record["evidence_quality"]["tier"], "transcript_coverage_pct": coverage, "visual_coverage_pct": 0, "record_path": str(path), "output_bundle_path": str(root / "output" / str(post_id)), "corpus_entities_updated": ["LESSON-0017"] if post_id == 43092 else [], "entities_created": [], "relationships_updated": [], "validation_status": "VALIDATED", "methodology_version": "2026-07-22.1", "checkpointed_at": datetime.now(timezone.utc).isoformat()}
        _write_atomic(checkpoint_path, checkpoint)
        written.append(path)
    return written


if __name__ == "__main__":
    for output in process(Path("data/research/daytradespy")):
        print(output)