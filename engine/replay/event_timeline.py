from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TimelineEvent:
    snapshot_id: str
    snapshot_date: str
    stage: str
    status: str
    content_hash: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_timeline_events(day_results: tuple[dict[str, Any], ...]) -> tuple[TimelineEvent, ...]:
    events: list[TimelineEvent] = []
    for day in day_results:
        snapshot_id = str(day["snapshot_id"])
        snapshot_date = str(day["snapshot_date"])
        for stage_name in ["thesis", "decision", "portfolio", "performance"]:
            stage = dict(day["stages"].get(stage_name) or {})
            events.append(
                TimelineEvent(
                    snapshot_id=snapshot_id,
                    snapshot_date=snapshot_date,
                    stage=stage_name,
                    status=str(stage.get("status") or "UNKNOWN"),
                    content_hash=str(stage.get("content_hash") or ""),
                    detail=str(stage.get("detail") or ""),
                )
            )
    events.sort(key=lambda item: (item.snapshot_date, item.snapshot_id, item.stage))
    return tuple(events)
