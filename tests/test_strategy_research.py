from execution.strategy_research import StrategyResearchStore, analyze_completed_trade, classify_trend_strength


def _trade():
    return {
        "entry_time": "2026-07-23T10:00:00-04:00", "direction": "CALL", "option_symbol": "SPY_TEST",
        "option_entry": 5.0, "option_exit": 5.5, "option_quantity": 1, "option_pnl_pct": 10.0,
        "option_high_since_entry": 6.0, "option_low_since_entry": 4.5, "mfe_pct": 20.0, "mae_pct": -10.0,
        "exit_efficiency_pct": 66.6667, "exit_reason": "TARGET_HIT", "broker_entry_order_id": "entry-1", "broker_exit_order_id": "exit-1",
        "entry_diagnostic_snapshot": '{"confidence_score": 4, "close": 101, "vwap": 100, "ema10": 101, "ema20": 100, "ema50": 99, "ema10_slope": 0.2, "macd_histogram": 0.3, "rsi": 65, "volume_ratio": 1.5, "setup_type": "BREAKOUT", "regime": "BULL_TREND"}',
        "exit_diagnostic_snapshot": '{"reason": "TARGET_HIT"}',
    }


def test_trend_classifier_uses_objective_features():
    assert classify_trend_strength({"close": 101, "vwap": 100, "ema10": 101, "ema20": 100, "ema50": 99, "ema10_slope": 0.1, "macd_histogram": 0.2, "rsi": 65, "volume_ratio": 1.3}) == "EXCEPTIONAL_TREND"


def test_completed_trade_analysis_keeps_scores_independent_and_persists(tmp_path):
    analysis = analyze_completed_trade(_trade(), store=StrategyResearchStore(tmp_path / "research.db"))
    assert analysis["research_only"] is True
    assert analysis["outcome_pct"] == 10.0
    assert set(analysis["scores"]) == {"setup_quality_score", "execution_quality_score", "exit_quality_score", "decision_quality_score"}
    assert analysis["exit_simulations"]["CURRENT_EXIT"]["return_pct"] == 10.0
    assert analysis["exit_simulations"]["EMA10_TRAILING"]["status"] == "UNAVAILABLE_EVIDENCE"
    assert analysis["promotion_status"] == "RESEARCH_ONLY_INSUFFICIENT_SAMPLE"


def test_expectancy_is_grouped_without_production_recommendations(tmp_path):
    store = StrategyResearchStore(tmp_path / "research.db")
    analyze_completed_trade(_trade(), store=store)
    expectancy = store.expectancy()
    assert expectancy["trend_strength"]["EXCEPTIONAL_TREND"] == {"count": 1, "expectancy_pct": 10.0, "win_rate_pct": 100.0}
    assert expectancy["setup_type"]["BREAKOUT"]["count"] == 1
    assert expectancy["time_of_day"]["10:00"]["count"] == 1
    assert expectancy["checklist_score"]["4.0"]["count"] == 1
    assert expectancy["market_regime"]["BULL_TREND"]["count"] == 1
    assert expectancy["exit_strategy"]["CURRENT_EXIT"]["count"] == 1