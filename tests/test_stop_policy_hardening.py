from datetime import datetime

import pytest

import execution.live_engine as live_engine
import execution.paper_engine as paper_engine


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 7, 17, 10, 0, 0)
        if tz is not None:
            return base.replace(tzinfo=tz)
        return base


def _paper_position(entry=5.0):
    return paper_engine.Position(
        direction="CALL",
        entry_price=500.0,
        stop_price=495.0,
        target_price=510.0,
        quantity=1,
        opened=datetime(2026, 7, 17, 9, 50, 0),
        reason="TEST",
        option_symbol="SPY_TEST",
        option_entry=entry,
        option_delta=0.5,
        option_stop=0.0,
        option_initial_stop=0.0,
    )


def _live_position(entry=5.0):
    return live_engine.Position(
        direction="CALL",
        entry_price=500.0,
        stop_price=495.0,
        target_price=510.0,
        quantity=1,
        opened=datetime.now(),
        reason="TEST",
        option_symbol="SPY_TEST",
        option_entry=entry,
        option_delta=0.5,
        option_stop=4.75,
        option_initial_stop=4.75,
    )


def test_live_stop_reason_uses_active_broker_stop_tier():
    pos = _live_position(entry=5.89)
    pos.active_stop_reason = "4% TRAIL"

    # A trailing stop can fill below its trigger after the option reverses.
    # The label must remain the tier sent to Schwab, not be reclassified as STOP.
    assert live_engine._stop_reason_for_active_stop(pos) == "4% TRAIL"


def test_protective_stop_limit_keeps_the_intended_loss_floor():
    trigger_price, limit_price = live_engine._protective_stop_order_prices(5.87)

    assert trigger_price == 5.88
    assert limit_price == 5.87


def test_live_stop_hit_keeps_broker_stop_limit_working(monkeypatch):
    pos = _live_position(entry=6.18)
    pos.opened = datetime.now()
    pos.option_stop = 5.87
    pos.option_initial_stop = 5.87
    live_engine.current_position = pos

    close_calls = []
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: True)
    monkeypatch.setattr(live_engine, "close_trade", lambda *args, **kwargs: close_calls.append((args, kwargs)))
    monkeypatch.setattr(live_engine, "MAX_TRADE_HOLD_MINUTES", 999_999)
    live_engine._last_protective_stop_check_epoch = live_engine.time.time()
    live_engine._last_protective_stop_check_ok = True

    live_engine.manage_trade(current_price=744.68, option_mark=5.73, option_bid=5.72)

    assert close_calls == []


