#!/usr/bin/env python3
"""Build a local searchable catalog of DayTradeSPY research evidence."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    return "" if value is None else str(value)


def _transcript_text(path: str) -> str:
    transcript_path = Path(path)
    if not path or not transcript_path.exists():
        return ""
    if transcript_path.suffix == ".json":
        payload = _read_json(transcript_path)
        return _text(payload.get("cues", payload))
    return transcript_path.read_text(encoding="utf-8")


def _report_text(path: str) -> str:
    report_path = Path(path)
    return report_path.read_text(encoding="utf-8") if path and report_path.exists() else ""


def build_catalog(root: Path, database_path: Path, jsonl_path: Path) -> int:
    """Create a portable FTS catalog; source metadata is indexed even without transcripts."""
    registry = _read_json(root / "recording_registry.json")
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DROP TABLE IF EXISTS recordings")
        connection.execute("DROP TABLE IF EXISTS recording_search")
        connection.execute("DROP TABLE IF EXISTS corpus_entities")
        connection.execute("DROP TABLE IF EXISTS corpus_entity_search")
        connection.execute("CREATE TABLE recordings (post_id INTEGER PRIMARY KEY, recording_date TEXT, title TEXT, source_url TEXT, analysis_status TEXT, transcript_coverage INTEGER, visual_coverage INTEGER, evidence_grade TEXT, machine_record_path TEXT)")
        connection.execute("CREATE VIRTUAL TABLE recording_search USING fts5(post_id UNINDEXED, title, transcript, report, claims, trades, status)")
        connection.execute("CREATE TABLE corpus_entities (entity_id TEXT PRIMARY KEY, entity_type TEXT, title TEXT, confidence TEXT, research_status TEXT)")
        connection.execute("CREATE VIRTUAL TABLE corpus_entity_search USING fts5(entity_id UNINDEXED, entity_type, title, content, status)")
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("w", encoding="utf-8") as catalog:
            for item in registry["recordings"]:
                record: dict[str, Any] = {}
                record_path = item.get("machine_record_path")
                if record_path and Path(record_path).exists():
                    record = _read_json(Path(record_path))
                transcript = _transcript_text(item.get("transcript", {}).get("path", ""))
                report = _report_text(item.get("report_path", ""))
                claims = _text(record.get("claims", []))
                trades = _text(record.get("reported_trades", []))
                lessons = _text(record.get("lesson_references", []))
                visual = record.get("recording", {}).get("visual_review", {})
                row = {
                    "post_id": item["post_id"], "recording_date": item["recording_date"], "title": item["title"],
                    "source_url": item["source_url"], "analysis_status": item["analysis_status"],
                    "transcript_coverage": item.get("transcript", {}).get("completeness_pct", 0),
                    "visual_coverage": visual.get("coverage_pct", 0),
                    "evidence_grade": (item.get("evidence_quality") or {}).get("overall_grade", "UNAVAILABLE"),
                    "machine_record_path": record_path or "", "transcript": transcript, "report": report, "claims": f"{claims} {lessons}", "trades": trades,
                }
                catalog.write(json.dumps(row, sort_keys=True) + "\n")
                connection.execute("INSERT INTO recordings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(row[key] for key in ("post_id", "recording_date", "title", "source_url", "analysis_status", "transcript_coverage", "visual_coverage", "evidence_grade", "machine_record_path")))
                connection.execute("INSERT INTO recording_search VALUES (?, ?, ?, ?, ?, ?, ?)", (row["post_id"], row["title"], transcript, report, claims, trades, row["analysis_status"]))
            corpus_path = root / "knowledge_corpus.json"
            if corpus_path.exists():
                corpus = _read_json(corpus_path)
                for entity in corpus.get("entities", []):
                    content = _text(entity)
                    catalog.write(json.dumps({"kind": "corpus_entity", **entity}, sort_keys=True) + "\n")
                    connection.execute("INSERT INTO corpus_entities VALUES (?, ?, ?, ?, ?)", (entity["entity_id"], entity["entity_type"], entity["title"], entity["current_confidence"], entity["research_status"]))
                    connection.execute("INSERT INTO corpus_entity_search VALUES (?, ?, ?, ?, ?)", (entity["entity_id"], entity["entity_type"], entity["title"], content, entity["research_status"]))
        connection.commit()
        return len(registry["recordings"])
    finally:
        connection.close()


def search(database_path: Path, query: str, limit: int) -> list[tuple[Any, ...]]:
    with sqlite3.connect(database_path) as connection:
        return connection.execute("SELECT entity_id, title, status FROM corpus_entity_search WHERE corpus_entity_search MATCH ? UNION ALL SELECT post_id, title, status FROM recording_search WHERE recording_search MATCH ? LIMIT ?", (query, query, limit)).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/research/daytradespy"))
    parser.add_argument("--database", type=Path, default=Path("data/research/daytradespy/search_catalog.sqlite"))
    parser.add_argument("--jsonl", type=Path, default=Path("data/research/daytradespy/search_catalog.jsonl"))
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.search:
        for result in search(args.database, args.search, args.limit):
            print(" | ".join(str(value) for value in result))
        return 0
    print(f"Indexed {build_catalog(args.root, args.database, args.jsonl)} DayTradeSPY recordings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())