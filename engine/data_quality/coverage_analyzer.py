"""Read-only, deterministic historical source coverage auditor."""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from engine.datasets.dataset_schema import canonical_json_bytes, hash_bytes, parse_date

from .coverage_report import markdown_report
from .coverage_schema import ArtifactConflictError, AuditInputError, AuditResult, EVENT_DRIVEN_SOURCES, SOURCE_FIELDS, STATUS_RANK
from .gap_analyzer import expected_dates, longest_interval, missing_dates
from .point_in_time_auditor import audit_record, availability_date
from .source_consistency import load_source_records, source_root_hash


class HistoricalCoverageAuditor:
    """Audit local imported sources without changing or invoking any engine."""

    def audit(self, *, source_root: Path | str, policy_path: Path | str, symbols: Sequence[str], start_date: str, end_date: str, frequency: str, output_root: Path | str, universe_file: Path | str | None = None, report_only_failures: bool = False) -> AuditResult:
        root, policy = Path(source_root), _load_policy(Path(policy_path))
        start, end = parse_date(start_date, field_name="start_date"), parse_date(end_date, field_name="end_date")
        if start > end or not frequency.strip():
            raise AuditInputError("start_date must not exceed end_date and frequency is required")
        canonical_symbols = tuple(sorted({str(item).upper().strip() for item in symbols if str(item).strip()}))
        if not canonical_symbols:
            raise AuditInputError("symbols must contain at least one value")
        root_hash = source_root_hash(root)
        policy_hash = hash_bytes(Path(policy_path).read_bytes())
        audit_id = hash_bytes(canonical_json_bytes({"source_root_hash": root_hash, "policy_hash": policy_hash, "symbols": list(canonical_symbols), "start_date": start.isoformat(), "end_date": end.isoformat(), "frequency": frequency}))
        records_by_source: dict[str, list[dict[str, Any]]] = {}
        consistency_errors: list[str] = []
        for source in SOURCE_FIELDS:
            records, _, errors = load_source_records(root, source)
            records_by_source[source] = records
            consistency_errors.extend(errors)
        consistency_errors.extend(_manifest_errors(root))
        if universe_file is not None:
            records_by_source["universes"] = _load_universe_file(Path(universe_file))
        symbols_report: dict[str, Any] = {}
        gaps: list[dict[str, Any]] = []
        all_lookahead: list[str] = []
        for symbol in canonical_symbols:
            source_reports: dict[str, Any] = {}
            symbol_lookahead: list[str] = []
            for source, field in SOURCE_FIELDS.items():
                source_policy = _source_policy(policy, source)
                candidates = [record for record in records_by_source[source] if source == "macro" or str(record.get("symbol", "")).upper() == symbol]
                source_result, source_gaps, failures = _coverage(source, field, candidates, start, end, source_policy, symbol, [record for record in records_by_source["universes"] if str(record.get("symbol", "")).upper() == symbol])
                source_reports[source] = source_result
                gaps.extend(source_gaps)
                symbol_lookahead.extend(failures)
            all_lookahead.extend(symbol_lookahead)
            status = _symbol_status(source_reports, symbol_lookahead, consistency_errors, policy)
            symbols_report[symbol] = {"status": status, "sources": source_reports, "lookahead_failures": sorted(set(symbol_lookahead)), "source_consistency_errors": sorted(set(consistency_errors))}
        overall = "LOOKAHEAD_FAILURE" if all_lookahead else max((details["status"] for details in symbols_report.values()), key=lambda status: STATUS_RANK[status])
        ready = tuple(symbol for symbol, details in symbols_report.items() if details["status"] == "READY")
        partial = tuple(symbol for symbol, details in symbols_report.items() if details["status"] == "PARTIAL")
        not_ready = tuple(symbol for symbol, details in symbols_report.items() if details["status"] in ("NOT_READY", "LOOKAHEAD_FAILURE"))
        report = {"audit_id": audit_id, "schema_version": "1.0.0", "status": overall, "source_root_hash": root_hash, "policy_hash": policy_hash, "symbols": symbols_report, "start_date": start.isoformat(), "end_date": end.isoformat(), "frequency": frequency, "report_only_failures": bool(report_only_failures)}
        gap_report = {"audit_id": audit_id, "gaps": sorted(gaps, key=lambda item: (item["symbol"], item["source"], item["classification"], item.get("date", "")))}
        destination = Path(output_root) / audit_id
        _publish(destination, report, gap_report, root_hash, policy_hash)
        return AuditResult(audit_id, overall, ready, partial, not_ready, tuple(sorted(set(all_lookahead))), str(destination), report)


