from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd


EASTERN_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")
EVALUATION_SECOND = 1


@dataclass
class SignalCycleDecision:
    evaluation_time: datetime
    cycle_minute: datetime
    expected_candle_time: datetime
    status: str
    reason: str
    attempted: bool
    should_manage_position: bool
    should_evaluate: bool
    candle_timestamp: Optional[datetime] = None
    candle_age_seconds: Optional[float] = None
    completed_df: Optional[pd.DataFrame] = None
    last_row: Optional[pd.Series] = None
    prev_row: Optional[pd.Series] = None


def normalize_timestamp(value, default_tz=UTC_TZ) -> Optional[datetime]:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(default_tz)
    return timestamp.to_pydatetime()


def _to_eastern(value) -> Optional[datetime]:
    timestamp = normalize_timestamp(value)
    if timestamp is None:
        return None
    timestamp = pd.Timestamp(timestamp)
    return timestamp.tz_convert(EASTERN_TZ).to_pydatetime()


def _extract_candle_timestamp(row: Optional[pd.Series]) -> Optional[datetime]:
    if row is None:
        return None
    if "datetime" in row.index:
        return _to_eastern(row["datetime"])
    return _to_eastern(row.name)


def compute_completed_candles(df: pd.DataFrame, now_et: Optional[datetime] = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if now_et is None:
        return df.iloc[:-1].copy() if len(df) > 1 else df.copy()

    now_et = now_et.astimezone(EASTERN_TZ)
    last_ts = _extract_candle_timestamp(df.iloc[-1])
    if last_ts is None:
        return df.iloc[:-1].copy() if len(df) > 1 else df.copy()

    current_minute = now_et.replace(second=0, microsecond=0)
    last_minute = last_ts.astimezone(EASTERN_TZ).replace(second=0, microsecond=0)
    if last_minute >= current_minute and len(df) > 1:
        return df.iloc[:-1].copy()
    return df.copy()


def should_attempt_evaluation(now_et: datetime, last_cycle_minute: Optional[datetime]) -> bool:
    cycle_minute = now_et.astimezone(EASTERN_TZ).replace(second=0, microsecond=0)
    if now_et.astimezone(EASTERN_TZ).second < EVALUATION_SECOND:
        return False
    if last_cycle_minute is None:
        return True
    return cycle_minute > last_cycle_minute.astimezone(EASTERN_TZ).replace(second=0, microsecond=0)


def plan_signal_cycle(
    df: pd.DataFrame,
    now_et: datetime,
    last_cycle_minute: Optional[datetime] = None,
    last_evaluated_candle_time: Optional[datetime] = None,
    force_attempt: bool = False,
) -> SignalCycleDecision:
    now_et = now_et.astimezone(EASTERN_TZ)
    cycle_minute = now_et.replace(second=0, microsecond=0)
    expected_candle_time = cycle_minute - timedelta(minutes=1)

    if (not force_attempt) and (not should_attempt_evaluation(now_et, last_cycle_minute)):
        return SignalCycleDecision(
            evaluation_time=now_et,
            cycle_minute=cycle_minute,
            expected_candle_time=expected_candle_time,
            status="WAITING",
            reason="not evaluation second",
            attempted=False,
            should_manage_position=True,
            should_evaluate=False,
        )

    completed_df = compute_completed_candles(df, now_et=now_et)
    if len(completed_df) < 2:
        return SignalCycleDecision(
            evaluation_time=now_et,
            cycle_minute=cycle_minute,
            expected_candle_time=expected_candle_time,
            status="SKIPPED",
            reason="closed candle unavailable",
            attempted=True,
            should_manage_position=True,
            should_evaluate=False,
            completed_df=completed_df,
        )

    last_row = completed_df.iloc[-1]
    prev_row = completed_df.iloc[-2]
    candle_timestamp = _extract_candle_timestamp(last_row)

    if candle_timestamp is None or candle_timestamp.replace(second=0, microsecond=0) != expected_candle_time:
        return SignalCycleDecision(
            evaluation_time=now_et,
            cycle_minute=cycle_minute,
            expected_candle_time=expected_candle_time,
            status="SKIPPED",
            reason="closed candle unavailable",
            attempted=True,
            should_manage_position=True,
            should_evaluate=False,
            candle_timestamp=candle_timestamp,
            completed_df=completed_df,
            last_row=last_row,
            prev_row=prev_row,
        )

    candle_age_seconds = round((now_et - (candle_timestamp + timedelta(minutes=1))).total_seconds(), 1)

    if last_evaluated_candle_time is not None:
        last_evaluated_candle_time = last_evaluated_candle_time.astimezone(EASTERN_TZ).replace(second=0, microsecond=0)
        if candle_timestamp.replace(second=0, microsecond=0) == last_evaluated_candle_time:
            return SignalCycleDecision(
                evaluation_time=now_et,
                cycle_minute=cycle_minute,
                expected_candle_time=expected_candle_time,
                status="SKIPPED",
                reason="duplicate candle already evaluated",
                attempted=True,
                should_manage_position=True,
                should_evaluate=False,
                candle_timestamp=candle_timestamp,
                candle_age_seconds=candle_age_seconds,
                completed_df=completed_df,
                last_row=last_row,
                prev_row=prev_row,
            )

    return SignalCycleDecision(
        evaluation_time=now_et,
        cycle_minute=cycle_minute,
        expected_candle_time=expected_candle_time,
        status="EVALUATED",
        reason="closed candle ready",
        attempted=True,
        should_manage_position=True,
        should_evaluate=True,
        candle_timestamp=candle_timestamp,
        candle_age_seconds=candle_age_seconds,
        completed_df=completed_df,
        last_row=last_row,
        prev_row=prev_row,
    )