from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from engine.phase3.paper_portfolio_engine import PaperPortfolioEngine, PaperPortfolioEngineValidationError
from engine.phase3.paper_portfolio_governance import (
    PaperPortfolioState,
    PaperRecommendationModel,
    PaperRecommendationPolicy,
    PaperRecommendationStatus,
)
from engine.phase3.system_validation import SystemValidationModel


REPO_ROOT = Path(__file__).resolve().parent.parent

FROZEN_HASHES = {
    "config/research_os_manifest.json": "8133e50ecfad9dc31fc40d237c4409c4ca9573936603008b9f7ca30e3939a473",
    "engine/phase3/context.py": "2099134c8afee427adeb6b291b5f4e10c6b9f0fae9ca4313feb6018297e4c3f1",
    "engine/phase3/expected_return/model.py": "8e0d2b399872c6910bb242ccd204c3687cd7e817cc5138462d82981e1b73ceeb",
    "engine/phase3/decision_engine/model.py": "15f7a92d288314afbfcd1a2d19d1c1484bcd88beece2f8ce7aff4c3ead479beb",
    "engine/phase3/calibration/model.py": "e5977219a3abf15b34e69de0ceef05d6dfccae566934cafb77dd88156c1be367",
    "engine/phase3/portfolio_simulation/model.py": "a4565433daf6f3aa8a2673bd493f7265462109f93890b9f0c48b9965d213d385",
    "engine/phase3/shadow_portfolio_construction/model.py": "43d39d2fec949b6a6060741890e703f19341b2bce63ddce8bd6b481c37c9f53d",
    "engine/phase3/system_validation/model.py": "66b02a55a1cacf154035d9f9454eb4dc5a4c88836c525a49a68cd4de424da3ab",
    "engine/research_os_release.py": "bebb46337f73450af766b325eb6052a5a5db2276926e5166271b0be774f20a35",
    "engine/phase2_downstream.py": "7d25d7aa24be4177118ac41e209fc173e5e5c20607052a0ce4522352ad41804b",
    "engine/portfolio_engine.py": "4d39683c3a0fee762bf028f748216388aef5b68ed3b5ac149478f6e2f8afb63b",
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _approved_governance_records():
    validation = SystemValidationModel(REPO_ROOT).evaluate()
    governance_model = PaperRecommendationModel()
    base_policy = PaperRecommendationPolicy.default()
    policy = PaperRecommendationPolicy(
        **{
            **base_policy.__dict__,
            "maximum_position_weight": 1.0,
            "maximum_sector_weight": 1.0,
            "maximum_portfolio_turnover": 1.0,
            "minimum_cash_reserve": 0.0,
            "shadow_allocation_requirements": ("WEIGHTS_RECONCILE",),
        }
    )
    state = PaperPortfolioState(
        as_of_timestamp="2026-07-18T23:00:00+00:00",
        paper_cash=1000.0,
        paper_holdings={validation.decision.ticker: 1000.0},
        paper_weights={validation.decision.ticker: 0.5},
        total_paper_value=2000.0,
        provenance={"source": "paper_portfolio_engine_test"},
        version="1.0",
    )
    governance = governance_model.evaluate(
        decision_results=(validation.decision,),
        expected_return_results={validation.expected_return.ticker: validation.expected_return},
        calibration_results={validation.calibration.ticker: validation.calibration},
        simulation_result=validation.simulation,
        shadow_allocation_result=validation.shadow_allocation,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals={validation.decision.ticker: policy.required_approvals},
        as_of_timestamp="2026-07-18T23:00:00+00:00",
    )
    return governance.recommendation_records, state, policy


def test_engine_boundary_integrity() -> None:
    forbidden_import_prefixes = (
        "engine.research_phase1",
        "engine.phase2_research",
        "engine.phase2_downstream",
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
    )
    forbidden_raw_tokens = (
        "phase2_artifact.json",
        "phase2_review.md",
        "read_text(",
        "json.loads(path.read_text",
        "write_text(",
        "write_bytes(",
        "to_csv(",
        "to_json(",
    )

    for path in (REPO_ROOT / "engine" / "phase3" / "paper_portfolio_engine").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(alias.name.startswith(prefix) for prefix in forbidden_import_prefixes)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(node.module.startswith(prefix) for prefix in forbidden_import_prefixes)
        for token in forbidden_raw_tokens:
            assert token not in source


def test_deterministic_fills_and_transaction_ids_and_snapshots() -> None:
    records, state, policy = _approved_governance_records()
    engine = PaperPortfolioEngine()
    ticker = records[0].ticker
    prices = {ticker: {"2026-07-18T23:00:00+00:00": 100.0, "default": 100.0}}
    benchmark = {"start": 100.0, "end": 101.0}

    first = engine.evaluate(
        recommendation_records=records,
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices=prices,
        benchmark_prices=benchmark,
        as_of_timestamp="2026-07-18T23:00:00+00:00",
    )
    second = engine.evaluate(
        recommendation_records=records,
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices=prices,
        benchmark_prices=benchmark,
        as_of_timestamp="2026-07-18T23:00:00+00:00",
    )

    assert first == second
    assert [tx.transaction_id for tx in first.simulated_fills] == [tx.transaction_id for tx in second.simulated_fills]
    assert first.performance_snapshot == second.performance_snapshot


def test_immutability_and_reconciliation() -> None:
    records, state, policy = _approved_governance_records()
    ticker = records[0].ticker
    result = PaperPortfolioEngine().evaluate(
        recommendation_records=records,
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices={ticker: {"2026-07-18T23:00:00+00:00": 100.0}},
        benchmark_prices={"start": 100.0, "end": 101.0},
        as_of_timestamp="2026-07-18T23:00:00+00:00",
    )

    with pytest.raises(AttributeError):
        result.transaction_history.append(None)  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        result.positions[0].weight = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.performance_snapshot.nav = 0.0  # type: ignore[misc]

    total = sum(result.updated_state.paper_weights.values()) + (result.updated_state.paper_cash / result.updated_state.total_paper_value)
    assert abs(total - 1.0) <= 1e-8


def test_blocked_and_expired_recommendations_never_execute() -> None:
    records, state, policy = _approved_governance_records()
    ticker = records[0].ticker

    blocked = records[0].__class__(
        **{**records[0].__dict__, "status": PaperRecommendationStatus.BLOCKED, "blocking_reasons": ("POLICY",)}
    )
    expired = records[0].__class__(
        **{**records[0].__dict__, "status": PaperRecommendationStatus.EXPIRED, "blocking_reasons": ("STALE",)}
    )

    engine = PaperPortfolioEngine()
    blocked_result = engine.evaluate(
        recommendation_records=(blocked,),
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices={ticker: {"2026-07-18T23:00:00+00:00": 100.0}},
        benchmark_prices={"start": 100.0, "end": 101.0},
        as_of_timestamp="2026-07-18T23:00:00+00:00",
    )
    expired_result = engine.evaluate(
        recommendation_records=(expired,),
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices={ticker: {"2026-07-18T23:00:00+00:00": 100.0}},
        benchmark_prices={"start": 100.0, "end": 101.0},
        as_of_timestamp="2026-07-18T23:00:00+00:00",
    )

    assert not blocked_result.simulated_fills
    assert not expired_result.simulated_fills


def test_fail_closed_conditions() -> None:
    records, state, policy = _approved_governance_records()
    ticker = records[0].ticker
    engine = PaperPortfolioEngine()

    with pytest.raises(PaperPortfolioEngineValidationError):
        engine.evaluate(
            recommendation_records=records,
            paper_portfolio_state=state,
            policy=policy,
            historical_market_prices={},
            benchmark_prices={"start": 100.0, "end": 101.0},
            as_of_timestamp="2026-07-18T23:00:00+00:00",
        )

    with pytest.raises(PaperPortfolioEngineValidationError):
        engine.evaluate(
            recommendation_records=records,
            paper_portfolio_state=state,
            policy=policy,
            historical_market_prices={ticker: {"2026-07-18T23:00:00+00:00": 100.0}},
            benchmark_prices={"start": 100.0, "end": 101.0},
            as_of_timestamp="2026-07-18T23:00:00+00:00",
            broker_access_attempted=True,
        )


def test_benchmark_and_audit_continuity_and_frozen_hashes() -> None:
    records, state, policy = _approved_governance_records()
    ticker = records[0].ticker
    result = PaperPortfolioEngine().evaluate(
        recommendation_records=records,
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices={ticker: {"2026-07-18T23:00:00+00:00": 100.0}},
        benchmark_prices={"start": 100.0, "end": 101.0},
        as_of_timestamp="2026-07-18T23:00:00+00:00",
    )

    assert abs(result.benchmark_comparison["benchmark_return"] - 0.01) <= 1e-12
    assert result.portfolio_audit.configuration_hash
    assert result.portfolio_audit.input_hashes
    assert result.portfolio_audit.validation_steps

    actual = {path: _sha(REPO_ROOT / path) for path in FROZEN_HASHES}
    assert actual == FROZEN_HASHES
