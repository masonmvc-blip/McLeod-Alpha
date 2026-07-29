from types import SimpleNamespace

import execution.live_engine as live_engine
import phase3_monitor
from reports.stop_execution_review import build_stop_execution_review


def test_open_position_uses_fast_path_without_fetching_candles(monkeypatch):
    position = object()
    engine = SimpleNamespace(current_position=position)
    sleeps = []

    monkeypatch.setattr(phase3_monitor, "client", None)
    monkeypatch.setattr(phase3_monitor, "ENGINE_MODULE", engine)
    monkeypatch.setattr(phase3_monitor, "_enforce_end_of_day_exit", lambda: False)
    monkeypatch.setattr(
        phase3_monitor,
        "_manage_open_position_priority",
        lambda: True,
    )
    monkeypatch.setattr(
        phase3_monitor,
        "get_candles",
        lambda: (_ for _ in ()).throw(AssertionError("candle fetch delayed execution")),
    )

    phase3_monitor.run_monitor(
        max_cycles=1,
        runtime_initializer=lambda: None,
        sleep_fn=sleeps.append,
    )

    assert sleeps == [phase3_monitor.OPEN_POSITION_POLL_SECONDS]
    assert phase3_monitor.OPEN_POSITION_POLL_SECONDS == 0.75


