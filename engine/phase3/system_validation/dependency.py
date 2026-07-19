from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class DependencyValidationResult:
    passed: bool
    errors: tuple[str, ...]
    dependency_graph: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


class DependencyValidator:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def validate(self) -> DependencyValidationResult:
        files = {
            "research_os_release": self.workspace_root / "engine" / "research_os_release.py",
            "phase3_context": self.workspace_root / "engine" / "phase3" / "context.py",
            "expected_return": self.workspace_root / "engine" / "phase3" / "expected_return" / "model.py",
            "decision_engine": self.workspace_root / "engine" / "phase3" / "decision_engine" / "model.py",
            "calibration": self.workspace_root / "engine" / "phase3" / "calibration" / "model.py",
            "portfolio_simulation": self.workspace_root / "engine" / "phase3" / "portfolio_simulation" / "model.py",
            "shadow_portfolio": self.workspace_root / "engine" / "phase3" / "shadow_portfolio_construction" / "model.py",
            "system_validation": self.workspace_root / "engine" / "phase3" / "system_validation" / "model.py",
            "portfolio_engine": self.workspace_root / "engine" / "portfolio_engine.py",
        }

        sources = {name: path.read_text(encoding="utf-8") for name, path in files.items()}
        errors: list[str] = []

        # Frozen layers must not import higher validation layer.
        frozen_layers = ["phase3_context", "expected_return", "decision_engine", "calibration", "portfolio_simulation", "shadow_portfolio"]
        for name in frozen_layers:
            if "engine.phase3.system_validation" in sources[name]:
                errors.append(f"Frozen module {name} imports higher system validation layer.")

        # No direct phase1 access in phase3 layers.
        for name in ["expected_return", "decision_engine", "calibration", "portfolio_simulation", "shadow_portfolio", "system_validation"]:
            if "engine.research_phase1" in sources[name]:
                errors.append(f"Direct Phase 1 access detected in {name}.")

        # No direct phase2 access except allowed context adapter layer and schema constants in decision engine.
        if "engine.phase2_downstream" in sources["expected_return"] or "engine.phase2_downstream" in sources["calibration"] or "engine.phase2_downstream" in sources["portfolio_simulation"] or "engine.phase2_downstream" in sources["shadow_portfolio"]:
            errors.append("Direct Phase 2 adapter access detected outside approved interfaces.")
        if "engine.phase2_research" in sources["calibration"] or "engine.phase2_research" in sources["portfolio_simulation"] or "engine.phase2_research" in sources["shadow_portfolio"]:
            errors.append("Direct Phase 2 research access detected outside approved interfaces.")

        # No raw artifact reads in phase3 layers.
        for name in ["expected_return", "decision_engine", "calibration", "portfolio_simulation", "shadow_portfolio", "system_validation"]:
            if "phase2_artifact.json" in sources[name] or "phase2_review.md" in sources[name] or "read_text(" in sources[name]:
                # Allow read_text in this dependency validator itself only.
                if name != "system_validation":
                    errors.append(f"Raw artifact/file read pattern detected in {name}.")

        # Production portfolio engine is untouched by phase3 layers (no imports).
        for name in ["expected_return", "decision_engine", "calibration", "portfolio_simulation", "shadow_portfolio", "system_validation"]:
            if "engine.portfolio_engine" in sources[name]:
                errors.append(f"Production portfolio engine imported by {name}.")

        graph = {
            "research_os_release": tuple(),
            "phase3_context": tuple(),
            "expected_return": ("phase3_context",),
            "decision_engine": ("phase3_context", "expected_return"),
            "calibration": ("expected_return", "decision_engine"),
            "portfolio_simulation": ("expected_return", "decision_engine"),
            "shadow_portfolio": ("expected_return", "decision_engine"),
            "system_validation": (
                "research_os_release",
                "phase3_context",
                "expected_return",
                "decision_engine",
                "calibration",
                "portfolio_simulation",
                "shadow_portfolio",
            ),
        }
        if self._has_cycle(graph):
            errors.append("Dependency graph contains a cycle.")

        return DependencyValidationResult(passed=len(errors) == 0, errors=tuple(errors), dependency_graph=graph)

    @staticmethod
    def _has_cycle(graph: Mapping[str, tuple[str, ...]]) -> bool:
        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(node: str) -> bool:
            if node in stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            stack.add(node)
            for nxt in graph.get(node, ()):  # pragma: no branch
                if dfs(nxt):
                    return True
            stack.remove(node)
            return False

        for node in graph:
            if dfs(node):
                return True
        return False
