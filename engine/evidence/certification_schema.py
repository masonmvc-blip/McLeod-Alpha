from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


DECISIONS = frozenset(("CERTIFIED", "REJECTED", "NEEDS_MORE_EVIDENCE"))


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=False) + "\n").encode("utf-8")


def content_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class CertificationPolicy:
    policy_id: str
    version: str
    created_at: str
    description: str
    minimum_train_performance: float
    minimum_test_performance: float
    minimum_effect_size: float
    minimum_confidence_level: float
    maximum_drawdown_increase: float
    maximum_turnover_increase: float
    minimum_stability_score: float
    minimum_reproducibility_score: float
    minimum_economic_significance: float

    @property
    def policy_hash(self) -> str:
        return content_hash(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "policy_hash": self.policy_hash}


@dataclass(frozen=True)
class Certification:
    certification_id: str
    experiment_id: str
    policy_id: str
    policy_version: str
    decision: str
    timestamp: str
    artifact_hash: str
    policy_hash: str
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)