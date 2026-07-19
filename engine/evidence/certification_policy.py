from __future__ import annotations

from .certification_schema import CertificationPolicy


def validate_policy(policy: CertificationPolicy) -> CertificationPolicy:
    if not all((policy.policy_id, policy.version, policy.created_at, policy.description)):
        raise ValueError("policy identity fields are required")
    values = (
        policy.minimum_train_performance, policy.minimum_test_performance, policy.minimum_effect_size,
        policy.minimum_confidence_level, policy.maximum_drawdown_increase, policy.maximum_turnover_increase,
        policy.minimum_stability_score, policy.minimum_reproducibility_score, policy.minimum_economic_significance,
    )
    if any(not isinstance(value, (int, float)) for value in values):
        raise ValueError("policy thresholds must be numeric")
    if not 0.0 <= policy.minimum_confidence_level <= 1.0:
        raise ValueError("confidence level must be between zero and one")
    return policy