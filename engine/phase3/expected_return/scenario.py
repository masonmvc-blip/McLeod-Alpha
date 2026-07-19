from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Scenario:
    intrinsic_value: float
    probability: float
    rationale: str
    supporting_assumptions: Mapping[str, Any] = field(default_factory=dict)
