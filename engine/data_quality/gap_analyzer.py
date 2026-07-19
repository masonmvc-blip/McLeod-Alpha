"""Deterministic period and gap classification helpers."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def expected_dates(start: date, end: date, rule: str) -> tuple[date, ...]:
    if rule == "trading_day":
        return tuple(day for day in _days(start, end) if day.weekday() < 5)
    if rule == "quarterly":
        periods: list[date] = []
        year, quarter = start.year, ((start.month - 1) // 3) + 1
        while (year, quarter) <= (end.year, ((end.month - 1) // 3) + 1):
            month = quarter * 3
            candidate = date(year, month, 1)
            if candidate < start:
                candidate = start
            if candidate <= end:
                periods.append(candidate)
            quarter += 1
            if quarter == 5:
                year, quarter = year + 1, 1
        return tuple(periods)
    if rule in ("daily", "membership_effective"):
        return tuple(_days(start, end))
    return ()


def missing_dates(expected: Iterable[date], covered: Iterable[date]) -> tuple[date, ...]:
    covered_set = set(covered)
    return tuple(day for day in expected if day not in covered_set)


def longest_interval(days: Iterable[date]) -> dict[str, object] | None:
    ordered = sorted(set(days))
    if not ordered:
        return None
    best_start = current_start = ordered[0]
    best_end = current_end = ordered[0]
    for day in ordered[1:]:
        if day == current_end + timedelta(days=1):
            current_end = day
        else:
            if (current_end - current_start) > (best_end - best_start):
                best_start, best_end = current_start, current_end
            current_start = current_end = day
    if (current_end - current_start) > (best_end - best_start):
        best_start, best_end = current_start, current_end
    return {"start_date": best_start.isoformat(), "end_date": best_end.isoformat(), "days": (best_end - best_start).days + 1}


def _days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)