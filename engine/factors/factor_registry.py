from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Iterable

from .factor_contract import FactorContract
from .factor_schema import canonical_bytes, content_hash
from .factor_versioning import version_key


class FactorRegistry:
    def __init__(self) -> None:
        self._versions: dict[str, dict[str, FactorContract]] = {}

    def register(self, factor: FactorContract) -> None:
        metadata = factor.metadata
        existing_names = {item.metadata.name: factor_id for factor_id, versions in self._versions.items() for item in versions.values()}
        owner = existing_names.get(metadata.name)
        if owner is not None and owner != metadata.factor_id:
            raise ValueError(f"duplicate factor name: {metadata.name}")
        versions = self._versions.setdefault(metadata.factor_id, {})
        if metadata.version in versions:
            if versions[metadata.version].metadata != metadata:
                raise ValueError("immutable factor version conflict")
            return
        versions[metadata.version] = factor

    def load(self, factor_id: str, version: str | None = None) -> FactorContract:
        versions = self._versions.get(factor_id)
        if not versions:
            raise KeyError(f"unknown factor: {factor_id}")
        selected = version or max(versions, key=version_key)
        if selected not in versions:
            raise KeyError(f"unknown factor version: {factor_id}@{selected}")
        return versions[selected]

    def factors(self) -> tuple[FactorContract, ...]:
        return tuple(self.load(factor_id, version) for factor_id in sorted(self._versions) for version in sorted(self._versions[factor_id], key=version_key))

    def artifact_payload(self) -> dict:
        return {"factors": [factor.metadata.to_dict() for factor in self.factors()], "current_versions": {factor_id: self.load(factor_id).metadata.version for factor_id in sorted(self._versions)}}

    def write_artifacts(self, root: Path | str, validation_report: dict) -> None:
        destination = Path(root); destination.mkdir(parents=True, exist_ok=True)
        registry = self.artifact_payload()
        registry_bytes = canonical_bytes(registry)
        report_bytes = canonical_bytes(validation_report)
        manifest = {"registry_hash": sha256(registry_bytes).hexdigest(), "validation_report_hash": sha256(report_bytes).hexdigest(), "content_hash": content_hash({"registry": registry, "validation_report": validation_report})}
        (destination / "registry.json").write_bytes(registry_bytes)
        (destination / "validation_report.json").write_bytes(report_bytes)
        (destination / "registry_manifest.json").write_bytes(canonical_bytes(manifest))
        lines = ["# Factor Validation Report", "", f"Valid: {validation_report['valid']}", "", "## Findings"] + [f"- {item}" for item in validation_report["findings"]]
        (destination / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")