from __future__ import annotations

from datetime import date, timedelta

from .types import CrossValidationFold


def _parse(d: str) -> date:
    return date.fromisoformat(d)


def _fmt(d: date) -> str:
    return d.isoformat()


def _validate_chronology(train_end: date, test_start: date) -> None:
    if train_end >= test_start:
        raise ValueError("training window must end before test window starts")


def build_cross_validation_folds(
    start_date: str,
    end_date: str,
    *,
    method: str,
    k: int = 5,
    purge_days: int = 0,
    embargo_days: int = 0,
    allow_shuffled_k_fold: bool = False,
) -> tuple[CrossValidationFold, ...]:
    start = _parse(start_date)
    end = _parse(end_date)
    if end <= start:
        raise ValueError("end_date must be > start_date")
    if purge_days < 0 or embargo_days < 0:
        raise ValueError("purge_days and embargo_days must be >= 0")
    total_days = max(1, (end - start).days)
    k = max(2, k)
    step = max(1, total_days // k)

    allowed = {"rolling", "expanding", "walk_forward", "k_fold", "out_of_time"}
    if method not in allowed:
        raise ValueError(f"unsupported cross-validation method: {method}")
    if method == "k_fold" and allow_shuffled_k_fold:
        raise ValueError("ordinary shuffled k-fold is prohibited for time-series research")

    folds: list[CrossValidationFold] = []
    for idx in range(k):
        if method == "rolling":
            train_start = start + timedelta(days=idx * step)
            train_end = min(end - timedelta(days=step), train_start + timedelta(days=step * 2))
            test_start = train_end + timedelta(days=1 + purge_days + embargo_days)
            test_end = min(end, test_start + timedelta(days=step - 1))
        elif method in {"expanding", "walk_forward"}:
            train_start = start
            train_end = min(end - timedelta(days=step), start + timedelta(days=(idx + 1) * step))
            test_start = train_end + timedelta(days=1 + purge_days + embargo_days)
            test_end = min(end, test_start + timedelta(days=step - 1))
        elif method == "k_fold":
            fold_size = step
            test_start = start + timedelta(days=(idx + 1) * fold_size)
            test_end = min(end, test_start + timedelta(days=fold_size - 1))
            train_start = start
            train_end = test_start - timedelta(days=1 + purge_days)
        elif method == "out_of_time":
            train_start = start
            train_end = start + timedelta(days=int(total_days * 0.7))
            test_start = train_end + timedelta(days=1 + purge_days + embargo_days)
            test_end = end

        if train_end <= train_start:
            raise ValueError("undersized training fold")
        if test_end < test_start:
            raise ValueError("undersized test fold")
        _validate_chronology(train_end, test_start)

        fold = CrossValidationFold(
            method=method,
            fold_id=f"{method}_{idx + 1:02d}",
            train_start=_fmt(train_start),
            train_end=_fmt(train_end),
            test_start=_fmt(test_start),
            test_end=_fmt(test_end),
        )
        folds.append(fold)
    return tuple(folds)
