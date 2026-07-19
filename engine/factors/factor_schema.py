from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from .factor_categories import CATEGORIES
from .factor_tags import normalize_tags


STATUSES = frozenset(("PROPOSED", "EXPERIMENTAL", "UNDER_TEST", "CERTIFIED", "ACTIVE", "DEPRECATED", "RETIRED"))


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=False) + "\n").encode("utf-8")


def content_hash(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class FactorMetadata:
    factor_id: str
    name: str
    version: str
    author: str
    created_at: str
    description: str
    economic_rationale: str
    expected_direction: str
    category: str
    tags: tuple[str, ...]
    required_snapshot_fields: tuple[str, ...]
    point_in_time_safe: bool
    deterministic: bool
    status: str
    evidence_required: bool
    retired: bool
    dependencies: tuple[str, ...] = ()
    certification_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.factor_id, self.name, self.version, self.author, self.created_at, self.description, self.economic_rationale, self.expected_direction)):
            raise ValueError("all required factor metadata fields are required")
        if self.category not in CATEGORIES or self.status not in STATUSES:
            raise ValueError("invalid factor category or lifecycle status")
        if not self.point_in_time_safe or not self.deterministic:
            raise ValueError("factors must declare point-in-time safety and determinism")
        object.__setattr__(self, "tags", normalize_tags(self.tags))
        object.__setattr__(self, "required_snapshot_fields", tuple(sorted(set(self.required_snapshot_fields))))
        object.__setattr__(self, "dependencies", tuple(sorted(set(self.dependencies))))
        object.__setattr__(self, "certification_references", tuple(sorted(set(self.certification_references))))

    @property
    def metadata_hash(self) -> str:
        return content_hash(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "metadata_hash": self.metadata_hash}