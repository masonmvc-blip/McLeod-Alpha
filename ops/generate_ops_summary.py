#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = PROJECT_ROOT / "data" / "reports" / "runtime_events.jsonl"
OUT_PATH = PROJECT_ROOT / "data" / "reports" / "ops_daily_summary.txt"


def load_events(path: Path):
    events = []
    if not path.exists():
        return events
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def main() -> int:
    now = datetime.now(timezone.utc)
    events = load_events(EVENTS_PATH)

    by_type = Counter(str(e.get("event_type") or "UNKNOWN") for e in events)
    by_sev = Counter(str(e.get("severity") or "UNKNOWN") for e in events)

    lines = [
        f"Ops Daily Summary UTC: {now.isoformat()}",
        f"Events file: {EVENTS_PATH}",
        f"Total events: {len(events)}",
        "",
        "By severity:",
    ]
    for key in sorted(by_sev):
        lines.append(f"- {key}: {by_sev[key]}")

    lines.append("")
    lines.append("By event type:")
    for key in sorted(by_type):
        lines.append(f"- {key}: {by_type[key]}")

    lines.append("")
    lines.append("Last 10 events:")
    for event in events[-10:]:
        lines.append(
            f"- {event.get('ts')} | {event.get('severity')} | {event.get('event_type')} | {event.get('message')}"
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
