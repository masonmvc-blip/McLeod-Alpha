from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from engine.phase2_research import (
    PHASE2_LOCK_NAME,
    PHASE2_ONBOARDING_ALLOWLIST,
    PHASE2_SCHEMA_VERSION,
    PHASE2_TICKER_REGISTRY,
)


MAX_ARTIFACT_AGE_HOURS_DEFAULT = 72


class Phase2DownstreamError(ValueError):
    pass


@dataclass(frozen=True)
class Phase2DownstreamSnapshot:
    ticker: str
    available: bool
    status: str
    warning: str = ""
    artifact_path: str = ""
    review_path: str = ""
    generated_at: str = ""
    source_phase1_artifact_fingerprint: str = ""
    schema_version: str = ""
    phase2_framework_locked: bool = False
    phase2_lock_name: str = ""
    approved_for_eipv: bool = False
    informational_only: bool = True
    canonical_score: Dict[str, Any] = field(default_factory=dict)
    score_audit: Dict[str, Any] = field(default_factory=dict)
    review_text: str = ""
    source_phase1_fact_path: str = ""
    source_phase1_review_path: str = ""

    @property
    def component_scores(self) -> Dict[str, Any]:
        return dict(self.canonical_score.get("component_scores") or {})

    @property
    def overall_score(self) -> Dict[str, Any]:
        return dict(self.canonical_score.get("overall_score") or {})

    @property
    def confidence(self) -> float:
        overall = self.overall_score
        return float(overall.get("confidence") or self.canonical_score.get("confidence") or 0.0)

    @property
    def missing_inputs(self) -> List[str]:
        overall = self.overall_score
        missing = overall.get("missing_inputs") or self.canonical_score.get("missing_inputs") or []
        return list(missing)

    @property
    def provenance(self) -> Dict[str, Any]:
        return dict(self.canonical_score.get("provenance") or {})

    def to_context(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "available": self.available,
            "status": self.status,
            "warning": self.warning,
            "artifact_path": self.artifact_path,
            "review_path": self.review_path,
            "generated_at": self.generated_at,
            "schema_version": self.schema_version,
            "phase2_framework_locked": self.phase2_framework_locked,
            "phase2_lock_name": self.phase2_lock_name,
            "approved_for_eipv": self.approved_for_eipv,
            "informational_only": self.informational_only,
            "source_phase1_artifact_fingerprint": self.source_phase1_artifact_fingerprint,
            "source_phase1_fact_path": self.source_phase1_fact_path,
            "source_phase1_review_path": self.source_phase1_review_path,
            "canonical_score": self.canonical_score,
            "score_audit": self.score_audit,
            "component_scores": self.component_scores,
            "overall_score": self.overall_score,
            "confidence": self.confidence,
            "missing_inputs": self.missing_inputs,
            "provenance": self.provenance,
            "review_text": self.review_text,
        }


