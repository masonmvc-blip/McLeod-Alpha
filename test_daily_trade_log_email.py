from datetime import date, time as dt_time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import execution.daily_trade_log_email as trade_email


def test_target_send_time_regular_close(monkeypatch):
    monkeypatch.setattr(trade_email, "_configured_send_time_ct", lambda: dt_time(15, 1))
    monkeypatch.setattr(trade_email, "_get_market_close_time_ct", lambda _: dt_time(15, 0))

    target = trade_email._target_send_time_ct(date(2026, 7, 15))
    assert target == dt_time(15, 1)


def test_target_send_time_early_close(monkeypatch):
    monkeypatch.setattr(trade_email, "_configured_send_time_ct", lambda: dt_time(15, 1))
    monkeypatch.setattr(trade_email, "_get_market_close_time_ct", lambda _: dt_time(12, 0))

    target = trade_email._target_send_time_ct(date(2026, 7, 3))
    assert target == dt_time(12, 5)


def test_normalize_option_pnl_pct_from_ratio():
    pct = trade_email._normalize_option_pnl_pct(raw_pct=0.125, option_entry=None, option_exit=None)
    assert pct == 12.5


def test_extract_reasons_splits_penalties():
    snap = {
        "entry_reasons_call": [
            "ema_alignment",
            "volume_weakening_bullish_move",
        ],
        "momentum_freshness_call": {
            "positives": ["momentum_fresh_trend"],
            "penalties": ["momentum_late_streak"],
        },
    }

    positives, penalties = trade_email._extract_reasons(snap, "CALL")

    assert "ema_alignment" in positives
    assert "momentum:momentum_fresh_trend" in positives
    assert "volume_weakening_bullish_move" in penalties
    assert "momentum:momentum_late_streak" in penalties


def test_placeholder_symbol_filtering():
    rows = [
        {"option_symbol": "SPY_CALL"},
        {"option_symbol": "SPY 07-13-26 P450"},
        {"option_symbol": "SPY   260724C00755000"},
    ]
    filtered = trade_email._filter_placeholder_trade_rows(rows)
    assert len(filtered) == 1
    assert filtered[0]["option_symbol"] == "SPY   260724C00755000"


def test_process_pending_verification_marks_done(monkeypatch, tmp_path):
    monkeypatch.setattr(trade_email, "DELIVERY_LOG_PATH", tmp_path / "delivery.log")

    csv_file = tmp_path / "a.csv"
    json_file = tmp_path / "a.json"
    csv_file.write_text("x")
    json_file.write_text("{}")

    now = datetime.now(ZoneInfo("America/Chicago"))
    state = {
        "verification_due_at": (now - timedelta(minutes=2)).isoformat(),
        "verification_done": False,
        "last_csv_path": str(csv_file),
        "last_json_path": str(json_file),
        "attempt_count": 1,
        "attempt_date": now.date().isoformat(),
    }

    trade_email._process_pending_verification(state, now)
    assert state.get("verification_done") is True
