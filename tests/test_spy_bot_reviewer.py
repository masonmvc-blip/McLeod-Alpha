import json
import csv
from datetime import datetime, timedelta, timezone

from spy_bot_reviewer import SpyBotReviewer
from spy_bot_reviewer.patterns import PatternDiscoveryEngine
from spy_bot_reviewer.hypotheses import HypothesisRegistry
from spy_bot_reviewer.market_memory import MarketMemoryEngine
from spy_bot_reviewer.governance import ResearchGovernanceEngine
from spy_bot_reviewer.experiments import ExperimentFramework


def _write_export(tmp_path):
    export = tmp_path / "data" / "reports" / "trade_logs" / "daily_trade_review_data_2026-07-20.json"
    export.parent.mkdir(parents=True)
    entry = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
    export.write_text(json.dumps({
        "summary": {"total_trades": 2},
        "trades": [
            {"trade_id": 1, "option_symbol": "SPY 260720C00600000", "entry_time": entry.isoformat(), "exit_time": (entry + timedelta(minutes=20)).isoformat(), "dollar_pnl": 15, "market_regime": "TREND"},
            {"trade_id": 2, "option_symbol": "SPY 260720P00590000", "entry_time": (entry + timedelta(minutes=30)).isoformat(), "exit_time": (entry + timedelta(minutes=40)).isoformat(), "dollar_pnl": -5, "entry_score": 72},
        ],
    }))
    return export


def _write_candles(tmp_path):
    path = tmp_path / "data" / "spy_1min_history.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["datetime", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for offset in range(120):
            price = 600 + offset * 0.01
            writer.writerow({"datetime": (start + timedelta(minutes=offset)).isoformat(), "open": price, "high": price + .03, "low": price - .03, "close": price + .01, "volume": 1000})


def test_session_review_is_chained_and_collects_spy_trade_evidence(tmp_path):
    reviewer = SpyBotReviewer(tmp_path)
    export = _write_export(tmp_path)
    _write_candles(tmp_path)

    first = reviewer.run_session_review("2026-07-20", export)
    second = reviewer.run_session_review("2026-07-20", export)

    assert first["record_hash"]
    assert second["previous_record_hash"] == first["record_hash"]
    assert len(second["evidence"]["trades"]) == 2
    assert second["analysis"]["provider"] == "deterministic_fallback"
    replay = reviewer.replay_bundle("1")
    assert replay["bundle_hash"]
    assert replay["candles"]["1m"]
    assert replay["candles"]["5m"]
    assert replay["candles"]["15m"]
    assert set(replay["scores"]) >= {"Setup Quality", "Entry Timing", "Exit Timing", "Risk Management", "Execution Quality"}


def test_rule_promotion_requires_a_positive_expectancy_increase(tmp_path):
    reviewer = SpyBotReviewer(tmp_path)
    outcomes = [{"pnl": 10, "rule_eligible": True}] * 20 + [{"pnl": -10, "rule_eligible": False}] * 20

    result = reviewer.validate_rule("score-floor", "Require an entry score of at least 70.", outcomes)

    assert result["status"] == "Validated"
    assert result["promotion"]["automatic_live_deployment"] is False
    assert result["expectancy_improvement"] > 0


def test_counterfactuals_require_many_trades_before_rule_validation(tmp_path):
    reviewer = SpyBotReviewer(tmp_path)
    reviewer.replay_dir.mkdir(parents=True)
    for index in range(20):
        (reviewer.replay_dir / f"{index}.json").write_text(json.dumps({
            "alternative_outcomes": {
                "actual": {"pnl": 1},
                "alternatives": [{"name": "Technical EMA20 exit", "comparison": "alternative", "pnl": 2}],
            },
        }))

    summary = reviewer.counterfactual_summary()

    improvement = summary["improvements"][0]
    assert improvement["status"] == "Candidate for Rule Validation"
    assert improvement["trades_tested"] == 20
    assert improvement["automatic_live_deployment"] is False


def test_pattern_discovery_snapshots_are_immutable_and_advisory_only(tmp_path):
    bundles = [{
        "trade": {"market_regime": "TREND", "direction": "CALL", "entry_time": "2026-07-20T14:00:00+00:00", "entry_score": 80},
        "candles": {"1m": [{"open": 100, "high": 101, "low": 99.9, "close": 100.5, "ema10": 100.4, "ema20": 100.1, "vwap": 100.2, "rsi": 60, "macd": 0.2}]},
        "execution": {"confidence_score": 80},
        "scores": {"Setup Quality": 80},
        "alternative_outcomes": {"actual": {"pnl": 2, "mae_pct": 0.1, "mfe_pct": 0.5, "hold_minutes": 5, "risk_adjusted_return": 2}},
    } for _ in range(10)]

    engine = PatternDiscoveryEngine(tmp_path)
    snapshot = engine.discover(bundles)

    assert snapshot["snapshot_hash"]
    assert snapshot["patterns"]
    assert snapshot["policy"]["automatic_live_deployment"] is False
    assert engine.latest()["snapshot_hash"] == snapshot["snapshot_hash"]


