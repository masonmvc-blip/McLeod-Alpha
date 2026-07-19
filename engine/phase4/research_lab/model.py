from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
from typing import Mapping, Sequence

from .backtest import run_backtest
from .cross_validation import build_cross_validation_folds
from .factor_interactions import evaluate_factor_interactions
from .feature_importance import rank_feature_importance
from .overfitting import detect_overfitting
from .regime_analysis import analyze_regimes
from .reporting import (
    render_experiment_report,
    render_factor_rankings,
    render_model_improvement_recommendations,
    render_research_lab_summary,
)
from .statistics import evaluate_statistical_tests
from .types import (
    ExperimentResult,
    ExperimentSpec,
    ExperimentStatus,
    FeatureImportanceScore,
    FactorDefinition,
    InteractionEvaluation,
    PerformanceMetrics,
    RecommendedWeightAdjustment,
    RegimePerformance,
    ResearchReportBundle,
    StatisticalTestResult,
)
from .validation import validate_experiment_inputs


class FactorRegistry:
    def __init__(self) -> None:
        self._factors: dict[str, FactorDefinition] = {}
        self._seed_builtins()

    def _validate_factor(self, factor: FactorDefinition) -> None:
        if not factor.factor_id.strip():
            raise ValueError("factor_id must be non-empty")
        if not factor.name.strip():
            raise ValueError("factor name must be non-empty")
        if not factor.category.strip():
            raise ValueError("factor category must be non-empty")
        if not factor.description.strip():
            raise ValueError("factor description must be non-empty")
        if not factor.source.strip():
            raise ValueError("factor source must be non-empty")
        if not factor.version.strip():
            raise ValueError("factor version must be non-empty")

    def register(self, factor: FactorDefinition) -> None:
        self._validate_factor(factor)
        key = factor.name.strip().lower()
        if not key:
            raise ValueError("factor name must be non-empty")
        if key in self._factors:
            raise ValueError(f"factor already registered: {factor.name}")
        self._factors[key] = factor

    def register_custom(self, *, name: str, description: str, source: str = "user") -> FactorDefinition:
        factor = FactorDefinition(
            factor_id=f"custom::{name.strip().lower().replace(' ', '_')}",
            name=name,
            category="Custom",
            description=description,
            source=source,
            version="1.0",
        )
        self.register(factor)
        return factor

    def get(self, name: str) -> FactorDefinition | None:
        return self._factors.get(name.strip().lower())

    def list_all(self) -> tuple[FactorDefinition, ...]:
        return tuple(self._factors[k] for k in sorted(self._factors.keys()))

    def _seed_builtins(self) -> None:
        builtins: list[tuple[str, str, str]] = [
            ("Valuation", "PE", "Price-to-earnings ratio"),
            ("Valuation", "EV/EBITDA", "Enterprise value to EBITDA"),
            ("Valuation", "FCF Yield", "Free-cash-flow yield"),
            ("Valuation", "Earnings Yield", "Inverse PE"),
            ("Valuation", "P/B", "Price-to-book"),
            ("Valuation", "P/S", "Price-to-sales"),
            ("Valuation", "PEG", "Price/earnings-to-growth"),
            ("Quality", "ROIC", "Return on invested capital"),
            ("Quality", "ROE", "Return on equity"),
            ("Quality", "ROA", "Return on assets"),
            ("Quality", "Gross Margin", "Gross margin percentage"),
            ("Quality", "Operating Margin", "Operating margin percentage"),
            ("Quality", "FCF Margin", "Free-cash-flow margin"),
            ("Quality", "Debt/EBITDA", "Leverage ratio"),
            ("Quality", "Interest Coverage", "Debt service capacity"),
            ("Growth", "Revenue Growth", "Revenue growth trend"),
            ("Growth", "EPS Growth", "Earnings per share growth"),
            ("Growth", "FCF Growth", "Free-cash-flow growth"),
            ("Growth", "Book Value Growth", "Book value growth"),
            ("Capital Allocation", "Buybacks", "Net share repurchase activity"),
            ("Capital Allocation", "Share Dilution", "Share count growth"),
            ("Capital Allocation", "Dividend Growth", "Dividend per share growth"),
            ("Capital Allocation", "Reinvestment Rate", "Reinvestment of free cash flow"),
            ("Management", "Insider Ownership", "Percent insider ownership"),
            ("Management", "Founder Led", "Founder-led indicator"),
            ("Management", "CEO Tenure", "CEO years in role"),
            ("Management", "Insider Buying", "Insider buy activity"),
            ("Market", "Relative Strength", "Relative momentum vs universe"),
            ("Market", "Momentum", "Price momentum"),
            ("Market", "Volatility", "Return variability"),
            ("Market", "Drawdown", "Peak-to-trough decline"),
            ("Macro", "Rates", "Interest rate backdrop"),
            ("Macro", "Inflation", "Inflation regime proxy"),
            ("Macro", "Truck Sales", "Industrial demand proxy"),
            ("Macro", "PMI", "Manufacturing sentiment"),
            ("Macro", "Credit Spreads", "Credit risk premium"),
        ]
        for category, name, description in builtins:
            self.register(
                FactorDefinition(
                    factor_id=f"{category.lower().replace(' ', '_')}::{name.lower().replace(' ', '_').replace('/', '_')}",
                    name=name,
                    category=category,
                    description=description,
                    source="builtin",
                )
            )


