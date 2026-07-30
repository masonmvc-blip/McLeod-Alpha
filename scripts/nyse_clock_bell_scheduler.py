#!/usr/bin/env python3
"""Play the NYSE bells from the Mac's local wall clock.

launchd's StartCalendarInterval is allowed to coalesce work and can start a
job several seconds after the requested minute.  This process stays resident,
uses launchd only to keep it alive, and watches the local wall clock itself.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


BELL_TIMES = (
    ("opening_bell", 8, 30),
    ("closing_bell", 15, 0),
)
WEEKDAYS = frozenset(range(5))
TRIGGER_GRACE_SECONDS = 1.0
MAX_CLOCK_CHECK_SECONDS = 1.0
FINAL_APPROACH_SECONDS = 0.05

ROOT_DIR = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT_DIR / "scripts" / "play_nyse_clock_bell.sh"


def scheduled_bells(day: datetime) -> Iterable[tuple[str, datetime]]:
    """Return bell names and local, naive wall-clock times for ``day``."""
    if day.weekday() not in WEEKDAYS:
        return ()
    return tuple(
        (name, day.replace(hour=hour, minute=minute, second=0, microsecond=0))
        for name, hour, minute in BELL_TIMES
    )


def due_bell(
    now: datetime,
    fired: set[tuple[object, str]],
) -> tuple[str, datetime] | None:
    """Return a bell that is due now, allowing a short process-wakeup grace."""
    for name, target in scheduled_bells(now):
        key = (target.date(), name)
        lateness = (now - target).total_seconds()
        if key not in fired and 0 <= lateness <= TRIGGER_GRACE_SECONDS:
            return name, target
    return None


def next_bell(now: datetime) -> tuple[str, datetime]:
    """Find the next future weekday bell in local wall-clock time."""
    for days_ahead in range(8):
        day = now + timedelta(days=days_ahead)
        for name, target in scheduled_bells(day):
            if target > now:
                return name, target
    raise RuntimeError("could not find the next weekday bell")


def sleep_interval(now: datetime, target: datetime) -> float:
    """Choose a clock-check interval, tightening near the target boundary."""
    remaining = (target - now).total_seconds()
    if remaining <= 0:
        return 0
    if remaining <= FINAL_APPROACH_SECONDS:
        return min(remaining, 0.005)
    return min(MAX_CLOCK_CHECK_SECONDS, remaining - FINAL_APPROACH_SECONDS)


def run() -> None:
    fired: set[tuple[object, str]] = set()
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not stopping:
        now = datetime.now()
        due = due_bell(now, fired)
        if due is not None:
            name, target = due
            fired.add((target.date(), name))
            subprocess.run(
                ["/bin/zsh", str(RUNNER_PATH), name],
                cwd=ROOT_DIR,
                check=False,
            )
            continue

        # Bound every sleep so manual Mac clock/time-zone changes are observed.
        _, target = next_bell(now)
        time.sleep(sleep_interval(now, target))

        # This set normally has two entries. Pruning keeps a long-running agent
        # bounded without depending on a restart at midnight.
        cutoff = datetime.now().date() - timedelta(days=1)
        fired = {key for key in fired if key[0] >= cutoff}


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"NYSE clock bell scheduler failed: {exc}", file=sys.stderr)
        raise
