from __future__ import annotations

import json

import pandas as pd

from engine.brain import Brain
from execution.opportunity_logger import _adx_metrics, log_evaluated_setups


def _completed_candles(count: int = 32) -> pd.DataFrame:
    index = pd.date_range("2026-07-21 13:30:00+00:00", periods=count, freq="min")
    rows = []
    for position in range(count):
        close = 100.0 + position
        rows.append({
            "open": close - 0.25,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0,
            "ema10": close - 0.2,
            "ema20": close - 0.4,
            "ema50": close - 0.6,
            "vwap": close - 0.3,
            "macd_hist": position * 0.01,
        })
    return pd.DataFrame(rows, index=index)


def test_wilder_adx_uses_completed_candles_and_reports_directional_values():
    metrics = _adx_metrics(_completed_candles())

    assert metrics["adx_14"] == 100.0
    assert metrics["plus_di_14"] == 50.0
    assert metrics["minus_di_14"] == 0.0
    assert metrics["adx_slope_1"] == 0.0
    assert metrics["adx_trend"] == "FLAT"


def test_adx_telemetry_is_serialized_into_immutable_opportunity_records(tmp_path, monkeypatch):
    monkeypatch.setattr("execution.opportunity_logger.OPPORTUNITY_LOG_DIR", tmp_path)
    frame = _completed_candles()

    log_evaluated_setups(
        last=frame.iloc[-1],
        prev=frame.iloc[-2],
        df=frame,
        regime="BULL_TREND",
        call_score=5,
        call_reasons=["bull_ema_stack"],
        put_score=0,
        put_reasons=[],
        entry_threshold=5,
        allow_entry=True,
        in_position=False,
        in_market_hours=True,
        entered_call=True,
        entered_put=False,
        feature_payload={},
        selected_option_call={"symbol": "SPY_260721C00600000"},
    )

    path = tmp_path / "opportunity_setups_2026-07-21.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for record in records:
        assert record["adx_14"] == 100.0
        assert record["plus_di_14"] == 50.0
        assert record["minus_di_14"] == 0.0
        assert record["adx_trend"] == "FLAT"
        assert len(record["research"]["feature_hash"]) == 64
        assert record["research"]["shadow_only"] is True
        assert record["research"]["promotion_eligible"] is False


def test_adx_telemetry_does_not_change_live_entry_decision():
    frame = _completed_candles()
    brain = Brain()

    before = brain.evaluate_entry(frame.iloc[-1], frame.iloc[-2], frame)
    _adx_metrics(frame)
    after = brain.evaluate_entry(frame.iloc[-1], frame.iloc[-2], frame)

    assert after == before