class ResearchLabModel:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.factor_registry = FactorRegistry()

    def run_experiment(
        self,
        *,
        spec: ExperimentSpec,
        factor_returns: Mapping[str, Sequence[float]],
        benchmark_returns: Sequence[float],
        regime_labels: Sequence[str],
    ) -> ExperimentResult:
        validate_experiment_inputs(spec=spec, factor_returns=factor_returns, benchmark_returns=benchmark_returns)
        backtest_output = run_backtest(
            experiment_id=spec.experiment_id,
            factor_returns=factor_returns,
            benchmark_returns=benchmark_returns,
        )
        metrics: PerformanceMetrics = backtest_output["metrics"]
        strategy_returns: tuple[float, ...] = backtest_output["strategy_returns"]

        stats: StatisticalTestResult = evaluate_statistical_tests(
            strategy_returns=strategy_returns,
            benchmark_returns=tuple(float(x) for x in benchmark_returns),
            num_hypotheses=max(1, len(spec.factors)),
        )
        overfit = detect_overfitting(
            strategy_returns=strategy_returns,
            benchmark_returns=tuple(float(x) for x in benchmark_returns),
            sample_size=len(strategy_returns),
            num_trials=max(1, len(spec.factors) * 2),
            look_ahead_prevention=spec.look_ahead_prevention,
            survivorship_policy=spec.survivorship_policy.value,
            data_quality_score=spec.data_quality_score,
        )
        feature_rankings = rank_feature_importance(spec.factors, strategy_returns=strategy_returns)
        interaction_rankings = evaluate_factor_interactions(spec.factors, strategy_returns=strategy_returns)
        regime_breakdown = analyze_regimes(strategy_returns=strategy_returns, regimes=tuple(regime_labels))
        folds = build_cross_validation_folds(spec.date_range[0], spec.date_range[1], method="walk_forward", k=5)

        status = ExperimentStatus.COMPLETED if overfit.passed else ExperimentStatus.FAILED
        return ExperimentResult(
            experiment_id=spec.experiment_id,
            metrics=metrics,
            statistical_tests=stats,
            overfitting_check=overfit,
            feature_rankings=feature_rankings,
            interaction_rankings=interaction_rankings,
            regime_breakdown=regime_breakdown,
            cross_validation_folds=folds,
            status=status,
            provenance=spec.provenance,
        )

    def recommend_weight_adjustments(
        self,
        *,
        current_weights: Mapping[str, float],
        feature_rankings: Sequence[FeatureImportanceScore],
        supporting_experiment_ids: Sequence[str],
    ) -> tuple[RecommendedWeightAdjustment, ...]:
        ranked = sorted(feature_rankings, key=lambda row: (-row.composite_score, row.factor))
        adjustments: list[RecommendedWeightAdjustment] = []
        for row in ranked[:10]:
            current_weight = float(current_weights.get(row.factor, 0.0))
            delta = min(0.05, max(-0.05, row.composite_score * 0.05))
            rec_weight = max(0.0, current_weight + delta)
            adjustments.append(
                RecommendedWeightAdjustment(
                    factor=row.factor,
                    current_weight=current_weight,
                    recommended_weight=rec_weight,
                    evidence=f"Composite score {row.composite_score:.4f}",
                    confidence=max(0.0, min(1.0, row.stability)),
                    expected_improvement=max(0.0, row.marginal_improvement),
                    statistical_significance=1.0 - min(1.0, row.redundancy),
                    risks=("requires human validation",),
                    supporting_experiments=tuple(sorted(set(supporting_experiment_ids))),
                    human_approval_required=True,
                )
            )
        return tuple(adjustments)

    def generate_reports(
        self,
        *,
        result: ExperimentResult,
        adjustments: Sequence[RecommendedWeightAdjustment],
    ) -> ResearchReportBundle:
        synthetic_only = str((result.provenance or {}).get("data_classification") or "").upper() == "SYNTHETIC_VALIDATION_ONLY"
        return ResearchReportBundle(
            research_lab_summary_v1=render_research_lab_summary(result, synthetic_only=synthetic_only),
            experiment_report_v1=render_experiment_report(result, synthetic_only=synthetic_only),
            factor_rankings_v1=render_factor_rankings(result.feature_rankings),
            model_improvement_recommendations_v1=render_model_improvement_recommendations(adjustments, synthetic_only=synthetic_only),
        )

    def write_reports(self, *, report_bundle: ResearchReportBundle, output_dir: Path) -> tuple[Path, ...]:
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "research_lab_summary_v1.md": report_bundle.research_lab_summary_v1,
            "experiment_report_v1.md": report_bundle.experiment_report_v1,
            "factor_rankings_v1.md": report_bundle.factor_rankings_v1,
            "model_improvement_recommendations_v1.md": report_bundle.model_improvement_recommendations_v1,
        }
        paths: list[Path] = []
        for name in sorted(payload.keys()):
            path = output_dir / name
            path.write_text(payload[name], encoding="utf-8")
            paths.append(path)
        return tuple(paths)

    def _write_canonical_json(self, *, path: Path, payload: object) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        return path

    def _sha256_path(self, path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _manifest_path_value(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.workspace_root))
        except ValueError:
            return str(path)

    def write_reports_with_artifact_manifest(
        self,
        *,
        result: ExperimentResult,
        adjustments: Sequence[RecommendedWeightAdjustment],
        output_dir: Path,
        deterministic_seed: str,
        schema_version: str = "1.0",
    ) -> tuple[tuple[Path, ...], Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build canonical underlying artifacts first.
        base_provenance = dict(result.provenance)
        dataset_manifest = {
            "dataset_id": base_provenance.get("dataset_id", "UNKNOWN"),
            "dataset_version": base_provenance.get("dataset_version", "1.0"),
            "date_range": base_provenance.get("date_range", "UNKNOWN"),
            "universe": base_provenance.get("universe", "UNKNOWN"),
            "survivorship_policy": base_provenance.get("survivorship_policy", "UNKNOWN"),
            "publication_lag_policy": base_provenance.get("publication_lag_policy", "UNKNOWN"),
        }
        hypothesis_artifact = {
            "hypothesis_id": base_provenance.get("hypothesis_id", "UNKNOWN"),
            "factors": [row.factor for row in result.feature_rankings],
            "data_classification": base_provenance.get("data_classification", "UNKNOWN"),
        }
        experiment_spec = {
            "experiment_id": result.experiment_id,
            "benchmark": base_provenance.get("benchmark", "UNKNOWN"),
            "sample_size": base_provenance.get("sample_size", "UNKNOWN"),
            "transaction_assumptions": base_provenance.get("transaction_assumptions", "UNKNOWN"),
            "validation_method": base_provenance.get("validation_method", "UNKNOWN"),
        }
        experiment_result_payload = {
            "experiment_id": result.experiment_id,
            "status": result.status.value,
            "metrics": asdict(result.metrics),
            "statistical_tests": asdict(result.statistical_tests),
            "overfitting_check": asdict(result.overfitting_check),
        }
        validation_result_payload = {
            "experiment_id": result.experiment_id,
            "out_of_sample_passed": bool(result.statistical_tests.out_of_sample_passed),
            "overfitting_passed": bool(result.overfitting_check.passed),
            "failed_checks": list(result.overfitting_check.reasons),
        }
        feature_rankings_payload = [asdict(row) for row in result.feature_rankings]
        interaction_rankings_payload = [asdict(row) for row in result.interaction_rankings]
        regime_analysis_payload = [asdict(row) for row in result.regime_breakdown]
        recommendations_payload = [asdict(row) for row in adjustments]

        underlying: dict[str, tuple[str, Path]] = {
            "dataset_manifest": ("dataset_manifest", self._write_canonical_json(path=output_dir / "dataset_manifest_v1.json", payload=dataset_manifest)),
            "hypothesis_artifact": ("hypothesis_artifact", self._write_canonical_json(path=output_dir / "hypothesis_artifact_v1.json", payload=hypothesis_artifact)),
            "experiment_spec": ("experiment_spec", self._write_canonical_json(path=output_dir / "experiment_spec_v1.json", payload=experiment_spec)),
            "experiment_result": ("experiment_result", self._write_canonical_json(path=output_dir / "experiment_result_v1.json", payload=experiment_result_payload)),
            "validation_result": ("validation_result", self._write_canonical_json(path=output_dir / "validation_result_v1.json", payload=validation_result_payload)),
            "feature_rankings": ("feature_rankings", self._write_canonical_json(path=output_dir / "feature_rankings_v1.json", payload=feature_rankings_payload)),
            "interaction_rankings": ("interaction_rankings", self._write_canonical_json(path=output_dir / "interaction_rankings_v1.json", payload=interaction_rankings_payload)),
            "regime_analysis": ("regime_analysis", self._write_canonical_json(path=output_dir / "regime_analysis_v1.json", payload=regime_analysis_payload)),
            "model_improvement_recommendations": (
                "model_improvement_recommendations",
                self._write_canonical_json(path=output_dir / "model_improvement_recommendations_v1.json", payload=recommendations_payload),
            ),
        }

        artifact_hashes = {key: self._sha256_path(path) for key, (_, path) in underlying.items()}
        artifact_hash_line = ", ".join(f"{k}={v}" for k, v in sorted(artifact_hashes.items()))

        # Generate reports with real underlying artifact hashes embedded.
        enriched_provenance = dict(base_provenance)
        enriched_provenance["artifact_hashes"] = artifact_hash_line
        enriched_result = ExperimentResult(
            experiment_id=result.experiment_id,
            metrics=result.metrics,
            statistical_tests=result.statistical_tests,
            overfitting_check=result.overfitting_check,
            feature_rankings=result.feature_rankings,
            interaction_rankings=result.interaction_rankings,
            regime_breakdown=result.regime_breakdown,
            cross_validation_folds=result.cross_validation_folds,
            status=result.status,
            provenance=enriched_provenance,
        )
        bundle = self.generate_reports(result=enriched_result, adjustments=adjustments)
        report_paths = self.write_reports(report_bundle=bundle, output_dir=output_dir)

        # Hash reports after they include underlying hashes.
        report_hashes = {path.name: self._sha256_path(path) for path in sorted(report_paths, key=lambda p: p.name)}

        manifest_rows: list[dict[str, str]] = []
        for key, (artifact_type, path) in sorted(underlying.items()):
            manifest_rows.append(
                {
                    "artifact_path": self._manifest_path_value(path),
                    "artifact_type": artifact_type,
                    "sha256": artifact_hashes[key],
                    "size": str(path.stat().st_size),
                    "schema_version": schema_version,
                    "experiment_id": result.experiment_id,
                    "generation_timestamp_policy": "deterministic-no-wall-clock",
                    "deterministic_seed": deterministic_seed,
                    "provenance": "phase4.reporting.pipeline",
                }
            )
        for path in sorted(report_paths, key=lambda p: p.name):
            manifest_rows.append(
                {
                    "artifact_path": self._manifest_path_value(path),
                    "artifact_type": "report",
                    "sha256": report_hashes[path.name],
                    "size": str(path.stat().st_size),
                    "schema_version": schema_version,
                    "experiment_id": result.experiment_id,
                    "generation_timestamp_policy": "deterministic-no-wall-clock",
                    "deterministic_seed": deterministic_seed,
                    "provenance": "phase4.reporting.pipeline",
                }
            )

        manifest_path = output_dir / "artifact_manifest_v1.json"
        self._write_canonical_json(path=manifest_path, payload={"artifacts": manifest_rows})
        return report_paths, manifest_path

    def write_validation_artifact(self, *, passed: bool, output_path: Path) -> None:
        artifact = {
            "milestone": "McLeodResearchLab_v1.0_Validated",
            "passed": bool(passed),
            "fail_closed": True,
            "production_updates_applied": False,
            "human_approval_required_for_weight_changes": True,
            "data_classification": "SYNTHETIC_VALIDATION_ONLY",
            "no_historical_alpha_conclusion": True,
            "no_production_weight_implication": True,
            "no_activation_implication": True,
            "no_live_trading_implication": True,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(artifact, sort_keys=True, indent=2), encoding="utf-8")
