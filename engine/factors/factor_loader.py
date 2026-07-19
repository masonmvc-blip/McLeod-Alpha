from __future__ import annotations

from .factor_contract import FactorContract
from .factor_registry import FactorRegistry


def load_factor(registry: FactorRegistry, factor_id: str, version: str | None = None) -> FactorContract:
    factor = registry.load(factor_id, version)
    if factor.metadata.retired:
        raise ValueError(f"retired factor cannot be loaded: {factor_id}")
    return factor