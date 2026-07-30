from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nyse_clock_bell_scheduler.py"
SPEC = spec_from_file_location("nyse_clock_bell_scheduler", SCRIPT)
assert SPEC and SPEC.loader
scheduler = module_from_spec(SPEC)
SPEC.loader.exec_module(scheduler)


def test_opening_bell_is_due_on_exact_mac_clock_boundary():
    now = datetime(2026, 7, 29, 8, 30, 0)
    assert scheduler.due_bell(now, set()) == ("opening_bell", now)


def test_closing_bell_is_due_on_exact_mac_clock_boundary():
    now = datetime(2026, 7, 29, 15, 0, 0)
    assert scheduler.due_bell(now, set()) == ("closing_bell", now)


def test_bell_does_not_repeat_after_it_fires():
    now = datetime(2026, 7, 29, 8, 30, 0, 500_000)
    fired = {(now.date(), "opening_bell")}
    assert scheduler.due_bell(now, fired) is None


def test_old_five_second_delay_is_not_accepted():
    now = datetime(2026, 7, 29, 8, 30, 5)
    assert scheduler.due_bell(now, set()) is None


def test_next_bell_skips_weekend():
    friday_after_close = datetime(2026, 7, 31, 15, 0, 1)
    assert scheduler.next_bell(friday_after_close) == (
        "opening_bell",
        datetime(2026, 8, 3, 8, 30, 0),
    )


def test_scheduler_tightens_clock_checks_near_boundary():
    target = datetime(2026, 7, 29, 8, 30, 0)
    now = datetime(2026, 7, 29, 8, 29, 59, 990_000)
    assert scheduler.sleep_interval(now, target) <= 0.005
