from .backtest import run_backtest
from .cross_validation import build_cross_validation_folds
from .adversarial_datasets import (
    build_adversarial_dataset_fixtures,
    dataset_suite_passed,
    run_dataset_adversarial_suite,
    validate_dataset_fixture,
)
from .dataset import create_dataset_spec, deterministic_dataset_id
from .experiment import create_experiment_spec, deterministic_experiment_id
from .factor_interactions import evaluate_factor_interactions
from .feature_importance import rank_feature_importance
from .hypothesis import create_hypothesis, deterministic_hypothesis_id
from .model import FactorRegistry, ResearchLabModel
from .overfitting import detect_overfitting
from .overfitting_certification import overfitting_matrix_passed, run_overfitting_adversarial_matrix
from .regime_analysis import analyze_regimes
from .reporting import (
    render_experiment_report,
    render_factor_rankings,
    render_model_improvement_recommendations,
    render_research_lab_summary,
)
from .statistics import evaluate_statistical_tests
from .scientific_parity import run_scientific_parity_suite, scientific_parity_passed
from .types import (
    CrossValidationFold,
    DatasetSpec,
    DatasetContaminationResult,
    DatasetObservation,
    ExpectedDirection,
    ExperimentResult,
    ExperimentSpec,
    ExperimentStatus,
    FactorDefinition,
    FeatureImportanceScore,
    HypothesisType,
    InteractionEvaluation,
    InteractionType,
    OverfittingCheck,
    OverfittingCertificationResult,
    PerformanceMetrics,
    RebalanceFrequency,
    RecommendedWeightAdjustment,
    RegimePerformance,
    ResearchHypothesis,
    ResearchLabValidationResult,
    ResearchReportBundle,
    ScientificParityResult,
    StatisticalTestResult,
    SurvivorshipPolicy,
    TransactionAssumptions,
)
from .validation import validate_bias_leakage_controls, validate_experiment_inputs

__all__ = [
    "CrossValidationFold",
    "DatasetSpec",
    "DatasetContaminationResult",
    "DatasetObservation",
    "ExpectedDirection",
    "ExperimentResult",
    "ExperimentSpec",
    "ExperimentStatus",
    "FactorDefinition",
    "FactorRegistry",
    "FeatureImportanceScore",
    "HypothesisType",
    "InteractionEvaluation",
    "InteractionType",
    "OverfittingCheck",
    "OverfittingCertificationResult",
    "PerformanceMetrics",
    "RebalanceFrequency",
    "RecommendedWeightAdjustment",
    "RegimePerformance",
    "ResearchHypothesis",
    "ResearchLabModel",
    "ResearchLabValidationResult",
    "ResearchReportBundle",
    "ScientificParityResult",
    "StatisticalTestResult",
    "SurvivorshipPolicy",
    "TransactionAssumptions",
    "analyze_regimes",
    "build_cross_validation_folds",
    "build_adversarial_dataset_fixtures",
    "create_dataset_spec",
    "create_experiment_spec",
    "create_hypothesis",
    "detect_overfitting",
    "deterministic_dataset_id",
    "deterministic_experiment_id",
    "deterministic_hypothesis_id",
    "evaluate_factor_interactions",
    "evaluate_statistical_tests",
    "dataset_suite_passed",
    "overfitting_matrix_passed",
    "rank_feature_importance",
    "render_experiment_report",
    "render_factor_rankings",
    "render_model_improvement_recommendations",
    "render_research_lab_summary",
    "run_backtest",
    "run_dataset_adversarial_suite",
    "run_overfitting_adversarial_matrix",
    "run_scientific_parity_suite",
    "scientific_parity_passed",
    "validate_dataset_fixture",
    "validate_bias_leakage_controls",
    "validate_experiment_inputs",
]
