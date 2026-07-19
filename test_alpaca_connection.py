#!/usr/bin/env python3
"""Test Alpaca credentials and download one day of SPY options data.

This script:
1) Loads Alpaca credentials from .env
2) Verifies authenticated connection to Alpaca account endpoint
3) Tries to fetch historical SPY option quotes for one contract
4) Aggregates quotes to 1-minute bars and saves CSV outputs
5) Falls back to SPY stock 1-minute bars if options data is unavailable

No live/paper/backtesting trading code is modified.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv


NY_TZ = "America/New_York"
OUTPUT_DIR = Path("data/alpaca_test")


@dataclass
class AlpacaConfig:
    api_key: str
    api_secret: str
    trading_base_url: str
    data_base_url: str


def _get_env(keys: List[str]) -> Optional[str]:
    for key in keys:
        val = os.getenv(key)
        if val:
            return val.strip()
    return None


def load_config() -> AlpacaConfig:
    load_dotenv()

    api_key = _get_env(["APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY"])
    api_secret = _get_env(["APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY", "ALPACA_API_SECRET"])

    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing Alpaca API credentials in .env. "
            "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY (or ALPACA_* equivalents)."
        )

    trading_base_url = _get_env(["ALPACA_BASE_URL", "APCA_API_BASE_URL"]) or "https://paper-api.alpaca.markets"
    data_base_url = _get_env(["ALPACA_DATA_URL"]) or "https://data.alpaca.markets"

    return AlpacaConfig(
        api_key=api_key,
        api_secret=api_secret,
        trading_base_url=trading_base_url.rstrip("/"),
        data_base_url=data_base_url.rstrip("/"),
    )


def auth_headers(cfg: AlpacaConfig) -> Dict[str, str]:
    return {
        "APCA-API-KEY-ID": cfg.api_key,
        "APCA-API-SECRET-KEY": cfg.api_secret,
    }


def request_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    resp = requests.request(method=method, url=url, headers=headers, params=params, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text[:500]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Invalid JSON from {url}: {resp.text[:300]}") from exc


def verify_connection(cfg: AlpacaConfig) -> Dict[str, Any]:
    account_url = f"{cfg.trading_base_url}/v2/account"
    account = request_json("GET", account_url, headers=auth_headers(cfg))
    print("Connection verified.")
    print(f"Account status: {account.get('status', 'unknown')}")
    print(f"Buying power: {account.get('buying_power', 'n/a')}")
    return account


def previous_trading_day_window() -> Tuple[pd.Timestamp, pd.Timestamp]:
    now_ny = pd.Timestamp.now(tz=NY_TZ)
    day = (now_ny - pd.Timedelta(days=1)).normalize()
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)

    start = day + pd.Timedelta(hours=9, minutes=30)
    end = day + pd.Timedelta(hours=16)
    return start, end


def fetch_spy_option_contract(cfg: AlpacaConfig) -> Optional[str]:
    """Try to fetch one active SPY option contract symbol."""
    url = f"{cfg.trading_base_url}/v2/options/contracts"

    now_ny = pd.Timestamp.now(tz=NY_TZ)
    exp_gte = now_ny.date().isoformat()
    exp_lte = (now_ny + pd.Timedelta(days=45)).date().isoformat()

    params = {
        "underlying_symbols": "SPY",
        "status": "active",
        "expiration_date_gte": exp_gte,
        "expiration_date_lte": exp_lte,
        "limit": 100,
    }

    try:
        payload = request_json("GET", url, headers=auth_headers(cfg), params=params)
    except Exception as exc:
        print(f"Could not fetch options contracts: {exc}")
        return None

    contracts = payload.get("option_contracts", [])
    if not contracts:
        return None

    symbol = contracts[0].get("symbol")
    return symbol


def _extract_quote_rows(payload: Dict[str, Any], symbol: str) -> List[Dict[str, Any]]:
    quotes = payload.get("quotes", {})
    if isinstance(quotes, dict):
        return quotes.get(symbol, [])
    return []


def fetch_option_quotes_for_day(
    cfg: AlpacaConfig,
    option_symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Fetch raw historical option quotes for one day with pagination."""
    url = f"{cfg.data_base_url}/v1beta1/options/quotes"
    headers = auth_headers(cfg)

    params: Dict[str, Any] = {
        "symbols": option_symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sort": "asc",
        "limit": 10000,
    }

    all_rows: List[Dict[str, Any]] = []
    page = 1

    while True:
        payload = request_json("GET", url, headers=headers, params=params)
        rows = _extract_quote_rows(payload, option_symbol)
        all_rows.extend(rows)

        next_token = payload.get("next_page_token")
        print(f"Fetched page {page}, rows: {len(rows)}, total: {len(all_rows)}")

        if not next_token:
            break

        params["page_token"] = next_token
        page += 1

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # Normalize known Alpaca quote fields while remaining tolerant to schema variants.
    # Common keys: t (timestamp), bp (bid price), ap (ask price), bs/as (sizes), c (conditions)
    if "t" in df.columns:
        df["timestamp"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY_TZ)
    elif "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(NY_TZ)
    else:
        raise RuntimeError("Options quote payload missing timestamp field.")

    if "bp" in df.columns:
        df["bid_price"] = pd.to_numeric(df["bp"], errors="coerce")
    if "ap" in df.columns:
        df["ask_price"] = pd.to_numeric(df["ap"], errors="coerce")

    if "bid_price" in df.columns and "ask_price" in df.columns:
        df["mid_price"] = (df["bid_price"] + df["ask_price"]) / 2.0

    df["option_symbol"] = option_symbol
    return df.sort_values("timestamp").reset_index(drop=True)


