from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from engine.phase4.research_lab import (
    ExpectedDirection,
    HypothesisType,
    RebalanceFrequency,
    ResearchLabModel,
    SurvivorshipPolicy,
    TransactionAssumptions,
    build_cross_validation_folds,
    create_dataset_spec,
    create_experiment_spec,
    create_hypothesis,
)
from engine.phase4.research_lab.overfitting import detect_overfitting


REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_LAB_DIR = REPO_ROOT / "engine" / "phase4" / "research_lab"

FROZEN_FILES = (
    REPO_ROOT / "config" / "research_os_manifest.json",
    REPO_ROOT / "engine" / "phase3" / "context.py",
    REPO_ROOT / "engine" / "phase3" / "expected_return" / "model.py",
    REPO_ROOT / "engine" / "phase3" / "decision_engine" / "model.py",
    REPO_ROOT / "engine" / "phase3" / "calibration" / "model.py",
    REPO_ROOT / "engine" / "phase3" / "portfolio_simulation" / "model.py",
    REPO_ROOT / "engine" / "phase3" / "shadow_portfolio_construction" / "model.py",
    REPO_ROOT / "engine" / "phase3" / "system_validation" / "model.py",
    REPO_ROOT / "engine" / "portfolio_engine.py",
    REPO_ROOT / "engine" / "phase2_downstream.py",
)

FROZEN_MILESTONES = (
    REPO_ROOT / "data" / "research" / "logs" / "Research_OS_v1.0.json",
    REPO_ROOT / "data" / "research" / "logs" / "Phase3_Foundation_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "ExpectedReturnEngine_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "DecisionEngine_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "CalibrationEngine_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "PortfolioSimulation_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "ShadowPortfolioConstruction_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "SystemValidation_Complete.json",
    REPO_ROOT / "data" / "research" / "logs" / "SystemAudit_Complete.json",
    REPO_ROOT / "data" / "research" / "logs" / "RepositoryHygiene_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "PaperPortfolioGovernance_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "PaperPortfolioEngine_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "PaperPortfolioPersistenceReplay_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "PaperPortfolioOperationsReadiness_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "IndependentSystemCertification_Validated.json",
    REPO_ROOT / "data" / "research" / "logs" / "PaperPortfolioActivationGate_Validated.json",
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _build_fixture_lab_run() -> tuple[ResearchLabModel, object, object, tuple[float, ...], tuple[float, ...], tuple[str, ...]]:
    hypothesis = create_hypothesis(
        title="ROIC and Insider Buying Improve Forward Returns",
        description="Companies with high ROIC and insider buying outperform benchmark.",
        author="research",
        creation_timestamp="2026-07-18T00:00:00+00:00",
        hypothesis_type=HypothesisType.MULTI_FACTOR,
        factors_under_test=("ROIC", "Insider Buying", "Momentum"),
        expected_direction=ExpectedDirection.POSITIVE,
        null_hypothesis="No difference in returns vs benchmark.",
        alternative_hypothesis="Positive excess return and Sharpe.",
        required_dataset="US_LARGE_CAP_V1",
        required_sample_size=120,
        version="1.0",
        provenance={"source": "unit_test"},
    )
    dataset = create_dataset_spec(
        universe="US_LARGE_CAP",
        start_date="2020-01-01",
        end_date="2026-06-30",
        required_fields=("date", "ticker", "return", "ROIC", "Insider Buying", "Momentum"),
        survivorship_policy=SurvivorshipPolicy.INCLUDE_DELISTED,
        look_ahead_prevention=True,
        data_quality_score=0.95,
        provenance={"source": "unit_test"},
    )
    spec = create_experiment_spec(
        dataset=dataset,
        universe="US_LARGE_CAP",
        date_range=("2020-01-01", "2026-06-30"),
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        holding_period_days=21,
        benchmark="SPY",
        transaction_assumptions=TransactionAssumptions(
            slippage_bps=5.0,
            commission_bps=1.0,
            borrow_cost_bps=0.0,
        ),
        survivorship_policy=SurvivorshipPolicy.INCLUDE_DELISTED,
        look_ahead_prevention=True,
        data_quality_score=0.95,
        factors=hypothesis.factors_under_test,
        hypothesis_id=hypothesis.hypothesis_id,
        provenance={
            "source": "unit_test",
            "deterministic_seed": "unit-seed-1",
            "data_classification": "SYNTHETIC_VALIDATION_ONLY",
        },
    )
    strategy = tuple(0.002 + ((i % 7) - 3) * 0.0003 for i in range(252))
    benchmark = tuple(0.001 + ((i % 5) - 2) * 0.0002 for i in range(252))
    regimes = tuple(
        [
            "bull markets",
            "bear markets",
            "recessions",
            "recoveries",
            "inflationary periods",
            "falling-rate periods",
            "rising-rate periods",
            "high volatility",
            "low volatility",
        ][i % 9]
        for i in range(252)
    )
    lab = ResearchLabModel(REPO_ROOT)
    return lab, hypothesis, spec, strategy, benchmark, regimes


def test_research_lab_isolated_no_broker_or_production_imports() -> None:
    forbidden_import_prefixes = (
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
        "engine.portfolio_engine",
        "engine.phase3",
        "execution",
        "broker",
    )
    forbidden_tokens = (
        "live trading",
        "place_order",
        "execute_order",
        "real_account",
        "production portfolio",
    )

    for path in RESEARCH_LAB_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_import_prefixes)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden_import_prefixes)
        for token in forbidden_tokens:
            assert token not in source.lower()


