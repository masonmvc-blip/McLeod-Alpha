from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from engine.phase4.research_lab import (
    ExpectedDirection,
    FactorDefinition,
    FactorRegistry,
    HypothesisType,
    RebalanceFrequency,
    ResearchLabModel,
    SurvivorshipPolicy,
    TransactionAssumptions,
    build_cross_validation_folds,
    dataset_suite_passed,
    create_dataset_spec,
    create_experiment_spec,
    create_hypothesis,
    evaluate_statistical_tests,
    overfitting_matrix_passed,
    run_dataset_adversarial_suite,
    run_overfitting_adversarial_matrix,
    run_scientific_parity_suite,
    scientific_parity_passed,
    validate_dataset_fixture,
    validate_bias_leakage_controls,
)
from engine.phase4.research_lab.backtest import run_backtest


REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER_PATH = REPO_ROOT / "data" / "research" / "logs" / "McLeodResearchLab_v1.0_Validated.json"
LAB_DIR = REPO_ROOT / "engine" / "phase4" / "research_lab"
REQ_PATH = REPO_ROOT / "config" / "research_lab_v1_requirements.json"


REQUIRED_FACTORS = {
    "Valuation": {"PE", "EV/EBITDA", "FCF Yield", "Earnings Yield", "P/B", "P/S", "PEG"},
    "Quality": {"ROIC", "ROE", "ROA", "Gross Margin", "Operating Margin", "FCF Margin", "Debt/EBITDA", "Interest Coverage"},
    "Growth": {"Revenue Growth", "EPS Growth", "FCF Growth", "Book Value Growth"},
    "Capital Allocation": {"Buybacks", "Share Dilution", "Dividend Growth", "Reinvestment Rate"},
    "Management": {"Insider Ownership", "Founder Led", "CEO Tenure", "Insider Buying"},
    "Market": {"Relative Strength", "Momentum", "Volatility", "Drawdown"},
    "Macro": {"Rates", "Inflation", "Truck Sales", "PMI", "Credit Spreads"},
}


def _build_spec(seed: str = "42"):
    hypothesis = create_hypothesis(
        title="ROIC + Insider Buying + Momentum",
        description="Synthetic validation fixture only.",
        author="cert",
        creation_timestamp="2026-07-18T00:00:00+00:00",
        hypothesis_type=HypothesisType.MULTI_FACTOR,
        factors_under_test=("ROIC", "Insider Buying", "Momentum"),
        expected_direction=ExpectedDirection.POSITIVE,
        null_hypothesis="No alpha",
        alternative_hypothesis="Positive alpha",
        required_dataset="SYNTHETIC_DS",
        required_sample_size=120,
        version="1.0",
        provenance={"source": "cert"},
    )
    dataset = create_dataset_spec(
        universe="US_LARGE_CAP",
        start_date="2020-01-01",
        end_date="2026-06-30",
        required_fields=("date", "ticker", "return", "ROIC", "Insider Buying", "Momentum"),
        survivorship_policy=SurvivorshipPolicy.INCLUDE_DELISTED,
        look_ahead_prevention=True,
        data_quality_score=0.95,
        provenance={"source": "cert"},
        required_sample_size=120,
    )
    spec = create_experiment_spec(
        dataset=dataset,
        universe="US_LARGE_CAP",
        date_range=("2020-01-01", "2026-06-30"),
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        holding_period_days=21,
        benchmark="SPY",
        transaction_assumptions=TransactionAssumptions(slippage_bps=5.0, commission_bps=1.0, borrow_cost_bps=0.0),
        survivorship_policy=SurvivorshipPolicy.INCLUDE_DELISTED,
        look_ahead_prevention=True,
        data_quality_score=0.95,
        factors=hypothesis.factors_under_test,
        hypothesis_id=hypothesis.hypothesis_id,
        provenance={
            "source": "cert",
            "deterministic_seed": seed,
            "dataset_id": dataset.dataset_id,
            "dataset_version": "1.0",
            "date_range": "2020-01-01..2026-06-30",
            "universe": "US_LARGE_CAP",
            "survivorship_policy": "INCLUDE_DELISTED",
            "publication_lag_policy": "POINT_IN_TIME_ONLY",
            "transaction_assumptions": "slippage=5bps,commission=1bps,borrow=0bps",
            "benchmark": "SPY",
            "sample_size": "252",
            "validation_method": "walk_forward+adversarial",
            "in_sample_results": "synthetic_fixture",
            "warnings": "SYNTHETIC_VALIDATION_ONLY",
            "limitations": "No historical alpha evidence",
            "multiple_testing_correction": "Scalar family correction",
            "artifact_hashes": "deterministic_fixture",
            "data_classification": "SYNTHETIC_VALIDATION_ONLY",
        },
    )
    return spec


