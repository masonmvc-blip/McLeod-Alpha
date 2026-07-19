from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd

from strategy.monitor_cycle import UTC_TZ, normalize_timestamp


FetchFunc = Callable[[datetime, datetime], pd.DataFrame]
IndicatorFunc = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass
class RollingMinuteHistoryCache:
    fetch_func: FetchFunc
    indicator_func: IndicatorFunc
    bootstrap_lookback: timedelta = timedelta(days=2)
    refresh_lookback: timedelta = timedelta(minutes=15)
    max_rows: int = 3000
    raw_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    indicator_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    last_refresh_at: Optional[datetime] = None

    def refresh(self, now: Optional[datetime] = None) -> pd.DataFrame:
        now = normalize_timestamp(now or datetime.now(), default_tz=UTC_TZ)

        if self.raw_df.empty:
            start = now - self.bootstrap_lookback
        else:
            latest_dt = self._latest_raw_datetime() or (now - self.refresh_lookback)
            start = min(latest_dt, now) - self.refresh_lookback

        incoming = self.fetch_func(start, now)
        self.raw_df = self._merge_frames(self.raw_df, incoming)
        self.indicator_df = self.indicator_func(self.raw_df.copy()) if not self.raw_df.empty else pd.DataFrame()
        self.last_refresh_at = now
        return self.indicator_df

    def latest_close(self) -> Optional[float]:
        if self.indicator_df is None or self.indicator_df.empty:
            return None
        try:
            return float(self.indicator_df.iloc[-1]["close"])
        except (TypeError, ValueError, KeyError):
            return None

    def _latest_raw_datetime(self) -> Optional[datetime]:
        if self.raw_df is None or self.raw_df.empty or "datetime" not in self.raw_df.columns:
            return None
        return normalize_timestamp(self.raw_df.iloc[-1]["datetime"], default_tz=UTC_TZ)

    def _merge_frames(self, base: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
        if incoming is None or incoming.empty:
            merged = base.copy()
        elif base is None or base.empty:
            merged = incoming.copy()
        else:
            merged = pd.concat([base, incoming], ignore_index=True)

        if merged.empty:
            return merged

        if "datetime" not in merged.columns:
            raise ValueError("Minute history cache requires a datetime column")

        merged = merged.copy()
        merged["datetime"] = pd.to_datetime(merged["datetime"], utc=True)

        merged = merged.drop_duplicates(subset=["datetime"], keep="last")
        merged = merged.sort_values("datetime").reset_index(drop=True)

        if self.max_rows and len(merged) > self.max_rows:
            merged = merged.tail(self.max_rows).reset_index(drop=True)

        return merged