def test_hypothesis_and_experiment_ids_deterministic_and_immutable() -> None:
    _, hypothesis, spec, _, _, _ = _build_fixture_lab_run()
    _, hypothesis2, spec2, _, _, _ = _build_fixture_lab_run()
    assert hypothesis.hypothesis_id == hypothesis2.hypothesis_id
    assert spec.experiment_id == spec2.experiment_id
    with pytest.raises(FrozenInstanceError):
        hypothesis.title = "tamper"  # type: ignore[misc]


def test_cross_validation_walk_forward_and_out_of_time() -> None:
    folds = build_cross_validation_folds("2020-01-01", "2026-06-30", method="walk_forward", k=5)
    assert len(folds) == 5
    assert all(fold.method == "walk_forward" for fold in folds)

    oot = build_cross_validation_folds("2020-01-01", "2026-06-30", method="out_of_time", k=3)
    assert len(oot) == 3
    assert all(fold.method == "out_of_time" for fold in oot)


def test_overfitting_detection_fail_closed() -> None:
    bad = detect_overfitting(
        strategy_returns=[0.2] * 20,
        benchmark_returns=[0.0] * 20,
        sample_size=20,
        num_trials=80,
        look_ahead_prevention=False,
        survivorship_policy="EXCLUDE_DELISTED",
        data_quality_score=0.2,
    )
    assert bad.passed is False
    assert "LOOK_AHEAD_BIAS" in bad.reasons
    assert "INSUFFICIENT_SAMPLE_SIZE" in bad.reasons


def test_feature_and_interaction_rankings_deterministic() -> None:
    lab, _, spec, strategy, benchmark, regimes = _build_fixture_lab_run()
    factor_returns = {f: strategy for f in spec.factors}
    first = lab.run_experiment(
        spec=spec,
        factor_returns=factor_returns,
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    second = lab.run_experiment(
        spec=spec,
        factor_returns=factor_returns,
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    assert first.feature_rankings == second.feature_rankings
    assert first.interaction_rankings == second.interaction_rankings


def test_reports_deterministic_and_named_v1(tmp_path: Path) -> None:
    lab, _, spec, strategy, benchmark, regimes = _build_fixture_lab_run()
    factor_returns = {f: strategy for f in spec.factors}
    result = lab.run_experiment(
        spec=spec,
        factor_returns=factor_returns,
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    adjustments = lab.recommend_weight_adjustments(
        current_weights={factor: 0.1 for factor in spec.factors},
        feature_rankings=result.feature_rankings,
        supporting_experiment_ids=(result.experiment_id,),
    )
    assert all(adj.human_approval_required for adj in adjustments)

    bundle1 = lab.generate_reports(result=result, adjustments=adjustments)
    bundle2 = lab.generate_reports(result=result, adjustments=adjustments)
    assert bundle1 == bundle2

    output_dir = tmp_path / "reports"
    paths = lab.write_reports(report_bundle=bundle1, output_dir=output_dir)
    names = sorted(path.name for path in paths)
    assert names == [
        "experiment_report_v1.md",
        "factor_rankings_v1.md",
        "model_improvement_recommendations_v1.md",
        "research_lab_summary_v1.md",
    ]


def test_frozen_milestones_and_hashes_unchanged_after_research_run() -> None:
    missing = [path for path in FROZEN_MILESTONES if not path.exists()]
    assert not missing

    before = {str(path): _sha(path) for path in FROZEN_FILES}
    milestone_before = {str(path): _sha(path) for path in FROZEN_MILESTONES}

    lab, _, spec, strategy, benchmark, regimes = _build_fixture_lab_run()
    factor_returns = {f: strategy for f in spec.factors}
    result = lab.run_experiment(
        spec=spec,
        factor_returns=factor_returns,
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    adjustments = lab.recommend_weight_adjustments(
        current_weights={factor: 0.1 for factor in spec.factors},
        feature_rankings=result.feature_rankings,
        supporting_experiment_ids=(result.experiment_id,),
    )
    assert all(adj.human_approval_required for adj in adjustments)

    after = {str(path): _sha(path) for path in FROZEN_FILES}
    milestone_after = {str(path): _sha(path) for path in FROZEN_MILESTONES}

    assert before == after
    assert milestone_before == milestone_after


def test_no_automatic_model_or_weight_updates(tmp_path: Path) -> None:
    lab, _, spec, strategy, benchmark, regimes = _build_fixture_lab_run()
    factor_returns = {f: strategy for f in spec.factors}
    result = lab.run_experiment(
        spec=spec,
        factor_returns=factor_returns,
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    adjustments = lab.recommend_weight_adjustments(
        current_weights={factor: 0.1 for factor in spec.factors},
        feature_rankings=result.feature_rankings,
        supporting_experiment_ids=(result.experiment_id,),
    )
    assert all(adj.human_approval_required for adj in adjustments)

    marker = tmp_path / "McLeodResearchLab_v1.0_Validated.json"
    lab.write_validation_artifact(passed=True, output_path=marker)
    payload = marker.read_text(encoding="utf-8")
    assert "production_updates_applied" in payload
    assert "false" in payload.lower()
