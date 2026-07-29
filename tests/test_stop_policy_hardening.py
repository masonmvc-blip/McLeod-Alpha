import json
from datetime import datetime
from unittest.mock import Mock

import pytest

from backtesting.stop_policy_simulator import SimulatedPosition, simulate_trade_management
import execution.live_engine as live_engine


@pytest.fixture(autouse=True)
def _isolate_live_position_persistence(monkeypatch):
    """Keep stop-policy unit tests from mutating production runtime artifacts."""
    monkeypatch.setattr(live_engine, "save_position", lambda _position: None)
    monkeypatch.setattr(live_engine, "clear_position", lambda: None)
    monkeypatch.setattr(live_engine, "_audit_bot_order", lambda _order_id, _intent: None)
    live_engine.current_position = None
    yield
    live_engine.current_position = None


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 7, 17, 10, 0, 0)
        if tz is not None:
            return base.replace(tzinfo=tz)
        return base


def _simulated_position(entry=5.0):
    return SimulatedPosition(
        direction="CALL",
        entry_price=500.0,
        target_price=510.0,
        quantity=1,
        opened=datetime(2026, 7, 17, 9, 59, 0),
        option_entry=entry,
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
    pos.active_stop_reason = "4% Stop"

    # A trailing stop can fill below its trigger after the option reverses.
    # The label must remain the tier sent to Schwab, not be reclassified as STOP.
    assert live_engine._stop_reason_for_active_stop(pos) == "4% Stop"


def test_brain_stop_exit_preserves_active_broker_stop_tier():
    pos = _live_position(entry=5.0)
    pos.option_stop = 5.15
    pos.active_stop_reason = "4% Stop"

    decision = live_engine.LIVE_BRAIN.evaluate_exit(
        pos,
        {"option_bid": 5.10, "option_mark": 5.11, "protective_stop_active": False},
        conditions=("stop",),
    )

    assert decision.reason == "4% Stop"


def test_end_of_day_exit_boundary_is_345_pm_eastern():
    eastern = live_engine.EASTERN_TZ

    assert live_engine._is_end_of_day_exit_due(datetime(2026, 7, 17, 15, 44, 59, tzinfo=eastern)) is False
    assert live_engine._is_end_of_day_exit_due(datetime(2026, 7, 17, 15, 45, 0, tzinfo=eastern)) is True


def test_live_manager_exits_open_position_at_end_of_day(monkeypatch):
    live_engine.current_position = _live_position()
    close_calls = []
    monkeypatch.setattr(live_engine, "_is_end_of_day_exit_due", lambda: True)
    monkeypatch.setattr(live_engine, "close_trade", lambda *args: close_calls.append(args))

    live_engine.manage_trade(current_price=500.0, option_mark=5.0, option_bid=4.99)

    assert close_calls == [(500.0, "END_OF_DAY_EXIT", 5.0)]


def test_protective_stop_limit_keeps_the_intended_loss_floor():
    trigger_price, limit_price = live_engine._protective_stop_order_prices(5.87)

    assert trigger_price == 5.88
    assert limit_price == 5.87


def test_known_stop_replacement_skips_account_scan_and_cancels_only_after_submit(monkeypatch):
    client = Mock()
    response = Mock()
    response.headers = {"Location": "/orders/replacement-stop"}
    response.raise_for_status.return_value = None
    client.place_order.return_value = response
    client.cancel_order.return_value.raise_for_status.return_value = None
    live_engine.set_schwab_client(client, "account-number", "account-hash")
    monkeypatch.setattr(live_engine, "_audit_bot_order", lambda *_args: None)

    order_id, stop_price = live_engine._submit_protective_stop(
        "SPY  260720C00600000",
        fill_price=5.00,
        quantity=1,
        stop_price_override=5.25,
        existing_stop_order_id="old-stop",
    )

    assert order_id == "replacement-stop"
    assert stop_price == 5.25
    client.get_orders_for_account.assert_not_called()
    assert client.place_order.call_count == 1
    submitted_order = client.place_order.call_args[0][1]
    assert str(getattr(submitted_order, "_orderType", "")) == "STOP"
    assert not getattr(submitted_order, "_price", None)
    assert str(getattr(submitted_order, "_stopPrice", "")) == "5.25"
    client.cancel_order.assert_called_once_with("old-stop", "account-hash")


def test_same_target_known_stop_is_coalesced_without_duplicate_place(monkeypatch):
    client = Mock()
    known = Mock()
    known.raise_for_status.return_value = None
    known.json.return_value = {
        "status": "WORKING",
        "orderType": "STOP",
        "stopPrice": 5.25,
        "orderLegCollection": [{
            "instruction": "SELL_TO_CLOSE",
            "instrument": {
                "assetType": "OPTION",
                "symbol": "SPY  260720C00600000",
            },
        }],
    }
    client.get_order.return_value = known
    live_engine.set_schwab_client(client, "account-number", "account-hash")

    order_id, stop_price = live_engine._submit_protective_stop(
        "SPY  260720C00600000",
        fill_price=5.00,
        quantity=1,
        stop_price_override=5.25,
        existing_stop_order_id="working-stop",
        existing_stop_price=5.25,
    )

    assert (order_id, stop_price) == ("working-stop", 5.25)
    client.place_order.assert_not_called()
    client.cancel_order.assert_not_called()


def test_same_target_known_stop_is_preserved_during_broker_outage(monkeypatch):
    client = Mock()
    client.get_order.side_effect = RuntimeError("Schwab rate-limit cooldown active")
    live_engine.set_schwab_client(client, "account-number", "account-hash")

    order_id, stop_price = live_engine._submit_protective_stop(
        "SPY  260720C00600000",
        fill_price=5.00,
        quantity=1,
        stop_price_override=5.25,
        existing_stop_order_id="last-confirmed-stop",
        existing_stop_price=5.25,
    )

    assert (order_id, stop_price) == ("last-confirmed-stop", 5.25)
    client.place_order.assert_not_called()


def test_restore_reconciles_flat_position_before_stop_submission(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 59, 0)
    pos.protective_stop_order_id = "filled-stop"
    live_engine.current_position = pos

    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_is_end_of_day_exit_due", lambda: False)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: False)

    sync_calls = []

    def reconcile_flat(_price, force=False):
        sync_calls.append(force)
        if force:
            live_engine.current_position = None

    monkeypatch.setattr(live_engine, "_sync_position_with_broker", reconcile_flat)
    monkeypatch.setattr(
        live_engine,
        "_submit_protective_stop",
        lambda *_args, **_kwargs: pytest.fail("flat account must not receive a replacement stop"),
    )

    live_engine._last_protective_stop_check_epoch = 0.0
    live_engine._last_protective_stop_check_ok = False
    live_engine.manage_trade(current_price=500.0, option_mark=5.20, option_bid=5.20)

    assert sync_calls == [False, True]
    assert live_engine.current_position is None


def test_initial_protective_stop_skips_account_order_scan(monkeypatch):
    client = Mock()
    response = Mock()
    response.headers = {"Location": "/orders/initial-stop"}
    response.raise_for_status.return_value = None
    client.place_order.return_value = response
    live_engine.set_schwab_client(client, "account-number", "account-hash")
    monkeypatch.setattr(live_engine, "_audit_bot_order", lambda *_args: None)

    order_id, stop_price = live_engine._submit_protective_stop(
        "SPY  260720C00600000",
        fill_price=5.00,
        quantity=1,
        skip_existing_order_scan=True,
    )

    assert order_id == "initial-stop"
    assert stop_price > 0
    client.get_orders_for_account.assert_not_called()


def test_live_stop_hit_keeps_broker_stop_limit_working(monkeypatch):
    pos = _live_position(entry=6.18)
    pos.opened = datetime.now()
    pos.option_stop = 5.87
    pos.option_initial_stop = 5.87
    live_engine.current_position = pos

    close_calls = []
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price, force=False: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: True)
    monkeypatch.setattr(live_engine, "close_trade", lambda *args, **kwargs: close_calls.append((args, kwargs)))
    monkeypatch.setattr(live_engine, "_is_end_of_day_exit_due", lambda: False)
    live_engine._last_protective_stop_check_epoch = live_engine.time.time()
    live_engine._last_protective_stop_check_ok = True

    live_engine.manage_trade(current_price=744.68, option_mark=5.73, option_bid=5.72)

    assert close_calls == []