class Phase2DownstreamAdapter:
    def __init__(self, max_artifact_age_hours: Optional[int] = None):
        self.max_artifact_age_hours = int(
            max_artifact_age_hours
            if max_artifact_age_hours is not None
            else os.getenv("PHASE2_MAX_ARTIFACT_AGE_HOURS", str(MAX_ARTIFACT_AGE_HOURS_DEFAULT))
        )

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        return str(ticker or "").strip().upper()

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _fingerprint(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _artifact_paths(self, ticker: str) -> Dict[str, Path]:
        normalized = self._normalize_ticker(ticker)
        if normalized not in PHASE2_ONBOARDING_ALLOWLIST:
            raise Phase2DownstreamError(f"Ticker {normalized or ticker!r} is not approved for Phase 2 downstream consumption.")
        config = PHASE2_TICKER_REGISTRY.get(normalized)
        if not config:
            raise Phase2DownstreamError(f"Ticker {normalized!r} is missing a Phase 2 registry entry.")
        return {
            "artifact": Path(config["output_dir"]) / f"{normalized}_phase2_artifact.json",
            "review": Path(config["output_dir"]) / f"{normalized}_phase2_review.md",
            "phase1_fact": Path(config["phase1_fact_path"]),
            "phase1_review": Path(config["phase1_review_path"]),
        }

    def _invalid(self, ticker: str, artifact_path: Path, review_path: Path, warning: str) -> Phase2DownstreamSnapshot:
        return Phase2DownstreamSnapshot(
            ticker=self._normalize_ticker(ticker),
            available=False,
            status="unavailable",
            warning=warning,
            artifact_path=str(artifact_path),
            review_path=str(review_path),
            approved_for_eipv=False,
            informational_only=True,
        )

    def load_ticker(self, ticker: str) -> Phase2DownstreamSnapshot:
        normalized = self._normalize_ticker(ticker)
        try:
            paths = self._artifact_paths(normalized)
        except Exception as exc:
            return self._invalid(normalized, Path(""), Path(""), str(exc))

        artifact_path = paths["artifact"]
        review_path = paths["review"]
        phase1_fact_path = paths["phase1_fact"]
        phase1_review_path = paths["phase1_review"]

        if not artifact_path.exists() or not review_path.exists():
            return self._invalid(normalized, artifact_path, review_path, "Phase 2 artifact or review file is missing.")

        try:
            artifact = self._read_json(artifact_path)
        except Exception as exc:
            return self._invalid(normalized, artifact_path, review_path, f"Unable to parse Phase 2 artifact: {exc}")

        canonical_score = artifact.get("canonical_score") or {}
        score_audit = artifact.get("score_audit") or {}
        generated_at = str(artifact.get("generated_at") or canonical_score.get("generated_at") or "")
        schema_version = str(artifact.get("schema_version") or canonical_score.get("schema_version") or "")
        ticker_value = str(artifact.get("ticker") or canonical_score.get("ticker") or "").strip().upper()
        framework_locked = bool(canonical_score.get("phase2_framework_locked") or artifact.get("phase2_framework_locked"))
        lock_name = str(canonical_score.get("phase2_lock_name") or artifact.get("phase2_lock_name") or "")
        source_fingerprint = str(artifact.get("source_phase1_artifact_fingerprint") or canonical_score.get("source_phase1_artifact_fingerprint") or "")
        review_text = review_path.read_text(encoding="utf-8")

        if ticker_value != normalized:
            return self._invalid(normalized, artifact_path, review_path, f"Ticker mismatch: expected {normalized}, found {ticker_value or 'missing'}.")
        if schema_version != PHASE2_SCHEMA_VERSION:
            return self._invalid(normalized, artifact_path, review_path, f"Unsupported schema version: {schema_version or 'missing'}.")
        if not framework_locked or lock_name != PHASE2_LOCK_NAME:
            return self._invalid(normalized, artifact_path, review_path, "Phase 2 lock metadata is missing or invalid.")
        if not canonical_score:
            return self._invalid(normalized, artifact_path, review_path, "Canonical Phase 2 score object is missing.")
        if not isinstance(score_audit, dict) or not bool(score_audit.get("passed")):
            return self._invalid(normalized, artifact_path, review_path, "Phase 2 score audit failed or is missing.")
        if not generated_at or self._parse_timestamp(generated_at) is None:
            return self._invalid(normalized, artifact_path, review_path, "Phase 2 artifact generation timestamp is missing or invalid.")
        artifact_age = datetime.now(timezone.utc) - self._parse_timestamp(generated_at)
        if artifact_age.total_seconds() > max(1, self.max_artifact_age_hours) * 3600:
            return self._invalid(normalized, artifact_path, review_path, f"Phase 2 artifact is stale beyond {self.max_artifact_age_hours} hours.")
        if not phase1_fact_path.exists():
            return self._invalid(normalized, artifact_path, review_path, "Source Phase 1 fact artifact is missing.")
        if source_fingerprint != self._fingerprint(phase1_fact_path):
            return self._invalid(normalized, artifact_path, review_path, "Source Phase 1 fingerprint mismatch.")
        if str(canonical_score.get("ticker") or "").strip().upper() != normalized:
            return self._invalid(normalized, artifact_path, review_path, "Canonical score ticker mismatch.")
        if str(canonical_score.get("schema_version") or "") != PHASE2_SCHEMA_VERSION:
            return self._invalid(normalized, artifact_path, review_path, "Canonical score schema version mismatch.")
        if bool(canonical_score.get("phase2_framework_locked")) is not True:
            return self._invalid(normalized, artifact_path, review_path, "Canonical score lock flag is false.")
        if str(canonical_score.get("phase2_lock_name") or "") != PHASE2_LOCK_NAME:
            return self._invalid(normalized, artifact_path, review_path, "Canonical score lock name mismatch.")

        context = Phase2DownstreamSnapshot(
            ticker=normalized,
            available=True,
            status="valid",
            artifact_path=str(artifact_path),
            review_path=str(review_path),
            generated_at=generated_at,
            source_phase1_artifact_fingerprint=source_fingerprint,
            schema_version=schema_version,
            phase2_framework_locked=framework_locked,
            phase2_lock_name=lock_name,
            approved_for_eipv=False,
            informational_only=True,
            canonical_score=canonical_score,
            score_audit=score_audit,
            review_text=review_text,
            source_phase1_fact_path=str(phase1_fact_path),
            source_phase1_review_path=str(phase1_review_path),
        )

        if review_text and str(canonical_score.get("ticker") or "").strip().upper() not in review_text:
            return self._invalid(normalized, artifact_path, review_path, "Review text does not match ticker context.")

        return context

    def load_many(self, tickers: Sequence[str]) -> Dict[str, Phase2DownstreamSnapshot]:
        results: Dict[str, Phase2DownstreamSnapshot] = {}
        for ticker in tickers:
            snapshot = self.load_ticker(ticker)
            results[snapshot.ticker] = snapshot
        return results
