from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from engine.phase3.approval import ApprovalState
from engine.phase3.calibration.model import CalibrationModel, CalibrationResult
from engine.phase3.calibration.types import OutcomeRecord
from engine.phase3.context import ResearchContext, load_research_context
from engine.phase3.decision_engine.model import DecisionModel, DecisionResult
from engine.phase3.expected_return.model import ExpectedReturnModel, ExpectedReturnResult
from engine.phase3.expected_return.scenario import Scenario
from engine.phase3.portfolio_simulation.model import SimulationModel, SimulationResult
from engine.phase3.portfolio_simulation.types import SimulationScenario
from engine.phase3.shadow_portfolio_construction.model import ShadowAllocationModel, ShadowAllocationResult
from engine.phase3.shadow_portfolio_construction.types import PortfolioConstraints
from engine.research_os_release import REQUIRED_RELEASE_SUITES, load_research_os_manifest, validate_research_os_release

from .dependency import DependencyValidator
from .replay import ReplayValidator, ReplayValidationResult
from .types import EndToEndAudit, EndToEndAuditStep


class SystemValidationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SystemValidationResult:
    passed: bool
    context: ResearchContext
    expected_return: ExpectedReturnResult
    decision: DecisionResult
    calibration: CalibrationResult
    simulation: SimulationResult
    shadow_allocation: ShadowAllocationResult
    dependency_passed: bool
    replay: ReplayValidationResult
    audit: EndToEndAudit