def test_failed_exit_submission_keeps_existing_protective_stop(monkeypatch):
    pos = _live_position()
    pos.protective_stop_order_id = "existing-stop"
    live_engine.current_position = pos

    cancelled_orders = []
    monkeypatch.setattr(live_engine, "_submit_option_exit_market_order", lambda *_args: None)
    monkeypatch.setattr(live_engine, "_cancel_protective_stop", lambda order_id: cancelled_orders.append(order_id))
    monkeypatch.setattr(
        live_engine,
        "_submit_protective_stop",
        lambda *_args, **_kwargs: pytest.fail("must not replace a stop that was never canceled"),
    )

    assert live_engine.close_trade(500.0, "MANUAL_EXIT") is False
    assert cancelled_orders == []


def test_exit_submission_cooldown_keeps_existing_protective_stop(monkeypatch):

    def test_near_market_manual_exit_prices_at_midpoint_of_spread(monkeypatch):
        monkeypatch.setattr(live_engine, "_fetch_option_quote_levels", lambda _symbol: {"bid": 5.00, "ask": 5.40})

        assert live_engine._compute_fast_exit_limit_price("SPY TEST", 5.20) == 5.20
    pos = _live_position()
    pos.protective_stop_order_id = "existing-stop"
    live_engine.current_position = pos

    monkeypatch.setattr(live_engine, "_last_exit_submission_failure_epoch", live_engine.time.time())
    monkeypatch.setattr(
        live_engine,
        "_submit_option_exit_market_order",
        lambda *_args: pytest.fail("cooldown must suppress duplicate exit submission"),
    )
    monkeypatch.setattr(
        live_engine,
        "_cancel_protective_stop",
        lambda *_args: pytest.fail("cooldown must preserve the protective stop"),
    )

    assert live_engine.close_trade(500.0, "MANUAL_EXIT") is False


