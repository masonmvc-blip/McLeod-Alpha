from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from engine.phase3.approval import ApprovalState


class BlockingCode(str, Enum):
    NOT_APPROVED = "NOT_APPROVED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INVALID_EXPECTED_RETURN = "INVALID_EXPECTED_RETURN"
    INVALID_ARTIFACT = "INVALID_ARTIFACT"
    STALE_ARTIFACT = "STALE_ARTIFACT"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"


@dataclass(frozen=True)
class DecisionAuditStep:
    step: str
    passed: bool
    detail: str
    timestamp: str
    record: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionAudit:
    ticker: str
    approval_state: ApprovalState
    blocking_reasons: tuple[BlockingCode, ...]
    steps: tuple[DecisionAuditStep, ...]
    deterministic_record: Mapping[str, Any] = field(default_factory=dict)
