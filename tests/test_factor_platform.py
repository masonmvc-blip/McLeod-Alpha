from __future__ import annotations

from pathlib import Path
import pytest

from engine.factors import FactorContract, FactorMetadata, FactorRegistry, load_factor, validate_registry


def _metadata(version: str = "1.0.0", factor_id: str = "quality.margin") -> FactorMetadata:
    return FactorMetadata(factor_id, "Margin Quality", version, "research", "2024-01-01T00:00:00Z", "margin", "durable margins", "POSITIVE", "QUALITY", ("quality",), ("company_fundamentals.margin",), True, True, "EXPERIMENTAL", True, False)


def _margin(snapshot):
    return snapshot["company_fundamentals"]["margin"]


def test_pure_contract_version_loading_and_deterministic_artifacts(tmp_path: Path) -> None:
    registry = FactorRegistry()
    first = FactorContract(_metadata("1.0.0"), _margin)
    second = FactorContract(_metadata("1.1.0"), _margin)
    registry.register(second); registry.register(first)
    snapshot = {"company_fundamentals": {"margin": 0.2}}
    assert load_factor(registry, "quality.margin", "1.0.0").evaluate(snapshot) == 0.2
    assert registry.load("quality.margin").metadata.version == "1.1.0"
    report = validate_registry(registry)
    registry.write_artifacts(tmp_path / "first", report); registry.write_artifacts(tmp_path / "second", report)
    assert {entry.name: entry.read_bytes() for entry in (tmp_path / "first").iterdir()} == {entry.name: entry.read_bytes() for entry in (tmp_path / "second").iterdir()}


def test_duplicate_and_invalid_factor_rejection() -> None:
    registry = FactorRegistry(); registry.register(FactorContract(_metadata(), _margin))
    with pytest.raises(ValueError, match="duplicate factor name"):
        registry.register(FactorContract(_metadata(factor_id="other.margin"), _margin))
    with pytest.raises(ValueError, match="point-in-time"):
        FactorMetadata("bad", "Bad", "1.0.0", "a", "2024-01-01", "d", "r", "POSITIVE", "CUSTOM", (), ("x",), False, True, "PROPOSED", True, False)
    def impure(snapshot):
        snapshot["company_fundamentals"]["margin"] = 1
        return 1
    with pytest.raises(TypeError):
        FactorContract(_metadata("2.0.0"), impure).evaluate({"company_fundamentals": {"margin": 0.2}})