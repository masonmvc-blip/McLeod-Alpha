from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .certification_policy import ValidationCertificationPolicy
from .certification_report import render_validation_certification_markdown


SCHEMA_VERSION = "1.0.0"


class ValidationCertificationError(RuntimeError):
    pass


class ValidationCertificationConflictError(ValidationCertificationError):
    pass


class ValidationCertificationInputError(ValidationCertificationError):
    pass


@dataclass(frozen=True)
class CertificationCheck:
    check_id: str
    category: str
    metric: str
    observed_value: str
    required_value: str
    operator: str
    status: str
    severity: str
    blocking: bool
    reason: str
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ValidationCertificationResult:
    certification_id: str
    system_version: str
    as_of_date: str
    policy_version: str
    status: str
    eligible_for_paper_trading: bool
    checks: tuple[CertificationCheck, ...]
    blocking_failures: tuple[str, ...]
    warnings: tuple[str, ...]
    first_blocker: str
    validation_report_hash: str
    policy_hash: str
    content_hash: str
    artifact_paths: tuple[str, ...]
    executive_summary: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [asdict(check) for check in self.checks]
        payload["artifact_paths"] = list(self.artifact_paths)
        return payload


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _format_float(value: float) -> str:
    return f"{float(value):.6f}"


def _make_check(
    *,
    check_id: str,
    category: str,
    metric: str,
    observed_value: Any,
    required_value: Any,
    operator: str,
    status: str,
    severity: str,
    blocking: bool,
    reason: str,
    evidence: tuple[str, ...] = (),
) -> CertificationCheck:
    return CertificationCheck(
        check_id=check_id,
        category=category,
        metric=metric,
        observed_value=str(observed_value),
        required_value=str(required_value),
        operator=operator,
        status=status,
        severity=severity,
        blocking=blocking,
        reason=reason,
        evidence=evidence,
    )


def _extract_validation_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "validation_report",
        "integrity_status",
        "deterministic_replay",
        "byte_stable_rerun",
        "no_future_information",
        "artifact_hash_match",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValidationCertificationInputError(f"Validation input missing keys: {', '.join(missing)}")

    report = payload["validation_report"]
    if not isinstance(report, dict):
        raise ValidationCertificationInputError("validation_report must be an object")

    replay_points = report.get("replay_result", {}).get("points", [])
    benchmark = report.get("benchmark_result", {})
    calibration = report.get("calibration_result", {})
    drift = report.get("drift_result", {})
    success_cases = report.get("success_cases", []) or []
    failure_cases = report.get("failure_cases", []) or []

    if not isinstance(replay_points, (list, tuple)):
        raise ValidationCertificationInputError("validation_report.replay_result.points must be a sequence")
    if not isinstance(success_cases, (list, tuple)):
        raise ValidationCertificationInputError("validation_report.success_cases must be a sequence")
    if not isinstance(failure_cases, (list, tuple)):
        raise ValidationCertificationInputError("validation_report.failure_cases must be a sequence")

    replay_points = list(replay_points)
    success_cases = list(success_cases)
    failure_cases = list(failure_cases)

    date_values: list[date] = []
    for point in replay_points:
        if not isinstance(point, dict):
            continue
        text = str(point.get("as_of_date", "")).strip()
        if not text:
            continue
        try:
            date_values.append(date.fromisoformat(text))
        except ValueError:
            continue
    replay_period_days = 0
    if date_values:
        replay_period_days = ((max(date_values) - min(date_values)).days + 1)

    replay_count = len(replay_points)
    failure_rate = (len(failure_cases) / replay_count) if replay_count else 1.0
    drift_count = len(drift.get("significant_drifts", []) or [])

    return {
        "as_of_date": str(report.get("generated_at", "")).split("T", 1)[0],
        "report_payload": report,
        "validation_report_hash": sha256(_stable_json(report).encode("utf-8")).hexdigest(),
        "replay_points": replay_count,
        "replay_period_days": replay_period_days,
        "alpha_vs_spy": float(benchmark.get("alpha_vs_spy", 0.0)),
        "alpha_vs_equal_weight": float(benchmark.get("alpha_vs_equal_weight", 0.0)),
        "alpha_vs_benchmark_portfolio": float(benchmark.get("alpha_vs_benchmark_portfolio", 0.0)),
        "hit_rate": float(benchmark.get("hit_rate", 0.0)),
        "sharpe": float(benchmark.get("sharpe", 0.0)),
        "sortino": float(benchmark.get("sortino", 0.0)),
        "max_drawdown": float(benchmark.get("max_drawdown", 0.0)),
        "turnover": float(benchmark.get("turnover", 0.0)),
        "calibration_error": float(calibration.get("calibration_error", 0.0)),
        "confidence_accuracy": float(calibration.get("confidence_accuracy", 0.0)),
        "replacement_accuracy": float(calibration.get("replacement_accuracy", 0.0)),
        "portfolio_allocation_quality": float(calibration.get("portfolio_allocation_quality", 0.0)),
        "significant_drift_count": drift_count,
        "success_case_count": len(success_cases),
        "failure_case_rate": float(failure_rate),
        "integrity_status": str(payload["integrity_status"]),
        "deterministic_replay": bool(payload["deterministic_replay"]),
        "byte_stable_rerun": bool(payload["byte_stable_rerun"]),
        "no_future_information": bool(payload["no_future_information"]),
        "artifact_hash_match": bool(payload["artifact_hash_match"]),
    }


