"""Build a deterministic inventory from pytest's short-trace failure summary."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


FAILURE = re.compile(r"^FAILED (?P<node>.+?) - (?P<exception>[\w.]+(?:Error|Exception)|AssertionError): (?P<message>.*)$")
SUMMARY_FAILURE = re.compile(r"^FAILED (?P<node>.+)$")


def classify(exception: str, message: str, node_id: str) -> tuple[str, str, str, str]:
    text = f"{exception} {message}".lower()
    if "offset-naive" in text or "offset-aware" in text:
        return "TIMEZONE_BUG", "mixed naive and timezone-aware datetimes", "execution", "normalize test-facing timestamps to UTC-aware values"
    if exception == "AttributeError" and "phase3_monitor" in text:
        return "LEGACY_API_MISMATCH", "test expects a removed phase3_monitor public helper", "phase3_monitor", "locate canonical helper and add a thin compatibility wrapper"
    if "historical csv" in text or "csv file not found" in text:
        return "MISSING_FIXTURE", "historical input fixture is unavailable", "backtesting", "use a minimal synthetic fixture only when test-defined structure is complete"
    if exception == "FileNotFoundError" or "missing report:" in text or "missing frozen" in text:
        return "MISSING_ARTIFACT", "required generated or frozen artifact is absent", "research_validation", "generate only artifacts whose deterministic inputs and schema are locally available"
    if "artifact is not ready" in text or "missing" in text:
        return "ENVIRONMENT_DEPENDENCY", "required validated research inputs are unavailable in this checkout", "research", "restore the verified dependency; do not fabricate it"
    if exception == "AssertionError":
        return "ACTUAL_LOGIC_REGRESSION", "assertion requires targeted subsystem review", _subsystem(node_id), "inspect the focused failing test and its owning implementation"
    return "OTHER", "unclassified pytest failure", _subsystem(node_id), "inspect the focused failure before changing code"


def _subsystem(node_id: str) -> str:
    path = node_id.split("::", 1)[0]
    if "phase" in path or "research" in path:
        return "research"
    if "portfolio" in path:
        return "portfolio"
    return "general"


def inventory(report_text: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line in report_text.splitlines():
        match = FAILURE.match(line.strip())
        if not match:
            continue
        node_id, exception, message = match.group("node"), match.group("exception"), match.group("message")
        category, root_cause, subsystem, recommendation = classify(exception, message, node_id)
        records.append({
            "test_node_id": node_id,
            "source_file": node_id.split("::", 1)[0],
            "exception_type": exception,
            "message": message,
            "category": category,
            "suspected_root_cause": root_cause,
            "affected_subsystem": subsystem,
            "introduced_by_recent_work": "unknown",
            "recommended_smallest_fix": recommendation,
            "confidence": "high" if category in {"TIMEZONE_BUG", "LEGACY_API_MISMATCH", "MISSING_FIXTURE", "MISSING_ARTIFACT"} else "medium",
        })
    counts = dict(sorted(Counter(record["category"] for record in records).items()))
    return {"schema_version": "1.0.0", "failure_count": len(records), "category_counts": counts, "failures": records}


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# Regression Failure Inventory", "", f"Failures: {payload['failure_count']}", "", "## Categories", ""]
    lines.extend(f"- {category}: {count}" for category, count in payload["category_counts"].items())
    lines.extend(("", "## Failures", "", "| Test | Category | Exception | Message |", "| --- | --- | --- | --- |"))
    for item in payload["failures"]:
        message = item["message"].replace("|", "\\|")
        lines.append(f"| `{item['test_node_id']}` | {item['category']} | {item['exception_type']} | {message} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    parser.add_argument("--compatibility-audit", type=Path)
    parser.add_argument("--supported-contracts", type=Path)
    args = parser.parse_args(argv)
    payload = inventory(args.report.read_text(encoding="utf-8"))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown(payload), encoding="utf-8")
    if args.compatibility_audit and args.supported_contracts:
        contracts = compatibility_audit(args.report.read_text(encoding="utf-8"))
        args.supported_contracts.write_text(json.dumps(contracts["contracts"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.compatibility_audit.write_text(contracts["markdown"], encoding="utf-8")
    return 0


def compatibility_audit(report_text: str) -> dict[str, Any]:
    nodes = [match.group("node") for line in report_text.splitlines() if (match := SUMMARY_FAILURE.match(line.strip()))]
    items = [_contract_item(node) for node in nodes]
    contracts = {"schema_version": "1.0.0", "failing_tests": items}
    lines = ["# Legacy Compatibility Audit", "", "This is a read-only audit of the completed regression report.", "", "| Test | Status | Replacement / disposition | Production reference | Retire test? |", "| --- | --- | --- | --- | --- |"]
    for item in items:
        lines.append(f"| `{item['test_node']}` | {item['status']} | {item['replacement_subsystem']} | {item['production_reference']} | {item['retire_test']} |")
    return {"contracts": contracts, "markdown": "\n".join(lines) + "\n"}


def _contract_item(node: str) -> dict[str, str]:
    lower = node.lower()
    if "absorption_score" in lower or "reject_continuation" in lower:
        return {"test_node": node, "status": "LEGACY", "replacement_subsystem": "strategy.signals / execution feature payload; no canonical helper wrapper exists", "production_reference": "none outside tests", "retire_test": "yes"}
    if "daily_opportunity_review" in lower or "market_regime_filter" in lower:
        return {"test_node": node, "status": "SUPERSEDED", "replacement_subsystem": "phase3_monitor.run_monitor runtime boundary", "production_reference": "cockpit.py and alpha.py launch phase3_monitor.py", "retire_test": "yes"}
    if "stop_policy" in lower:
        return {"test_node": node, "status": "ACTIVE", "replacement_subsystem": "execution.paper_engine", "production_reference": "active paper execution path", "retire_test": "no"}
    if "regime_filter_ab" in lower:
        return {"test_node": node, "status": "ACTIVE", "replacement_subsystem": "backtesting.regime_filter_ab", "production_reference": "local backtesting tool", "retire_test": "no"}
    if "phase1" in lower or "phase2" in lower or "research" in lower or "portfolio" in lower or "validation" in lower or "certification" in lower:
        return {"test_node": node, "status": "SUPERSEDED", "replacement_subsystem": "frozen research/portfolio release artifacts", "production_reference": "no direct live-monitor reference", "retire_test": "yes, after release contract is formally retired"}
    return {"test_node": node, "status": "UNKNOWN", "replacement_subsystem": "not established by local references", "production_reference": "unknown", "retire_test": "no"}


if __name__ == "__main__":
    raise SystemExit(main())