from unittest.mock import Mock

import execution.live_engine as live_engine


def test_affordability_reduces_seven_contract_request_to_five():
    assert live_engine._max_affordable_option_contracts(
        available_funds=4006.61,
        option_price=6.83,
        requested_quantity=7,
    ) == 5


def test_affordability_never_exceeds_configured_contract_cap():
    assert live_engine._max_affordable_option_contracts(
        available_funds=100000.0,
        option_price=1.0,
        requested_quantity=7,
    ) == live_engine.MAX_OPEN_CONTRACTS


def test_affordability_blocks_when_one_contract_cannot_be_funded():
    assert live_engine._max_affordable_option_contracts(
        available_funds=600.0,
        option_price=6.83,
        requested_quantity=7,
    ) == 0


def test_option_buying_funds_use_schwab_nonmarginable_balance(monkeypatch):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {
        "securitiesAccount": {
            "currentBalances": {
                "availableFundsNonMarginableTrade": 4006.61,
                "availableFunds": 4100.0,
                "dayTradingBuyingPower": 112371.0,
            }
        }
    }
    client = Mock()
    client.get_account.return_value = response
    monkeypatch.setattr(live_engine, "_schwab_client", client)
    monkeypatch.setattr(live_engine, "_schwab_account_hash", "account-hash")

    assert live_engine._get_available_option_buying_funds() == 4006.61


def test_buying_power_rejection_is_actionable_terminal_reason():
    assert live_engine._entry_terminal_block_reason(
        "REJECTED",
        "You do not have enough available cash/buying power for this order.",
    ) == "insufficient_option_buying_power"


def test_open_trade_submits_largest_affordable_quantity(monkeypatch):
    submitted = {}

    monkeypatch.setattr(live_engine, "current_position", None)
    monkeypatch.setattr(live_engine, "_submission_rejected", False)
    monkeypatch.setattr(live_engine, "_max_quantity_exceeded", False)
    monkeypatch.setattr(live_engine, "_protective_stop_failed", False)
    monkeypatch.setattr(live_engine, "_entry_pending", False)
    monkeypatch.setattr(live_engine, "_safe_mode", False)
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
        lambda _symbol, _mark: (
            6.83,
            {"bid": 6.79, "ask": 6.83, "mark": 6.81, "last": 6.82},
        ),
    )
    monkeypatch.setattr(
        live_engine,
        "_validate_entry_quote_snapshot",
        lambda _snapshot: (True, None),
    )
    monkeypatch.setattr(
        live_engine,
        "_get_available_option_buying_funds",
        lambda: 4006.61,
    )

    def capture_submission(_symbol, _direction, _price, quantity):
        submitted["quantity"] = quantity
        return None

    monkeypatch.setattr(live_engine, "_submit_option_order", capture_submission)

    opened = live_engine.open_trade(
        direction="PUT",
        price=733.0,
        stop=733.75,
        target=731.5,
        quantity=live_engine.MAX_OPEN_CONTRACTS,
        reason="TEST",
        option={"symbol": "SPY   260807P00730000", "mark": 6.81},
    )

    assert opened is False
    assert submitted["quantity"] == 5
    assert live_engine.get_last_open_trade_metrics()["selected_quantity"] == 5
