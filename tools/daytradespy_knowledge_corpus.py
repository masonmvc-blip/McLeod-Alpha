#!/usr/bin/env python3
"""Maintain the permanent DayTradeSPY entity graph without duplicate knowledge."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_ENTITY_TYPES = {"LESSON", "CLAIM", "OBSERVATION", "HYPOTHESIS", "FEATURE", "SETUP", "MARKET_REGIME", "FAILURE_MODE", "INDICATOR", "PATTERN", "REPLAY_CANDIDATE", "RESEARCH_QUESTION"}
VALID_RELATIONSHIPS = {"SUPPORTS", "CONTRADICTS", "REFINES", "MERGES_WITH", "ASSOCIATED_WITH", "STRENGTHENS"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, corpus: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def find_entities(corpus: dict[str, Any], query: str) -> list[dict[str, Any]]:
    """Return canonical candidates before callers attempt any entity creation."""
    tokens = set(query.lower().split())
    matches = []
    for entity in corpus["entities"]:
        searchable = " ".join([entity["entity_id"], entity["title"], entity["description"], *entity.get("aliases", [])]).lower()
        if tokens.intersection(searchable.split()):
            matches.append(entity)
    return matches


def create_entity(path: Path, entity: dict[str, Any]) -> dict[str, Any]:
    """Create a permanent entity only after callers have searched for a match."""
    required = {"entity_id", "entity_type", "title", "description"}
    missing = required.difference(entity)
    if missing:
        raise ValueError(f"Missing entity fields: {', '.join(sorted(missing))}")
    if entity["entity_type"] not in VALID_ENTITY_TYPES:
        raise ValueError(f"Unsupported entity type: {entity['entity_type']}")
    corpus = load(path)
    if any(existing["entity_id"] == entity["entity_id"] for existing in corpus["entities"]):
        raise ValueError(f"Permanent entity ID already exists: {entity['entity_id']}")
    normalized_title = entity["title"].strip().lower()
    if any(existing["title"].strip().lower() == normalized_title for existing in corpus["entities"]):
        raise ValueError(f"Existing entity has the same title: {entity['title']}")
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "first_observed": "UNKNOWN", "last_observed": "UNKNOWN", "times_supported": 0,
        "times_contradicted": 0, "supporting_recordings": [], "contradicting_recordings": [],
        "current_confidence": "UNVALIDATED", "evidence_weight": 0.0, "research_status": "OBSERVATION_ONLY",
        "aliases": [], "related_entities": [], "related_recordings": [], "related_features": [],
        "related_setups": [], "related_patterns": [], "related_failure_modes": [], "related_hypotheses": [],
        "related_market_regimes": [], "last_updated": now, "version": 1,
    }
    created = {**defaults, **entity}
    corpus["entities"].append(created)
    corpus["entities"].sort(key=lambda item: item["entity_id"])
    write(path, corpus)
    return created


def record_entity_evidence(path: Path, entity_id: str, recording_id: int, observed_date: str, relationship: str, evidence: str) -> dict[str, Any]:
    """Update a stable entity once per recording/timestamp/evidence relationship."""
    if relationship not in {"SUPPORTS", "CONTRADICTS", "REFINES"}:
        raise ValueError("entity evidence must SUPPORTS, CONTRADICTS, or REFINES")
    corpus = load(path)
    entities = {entity["entity_id"]: entity for entity in corpus["entities"]}
    entity = entities.get(entity_id)
    if entity is None:
        raise ValueError(f"Unknown permanent entity ID: {entity_id}")
    events = entity.setdefault("evidence_events", [])
    event_id = f"{recording_id}:{relationship}:{evidence}"
    if not any(event["event_id"] == event_id for event in events):
        events.append({"event_id": event_id, "recording_id": recording_id, "observed_date": observed_date, "relationship": relationship, "evidence": evidence})
        if relationship == "SUPPORTS":
            entity["times_supported"] += 1
            entity["supporting_recordings"] = sorted(set(entity["supporting_recordings"] + [recording_id]))
        elif relationship == "CONTRADICTS":
            entity["times_contradicted"] += 1
            entity["contradicting_recordings"] = sorted(set(entity["contradicting_recordings"] + [recording_id]))
        entity["related_recordings"] = sorted(set(entity["related_recordings"] + [recording_id]))
        if observed_date != "UNKNOWN":
            entity["first_observed"] = observed_date if entity["first_observed"] == "UNKNOWN" else min(entity["first_observed"], observed_date)
            entity["last_observed"] = observed_date if entity["last_observed"] == "UNKNOWN" else max(entity["last_observed"], observed_date)
        denominator = entity["times_supported"] + entity["times_contradicted"]
        entity["evidence_weight"] = round(denominator * entity["times_supported"] / denominator, 2) if denominator else 0.0
        entity["last_updated"] = datetime.now(timezone.utc).isoformat()
        entity["version"] += 1
    write(path, corpus)
    return entity


def record_relationship_evidence(path: Path, relationship_id: str, recording_id: int, relationship: str, evidence: str) -> dict[str, Any]:
    """Accumulate evidence on a stable edge without duplicating it."""
    if relationship not in VALID_RELATIONSHIPS:
        raise ValueError(f"Invalid relationship: {relationship}")
    corpus = load(path)
    edges = {edge["relationship_id"]: edge for edge in corpus["relationships"]}
    edge = edges.get(relationship_id)
    if edge is None:
        raise ValueError(f"Unknown relationship ID: {relationship_id}")
    event_id = f"{recording_id}:{relationship}:{evidence}"
    if not any(event["event_id"] == event_id for event in edge["evidence_events"]):
        edge["evidence_events"].append({"event_id": event_id, "recording_id": recording_id, "relationship": relationship, "evidence": evidence})
        key = "times_contradicted" if relationship == "CONTRADICTS" else "times_supported"
        recording_key = "contradicting_recordings" if relationship == "CONTRADICTS" else "supporting_recordings"
        edge[key] += 1
        edge[recording_key] = sorted(set(edge[recording_key] + [recording_id]))
        edge["last_updated"] = datetime.now(timezone.utc).isoformat()
        edge["version"] += 1
    write(path, corpus)
    return edge