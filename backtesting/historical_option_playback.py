"""Historical option trade playback for replay/backtesting.

Uses Alpaca historical option trades as the primary option price source and
falls back to the synthetic EstimatedOptionPricer when historical trades are
not available for a timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict

import numpy as np
import pandas as pd

from backtesting.data_loader import TIMEZONE
from backtesting.option_pricer import EstimatedOptionPricer


@dataclass
class _DirectionalTradeSeries:
    timestamps_ns_utc: np.ndarray
    prices: np.ndarray


class AlpacaHistoricalTradePlayback:
    """Nearest-trade-at-or-before historical trade lookup by direction."""

    def __init__(self, call_trades: Optional[pd.DataFrame] = None, put_trades: Optional[pd.DataFrame] = None):
        self._series: Dict[str, _DirectionalTradeSeries] = {
            "CALL": self._build_series(call_trades),
            "PUT": self._build_series(put_trades),
        }

    @staticmethod
    def _build_series(df: Optional[pd.DataFrame]) -> _DirectionalTradeSeries:
        if df is None or df.empty:
            return _DirectionalTradeSeries(
                timestamps_ns_utc=np.array([], dtype=np.int64),
                prices=np.array([], dtype=np.float64),
            )

        work = df.copy()

        ts_col = "timestamp_et" if "timestamp_et" in work.columns else "timestamp"
        px_col = "p" if "p" in work.columns else "price"
        if ts_col not in work.columns or px_col not in work.columns:
            return _DirectionalTradeSeries(
                timestamps_ns_utc=np.array([], dtype=np.int64),
                prices=np.array([], dtype=np.float64),
            )

        ts = pd.to_datetime(work[ts_col], errors="coerce")
        ts = ts.dt.tz_localize(TIMEZONE) if ts.dt.tz is None else ts.dt.tz_convert(TIMEZONE)

        work = pd.DataFrame({"timestamp": ts, "price": pd.to_numeric(work[px_col], errors="coerce")})
        work = work.dropna(subset=["timestamp", "price"]).sort_values("timestamp")
        if work.empty:
            return _DirectionalTradeSeries(
                timestamps_ns_utc=np.array([], dtype=np.int64),
                prices=np.array([], dtype=np.float64),
            )

        ts_utc_ns = (
            work["timestamp"]
            .dt.tz_convert("UTC")
            .dt.tz_localize(None)
            .to_numpy(dtype="datetime64[ns]")
            .astype("int64")
        )
        prices = work["price"].astype(float).to_numpy()
        return _DirectionalTradeSeries(timestamps_ns_utc=ts_utc_ns, prices=prices)

    @classmethod
    def from_directory(cls, trade_data_dir: str | Path, trade_date: Optional[str] = None) -> "AlpacaHistoricalTradePlayback":
        root = Path(trade_data_dir)
        if not root.exists():
            return cls()

        def _select_file(direction: str) -> Optional[Path]:
            base = f"spy_{direction.lower()}_trades_"
            if trade_date:
                exact = root / f"{base}{trade_date}.csv"
                if exact.exists():
                    return exact
                return None
            candidates = sorted(root.glob(f"{base}*.csv"))
            return candidates[-1] if candidates else None

        call_file = _select_file("call")
        put_file = _select_file("put")

        call_df = pd.read_csv(call_file) if call_file else None
        put_df = pd.read_csv(put_file) if put_file else None
        return cls(call_trades=call_df, put_trades=put_df)

    def get_trade_price(self, direction: str, timestamp: pd.Timestamp) -> Optional[float]:
        key = str(direction).upper()
        if key not in self._series:
            return None

        series = self._series[key]
        if series.timestamps_ns_utc.size == 0:
            return None

        ts = pd.Timestamp(timestamp)
        ts = ts.tz_localize(TIMEZONE) if ts.tzinfo is None else ts.tz_convert(TIMEZONE)
        ts_ns_utc = int(
            ts.tz_convert("UTC")
            .tz_localize(None)
            .to_datetime64()
            .astype("datetime64[ns]")
            .astype("int64")
        )

        idx = int(np.searchsorted(series.timestamps_ns_utc, ts_ns_utc, side="right") - 1)
        if idx < 0:
            return None
        return float(series.prices[idx])


class HybridReplayOptionPricer:
    """Historical-trade-first replay pricer with synthetic fallback."""

    MODEL_NAME = "HISTORICAL_TRADE_PLAYBACK_WITH_ESTIMATED_FALLBACK"

    def __init__(
        self,
        synthetic_pricer: EstimatedOptionPricer,
        historical_playback: Optional[AlpacaHistoricalTradePlayback] = None,
    ):
        self.synthetic_pricer = synthetic_pricer
        self.historical_playback = historical_playback or AlpacaHistoricalTradePlayback()
        self.delta = synthetic_pricer.delta
        self.time_decay_per_minute = synthetic_pricer.time_decay_per_minute
        self.slippage = synthetic_pricer.slippage

    def get_entry_price(
        self,
        *,
        direction: Optional[str] = None,
        entry_time: Optional[pd.Timestamp] = None,
        entry_spy_price: Optional[float] = None,
    ) -> float:
        if direction and entry_time is not None:
            hist = self.historical_playback.get_trade_price(direction=direction, timestamp=pd.Timestamp(entry_time))
            if hist is not None and hist > 0:
                return hist
        return float(self.synthetic_pricer.get_entry_price())

    def get_option_mark_and_bid(
        self,
        *,
        direction: str,
        entry_spy_price: float,
        current_spy_price: float,
        entry_time: pd.Timestamp,
        current_time: pd.Timestamp,
    ) -> Tuple[float, float, str]:
        hist = self.historical_playback.get_trade_price(direction=direction, timestamp=pd.Timestamp(current_time))
        if hist is not None and hist > 0:
            return float(hist), float(hist), "HISTORICAL_TRADE"

        option_mark = float(
            self.synthetic_pricer.simulate_price_change(
                direction=direction,
                entry_spy_price=float(entry_spy_price),
                current_spy_price=float(current_spy_price),
                entry_time=pd.Timestamp(entry_time).to_pydatetime(),
                current_time=pd.Timestamp(current_time).to_pydatetime(),
                position="mid",
            )
        )
        option_bid = float(self.synthetic_pricer.get_bid_ask_adjusted_price(option_mark, side="bid"))
        return option_mark, option_bid, "ESTIMATED_FALLBACK"

    def simulate_price_change(self, *args, **kwargs):
        return self.synthetic_pricer.simulate_price_change(*args, **kwargs)

    def get_bid_ask_adjusted_price(self, *args, **kwargs):
        return self.synthetic_pricer.get_bid_ask_adjusted_price(*args, **kwargs)


def build_replay_option_pricer(
    *,
    entry_option_price: float,
    delta: float,
    slippage: float,
    trade_date: Optional[str] = None,
    trade_data_dir: str | Path = "data/alpaca_test",
) -> HybridReplayOptionPricer:
    synthetic = EstimatedOptionPricer(
        entry_option_price=entry_option_price,
        delta=delta,
        slippage=slippage,
    )
    playback = AlpacaHistoricalTradePlayback.from_directory(trade_data_dir=trade_data_dir, trade_date=trade_date)
    return HybridReplayOptionPricer(synthetic_pricer=synthetic, historical_playback=playback)
