"""Alpaca historical option-trade-backed full backtest engine.

This module is backtesting-only. It does not modify paper/live execution behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta, time as dt_time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from backtesting import load_csv_data, ReplayEngine
from backtesting.replay_trade_management import (
    evaluate_trade_management_step,
    initialize_trade_management_state,
)
from backtesting.signal_replay import SignalReplayEngine


ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

DATA_BASE_URL = "https://data.alpaca.markets"
TRADING_BASE_URL = "https://paper-api.alpaca.markets"

ENTRY_START = dt_time(9, 30, 0)
ENTRY_END = dt_time(15, 44, 59)
EOD_EXIT = dt_time(15, 59, 0)


@dataclass
class AvailabilityRow:
    trade_id: int
    signal_time: str
    direction: str
    option_symbol: str
    status: str
    reason: str


@dataclass
class BacktestTrade:
    trade_id: int
    entry_signal_time: datetime
    entry_fill_time: Optional[datetime]
    direction: str
    option_symbol: str
    entry_score: int
    entry_reasons: List[str]
    market_regime: str
    entry_spy_price: float
    option_entry: Optional[float]
    exit_trigger_time: Optional[datetime]
    exit_fill_time: Optional[datetime]
    exit_reason: str
    option_exit: Optional[float]
    option_pnl_dollars: Optional[float]
    option_pnl_pct: Optional[float]
    hold_duration_seconds: Optional[float]
    data_source: str
    excluded_from_official: bool
    data_unavailable_reason: str
    entry_fill_age_seconds: Optional[float] = None
    exit_fill_age_seconds: Optional[float] = None


class AlpacaClient:
    def __init__(self, api_key: str, api_secret: str):
        self.headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 5,
    ) -> Dict[str, Any]:
        for attempt in range(max_retries):
            resp = requests.request(method, url, headers=self.headers, params=params, timeout=45)
            if resp.status_code == 429:
                time.sleep(min(2 ** attempt, 10))
                continue
            if resp.status_code >= 400:
                msg = resp.text[:500].replace("\n", " ")
                raise RuntimeError(f"HTTP {resp.status_code} from {url}: {msg}")
            return resp.json()
        raise RuntimeError(f"Rate-limited repeatedly for {url}")

    def fetch_contracts_for_expiration(
        self,
        expiration: date,
        direction: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ctype = "call" if direction.upper() == "CALL" else "put"
        url = f"{TRADING_BASE_URL}/v2/options/contracts"
        out: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {
                "underlying_symbols": "SPY",
                "expiration_date": expiration.isoformat(),
                "type": ctype,
                "limit": 1000,
            }
            if status:
                params["status"] = status
            if page_token:
                params["page_token"] = page_token
            payload = self._request("GET", url, params=params)
            out.extend(payload.get("option_contracts", []))
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return out

    def fetch_contracts_for_window(
        self,
        start_expiration: date,
        end_expiration: date,
        direction: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ctype = "call" if direction.upper() == "CALL" else "put"
        url = f"{TRADING_BASE_URL}/v2/options/contracts"
        out: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {
                "underlying_symbols": "SPY",
                "expiration_date_gte": start_expiration.isoformat(),
                "expiration_date_lte": end_expiration.isoformat(),
                "type": ctype,
                "limit": 1000,
            }
            if status:
                params["status"] = status
            if page_token:
                params["page_token"] = page_token
            payload = self._request("GET", url, params=params)
            out.extend(payload.get("option_contracts", []))
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return out

    def fetch_snapshots_for_symbols(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        url = f"{DATA_BASE_URL}/v1beta1/options/snapshots"
        snapshots: Dict[str, Dict[str, Any]] = {}
        batch_size = 100
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            params = {"symbols": ",".join(batch)}
            payload = self._request("GET", url, params=params)
            snapshots.update(payload.get("snapshots", {}))
        return snapshots

    def download_trades(self, symbol: str, day: date) -> pd.DataFrame:
        start_et = datetime.combine(day, dt_time(0, 0, 0), tzinfo=ET)
        end_et = datetime.combine(day, dt_time(23, 59, 59), tzinfo=ET)

        params: Dict[str, Any] = {
            "symbols": symbol,
            "start": start_et.astimezone(UTC).isoformat(),
            "end": end_et.astimezone(UTC).isoformat(),
            "sort": "asc",
            "limit": 10000,
        }

        url = f"{DATA_BASE_URL}/v1beta1/options/trades"
        rows: List[Dict[str, Any]] = []
        while True:
            payload = self._request("GET", url, params=params)
            bucket = payload.get("trades", {})
            rows.extend(bucket.get(symbol, []))
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        ts_col = "t" if "t" in df.columns else "timestamp"
        px_col = "p" if "p" in df.columns else "price"
        if ts_col not in df.columns or px_col not in df.columns:
            return pd.DataFrame()

        df = df.rename(columns={ts_col: "timestamp", px_col: "price"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(ET)
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.dropna(subset=["timestamp", "price"]).sort_values("timestamp").reset_index(drop=True)
        return df


class SymbolTradeSeries:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        if self.df.empty:
            self.ts_index = pd.DatetimeIndex([], tz=ET)
            self.price_arr = np.array([], dtype=np.float64)
        else:
            self.ts_index = pd.DatetimeIndex(self.df["timestamp"])
            self.price_arr = self.df["price"].to_numpy(dtype=np.float64)

    def latest_at_or_before(self, ts: datetime) -> Optional[Tuple[datetime, float]]:
        if self.ts_index.empty:
            return None
        target = pd.Timestamp(ts).tz_convert(ET)
        idx = int(self.ts_index.searchsorted(target, side="right") - 1)
        if idx < 0:
            return None
        ts_out = self.ts_index[idx].to_pydatetime()
        return ts_out, float(self.price_arr[idx])

    def first_at_or_after(self, ts: datetime) -> Optional[Tuple[datetime, float]]:
        if self.ts_index.empty:
            return None
        target = pd.Timestamp(ts).tz_convert(ET)
        idx = int(self.ts_index.searchsorted(target, side="left"))
        if idx >= len(self.ts_index):
            return None
        ts_out = self.ts_index[idx].to_pydatetime()
        return ts_out, float(self.price_arr[idx])


class ManagementPricer:
    """Price source for evaluate_trade_management_step using historical trades only."""

    def __init__(self, series: SymbolTradeSeries):
        self.series = series

    def get_option_mark_and_bid(
        self,
        *,
        direction: str,
        entry_spy_price: float,
        current_spy_price: float,
        entry_time: datetime,
        current_time: datetime,
    ) -> Tuple[float, float, str]:
        point = self.series.latest_at_or_before(current_time)
        if point is None:
            # caller should avoid evaluating timestamps without available history,
            # but return a non-triggering placeholder if needed
            return 0.0, 0.0, "ALPACA_HISTORICAL_TRADE"
        _, price = point
        return price, price, "ALPACA_HISTORICAL_TRADE"


def _nearest_friday_at_least_7_days(entry_dt: datetime) -> date:
    d = entry_dt.date() + timedelta(days=7)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def _is_regular_entry_time(ts: datetime) -> bool:
    t = ts.timetz().replace(tzinfo=None)
    return ENTRY_START <= t <= ENTRY_END


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _load_env_creds() -> Tuple[str, str]:
    load_dotenv(".env")
    key = os.getenv("ALPACA_API_KEY", "").strip()
    sec = os.getenv("ALPACA_API_SECRET", "").strip()
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY / ALPACA_API_SECRET in .env")
    return key, sec


def _choose_direction(signal: Dict[str, Any]) -> Optional[Tuple[str, int, List[str]]]:
    call_q = bool(signal.get("call_qualified", False))
    put_q = bool(signal.get("put_qualified", False))
    call_s = int(signal.get("call_score", 0) or 0)
    put_s = int(signal.get("put_score", 0) or 0)
    if call_q and put_q:
        if call_s > put_s:
            return "CALL", call_s, list(signal.get("call_reasons", []))
        if put_s > call_s:
            return "PUT", put_s, list(signal.get("put_reasons", []))
        return None
    if call_q:
        return "CALL", call_s, list(signal.get("call_reasons", []))
    if put_q:
        return "PUT", put_s, list(signal.get("put_reasons", []))
    return None


def _build_signal_map(signals: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for s in signals:
        idx = int(s.get("_step_idx", -1))
        if idx >= 0:
            out[idx] = s
    return out


def _compute_drawdown(equity: List[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _profit_factor(pnls: List[float]) -> float:
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = sum(-p for p in pnls if p < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _expectancy(pnls: List[float]) -> float:
    if not pnls:
        return 0.0
    return sum(pnls) / len(pnls)


def _serialize_trade(t: BacktestTrade) -> Dict[str, Any]:
    d = asdict(t)
    for k in [
        "entry_signal_time",
        "entry_fill_time",
        "exit_trigger_time",
        "exit_fill_time",
    ]:
        v = d.get(k)
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _target_delta_for_direction(direction: str) -> float:
    return 0.45 if direction.upper() == "CALL" else -0.45


def _contract_type_for_selection(contract: Dict[str, Any]) -> str:
    ctype = str(contract.get("type") or "").strip().lower()
    if ctype in {"call", "put"}:
        return ctype
    symbol = str(contract.get("symbol") or "")
    if len(symbol) >= 9:
        marker = symbol[-9:-8]
        if marker == "C":
            return "call"
        if marker == "P":
            return "put"
    return ""


def _contract_expiration(contract: Dict[str, Any]) -> Optional[date]:
    text = contract.get("expiration_date")
    if not text:
        return None
    try:
        return pd.Timestamp(text).date()
    except Exception:
        return None


def _contract_strike(contract: Dict[str, Any]) -> Optional[float]:
    try:
        return float(contract.get("strike_price"))
    except Exception:
        return None


def _choose_historical_contract_from_contracts(
    *,
    contracts: List[Dict[str, Any]],
    direction: str,
    spy_entry: float,
    target_expiration: date,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    expected_type = "call" if direction.upper() == "CALL" else "put"

    if not contracts:
        diag = {
            "target_expiration": target_expiration.isoformat(),
            "number_of_contracts_returned": 0,
            "available_expirations": "",
            "available_strikes": "",
            "closest_strike": "",
            "closest_contract_symbol": "",
            "contract_status": "",
            "contract_expiration": "",
            "contract_strike": "",
            "contract_type": "",
            "rejection_reason": "NO_CONTRACTS_RETURNED_FOR_QUERY",
            "closest_candidate_rejection_reason": "",
        }
        return None, diag

    typed = [c for c in contracts if _contract_type_for_selection(c) == expected_type]
    available_expirations = sorted({e for e in (_contract_expiration(c) for c in typed) if e is not None})

    diag: Dict[str, Any] = {
        "target_expiration": target_expiration.isoformat(),
        "number_of_contracts_returned": len(contracts),
        "available_expirations": ";".join(d.isoformat() for d in available_expirations),
        "available_strikes": "",
        "closest_strike": "",
        "closest_contract_symbol": "",
        "contract_status": "",
        "contract_expiration": "",
        "contract_strike": "",
        "contract_type": "",
        "rejection_reason": "",
        "closest_candidate_rejection_reason": "",
    }

    if not typed:
        diag["rejection_reason"] = "CALL_PUT_TYPE_MISMATCH"
        return None, diag

    chosen_exp = None
    if target_expiration in available_expirations:
        chosen_exp = target_expiration
    else:
        future = [d for d in available_expirations if d >= target_expiration]
        if future:
            chosen_exp = min(future)

    if chosen_exp is None:
        diag["rejection_reason"] = "NO_ELIGIBLE_EXPIRATION"
        return None, diag

    same_exp = [c for c in typed if _contract_expiration(c) == chosen_exp]
    strike_contracts: List[Tuple[float, Dict[str, Any]]] = []
    for c in same_exp:
        strike = _contract_strike(c)
        if strike is None:
            continue
        strike_contracts.append((strike, c))

    if not strike_contracts:
        diag["rejection_reason"] = "NO_STRIKE_DATA"
        return None, diag

    unique_strikes = sorted({s for s, _ in strike_contracts})
    diag["available_strikes"] = ";".join(f"{x:.3f}" for x in unique_strikes)

    closest_strike, closest_contract = min(
        strike_contracts,
        key=lambda item: (abs(item[0] - spy_entry), -_safe_float(item[1].get("open_interest"), 0.0), str(item[1].get("symbol") or "")),
    )
    diag["closest_strike"] = f"{closest_strike:.3f}"
    diag["closest_contract_symbol"] = str(closest_contract.get("symbol") or "")

    selected = max(
        strike_contracts,
        key=lambda item: (
            _safe_float(item[1].get("open_interest"), 0.0),
            -abs(item[0] - spy_entry),
            str(item[1].get("symbol") or ""),
        ),
    )[1]

    diag["contract_status"] = str(selected.get("status") or "")
    exp = _contract_expiration(selected)
    diag["contract_expiration"] = exp.isoformat() if exp else ""
    strike = _contract_strike(selected)
    diag["contract_strike"] = f"{strike:.3f}" if strike is not None else ""
    diag["contract_type"] = _contract_type_for_selection(selected)

    return selected, diag


def _select_option_contract(
    client: AlpacaClient,
    entry_dt: datetime,
    direction: str,
    spy_entry: float,
    snapshot_cache_dir: Path,
) -> Optional[str]:
    expiration = _nearest_friday_at_least_7_days(entry_dt)
    cache_file = snapshot_cache_dir / f"SPY_{expiration.isoformat()}_{direction}.json"

    if cache_file.exists():
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        contracts = client.fetch_contracts_for_expiration(expiration=expiration, direction=direction)
        if not contracts:
            return None
        symbols = [str(c.get("symbol")) for c in contracts if c.get("symbol")]
        snapshots = client.fetch_snapshots_for_symbols(symbols)
        payload = {"contracts": contracts, "snapshots": snapshots}
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(payload), encoding="utf-8")

    contracts = payload.get("contracts", [])
    snapshots = payload.get("snapshots", {})

    candidates: List[Dict[str, Any]] = []
    for c in contracts:
        symbol = str(c.get("symbol") or "")
        if not symbol:
            continue
        snap = snapshots.get(symbol) or {}
        q = snap.get("latestQuote") or {}
        bid = _safe_float(q.get("bp"), 0.0)
        ask = _safe_float(q.get("ap"), 0.0)
        if bid <= 0 or ask <= 0:
            continue
        mark = (bid + ask) / 2.0
        if mark <= 0:
            continue
        spread = ask - bid
        spread_pct = (spread / mark) * 100.0
        if spread > 0.05 or spread_pct > 8.0:
            continue

        vol = int(_safe_float((snap.get("dailyBar") or {}).get("v"), 0.0))
        oi = int(_safe_float(c.get("open_interest"), 0.0))
        strike = _safe_float(c.get("strike_price"), 0.0)

        candidates.append(
            {
                "symbol": symbol,
                "volume": vol,
                "open_interest": oi,
                "strike": strike,
            }
        )

    if not candidates:
        return None

    best = max(
        candidates,
        key=lambda o: (
            o["volume"],
            o["open_interest"],
            -abs(float(o["strike"]) - float(spy_entry)),
        ),
    )
    return str(best["symbol"])


def run_alpaca_full_backtest(
    *,
    spy_csv_path: str,
    call_threshold: int = 5,
    put_threshold: int = 5,
    max_hold_minutes: int = 15,
    max_trades_per_day: int = 20,
    cache_root: str = "data/historical/options/alpaca",
    output_dir: str = "backtesting/output",
    spy_df: Optional[pd.DataFrame] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    diagnostics_limit: int = 100,
) -> Dict[str, Any]:
    def _emit(msg: str) -> None:
        if progress_callback is not None:
            progress_callback(msg)

    key, sec = _load_env_creds()
    client = AlpacaClient(key, sec)

    cache_root_path = Path(cache_root)
    trades_cache_dir = cache_root_path / "trades"
    snapshot_cache_dir = cache_root_path / "snapshots"
    trades_cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot_cache_dir.mkdir(parents=True, exist_ok=True)

    df = spy_df.copy() if spy_df is not None else load_csv_data(spy_csv_path)
    _emit(f"SPY data loaded: {len(df)} candles from {spy_csv_path}")

    replay_engine = ReplayEngine(df, include_premarket=True)
    signal_engine = SignalReplayEngine(
        replay_engine,
        call_threshold=call_threshold,
        put_threshold=put_threshold,
    )
    signals = signal_engine.replay()
    signal_map = _build_signal_map(signals)
    all_candles = replay_engine.get_candles_up_to_step(replay_engine.total_steps() - 1).copy()
    trading_dates = sorted(all_candles["timestamp"].dt.date.unique().tolist())
    _emit(f"Trading dates found: {len(trading_dates)}")
    _emit(f"Signals found: {len(signals)}")

    spy_by_day: Dict[date, pd.DataFrame] = {
        d: grp.sort_values("timestamp").reset_index(drop=True)
        for d, grp in all_candles.groupby(all_candles["timestamp"].dt.date)
    }

    trades: List[BacktestTrade] = []
    availability: List[AvailabilityRow] = []
    max_hold_audit_rows: List[Dict[str, Any]] = []
    contract_selection_diagnostics: List[Dict[str, Any]] = []

    open_trade: Optional[BacktestTrade] = None
    open_series: Optional[SymbolTradeSeries] = None
    open_pricer: Optional[ManagementPricer] = None
    open_state = None
    open_day: Optional[date] = None
    trades_today = 0
    accepted_trades = 0
    data_unavailable_trades = 0

    contracts_payload_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    trade_history_presence_cache: Dict[Tuple[str, str], bool] = {}

    def _load_or_download_symbol_day(symbol: str, day: date) -> pd.DataFrame:
        p = trades_cache_dir / f"{symbol}_{day.isoformat()}.csv"
        if p.exists():
            return pd.read_csv(p, parse_dates=["timestamp"]).assign(
                timestamp=lambda dfr: pd.to_datetime(dfr["timestamp"], utc=True).dt.tz_convert(ET)
            )
        df_trades = client.download_trades(symbol=symbol, day=day)
        if not df_trades.empty:
            out_df = df_trades.copy()
            out_df["timestamp"] = out_df["timestamp"].dt.tz_convert(UTC)
            out_df.to_csv(p, index=False)
        else:
            # persist empty marker file to avoid redownload loops
            pd.DataFrame(columns=["timestamp", "price"]).to_csv(p, index=False)
        return df_trades

    def _has_trade_history(symbol: str, day: date) -> bool:
        if not symbol:
            return False
        key = (symbol, day.isoformat())
        if key in trade_history_presence_cache:
            return trade_history_presence_cache[key]
        found = not _load_or_download_symbol_day(symbol, day).empty
        trade_history_presence_cache[key] = found
        return found

    def _select_option_contract_cached(entry_dt: datetime, direction: str, spy_entry: float) -> Tuple[Optional[str], Dict[str, Any]]:
        target_expiration = _nearest_friday_at_least_7_days(entry_dt)
        window_end = target_expiration + timedelta(days=14)
        cache_key = (target_expiration.isoformat(), direction)

        payload = contracts_payload_cache.get(cache_key)
        if payload is None:
            cache_file = snapshot_cache_dir / (
                f"SPY_{target_expiration.isoformat()}_{window_end.isoformat()}_{direction}_contracts.json"
            )
            if cache_file.exists():
                payload = json.loads(cache_file.read_text(encoding="utf-8"))
                _emit(
                    "Alpaca contracts loaded from cache: "
                    f"target_expiration={target_expiration.isoformat()} direction={direction}"
                )
            else:
                contracts = client.fetch_contracts_for_window(
                    start_expiration=target_expiration,
                    end_expiration=window_end,
                    direction=direction,
                    status=None,
                )
                payload = {"contracts": contracts}
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(payload), encoding="utf-8")
                _emit(
                    "Alpaca contracts downloaded: "
                    f"target_expiration={target_expiration.isoformat()} direction={direction} contracts={len(contracts)}"
                )
            contracts_payload_cache[cache_key] = payload

        contracts = payload.get("contracts", [])
        selected, diag = _choose_historical_contract_from_contracts(
            contracts=contracts,
            direction=direction,
            spy_entry=spy_entry,
            target_expiration=target_expiration,
        )

        selected_symbol = str((selected or {}).get("symbol") or "")
        closest_symbol = str(diag.get("closest_contract_symbol") or "")

        diag["signal_timestamp"] = entry_dt.isoformat()
        diag["direction"] = direction
        diag["spy_price"] = round(float(spy_entry), 6)
        diag["target_delta"] = _target_delta_for_direction(direction)
        diag["target_strike"] = round(float(spy_entry), 6)
        diag["snapshot_available"] = False
        diag["trade_history_available"] = _has_trade_history(selected_symbol or closest_symbol, entry_dt.date())

        if selected_symbol:
            return selected_symbol, diag

        if not diag.get("rejection_reason"):
            diag["rejection_reason"] = "NO_CONTRACT_MATCHING_PRODUCTION_RULES"
        return None, diag

    for step in range(replay_engine.total_steps()):
        candle = all_candles.iloc[step]
        ts = pd.Timestamp(candle["timestamp"]).to_pydatetime()
        day = ts.date()

        if open_day != day:
            trades_today = 0
            open_day = day
            _emit(f"Processing trading date: {day.isoformat()}")

        # manage open trade using option-trade timestamps + deadline + EOD priorities
        if open_trade is not None and open_series is not None and open_pricer is not None and open_state is not None:
            deadline = open_trade.entry_fill_time + timedelta(minutes=max_hold_minutes)
            eod_dt = datetime.combine(open_trade.entry_fill_time.date(), EOD_EXIT, tzinfo=ET)
            end_dt = min(deadline, eod_dt)

            # event timeline: option trade timestamps + hard deadlines (no future leakage)
            day_series = open_series.df[
                (open_series.df["timestamp"] >= open_trade.entry_fill_time)
                & (open_series.df["timestamp"] <= end_dt)
            ]
            events = set(pd.to_datetime(day_series["timestamp"]).dt.tz_convert(ET).to_list())
            events.add(pd.Timestamp(deadline))
            events.add(pd.Timestamp(eod_dt))
            event_times = sorted(events)

            trigger_time: Optional[datetime] = None
            trigger_reason: Optional[str] = None
            earlier_stop = False

            day_candles = spy_by_day.get(open_trade.entry_fill_time.date())
            if day_candles is None or day_candles.empty:
                day_candles = pd.DataFrame(columns=["timestamp", "close"])
            day_index = pd.DatetimeIndex(day_candles["timestamp"]) if not day_candles.empty else pd.DatetimeIndex([], tz=ET)
            day_close = day_candles["close"].to_numpy(dtype=np.float64) if not day_candles.empty else np.array([], dtype=np.float64)

            for ev in event_times:
                ev_dt = pd.Timestamp(ev).to_pydatetime()
                if ev_dt < open_trade.entry_fill_time:
                    continue

                if day_index.empty:
                    continue
                idx = int(day_index.searchsorted(pd.Timestamp(ev_dt), side="right") - 1)
                if idx < 0:
                    continue
                spy_px = float(day_close[idx])

                step_result = evaluate_trade_management_step(
                    state=open_state,
                    pricer=open_pricer,
                    current_spy_price=spy_px,
                    current_time=ev_dt,
                    eod_exit_time=EOD_EXIT,
                    max_hold_minutes=max_hold_minutes,
                )

                if step_result.exit_decision == "EXIT":
                    trigger_time = ev_dt
                    trigger_reason = step_result.exit_reason
                    if trigger_reason in {"INITIAL_STOP", "TRAILING_STOP"} and ev_dt < deadline:
                        earlier_stop = True
                    break

            if trigger_time is not None and trigger_reason is not None:
                exit_fill = open_series.first_at_or_after(trigger_time)
                if exit_fill is None:
                    open_trade.exit_reason = trigger_reason
                    open_trade.exit_trigger_time = trigger_time
                    open_trade.excluded_from_official = True
                    open_trade.data_unavailable_reason = "DATA_UNAVAILABLE_EXIT_FILL"
                    open_trade.data_source = "ALPACA_HISTORICAL_TRADE"
                    availability.append(
                        AvailabilityRow(
                            trade_id=open_trade.trade_id,
                            signal_time=open_trade.entry_signal_time.isoformat(),
                            direction=open_trade.direction,
                            option_symbol=open_trade.option_symbol,
                            status="DATA_UNAVAILABLE",
                            reason="NO_EXIT_TRADE_AT_OR_AFTER_TRIGGER",
                        )
                    )
                else:
                    ex_ts, ex_px = exit_fill
                    open_trade.exit_trigger_time = trigger_time
                    open_trade.exit_fill_time = ex_ts
                    open_trade.exit_reason = trigger_reason
                    open_trade.option_exit = ex_px
                    open_trade.option_pnl_dollars = (ex_px - float(open_trade.option_entry)) * 100.0
                    open_trade.option_pnl_pct = ((ex_px - float(open_trade.option_entry)) / float(open_trade.option_entry)) * 100.0
                    open_trade.hold_duration_seconds = (ex_ts - open_trade.entry_fill_time).total_seconds()
                    open_trade.exit_fill_age_seconds = (ex_ts - trigger_time).total_seconds()
                    open_trade.data_source = "ALPACA_HISTORICAL_TRADE"

                    if trigger_reason == "MAX_HOLD_15_MIN":
                        deadline_dt = open_trade.entry_fill_time + timedelta(minutes=max_hold_minutes)
                        max_hold_audit_rows.append(
                            {
                                "trade_id": open_trade.trade_id,
                                "direction": open_trade.direction,
                                "option_symbol": open_trade.option_symbol,
                                "entry_signal_time": open_trade.entry_signal_time.isoformat(),
                                "entry_fill_time": open_trade.entry_fill_time.isoformat(),
                                "max_hold_deadline": deadline_dt.isoformat(),
                                "actual_exit_time": ex_ts.isoformat(),
                                "elapsed_seconds": round(open_trade.hold_duration_seconds, 6),
                                "seconds_after_deadline": round((ex_ts - deadline_dt).total_seconds(), 6),
                                "option_entry": round(float(open_trade.option_entry), 6),
                                "option_exit": round(float(ex_px), 6),
                                "option_pnl_dollars": round(float(open_trade.option_pnl_dollars), 6),
                                "option_pnl_pct": round(float(open_trade.option_pnl_pct), 6),
                                "earlier_stop_triggered": bool(earlier_stop),
                                "exit_reason": trigger_reason,
                                "data_source": "ALPACA_HISTORICAL_TRADE",
                            }
                        )

                trades.append(open_trade)
                open_trade = None
                open_series = None
                open_pricer = None
                open_state = None

        # attempt new entry only when flat
        if open_trade is not None:
            continue

        signal = signal_map.get(step)
        if not signal:
            continue

        choice = _choose_direction(signal)
        if choice is None:
            continue

        direction, entry_score, entry_reasons = choice
        if not _is_regular_entry_time(ts):
            continue
        if trades_today >= max_trades_per_day:
            continue

        entry_spy = float(candle["close"])
        option_symbol, select_diag = _select_option_contract_cached(entry_dt=ts, direction=direction, spy_entry=entry_spy)

        trade_id = len(trades) + (1 if open_trade is None else 2)
        if not option_symbol:
            data_unavailable_trades += 1
            if len(contract_selection_diagnostics) < diagnostics_limit:
                contract_selection_diagnostics.append(
                    {
                        "signal_timestamp": select_diag.get("signal_timestamp", ts.isoformat()),
                        "direction": select_diag.get("direction", direction),
                        "spy_price": select_diag.get("spy_price", entry_spy),
                        "target_expiration": select_diag.get("target_expiration", ""),
                        "target_delta": select_diag.get("target_delta", _target_delta_for_direction(direction)),
                        "target_strike": select_diag.get("target_strike", entry_spy),
                        "number_of_contracts_returned": select_diag.get("number_of_contracts_returned", 0),
                        "available_expirations": select_diag.get("available_expirations", ""),
                        "available_strikes": select_diag.get("available_strikes", ""),
                        "closest_strike": select_diag.get("closest_strike", ""),
                        "closest_contract_symbol": select_diag.get("closest_contract_symbol", ""),
                        "contract_status": select_diag.get("contract_status", ""),
                        "contract_expiration": select_diag.get("contract_expiration", ""),
                        "contract_strike": select_diag.get("contract_strike", ""),
                        "contract_type": select_diag.get("contract_type", ""),
                        "snapshot_available": select_diag.get("snapshot_available", False),
                        "trade_history_available": select_diag.get("trade_history_available", False),
                        "rejection_reason": select_diag.get("rejection_reason", "NO_CONTRACT_MATCHING_PRODUCTION_RULES"),
                        "closest_candidate_rejection_reason": select_diag.get("closest_candidate_rejection_reason", ""),
                    }
                )
            availability.append(
                AvailabilityRow(
                    trade_id=trade_id,
                    signal_time=ts.isoformat(),
                    direction=direction,
                    option_symbol="",
                    status="DATA_UNAVAILABLE",
                    reason="NO_CONTRACT_MATCHING_PRODUCTION_RULES",
                )
            )
            trades.append(
                BacktestTrade(
                    trade_id=trade_id,
                    entry_signal_time=ts,
                    entry_fill_time=None,
                    direction=direction,
                    option_symbol="",
                    entry_score=entry_score,
                    entry_reasons=entry_reasons,
                    market_regime=str(signal.get("market_regime", "UNKNOWN")),
                    entry_spy_price=entry_spy,
                    option_entry=None,
                    exit_trigger_time=None,
                    exit_fill_time=None,
                    exit_reason="DATA_UNAVAILABLE",
                    option_exit=None,
                    option_pnl_dollars=None,
                    option_pnl_pct=None,
                    hold_duration_seconds=None,
                    data_source="ALPACA_HISTORICAL_TRADE",
                    excluded_from_official=True,
                    data_unavailable_reason="NO_CONTRACT",
                )
            )
            if data_unavailable_trades % 100 == 0:
                _emit(f"DATA_UNAVAILABLE trades: {data_unavailable_trades}")
            continue

        day_trades = _load_or_download_symbol_day(option_symbol, ts.date())
        series = SymbolTradeSeries(day_trades)
        entry_fill = series.first_at_or_after(ts)
        if entry_fill is None:
            data_unavailable_trades += 1
            availability.append(
                AvailabilityRow(
                    trade_id=trade_id,
                    signal_time=ts.isoformat(),
                    direction=direction,
                    option_symbol=option_symbol,
                    status="DATA_UNAVAILABLE",
                    reason="NO_ENTRY_TRADE_AT_OR_AFTER_SIGNAL",
                )
            )
            trades.append(
                BacktestTrade(
                    trade_id=trade_id,
                    entry_signal_time=ts,
                    entry_fill_time=None,
                    direction=direction,
                    option_symbol=option_symbol,
                    entry_score=entry_score,
                    entry_reasons=entry_reasons,
                    market_regime=str(signal.get("market_regime", "UNKNOWN")),
                    entry_spy_price=entry_spy,
                    option_entry=None,
                    exit_trigger_time=None,
                    exit_fill_time=None,
                    exit_reason="DATA_UNAVAILABLE",
                    option_exit=None,
                    option_pnl_dollars=None,
                    option_pnl_pct=None,
                    hold_duration_seconds=None,
                    data_source="ALPACA_HISTORICAL_TRADE",
                    excluded_from_official=True,
                    data_unavailable_reason="NO_ENTRY_FILL",
                )
            )
            if data_unavailable_trades % 100 == 0:
                _emit(f"DATA_UNAVAILABLE trades: {data_unavailable_trades}")
            continue

        en_ts, en_px = entry_fill
        open_trade = BacktestTrade(
            trade_id=trade_id,
            entry_signal_time=ts,
            entry_fill_time=en_ts,
            direction=direction,
            option_symbol=option_symbol,
            entry_score=entry_score,
            entry_reasons=entry_reasons,
            market_regime=str(signal.get("market_regime", "UNKNOWN")),
            entry_spy_price=entry_spy,
            option_entry=en_px,
            exit_trigger_time=None,
            exit_fill_time=None,
            exit_reason="",
            option_exit=None,
            option_pnl_dollars=None,
            option_pnl_pct=None,
            hold_duration_seconds=None,
            data_source="ALPACA_HISTORICAL_TRADE",
            excluded_from_official=False,
            data_unavailable_reason="",
            entry_fill_age_seconds=(en_ts - ts).total_seconds(),
        )
        open_series = series
        open_pricer = ManagementPricer(series)
        open_state = initialize_trade_management_state(
            entry_time=en_ts,
            direction=direction,
            entry_spy_price=entry_spy,
            entry_option_price=en_px,
        )
        accepted_trades += 1
        if accepted_trades % 10 == 0:
            _emit(f"Accepted trades: {accepted_trades}")
        trades_today += 1

    # close dangling open trade as unavailable if still open by end of dataset
    if open_trade is not None:
        open_trade.exit_reason = "DATA_UNAVAILABLE"
        open_trade.excluded_from_official = True
        open_trade.data_unavailable_reason = "NO_EXIT_TRIGGER_IN_RANGE"
        trades.append(open_trade)

    # official stats exclude data-unavailable rows
    official = [t for t in trades if not t.excluded_from_official and t.option_pnl_dollars is not None]
    pnls = [float(t.option_pnl_dollars) for t in official]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    equity = []
    running = 0.0
    for p in pnls:
        running += p
        equity.append(running)

    by_exit: Dict[str, Dict[str, float]] = {}
    by_hour: Dict[str, Dict[str, float]] = {}
    by_regime: Dict[str, Dict[str, float]] = {}
    by_score: Dict[str, Dict[str, float]] = {}
    by_dir: Dict[str, Dict[str, float]] = {"CALL": {"count": 0, "wins": 0, "pnl": 0.0}, "PUT": {"count": 0, "wins": 0, "pnl": 0.0}}

    for t in official:
        p = float(t.option_pnl_dollars)
        r = t.exit_reason
        by_exit.setdefault(r, {"count": 0, "wins": 0, "pnl": 0.0})
        by_exit[r]["count"] += 1
        by_exit[r]["wins"] += 1 if p > 0 else 0
        by_exit[r]["pnl"] += p

        hr = str(pd.Timestamp(t.entry_fill_time).hour)
        by_hour.setdefault(hr, {"count": 0, "wins": 0, "pnl": 0.0})
        by_hour[hr]["count"] += 1
        by_hour[hr]["wins"] += 1 if p > 0 else 0
        by_hour[hr]["pnl"] += p

        rg = str(t.market_regime)
        by_regime.setdefault(rg, {"count": 0, "wins": 0, "pnl": 0.0})
        by_regime[rg]["count"] += 1
        by_regime[rg]["wins"] += 1 if p > 0 else 0
        by_regime[rg]["pnl"] += p

        sc = str(t.entry_score)
        by_score.setdefault(sc, {"count": 0, "wins": 0, "pnl": 0.0})
        by_score[sc]["count"] += 1
        by_score[sc]["wins"] += 1 if p > 0 else 0
        by_score[sc]["pnl"] += p

        by_dir[t.direction]["count"] += 1
        by_dir[t.direction]["wins"] += 1 if p > 0 else 0
        by_dir[t.direction]["pnl"] += p

    max_hold_trades = [t for t in official if t.exit_reason == "MAX_HOLD_15_MIN"]
    hold_seconds = [float(t.hold_duration_seconds) for t in official if t.hold_duration_seconds is not None]
    deadline_delays = [float(t.exit_fill_age_seconds) for t in max_hold_trades if t.exit_fill_age_seconds is not None]

    max_hold_failures = 0
    for row in max_hold_audit_rows:
        if row["elapsed_seconds"] < 900:
            max_hold_failures += 1
        if row["seconds_after_deadline"] < 0:
            max_hold_failures += 1

    summary = {
        "historical_date_range": {
            "start": str(all_candles["timestamp"].min()),
            "end": str(all_candles["timestamp"].max()),
        },
        "trading_days": int(all_candles["timestamp"].dt.date.nunique()),
        "signals_generated": len(signals),
        "trades_with_usable_alpaca_data": len(official),
        "trades_excluded_data_unavailable": len([t for t in trades if t.excluded_from_official]),
        "completed_trades": len(official),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate_pct": (len(winners) / len(official) * 100.0) if official else 0.0,
        "net_pnl": sum(pnls),
        "profit_factor": _profit_factor(pnls),
        "expectancy": _expectancy(pnls),
        "maximum_drawdown": _compute_drawdown(equity),
        "call_vs_put": by_dir,
        "by_entry_score": by_score,
        "by_exit_reason": by_exit,
        "by_hour": by_hour,
        "by_market_regime": by_regime,
        "max_hold_count": len(max_hold_trades),
        "max_hold_pnl": sum(float(t.option_pnl_dollars) for t in max_hold_trades),
        "average_hold_duration_seconds": (sum(hold_seconds) / len(hold_seconds)) if hold_seconds else 0.0,
        "median_hold_duration_seconds": float(pd.Series(hold_seconds).median()) if hold_seconds else 0.0,
        "average_delay_after_max_hold_deadline_seconds": (sum(deadline_delays) / len(deadline_delays)) if deadline_delays else 0.0,
        "earliest_exit_timing_error_seconds": min(deadline_delays) if deadline_delays else 0.0,
        "latest_exit_timing_error_seconds": max(deadline_delays) if deadline_delays else 0.0,
        "max_hold_audit_failures": max_hold_failures,
        "data_source_label": "ALPACA_HISTORICAL_TRADE",
        "execution_note": "Historical option trades are prints, not guaranteed executable bid/ask fills.",
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trades_df = pd.DataFrame([_serialize_trade(t) for t in trades])
    trades_path = out_dir / "alpaca_full_backtest_trades.csv"
    trades_df.to_csv(trades_path, index=False)

    summary_path = out_dir / "alpaca_full_backtest_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    max_hold_path = out_dir / "max_hold_audit.csv"
    pd.DataFrame(max_hold_audit_rows).to_csv(max_hold_path, index=False)

    availability_df = pd.DataFrame([asdict(r) for r in availability])
    availability_path = out_dir / "data_availability_report.csv"
    availability_df.to_csv(availability_path, index=False)

    diagnostics_path = out_dir / "contract_selection_diagnostics.csv"
    pd.DataFrame(contract_selection_diagnostics).to_csv(diagnostics_path, index=False)

    report_lines = [
        "ALPACA FULL BACKTEST REPORT",
        "=" * 80,
        f"Historical date range: {summary['historical_date_range']['start']} -> {summary['historical_date_range']['end']}",
        f"Trading days: {summary['trading_days']}",
        f"Signals generated: {summary['signals_generated']}",
        f"Trades with usable Alpaca data: {summary['trades_with_usable_alpaca_data']}",
        f"Trades excluded as DATA_UNAVAILABLE: {summary['trades_excluded_data_unavailable']}",
        f"Completed trades: {summary['completed_trades']}",
        f"Winners: {summary['winners']} | Losers: {summary['losers']}",
        f"Win rate: {summary['win_rate_pct']:.2f}%",
        f"Net P/L: ${summary['net_pnl']:.2f}",
        f"Profit factor: {summary['profit_factor']:.4f}",
        f"Expectancy: {summary['expectancy']:.4f}",
        f"Maximum drawdown: {summary['maximum_drawdown']:.4f}",
        f"MAX_HOLD_15_MIN count: {summary['max_hold_count']} | P/L: ${summary['max_hold_pnl']:.2f}",
        f"Average hold duration (s): {summary['average_hold_duration_seconds']:.4f}",
        f"Median hold duration (s): {summary['median_hold_duration_seconds']:.4f}",
        f"Average delay after max-hold deadline (s): {summary['average_delay_after_max_hold_deadline_seconds']:.4f}",
        f"Earliest exit timing error (s): {summary['earliest_exit_timing_error_seconds']:.4f}",
        f"Latest exit timing error (s): {summary['latest_exit_timing_error_seconds']:.4f}",
        f"Max-hold audit failures: {summary['max_hold_audit_failures']}",
        f"Data source: {summary['data_source_label']}",
        f"Note: {summary['execution_note']}",
        "",
        "CALL vs PUT:",
        json.dumps(summary["call_vs_put"], indent=2),
        "",
        "By entry score:",
        json.dumps(summary["by_entry_score"], indent=2),
        "",
        "By exit reason:",
        json.dumps(summary["by_exit_reason"], indent=2),
        "",
        "By hour:",
        json.dumps(summary["by_hour"], indent=2),
        "",
        "By market regime:",
        json.dumps(summary["by_market_regime"], indent=2),
    ]

    report_path = out_dir / "alpaca_full_backtest_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    _emit(f"Accepted trades: {accepted_trades}")
    _emit(f"DATA_UNAVAILABLE trades: {len([t for t in trades if t.excluded_from_official])}")
    _emit(f"Output path: {trades_path}")
    _emit(f"Output path: {summary_path}")
    _emit(f"Output path: {report_path}")
    _emit(f"Output path: {max_hold_path}")
    _emit(f"Output path: {availability_path}")
    _emit(f"Output path: {diagnostics_path}")

    return {
        "summary": summary,
        "files": {
            "trades": str(trades_path),
            "summary": str(summary_path),
            "report": str(report_path),
            "max_hold_audit": str(max_hold_path),
            "availability": str(availability_path),
            "contract_selection_diagnostics": str(diagnostics_path),
        },
    }


def _iter_selected_contracts_for_validation(
    contracts: List[Dict[str, Any]],
    *,
    direction: str,
    spy_entry: float,
    target_expiration: date,
) -> List[str]:
    selected, _ = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction=direction,
        spy_entry=spy_entry,
        target_expiration=target_expiration,
    )
    if selected is None:
        return []

    expected_type = "call" if direction.upper() == "CALL" else "put"
    typed = [c for c in contracts if _contract_type_for_selection(c) == expected_type]
    same_exp = [c for c in typed if _contract_expiration(c) == _contract_expiration(selected)]
    ranked = sorted(
        same_exp,
        key=lambda c: (
            -_safe_float(c.get("open_interest"), 0.0),
            abs((_contract_strike(c) or 0.0) - spy_entry),
            str(c.get("symbol") or ""),
        ),
    )
    return [str(c.get("symbol") or "") for c in ranked if c.get("symbol")][:15]


def run_july13_selector_validation(
    *,
    spy_df: pd.DataFrame,
    call_threshold: int,
    put_threshold: int,
    cache_root: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    def _emit(msg: str) -> None:
        if progress_callback is not None:
            progress_callback(msg)

    key, sec = _load_env_creds()
    client = AlpacaClient(key, sec)

    target_day = date(2026, 7, 13)
    target_day_dt = datetime(2026, 7, 13, 9, 30, tzinfo=ET)
    target_exp = _nearest_friday_at_least_7_days(target_day_dt)

    replay_engine = ReplayEngine(spy_df, include_premarket=True)
    signal_engine = SignalReplayEngine(
        replay_engine,
        call_threshold=call_threshold,
        put_threshold=put_threshold,
    )
    signals = signal_engine.replay()
    signal_map = _build_signal_map(signals)
    all_candles = replay_engine.get_candles_up_to_step(replay_engine.total_steps() - 1).copy()

    july_signals: List[Tuple[datetime, str, float]] = []
    for step in range(replay_engine.total_steps()):
        candle = all_candles.iloc[step]
        ts = pd.Timestamp(candle["timestamp"]).to_pydatetime()
        if ts.date() != target_day:
            continue
        if not _is_regular_entry_time(ts):
            continue
        signal = signal_map.get(step)
        if not signal:
            continue
        choice = _choose_direction(signal)
        if choice is None:
            continue
        direction, _, _ = choice
        july_signals.append((ts, direction, float(candle["close"])))
        if len(july_signals) >= 10:
            break

    cache_root_path = Path(cache_root)
    snapshot_cache_dir = cache_root_path / "snapshots"
    snapshot_cache_dir.mkdir(parents=True, exist_ok=True)

    known_symbols: Dict[str, str] = {}
    contracts_by_dir: Dict[str, List[Dict[str, Any]]] = {}
    for direction in ["CALL", "PUT"]:
        window_end = target_exp + timedelta(days=14)
        cache_file = snapshot_cache_dir / (
            f"SPY_{target_exp.isoformat()}_{window_end.isoformat()}_{direction}_contracts.json"
        )
        if cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            contracts = payload.get("contracts", [])
        else:
            contracts = client.fetch_contracts_for_window(
                start_expiration=target_exp,
                end_expiration=window_end,
                direction=direction,
                status=None,
            )
            cache_file.write_text(json.dumps({"contracts": contracts}), encoding="utf-8")
        contracts_by_dir[direction] = contracts

        base_spy = july_signals[0][2] if july_signals else 0.0
        ranked_symbols = _iter_selected_contracts_for_validation(
            contracts,
            direction=direction,
            spy_entry=base_spy,
            target_expiration=target_exp,
        )
        for sym in ranked_symbols:
            if not sym:
                continue
            if not client.download_trades(sym, target_day).empty:
                known_symbols[direction] = sym
                break

    found = 0
    rejected = 0
    exact_matches = 0
    rows_with_trades = 0
    per_signal: List[Dict[str, Any]] = []

    for ts, direction, spy_px in july_signals:
        selected, diag = _choose_historical_contract_from_contracts(
            contracts=contracts_by_dir.get(direction, []),
            direction=direction,
            spy_entry=spy_px,
            target_expiration=_nearest_friday_at_least_7_days(ts),
        )
        if selected is None:
            rejected += 1
            per_signal.append(
                {
                    "signal_timestamp": ts.isoformat(),
                    "direction": direction,
                    "selected_symbol": "",
                    "rejection_reason": diag.get("rejection_reason", "UNKNOWN"),
                    "trade_rows": 0,
                }
            )
            continue

        found += 1
        symbol = str(selected.get("symbol") or "")
        if known_symbols.get(direction) and known_symbols.get(direction) == symbol:
            exact_matches += 1
        trade_rows = len(client.download_trades(symbol, target_day))
        if trade_rows > 0:
            rows_with_trades += 1
        per_signal.append(
            {
                "signal_timestamp": ts.isoformat(),
                "direction": direction,
                "selected_symbol": symbol,
                "rejection_reason": "",
                "trade_rows": trade_rows,
            }
        )

    _emit(
        "July13 selector validation: "
        f"signals_tested={len(july_signals)} found={found} rejected={rejected} "
        f"exact_known_matches={exact_matches} with_trade_rows={rows_with_trades}"
    )
    for direction in ["CALL", "PUT"]:
        _emit(f"July13 known symbol {direction}: {known_symbols.get(direction, 'NONE')}")

    return {
        "signals_tested": len(july_signals),
        "found": found,
        "rejected": rejected,
        "exact_known_matches": exact_matches,
        "with_trade_rows": rows_with_trades,
        "known_symbols": known_symbols,
        "per_signal": per_signal,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Alpaca historical option-trade full backtest")
    parser.add_argument("--data", default="data/historical/spy_1m.csv", help="Path to SPY 1-minute CSV")
    parser.add_argument("--call-threshold", type=int, default=5)
    parser.add_argument("--put-threshold", type=int, default=5)
    parser.add_argument("--max-hold", type=int, default=15)
    parser.add_argument("--max-trades", type=int, default=20)
    parser.add_argument("--cache-root", default="data/historical/options/alpaca")
    parser.add_argument("--output-dir", default="backtesting/output")
    args = parser.parse_args()

    print("=" * 80)
    print("ALPACA FULL BACKTEST")
    print("=" * 80)

    # Validate creds from .env up front for immediate operator feedback.
    _load_env_creds()
    print("Credentials loaded from .env")

    spy_df = load_csv_data(args.data)
    print(f"SPY data loaded: {len(spy_df)} candles from {args.data}")

    july13_validation = run_july13_selector_validation(
        spy_df=spy_df,
        call_threshold=args.call_threshold,
        put_threshold=args.put_threshold,
        cache_root=args.cache_root,
        progress_callback=print,
    )
    print("July13 selector validation summary:")
    print(json.dumps(july13_validation, indent=2))

    result = run_alpaca_full_backtest(
        spy_csv_path=args.data,
        call_threshold=args.call_threshold,
        put_threshold=args.put_threshold,
        max_hold_minutes=args.max_hold,
        max_trades_per_day=args.max_trades,
        cache_root=args.cache_root,
        output_dir=args.output_dir,
        spy_df=spy_df,
        progress_callback=print,
    )

    summary = result["summary"]
    print("\nFinal summary:")
    print(f"Trading days: {summary['trading_days']}")
    print(f"Signals generated: {summary['signals_generated']}")
    print(f"Accepted/usable trades: {summary['trades_with_usable_alpaca_data']}")
    print(f"DATA_UNAVAILABLE trades: {summary['trades_excluded_data_unavailable']}")
    print(f"Max-hold exits: {summary['max_hold_count']}")
    print(f"Net P/L: {summary['net_pnl']}")

    print("\nOutput files:")
    for _, path in result["files"].items():
        print(path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