def test_reconciliation_clears_stale_local_position_when_broker_is_flat(monkeypatch, tmp_path):
    live_engine.current_position = _live_position()
    cleared = []
    snapshot_path = tmp_path / "broker_reconciliation_snapshot.json"
    monkeypatch.setattr(live_engine, "BROKER_RECONCILIATION_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(live_engine, "get_schwab_positions", lambda: ([], [], 200, None))
    monkeypatch.setattr(live_engine, "clear_position", lambda: cleared.append(True))

    assert live_engine.reconcile_startup() is True
    assert cleared == [True]
    assert live_engine.current_position is None
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["status"] == "SUCCESS"
    assert snapshot["spy_option_positions"] == []
    assert snapshot["spy_option_orders"] == []


def test_reconciliation_excludes_canceled_spy_orders_from_snapshot(monkeypatch, tmp_path):
    snapshot_path = tmp_path / "broker_reconciliation_snapshot.json"
    monkeypatch.setattr(live_engine, "BROKER_RECONCILIATION_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(live_engine, "current_position", None)
    canceled_order = {
        "status": "CANCELED",
        "orderLegCollection": [{"quantity": 1, "instrument": {"assetType": "OPTION", "symbol": "SPY TEST"}}],
    }
    monkeypatch.setattr(live_engine, "get_schwab_positions", lambda: ([], [canceled_order], 200, None))

    assert live_engine.reconcile_startup() is True
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["spy_option_orders"] == []


def test_broker_governor_blocks_all_calls_after_rate_limit(monkeypatch, tmp_path):
    class RateLimitedResponse:
        status_code = 429
        headers = {"Retry-After": "45"}

        def raise_for_status(self):
            raise RuntimeError("429 Too Many Requests")

    class Client:
        def get_account(self):
            return RateLimitedResponse()

    cooldown_file = tmp_path / "broker_rate_limit.json"
    monkeypatch.setattr(live_engine, "BROKER_RATE_LIMIT_STATE_FILE", cooldown_file)
    monkeypatch.setattr(live_engine, "_broker_rate_limited_until_epoch", 0.0)
    monkeypatch.setattr(live_engine, "_last_broker_request_epoch", 0.0)

    client = live_engine._GovernedSchwabClient(Client())
    with pytest.raises(RuntimeError, match="429"):
        client.get_account().raise_for_status()

    assert live_engine._broker_rate_limited_until_epoch > live_engine.time.time()
    assert cooldown_file.exists()
    with pytest.raises(RuntimeError, match="cooldown active"):
        client.get_account()


def test_broker_governor_preserves_client_enum_classes():
    class Account:
        class Fields:
            POSITIONS = "positions"

    class Client:
        pass

    Client.Account = Account

    assert live_engine._GovernedSchwabClient(Client()).Account.Fields.POSITIONS == "positions"


@pytest.mark.parametrize(
    "option_mark, expected_stop",
    [
        (5.000, 4.80),
        (5.051, 4.89947),
        (5.101, 4.99898),
        (5.151, 5.073735),
        (5.201, 5.14899),
        (5.401, 5.34699),
    ],
)
def test_simulation_adapter_stop_ladder_thresholds(option_mark, expected_stop):
    pos, _decision = simulate_trade_management(
        position=_simulated_position(),
        option_mark=option_mark,
        now=_FixedDateTime.now(),
    )

    assert pos.option_stop == pytest.approx(expected_stop, abs=1e-6)


def test_simulation_adapter_ratchet_never_moves_down():
    pos = _simulated_position()
    pos.option_initial_stop = 4.75
    pos.option_stop = 5.30
    pos, _decision = simulate_trade_management(position=pos, option_mark=5.25, now=_FixedDateTime.now())

    assert pos.option_stop == pytest.approx(5.30, abs=1e-6)


def test_live_close_when_protective_restore_fails(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 59, 0)
    live_engine.current_position = pos

    close_calls = {}

    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price, force=False: None)
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


def test_live_preserves_existing_stop_when_ratcheted_stop_sync_fails(monkeypatch):
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

    assert close_calls == {}
    assert live_engine.current_position.option_stop == 4.95


def test_live_ratchet_defers_small_stop_improvements(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 59, 0)
    pos.option_stop = 5.25
    pos.option_initial_stop = 4.75
    live_engine.current_position = pos

    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: True)
    monkeypatch.setattr(
        live_engine,
        "_submit_protective_stop",
        lambda *_args, **_kwargs: pytest.fail("small ratchet must not submit a broker replacement"),
    )
    monkeypatch.setattr(live_engine, "STOP_RATCHET_MIN_IMPROVEMENT_DOLLARS", 0.10)
    live_engine._last_protective_stop_check_epoch = 0.0
    live_engine._last_protective_stop_check_ok = True
    live_engine._last_protective_stop_submission_epoch = 0.0

    live_engine.manage_trade(current_price=500.0, option_mark=5.40, option_bid=5.40)

    assert live_engine.current_position.option_stop == 5.25


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
    assert pos.active_stop_reason == "4% Stop"