def _metric_check(
    *,
    check_id: str,
    category: str,
    metric: str,
    observed: float,
    required: float,
    op: str,
    blocking: bool,
    severity: str,
    warn_on_fail: bool,
    evidence: tuple[str, ...] = (),
) -> CertificationCheck:
    if op == ">=":
        passed = observed >= required
    elif op == "<=":
        passed = observed <= required
    else:
        raise ValidationCertificationInputError(f"Unsupported operator: {op}")

    if passed:
        status = "PASS"
        reason = f"Observed {_format_float(observed)} satisfies {op} {_format_float(required)}"
    else:
        status = "FAIL" if (blocking and not warn_on_fail) else "WARN"
        reason = f"Observed {_format_float(observed)} does not satisfy {op} {_format_float(required)}"

    return _make_check(
        check_id=check_id,
        category=category,
        metric=metric,
        observed_value=_format_float(observed),
        required_value=_format_float(required),
        operator=op,
        status=status,
        severity=severity,
        blocking=blocking,
        reason=reason,
        evidence=evidence,
    )


def _boolean_check(
    *,
    check_id: str,
    category: str,
    metric: str,
    observed: bool,
    required: bool,
    blocking: bool,
    severity: str,
) -> CertificationCheck:
    passed = observed == required
    status = "PASS" if passed else "FAIL"
    return _make_check(
        check_id=check_id,
        category=category,
        metric=metric,
        observed_value=str(observed).lower(),
        required_value=str(required).lower(),
        operator="==",
        status=status,
        severity=severity,
        blocking=blocking,
        reason=("Boolean requirement satisfied" if passed else "Boolean requirement failed"),
    )


