from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class CertificationResult:
    passed: bool
    verified_milestones: tuple[str, ...]
    checked_reports: tuple[str, ...]
    checked_suites: tuple[str, ...]
    checked_packages: tuple[str, ...]
    frozen_hash_checks: Mapping[str, bool]
    dependency_graph_valid: bool
    lifecycle_registry_valid: bool
    package_isolation_valid: bool
    report_references_valid: bool
    marker_validation_consistent: bool
    deterministic_replay_from_clean_repo: bool
    discrepancies: tuple[str, ...] = field(default_factory=tuple)
    unresolved_risks: tuple[str, ...] = field(default_factory=tuple)
    observations: tuple[str, ...] = field(default_factory=tuple)
