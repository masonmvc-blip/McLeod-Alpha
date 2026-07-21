from datetime import datetime
from zoneinfo import ZoneInfo

from engine.runtime_status import _should_present_latest_session_as_today


ET = ZoneInfo("America/New_York")


def test_preopen_today_uses_single_completed_weekly_session():
    now = datetime(2026, 7, 21, 8, 44, tzinfo=ET)

    assert _should_present_latest_session_as_today(
        now,
        current_day_has_transactions=False,
        week_transaction_dates={datetime(2026, 7, 20, tzinfo=ET).date()},
    )


def test_today_remains_calendar_day_after_open_or_multiple_sessions():
    monday = datetime(2026, 7, 20, tzinfo=ET).date()
    tuesday = datetime(2026, 7, 21, tzinfo=ET).date()

    assert not _should_present_latest_session_as_today(
        datetime(2026, 7, 21, 9, 30, tzinfo=ET),
        current_day_has_transactions=False,
        week_transaction_dates={monday},
    )
    assert not _should_present_latest_session_as_today(
        datetime(2026, 7, 22, 8, 0, tzinfo=ET),
        current_day_has_transactions=False,
        week_transaction_dates={monday, tuesday},
    )