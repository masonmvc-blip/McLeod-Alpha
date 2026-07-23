#!/usr/bin/env python3
"""Maintain stable, non-duplicated DayTradeSPY lesson records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "schema_version": "daytradespy-lesson-registry.v1", "lessons": []
    }


def write_registry(path: Path, registry: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def upsert_lesson(path: Path, lesson: dict[str, Any]) -> None:
    """Replace only the matching stable lesson ID; never create a duplicate."""
    registry = load_registry(path)
    lessons = {item["lesson_id"]: item for item in registry["lessons"]}
    existing = lessons.get(lesson["lesson_id"], {})
    lessons[lesson["lesson_id"]] = {**existing, **lesson}
    registry["lessons"] = [lessons[lesson_id] for lesson_id in sorted(lessons)]
    write_registry(path, registry)


def record_lesson_evidence(
    path: Path,
    lesson_id: str,
    recording_id: int,
    timestamp: str,
    relationship: str,
    evidence: str,
    observed_date: str = "UNKNOWN",
) -> dict[str, Any]:
    """Link one recording to a stable lesson without duplicating its evidence."""
    if relationship not in {"SUPPORTS", "CONTRADICTS", "REFINES"}:
        raise ValueError("relationship must be SUPPORTS, CONTRADICTS, or REFINES")
    registry = load_registry(path)
    lessons = {lesson["lesson_id"]: lesson for lesson in registry["lessons"]}
    if lesson_id not in lessons:
        raise ValueError(f"Unknown lesson ID: {lesson_id}")
    lesson = lessons[lesson_id]
    events = lesson.setdefault("recording_evidence", [])
    event_key = f"{recording_id}:{timestamp}:{relationship}"
    if not any(event.get("event_key") == event_key for event in events):
        event = {"event_key": event_key, "recording_id": recording_id, "timestamp": timestamp, "relationship": relationship, "evidence": evidence, "observed_date": observed_date}
        events.append(event)
        if relationship == "SUPPORTS":
            lesson["times_supported"] += 1
            lesson["supporting_recordings"] = sorted(set(lesson["supporting_recordings"] + [recording_id]))
        elif relationship == "CONTRADICTS":
            lesson["times_contradicted"] += 1
            lesson["contradicting_recordings"] = sorted(set(lesson["contradicting_recordings"] + [recording_id]))
        if observed_date != "UNKNOWN":
            prior_date = lesson.get("last_observed", "UNKNOWN")
            lesson["last_observed"] = observed_date if prior_date == "UNKNOWN" else max(prior_date, observed_date)
        denominator = lesson["times_supported"] + lesson["times_contradicted"]
        lesson["evidence_weight"] = round(denominator * (lesson["times_supported"] / denominator), 2) if denominator else 0.0
    write_registry(path, registry)
    return lesson


if __name__ == "__main__":
    registry_path = Path("data/research/daytradespy/lesson_registry.json")
    registry = load_registry(registry_path)
    print(f"Loaded {len(registry['lessons'])} permanent lessons")