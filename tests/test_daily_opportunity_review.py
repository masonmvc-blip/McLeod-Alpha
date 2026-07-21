import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from execution.opportunity_logger import log_evaluated_setups
import reports.daily_opportunity_review as dor


ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _sample_df():
    rows = [
        {"datetime": datetime(2026, 7, 17, 13, 56, tzinfo=UTC), "open": 600.0, "high": 600.2, "low": 599.8, "close": 600.1, "volume": 1000, "ema10": 600.0, "ema20": 599.9, "ema50": 599.7, "vwap": 599.9, "macd_hist": 0.01},
        {"datetime": datetime(2026, 7, 17, 13, 57, tzinfo=UTC), "open": 600.1, "high": 600.3, "low": 600.0, "close": 600.2, "volume": 1200, "ema10": 600.05, "ema20": 599.95, "ema50": 599.75, "vwap": 599.95, "macd_hist": 0.02},
        {"datetime": datetime(2026, 7, 17, 13, 58, tzinfo=UTC), "open": 600.2, "high": 600.4, "low": 600.1, "close": 600.3, "volume": 1400, "ema10": 600.1, "ema20": 600.0, "ema50": 599.8, "vwap": 600.0, "macd_hist": 0.03},
        {"datetime": datetime(2026, 7, 17, 13, 59, tzinfo=UTC), "open": 600.3, "high": 600.45, "low": 600.2, "close": 600.4, "volume": 1500, "ema10": 600.15, "ema20": 600.05, "ema50": 599.85, "vwap": 600.05, "macd_hist": 0.04},
        {"datetime": datetime(2026, 7, 17, 14, 0, tzinfo=UTC), "open": 600.4, "high": 600.6, "low": 600.3, "close": 600.5, "volume": 1600, "ema10": 600.2, "ema20": 600.1, "ema50": 599.9, "vwap": 600.1, "macd_hist": 0.05},
    ]
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["datetime"])
    return df


def test_logger_timestamps_are_eastern(tmp_path, monkeypatch):
    monkeypatch.setattr("execution.opportunity_logger.OPPORTUNITY_LOG_DIR", tmp_path)

    df = _sample_df()
    last = df.iloc[-1]
    prev = df.iloc[-2]

    log_evaluated_setups(
        last=last,
        prev=prev,
        df=df,
        regime="BULL_TREND",
        call_score=5,
        call_reasons=["bull_ema_stack", "ema10_rising"],
        put_score=1,
        put_reasons=["volume_weakening_bearish_move"],
        entry_threshold=5,
        allow_entry=True,
        in_position=False,
        in_market_hours=True,
        entered_call=True,
        entered_put=False,
        feature_payload={},
        selected_option_call={"symbol": "SPY_260717C00600000"},
        selected_option_put=None,
    )

    path = tmp_path / "opportunity_setups_2026-07-17.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    for row in lines:
        eval_dt = datetime.fromisoformat(row["evaluation_time_et"])
        candle_dt = datetime.fromisoformat(row["candle_time_et"])
        assert eval_dt.tzinfo is not None
        assert candle_dt.tzinfo is not None
        assert eval_dt.utcoffset().total_seconds() in {-4 * 3600, -5 * 3600}
        assert candle_dt.utcoffset().total_seconds() in {-4 * 3600, -5 * 3600}
        assert row["research"]["research_version"] == "market-state-adx-v1"
        assert row["research"]["market_state_model"] == "v1.0"
        assert row["research"]["feature_schema"] == "2026-07-adx-v1"
        assert len(row["research"]["feature_schema_hash"]) == 64
        assert len(row["research"]["feature_hash"]) == 64
        assert row["research"]["classification_confidence"] is None
        assert row["research"]["trend_state"]
        assert row["research"]["freshness_score"] is None
        assert row["research"]["research_engine_would_trade"] is None
        assert row["research"]["shadow_only"] is True
        assert row["research"]["promotion_eligible"] is False