def evaluate_validation_certification(
    *,
    policy: ValidationCertificationPolicy,
    validation_input_payload: dict[str, Any],
    system_version: str,
    output_root: Path,
    write_artifacts: bool,
) -> ValidationCertificationResult:
    snapshot = _extract_validation_snapshot(validation_input_payload)
    policy_hash = policy.policy_hash

    checks: list[CertificationCheck] = []

    # Data sufficiency blocking checks.
    replay_points = int(snapshot["replay_points"])
    if replay_points == 0:
        checks.append(
            _make_check(
                check_id="data.replay_points",
                category="data_sufficiency",
                metric="minimum_replay_points",
                observed_value="0",
                required_value=str(policy.minimum_replay_points),
                operator=">=",
                status="NOT_ENOUGH_DATA",
                severity="critical",
                blocking=True,
                reason="No replay points available.",
            )
        )
    else:
        checks.append(
            _metric_check(
                check_id="data.replay_points",
                category="data_sufficiency",
                metric="minimum_replay_points",
                observed=float(snapshot["replay_points"]),
                required=float(policy.minimum_replay_points),
                op=">=",
                blocking=True,
                severity="critical",
                warn_on_fail=False,
            )
        )

    checks.append(
        _metric_check(
            check_id="data.replay_period_days",
            category="data_sufficiency",
            metric="minimum_replay_period_days",
            observed=float(snapshot["replay_period_days"]),
            required=float(policy.minimum_replay_period_days),
            op=">=",
            blocking=True,
            severity="critical",
            warn_on_fail=False,
        )
    )

    # Benchmark and risk as non-blocking warnings.
    checks.extend(
        [
            _metric_check(
                check_id="benchmark.alpha_vs_spy",
                category="benchmark_performance",
                metric="minimum_alpha_vs_spy",
                observed=float(snapshot["alpha_vs_spy"]),
                required=policy.minimum_alpha_vs_spy,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="benchmark.alpha_vs_equal_weight",
                category="benchmark_performance",
                metric="minimum_alpha_vs_equal_weight",
                observed=float(snapshot["alpha_vs_equal_weight"]),
                required=policy.minimum_alpha_vs_equal_weight,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="benchmark.alpha_vs_benchmark",
                category="benchmark_performance",
                metric="minimum_alpha_vs_benchmark_portfolio",
                observed=float(snapshot["alpha_vs_benchmark_portfolio"]),
                required=policy.minimum_alpha_vs_benchmark_portfolio,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="benchmark.hit_rate",
                category="benchmark_performance",
                metric="minimum_hit_rate",
                observed=float(snapshot["hit_rate"]),
                required=policy.minimum_hit_rate,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="risk.sharpe",
                category="risk",
                metric="minimum_sharpe",
                observed=float(snapshot["sharpe"]),
                required=policy.minimum_sharpe,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="risk.sortino",
                category="risk",
                metric="minimum_sortino",
                observed=float(snapshot["sortino"]),
                required=policy.minimum_sortino,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="risk.drawdown",
                category="risk",
                metric="maximum_drawdown",
                observed=float(snapshot["max_drawdown"]),
                required=policy.maximum_drawdown,
                op="<=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="risk.turnover",
                category="risk",
                metric="maximum_turnover",
                observed=float(snapshot["turnover"]),
                required=policy.maximum_turnover,
                op="<=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
        ]
    )

    checks.extend(
        [
            _metric_check(
                check_id="calibration.error",
                category="calibration",
                metric="maximum_calibration_error",
                observed=float(snapshot["calibration_error"]),
                required=policy.maximum_calibration_error,
                op="<=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="calibration.confidence_accuracy",
                category="calibration",
                metric="minimum_confidence_accuracy",
                observed=float(snapshot["confidence_accuracy"]),
                required=policy.minimum_confidence_accuracy,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="calibration.replacement_accuracy",
                category="calibration",
                metric="minimum_replacement_accuracy",
                observed=float(snapshot["replacement_accuracy"]),
                required=policy.minimum_replacement_accuracy,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
            _metric_check(
                check_id="calibration.portfolio_allocation_quality",
                category="calibration",
                metric="minimum_portfolio_allocation_quality",
                observed=float(snapshot["portfolio_allocation_quality"]),
                required=policy.minimum_portfolio_allocation_quality,
                op=">=",
                blocking=False,
                severity="medium",
                warn_on_fail=True,
            ),
        ]
    )

    checks.append(
        _metric_check(
            check_id="drift.significant_count",
            category="drift",
            metric="maximum_significant_drift_count",
            observed=float(snapshot["significant_drift_count"]),
            required=float(policy.maximum_significant_drift_count),
            op="<=",
            blocking=False,
            severity="medium",
            warn_on_fail=True,
        )
    )

    # hard safety checks
    checks.append(
        _make_check(
            check_id="integrity.status",
            category="integrity",
            metric="required_integrity_status",
            observed_value=str(snapshot["integrity_status"]),
            required_value=str(policy.required_integrity_status),
            operator="==",
            status="PASS" if str(snapshot["integrity_status"]) == policy.required_integrity_status else "FAIL",
            severity="critical",
            blocking=True,
            reason="Integrity status check",
        )
    )
    checks.append(
        _boolean_check(
            check_id="integrity.artifact_hash_match",
            category="integrity",
            metric="artifact_hash_match",
            observed=bool(snapshot["artifact_hash_match"]),
            required=True,
            blocking=True,
            severity="critical",
        )
    )
    checks.append(
        _boolean_check(
            check_id="determinism.replay",
            category="determinism",
            metric="required_deterministic_replay",
            observed=bool(snapshot["deterministic_replay"]),
            required=policy.required_deterministic_replay,
            blocking=True,
            severity="critical",
        )
    )
    checks.append(
        _boolean_check(
            check_id="determinism.byte_stable",
            category="determinism",
            metric="required_byte_stable_rerun",
            observed=bool(snapshot["byte_stable_rerun"]),
            required=policy.required_byte_stable_rerun,
            blocking=True,
            severity="critical",
        )
    )
    checks.append(
        _boolean_check(
            check_id="lookahead.safety",
            category="lookahead_safety",
            metric="required_no_future_information",
            observed=bool(snapshot["no_future_information"]),
            required=policy.required_no_future_information,
            blocking=True,
            severity="critical",
        )
    )

    checks.extend(
        [
            _metric_check(
                check_id="data.success_case_count",
                category="data_sufficiency",
                metric="minimum_success_case_count",
                observed=float(snapshot["success_case_count"]),
                required=float(policy.minimum_success_case_count),
                op=">=",
                blocking=True,
                severity="critical",
                warn_on_fail=False,
            ),
            _metric_check(
                check_id="data.failure_case_rate",
                category="data_sufficiency",
                metric="maximum_failure_case_rate",
                observed=float(snapshot["failure_case_rate"]),
                required=float(policy.maximum_failure_case_rate),
                op="<=",
                blocking=True,
                severity="critical",
                warn_on_fail=False,
            ),
        ]
    )

    blocking_failures = tuple(
        f"{check.check_id}: {check.reason}"
        for check in checks
        if check.blocking and check.status in {"FAIL", "NOT_ENOUGH_DATA"}
    )
    warnings = tuple(f"{check.check_id}: {check.reason}" for check in checks if check.status == "WARN")

    if blocking_failures:
        status = "FAIL"
    elif warnings and policy.allow_conditional_pass:
        status = "CONDITIONAL_PASS"
    elif warnings and not policy.allow_conditional_pass:
        status = "FAIL"
        blocking_failures = blocking_failures + ("policy.conditional_pass: warnings present but policy disallows conditional pass",)
    else:
        status = "PASS"

    eligible_for_paper_trading = status in {"PASS", "CONDITIONAL_PASS"}
    first_blocker = blocking_failures[0] if blocking_failures else ""

    certification_seed = {
        "system_version": str(system_version),
        "validation_report_hash": snapshot["validation_report_hash"],
        "policy_hash": policy_hash,
    }
    certification_id = "VCERT-" + sha256(_stable_json(certification_seed).encode("utf-8")).hexdigest()[:20].upper()

    result_payload_for_hash = {
        "certification_id": certification_id,
        "system_version": str(system_version),
        "as_of_date": snapshot["as_of_date"],
        "policy_version": policy.policy_version,
        "status": status,
        "eligible_for_paper_trading": eligible_for_paper_trading,
        "checks": [asdict(check) for check in checks],
        "blocking_failures": list(blocking_failures),
        "warnings": list(warnings),
        "first_blocker": first_blocker,
        "validation_report_hash": snapshot["validation_report_hash"],
        "policy_hash": policy_hash,
    }
    content_hash = sha256(_stable_json(result_payload_for_hash).encode("utf-8")).hexdigest()

    executive_summary = (
        f"Validation certification {status} for system version {system_version}. "
        f"Blocking failures: {len(blocking_failures)}. Warnings: {len(warnings)}."
    )

    result = ValidationCertificationResult(
        certification_id=certification_id,
        system_version=str(system_version),
        as_of_date=snapshot["as_of_date"],
        policy_version=policy.policy_version,
        status=status,
        eligible_for_paper_trading=eligible_for_paper_trading,
        checks=tuple(checks),
        blocking_failures=blocking_failures,
        warnings=warnings,
        first_blocker=first_blocker,
        validation_report_hash=snapshot["validation_report_hash"],
        policy_hash=policy_hash,
        content_hash=content_hash,
        artifact_paths=(),
        executive_summary=executive_summary,
    )

    if not write_artifacts:
        return result

    certification_dir = Path(output_root) / "artifacts" / "validation" / "certifications" / certification_id
    certification_json_path = certification_dir / "validation_certification.json"
    certification_md_path = certification_dir / "validation_certification.md"
    manifest_path = certification_dir / "certification_manifest.json"

    rendered_markdown = render_validation_certification_markdown(result)

    result_with_paths = ValidationCertificationResult(
        certification_id=result.certification_id,
        system_version=result.system_version,
        as_of_date=result.as_of_date,
        policy_version=result.policy_version,
        status=result.status,
        eligible_for_paper_trading=result.eligible_for_paper_trading,
        checks=result.checks,
        blocking_failures=result.blocking_failures,
        warnings=result.warnings,
        first_blocker=result.first_blocker,
        validation_report_hash=result.validation_report_hash,
        policy_hash=result.policy_hash,
        content_hash=result.content_hash,
        artifact_paths=(str(certification_json_path), str(certification_md_path), str(manifest_path)),
        executive_summary=result.executive_summary,
    )

    certification_json_bytes = (json.dumps(result_with_paths.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    certification_md_bytes = rendered_markdown.encode("utf-8")

    artifact_hashes = {
        "validation_certification.json": _sha(certification_json_bytes),
        "validation_certification.md": _sha(certification_md_bytes),
    }
    manifest_payload = {
        "certification_id": certification_id,
        "system_version": str(system_version),
        "policy_version": policy.policy_version,
        "validation_report_hash": snapshot["validation_report_hash"],
        "policy_hash": policy_hash,
        "artifact_hashes": dict(sorted(artifact_hashes.items(), key=lambda item: item[0])),
        "status": status,
        "schema_version": SCHEMA_VERSION,
    }
    manifest_bytes = (json.dumps(manifest_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

    expected = {
        "validation_certification.json": certification_json_bytes,
        "validation_certification.md": certification_md_bytes,
        "certification_manifest.json": manifest_bytes,
    }

    if certification_dir.exists():
        for name, content in sorted(expected.items(), key=lambda item: item[0]):
            path = certification_dir / name
            if not path.exists():
                raise ValidationCertificationConflictError(f"Existing certification missing artifact: {name}")
            if path.read_bytes() != content:
                raise ValidationCertificationConflictError(f"Conflicting artifact content: {name}")
    else:
        certification_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(certification_json_path, certification_json_bytes)
        _atomic_write(certification_md_path, certification_md_bytes)
        _atomic_write(manifest_path, manifest_bytes)

    return result_with_paths