def fetch_option_bars_for_day(
    cfg: AlpacaConfig,
    option_symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Fetch 1-minute option bars if quotes endpoint is unavailable."""
    url = f"{cfg.data_base_url}/v1beta1/options/bars"
    headers = auth_headers(cfg)

    params: Dict[str, Any] = {
        "symbols": option_symbol,
        "timeframe": "1Min",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sort": "asc",
        "limit": 10000,
    }

    all_rows: List[Dict[str, Any]] = []
    page = 1

    while True:
        payload = request_json("GET", url, headers=headers, params=params)
        bars = payload.get("bars", {})
        rows = bars.get(option_symbol, []) if isinstance(bars, dict) else []
        all_rows.extend(rows)

        next_token = payload.get("next_page_token")
        print(f"Fetched option bars page {page}, rows: {len(rows)}, total: {len(all_rows)}")

        if not next_token:
            break

        params["page_token"] = next_token
        page += 1

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    if "t" in df.columns:
        df["timestamp"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY_TZ)
    elif "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(NY_TZ)

    rename_map = {
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "n": "trade_count",
        "vw": "vwap",
    }
    df = df.rename(columns=rename_map)
    df["option_symbol"] = option_symbol
    return df.sort_values("timestamp").reset_index(drop=True)


def aggregate_quotes_to_1min(df_quotes: pd.DataFrame) -> pd.DataFrame:
    if df_quotes.empty:
        return df_quotes

    if "timestamp" not in df_quotes.columns:
        raise RuntimeError("Cannot aggregate quotes without timestamp column.")

    work = df_quotes.copy()
    work["minute"] = work["timestamp"].dt.floor("min")

    agg_map: Dict[str, Any] = {"timestamp": "last"}
    for col in ["bid_price", "ask_price", "mid_price", "option_symbol"]:
        if col in work.columns:
            agg_map[col] = "last"

    out = work.groupby("minute", as_index=False).agg(agg_map)
    out = out.rename(columns={"minute": "bar_minute"})
    return out


def fetch_stock_bars_fallback(cfg: AlpacaConfig, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Fallback if options quotes are unavailable for account/data plan."""
    url = f"{cfg.data_base_url}/v2/stocks/SPY/bars"
    headers = auth_headers(cfg)

    # Try SIP first; fallback to IEX if not entitled.
    feeds = ["sip", "iex"]
    last_err = None

    for feed in feeds:
        params = {
            "timeframe": "1Min",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": "raw",
            "feed": feed,
            "limit": 10000,
        }
        try:
            payload = request_json("GET", url, headers=headers, params=params)
            bars = payload.get("bars", [])
            if not bars:
                continue

            df = pd.DataFrame(bars)
            if "t" in df.columns:
                df["timestamp"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY_TZ)
            elif "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(NY_TZ)

            rename_map = {
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "n": "trade_count",
                "vw": "vwap",
            }
            df = df.rename(columns=rename_map)
            df["feed"] = feed
            return df.sort_values("timestamp").reset_index(drop=True)
        except Exception as exc:
            last_err = exc

    raise RuntimeError(f"Unable to fetch fallback stock bars: {last_err}")


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    try:
        cfg = load_config()
        ensure_output_dir()

        verify_connection(cfg)

        start, end = previous_trading_day_window()
        day_tag = start.strftime("%Y-%m-%d")

        option_symbol = fetch_spy_option_contract(cfg)
        if option_symbol:
            print(f"Using option contract: {option_symbol}")
            try:
                quotes_df = fetch_option_quotes_for_day(cfg, option_symbol, start, end)
                if not quotes_df.empty:
                    raw_path = OUTPUT_DIR / f"spy_option_quotes_raw_{day_tag}.csv"
                    one_min_path = OUTPUT_DIR / f"spy_option_quotes_1min_{day_tag}.csv"

                    quotes_df.to_csv(raw_path, index=False)
                    one_min_df = aggregate_quotes_to_1min(quotes_df)
                    one_min_df.to_csv(one_min_path, index=False)

                    print(f"Saved raw option quotes: {raw_path}")
                    print(f"Saved 1-minute option quotes: {one_min_path}")
                    print(f"Rows raw={len(quotes_df)}, 1min={len(one_min_df)}")
                    return 0

                print("No option quotes returned for selected contract/day. Trying options bars endpoint.")
            except Exception as exc:
                print(f"Options quotes endpoint unavailable: {exc}")

            try:
                option_bars_df = fetch_option_bars_for_day(cfg, option_symbol, start, end)
                if not option_bars_df.empty:
                    bars_path = OUTPUT_DIR / f"spy_option_bars_1min_{day_tag}.csv"
                    option_bars_df.to_csv(bars_path, index=False)
                    print(f"Saved 1-minute option bars: {bars_path}")
                    print(f"Rows={len(option_bars_df)}")
                    return 0
                print("No option bars returned for selected contract/day. Trying fallback.")
            except Exception as exc:
                print(f"Options bars endpoint unavailable: {exc}")
        else:
            print("No option contract found or endpoint unavailable. Trying fallback.")

        # Closest available historical data fallback.
        bars_df = fetch_stock_bars_fallback(cfg, start, end)
        fallback_path = OUTPUT_DIR / f"spy_stock_1min_fallback_{day_tag}.csv"
        bars_df.to_csv(fallback_path, index=False)

        print(f"Saved fallback 1-minute SPY stock bars: {fallback_path}")
        print(f"Rows={len(bars_df)}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
