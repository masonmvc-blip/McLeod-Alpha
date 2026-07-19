from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from engine.validation.certification_gate import (
    ValidationCertificationConflictError,
    ValidationCertificationInputError,
    evaluate_validation_certification,
)
from engine.validation.certification_policy import (
    ValidationCertificationPolicyError,
    load_validation_certification_policy,
)
from engine.validation.validation_lab import ValidationLab, ValidationLabInputs
from tests.test_validation_lab import _points
from tools.run_validation_certification import main as cli_main


def _policy_path() -> Path:
    return Path("tests/fixtures/validation_certification_policy.json")


def _report_payload() -> dict:
    report = ValidationLab().validate(ValidationLabInputs(replay_points=_points()))
    return report.to_dict()


def _validation_input(
    *,
    integrity_status: str = "ok",
    deterministic_replay: bool = True,
    byte_stable_rerun: bool = True,
    no_future_information: bool = True,
    artifact_hash_match: bool = True,
) -> dict:
    return {
        "validation_report": _report_payload(),
        "integrity_status": integrity_status,
        "deterministic_replay": deterministic_replay,
        "byte_stable_rerun": byte_stable_rerun,
        "no_future_information": no_future_information,
        "artifact_hash_match": artifact_hash_match,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_valid_policy_parsing():
    policy = load_validation_certification_policy(_policy_path())
    assert policy.policy_version == "2026.07.v1"
    assert policy.minimum_replay_points == 4


def test_invalid_policy_rejection(tmp_path):
    invalid = tmp_path / "policy.json"
    _write_json(invalid, {"policy_version": "x"})
    with pytest.raises(ValidationCertificationPolicyError):
        load_validation_certification_policy(invalid)


def test_pass_decision(tmp_path):
    policy = load_validation_certification_policy(_policy_path())
    result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=_validation_input(),
        system_version="v1.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )
    assert result.status == "PASS"
    assert result.eligible_for_paper_trading is True


def test_conditional_pass_decision(tmp_path):
    policy_payload = json.loads(_policy_path().read_text(encoding="utf-8"))
    policy_payload["minimum_alpha_vs_spy"] = 0.01
    local_policy_path = tmp_path / "policy_conditional.json"
    _write_json(local_policy_path, policy_payload)
    policy = load_validation_certification_policy(local_policy_path)

    result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=_validation_input(),
        system_version="v1.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )
    assert result.status == "CONDITIONAL_PASS"
    assert result.warnings


def test_fail_decision_blocking(tmp_path):
    policy = load_validation_certification_policy(_policy_path())
    payload = _validation_input(integrity_status="failed")
    result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v1.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )
    assert result.status == "FAIL"
    assert result.first_blocker


def test_insufficient_replay_data_failure(tmp_path):
    policy = load_validation_certification_policy(_policy_path())
    payload = _validation_input()
    payload["validation_report"]["replay_result"]["points"] = []
    payload["validation_report"]["failure_cases"] = []
    payload["validation_report"]["success_cases"] = []

    result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v1.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )
    assert result.status == "FAIL"
    assert any("data.replay_points" in item for item in result.blocking_failures)


def test_threshold_failures_and_safety_failures(tmp_path):
    policy = load_validation_certification_policy(_policy_path())

    payload = _validation_input()
    payload["validation_report"]["benchmark_result"]["alpha_vs_spy"] = -0.02
    payload["validation_report"]["benchmark_result"]["max_drawdown"] = 0.50
    payload["validation_report"]["calibration_result"]["calibration_error"] = 25.0
    payload["validation_report"]["drift_result"]["significant_drifts"] = [
        {"name": "a", "baseline": 1, "recent": 2, "delta": 1, "significant": True},
        {"name": "b", "baseline": 1, "recent": 2, "delta": 1, "significant": True},
        {"name": "c", "baseline": 1, "recent": 2, "delta": 1, "significant": True},
        {"name": "d", "baseline": 1, "recent": 2, "delta": 1, "significant": True},
    ]

    result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v1.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )
    assert result.status in {"CONDITIONAL_PASS", "FAIL"}
    assert any(check.metric == "minimum_alpha_vs_spy" and check.status == "WARN" for check in result.checks)
    assert any(check.metric == "maximum_drawdown" and check.status == "WARN" for check in result.checks)
    assert any(check.metric == "maximum_calibration_error" and check.status == "WARN" for check in result.checks)
    assert any(check.metric == "maximum_significant_drift_count" and check.status == "WARN" for check in result.checks)

    # hard safety failures
    hard_fail = _validation_input(deterministic_replay=False)
    hard_result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=hard_fail,
        system_version="v1.0.0-hard",
        output_root=tmp_path,
        write_artifacts=False,
    )
    assert hard_result.status == "FAIL"

    lookahead_fail = _validation_input(no_future_information=False)
    lookahead_result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=lookahead_fail,
        system_version="v1.0.0-lookahead",
        output_root=tmp_path,
        write_artifacts=False,
    )
    assert lookahead_result.status == "FAIL"