def test_live_ratchet_skips_wide_quote_without_weakening_existing_stop(monkeypatch):
    pos = _live_position()
    pos.opened = datetime(2026, 7, 17, 9, 59, 0)
    pos.option_stop = 4.95
    pos.option_initial_stop = 4.75
    live_engine.current_position = pos

    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: True)
    monkeypatch.setattr(live_engine, "_submit_protective_stop", lambda *_args, **_kwargs: pytest.fail("wide quote must not ratchet stop"))
    monkeypatch.setattr(live_engine, "save_position", lambda _pos: None)
    monkeypatch.setattr(live_engine, "record_stop_event", lambda *_args, **_kwargs: None)
    live_engine._last_protective_stop_check_epoch = live_engine.time.time()
    live_engine._last_protective_stop_check_ok = True

    live_engine.manage_trade(
        current_price=500.0,
        option_mark=5.40,
        option_bid=5.40,
        quote_metadata={"bid": 5.40, "ask": 6.40, "quote_spread_pct": 16.9, "quote_age_seconds": 0.1},
    )

    assert pos.option_stop == 4.95


def test_live_ratchet_retains_only_reliable_high_bid(monkeypatch):
    pos = _live_position()
    pos.option_trailing_high_bid = 5.20
    live_engine.current_position = pos

    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: True)
    monkeypatch.setattr(live_engine, "save_position", lambda _pos: None)
    monkeypatch.setattr(
        live_engine,
        "_submit_protective_stop",
        lambda *_args, **_kwargs: pytest.fail("unreliable quote must not ratchet stop"),
    )
    live_engine._last_protective_stop_check_epoch = live_engine.time.time()
    live_engine._last_protective_stop_check_ok = True

    live_engine.manage_trade(
        current_price=500.0,
        option_mark=6.00,
        option_bid=5.90,
        quote_metadata={"bid": 5.90, "ask": 6.90, "quote_spread_pct": 15.6, "quote_age_seconds": 0.1},
    )

    assert pos.option_trailing_high_bid == 5.20


