from pathlib import Path

from engine.memory import Memory, get_memory

DB = Path("data/mcleod_alpha.db")


def _memory():
    if DB == Path("data/mcleod_alpha.db"):
        return get_memory()
    return Memory(db_path=DB)

def init_trade_log():
    _memory().initialize_live_trade_store()


def log_bot_order(order_id, intent):
    """Persist a bot-submitted broker order ID for exact source attribution."""
    _memory().record_order(order_id, intent)


def log_trade_diagnostic_event(event_type, direction, option_symbol=None, source=None, snapshot=None):
    """Persist point-in-time diagnostic snapshots at ENTRY and EXIT."""
    _memory().record_diagnostic(event_type, direction, option_symbol, source, snapshot)

def log_trade(entry_time,
              exit_time,
              direction,
              entry_price,
              exit_price,
              pnl,
              exit_reason,
              feature_payload=None,
              option_symbol=None,
              option_entry=None,
              option_exit=None,
              option_quantity=None,
              option_delta=None,
              option_return=None,
              option_pnl_dollars=None,
              option_pnl_pct=None,
              broker_entry_order_id=None,
              broker_exit_order_id=None,
              momentum_freshness_score=None,
              momentum_phase=None,
              absorption_score=None,
              entry_diagnostic_snapshot=None,
              exit_diagnostic_snapshot=None):

    _memory().record_trade(
        entry_time=entry_time,
        exit_time=exit_time,
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        exit_reason=exit_reason,
        feature_payload=feature_payload,
        option_symbol=option_symbol,
        option_entry=option_entry,
        option_exit=option_exit,
        option_quantity=option_quantity,
        option_delta=option_delta,
        option_return=option_return,
        option_pnl_dollars=option_pnl_dollars,
        option_pnl_pct=option_pnl_pct,
        broker_entry_order_id=broker_entry_order_id,
        broker_exit_order_id=broker_exit_order_id,
        momentum_freshness_score=momentum_freshness_score,
        momentum_phase=momentum_phase,
        absorption_score=absorption_score,
        entry_diagnostic_snapshot=entry_diagnostic_snapshot,
        exit_diagnostic_snapshot=exit_diagnostic_snapshot,
    )
        