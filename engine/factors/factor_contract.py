from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import inspect
from types import MappingProxyType
from typing import Any, Callable

from .factor_schema import FactorMetadata


_BANNED_SOURCE_TOKENS = ("open(", "requests.", "urllib.", "socket.", "random.", "time.time(", "datetime.now(")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _field(snapshot: Mapping[str, Any], path: str) -> Any:
    value: Any = snapshot
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ValueError(f"missing required snapshot field: {path}")
        value = value[part]
    return value


@dataclass(frozen=True)
class FactorContract:
    metadata: FactorMetadata
    evaluator: Callable[[Mapping[str, Any]], float]

    def __post_init__(self) -> None:
        if not callable(self.evaluator):
            raise ValueError("factor evaluator must be callable")
        try:
            source = inspect.getsource(self.evaluator)
        except (OSError, TypeError):
            source = ""
        if any(token in source for token in _BANNED_SOURCE_TOKENS):
            raise ValueError("factor evaluator uses prohibited I/O, time, or randomness")
        if getattr(self.evaluator, "__closure__", None):
            raise ValueError("factor evaluator must not capture mutable state")

    def evaluate(self, snapshot: Mapping[str, Any]) -> float:
        frozen = _freeze(snapshot)
        for field in self.metadata.required_snapshot_fields:
            _field(frozen, field)
        before = repr(frozen)
        value = float(self.evaluator(frozen))
        if repr(frozen) != before:
            raise ValueError(f"factor {self.metadata.factor_id} mutated its snapshot")
        return value