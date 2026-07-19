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
        opened=datetime(2026, 7, 17, 9, 50, 0),
        reason="TEST",
        option_symbol="SPY_TEST",
        option_entry=entry,
        option_delta=0.5,
        option_stop=4.75,
        option_initial_stop=4.75,
    )


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
    live_engine.current_position = pos

    close_calls = {}

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
    pos.option_stop = 4.95
    pos.option_initial_stop = 4.75
    live_engine.current_position = pos

    close_calls = {}

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
