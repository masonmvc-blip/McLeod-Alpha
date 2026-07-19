from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class SnapshotValidationError(ValueError):
    pass


_REQUIRED_SNAPSHOT_KEYS = {
    "snapshot_id",
    "snapshot_date",
    "content_hash",
    "company_fundamentals",
    "sec_filings",
    "macro_data",
    "valuation",
    "analyst_estimates",
    "evidence",
    "thesis_state",
    "portfolio_state",
}


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_snapshot_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise SnapshotValidationError("snapshot_date is required")
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text)
    except Exception as exc:  # pragma: no cover
        raise SnapshotValidationError(f"Invalid snapshot_date: {text}") from exc


def compute_snapshot_content_hash(snapshot_payload: dict[str, Any]) -> str:
    canonical = {
        key: snapshot_payload[key]
        for key in sorted(snapshot_payload.keys())
        if key != "content_hash"
    }
    return sha256(_stable_json(canonical).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HistoricalSnapshot:
    snapshot_id: str
    snapshot_date: str
    content_hash: str
    company_fundamentals: dict[str, Any]
    sec_filings: list[dict[str, Any]]
    macro_data: dict[str, Any]
    valuation: dict[str, Any]
    analyst_estimates: dict[str, Any]
    evidence: list[dict[str, Any]]
    thesis_state: dict[str, Any]
    portfolio_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sec_filings"] = [dict(item) for item in self.sec_filings]
        payload["evidence"] = [dict(item) for item in self.evidence]
        return payload


def _normalize_snapshot_payload(payload: dict[str, Any], source: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SnapshotValidationError(f"Snapshot must be an object: {source}")

    missing = sorted(_REQUIRED_SNAPSHOT_KEYS - set(payload.keys()))
    if missing:
        raise SnapshotValidationError(f"Snapshot missing keys ({source.name}): {', '.join(missing)}")

    _parse_snapshot_date(str(payload["snapshot_date"]))

    computed_hash = compute_snapshot_content_hash(payload)
    observed_hash = str(payload.get("content_hash") or "").strip().lower()
    if observed_hash != computed_hash:
        raise SnapshotValidationError(
            f"content_hash mismatch in {source.name}: expected {computed_hash}, observed {observed_hash or 'missing'}"
        )

    return {
        "snapshot_id": str(payload["snapshot_id"]),
        "snapshot_date": str(payload["snapshot_date"]),
        "content_hash": observed_hash,
        "company_fundamentals": dict(payload.get("company_fundamentals") or {}),
        "sec_filings": [dict(row) for row in list(payload.get("sec_filings") or [])],
        "macro_data": dict(payload.get("macro_data") or {}),
        "valuation": dict(payload.get("valuation") or {}),
        "analyst_estimates": dict(payload.get("analyst_estimates") or {}),
        "evidence": [dict(row) for row in list(payload.get("evidence") or [])],
        "thesis_state": dict(payload.get("thesis_state") or {}),
        "portfolio_state": dict(payload.get("portfolio_state") or {}),
    }


def load_historical_snapshot(path: Path) -> HistoricalSnapshot:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SnapshotValidationError(f"Unable to parse snapshot JSON: {source}") from exc

    normalized = _normalize_snapshot_payload(payload, source)
    return HistoricalSnapshot(**normalized)


def load_historical_snapshots(snapshot_root: Path) -> tuple[HistoricalSnapshot, ...]:
    root = Path(snapshot_root)
    files = sorted(root.glob("*.json"), key=lambda item: item.name)
    if not files:
        raise SnapshotValidationError(f"No snapshot files found in {root}")

    snapshots = [load_historical_snapshot(path) for path in files]
    snapshots.sort(key=lambda item: (_parse_snapshot_date(item.snapshot_date), item.snapshot_id, item.content_hash))
    return tuple(snapshots)
