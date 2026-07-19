from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

from .event_timeline import build_timeline_events
from .replay_metrics import ReplayMetrics, compute_replay_metrics
from .snapshot_loader import HistoricalSnapshot


class ReplayLookaheadError(ValueError):
    pass


class ReplayIntegrityError(ValueError):
    pass


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha_payload(payload: Any) -> str:
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if _DATE_RE.match(text):
            return date.fromisoformat(text)
        if _DATETIME_RE.match(text):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        return None
    return None


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _check_no_lookahead(value: Any, *, as_of: date, path: str) -> None:
    if isinstance(value, dict):
        lower_keys = {str(key).strip().lower() for key in value.keys()}
        if ("is_future" in lower_keys or "future" in lower_keys) and bool(value.get("is_future") or value.get("future")):
            raise ReplayLookaheadError(f"Future marker detected at {path}")

        for key in sorted(value.keys(), key=lambda item: str(item)):
            next_path = f"{path}.{key}"
            _check_no_lookahead(value[key], as_of=as_of, path=next_path)
        return

    if isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            _check_no_lookahead(item, as_of=as_of, path=f"{path}[{idx}]")
        return

    if isinstance(value, str):
        parsed = _parse_date(value)
        if parsed is not None and parsed > as_of:
            raise ReplayLookaheadError(f"Lookahead date {value} at {path} > {as_of.isoformat()}")


class ReplayStageAdapter(Protocol):
    def run_thesis(self, snapshot: HistoricalSnapshot) -> dict[str, Any]:
        ...

    def run_decision(self, snapshot: HistoricalSnapshot, thesis_result: dict[str, Any]) -> dict[str, Any]:
        ...

    def run_portfolio(self, snapshot: HistoricalSnapshot, decision_result: dict[str, Any]) -> dict[str, Any]:
        ...

    def run_performance(self, snapshot: HistoricalSnapshot, portfolio_result: dict[str, Any]) -> dict[str, Any]:
        ...


class DefaultReplayStageAdapter:
    def run_thesis(self, snapshot: HistoricalSnapshot) -> dict[str, Any]:
        state = dict(snapshot.thesis_state)
        evidence_count = len(snapshot.evidence)
        health_score = float(state.get("health_score") or 0.0)
        status = str(state.get("status") or "ACTIVE")
        return {
            "health_score": round(health_score, 6),
            "status": status,
            "evidence_count": evidence_count,
            "state_hash": _sha_payload(state),
        }

    def run_decision(self, snapshot: HistoricalSnapshot, thesis_result: dict[str, Any]) -> dict[str, Any]:
        valuation_signal = float(snapshot.valuation.get("signal") or 0.0)
        health = float(thesis_result.get("health_score") or 0.0)
        confidence = max(0.0, min(1.0, (health / 100.0) * 0.7 + 0.3))

        if valuation_signal > 0.2 and health >= 55.0:
            recommendation = "BUY"
        elif valuation_signal < -0.2 or health < 40.0:
            recommendation = "TRIM"
        else:
            recommendation = "HOLD"

        return {
            "recommendation": recommendation,
            "confidence": round(confidence, 6),
            "valuation_signal": round(valuation_signal, 6),
            "thesis_health": round(health, 6),
        }

    def run_portfolio(self, snapshot: HistoricalSnapshot, decision_result: dict[str, Any]) -> dict[str, Any]:
        state = dict(snapshot.portfolio_state)
        turnover = float(state.get("turnover") or 0.0)
        cash_weight = float(state.get("cash_weight") or 0.0)
        return {
            "target_action": str(decision_result.get("recommendation") or "HOLD"),
            "turnover": round(turnover, 6),
            "cash_weight": round(cash_weight, 6),
            "holdings_count": int(state.get("holdings_count") or 0),
        }

    def run_performance(self, snapshot: HistoricalSnapshot, portfolio_result: dict[str, Any]) -> dict[str, Any]:
        alpha = float(snapshot.valuation.get("realized_alpha") or 0.0)
        replacement_quality = float(snapshot.portfolio_state.get("replacement_quality") or 0.0)
        action = str(portfolio_result.get("target_action") or "HOLD")
        realized_direction = 1.0 if action == "BUY" and alpha >= 0.0 else 0.0
        if action == "TRIM":
            realized_direction = 1.0 if alpha <= 0.0 else 0.0
        if action == "HOLD":
            realized_direction = 1.0 if abs(alpha) <= 0.02 else 0.0

        return {
            "alpha": round(alpha, 6),
            "replacement_quality": round(replacement_quality, 6),
            "realized_direction": round(realized_direction, 6),
        }


