from datetime import datetime, timedelta

import pytest

from backtesting.stop_policy_simulator import SimulatedPosition
from engine.brain import Brain, TradeAction
from engine.brain.live_rules import build_entry_risk_plan
from execution.contract_limits import MAX_OPEN_CONTRACTS
import execution.live_engine as live_engine


def _position():
    return SimulatedPosition(
        direction="CALL",
        entry_price=500.0,
        target_price=510.0,
        quantity=1,
        opened=datetime(2026, 7, 20, 9, 30),
        option_entry=5.0,
        option_stop=4.75,
        option_initial_stop=4.75,
    )


def test_evaluate_exit_returns_manual_exit_instruction():
    decision = Brain().evaluate_exit(
        _position(),
        {"current_price": 501.0, "option_mark": 5.05, "manual_exit": True, "manual_exit_reason": "MANUAL_EXIT_LIMIT"},
    )

    assert decision.action is TradeAction.EXIT
    assert decision.reason == "MANUAL_EXIT_LIMIT"


def test_evaluate_exit_returns_max_hold_stop_target_and_hold_instructions():
    brain = Brain()
    position = _position()

    hold_decision = brain.evaluate_exit(position, {"current_price": 505.0, "option_mark": 5.10, "now": position.opened + timedelta(minutes=19)})
    hold_time_decision = brain.evaluate_exit(position, {"current_price": 505.0, "option_mark": 5.10, "now": position.opened + timedelta(minutes=20)})
    active_time = position.opened + timedelta(minutes=19)
    stop_decision = brain.evaluate_exit(position, {"current_price": 505.0, "option_bid": 4.70, "protective_stop_active": False, "now": active_time})
    target_decision = brain.evaluate_exit(position, {"current_price": 510.0, "option_mark": 5.10, "now": active_time})

    assert hold_decision.action is TradeAction.HOLD
    assert hold_time_decision.reason == "MAX_HOLD_20_MIN"
    assert stop_decision.reason == "STOP"
    assert target_decision.reason == "TARGET_HIT"


def test_normalize_exit_reason_uses_canonical_stop_bands_and_vocabulary():
    brain = Brain()

    assert brain.normalize_exit_reason("TRAILING_STOP", 5.00, 5.27) == "4% TRAIL"
    assert brain.normalize_exit_reason("MANUAL_EXIT_LIMIT", 5.00, 5.27) == "MANUAL_EXIT_LIMIT"
    assert brain.normalize_exit_reason("unknown", 5.00, 5.27) == "TARGET_HIT"


def test_evaluate_protective_stop_result_owns_lifecycle_transitions():
    brain = Brain()
    position = _position()

    restored = brain.evaluate_protective_stop_result(position, restored=True, restore_count=1)
    repeated_restore = brain.evaluate_protective_stop_result(position, restored=True, restore_count=2)
    failed_restore = brain.evaluate_protective_stop_result(position, restored=False, restore_count=0)

    assert restored.action is TradeAction.HOLD
    assert repeated_restore.action is TradeAction.BLOCK_NEW_ENTRIES
    assert failed_restore.action is TradeAction.EXIT
    assert failed_restore.reason == "PROTECTIVE_STOP_SYNC_FAILED"


def test_entry_runtime_guard_owns_quantity_and_lifecycle_locks():
    brain = Brain()

    invalid_quantity = brain.evaluate_entry_runtime_guard(
        quantity=3, required_quantity=4, safe_mode=False, submission_rejected=False,
        max_quantity_exceeded=False, protective_stop_failed=False, entry_pending=False, already_in_trade=False,
    )
    protected_lock = brain.evaluate_entry_runtime_guard(
        quantity=4, required_quantity=4, safe_mode=False, submission_rejected=False,
        max_quantity_exceeded=False, protective_stop_failed=True, entry_pending=False, already_in_trade=False,
    )

    assert invalid_quantity.allowed is False
    assert invalid_quantity.reason == "contract_quantity_must_equal_max"
    assert protected_lock.reason == "protective_stop_failed_lock"


def test_live_entry_contract_cap_is_six_for_planning_and_submission(monkeypatch):
    _stop, _target, quantity = build_entry_risk_plan("CALL", 500.0)
    assert MAX_OPEN_CONTRACTS == 6
    assert quantity == 6

    monkeypatch.setattr(live_engine, "_schwab_client", object())
    monkeypatch.setattr(live_engine, "_schwab_account_hash", "test-account")
    monkeypatch.setattr(live_engine, "_submission_rejected", False)
    assert live_engine._submit_option_order("SPY TEST", "CALL", 1.0, 5) is None


def test_entry_admission_and_quote_quality_are_brain_decisions():
    brain = Brain()

    exposure = brain.evaluate_entry_admission(
        has_broker_exposure=True, risk_allowed=True, risk_block_reason=None, has_option_symbol=True,
    )
    quote = brain.evaluate_entry_quote(
        {"quote_age_seconds": 9.0, "quote_spread_pct": 16.0}, max_age_seconds=8.0, max_spread_pct=15.0,
    )

    assert exposure.reason == "existing_schwab_spy_option_exposure"
    assert quote.allowed is False
    assert "stale quote" in quote.reason
    assert "wide quote spread" in quote.reason


def test_live_quote_guard_forwards_to_brain_admission_policy():
    allowed, reason = live_engine._validate_entry_quote_snapshot(
        {"quote_age_seconds": 9.0, "quote_spread_pct": 10.0}
    )

    assert allowed is False
    assert "stale quote" in reason


def test_startup_reconciliation_and_initial_stop_are_brain_decisions():
    brain = Brain()

    unavailable = brain.evaluate_startup_reconciliation(
        broker_available=False, exposure_quantity=0, required_quantity=4, has_protective_stop=True,
    )
    oversized = brain.evaluate_startup_reconciliation(
        broker_available=True, exposure_quantity=5, required_quantity=4, has_protective_stop=True,
    )
    unprotected = brain.evaluate_startup_reconciliation(
        broker_available=True, exposure_quantity=1, required_quantity=4, has_protective_stop=False,
    )

    assert unavailable.reason == "safe_mode"
    assert oversized.reason == "max_quantity_exceeded_lock"
    assert unprotected.reason == "protective_stop_failed_lock"
    assert brain.initial_protective_stop(5.68) == pytest.approx(5.4528)


def test_startup_entry_attempt_gate_is_brain_owned():
    brain = Brain()

    assert brain.evaluate_startup_entry_admission(attempted_entries=0, blocked_attempts=2).allowed is False
    assert brain.evaluate_startup_entry_admission(attempted_entries=1, blocked_attempts=2).reason == "startup_guard"
    assert brain.evaluate_startup_entry_admission(attempted_entries=2, blocked_attempts=2).allowed is True