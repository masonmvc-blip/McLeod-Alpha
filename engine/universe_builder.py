#!/usr/bin/env python3
"""
McLeod U.S. Equity Universe Builder

Builds a broad U.S. investable common-stock universe from:
- Nasdaq Trader exchange listings
- SEC ticker/CIK exchange mapping

Outputs:
- data/us_equity_universe_latest.csv
- data/us_equity_universe_latest.json
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

import requests


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
CSV_OUT = DATA_DIR / "us_equity_universe_latest.csv"
JSON_OUT = DATA_DIR / "us_equity_universe_latest.json"

NASDAQ_TRADED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqtraded.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
SEC_TICKER_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

EXCHANGE_MAP = {
    "N": "NYSE",
    "Q": "NASDAQ",
    "A": "NYSE AMERICAN",
    "P": "NYSE ARCA",
    "V": "IEX",
    "Z": "CBOE BZX",
}

INTENTIONALLY_RETAIN_SHARE_CLASSES = {
    "GOOG",
    "GOOGL",
    "BRK.A",
    "BRK.B",
}

EXCLUDE_NAME_PATTERNS = [
    r"\bETF\b",
    r"\bETN\b",
    r"\bFUND\b",
    r"\bTRUST\b",
    r"\bPREFERRED\b",
    r"\bPREF\b",
    r"\bRIGHT\b",
    r"\bWARRANT\b",
    r"\bUNIT\b",
    r"\bACQUISITION\b",
    r"\bSPAC\b",
    r"\bHOLDINGS CORP II\b",
]


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace("/", ".")


def normalize_name(name: str) -> str:
    n = re.sub(r"\s+", " ", name.upper()).strip()
    n = re.sub(r"\b(COMMON STOCK|CLASS [A-Z]|ORDINARY SHARES?|SHARES?)\b", "", n)
    return re.sub(r"\s+", " ", n).strip(" ,.-")


def infer_security_type(name: str, symbol: str) -> str:
    n = name.upper()
    if "PREFERRED" in n or symbol.endswith("P"):
        return "preferred"
    if "WARRANT" in n or symbol.endswith("W") or symbol.endswith("WS"):
        return "warrant"
    if "RIGHT" in n or symbol.endswith("R"):
        return "right"
    if "UNIT" in n or symbol.endswith("U"):
        return "unit"
    if "ETF" in n or "FUND" in n or "TRUST" in n:
        return "fund_or_etf"
    return "common_stock"


class UniverseBuilder:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "McLeod Alpha Universe Builder 1.0 (research@mcleodalpha.local)"
        })

    def _fetch_text(self, url: str, retries: int = 3) -> str:
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
                return resp.text
            except Exception as exc:
                last_error = exc
                if attempt == retries:
                    raise
        raise RuntimeError(f"Failed to fetch {url}: {last_error}")

    def _parse_pipe_file(self, raw_text: str) -> List[Dict[str, str]]:
        lines = [ln for ln in raw_text.splitlines() if ln.strip() and not ln.startswith("File Creation Time")]
        if not lines:
            return []
        header = lines[0].split("|")
        rows = []
        for ln in lines[1:]:
            parts = ln.split("|")
            if len(parts) != len(header):
                continue
            rows.append({header[i].strip(): parts[i].strip() for i in range(len(header))})
        return rows

    def _load_sec_map(self) -> Dict[str, Dict[str, Any]]:
        payload = self.session.get(SEC_TICKER_EXCHANGE_URL, timeout=30)
        payload.raise_for_status()
        obj = payload.json()
        fields = obj.get("fields", [])
        data = obj.get("data", [])
        out = {}
        for row in data:
            rec = {fields[i]: row[i] for i in range(min(len(fields), len(row)))}
            ticker = normalize_ticker(str(rec.get("ticker", "")))
            if not ticker:
                continue
            out[ticker] = {
                "cik": f"{int(rec.get('cik')):010d}" if rec.get("cik") is not None else "",
                "sec_name": rec.get("name", ""),
                "sec_exchange": str(rec.get("exchange", "")).upper(),
            }
        return out

    def _is_excluded(self, symbol: str, name: str, etf_flag: str) -> bool:
        if not symbol or symbol.endswith("$"):
            return True
        if etf_flag.upper() == "Y":
            return True

        sec_type = infer_security_type(name, symbol)
        if sec_type != "common_stock":
            return True

        for pattern in EXCLUDE_NAME_PATTERNS:
            if re.search(pattern, name.upper()):
                return True

        # OTC and test issues are excluded.
        if symbol.endswith(".PK") or symbol.endswith(".OB"):
            return True

        return False

    def _dedupe(self, records: List[Dict[str, Any]], retain_symbols: set) -> List[Dict[str, Any]]:
        by_symbol = {}
        for r in records:
            by_symbol[r["symbol"]] = r

        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for r in by_symbol.values():
            symbol = r["symbol"]
            base = symbol.split(".")[0]
            key = (base, normalize_name(r["company_name"]))
            grouped.setdefault(key, []).append(r)

        deduped: List[Dict[str, Any]] = []
        for _, group in grouped.items():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            # Keep intentionally retained symbols and current holdings as-is.
            keep = [g for g in group if g["symbol"] in INTENTIONALLY_RETAIN_SHARE_CLASSES or g["symbol"] in retain_symbols]
            if keep:
                deduped.extend(keep)
                continue

            # Otherwise keep the first alphabetically as canonical class.
            group_sorted = sorted(group, key=lambda x: x["symbol"])
            deduped.append(group_sorted[0])

        return sorted(deduped, key=lambda x: (x["exchange"], x["symbol"]))

    def build(self) -> Dict[str, Any]:
        holdings_symbols = set()
        positions_csv = DATA_DIR / "schwab_positions_latest.csv"
        if positions_csv.exists():
            with open(positions_csv) as f:
                for row in csv.DictReader(f):
                    if row.get("asset_type", "").upper() == "EQUITY":
                        holdings_symbols.add(normalize_ticker(row.get("symbol", "")))

        nasdaq_traded = self._parse_pipe_file(self._fetch_text(NASDAQ_TRADED_URL))
        other_listed = self._parse_pipe_file(self._fetch_text(OTHER_LISTED_URL))
        sec_map = self._load_sec_map()

        records: List[Dict[str, Any]] = []
        now_iso = datetime.now().isoformat()

        for row in nasdaq_traded:
            symbol = normalize_ticker(row.get("Symbol", ""))
            name = row.get("Security Name", "")
            listing_exchange_code = row.get("Listing Exchange", "")
            exchange = EXCHANGE_MAP.get(listing_exchange_code, listing_exchange_code)
            etf_flag = row.get("ETF", "N")
            test_issue = row.get("Test Issue", "N")

            if exchange not in {"NYSE", "NASDAQ", "NYSE AMERICAN"}:
                continue
            if test_issue.upper() == "Y":
                continue
            if self._is_excluded(symbol, name, etf_flag):
                continue

            sec_rec = sec_map.get(symbol, {})
            records.append({
                "symbol": symbol,
                "company_name": name,
                "exchange": exchange,
                "market_cap": "",
                "sector": "",
                "industry": "",
                "cik": sec_rec.get("cik", ""),
                "security_type": "common_stock",
                "active": True,
                "last_refresh": now_iso,
                "source_listing": "nasdaq_traded",
            })

        for row in other_listed:
            symbol = normalize_ticker(row.get("ACT Symbol", ""))
            name = row.get("Security Name", "")
            exchange_code = row.get("Exchange", "")
            exchange = EXCHANGE_MAP.get(exchange_code, exchange_code)
            etf_flag = row.get("ETF", "N")
            test_issue = row.get("Test Issue", "N")

            if exchange not in {"NYSE", "NASDAQ", "NYSE AMERICAN"}:
                continue
            if test_issue.upper() == "Y":
                continue
            if self._is_excluded(symbol, name, etf_flag):
                continue

            sec_rec = sec_map.get(symbol, {})
            records.append({
                "symbol": symbol,
                "company_name": name,
                "exchange": exchange,
                "market_cap": "",
                "sector": "",
                "industry": "",
                "cik": sec_rec.get("cik", ""),
                "security_type": "common_stock",
                "active": True,
                "last_refresh": now_iso,
                "source_listing": "other_listed",
            })

        # Add SEC names when listing names are empty or truncated.
        for rec in records:
            sec = sec_map.get(rec["symbol"])
            if sec and sec.get("sec_name") and (not rec["company_name"] or len(rec["company_name"]) < 4):
                rec["company_name"] = sec["sec_name"]

        deduped = self._dedupe(records, holdings_symbols)

        fields = [
            "symbol",
            "company_name",
            "exchange",
            "market_cap",
            "sector",
            "industry",
            "cik",
            "security_type",
            "active",
            "last_refresh",
            "source_listing",
        ]

        with open(CSV_OUT, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(deduped)

        payload = {
            "metadata": {
                "generated_at": now_iso,
                "universe_size": len(deduped),
                "exchanges": ["NYSE", "NASDAQ", "NYSE AMERICAN"],
                "sources": [NASDAQ_TRADED_URL, OTHER_LISTED_URL, SEC_TICKER_EXCHANGE_URL],
            },
            "securities": deduped,
        }
        with open(JSON_OUT, "w") as f:
            json.dump(payload, f, indent=2)

        return {
            "size": len(deduped),
            "csv": str(CSV_OUT),
            "json": str(JSON_OUT),
        }


def main():
    builder = UniverseBuilder()
    result = builder.build()
    print(f"✓ Built U.S. equity universe: {result['size']:,} symbols")
    print(f"✓ CSV: {result['csv']}")
    print(f"✓ JSON: {result['json']}")


if __name__ == "__main__":
    main()
