import sqlite3

from execution import signal_logger


def test_log_signal_skips_transient_database_lock(monkeypatch, capsys):
    class LockedMemory:
        @staticmethod
        def record_signal(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(signal_logger, "get_memory", lambda: LockedMemory())

    signal_logger.log_signal(741.76, "BULL_TREND", 5, 0)

    assert "Signal telemetry write skipped: database is locked" in capsys.readouterr().out


def test_log_signal_reraises_unrelated_database_failure(monkeypatch):
    class BrokenMemory:
        @staticmethod
        def record_signal(*_args, **_kwargs):
            raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(signal_logger, "get_memory", lambda: BrokenMemory())

    try:
        signal_logger.log_signal(741.76, "BULL_TREND", 5, 0)
    except sqlite3.OperationalError as exc:
        assert str(exc) == "disk I/O error"
    else:
        raise AssertionError("Expected unrelated SQLite failure to propagate")