"""Point-in-time integrity checks; confirmed violations are never downgraded."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from engine.datasets.dataset_schema import parse_date

from .coverage_schema import SOURCE_FIELDS


def availability_date(source: str, record: Mapping[str, Any]) -> date:
    return parse_date(record[SOURCE_FIELDS[source]], field_name=SOURCE_FIELDS[source])


def audit_record(source: str, record: Mapping[str, Any], label: str) -> tuple[str, ...]:
    failures: list[str] = []
    try:
        available = availability_date(source, record)
    except (KeyError, ValueError):
        return (f"{label}: invalid availability timestamp",)
    if source == "prices" and available != parse_date(record.get("price_date"), field_name="price_date"):
        failures.append(f"{label}: price availability differs from price_date")
    if source == "universes":
        try:
            effective_from = parse_date(record.get("effective_from", record.get("membership_date")), field_name="effective_from")
            effective_to = record.get("effective_to")
            if effective_to and parse_date(effective_to, field_name="effective_to") < effective_from:
                failures.append(f"{label}: effective_to precedes effective_from")
        except ValueError:
            failures.append(f"{label}: invalid universe effective period")
    publication = _publication_date(record)
    if publication and available < publication:
        failures.append(f"{label}: availability precedes source publication timestamp")
    ignored = {SOURCE_FIELDS[source]}
    if source == "universes":
        ignored.update(("effective_from", "effective_to", "membership_date"))
    failures.extend(_nested_future_dates(record, available, label, ignored_keys=ignored))
    return tuple(sorted(set(failures)))


def _publication_date(record: Mapping[str, Any]) -> date | None:
    metadata = record.get("source_metadata")
    candidates = [record.get("publication_date"), record.get("publication_timestamp")]
    if isinstance(metadata, Mapping):
        candidates.extend((metadata.get("publication_date"), metadata.get("publication_timestamp"), metadata.get("published_at")))
    for value in candidates:
        if value not in (None, ""):
            try:
                return parse_date(value, field_name="publication timestamp")
            except ValueError:
                return None
    return None


def _nested_future_dates(value: Any, available: date, path: str, *, nested: bool = False, ignored_keys: set[str] | None = None) -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            if str(key) not in (ignored_keys or set()):
                failures.extend(_nested_future_dates(value[key], available, f"{path}.{key}", nested=True, ignored_keys=ignored_keys))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            failures.extend(_nested_future_dates(item, available, f"{path}[{index}]", nested=True, ignored_keys=ignored_keys))
    elif nested and isinstance(value, str):
        try:
            if parse_date(value, field_name=path) > available:
                failures.append(f"{path}: nested future date {value} exceeds availability {available.isoformat()}")
        except ValueError:
            pass
    return failures