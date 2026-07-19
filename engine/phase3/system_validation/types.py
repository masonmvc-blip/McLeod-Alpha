from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class EndToEndAuditStep:
    stage: str
    passed: bool
    detail: str
    timestamp: str
    record: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EndToEndAudit:
    modules_executed: tuple[str, ...]
    validation_status: str
    execution_order: tuple[str, ...]
    artifact_versions: Mapping[str, str]
    dependency_graph: Mapping[str, tuple[str, ...]]
    timestamps: Mapping[str, str]
    configuration_hash: str
    deterministic_replay_hash: str
    steps: tuple[EndToEndAuditStep, ...] = field(default_factory=tuple)
