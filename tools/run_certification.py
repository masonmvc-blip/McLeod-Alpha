from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PYTHON = REPO_ROOT / ".venv-1" / "bin" / "python"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "artifacts" / "certification_run"
DISCOVERY_PATTERNS = (
    "test_*invariants.py",
    "test_*certification*.py",
    "test_system_validation*.py",
    "test_research_lab*.py",
    "test_phase*_framework*.py",
)
IGNORED_PATH_PARTS = {".git", ".venv", "artifacts", "archive", "backups", "node_modules", "venv", "__pycache__"}


@dataclass(frozen=True)
class CertificationSuite:
    name: str
    command: Sequence[str]
    output_dir: str
    target: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _package_version(package_name: str) -> str | None:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _is_ignored_path(path: Path) -> bool:
    return any(part in IGNORED_PATH_PARTS for part in path.parts)


def _discover_test_files(repo_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in DISCOVERY_PATTERNS:
        for path in repo_root.rglob(pattern):
            if not path.is_file():
                continue
            relative_path = path.relative_to(repo_root)
            if _is_ignored_path(relative_path):
                continue
            candidates.append(relative_path)
    return sorted({candidate for candidate in candidates}, key=lambda p: p.as_posix())


def _slugify_path(path: Path) -> str:
    return path.with_suffix("").as_posix().replace("/", "__")


def discover_certification_suites(repo_root: Path = REPO_ROOT) -> list[CertificationSuite]:
    suites: list[CertificationSuite] = [
        CertificationSuite(
            name="collect_only",
            command=("--collect-only", "-q"),
            output_dir="collect_only",
            target="repo",
        )
    ]

    for path in _discover_test_files(repo_root):
        slug = _slugify_path(path)
        suites.append(
            CertificationSuite(
                name=slug,
                command=("-q", path.as_posix()),
                output_dir=f"discovered/{slug}",
                target=path.as_posix(),
            )
        )

    suites.append(
        CertificationSuite(
            name="canonical_matrix",
            command=("-q",),
            output_dir="canonical_matrix",
            target="repo",
        )
    )
    return suites


def _classify_failure(text: str) -> str:
    lowered = text.lower()
    if "filenotfounderror" in lowered or "missing artifact" in lowered or "does not exist" in lowered:
        return "missing artifact"
    if "modulenotfounderror" in lowered or "importerror" in lowered:
        return "import"
    if "no module named pytest" in lowered or "no module named" in lowered and "pytest" in lowered:
        return "environment"
    if "assertionerror" in lowered or lowered.startswith("failed ") or "failed tests/" in lowered:
        return "invariant"
    if "systemexit" in lowered or "error:" in lowered and "pip install" in lowered:
        return "environment"
    return "implementation"


def _first_nonempty_line(lines: Iterable[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_first_failure(stdout: str, stderr: str) -> str:
    combined = stdout.splitlines() + stderr.splitlines()
    for line in combined:
        stripped = line.strip()
        if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            return stripped
    for line in combined:
        stripped = line.strip()
        if any(token in stripped for token in ("Traceback (most recent call last):", "ModuleNotFoundError", "ImportError", "FileNotFoundError", "AssertionError", "SystemExit")):
            return stripped
    return _first_nonempty_line(combined)


def _extract_first_traceback(stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    marker = "Traceback (most recent call last):"
    start = combined.find(marker)
    if start == -1:
        return ""
    return combined[start:].rstrip()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _collect_environment_diagnostics(python_executable: Path) -> dict[str, object]:
    return {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "runner_python_executable": str(python_executable),
        "active_virtual_environment": {
            "virtual_env": os.environ.get("VIRTUAL_ENV"),
            "conda_prefix": os.environ.get("CONDA_PREFIX"),
            "is_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        },
        "platform": platform.platform(),
        "installed_versions": {
            "numpy": _package_version("numpy"),
            "scipy": _package_version("scipy"),
            "pandas": _package_version("pandas"),
            "pytest": _package_version("pytest"),
            "requests": _package_version("requests"),
        },
    }


def _is_collection_failure(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return "error collecting" in text or "collected" in text and "errors during collection" in text or "systemexit" in text


def _extract_offending_module(stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ERROR collecting "):
            return line.removeprefix("ERROR collecting ").strip()

    traceback_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("File ")]
    for line in reversed(traceback_lines):
        match = re.search(r'File "([^"]+\.py)"', line)
        if match:
            return Path(match.group(1)).as_posix()
    return "unknown"


def run_certification(
    *,
    repo_root: Path = REPO_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    python_executable: Path = DEFAULT_PYTHON,
) -> int:
    previous_summary = None
    previous_summary_path = output_root / "summary.json"
    if previous_summary_path.exists():
        try:
            previous_summary = json.loads(previous_summary_path.read_text(encoding="utf-8"))
        except Exception:
            previous_summary = None

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    environment = _collect_environment_diagnostics(python_executable)
    _write_text(output_root / "environment.json", json.dumps(environment, indent=2, sort_keys=True) + "\n")

    suite_results: list[dict[str, object]] = []
    collection_failure: dict[str, object] | None = None
    first_failed_suite: dict[str, object] | None = None

    for suite in discover_certification_suites(repo_root):
        suite_dir = output_root / suite.output_dir
        suite_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = suite_dir / f"{suite.name}.stdout.txt"
        stderr_path = suite_dir / f"{suite.name}.stderr.txt"

        command = [str(python_executable), "-m", "pytest", *suite.command]
        started_at = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed_seconds = round(time.perf_counter() - started_at, 6)

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        _write_text(stdout_path, stdout)
        _write_text(stderr_path, stderr)

        passed = result.returncode == 0
        first_failure = "" if passed else _extract_first_failure(stdout, stderr)
        first_traceback = "" if passed else _extract_first_traceback(stdout, stderr)

        suite_summary = {
            "name": suite.name,
            "command": command,
            "exit_code": result.returncode,
            "elapsed_seconds": elapsed_seconds,
            "passed": passed,
            "first_failure": first_failure,
            "first_traceback": first_traceback,
            "output_file": str(stdout_path.relative_to(repo_root)),
            "error_file": str(stderr_path.relative_to(repo_root)),
            "target": suite.target,
        }
        suite_results.append(suite_summary)

        if not passed:
            if first_failed_suite is None:
                first_failed_suite = suite_summary
            if collection_failure is None and _is_collection_failure(stdout, stderr):
                collection_failure = {
                    "offending_module": _extract_offending_module(stdout, stderr),
                    "traceback": first_traceback or stderr or stdout,
                    "classification": _classify_failure(first_traceback or first_failure or stderr or stdout),
                    "recommendation": "Fix the import-time blocker in the offending module, then rerun the certification runner.",
                }

    overall_failed = any(not suite["passed"] for suite in suite_results)

    summary_path = output_root / "summary.json"
    summary_payload = {
        "generated_at": _utc_now().isoformat(),
        "repo_root": str(repo_root),
        "output_root": str(output_root),
        "environment": environment,
        "suites": suite_results,
    }
    _write_text(summary_path, json.dumps(summary_payload, indent=2, sort_keys=True) + "\n")

    if collection_failure is not None:
        collection_failure_lines = [
            "# Collection Failure",
            "",
            f"Offending module: {collection_failure['offending_module']}",
            "",
            "## Traceback",
            "```text",
            collection_failure["traceback"],
            "```",
            "",
            f"Classification: {collection_failure['classification']}",
            "",
            f"Recommendation: {collection_failure['recommendation']}",
        ]
        _write_text(output_root / "collection_failure.md", "\n".join(collection_failure_lines) + "\n")

    passed_suites = [suite["name"] for suite in suite_results if suite["passed"]]
    failed_suites = [suite["name"] for suite in suite_results if not suite["passed"]]
    first_blocker = first_failed_suite or {}
    blocker_text = str(first_blocker.get("first_failure", "") or first_blocker.get("first_traceback", "")) if first_blocker else ""
    failure_classification = _classify_failure(blocker_text) if blocker_text else "none"

    environment_valid = all(value is not None for value in environment["installed_versions"].values())
    artifact_state_valid = collection_failure is None and failure_classification != "missing artifact"
    implementation_valid = collection_failure is None and failure_classification not in {"implementation", "invariant", "import", "environment", "missing artifact"} and overall_failed is False
    release_candidate = overall_failed is False and environment_valid and artifact_state_valid and implementation_valid
    blocking_issue = blocker_text or (collection_failure["offending_module"] if collection_failure else "") or "none"
    confidence = round(
        (
            float(environment_valid)
            + float(collection_failure is None)
            + float(artifact_state_valid)
            + float(implementation_valid)
            + float(release_candidate)
        )
        / 5.0,
        3,
    )

    readiness_payload = {
        "overall_status": "READY" if release_candidate else "BLOCKED",
        "passed_suites": passed_suites,
        "failed_suites": failed_suites,
        "collection_success": collection_failure is None,
        "environment_valid": environment_valid,
        "artifact_state_valid": artifact_state_valid,
        "implementation_valid": implementation_valid,
        "release_candidate": release_candidate,
        "blocking_issue": blocking_issue,
        "confidence": confidence,
    }
    _write_text(output_root / "release_readiness.json", json.dumps(readiness_payload, indent=2, sort_keys=True) + "\n")

    trend_lines: list[str]
    if previous_summary and isinstance(previous_summary, dict):
        previous_suites = previous_summary.get("suites", [])
        previous_passed = sum(1 for suite in previous_suites if suite.get("passed"))
        previous_failed = sum(1 for suite in previous_suites if not suite.get("passed"))
        trend_lines = [
            f"Previous run passed/failed: {previous_passed}/{previous_failed}",
            f"Current run passed/failed: {len(passed_suites)}/{len(failed_suites)}",
            f"Delta failed suites: {len(failed_suites) - previous_failed}",
        ]
    else:
        trend_lines = ["No previous certification run found."]

    table_lines = [
        "| Suite | Target | Status | Exit Code | Elapsed (s) | Output |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for suite in suite_results:
        status = "PASS" if suite["passed"] else "FAIL"
        table_lines.append(
            f"| {suite['name']} | {suite['target']} | {status} | {suite['exit_code']} | {suite['elapsed_seconds']} | {suite['output_file']} |"
        )

    dashboard_lines = [
        "# Release Dashboard",
        "",
        f"Overall status: {readiness_payload['overall_status']}",
        "",
        "## PASS / FAIL Table",
        *table_lines,
        "",
        "## Execution Times",
    ]
    dashboard_lines.extend(
        f"- {suite['target']}: {suite['elapsed_seconds']}s" for suite in suite_results
    )
    dashboard_lines.extend([
        "",
        "## Remaining Blockers",
        *(f"- {blocking_issue}" for _ in ([0] if blocking_issue and blocking_issue != 'none' else [])),
        *( ["- None"] if not blocking_issue or blocking_issue == 'none' else [] ),
        "",
        "## Trend Summary",
        *[f"- {line}" for line in trend_lines],
        "",
        "## Release Recommendation",
        "Ship" if release_candidate else "Do not ship until the first blocker is resolved.",
    ])
    dashboard_text = "\n".join(dashboard_lines) + "\n"
    _write_text(output_root / "release_dashboard.md", dashboard_text)
    _write_text(output_root / "report.md", dashboard_text)

    return 1 if overall_failed else 0


def main() -> int:
    return run_certification()


if __name__ == "__main__":
    raise SystemExit(main())