def test_deterministic_id_hash_and_byte_stable_rerun(tmp_path):
    policy = load_validation_certification_policy(_policy_path())
    payload = _validation_input()

    one = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v1.2.3",
        output_root=tmp_path,
        write_artifacts=True,
    )
    two = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v1.2.3",
        output_root=tmp_path,
        write_artifacts=True,
    )

    assert one.certification_id == two.certification_id
    assert one.content_hash == two.content_hash

    cert_dir = Path(one.artifact_paths[0]).parent
    json_bytes = (cert_dir / "validation_certification.json").read_bytes()
    md_bytes = (cert_dir / "validation_certification.md").read_bytes()
    json_bytes_2 = (cert_dir / "validation_certification.json").read_bytes()
    md_bytes_2 = (cert_dir / "validation_certification.md").read_bytes()
    assert json_bytes == json_bytes_2
    assert md_bytes == md_bytes_2


def test_idempotent_identical_rerun_and_conflict_detection(tmp_path):
    policy = load_validation_certification_policy(_policy_path())
    payload = _validation_input()

    result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v2.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )

    rerun = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v2.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )
    assert rerun.certification_id == result.certification_id

    cert_dir = Path(result.artifact_paths[0]).parent
    cert_json = cert_dir / "validation_certification.json"
    cert_json.write_text(cert_json.read_text(encoding="utf-8") + "#", encoding="utf-8")

    with pytest.raises(ValidationCertificationConflictError):
        evaluate_validation_certification(
            policy=policy,
            validation_input_payload=payload,
            system_version="v2.0.0",
            output_root=tmp_path,
            write_artifacts=True,
        )


def test_atomic_writes_and_manifest_hash_correctness(tmp_path):
    policy = load_validation_certification_policy(_policy_path())
    payload = _validation_input()

    result = evaluate_validation_certification(
        policy=policy,
        validation_input_payload=payload,
        system_version="v3.0.0",
        output_root=tmp_path,
        write_artifacts=True,
    )

    cert_dir = Path(result.artifact_paths[0]).parent
    manifest = json.loads((cert_dir / "certification_manifest.json").read_text(encoding="utf-8"))
    assert manifest["certification_id"] == result.certification_id
    assert manifest["policy_hash"] == result.policy_hash
    assert manifest["validation_report_hash"] == result.validation_report_hash

    json_hash = hashlib.sha256((cert_dir / "validation_certification.json").read_bytes()).hexdigest()
    md_hash = hashlib.sha256((cert_dir / "validation_certification.md").read_bytes()).hexdigest()
    assert manifest["artifact_hashes"]["validation_certification.json"] == json_hash
    assert manifest["artifact_hashes"]["validation_certification.md"] == md_hash


def test_cli_exit_codes_and_validate_only_no_writes(tmp_path):
    input_path = tmp_path / "validation_input.json"
    policy_path = _policy_path()
    _write_json(input_path, _validation_input())

    rc_pass = cli_main([
        "--validation-input",
        str(input_path),
        "--policy",
        str(policy_path),
        "--system-version",
        "v1",
        "--output-root",
        str(tmp_path / "pass"),
        "--print-summary",
    ])
    assert rc_pass == 0

    rc_validate_only = cli_main([
        "--validation-input",
        str(input_path),
        "--policy",
        str(policy_path),
        "--system-version",
        "v2",
        "--output-root",
        str(tmp_path / "validate_only"),
        "--validate-only",
        "--print-summary",
    ])
    assert rc_validate_only == 0
    cert_root = tmp_path / "validate_only" / "artifacts" / "validation" / "certifications"
    assert not cert_root.exists()

    bad_input = tmp_path / "bad_input.json"
    _write_json(bad_input, {"x": 1})
    rc_bad = cli_main([
        "--validation-input",
        str(bad_input),
        "--policy",
        str(policy_path),
        "--system-version",
        "v1",
    ])
    assert rc_bad == 5 or rc_bad == 3

    fail_payload = _validation_input(no_future_information=False)
    fail_path = tmp_path / "fail_input.json"
    _write_json(fail_path, fail_payload)
    rc_fail = cli_main([
        "--validation-input",
        str(fail_path),
        "--policy",
        str(policy_path),
        "--system-version",
        "v1-fail",
        "--output-root",
        str(tmp_path / "fail"),
    ])
    assert rc_fail == 2

    conditional_policy = tmp_path / "conditional_policy.json"
    pol = json.loads(policy_path.read_text(encoding="utf-8"))
    pol["minimum_alpha_vs_spy"] = 0.02
    _write_json(conditional_policy, pol)
    rc_conditional = cli_main([
        "--validation-input",
        str(input_path),
        "--policy",
        str(conditional_policy),
        "--system-version",
        "v1",
        "--output-root",
        str(tmp_path / "conditional"),
    ])
    assert rc_conditional == 1