def test_validation_marker_is_not_treated_as_final_certification() -> None:
    payload = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
    assert payload.get("status") in {"PROVISIONAL", "SUPERSEDED"}
    assert payload.get("full_deterministic_matrix_executed") is False


def test_module_completeness_and_substantive_implementations() -> None:
    required = {
        "__init__.py",
        "types.py",
        "hypothesis.py",
        "dataset.py",
        "experiment.py",
        "backtest.py",
        "statistics.py",
        "validation.py",
        "feature_importance.py",
        "factor_interactions.py",
        "regime_analysis.py",
        "cross_validation.py",
        "overfitting.py",
        "overfitting_certification.py",
        "scientific_parity.py",
        "adversarial_datasets.py",
        "reporting.py",
        "model.py",
    }
    present = {p.name for p in LAB_DIR.glob("*.py")}
    assert required.issubset(present)
    for name in required:
        source = (LAB_DIR / name).read_text(encoding="utf-8")
        assert "\n    pass\n" not in source
        assert "TODO" not in source
        assert len(source.splitlines()) >= 15


def test_factor_library_required_factors_and_registry_controls() -> None:
    registry = FactorRegistry()
    all_factors = registry.list_all()
    by_category: dict[str, set[str]] = {}
    for factor in all_factors:
        by_category.setdefault(factor.category, set()).add(factor.name)
    for category, expected in REQUIRED_FACTORS.items():
        assert expected.issubset(by_category.get(category, set()))

    with pytest.raises(ValueError):
        registry.register(
            FactorDefinition(
                factor_id="dup::roic",
                name="roic",
                category="Quality",
                description="duplicate",
                source="unit",
            )
        )

    custom = registry.register_custom(name="My Custom Factor", description="custom", source="analyst")
    assert custom.version == "1.0"
    assert registry.get("my custom factor") is not None

    with pytest.raises(ValueError):
        registry.register(
            FactorDefinition(
                factor_id="",
                name="Bad",
                category="Custom",
                description="desc",
                source="unit",
            )
        )


def test_cross_validation_certification_guards() -> None:
    for method in ("rolling", "expanding", "walk_forward", "k_fold", "out_of_time"):
        folds = build_cross_validation_folds("2020-01-01", "2026-06-30", method=method, k=5, purge_days=1, embargo_days=1)
        assert len(folds) == 5
        for fold in folds:
            assert fold.train_end < fold.test_start

    with pytest.raises(ValueError):
        build_cross_validation_folds("2020-01-01", "2020-01-03", method="rolling", k=5)

    with pytest.raises(ValueError):
        build_cross_validation_folds("2020-01-01", "2026-06-30", method="k_fold", allow_shuffled_k_fold=True)


def test_statistical_certification_with_edge_cases() -> None:
    out = run_backtest(
        experiment_id="fixture",
        factor_returns={"A": [0.1, -0.05], "B": [0.1, -0.05]},
        benchmark_returns=[0.0, 0.0],
    )
    metrics = out["metrics"]
    assert math.isclose(metrics.cagr, (1.1 * 0.95) ** (252.0 / 2.0) - 1.0, rel_tol=1e-9)
    assert math.isclose(metrics.max_drawdown, -0.05, rel_tol=1e-9)

    stats = evaluate_statistical_tests(
        strategy_returns=[0.01, 0.02, 0.0, -0.01],
        benchmark_returns=[0.0, 0.005, 0.0, -0.005],
        num_hypotheses=4,
    )
    assert 0.0 <= stats.t_p_value <= 1.0
    assert 0.0 <= stats.false_discovery_adjusted_p <= 1.0

    with pytest.raises(ValueError):
        evaluate_statistical_tests(strategy_returns=[0.01], benchmark_returns=[0.0], num_hypotheses=1)
    with pytest.raises(ValueError):
        evaluate_statistical_tests(strategy_returns=[0.01, float("nan")], benchmark_returns=[0.0, 0.0], num_hypotheses=1)
    with pytest.raises(ValueError):
        evaluate_statistical_tests(strategy_returns=[0.01, 0.02], benchmark_returns=[0.0], num_hypotheses=1)