@pytest.mark.parametrize(
    "option_mark, expected_stop",
    [
        (5.101, 4.85),
        (5.151, 4.95),
        (5.201, 5.04497),
        (5.251, 5.119725),
        (5.301, 5.19498),
        (5.351, 5.270735),
        (5.401, 5.34699),
    ],
)
def test_paper_stop_ladder_thresholds(option_mark, expected_stop, monkeypatch):
    pos = _paper_position()
    paper_engine.current_position = pos

    monkeypatch.setattr(paper_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(paper_engine, "load_position", lambda _cls: pos)
    monkeypatch.setattr(paper_engine, "save_position", lambda _pos: None)
    monkeypatch.setattr(paper_engine, "close_trade", lambda *_args, **_kwargs: False)

    paper_engine.manage_trade(price=500.0, option_mark=option_mark, option_bid=option_mark)

    assert pos.option_stop == pytest.approx(expected_stop, abs=1e-6)


def test_paper_ratchet_never_moves_down(monkeypatch):
    pos = _paper_position()
    pos.option_initial_stop = 4.75
    pos.option_stop = 5.30
    paper_engine.current_position = pos

    monkeypatch.setattr(paper_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(paper_engine, "load_position", lambda _cls: pos)
    monkeypatch.setattr(paper_engine, "save_position", lambda _pos: None)
    monkeypatch.setattr(paper_engine, "close_trade", lambda *_args, **_kwargs: False)

    paper_engine.manage_trade(price=500.0, option_mark=5.25, option_bid=5.25)

    assert pos.option_stop == pytest.approx(5.30, abs=1e-6)


def test_live_close_when_protective_restore_fails(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 59, 0)
    live_engine.current_position = pos

    close_calls = {}

    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: False)
    monkeypatch.setattr(live_engine, "_submit_protective_stop", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(live_engine, "_send_unprotected_position_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        live_engine,
        "close_trade",
        lambda _price, reason, _option_mark=None: close_calls.setdefault("reason", reason),
    )

    live_engine._last_protective_stop_check_epoch = 0.0
    live_engine._last_protective_stop_check_ok = False

    live_engine.manage_trade(current_price=500.0, option_mark=5.20, option_bid=5.20)

    assert close_calls.get("reason") == "PROTECTIVE_STOP_SYNC_FAILED"


def test_live_close_when_ratcheted_stop_sync_fails(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 59, 0)
    pos.option_stop = 4.95
    pos.option_initial_stop = 4.75
    live_engine.current_position = pos

    close_calls = {}

    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: True)
    monkeypatch.setattr(live_engine, "_submit_protective_stop", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(
        live_engine,
        "close_trade",
        lambda _price, reason, _option_mark=None: close_calls.setdefault("reason", reason),
    )

    live_engine._last_protective_stop_check_epoch = 0.0
    live_engine._last_protective_stop_check_ok = True

    live_engine.manage_trade(current_price=500.0, option_mark=5.40, option_bid=5.40)

    assert close_calls.get("reason") == "PROTECTIVE_STOP_SYNC_FAILED"


def test_live_ratchet_does_not_wait_for_recent_stop_health_check(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 59, 0)
    pos.option_stop = 4.95
    pos.option_initial_stop = 4.75
    pos.protective_stop_order_id = "existing-stop"
    live_engine.current_position = pos

    submitted = {}
    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(
        live_engine,
        "_has_active_protective_stop_order",
        lambda _symbol: (_ for _ in ()).throw(AssertionError("unexpected broker stop scan")),
    )
    monkeypatch.setattr(
        live_engine,
        "_submit_protective_stop",
        lambda *_args, **kwargs: (
            submitted.update(kwargs) or "replacement-stop",
            kwargs["stop_price_override"],
        ),
    )
    monkeypatch.setattr(live_engine, "save_position", lambda _pos: None)
    monkeypatch.setattr(live_engine, "close_trade", lambda *_args, **_kwargs: False)

    live_engine._last_protective_stop_check_epoch = live_engine.time.time()
    live_engine._last_protective_stop_check_ok = True
    live_engine.manage_trade(current_price=500.0, option_mark=5.40, option_bid=5.40)

    assert submitted["existing_stop_order_id"] == "existing-stop"
    assert pos.protective_stop_order_id == "replacement-stop"


def test_live_closes_at_twenty_minute_maximum_hold(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 40, 0)
    live_engine.current_position = pos

    close_calls = {}
    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(
        live_engine,
        "close_trade",
        lambda _price, reason, _option_mark=None: close_calls.setdefault("reason", reason),
    )

    live_engine.manage_trade(current_price=500.0, option_mark=5.20, option_bid=5.20)

    assert close_calls.get("reason") == "MAX_HOLD_20_MIN"


@pytest.mark.parametrize(
    "reason, entry, exit_px, expected",
    [
        ("2% Stop", 5.00, 4.85, "2% Stop"),
        ("3% Stop", 5.00, 4.95, "3% Stop"),
        ("7% TRAIL", 5.00, 5.27, "7% TRAIL"),
        ("TRAILING_STOP", 5.00, 5.27, "5% TRAIL"),
        ("TRAILING_STOP", 5.00, 5.40, "8% TRAIL"),
    ],
)
def test_live_exit_reason_guard(reason, entry, exit_px, expected):
    assert live_engine._guard_exit_reason(reason, entry, exit_px) == expected
