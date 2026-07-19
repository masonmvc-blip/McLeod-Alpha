from __future__ import annotations

from .factor_registry import FactorRegistry
from .factor_versioning import version_key


def validate_registry(registry: FactorRegistry) -> dict:
    findings: list[str] = []
    factors = registry.factors()
    ids = [factor.metadata.factor_id for factor in factors]
    names = [factor.metadata.name for factor in factors]
    if len(set(ids)) != len({(item.metadata.factor_id, item.metadata.version) for item in factors}):
        findings.append("duplicate factor version")
    if len(set(names)) != len({(item.metadata.factor_id, item.metadata.name) for item in factors}):
        findings.append("duplicate factor name")
    for factor in factors:
        metadata = factor.metadata
        version_key(metadata.version)
        if not metadata.required_snapshot_fields:
            findings.append(f"missing required snapshot fields: {metadata.factor_id}@{metadata.version}")
        if not metadata.point_in_time_safe or not metadata.deterministic:
            findings.append(f"unsafe metadata declaration: {metadata.factor_id}@{metadata.version}")
    return {"valid": not findings, "findings": sorted(findings), "factor_count": len(factors)}