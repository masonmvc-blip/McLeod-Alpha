from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from typing import Callable, Optional


@dataclass
class OptionQuoteSnapshot:
    symbol: str
    bid: Optional[float]
    ask: Optional[float]
    mark: Optional[float]
    last: Optional[float]
    fetched_at: datetime


class ActiveOptionQuoteCache:
    def __init__(self, fetch_func: Callable[[str], dict], ttl_seconds: float = 1.0):
        self.fetch_func = fetch_func
        self.ttl = timedelta(seconds=ttl_seconds)
        self._snapshot: Optional[OptionQuoteSnapshot] = None
        self._lock = threading.Lock()
        self._refresh_inflight = False

    def clear(self):
        with self._lock:
            self._snapshot = None
            self._refresh_inflight = False

    @staticmethod
    def _coerce_aware(ts: Optional[datetime]) -> datetime:
        """Normalize datetimes so subtraction cannot fail on naive/aware mismatch."""
        if ts is None:
            return datetime.now(timezone.utc)
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    def _build_snapshot(self, symbol: str, payload: dict, fetched_at: Optional[datetime] = None) -> OptionQuoteSnapshot:
        quote_blob = payload.get(symbol) or next(iter(payload.values()), {})
        quote = quote_blob.get("quote") or {}

        def _to_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return OptionQuoteSnapshot(
            symbol=symbol,
            bid=_to_float(quote.get("bidPrice")),
            ask=_to_float(quote.get("askPrice")),
            mark=_to_float(quote.get("mark")),
            last=_to_float(quote.get("lastPrice")),
            fetched_at=self._coerce_aware(fetched_at),
        )

    def _refresh_async(self, symbol: str):
        try:
            payload = self.fetch_func(symbol)
            snapshot = self._build_snapshot(symbol, payload, fetched_at=datetime.now(timezone.utc))
            with self._lock:
                self._snapshot = snapshot
        except Exception:
            pass
        finally:
            with self._lock:
                self._refresh_inflight = False

    def get(self, symbol: Optional[str], now: Optional[datetime] = None) -> Optional[OptionQuoteSnapshot]:
        if not symbol:
            self.clear()
            return None

        now = self._coerce_aware(now)
        with self._lock:
            snapshot = self._snapshot
            refresh_inflight = self._refresh_inflight

        if snapshot and snapshot.symbol == symbol and now - snapshot.fetched_at < self.ttl:
            return snapshot

        # Bootstrap fetch is synchronous to preserve existing behavior.
        if snapshot is None or snapshot.symbol != symbol:
            payload = self.fetch_func(symbol)
            built = self._build_snapshot(symbol, payload, fetched_at=now)
            with self._lock:
                self._snapshot = built
            return built

        # Stale-while-refresh: return last known quote immediately and refresh in background.
        if not refresh_inflight:
            with self._lock:
                if not self._refresh_inflight:
                    self._refresh_inflight = True
                    threading.Thread(
                        target=self._refresh_async,
                        args=(symbol,),
                        name="option-quote-refresh",
                        daemon=True,
                    ).start()

        return snapshot