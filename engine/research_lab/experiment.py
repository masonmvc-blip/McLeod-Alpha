from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=False) + "\n").encode("utf-8")


def content_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    name: str
    description: str
    hypothesis: str
    factors: tuple[str, ...]
    dataset: str
    replay_window: tuple[str, str]
    benchmark: str
    metrics: tuple[str, ...]
    seed: int
    status: str = "PROPOSED"

    @classmethod
    def create(cls, **values: Any) -> "Experiment":
        payload = {key: values[key] for key in ("name", "description", "hypothesis", "factors", "dataset", "replay_window", "benchmark", "metrics", "seed")}
        return cls(experiment_id=content_hash(payload), factors=tuple(payload.pop("factors")), replay_window=tuple(payload.pop("replay_window")), metrics=tuple(payload.pop("metrics")), **payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)