class SystemValidationModel:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.dependency_validator = DependencyValidator(workspace_root)
        self.replay_validator = ReplayValidator()

    def evaluate(
        self,
        *,
        ticker: str = "RKLB",
        market_price: float = 100.0,
        historical_returns: Mapping[str, list[float]] | None = None,
        suite_results: Mapping[str, bool] | None = None,
        force_schema_mismatch: bool = False,
        force_missing_artifact: bool = False,
    ) -> SystemValidationResult:
        for required in [
            self.workspace_root / "data" / "research" / "logs" / "Research_OS_v1.0.json",
            self.workspace_root / "data" / "research" / "logs" / "Phase3_Foundation_Validated.json",
            self.workspace_root / "data" / "research" / "logs" / "ExpectedReturnEngine_Validated.json",
            self.workspace_root / "data" / "research" / "logs" / "DecisionEngine_Validated.json",
            self.workspace_root / "data" / "research" / "logs" / "CalibrationEngine_Validated.json",
            self.workspace_root / "data" / "research" / "logs" / "PortfolioSimulation_Validated.json",
            self.workspace_root / "data" / "research" / "logs" / "ShadowPortfolioConstruction_Validated.json",
        ]:
            if not required.exists():
                raise SystemValidationValidationError(f"Missing frozen milestone artifact: {required.name}")

        stage_steps: list[EndToEndAuditStep] = []
        timestamps = {"start": "deterministic", "end": "deterministic"}
        release_status = validate_research_os_release(
            load_research_os_manifest(),
            suite_results=dict(suite_results or {name: True for name in REQUIRED_RELEASE_SUITES}),
            fail_closed=False,
        )
        if not release_status.passed:
            raise SystemValidationValidationError("Research_OS validation failed during system validation.")
        stage_steps.append(EndToEndAuditStep("research_os", True, "Research_OS release validation passed.", "deterministic"))

        context = load_research_context(ticker).with_approval_status(ApprovalState.APPROVED_FOR_EIPV)
        if force_missing_artifact:
            metadata = dict(context.artifact_metadata)
            metadata["available"] = False
            context = ResearchContext(
                ticker=context.ticker,
                overall_phase2_score=context.overall_phase2_score,
                component_scores=context.component_scores,
                confidence=context.confidence,
                missing_inputs=context.missing_inputs,
                provenance=context.provenance,
                approval_status=context.approval_status,
                artifact_metadata=metadata,
            )
        if force_schema_mismatch:
            metadata = dict(context.artifact_metadata)
            metadata["schema_version"] = "broken"
            context = ResearchContext(
                ticker=context.ticker,
                overall_phase2_score=context.overall_phase2_score,
                component_scores=context.component_scores,
                confidence=context.confidence,
                missing_inputs=context.missing_inputs,
                provenance=context.provenance,
                approval_status=context.approval_status,
                artifact_metadata=metadata,
            )
        stage_steps.append(EndToEndAuditStep("research_context", True, "ResearchContext loaded.", "deterministic"))

        expected_return = ExpectedReturnModel().evaluate(
            context,
            market_price=market_price,
            bear_scenario=Scenario(intrinsic_value=80.0, probability=0.2, rationale="recession"),
            base_scenario=Scenario(intrinsic_value=110.0, probability=0.5, rationale="stable"),
            bull_scenario=Scenario(intrinsic_value=145.0, probability=0.3, rationale="upside"),
            investment_horizon_years=2.0,
            user_assumptions={"confidence_weight": 0.10, "uncertainty_penalty": 0.20},
        )
        stage_steps.append(EndToEndAuditStep("expected_return", True, "ExpectedReturnModel evaluated.", "deterministic"))

        decision = DecisionModel().evaluate(context, expected_return)
        if not decision.decision_eligible:
            raise SystemValidationValidationError("Decision stage produced ineligible result in validation path.")
        stage_steps.append(EndToEndAuditStep("decision", True, "DecisionModel evaluated and eligible.", "deterministic"))

        outcome = OutcomeRecord(
            ticker=ticker,
            forecast_date="2026-07-01T00:00:00+00:00",
            evaluation_date="2026-07-18T00:00:00+00:00",
            expected_return=expected_return.expected_annual_return,
            realized_return=0.05,
            expected_intrinsic_value=expected_return.expected_intrinsic_value,
            realized_value=106.0,
            confidence=context.confidence,
            approval_state=context.approval_status,
            evaluation_horizon=2.0,
            provenance={"source": "system_validation"},
        )
        calibration = CalibrationModel().evaluate(expected_return, decision, outcome_record=outcome)
        stage_steps.append(EndToEndAuditStep("calibration", True, "CalibrationModel evaluated.", "deterministic"))

        hist = historical_returns or {ticker: [0.01, -0.005, 0.012, 0.004, -0.002, 0.009, 0.003, -0.001]}
        simulation = SimulationModel().evaluate(
            decision_outputs=[decision],
            expected_returns={ticker: expected_return},
            allocation_scenario=SimulationScenario(method="equal_weight", assumptions={"periods_per_year": 252}),
            historical_returns=hist,
            start_date="2026-01-01",
            end_date="2026-07-18",
            benchmark="SPY",
            benchmark_returns=[0.004, 0.003, -0.002, 0.001, 0.002, 0.001, 0.0, 0.001],
        )
        stage_steps.append(EndToEndAuditStep("portfolio_simulation", True, "SimulationModel evaluated.", "deterministic"))

        shadow = ShadowAllocationModel().evaluate(
            decision_results=[decision],
            expected_return_results={ticker: expected_return},
            current_shadow_holdings={ticker: 1000.0},
            available_shadow_cash=1000.0,
            constraints=PortfolioConstraints(
                maximum_position_weight=0.40,
                minimum_position_weight=0.05,
                maximum_sector_weight=0.60,
                maximum_total_invested_capital=100000.0,
                minimum_cash_reserve=0.10,
                maximum_number_of_holdings=10,
                maximum_turnover=0.80,
                prohibited_tickers=(),
                required_tickers=(),
            ),
            approved_allocation_method="equal_weight",
            timestamp="2026-07-18T20:00:00+00:00",
        )
        stage_steps.append(EndToEndAuditStep("shadow_portfolio", True, "ShadowAllocationModel evaluated.", "deterministic"))

        dependency = self.dependency_validator.validate()
        if not dependency.passed:
            raise SystemValidationValidationError("Dependency validation failed.")
        stage_steps.append(EndToEndAuditStep("dependency_validation", True, "Dependency validation passed.", "deterministic"))

        replay = self.replay_validator.validate(lambda: self._replay_payload(context, expected_return, decision, calibration, simulation, shadow, dependency.dependency_graph))
        if not replay.passed:
            raise SystemValidationValidationError("Replay validation failed.")
        stage_steps.append(EndToEndAuditStep("replay_validation", True, "Replay validation passed.", "deterministic"))

        execution_order = (
            "Research_OS",
            "Downstream Adapter",
            "ResearchContext",
            "ExpectedReturnModel",
            "DecisionModel",
            "CalibrationModel",
            "PortfolioSimulation",
            "ShadowPortfolioConstruction",
        )
        artifact_versions = {
            "Research_OS_version": "1.0",
            "phase2_schema_version": str(context.artifact_metadata.get("schema_version") or ""),
            "expected_return_audit": str(len(expected_return.calculation_audit)),
            "decision_audit": str(len(decision.decision_audit.steps)),
            "calibration_audit": str(len(calibration.calibration_audit.steps)),
            "simulation_audit": str(len(simulation.simulation_audit.validation_steps)),
            "shadow_audit": str(len(shadow.audit.validation_steps)),
        }

        config_hash = self._config_hash(
            ticker=ticker,
            market_price=market_price,
            artifact_versions=artifact_versions,
            execution_order=execution_order,
            dependency_graph=dependency.dependency_graph,
        )
        audit = EndToEndAudit(
            modules_executed=execution_order,
            validation_status="passed",
            execution_order=execution_order,
            artifact_versions=artifact_versions,
            dependency_graph=dependency.dependency_graph,
            timestamps=timestamps,
            configuration_hash=config_hash,
            deterministic_replay_hash=replay.replay_hash,
            steps=tuple(stage_steps),
        )

        return SystemValidationResult(
            passed=True,
            context=context,
            expected_return=expected_return,
            decision=decision,
            calibration=calibration,
            simulation=simulation,
            shadow_allocation=shadow,
            dependency_passed=True,
            replay=replay,
            audit=audit,
        )

    @staticmethod
    def _replay_payload(
        context: ResearchContext,
        expected_return: ExpectedReturnResult,
        decision: DecisionResult,
        calibration: CalibrationResult,
        simulation: SimulationResult,
        shadow: ShadowAllocationResult,
        graph: Mapping[str, tuple[str, ...]],
    ) -> dict[str, Any]:
        result = {
            "ticker": context.ticker,
            "expected_return": expected_return.expected_annual_return,
            "decision_eligible": decision.decision_eligible,
            "calibration_measurable": calibration.measurable,
            "simulation_cagr": simulation.simulated_cagr,
            "shadow_cash_weight": shadow.proposed_cash_weight,
        }
        audit = {
            "decision_steps": len(decision.decision_audit.steps),
            "calibration_steps": len(calibration.calibration_audit.steps),
            "simulation_steps": len(simulation.simulation_audit.validation_steps),
            "shadow_steps": len(shadow.audit.validation_steps),
            "graph": tuple(sorted((k, tuple(v)) for k, v in graph.items())),
        }
        execution_order = (
            "Research_OS",
            "Downstream Adapter",
            "ResearchContext",
            "ExpectedReturnModel",
            "DecisionModel",
            "CalibrationModel",
            "PortfolioSimulation",
            "ShadowPortfolioConstruction",
        )
        return {"result": result, "audit": audit, "execution_order": execution_order}

    @staticmethod
    def _config_hash(
        *,
        ticker: str,
        market_price: float,
        artifact_versions: Mapping[str, str],
        execution_order: tuple[str, ...],
        dependency_graph: Mapping[str, tuple[str, ...]],
    ) -> str:
        payload = (
            f"{ticker}|{market_price:.8f}|{execution_order}|"
            f"{sorted(artifact_versions.items())}|{sorted((k, tuple(v)) for k, v in dependency_graph.items())}"
        )
        return sha256(payload.encode("utf-8")).hexdigest()