def test_executed_and_rejected_included_once(tmp_path, monkeypatch):
    monkeypatch.setattr(dor, "OPPORTUNITY_LOG_DIR", tmp_path)
    monkeypatch.setattr(dor, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(dor, "SPY_HISTORY_PATH", tmp_path / "spy.csv")

    log_path = tmp_path / "opportunity_setups_2026-07-17.jsonl"
    payload = {
        "event_id": "2026-07-17T10:00:00-04:00|CALL",
        "evaluation_time_et": "2026-07-17T10:00:01-04:00",
        "candle_time_et": "2026-07-17T10:00:00-04:00",
        "direction": "CALL",
        "spy_price": 600.0,
        "entered": True,
        "rejected": False,
        "rejection_reason": None,
        "market_regime": "BULL_TREND",
        "positive_signals": ["bull_ema_stack"],
        "penalties": [],
    }
    log_path.write_text(json.dumps(payload) + "\n" + json.dumps(payload) + "\n" + json.dumps({
        **payload,
        "event_id": "2026-07-17T10:00:00-04:00|PUT",
        "direction": "PUT",
        "entered": False,
        "rejected": True,
        "rejection_reason": "Regime mismatch (BULL_TREND)",
    }) + "\n", encoding="utf-8")

    spy_csv = "datetime,open,high,low,close,volume\n2026-07-17T14:01:00+00:00,600,600.1,599.9,600.05,100\n"
    (tmp_path / "spy.csv").write_text(spy_csv, encoding="utf-8")

    paths = dor.build_daily_opportunity_review("2026-07-17")
    data = json.loads(paths.json.read_text(encoding="utf-8"))
    assert data["summary"]["total_evaluations"] == 2
    assert data["summary"]["trades_taken"] == 1
    assert data["summary"]["trades_rejected"] == 1


def test_post_rejection_tracking_uses_only_future_candles(tmp_path, monkeypatch):
    monkeypatch.setattr(dor, "OPPORTUNITY_LOG_DIR", tmp_path)
    monkeypatch.setattr(dor, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(dor, "SPY_HISTORY_PATH", tmp_path / "spy.csv")

    log_path = tmp_path / "opportunity_setups_2026-07-17.jsonl"
    log_path.write_text(json.dumps({
        "event_id": "2026-07-17T10:00:00-04:00|PUT",
        "evaluation_time_et": "2026-07-17T10:00:01-04:00",
        "candle_time_et": "2026-07-17T10:00:00-04:00",
        "direction": "PUT",
        "spy_price": 600.0,
        "entered": False,
        "rejected": True,
        "rejection_reason": "Regime mismatch",
        "market_regime": "BULL_TREND",
        "positive_signals": [],
        "penalties": [],
    }) + "\n", encoding="utf-8")

    # 09:59 ET candle has huge move and must be ignored; 10:01 ET is the first valid future candle.
    spy_csv = "\n".join([
        "datetime,open,high,low,close,volume",
        "2026-07-17T13:59:00+00:00,600,620,580,610,100",
        "2026-07-17T14:01:00+00:00,600,600.2,599.7,599.9,100",
        "2026-07-17T14:02:00+00:00,599.9,600.0,599.5,599.6,100",
    ])
    (tmp_path / "spy.csv").write_text(spy_csv, encoding="utf-8")

    paths = dor.build_daily_opportunity_review("2026-07-17")
    data = json.loads(paths.json.read_text(encoding="utf-8"))
    row = data["evaluated_setups"][0]
    tracking = row["post_rejection_tracking"]

    assert tracking["future_candles_used"] == 2
    assert tracking["max_favorable_spy_move"] < 5


def test_estimated_outcomes_are_labeled_estimates(tmp_path, monkeypatch):
    monkeypatch.setattr(dor, "OPPORTUNITY_LOG_DIR", tmp_path)
    monkeypatch.setattr(dor, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(dor, "SPY_HISTORY_PATH", tmp_path / "spy.csv")

    (tmp_path / "opportunity_setups_2026-07-17.jsonl").write_text(json.dumps({
        "event_id": "2026-07-17T10:00:00-04:00|CALL",
        "evaluation_time_et": "2026-07-17T10:00:01-04:00",
        "candle_time_et": "2026-07-17T10:00:00-04:00",
        "direction": "CALL",
        "spy_price": 600.0,
        "entered": False,
        "rejected": True,
        "rejection_reason": "CALL score below threshold by 1",
        "market_regime": "BULL_TREND",
        "positive_signals": [],
        "penalties": [],
    }) + "\n", encoding="utf-8")

    (tmp_path / "spy.csv").write_text(
        "datetime,open,high,low,close,volume\n"
        "2026-07-17T14:01:00+00:00,600,601,599.8,600.9,100\n",
        encoding="utf-8",
    )

    paths = dor.build_daily_opportunity_review("2026-07-17")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    outcome = payload["evaluated_setups"][0]["estimated_option_outcome"]
    assert outcome["is_estimate"] is True
    assert outcome["label"] == "estimated_from_spy_proxy"


def test_top_missed_opportunities_prioritize_near_misses_and_exclude_no_trade():
    events = [
        {
            "event_id": "near-miss", "entered": False, "direction": "CALL",
            "candle_time_et": "2026-07-17T10:00:00-04:00",
            "rejection_reason": "CALL score below threshold by 1",
            "market_regime": "BULL_TREND", "stage": 2, "cq": 2.9, "adx_14": 31.0,
            "estimated_option_outcome": {"estimated_option_mfe_pct": 8.0, "estimated_option_mae_pct": -1.0},
            "post_rejection_tracking": {"max_favorable_spy_move": 0.8},
        },
        {
            "event_id": "no-trade", "entered": False, "direction": "CALL",
            "candle_time_et": "2026-07-17T10:01:00-04:00",
            "rejection_reason": "CALL score below threshold by 1",
            "market_regime": "NO_TRADE",
            "estimated_option_outcome": {"estimated_option_mfe_pct": 30.0, "estimated_option_mae_pct": -1.0},
        },
        {
            "event_id": "qualified-skip", "entered": False, "direction": "PUT",
            "candle_time_et": "2026-07-17T10:02:00-04:00",
            "rejection_reason": "Qualified signal skipped: rate limit",
            "market_regime": "BEAR_TREND",
            "estimated_option_outcome": {"estimated_option_mfe_pct": 5.0, "estimated_option_mae_pct": -2.0},
        },
    ]

    top = dor._top_missed_opportunities(events)

    assert [row["event_id"] for row in top] == ["near-miss", "qualified-skip"]
    assert top[0]["research_rating"] == "research_candidate"
    assert top[0]["promotion_eligible"] is False
    assert top[0]["research_status"] == "exploratory_insufficient_sample"


def test_repeatable_near_miss_outranks_one_off_move_and_reports_regret():
    repeatable = [
        {
            "event_id": f"repeat-{index}", "entered": False, "direction": "CALL",
            "rejection_reason": "CALL score below threshold by 1", "market_regime": "BULL_TREND",
            "estimated_option_outcome": {"estimated_option_mfe_pct": 12.0, "estimated_option_mae_pct": -4.0},
        }
        for index in range(10)
    ]
    today = [
        {
            "event_id": "repeat-today", "entered": False, "direction": "CALL",
            "rejection_reason": "CALL score below threshold by 1", "market_regime": "BULL_TREND",
            "estimated_option_outcome": {"estimated_option_mfe_pct": 12.0, "estimated_option_mae_pct": -4.0},
        },
        {
            "event_id": "one-off", "entered": False, "direction": "PUT",
            "rejection_reason": "PUT score below threshold by 2", "market_regime": "BEAR_TREND",
            "estimated_option_outcome": {"estimated_option_mfe_pct": 30.0, "estimated_option_mae_pct": -4.0},
        },
    ]

    ranked = dor._top_missed_opportunities(today, repeatable + today)
    recurring = dor._recurring_near_misses(repeatable + today)

    assert ranked[0]["event_id"] == "repeat-today"
    assert ranked[0]["learning_value_components"]["pattern_repeatability"] == 40.0
    assert ranked[0]["learning_value_components"]["subsequent_opportunity"] == 12.0
    cohort = next(row for row in recurring if row["pattern"] == "CALL missed by 1 point")
    assert cohort["count"] == 11
    assert cohort["research_status"] == "candidate_for_validation"
    assert cohort["research_regret_pct"] == 12.0
    assert cohort["promotion_eligible"] is False


def test_not_entered_stage_pattern_normalizes_structured_stage():
    pattern = dor._near_miss_pattern(
        {"direction": "CALL", "stage": {"stage": 2, "label": "EARLY_CONTINUATION"}},
        "Not entered",
    )

    assert pattern == "Stage 2 Not Entered"


def test_live_decision_predicates_unchanged():
    source = Path("engine/brain/live_rules.py").read_text(encoding="utf-8")

    assert '"CALL": "BULL_TREND", "PUT": "BEAR_TREND"' in source
    assert "normalized_score >= LIVE_ENTRY_MIN_SCORE" in source
    assert "stop = entry - 0.75" in source
    assert "stop = entry + 0.75" in source
    assert "target = entry + 1.50" in source
    assert "target = entry - 1.50" in source
