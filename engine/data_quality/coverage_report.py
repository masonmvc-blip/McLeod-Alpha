"""Canonical report rendering."""

from __future__ import annotations

from typing import Any


def markdown_report(report: dict[str, Any]) -> str:
    lines = [f"# Historical Data Coverage Audit {report['audit_id']}", "", f"Status: **{report['status']}**", "", "## Symbol Readiness", ""]
    for symbol, details in sorted(report["symbols"].items()):
        lines.append(f"- {symbol}: {details['status']}")
    lines.extend(("", "## Source Coverage", ""))
    for symbol, details in sorted(report["symbols"].items()):
        for source, coverage in sorted(details["sources"].items()):
            lines.append(f"- {symbol} / {source}: {coverage['coverage_percentage']:.2f}% ({coverage['covered_periods']}/{coverage['expected_periods']})")
    return "\n".join(lines) + "\n"