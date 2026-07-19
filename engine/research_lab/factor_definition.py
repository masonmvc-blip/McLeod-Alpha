from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    evaluator: Callable[[Mapping[str, Any]], float]

    def evaluate(self, snapshot: Mapping[str, Any]) -> float:
        before = repr(snapshot)
        value = float(self.evaluator(snapshot))
        if repr(snapshot) != before:
            raise ValueError(f"factor {self.name} modified its snapshot")
        return value