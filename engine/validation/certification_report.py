from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_CERTIFICATION_REPORT_PATH = Path("artifacts") / "validation" / "certifications" / "validation_certification.md"


@dataclass(frozen=True)
class CertificationMarkdown:
    report_path: str
    markdown: str


def render_validation_certification_markdown(result) -> str:
    lines: list[str] = [
        "# Validation Certification",
        "",
        "## Executive Summary",
        result.executive_summary,
        "",
        "## Certification Status",
        f"- certification_id: {result.certification_id}",
        f"- status: {result.status}",
        f"- policy_version: {result.policy_version}",
        f"- system_version: {result.system_version}",
        f"- as_of_date: {result.as_of_date}",
        "",
        "## Paper Trading Eligibility",
        f"- eligible_for_paper_trading: {str(result.eligible_for_paper_trading).lower()}",
        "",
        "## Data Sufficiency",
    ]
    for check in result.checks:
        if check.category == "data_sufficiency":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Benchmark Performance"])
    for check in result.checks:
        if check.category == "benchmark_performance":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Risk Metrics"])
    for check in result.checks:
        if check.category == "risk":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Calibration"])
    for check in result.checks:
        if check.category == "calibration":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Drift"])
    for check in result.checks:
        if check.category == "drift":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Integrity"])
    for check in result.checks:
        if check.category == "integrity":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Determinism"])
    for check in result.checks:
        if check.category == "determinism":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Lookahead Safety"])
    for check in result.checks:
        if check.category == "lookahead_safety":
            lines.append(f"- {check.metric}: {check.status} ({check.reason})")

    lines.extend(["", "## Blocking Failures"])
    if result.blocking_failures:
        lines.extend(f"- {item}" for item in result.blocking_failures)
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings"])
    if result.warnings:
        lines.extend(f"- {item}" for item in result.warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Required Remediation"])
    if result.blocking_failures:
        lines.append("- Resolve all blocking failures before extended paper trading.")
    elif result.warnings:
        lines.append("- Resolve warnings before requesting PASS certification.")
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Certification Manifest",
        f"- validation_report_hash: {result.validation_report_hash}",
        f"- policy_hash: {result.policy_hash}",
        f"- content_hash: {result.content_hash}",
    ])
    return "\n".join(lines) + "\n"