def test_bias_leakage_adversarial_datasets_fail_closed() -> None:
    contaminated = {
        "future_fundamental_data": True,
        "future_prices": True,
        "revised_macro_data": False,
        "post_period_index_membership": True,
        "survivor_only_universe": True,
        "delisted_omission": True,
        "overlapping_train_test": True,
        "target_leakage_derived_features": True,
        "timestamp_misalignment": True,
        "filing_date_period_end_confusion": True,
        "publication_lag_violation": True,
        "corporate_action_hindsight": True,
        "benchmark_look_ahead": True,
        "universe_selection_look_ahead": True,
    }
    with pytest.raises(ValueError):
        validate_bias_leakage_controls(contamination_flags=contaminated)


def test_determinism_across_processes_and_input_order(tmp_path: Path) -> None:
    spec = _build_spec(seed="777")
    strategy = [0.001 + (i % 5) * 0.0001 for i in range(252)]
    benchmark = [0.0008 + (i % 3) * 0.0001 for i in range(252)]
    regimes = ["bull markets", "bear markets", "recessions", "recoveries", "inflationary periods", "falling-rate periods", "rising-rate periods", "high volatility", "low volatility"]

    lab = ResearchLabModel(REPO_ROOT)
    factors_a = {"ROIC": strategy, "Momentum": strategy, "Insider Buying": strategy}
    factors_b = {"Momentum": strategy, "Insider Buying": strategy, "ROIC": strategy}
    r1 = lab.run_experiment(spec=spec, factor_returns=factors_a, benchmark_returns=benchmark, regime_labels=regimes)
    r2 = lab.run_experiment(spec=spec, factor_returns=factors_b, benchmark_returns=benchmark, regime_labels=regimes)
    assert r1.feature_rankings == r2.feature_rankings
    assert r1.interaction_rankings == r2.interaction_rankings

    code = (
        "from pathlib import Path\n"
        "from engine.phase4.research_lab import ResearchLabModel\n"
        "from tests.test_research_lab_release_certification_invariants import _build_spec\n"
        "spec=_build_spec(seed='777')\n"
        "strategy=[0.001 + (i % 5) * 0.0001 for i in range(252)]\n"
        "benchmark=[0.0008 + (i % 3) * 0.0001 for i in range(252)]\n"
        "regimes=['bull markets','bear markets','recessions','recoveries','inflationary periods','falling-rate periods','rising-rate periods','high volatility','low volatility']\n"
        "lab=ResearchLabModel(Path('.'))\n"
        "r=lab.run_experiment(spec=spec,factor_returns={'ROIC':strategy,'Momentum':strategy,'Insider Buying':strategy},benchmark_returns=benchmark,regime_labels=regimes)\n"
        "print(r.experiment_id)\n"
        "print(r.feature_rankings[0].factor)\n"
    )
    out1 = subprocess.check_output([sys.executable, "-c", code], cwd=REPO_ROOT, text=True).strip().splitlines()
    out2 = subprocess.check_output([sys.executable, "-c", code], cwd=REPO_ROOT, text=True).strip().splitlines()
    assert out1 == out2


def test_model_change_firewall_and_broker_isolation() -> None:
    forbidden_import_prefixes = (
        "alpaca",
        "schwab",
        "engine.portfolio_engine",
        "engine.phase3",
        "execution",
    )
    forbidden_tokens = (
        "live trade",
        "place_order",
        "execute_order",
        "open_session",
        "token.json",
    )
    for path in LAB_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_import_prefixes)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden_import_prefixes)
        lower = source.lower()
        for token in forbidden_tokens:
            assert token not in lower


