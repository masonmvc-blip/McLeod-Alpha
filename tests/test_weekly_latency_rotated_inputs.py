import json
from pathlib import Path

from scripts.weekly_latency_insights import _load_events


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_load_events_includes_retained_rotations_in_order(tmp_path):
    current = tmp_path / "latency_cycle_history.jsonl"
    oldest = Path(f"{current}.20260726-090000")
    newest = Path(f"{current}.20260727-090000")
    _write(oldest, {"sequence": 1})
    _write(newest, {"sequence": 2})
    _write(current, {"sequence": 3})
    oldest.touch()
    newest.touch()
    oldest_mtime = oldest.stat().st_mtime - 2
    newest_mtime = newest.stat().st_mtime - 1
    oldest.chmod(0o600)
    newest.chmod(0o600)
    import os

    os.utime(oldest, (oldest_mtime, oldest_mtime))
    os.utime(newest, (newest_mtime, newest_mtime))

    assert [event["sequence"] for event in _load_events(current)] == [1, 2, 3]
