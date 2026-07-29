from reports.market_trend_shadow_report import (
    build_market_trend_shadow_payload,
    evaluate_market_trend_candidates,
    render_market_trend_shadow_markdown,
)


def _event(
    minute,
    *,
    relationship,
    session_trend,
    bid=4.95,
    ask=5.00,
    entered=False,
):
    return {
        "event_id": f"2026-07-29T10:{minute:02d}:00-04:00|CALL",
        "candle_time_et": f"2026-07-29T10:{minute:02d}:00-04:00",
        "direction": "CALL",
        "market_regime": "BULL_TREND",
        "session_market_trend": session_trend,
        "session_trend_relationship": relationship,
        "session_market_trend_snapshot": {
            "trend": session_trend,
            "session_open": 740.0,
            "session_close": 740.5,
            "session_vwap": 740.4,
        },
        "score": 6,
        "entry_threshold": 5,
        "stage": {"label": "EARLY_CONTINUATION"},
        "cq": 4.1,
        "mas": 3.9,
        "absorption_score": 3.3,
        "confidence": 4.2,
        "entered": entered,
        "option_selected": "SPY_TEST_CALL",
        "option_quote_snapshot": {
            "symbol": "SPY_TEST_CALL",
            "bid": bid,
            "ask": ask,
        },
        "research": {"current_engine_qualified": True},
    }


def test_market_trend_shadow_uses_executable_same_contract_first_passage():
    events = [
        _event(0, relationship="NEUTRAL", session_trend="NEUTRAL", entered=True),
        {
            **_event(1, relationship="ALIGNED", session_trend="BULL_TREND"),
            "option_selected": "OTHER",
            "option_quote_snapshot": {"symbol": "OTHER", "bid": 2.0, "ask": 2.05},
            "option_watch_quotes": [{"symbol": "SPY_TEST_CALL", "bid": 5.35}],
        },
    ]
    rows = evaluate_market_trend_candidates(
        events,
        broker_trades=[{
            "direction": "CALL",
            "entry_time": "2026-07-29T10:00:30-04:00",
            "broker_entry_order_id": "broker-entry",
            "pnl_dollars": 125.0,
        }],
    )

    first = next(row for row in rows if row["event_id"].endswith("10:00:00-04:00|CALL"))
    assert first["classification"] == "TARGET_BEFORE_STOP"
    assert first["mfe_pct"] == 7.0
    assert first["actual_broker_pnl_dollars"] == 125.0
    assert first["policy_would_admit"]["ALIGNED_ONLY"] is False
    assert first["policy_would_admit"]["ALIGNED_OR_NEUTRAL"] is True


def test_market_trend_shadow_withholds_and_keeps_human_gate_locked():
    events = [
        _event(0, relationship="NEUTRAL", session_trend="NEUTRAL"),
        {
            **_event(1, relationship="ALIGNED", session_trend="BULL_TREND"),
            "option_watch_quotes": [{"symbol": "SPY_TEST_CALL", "bid": 4.80}],
        },
    ]
    payload = build_market_trend_shadow_payload(
        events,
        broker_trades=[],
        trading_date="2026-07-29",
        reconciliation={"complete": False},
    )

    assert payload["shadow_only"] is True
    assert payload["automatic_live_change_allowed"] is False
    assert payload["conclusions_withheld"] is True
    assert payload["gate"]["decision"] == "COLLECT_MORE_DATA"
    assert payload["coverage"]["entry_time_session_trend_captured"] == 2
    rendered = render_market_trend_shadow_markdown(payload)
    assert "Session Market Trend" in rendered
    assert "Conclusions withheld" in rendered
