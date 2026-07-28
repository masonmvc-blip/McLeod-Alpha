import sqlite3

from engine.memory import get_memory


def log_signal(price, regime, call_score, put_score, feature_payload=None):
    """Persist decision telemetry without interrupting live trade management."""
    try:
        get_memory().record_signal(price, regime, call_score, put_score, feature_payload)
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower():
            raise
        print(f"Signal telemetry write skipped: {exc}")