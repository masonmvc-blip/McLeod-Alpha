from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class ValidationCertificationPolicyError(ValueError):
    pass


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _require(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise ValidationCertificationPolicyError(f"Missing policy key: {key}")
    return payload[key]


@dataclass(frozen=True)
class ValidationCertificationPolicy:
    policy_version: str
    minimum_replay_points: int
    minimum_replay_period_days: int
    minimum_alpha_vs_spy: float
    minimum_alpha_vs_equal_weight: float
    minimum_alpha_vs_benchmark_portfolio: float
    minimum_hit_rate: float
    minimum_sharpe: float
    minimum_sortino: float
    maximum_drawdown: float
    maximum_turnover: float
    maximum_calibration_error: float
    minimum_confidence_accuracy: float
    minimum_replacement_accuracy: float
    minimum_portfolio_allocation_quality: float
    maximum_significant_drift_count: int
    required_integrity_status: str
    required_deterministic_replay: bool
    required_byte_stable_rerun: bool
    required_no_future_information: bool
    minimum_success_case_count: int
    maximum_failure_case_rate: float
    allow_conditional_pass: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def policy_hash(self) -> str:
        return sha256(_stable_json(self.to_dict()).encode("utf-8")).hexdigest()


def load_validation_certification_policy(path: Path) -> ValidationCertificationPolicy:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationCertificationPolicyError(f"Policy file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationCertificationPolicyError(f"Policy JSON is invalid: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValidationCertificationPolicyError("Policy JSON must be an object.")

    required_keys = {
        "policy_version",
        "minimum_replay_points",
        "minimum_replay_period_days",
        "minimum_alpha_vs_spy",
        "minimum_alpha_vs_equal_weight",
        "minimum_alpha_vs_benchmark_portfolio",
        "minimum_hit_rate",
        "minimum_sharpe",
        "minimum_sortino",
        "maximum_drawdown",
        "maximum_turnover",
        "maximum_calibration_error",
        "minimum_confidence_accuracy",
        "minimum_replacement_accuracy",
        "minimum_portfolio_allocation_quality",
        "maximum_significant_drift_count",
        "required_integrity_status",
        "required_deterministic_replay",
        "required_byte_stable_rerun",
        "required_no_future_information",
        "minimum_success_case_count",
        "maximum_failure_case_rate",
        "allow_conditional_pass",
    }
    unknown = set(payload) - required_keys
    if unknown:
        raise ValidationCertificationPolicyError(f"Unknown policy keys: {', '.join(sorted(unknown))}")

    def _as_int(name: str) -> int:
        value = _require(payload, name)
        if isinstance(value, bool):
            raise ValidationCertificationPolicyError(f"{name} must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationCertificationPolicyError(f"{name} must be an integer") from exc

    def _as_float(name: str) -> float:
        value = _require(payload, name)
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationCertificationPolicyError(f"{name} must be numeric") from exc

    def _as_bool(name: str) -> bool:
        value = _require(payload, name)
        if not isinstance(value, bool):
            raise ValidationCertificationPolicyError(f"{name} must be boolean")
        return value

    def _as_str(name: str) -> str:
        value = str(_require(payload, name)).strip()
        if not value:
            raise ValidationCertificationPolicyError(f"{name} must be non-empty")
        return value

    policy = ValidationCertificationPolicy(
        policy_version=_as_str("policy_version"),
        minimum_replay_points=_as_int("minimum_replay_points"),
        minimum_replay_period_days=_as_int("minimum_replay_period_days"),
        minimum_alpha_vs_spy=_as_float("minimum_alpha_vs_spy"),
        minimum_alpha_vs_equal_weight=_as_float("minimum_alpha_vs_equal_weight"),
        minimum_alpha_vs_benchmark_portfolio=_as_float("minimum_alpha_vs_benchmark_portfolio"),
        minimum_hit_rate=_as_float("minimum_hit_rate"),
        minimum_sharpe=_as_float("minimum_sharpe"),
        minimum_sortino=_as_float("minimum_sortino"),
        maximum_drawdown=_as_float("maximum_drawdown"),
        maximum_turnover=_as_float("maximum_turnover"),
        maximum_calibration_error=_as_float("maximum_calibration_error"),
        minimum_confidence_accuracy=_as_float("minimum_confidence_accuracy"),
        minimum_replacement_accuracy=_as_float("minimum_replacement_accuracy"),
        minimum_portfolio_allocation_quality=_as_float("minimum_portfolio_allocation_quality"),
        maximum_significant_drift_count=_as_int("maximum_significant_drift_count"),
        required_integrity_status=_as_str("required_integrity_status"),
        required_deterministic_replay=_as_bool("required_deterministic_replay"),
        required_byte_stable_rerun=_as_bool("required_byte_stable_rerun"),
        required_no_future_information=_as_bool("required_no_future_information"),
        minimum_success_case_count=_as_int("minimum_success_case_count"),
        maximum_failure_case_rate=_as_float("maximum_failure_case_rate"),
        allow_conditional_pass=_as_bool("allow_conditional_pass"),
    )

    if policy.minimum_replay_points < 1:
        raise ValidationCertificationPolicyError("minimum_replay_points must be >= 1")
    if policy.minimum_replay_period_days < 1:
        raise ValidationCertificationPolicyError("minimum_replay_period_days must be >= 1")
    if policy.maximum_significant_drift_count < 0:
        raise ValidationCertificationPolicyError("maximum_significant_drift_count must be >= 0")

    return policy
