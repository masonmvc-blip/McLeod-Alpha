"""Immutable policy constants and result types for data-quality audits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SOURCE_FIELDS = {
    "sec": "filing_date",
    "prices": "price_date",
    "fundamentals": "available_date",
    "macro": "release_date",
    "analysts": "revision_date",
    "news": "published_at",
    "universes": "membership_date",
}
EVENT_DRIVEN_SOURCES = frozenset(("sec", "analysts", "news"))
STATUS_RANK = {"READY": 0, "PARTIAL": 1, "NOT_READY": 2, "LOOKAHEAD_FAILURE": 3}


class AuditInputError(ValueError):
    """Raised for invalid source data, policy, or audit parameters."""


class ArtifactConflictError(FileExistsError):
    """Raised when a deterministic audit path contains different artifacts."""


@dataclass(frozen=True)
class AuditResult:
    audit_id: str
    status: str
    symbols_ready: tuple[str, ...]
    symbols_partial: tuple[str, ...]
    symbols_not_ready: tuple[str, ...]
    lookahead_failures: tuple[str, ...]
    output_path: str
    report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "symbols_ready": list(self.symbols_ready), "symbols_partial": list(self.symbols_partial), "symbols_not_ready": list(self.symbols_not_ready), "lookahead_failures": list(self.lookahead_failures)}