def test_live_exits_when_price_crosses_deferred_high_water_stop(monkeypatch):
    pos = _live_position()
    pos.option_stop = 4.95
    pos.option_initial_stop = 4.75
    pos.option_trailing_high_bid = 5.40
    live_engine.current_position = pos

    close_calls = {}
    monkeypatch.setattr(live_engine, "datetime", _FixedDateTime)
    monkeypatch.setattr(live_engine, "_sync_position_with_broker", lambda _price: None)
    monkeypatch.setattr(live_engine, "_has_active_protective_stop_order", lambda _symbol: True)
    monkeypatch.setattr(live_engine, "save_position", lambda _pos: None)
    monkeypatch.setattr(
        live_engine,
        "_submit_protective_stop",
        lambda *_args, **_kwargs: pytest.fail("crossed high-water stop must exit, not submit above market"),
    )
    monkeypatch.setattr(
        live_engine,
        "close_trade",
        lambda _price, reason, option_mark=None: close_calls.update(reason=reason, mark=option_mark),
    )
    live_engine._last_protective_stop_check_epoch = live_engine.time.time()
    live_engine._last_protective_stop_check_ok = True
    live_engine._last_protective_stop_submission_epoch = 0.0

    live_engine.manage_trade(
        current_price=500.0,
        option_mark=5.31,
        option_bid=5.30,
        quote_metadata={"bid": 5.30, "ask": 5.32, "quote_spread_pct": 0.38, "quote_age_seconds": 0.1},
    )

    assert close_calls == {"reason": "4% Stop", "mark": 5.31}
    assert pos.option_stop == 4.95


def test_live_does_not_close_at_former_twenty_minute_maximum_hold(monkeypatch):
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

    assert close_calls == {}


@pytest.mark.parametrize(
    "reason, entry, exit_px, expected",
    [
        ("1% Stop", 5.00, 5.05, "1% Stop"),
        ("2% Stop", 5.00, 4.85, "2% Stop"),
        ("3% Stop", 5.00, 4.95, "3% Stop"),
        ("4% Stop", 5.00, 5.27, "4% Stop"),
        ("TRAILING_STOP", 5.00, 5.27, "4% Stop"),
        ("TRAILING_STOP", 5.00, 5.40, "4% Stop"),
    ],
)
def test_live_exit_reason_guard(reason, entry, exit_px, expected):
    assert live_engine._guard_exit_reason(reason, entry, exit_px) == expected
