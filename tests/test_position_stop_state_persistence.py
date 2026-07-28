from datetime import datetime

from engine.memory import Memory
from execution.live_engine import Position


def test_position_persists_trailing_and_stop_lifecycle_state(tmp_path):
    memory = Memory(db_path=tmp_path / "memory.db")
    memory.position_path = tmp_path / "open_position.json"
    position = Position(
        direction="CALL",
        entry_price=500.0,
        stop_price=495.0,
        target_price=510.0,
        quantity=6,
        opened=datetime(2026, 7, 28, 10, 0),
        reason="TEST",
        option_symbol="SPY   260807C00740000",
        option_entry=5.0,
        option_stop=5.15,
        option_initial_stop=4.80,
        protective_stop_restore_count=2,
        option_high_since_entry=5.50,
        option_low_since_entry=4.95,
        option_high_timestamp="2026-07-28T10:02:00-04:00",
        option_low_timestamp="2026-07-28T10:00:30-04:00",
        spy_price_at_option_high=741.0,
        spy_price_at_option_low=739.5,
        option_trailing_high_bid=5.48,
    )

    memory.save_position(position)
    restored = memory.load_position(Position)

    assert restored.protective_stop_restore_count == 2
    assert restored.option_high_since_entry == 5.50
    assert restored.option_low_since_entry == 4.95
    assert restored.option_high_timestamp == "2026-07-28T10:02:00-04:00"
    assert restored.option_low_timestamp == "2026-07-28T10:00:30-04:00"
    assert restored.spy_price_at_option_high == 741.0
    assert restored.spy_price_at_option_low == 739.5
    assert restored.option_trailing_high_bid == 5.48