def test_entry_miss_reprices_once_with_hard_cap_instead_of_market(monkeypatch):
    submissions = []
    quotes = iter([
        (
            6.83,
            {"bid": 6.79, "ask": 6.83, "mark": 6.81, "last": 6.82},
        ),
        (
            6.86,
            {"bid": 6.82, "ask": 6.86, "mark": 6.84, "last": 6.84},
        ),
    ])
    fills = iter([(False, None), (True, 6.85)])

    monkeypatch.setattr(live_engine, "current_position", None)
    monkeypatch.setattr(live_engine, "_submission_rejected", False)
    monkeypatch.setattr(live_engine, "_max_quantity_exceeded", False)
    monkeypatch.setattr(live_engine, "_protective_stop_failed", False)
    monkeypatch.setattr(live_engine, "_entry_pending", False)
    monkeypatch.setattr(live_engine, "_safe_mode", False)
    monkeypatch.setattr(live_engine, "_last_entry_order_status", None)
    monkeypatch.setattr(live_engine, "_last_entry_order_status_description", None)
    monkeypatch.setattr(live_engine, "ENTRY_MARKET_FALLBACK_ENABLED", False)
    monkeypatch.setattr(live_engine, "in_trade", lambda: False)
    monkeypatch.setattr(
        live_engine,
        "_fresh_entry_exposure_preflight",
        lambda: (False, None),
    )
    monkeypatch.setattr(live_engine, "can_open_trade", lambda: (True, None))
    monkeypatch.setattr(
        live_engine,
        "_compute_fast_entry_limit_price",
        lambda *_args: next(quotes),
    )
    monkeypatch.setattr(
        live_engine,
        "_validate_entry_quote_snapshot",
        lambda _snapshot: (True, None),
    )
    monkeypatch.setattr(
        live_engine,
        "_get_available_option_buying_funds",
        lambda: 10000.0,
    )
    monkeypatch.setattr(
        live_engine,
        "_submit_option_order",
        lambda _symbol, _direction, price, _quantity: (
            submissions.append(price) or f"order-{len(submissions)}"
        ),
    )
    monkeypatch.setattr(
        live_engine,
        "_wait_for_fill",
        lambda *_args, **_kwargs: next(fills),
    )
    monkeypatch.setattr(
        live_engine,
        "_submit_option_entry_market_order",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("uncapped market fallback must not run")
        ),
    )
    monkeypatch.setattr(
        live_engine,
        "_submit_protective_stop",
        lambda *_args, **_kwargs: ("stop-1", 6.58),
    )
    monkeypatch.setattr(live_engine, "save_position", lambda _position: None)
    monkeypatch.setattr(
        live_engine,
        "_record_entry_feature_vector",
        lambda *_args: None,
    )
    monkeypatch.setattr(live_engine, "_play_execution_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(live_engine, "send_trade_entry_alert", lambda **_kwargs: None)
    monkeypatch.setattr(live_engine, "log_trade_diagnostic_event", lambda **_kwargs: None)

    opened = live_engine.open_trade(
        direction="CALL",
        price=740.0,
        stop=739.25,
        target=741.5,
        quantity=live_engine.MAX_OPEN_CONTRACTS,
        reason="TEST",
        option={"symbol": "SPY TEST", "mark": 6.81, "delta": 0.5},
        feature_payload="{}",
    )

    assert opened is True
    assert submissions == [6.83, 6.86]
    metrics = live_engine.get_last_open_trade_metrics()
    assert metrics["entry_price_cap"] == 6.88
    assert metrics["final_limit_price"] == 6.86
    assert metrics["filled_via"] == "repriced_limit"
    assert live_engine.current_position.option_entry == 6.85


def test_daily_stop_review_measures_entry_and_exit_execution_drag():
    trade_key = "SPY TEST:2026-07-29T14:42:07-04:00"
    events = [{
        "recorded_at": "2026-07-29T14:42:08-04:00",
        "event_type": "option_quote_observed",
        "trade_key": trade_key,
        "option_symbol": "SPY TEST",
        "bid": 8.38,
    }]
    cycles = [
        {
            "recorded_at": "2026-07-29T14:42:08-04:00",
            "event_type": "option_management_cycle",
            "trade_key": "SPY TEST:2026-07-29 14:42:07-04:00",
            "quantity": 5,
            "bid": 8.38,
            "entry_option_quote_snapshot": {
                "ask": 7.82,
                "broker_fill_price": 7.71,
                "filled_via": "limit",
                "submitted_limit_price": 7.82,
            },
        },
        {
            "recorded_at": "2026-07-29T14:46:45-04:00",
            "event_type": "option_management_cycle",
            "trade_key": "SPY TEST:2026-07-29 14:42:07-04:00",
            "quantity": 5,
            "bid": 8.27,
        },
        {
            "recorded_at": "2026-07-29T14:46:46-04:00",
            "event_type": "broker_reconciled_exit_fill",
            "trade_key": "SPY TEST:2026-07-29 14:42:07-04:00",
            "quantity": 5,
            "broker_exit_fill_price": 8.18,
            "protective_stop_trigger": 8.27,
        },
    ]

    payload = build_stop_execution_review(
        events,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
        option_cycles=cycles,
    )

    quality = payload["trades"][0]["execution_quality"]
    assert quality["entry_adverse_slippage_dollars"] == 0.0
    assert quality["exit_execution_shortfall_dollars"] == 0.09
    assert quality["estimated_round_trip_execution_drag_dollars"] == 45.0
    assert quality["exit_protective_stop_trigger"] == 8.27


def test_daily_stop_review_joins_canonical_fill_when_exit_event_predates_logging():
    trade_key = "SPY TEST:2026-07-29T14:42:07-04:00"
    payload = build_stop_execution_review(
        [{
            "recorded_at": "2026-07-29T14:42:08-04:00",
            "event_type": "option_quote_observed",
            "trade_key": trade_key,
            "option_symbol": "SPY TEST",
            "bid": 8.38,
        }],
        trading_date="2026-07-29",
        reconciliation={"complete": True},
        option_cycles=[
            {
                "recorded_at": "2026-07-29T14:46:45-04:00",
                "event_type": "option_management_cycle",
                "trade_key": "SPY TEST:2026-07-29 14:42:07-04:00",
                "quantity": 5,
                "bid": 8.27,
                "entry_option_quote_snapshot": {
                    "ask": 7.82,
                    "broker_fill_price": 7.71,
                    "submitted_limit_price": 7.82,
                },
            },
        ],
        canonical_trades=[{
            "entry_time": "2026-07-29T14:42:05-04:00",
            "option_symbol": "SPY TEST",
            "option_exit_price": 8.18,
            "option_quantity": 5,
        }],
    )

    quality = payload["trades"][0]["execution_quality"]
    assert quality["exit_fill_price"] == 8.18
    assert quality["exit_execution_shortfall_dollars"] == 0.09
    assert quality["exit_fill_provenance"] == "canonical_broker_replay"