def audit_historical_sources(**kwargs: Any) -> AuditResult:
    return HistoricalCoverageAuditor().audit(**kwargs)


def _coverage(source: str, field: str, records: list[dict[str, Any]], start: date, end: date, policy: Mapping[str, Any], symbol: str, universe_records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    valid: list[tuple[date, dict[str, Any]]] = []
    invalid: list[str] = []
    failures: list[str] = []
    for index, record in enumerate(records, 1):
        label = f"{source}/{symbol}:{index}"
        try:
            available = availability_date(source, record)
        except (KeyError, ValueError):
            invalid.append(label)
            continue
        failures.extend(audit_record(source, record, label))
        if start <= available <= end:
            valid.append((available, record))
    dates = [item[0] for item in valid]
    counts: dict[date, int] = {}
    hashes: dict[date, set[str]] = {}
    for available, record in valid:
        counts[available] = counts.get(available, 0) + 1
        hashes.setdefault(available, set()).add(hash_bytes(canonical_json_bytes(record)))
    duplicates = sorted(day.isoformat() for day, count in counts.items() if count > 1)
    conflicts = sorted(day.isoformat() for day, values in hashes.items() if len(values) > 1)
    rule = str(policy.get("period_rule", "event_driven"))
    expected = expected_dates(start, end, rule)
    covered = tuple(day for day in expected if day in set(dates)) if expected else tuple(sorted(set(dates)))
    missing = missing_dates(expected, dates)
    gaps: list[dict[str, Any]] = []
    if source in EVENT_DRIVEN_SOURCES:
        if not valid:
            gaps.append({"symbol": symbol, "source": source, "classification": "EXPECTED_EVENT_DRIVEN"})
    elif not records:
        gaps.append({"symbol": symbol, "source": source, "classification": "SOURCE_NOT_PROVIDED"})
    for day in missing:
        classification = "UNIVERSE_NOT_ACTIVE" if source != "universes" and not _universe_active(day, universe_records) else "REQUIRED_MISSING"
        gaps.append({"symbol": symbol, "source": source, "classification": classification, "date": day.isoformat()})
    for day in invalid:
        gaps.append({"symbol": symbol, "source": source, "classification": "INVALID_RECORD", "record": day})
    for day in conflicts:
        gaps.append({"symbol": symbol, "source": source, "classification": "CONFLICT", "date": day})
    stale_days = int(policy.get("stale_after_days", 0) or 0)
    stale: list[dict[str, str]] = []
    if stale_days and dates:
        last = max(dates)
        if end - last > timedelta(days=stale_days):
            stale.append({"start_date": (last + timedelta(days=1)).isoformat(), "end_date": end.isoformat()})
            gaps.append({"symbol": symbol, "source": source, "classification": "STALE", "date": (last + timedelta(days=1)).isoformat()})
    return ({"first_available_date": min(dates).isoformat() if dates else None, "last_available_date": max(dates).isoformat() if dates else None, "total_records": len(records), "expected_periods": len(expected), "covered_periods": len(covered), "missing_periods": len(missing), "coverage_percentage": round((len(covered) * 100 / len(expected)) if expected else 100.0, 6), "longest_missing_interval": longest_interval(missing), "stale_data_intervals": stale, "duplicate_dates": duplicates, "conflicting_records": conflicts, "invalid_availability_timestamps": invalid}, gaps, failures)


def _universe_active(day: date, records: list[dict[str, Any]]) -> bool:
    for record in records:
        try:
            start = parse_date(record.get("effective_from", record.get("membership_date")), field_name="effective_from")
            end_value = record.get("effective_to")
            end = parse_date(end_value, field_name="effective_to") if end_value else date.max
            if start <= day <= end:
                return True
        except ValueError:
            continue
    return False


def _symbol_status(sources: Mapping[str, Any], failures: Sequence[str], consistency_errors: Sequence[str], policy: Mapping[str, Any]) -> str:
    if failures:
        return "LOOKAHEAD_FAILURE"
    if consistency_errors:
        return "NOT_READY"
    universe = sources["universes"]
    if universe["total_records"] == 0:
        return "NOT_READY"
    partial = False
    for source in ("prices", "fundamentals"):
        data = sources[source]
        threshold = float(_source_policy(policy, source).get("minimum_coverage_percentage", 100))
        if data["total_records"] == 0:
            return "NOT_READY"
        if data["coverage_percentage"] < threshold or data["conflicting_records"] or data["invalid_availability_timestamps"]:
            partial = True
    return "PARTIAL" if partial else "READY"


def _source_policy(policy: Mapping[str, Any], source: str) -> Mapping[str, Any]:
    value = policy.get("sources", {}).get(source, {})
    if not isinstance(value, Mapping):
        raise AuditInputError(f"policy sources.{source} must be an object")
    return value


def _load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditInputError(f"invalid policy: {path}") from exc
    if not isinstance(policy, dict) or not isinstance(policy.get("sources"), dict):
        raise AuditInputError("policy must contain a sources object")
    return policy


def _load_universe_file(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
        values = [json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(raw)
        values = values.get("records") if isinstance(values, dict) else values
        if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
            raise ValueError("must contain a list of objects")
        return values
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise AuditInputError(f"invalid universe file: {path}") from exc


def _manifest_errors(root: Path) -> list[str]:
    manifest_path = root / "import_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("source_hashes", {})
        errors = []
        for source, expected_hash in sorted(expected.items()):
            records_path = root / source / "records.jsonl"
            if not records_path.is_file() or hash_bytes(records_path.read_bytes()) != expected_hash:
                errors.append(f"{source}: source hash mismatch")
        return errors
    except (OSError, json.JSONDecodeError, AttributeError):
        return ["import_manifest.json: invalid manifest"]


def _publish(destination: Path, report: dict[str, Any], gap_report: dict[str, Any], root_hash: str, policy_hash: str) -> None:
    files = {"coverage_report.json": canonical_json_bytes(report), "coverage_report.md": markdown_report(report).encode("utf-8"), "gap_report.json": canonical_json_bytes(gap_report)}
    manifest = {"audit_id": report["audit_id"], "source_root_hash": root_hash, "policy_hash": policy_hash, "artifact_hashes": {name: hash_bytes(content) for name, content in sorted(files.items())}}
    files["audit_manifest.json"] = canonical_json_bytes(manifest)
    if destination.exists():
        existing = {path.name: path.read_bytes() for path in destination.iterdir() if path.is_file()}
        if existing != files:
            raise ArtifactConflictError(f"audit artifact conflict: {destination}")
        return
    with TemporaryDirectory(prefix="mcleod_audit_") as temporary_root:
        staging = Path(temporary_root) / destination.name
        staging.mkdir()
        for name, content in files.items():
            (staging / name).write_bytes(content)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_destination = destination.parent / f".{destination.name}.staging"
        if temporary_destination.exists():
            shutil.rmtree(temporary_destination)
        shutil.copytree(staging, temporary_destination)
        os.replace(temporary_destination, destination)