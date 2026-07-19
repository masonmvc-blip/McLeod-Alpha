from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class HypothesisType(str, Enum):
    SINGLE_FACTOR = "SINGLE_FACTOR"
    MULTI_FACTOR = "MULTI_FACTOR"
    MACRO = "MACRO"
    VALUATION = "VALUATION"
    QUALITY = "QUALITY"
    MOMENTUM = "MOMENTUM"
    GROWTH = "GROWTH"
    MANAGEMENT = "MANAGEMENT"
    INSIDER = "INSIDER"
    OPTIONS = "OPTIONS"
    PORTFOLIO = "PORTFOLIO"
    REGIME = "REGIME"
    CUSTOM = "CUSTOM"


class ExperimentStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExpectedDirection(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NON_LINEAR = "NON_LINEAR"
    UNKNOWN = "UNKNOWN"


class SurvivorshipPolicy(str, Enum):
    INCLUDE_DELISTED = "INCLUDE_DELISTED"
    EXCLUDE_DELISTED = "EXCLUDE_DELISTED"


class RebalanceFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class InteractionType(str, Enum):
    ADDITIVE = "ADDITIVE"
    NEUTRAL = "NEUTRAL"
    DESTRUCTIVE = "DESTRUCTIVE"


@dataclass(frozen=True)
class ResearchHypothesis:
    hypothesis_id: str
    title: str
    description: str
    author: str
    creation_timestamp: str
    hypothesis_type: HypothesisType
    factors_under_test: tuple[str, ...]
    expected_direction: ExpectedDirection
    null_hypothesis: str
    alternative_hypothesis: str
    required_dataset: str
    required_sample_size: int
    experiment_status: ExperimentStatus
    version: str
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    name: str
    category: str
    description: str
    source: str
    version: str = "1.0"


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    universe: str
    start_date: str
    end_date: str
    required_fields: tuple[str, ...]
    required_sample_size: int
    survivorship_policy: SurvivorshipPolicy
    look_ahead_prevention: bool
    data_quality_score: float
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class TransactionAssumptions:
    slippage_bps: float
    commission_bps: float
    borrow_cost_bps: float


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    dataset: DatasetSpec
    universe: str
    date_range: tuple[str, str]
    rebalance_frequency: RebalanceFrequency
    holding_period_days: int
    benchmark: str
    transaction_assumptions: TransactionAssumptions
    survivorship_policy: SurvivorshipPolicy
    look_ahead_prevention: bool
    data_quality_score: float
    factors: tuple[str, ...]
    hypothesis_id: str
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class PerformanceMetrics:
    cagr: float
    alpha: float
    beta: float
    sharpe: float
    sortino: float
    information_ratio: float
    max_drawdown: float
    recovery_time_days: int
    win_rate: float
    hit_rate: float
    turnover: float
    volatility: float
    skew: float
    kurtosis: float


@dataclass(frozen=True)
class StatisticalTestResult:
    t_statistic: float
    t_p_value: float
    mann_whitney_u: float
    mann_whitney_p_value: float
    effect_size: float
    bootstrap_ci_low: float
    bootstrap_ci_high: float
    monte_carlo_p_value: float
    false_discovery_adjusted_p: float
    out_of_sample_passed: bool


@dataclass(frozen=True)
class OverfittingCheck:
    look_ahead_bias: bool
    survivorship_bias: bool
    data_leakage: bool
    p_hacking: bool
    multiple_comparisons: bool
    unstable_parameters: bool
    insufficient_sample_size: bool
    excessive_optimization: bool
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CrossValidationFold:
    method: str
    fold_id: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str


@dataclass(frozen=True)
class FeatureImportanceScore:
    factor: str
    predictive_contribution: float
    stability: float
    persistence: float
    interaction_effects: float
    marginal_improvement: float
    redundancy: float
    composite_score: float


@dataclass(frozen=True)
class InteractionEvaluation:
    factors: tuple[str, ...]
    interaction_type: InteractionType
    incremental_return: float
    incremental_sharpe: float


@dataclass(frozen=True)
class RegimePerformance:
    regime: str
    observations: int
    mean_return: float
    volatility: float
    sharpe: float
    max_drawdown: float


@dataclass(frozen=True)
class RecommendedWeightAdjustment:
    factor: str
    current_weight: float
    recommended_weight: float
    evidence: str
    confidence: float
    expected_improvement: float
    statistical_significance: float
    risks: tuple[str, ...]
    supporting_experiments: tuple[str, ...]
    human_approval_required: bool = True


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    metrics: PerformanceMetrics
    statistical_tests: StatisticalTestResult
    overfitting_check: OverfittingCheck
    feature_rankings: tuple[FeatureImportanceScore, ...]
    interaction_rankings: tuple[InteractionEvaluation, ...]
    regime_breakdown: tuple[RegimePerformance, ...]
    cross_validation_folds: tuple[CrossValidationFold, ...]
    status: ExperimentStatus
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class ResearchReportBundle:
    research_lab_summary_v1: str
    experiment_report_v1: str
    factor_rankings_v1: str
    model_improvement_recommendations_v1: str


@dataclass(frozen=True)
class ResearchLabValidationResult:
    passed: bool
    checks: Mapping[str, bool]
    failures: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ScientificParityResult:
    metric_name: str
    fixture_id: str
    reference_implementation: str
    reference_value: float
    laboratory_value: float
    absolute_error: float
    relative_error: float
    tolerance: float
    passed: bool
    invalid_input_expectation: str
    seed: str
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class DatasetObservation:
    observation_id: str
    security_id: str
    observation_date: str
    economic_period_end: str
    filing_date: str
    publication_timestamp: str
    availability_timestamp: str
    effective_timestamp: str
    universe_membership_timestamp: str
    delisting_timestamp: str
    corporate_action_timestamp: str
    feature_name: str
    feature_value: float
    target_start_timestamp: str
    target_end_timestamp: str
    source_version: str
    revision_identifier: str
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class DatasetContaminationResult:
    fixture_id: str
    contamination_class: str
    passed: bool
    offending_observation_ids: tuple[str, ...]
    evidence: str
    severity: str
    validator_version: str
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class OverfittingCertificationResult:
    family_id: str
    experiment_ids: tuple[str, ...]
    number_of_trials: int
    raw_significant_count: int
    adjusted_significant_count: int
    correction_method: str
    out_of_sample_degradation: float
    fold_instability: float
    concentration_warnings: tuple[str, ...]
    endpoint_changes: int
    parameter_sensitivity: float
    passed: bool
    blockers: tuple[str, ...]
    provenance: Mapping[str, str]