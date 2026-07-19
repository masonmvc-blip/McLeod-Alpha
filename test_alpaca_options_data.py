#!/usr/bin/env python3
"""Standalone Alpaca historical-options connectivity test.

Uses only these .env keys:
- ALPACA_API_KEY
- ALPACA_API_SECRET

Behavior:
1) Verifies Alpaca Market Data auth at https://data.alpaca.markets
2) Discovers SPY option contracts around 2026-07-13 near spot
3) Requests historical option quotes (feed=indicative)
4) Falls back to option trades if quotes unavailable
5) Saves CSV outputs to data/alpaca_test/

This script does not modify live/paper/backtesting/production behavior.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv


DATA_BASE_URL = "https://data.alpaca.markets"
TRADING_BASE_URL = "https://paper-api.alpaca.markets"
OUT_DIR = Path("data/alpaca_test")
TARGET_DATE = "2026-07-13"
WINDOW_START_ET = "2026-07-13 09:30:00"
WINDOW_END_ET = "2026-07-13 10:00:00"


@dataclass
class ContractPick:
    call_symbol: str
    put_symbol: str


def _headers(api_key: str, api_secret: str) -> Dict[str, str]:
    return {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }


def _safe_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    max_retries: int = 5,
) -> Dict[str, Any]:
    for attempt in range(max_retries):
        resp = requests.request(method, url, headers=headers, params=params, timeout=timeout)

        if resp.status_code == 429:
            wait_s = min(2 ** attempt, 10)
            time.sleep(wait_s)
            continue

        if resp.status_code >= 400:
            msg = resp.text[:500].replace("\n", " ")
            raise RuntimeError(f"HTTP {resp.status_code}: {msg}")

        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON response from {url}") from exc

    raise RuntimeError("Request failed after retries due to rate limiting")


def _to_iso_utc(ts_et: str) -> str:
    return pd.Timestamp(ts_et, tz="America/New_York").tz_convert("UTC").isoformat()


def load_credentials() -> Tuple[str, str]:
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip()

    if not api_key or not api_secret:
        raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_API_SECRET in .env")

    return api_key, api_secret


def verify_market_data_auth(headers: Dict[str, str]) -> None:
    # Simple market-data request for auth verification.
    url = f"{DATA_BASE_URL}/v2/stocks/SPY/bars"
    params = {
        "timeframe": "1Min",
        "start": _to_iso_utc(f"{TARGET_DATE} 09:30:00"),
        "end": _to_iso_utc(f"{TARGET_DATE} 09:31:00"),
        "feed": "iex",
        "limit": 1,
    }
    payload = _safe_request("GET", url, headers=headers, params=params)
    _ = payload.get("bars", [])
    print("authentication: success")


def fetch_spy_spot(headers: Dict[str, str]) -> float:
    url = f"{DATA_BASE_URL}/v2/stocks/SPY/bars"
    params = {
        "timeframe": "1Min",
        "start": _to_iso_utc(WINDOW_START_ET),
        "end": _to_iso_utc(WINDOW_END_ET),
        "feed": "iex",
        "limit": 1000,
    }
    payload = _safe_request("GET", url, headers=headers, params=params)
    bars = payload.get("bars", [])
    if not bars:
        raise RuntimeError("No SPY bars returned for spot estimation")

    closes = []
    for b in bars:
        if "c" in b:
            closes.append(float(b["c"]))
        elif "close" in b:
            closes.append(float(b["close"]))

    if not closes:
        raise RuntimeError("Unable to parse SPY close prices for spot estimation")

    return float(closes[0])


def discover_contracts(headers: Dict[str, str], spot: float) -> ContractPick:
    # Use Alpaca options contracts endpoint for symbol discovery.
    url = f"{TRADING_BASE_URL}/v2/options/contracts"

    params = {
        "underlying_symbols": "SPY",
        "expiration_date_gte": TARGET_DATE,
        "expiration_date_lte": (pd.Timestamp(TARGET_DATE) + pd.Timedelta(days=14)).date().isoformat(),
        "limit": 1000,
    }

    payload = _safe_request("GET", url, headers=headers, params=params)
    contracts = payload.get("option_contracts", [])

    if not contracts:
        raise RuntimeError("No SPY option contracts returned for discovery window")

    calls = []
    puts = []

    for c in contracts:
        ctype = str(c.get("type", "")).lower()
        strike = c.get("strike_price")
        expiry = c.get("expiration_date")
        symbol = c.get("symbol")

        if strike is None or expiry is None or not symbol:
            continue

        try:
            strike_f = float(strike)
            exp_ts = pd.Timestamp(expiry)
        except Exception:
            continue

        if exp_ts.date() < pd.Timestamp(TARGET_DATE).date():
            continue

        dist = abs(strike_f - spot)
        score = (exp_ts, dist)

        if ctype == "call":
            calls.append((score, symbol))
        elif ctype == "put":
            puts.append((score, symbol))

    if not calls or not puts:
        raise RuntimeError("Could not find both CALL and PUT contracts near spot")

    calls.sort(key=lambda x: x[0])
    puts.sort(key=lambda x: x[0])

    return ContractPick(call_symbol=calls[0][1], put_symbol=puts[0][1])


def _paginate_option_endpoint(
    endpoint: str,
    symbol: str,
    headers: Dict[str, str],
    start_utc: str,
    end_utc: str,
    feed: Optional[str] = None,
) -> List[Dict[str, Any]]:
    url = f"{DATA_BASE_URL}{endpoint}"
    params: Dict[str, Any] = {
        "symbols": symbol,
        "start": start_utc,
        "end": end_utc,
        "sort": "asc",
        "limit": 10000,
    }
    if feed:
        params["feed"] = feed

    rows: List[Dict[str, Any]] = []

    while True:
        payload = _safe_request("GET", url, headers=headers, params=params)

        bucket_name = "quotes" if "quotes" in endpoint else "trades"
        bucket = payload.get(bucket_name, {})
        page_rows = bucket.get(symbol, []) if isinstance(bucket, dict) else []
        rows.extend(page_rows)

        next_token = payload.get("next_page_token")
        if not next_token:
            break

        params["page_token"] = next_token

    return rows


def rows_to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    t_col = "t" if "t" in df.columns else "timestamp" if "timestamp" in df.columns else None
    if t_col:
        df["timestamp"] = pd.to_datetime(df[t_col], utc=True)
        df["timestamp_et"] = df["timestamp"].dt.tz_convert("America/New_York")
    return df


def save_df(df: pd.DataFrame, path: Path) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def summarize_dataset(label: str, df: pd.DataFrame, path: Path) -> None:
    count = len(df)
    if count > 0 and "timestamp_et" in df.columns:
        earliest = str(df["timestamp_et"].min())
        latest = str(df["timestamp_et"].max())
    else:
        earliest = "n/a"
        latest = "n/a"

    fields = ",".join(df.columns.tolist()) if count > 0 else "n/a"

    print(f"{label} rows: {count}")
    print(f"{label} earliest: {earliest}")
    print(f"{label} latest: {latest}")
    print(f"{label} fields: {fields}")
    print(f"{label} file: {path}")


def fetch_quotes_or_trades_for_symbol(
    symbol: str,
    side_label: str,
    headers: Dict[str, str],
    start_utc: str,
    end_utc: str,
) -> None:
    feed = "indicative"
    print(f"feed used: {feed}")

    quote_rows = []
    quote_err = None
    try:
        quote_rows = _paginate_option_endpoint(
            endpoint="/v1beta1/options/quotes",
            symbol=symbol,
            headers=headers,
            start_utc=start_utc,
            end_utc=end_utc,
            feed=feed,
        )
    except Exception as exc:
        quote_err = str(exc)

    if quote_rows:
        qdf = rows_to_df(quote_rows)
        qpath = OUT_DIR / f"spy_{side_label}_quotes_2026-07-13.csv"
        save_df(qdf, qpath)
        summarize_dataset(f"{side_label} quotes", qdf, qpath)
        return

    if quote_err:
        print(f"{side_label} quotes limitation/error: {quote_err}")
    else:
        print(f"{side_label} quotes limitation/error: no rows returned")

    trade_rows = []
    trade_err = None
    try:
        trade_rows = _paginate_option_endpoint(
            endpoint="/v1beta1/options/trades",
            symbol=symbol,
            headers=headers,
            start_utc=start_utc,
            end_utc=end_utc,
            feed=None,
        )
    except Exception as exc:
        trade_err = str(exc)

    if trade_rows:
        tdf = rows_to_df(trade_rows)
        tpath = OUT_DIR / f"spy_{side_label}_trades_2026-07-13.csv"
        save_df(tdf, tpath)
        summarize_dataset(f"{side_label} trades", tdf, tpath)
        print(f"{side_label} note: quotes unavailable, used trades fallback")
        return

    if trade_err:
        print(f"{side_label} trades limitation/error: {trade_err}")
    else:
        print(f"{side_label} trades limitation/error: no rows returned")


def main() -> int:
    try:
        api_key, api_secret = load_credentials()
        headers = _headers(api_key, api_secret)

        verify_market_data_auth(headers)

        spot = fetch_spy_spot(headers)
        picks = discover_contracts(headers, spot)

        print(f"selected call symbol: {picks.call_symbol}")
        print(f"selected put symbol: {picks.put_symbol}")

        start_utc = _to_iso_utc(WINDOW_START_ET)
        end_utc = _to_iso_utc(WINDOW_END_ET)

        fetch_quotes_or_trades_for_symbol(picks.call_symbol, "call", headers, start_utc, end_utc)
        fetch_quotes_or_trades_for_symbol(picks.put_symbol, "put", headers, start_utc, end_utc)

        return 0

    except Exception as exc:
        print(f"authentication: failure")
        print(f"api error: {str(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
