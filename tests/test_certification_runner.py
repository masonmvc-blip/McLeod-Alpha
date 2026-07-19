from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import tools.run_certification as run_certification


def _fake_response(returncode: int, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _normalize_summary_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    normalized["repo_root"] = "<repo_root>"
    normalized["output_root"] = "<output_root>"
    normalized["environment"] = dict(payload["environment"])
    normalized["environment"]["runner_python_executable"] = "<python_executable>"
    normalized["suites"] = [dict(suite, elapsed_seconds=0.0) for suite in payload["suites"]]
    return normalized


def _normalize_dashboard_text(text: str) -> str:
    text = re.sub(r"\b\d+\.\d+s\b", "<elapsed>s", text)
    return re.sub(r"\b\d+\.\d+\b", "<elapsed>", text)


def test_suite_discovery_matches_expected_patterns(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "tests").mkdir(parents=True)
    (repo_root / "archive").mkdir()
    (repo_root / "tests" / "test_alpha_invariants.py").write_text("", encoding="utf-8")
    (repo_root / "tests" / "test_beta_certification.py").write_text("", encoding="utf-8")
    (repo_root / "tests" / "test_system_validation_core.py").write_text("", encoding="utf-8")
    (repo_root / "tests" / "test_research_lab_release_certification.py").write_text("", encoding="utf-8")
    (repo_root / "tests" / "test_phase2_framework_rules.py").write_text("", encoding="utf-8")
    (repo_root / "tests" / "test_not_included.py").write_text("", encoding="utf-8")
    (repo_root / "archive" / "test_archived_invariants.py").write_text("", encoding="utf-8")

    suites = run_certification.discover_certification_suites(repo_root)
    names = [suite.name for suite in suites]
    targets = [suite.target for suite in suites]

    assert names[0] == "collect_only"
    assert names[-1] == "canonical_matrix"
    assert targets[0] == "repo"
    assert targets[-1] == "repo"
    assert "tests/test_not_included.py" not in targets
    assert "archive/test_archived_invariants.py" not in targets

    discovered_targets = targets[1:-1]
    assert discovered_targets == sorted(discovered_targets)
    assert discovered_targets == [
        "tests/test_alpha_invariants.py",
        "tests/test_beta_certification.py",
        "tests/test_phase2_framework_rules.py",
        "tests/test_research_lab_release_certification.py",
        "tests/test_system_validation_core.py",
    ]


def test_environment_capture_writes_expected_keys(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/fake-venv")
    monkeypatch.setenv("CONDA_PREFIX", "/tmp/fake-conda")
    monkeypatch.setattr(run_certification, "_package_version", lambda name: f"{name}-version")

    env = run_certification._collect_environment_diagnostics(Path("/tmp/python"))

    assert env["runner_python_executable"] == "/tmp/python"
    assert env["installed_versions"] == {
        "numpy": "numpy-version",
        "scipy": "scipy-version",
        "pandas": "pandas-version",
        "pytest": "pytest-version",
        "requests": "requests-version",
    }
    assert env["active_virtual_environment"]["virtual_env"] == "/tmp/fake-venv"
    assert env["active_virtual_environment"]["conda_prefix"] == "/tmp/fake-conda"
    assert env["python_version"].count(".") >= 1


def test_collection_failure_generates_markdown(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = repo_root / "artifacts" / "certification_run"
    python_executable = tmp_path / "venv" / "bin" / "python"

    suites = [
        run_certification.CertificationSuite("collect_only", ("--collect-only", "-q"), "collect_only", "repo"),
        run_certification.CertificationSuite("canonical_matrix", ("-q",), "canonical_matrix", "repo"),
    ]
    responses = [
        _fake_response(
            2,
            stdout="",
            stderr=(
                "ERROR collecting tests/test_example.py\n"
                "Traceback (most recent call last):\n"
                '  File "/Users/mason/Documents/GitHub/McLeod-Alpha-New/engine/data_sources/sec_source.py", line 20, in <module>\n'
                "ModuleNotFoundError: No module named 'requests'\n"
            ),
        ),
        _fake_response(0, stdout="canonical matrix ok\n", stderr=""),
    ]
    perf = iter([1.0, 2.0, 3.0, 4.0])

    monkeypatch.setattr(run_certification, "discover_certification_suites", lambda repo_root=repo_root: suites)
    monkeypatch.setattr(run_certification.subprocess, "run", lambda command, **kwargs: responses.pop(0))
    monkeypatch.setattr(run_certification.time, "perf_counter", lambda: next(perf))
    monkeypatch.setattr(run_certification, "_utc_now", lambda: datetime(2026, 7, 19, tzinfo=timezone.utc))
    monkeypatch.setattr(run_certification, "_package_version", lambda name: "1.0.0")

    exit_code = run_certification.run_certification(
        repo_root=repo_root,
        output_root=output_root,
        python_executable=python_executable,
    )

    assert exit_code == 1
    collection_failure = (output_root / "collection_failure.md").read_text(encoding="utf-8")
    assert "Offending module: tests/test_example.py" in collection_failure
    assert "Classification: import" in collection_failure
    readiness = json.loads((output_root / "release_readiness.json").read_text(encoding="utf-8"))
    assert readiness["collection_success"] is False
    assert readiness["release_candidate"] is False
    assert readiness["blocking_issue"]


def test_release_readiness_and_deterministic_outputs(tmp_path, monkeypatch):
    repo_one = tmp_path / "repo_one"
    repo_two = tmp_path / "repo_two"
    repo_one.mkdir()
    repo_two.mkdir()
    output_one = repo_one / "artifacts" / "certification_run"
    output_two = repo_two / "artifacts" / "certification_run"
    python_executable = Path("/tmp/python")

    suites = [
        run_certification.CertificationSuite("collect_only", ("--collect-only", "-q"), "collect_only", "repo"),
        run_certification.CertificationSuite("tests__test_system_validation_invariants", ("-q", "tests/test_system_validation_invariants.py"), "discovered/tests__test_system_validation_invariants", "tests/test_system_validation_invariants.py"),
        run_certification.CertificationSuite("canonical_matrix", ("-q",), "canonical_matrix", "repo"),
    ]
    responses = [
        _fake_response(0, stdout="collect ok\n", stderr=""),
        _fake_response(0, stdout="system validation ok\n", stderr=""),
        _fake_response(0, stdout="canonical matrix ok\n", stderr=""),
        _fake_response(0, stdout="collect ok\n", stderr=""),
        _fake_response(0, stdout="system validation ok\n", stderr=""),
        _fake_response(0, stdout="canonical matrix ok\n", stderr=""),
    ]
    perf = iter([1.0, 1.25, 2.0, 2.5, 3.0, 3.75, 4.0, 4.25, 5.0, 5.5, 6.0, 6.25])

    monkeypatch.setattr(run_certification, "discover_certification_suites", lambda repo_root=None: suites)
    monkeypatch.setattr(run_certification.subprocess, "run", lambda command, **kwargs: responses.pop(0))
    monkeypatch.setattr(run_certification.time, "perf_counter", lambda: next(perf))
    monkeypatch.setattr(run_certification, "_utc_now", lambda: datetime(2026, 7, 19, tzinfo=timezone.utc))
    monkeypatch.setattr(run_certification, "_package_version", lambda name: f"{name}-1.0.0")

    first_exit = run_certification.run_certification(
        repo_root=repo_one,
        output_root=output_one,
        python_executable=python_executable,
    )
    second_exit = run_certification.run_certification(
        repo_root=repo_two,
        output_root=output_two,
        python_executable=python_executable,
    )

    assert first_exit == 0
    assert second_exit == 0

    first_summary = (output_one / "summary.json").read_text(encoding="utf-8")
    second_summary = (output_two / "summary.json").read_text(encoding="utf-8")
    first_readiness = (output_one / "release_readiness.json").read_text(encoding="utf-8")
    second_readiness = (output_two / "release_readiness.json").read_text(encoding="utf-8")
    first_dashboard = (output_one / "release_dashboard.md").read_text(encoding="utf-8")
    second_dashboard = (output_two / "release_dashboard.md").read_text(encoding="utf-8")
    first_environment = (output_one / "environment.json").read_text(encoding="utf-8")
    second_environment = (output_two / "environment.json").read_text(encoding="utf-8")

    assert _normalize_summary_payload(json.loads(first_summary)) == _normalize_summary_payload(json.loads(second_summary))
    assert first_readiness == second_readiness
    assert _normalize_dashboard_text(first_dashboard) == _normalize_dashboard_text(second_dashboard)
    assert first_environment == second_environment

    summary_payload = json.loads(first_summary)
    assert summary_payload["environment"]["installed_versions"]["pytest"] == "pytest-1.0.0"
    assert summary_payload["suites"][0]["output_file"] == "artifacts/certification_run/collect_only/collect_only.stdout.txt"
    assert summary_payload["suites"][-1]["output_file"] == "artifacts/certification_run/canonical_matrix/canonical_matrix.stdout.txt"

    readiness_payload = json.loads(first_readiness)
    assert readiness_payload["overall_status"] == "READY"
    assert readiness_payload["release_candidate"] is True
    assert readiness_payload["confidence"] == 1.0