@dataclass(frozen=True)
class ReplayRunResult:
    replay_id: str
    snapshot_count: int
    day_results: tuple[dict[str, Any], ...]
    timeline: tuple[dict[str, Any], ...]
    metrics: ReplayMetrics
    content_hash: str
    artifact_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_id": self.replay_id,
            "snapshot_count": self.snapshot_count,
            "day_results": [dict(item) for item in self.day_results],
            "timeline": [dict(item) for item in self.timeline],
            "metrics": self.metrics.to_dict(),
            "content_hash": self.content_hash,
            "artifact_paths": list(self.artifact_paths),
        }


def _stage_record(stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_payload = json.loads(_stable_json(payload))
    return {
        "stage": stage,
        "status": "PASS",
        "detail": f"{stage} executed",
        "payload": normalized_payload,
        "content_hash": _sha_payload({"stage": stage, "payload": normalized_payload}),
    }


def _evaluate_snapshot(snapshot: HistoricalSnapshot, adapter: ReplayStageAdapter) -> dict[str, Any]:
    as_of = _parse_date(snapshot.snapshot_date)
    if as_of is None:
        raise ReplayIntegrityError(f"Invalid snapshot date: {snapshot.snapshot_date}")

    snapshot_payload = snapshot.to_dict()
    _check_no_lookahead(snapshot_payload, as_of=as_of, path="snapshot")

    thesis_result = adapter.run_thesis(snapshot)
    _check_no_lookahead(thesis_result, as_of=as_of, path="thesis_result")

    decision_result = adapter.run_decision(snapshot, thesis_result)
    _check_no_lookahead(decision_result, as_of=as_of, path="decision_result")

    portfolio_result = adapter.run_portfolio(snapshot, decision_result)
    _check_no_lookahead(portfolio_result, as_of=as_of, path="portfolio_result")

    performance_result = adapter.run_performance(snapshot, portfolio_result)
    _check_no_lookahead(performance_result, as_of=as_of, path="performance_result")

    stages = {
        "thesis": _stage_record("thesis", thesis_result),
        "decision": _stage_record("decision", decision_result),
        "portfolio": _stage_record("portfolio", portfolio_result),
        "performance": _stage_record("performance", performance_result),
    }

    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_date": snapshot.snapshot_date,
        "snapshot_hash": snapshot.content_hash,
        "stages": stages,
        "day_hash": _sha_payload(
            {
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_date": snapshot.snapshot_date,
                "snapshot_hash": snapshot.content_hash,
                "stages": {key: stages[key]["content_hash"] for key in sorted(stages.keys())},
            }
        ),
    }


def run_historical_replay(
    *,
    snapshots: tuple[HistoricalSnapshot, ...],
    output_root: Path,
    write_artifacts: bool,
    adapter: ReplayStageAdapter | None = None,
) -> ReplayRunResult:
    stage_adapter = adapter or DefaultReplayStageAdapter()
    day_results = tuple(_evaluate_snapshot(snapshot, stage_adapter) for snapshot in snapshots)

    timeline_events = build_timeline_events(day_results)
    timeline = tuple(event.to_dict() for event in timeline_events)
    metrics = compute_replay_metrics(day_results)

    replay_seed = {
        "snapshot_hashes": [snapshot.content_hash for snapshot in snapshots],
        "snapshot_dates": [snapshot.snapshot_date for snapshot in snapshots],
        "snapshot_ids": [snapshot.snapshot_id for snapshot in snapshots],
    }
    replay_id = "REPLAY-" + sha256(_stable_json(replay_seed).encode("utf-8")).hexdigest()[:20].upper()

    base_payload = {
        "replay_id": replay_id,
        "snapshot_count": len(snapshots),
        "day_results": [dict(item) for item in day_results],
        "timeline": [dict(item) for item in timeline],
        "metrics": metrics.to_dict(),
    }
    content_hash = _sha_payload(base_payload)

    result = ReplayRunResult(
        replay_id=replay_id,
        snapshot_count=len(snapshots),
        day_results=day_results,
        timeline=timeline,
        metrics=metrics,
        content_hash=content_hash,
        artifact_paths=(),
    )

    if not write_artifacts:
        return result

    replay_dir = Path(output_root)
    replay_json_path = replay_dir / "replay_result.json"
    timeline_json_path = replay_dir / "replay_timeline.json"

    replay_payload = result.to_dict()
    replay_bytes = (json.dumps(replay_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    timeline_bytes = (json.dumps(replay_payload["timeline"], indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

    _atomic_write_bytes(replay_json_path, replay_bytes)
    _atomic_write_bytes(timeline_json_path, timeline_bytes)

    return ReplayRunResult(
        replay_id=result.replay_id,
        snapshot_count=result.snapshot_count,
        day_results=result.day_results,
        timeline=result.timeline,
        metrics=result.metrics,
        content_hash=result.content_hash,
        artifact_paths=(str(replay_json_path), str(timeline_json_path)),
    )
