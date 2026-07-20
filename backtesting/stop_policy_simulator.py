"""Deterministic, broker-free adapter for canonical Brain stop-policy tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from engine.brain import Brain, TradeDecision


@dataclass
class SimulatedPosition:
    direction: str = "CALL"
    entry_price: float = 500.0
    target_price: float = 510.0
    quantity: int = 1
    opened: datetime | None = None
    option_entry: float = 5.0
    option_stop: float = 0.0
    option_initial_stop: float = 0.0


def simulate_trade_management(
    *,
    option_mark: float,
    option_bid: float | None = None,
    position: SimulatedPosition | None = None,
    now: datetime | None = None,
) -> tuple[SimulatedPosition, TradeDecision]:
    """Run one canonical Brain management cycle without broker or persistence side effects."""
    current = position or SimulatedPosition(opened=now)
    timestamp = now or datetime.now()
    if current.opened is None:
        current.opened = timestamp

    decision = Brain().manage_trade(
        current,
        {
            "current_price": current.entry_price,
            "option_mark": option_mark,
            "option_bid": option_bid if option_bid is not None else option_mark,
            "protective_stop_active": True,
            "now": timestamp,
        },
    )
    for field_name, value in decision.metadata.get("state_updates", {}).items():
        setattr(current, field_name, value)
    return current, decision