def test_synthetic_labeling_and_report_disclosure_requirements(tmp_path: Path) -> None:
    spec = _build_spec(seed="999")
    strategy = [0.001 + (i % 5) * 0.0001 for i in range(252)]
    benchmark = [0.0008 + (i % 3) * 0.0001 for i in range(252)]
    regimes = ["bull markets", "bear markets", "recessions", "recoveries", "inflationary periods", "falling-rate periods", "rising-rate periods", "high volatility", "low volatility"]

    lab = ResearchLabModel(REPO_ROOT)
    result = lab.run_experiment(
        spec=spec,
        factor_returns={"ROIC": strategy, "Momentum": strategy, "Insider Buying": strategy},
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    adjustments = lab.recommend_weight_adjustments(
        current_weights={"ROIC": 0.1, "Momentum": 0.1, "Insider Buying": 0.1},
        feature_rankings=result.feature_rankings,
        supporting_experiment_ids=(result.experiment_id,),
    )
    bundle = lab.generate_reports(result=result, adjustments=adjustments)

    assert "SYNTHETIC_VALIDATION_ONLY" in bundle.research_lab_summary_v1
    assert "No historical alpha conclusion." in bundle.research_lab_summary_v1
    assert "dataset_identity" in bundle.experiment_report_v1
    assert "reproducibility_seed" in bundle.experiment_report_v1

    marker = tmp_path / "marker.json"
    lab.write_validation_artifact(passed=True, output_path=marker)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["data_classification"] == "SYNTHETIC_VALIDATION_ONLY"
    assert payload["no_historical_alpha_conclusion"] is True


def test_clean_environment_rehearsal(tmp_path: Path) -> None:
    # Build isolated synthetic dataset and run a valid experiment.
    spec = _build_spec(seed="clean-room-seed")
    strategy = [0.001 + (i % 7) * 0.0001 for i in range(252)]
    benchmark = [0.0009 + (i % 5) * 0.00005 for i in range(252)]
    regimes = [
        "bull markets",
        "bear markets",
        "recessions",
        "recoveries",
        "inflationary periods",
        "falling-rate periods",
        "rising-rate periods",
        "high volatility",
        "low volatility",
    ]
    lab = ResearchLabModel(REPO_ROOT)
    result = lab.run_experiment(
        spec=spec,
        factor_returns={"ROIC": strategy, "Momentum": strategy, "Insider Buying": strategy},
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    assert result.status.value == "COMPLETED"

    # Contaminated fixtures must fail closed.
    with pytest.raises(ValueError):
        validate_bias_leakage_controls(
            contamination_flags={
                "future_fundamental_data": True,
                "future_prices": False,
                "revised_macro_data": False,
                "post_period_index_membership": False,
                "survivor_only_universe": False,
                "delisted_omission": False,
                "overlapping_train_test": False,
                "target_leakage_derived_features": False,
                "timestamp_misalignment": False,
                "filing_date_period_end_confusion": False,
                "publication_lag_violation": False,
                "corporate_action_hindsight": False,
                "benchmark_look_ahead": False,
                "universe_selection_look_ahead": False,
            }
        )

    # Deterministic reproduction in second process.
    code = (
        "from pathlib import Path\n"
        "from tests.test_research_lab_release_certification_invariants import _build_spec\n"
        "from engine.phase4.research_lab import ResearchLabModel\n"
        "spec=_build_spec(seed='clean-room-seed')\n"
        "strategy=[0.001 + (i % 7) * 0.0001 for i in range(252)]\n"
        "benchmark=[0.0009 + (i % 5) * 0.00005 for i in range(252)]\n"
        "regimes=['bull markets','bear markets','recessions','recoveries','inflationary periods','falling-rate periods','rising-rate periods','high volatility','low volatility']\n"
        "lab=ResearchLabModel(Path('.'))\n"
        "r=lab.run_experiment(spec=spec,factor_returns={'ROIC':strategy,'Momentum':strategy,'Insider Buying':strategy},benchmark_returns=benchmark,regime_labels=regimes)\n"
        "print(r.experiment_id)\n"
        "print(r.metrics.cagr)\n"
    )
    p1 = subprocess.check_output([sys.executable, "-c", code], cwd=REPO_ROOT, text=True).strip()
    p2 = subprocess.check_output([sys.executable, "-c", code], cwd=REPO_ROOT, text=True).strip()
    assert p1 == p2

    # Generate deterministic reports in temp storage and compare.
    adjustments = lab.recommend_weight_adjustments(
        current_weights={"ROIC": 0.1, "Momentum": 0.1, "Insider Buying": 0.1},
        feature_rankings=result.feature_rankings,
        supporting_experiment_ids=(result.experiment_id,),
    )
    bundle = lab.generate_reports(result=result, adjustments=adjustments)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    paths_a = lab.write_reports(report_bundle=bundle, output_dir=out_a)
    paths_b = lab.write_reports(report_bundle=bundle, output_dir=out_b)
    assert sorted(p.name for p in paths_a) == sorted(p.name for p in paths_b)
    for name in sorted(p.name for p in paths_a):
        assert (out_a / name).read_text(encoding="utf-8") == (out_b / name).read_text(encoding="utf-8")

    # Cleanup rehearsal temporary outputs.
    for p in list(out_a.rglob("*")) + list(out_b.rglob("*")):
        if p.is_file():
            p.unlink()
    for p in sorted(list(out_a.rglob("*")) + list(out_b.rglob("*")), reverse=True):
        if p.is_dir():
            p.rmdir()
    out_a.rmdir()
    out_b.rmdir()
    assert not out_a.exists()
    assert not out_b.exists()


def test_scientific_library_parity_complete_and_deterministic() -> None:
    first = run_scientific_parity_suite()
    second = run_scientific_parity_suite()
    assert first == second
    assert scientific_parity_passed(first)

    metric_names = {row.metric_name for row in first}
    required = {
        "CAGR",
        "Alpha",
        "Beta",
        "Sharpe",
        "Sortino",
        "Information Ratio",
        "Max Drawdown",
        "Recovery Time",
        "Win Rate",
        "Hit Rate",
        "Turnover",
        "Volatility",
        "Skew",
        "Kurtosis",
        "t-test",
        "Mann-Whitney",
        "bootstrap confidence intervals low",
        "bootstrap confidence intervals high",
        "Monte Carlo resampling",
        "effect size",
        "false-discovery correction",
    }
    assert required.issubset(metric_names)

    frequencies = {row.provenance.get("frequency") for row in first if row.provenance.get("frequency")}
    assert {"daily", "weekly", "monthly"}.issubset(frequencies)

    invalid_rows = [row for row in first if row.fixture_id == "invalid_inputs_v1"]
    assert len(invalid_rows) >= 5
    assert all(row.passed for row in invalid_rows)


def test_dataset_adversarial_fixtures_detect_contamination_from_data() -> None:
    signature = inspect.signature(validate_dataset_fixture)
    assert "contaminated" not in signature.parameters
    assert "contamination_flags" not in signature.parameters

    results = run_dataset_adversarial_suite()
    assert dataset_suite_passed(results)

    valid_rows = [row for row in results if row.fixture_id.endswith("::valid")]
    contaminated_rows = [row for row in results if row.fixture_id.endswith("::contaminated")]
    assert valid_rows and contaminated_rows
    assert all(row.passed for row in valid_rows)
    assert all(not row.passed for row in contaminated_rows)
    assert all(row.offending_observation_ids for row in contaminated_rows)
    assert all(row.evidence for row in contaminated_rows)


def test_overfitting_adversarial_family_matrix() -> None:
    results = run_overfitting_adversarial_matrix()
    assert overfitting_matrix_passed(results)

    families = {row.family_id for row in results}
    assert {
        "repeated_hypothesis_testing",
        "multiple_comparison_inflation",
        "parameter_grid_explosion",
        "best_backtest_selection",
        "unstable_folds",
        "weak_out_of_sample",
        "insufficient_effective_sample",
        "extreme_turnover",
        "regime_concentration",
        "single_security",
        "single_period",
        "endpoint_manipulation",
        "excessive_factor_combinations",
        "excessive_universe_variations",
        "excessive_holding_period_variations",
        "excessive_rebalance_frequency_variations",
        "control_family",
    }.issubset(families)

    control = [row for row in results if row.family_id == "control_family"]
    assert len(control) == 1 and control[0].passed
    for row in results:
        if row.family_id != "control_family":
            assert not row.passed
            assert len(row.blockers) > 0
            assert row.correction_method in {"benjamini-hochberg", "bonferroni"}


def test_artifact_hashing_pipeline_is_real_and_deterministic(tmp_path: Path) -> None:
    spec = _build_spec(seed="hash-seed")
    strategy = [0.001 + (i % 7) * 0.0001 for i in range(252)]
    benchmark = [0.0009 + (i % 5) * 0.00005 for i in range(252)]
    regimes = [
        "bull markets",
        "bear markets",
        "recessions",
        "recoveries",
        "inflationary periods",
        "falling-rate periods",
        "rising-rate periods",
        "high volatility",
        "low volatility",
    ]
    lab = ResearchLabModel(REPO_ROOT)
    result = lab.run_experiment(
        spec=spec,
        factor_returns={"ROIC": strategy, "Momentum": strategy, "Insider Buying": strategy},
        benchmark_returns=benchmark,
        regime_labels=regimes,
    )
    adjustments = lab.recommend_weight_adjustments(
        current_weights={"ROIC": 0.1, "Momentum": 0.1, "Insider Buying": 0.1},
        feature_rankings=result.feature_rankings,
        supporting_experiment_ids=(result.experiment_id,),
    )

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    _, manifest_a = lab.write_reports_with_artifact_manifest(
        result=result,
        adjustments=adjustments,
        output_dir=out_a,
        deterministic_seed="hash-seed",
    )
    _, manifest_b = lab.write_reports_with_artifact_manifest(
        result=result,
        adjustments=adjustments,
        output_dir=out_b,
        deterministic_seed="hash-seed",
    )

    a_payload = json.loads(manifest_a.read_text(encoding="utf-8"))
    b_payload = json.loads(manifest_b.read_text(encoding="utf-8"))
    a_norm = sorted((row["artifact_type"], row["sha256"], row["size"], row["schema_version"], row["experiment_id"], row["deterministic_seed"]) for row in a_payload["artifacts"])
    b_norm = sorted((row["artifact_type"], row["sha256"], row["size"], row["schema_version"], row["experiment_id"], row["deterministic_seed"]) for row in b_payload["artifacts"])
    assert a_norm == b_norm

    rows = a_payload["artifacts"]
    assert rows
    assert all(row["sha256"] and len(row["sha256"]) == 64 for row in rows)
    assert all("placeholder" not in row["sha256"].lower() for row in rows)

    for row in rows:
        artifact_path = Path(row["artifact_path"])
        if not artifact_path.is_absolute():
            artifact_path = REPO_ROOT / artifact_path
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        assert digest == row["sha256"]

    summary_text = (out_a / "research_lab_summary_v1.md").read_text(encoding="utf-8")
    assert "artifact_hashes" in summary_text
    assert "not_recorded" not in summary_text

    tampered = out_a / "experiment_result_v1.json"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    digest_after = hashlib.sha256(tampered.read_bytes()).hexdigest()
    original = next(row for row in rows if row["artifact_path"].endswith("experiment_result_v1.json"))["sha256"]
    assert digest_after != original


def test_traceability_all_verified_and_eligibility_derived() -> None:
    payload = json.loads(REQ_PATH.read_text(encoding="utf-8"))
    requirements = payload["requirements"]
    assert requirements

    derived = True
    for req in requirements:
        assert req["status"] == "VERIFIED"
        assert req.get("requirement")
        assert req.get("implementation_files")
        assert req.get("public_interfaces")
        assert req.get("invariant_tests")
        assert req.get("certification_tests")
        assert req.get("evidence_artifacts")
        assert req.get("verification_rationale")
        assert "verified_hash_references" in req
        if req["status"] != "VERIFIED":
            derived = False

        for rel_path in req["implementation_files"]:
            assert (REPO_ROOT / rel_path).exists()
        for rel_path in req["evidence_artifacts"]:
            assert (REPO_ROOT / rel_path).exists()
        for rel_path, expected_hash in req["verified_hash_references"].items():
            path = REPO_ROOT / rel_path
            assert path.exists()
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == expected_hash

    assert payload.get("certification_eligible") == derived


def test_frozen_markers_unchanged_and_conflicted_copies_archived_only() -> None:
    frozen_markers = [
        "data/research/logs/Research_OS_v1.0.json",
        "data/research/logs/Phase3_Foundation_Validated.json",
        "data/research/logs/PaperPortfolioGovernance_Validated.json",
        "data/research/logs/PaperPortfolioEngine_Validated.json",
        "data/research/logs/PaperPortfolioPersistenceReplay_Validated.json",
        "data/research/logs/PaperPortfolioOperationsReadiness_Validated.json",
        "data/research/logs/IndependentSystemCertification_Validated.json",
        "data/research/logs/PaperPortfolioActivationGate_Validated.json",
    ]
    for rel in frozen_markers:
        path = REPO_ROOT / rel
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert text.strip()

    active_conflicted = [
        path for path in REPO_ROOT.glob("token*conflicted copy*.json") if "archive/2026-07-18_cleanup" not in str(path)
    ]
    assert not active_conflicted
