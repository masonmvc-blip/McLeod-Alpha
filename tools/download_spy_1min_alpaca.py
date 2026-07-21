#!/usr/bin/env python3
"""Download historical one-minute SPY bars from Alpaca for replay backtests."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
DATA_URL = "https://data.alpaca.markets/v2/stocks/SPY/bars"


def _env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError(f"Missing required environment variable; expected one of: {', '.join(names)}")


def _fetch_bars(headers: dict[str, str], start: datetime, end: datetime, feed: str) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "timeframe": "1Min",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "adjustment": "raw",
        "feed": feed,
        "limit": 10000,
    }
    rows: list[dict[str, Any]] = []
    while True:
        response = requests.get(DATA_URL, headers=headers, params=params, timeout=45)
        if response.status_code >= 400:
            raise RuntimeError(f"Alpaca returned HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        rows.extend(payload.get("bars") or [])
        page_token = payload.get("next_page_token")
        if not page_token:
            return rows
        params["page_token"] = page_token


def download(start_date: str, end_date: str, output: Path) -> tuple[int, str]:
    load_dotenv()
    api_key = _env_value("APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY")
    api_secret = _env_value("APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY", "ALPACA_API_SECRET")
    start = datetime.combine(datetime.fromisoformat(start_date).date(), time.min, tzinfo=ET)
    end = datetime.combine(datetime.fromisoformat(end_date).date(), time.max, tzinfo=ET)
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}

    errors: list[str] = []
    for feed in ("sip", "iex"):
        try:
            rows = _fetch_bars(headers, start, end, feed)
            if not rows:
                errors.append(f"{feed}: no bars returned")
                continue
            frame = pd.DataFrame(rows).rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            required = ["timestamp", "open", "high", "low", "close", "volume"]
            missing = [column for column in required if column not in frame]
            if missing:
                raise RuntimeError(f"Alpaca response omitted columns: {missing}")
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(ET)
            frame = frame[required].drop_duplicates("timestamp").sort_values("timestamp")
            output.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(output, index=False)
            return len(frame), feed
        except Exception as exc:
            errors.append(f"{feed}: {exc}")
    raise RuntimeError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, help="Inclusive YYYY-MM-DD date in ET")
    parser.add_argument("--end-date", required=True, help="Inclusive YYYY-MM-DD date in ET")
    parser.add_argument("--output", type=Path, required=True, help="Destination CSV path")
    args = parser.parse_args()
    rows, feed = download(args.start_date, args.end_date, args.output)
    print(f"Downloaded {rows} one-minute SPY bars from Alpaca feed={feed} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())