def test_hypothesis_registry_updates_evidence_without_auto_promotion(tmp_path):
    registry = HypothesisRegistry(tmp_path)
    created = registry.ingest(
        source="counterfactual_analyzer",
        proposal="Evaluate an EMA20 exit.",
        originating_evidence={"expectancy_improvement": 1.2},
        expected_improvement=1.2,
        minimum_sample_size=2,
        confidence_target=0.5,
        reviewer_version="test",
    )

    registry.refresh_evidence([
        {"trade_id": "1", "alternative_outcomes": {"actual": {"pnl": 1}}},
        {"trade_id": "2", "alternative_outcomes": {"actual": {"pnl": 1}}},
    ], "test")
    current = registry.current()[created["hypothesis_id"]]

    assert current["status"] == "Ready for Validation"
    assert current["previous_revision_hash"]
    promoted = registry.manual_promote(created["hypothesis_id"], "test")
    assert promoted["status"] == "Validating"
    assert promoted["decision"]["automatic"] is False


def test_market_memory_retrieves_prior_pre_entry_analog(tmp_path):
    engine = MarketMemoryEngine(tmp_path)

    def bundle(day, trade_id):
        return {
            "trade_id": trade_id,
            "trade": {"trade_id": trade_id, "entry_time": f"{day}T14:00:00+00:00", "exit_time": f"{day}T14:02:00+00:00", "market_regime": "TREND", "entry_score": 80},
            "candles": {"1m": [
                {"time": f"{day}T13:59:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 50000, "ema10": 100.4, "ema20": 100.2, "vwap": 100.3, "rsi": 60, "macd": 0.2},
                {"time": f"{day}T14:00:00+00:00", "open": 100.5, "high": 101, "low": 100, "close": 100.7, "volume": 50000, "ema10": 100.5, "ema20": 100.3, "vwap": 100.4, "rsi": 62, "macd": 0.3},
                {"time": f"{day}T14:03:00+00:00", "open": 100.7, "high": 101, "low": 100, "close": 100.8, "volume": 50000, "ema10": 100.6, "ema20": 100.4, "vwap": 100.5, "rsi": 63, "macd": 0.3},
            ]},
            "execution": {"confidence_score": 80},
            "alternative_outcomes": {"actual": {"pnl": 2}, "alternatives": [{"name": "EMA exit", "delta_pnl": 1}]},
        }

    engine.capture_session("2026-07-17", [bundle("2026-07-17", "one")], ["hyp-one"])
    current = engine.capture_session("2026-07-20", [bundle("2026-07-20", "two")], ["hyp-two"])

    assert current["record_hash"]
    assert current["analogs"][0]["trading_date"] == "2026-07-17"
    assert current["analogs"][0]["active_hypothesis_ids"] == ["hyp-one"]
    assert current["feature_schema_version"] == "market-context-features.v1"


def test_research_governance_tracks_lifecycle_and_advisory_boundary(tmp_path):
    (tmp_path / "hypothesis_history.jsonl").write_text(json.dumps({
        "hypothesis_id": "hyp-1",
        "source": "counterfactual_analyzer",
        "proposal": "Evaluate an EMA20 exit.",
        "status": "Ready for Validation",
        "created_at": "2026-07-01T00:00:00+00:00",
        "expected_improvement": 1.2,
        "supporting_trade_ids": ["1"],
        "conflicting_trade_ids": [],
        "reviewer_version": "test",
    }) + "\n")
    (tmp_path / "rule_validation_history.jsonl").write_text(json.dumps({
        "rule_id": "hyp-1", "status": "Validated", "expectancy_improvement": 1.2,
    }) + "\n")

    snapshot = ResearchGovernanceEngine(tmp_path).snapshot()

    lifecycle = snapshot["recommendation_lifecycles"][0]
    assert lifecycle["advanced_through_hypothesis_lab"] is True
    assert lifecycle["advanced_through_rule_validation"] is True
    assert lifecycle["adopted"] is False
    assert snapshot["dependency_graph"]["edges"]
    assert snapshot["advisory_only"] is True
    assert snapshot["snapshot_hash"]


def test_experiment_framework_creates_replay_only_protocol_with_provenance(tmp_path):
    framework = ExperimentFramework(tmp_path)
    experiments = framework.sync(
        {"hyp-1": {"hypothesis_id": "hyp-1", "status": "Ready for Validation", "expected_improvement": 1, "minimum_sample_size": 2, "supporting_trade_ids": ["1"]}},
        [
            {"trade_id": "1", "alternative_outcomes": {"actual": {"pnl": 2}}},
            {"trade_id": "2", "alternative_outcomes": {"actual": {"pnl": -1}}},
        ],
        {"reviewer_version": "reviewer-v1", "prompt_version": "prompt-v1", "market_memory_version": "memory-v1"},
    )

    experiment = experiments[0]
    assert experiment["mode"] == "REPLAY_ONLY"
    assert experiment["protocol"]["sequential_testing"]
    assert experiment["interim"]["confidence_interval"]
    assert experiment["provenance"]["prompt_version"] == "prompt-v1"
    assert experiment["manual_approval_required"] is True
    assert experiment["live_engine_isolated"] is True