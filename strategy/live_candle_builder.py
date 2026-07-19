from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd


UTC = ZoneInfo("UTC")


@dataclass
class LiveQuoteSnapshot:
    price: Optional[float]
    total_volume: Optional[float]
    quote_time_utc: Optional[datetime]


class LiveMinuteCandleBuilder:
    def __init__(self, symbol: str, max_candles: int = 3):
        self.symbol = symbol
        self.max_candles = max_candles
        self._candles: OrderedDict[datetime, dict] = OrderedDict()
        self._last_total_volume: Optional[float] = None

    def update_from_quote_payload(self, payload: dict) -> LiveQuoteSnapshot:
        snapshot = self._extract_snapshot(payload)
        if snapshot.price is None or snapshot.quote_time_utc is None:
            return snapshot

        minute_dt = snapshot.quote_time_utc.astimezone(UTC).replace(second=0, microsecond=0)
        delta_volume = 0.0
        if snapshot.total_volume is not None and self._last_total_volume is not None:
            delta_volume = max(0.0, float(snapshot.total_volume) - float(self._last_total_volume))
        if snapshot.total_volume is not None:
            self._last_total_volume = float(snapshot.total_volume)

        candle = self._candles.get(minute_dt)
        if candle is None:
            candle = {
                "datetime": minute_dt,
                "open": float(snapshot.price),
                "high": float(snapshot.price),
                "low": float(snapshot.price),
                "close": float(snapshot.price),
                "volume": float(max(0.0, delta_volume)),
            }
            self._candles[minute_dt] = candle
        else:
            candle["high"] = max(float(candle["high"]), float(snapshot.price))
            candle["low"] = min(float(candle["low"]), float(snapshot.price))
            candle["close"] = float(snapshot.price)
            candle["volume"] = float(candle.get("volume", 0.0) or 0.0) + float(max(0.0, delta_volume))

        while len(self._candles) > self.max_candles:
            self._candles.popitem(last=False)

        return snapshot

    def as_dataframe(self) -> pd.DataFrame:
        if not self._candles:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
        return pd.DataFrame(list(self._candles.values()))

    def latest_price(self) -> Optional[float]:
        if not self._candles:
            return None
        latest = next(reversed(self._candles.values()))
        try:
            return float(latest.get("close"))
        except (TypeError, ValueError):
            return None

    def merge_with_history(self, history_df: pd.DataFrame) -> pd.DataFrame:
        local_df = self.as_dataframe()
        if history_df is None or history_df.empty:
            merged = local_df.copy()
        elif local_df.empty:
            merged = history_df.copy()
        else:
            merged = pd.concat([history_df.copy(), local_df], ignore_index=True)

        if merged.empty:
            return merged

        merged = merged.copy()
        merged["datetime"] = pd.to_datetime(merged["datetime"], utc=True)
        merged = merged.drop_duplicates(subset=["datetime"], keep="last")
        merged = merged.sort_values("datetime").reset_index(drop=True)
        return merged

    def _extract_snapshot(self, payload: dict) -> LiveQuoteSnapshot:
        quote_blob = payload.get(self.symbol) or next(iter(payload.values()), {})
        quote = quote_blob.get("quote") or {}
        regular = quote_blob.get("regular") or {}
        extended = quote_blob.get("extended") or {}

        def _to_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        price = None
        for value in (
            quote.get("mark"),
            quote.get("lastPrice"),
            regular.get("regularMarketLastPrice"),
            extended.get("lastPrice"),
            quote.get("closePrice"),
        ):
            price = _to_float(value)
            if price is not None and price > 0:
                break

        total_volume = None
        for value in (
            quote.get("totalVolume"),
            extended.get("totalVolume"),
        ):
            total_volume = _to_float(value)
            if total_volume is not None:
                break

        # Some Schwab payloads include multiple clock fields where one can lag.
        # Use the newest valid timestamp so continuity checks do not reject fresh quotes.
        quote_time_utc = None
        latest_ms = None
        for value in (
            quote.get("quoteTime"),
            quote.get("tradeTime"),
            regular.get("regularMarketTradeTime"),
            extended.get("tradeTime"),
        ):
            try:
                ts_ms = int(value)
            except (TypeError, ValueError):
                continue

            if ts_ms <= 0:
                continue
            if latest_ms is None or ts_ms > latest_ms:
                latest_ms = ts_ms

        if latest_ms is not None:
            try:
                quote_time_utc = datetime.fromtimestamp(latest_ms / 1000, tz=UTC)
            except OSError:
                quote_time_utc = None

        return LiveQuoteSnapshot(
            price=price,
            total_volume=total_volume,
            quote_time_utc=quote_time_utc,
        )