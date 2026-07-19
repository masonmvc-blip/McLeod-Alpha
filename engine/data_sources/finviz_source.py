#!/usr/bin/env python3
"""
Finviz Data Source
Retrieves market/fundamental metrics by parsing public Finviz quote pages.
"""

from datetime import datetime
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional

import requests


WORKSPACE = Path(__file__).parent.parent.parent
DATA_DIR = WORKSPACE / "data"
CACHE_FILE = DATA_DIR / "finviz_cache.json"


class FinvizDataSource:
    """Finviz screener data source."""
    
    def __init__(self):
        """Initialize Finviz data source."""
        self.name = "Finviz Elite"
        self.confidence_base = 78
        self.available = True
        self.cache_ttl_hours = 8
        self.cache = self._load_cache()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        })

    def _load_cache(self) -> Dict[str, Any]:
        if not CACHE_FILE.exists():
            return {}
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(self.cache, f, indent=2)

    @staticmethod
    def _parse_numeric_value(raw_value: str) -> Optional[float]:
        if raw_value is None:
            return None
        v = raw_value.strip().replace(",", "")
        if not v or v in {"-", "N/A"}:
            return None
        if v.endswith("%"):
            v = v[:-1]
        multiplier = 1.0
        if v.endswith("B"):
            multiplier = 1_000_000_000.0
            v = v[:-1]
        elif v.endswith("M"):
            multiplier = 1_000_000.0
            v = v[:-1]
        elif v.endswith("K"):
            multiplier = 1_000.0
            v = v[:-1]
        try:
            return float(v) * multiplier
        except ValueError:
            return None

    def _fetch_snapshot(self, symbol: str) -> Optional[Dict[str, str]]:
        symbol = symbol.upper().replace(".", "-")

        cached = self.cache.get(symbol)
        if cached:
            ts = cached.get("timestamp")
            try:
                cache_dt = datetime.fromisoformat(ts)
                age_hours = (datetime.now() - cache_dt).total_seconds() / 3600
                cached_snapshot = cached.get("snapshot")
                if age_hours < self.cache_ttl_hours and isinstance(cached_snapshot, dict) and cached_snapshot:
                    return cached.get("snapshot")
            except Exception:
                pass

        url = f"https://finviz.com/quote.ashx?t={symbol}"
        response = self.session.get(url, timeout=20)
        response.raise_for_status()
        html = response.text

        # Parse Finviz key/value cells from current snapshot-table2 row structure.
        pairs = re.findall(
            r"snapshot-td-label\">(.*?)</div>.*?snapshot-td-content\">(?:<b>)?(.*?)(?:</b>)?</div>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not pairs:
            return None

        cleaned = {}
        for key, value in pairs:
            key_clean = re.sub(r"<[^>]+>", "", key).strip()
            value_clean = re.sub(r"<[^>]+>", "", value).strip()
            if key_clean:
                cleaned[key_clean] = value_clean

        self.cache[symbol] = {
            "timestamp": datetime.now().isoformat(),
            "snapshot": cleaned,
        }
        self._save_cache()
        return cleaned
    
    def get_metric(self, symbol: str, metric: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve metric from Finviz Elite.
        
        Returns: {value, source, timestamp, confidence, stale}
        or None if not available
        """
        if not self.available:
            return None

        try:
            snapshot = self._fetch_snapshot(symbol)
        except Exception:
            return None

        if not snapshot:
            return None

        metric_map = {
            "pe_ratio": "P/E",
            "price_to_book": "P/B",
            "price_to_sales": "P/S",
            "price_to_fcf": "P/FCF",
            "dividend_yield": "Dividend %",
            "market_cap": "Market Cap",
            "shares_outstanding": "Shs Outstand",
        }

        finviz_key = metric_map.get(metric)
        if not finviz_key:
            return None

        raw = snapshot.get(finviz_key)
        if raw is None:
            return None

        value = self._parse_numeric_value(raw)
        if value is None:
            return None

        # Dividend is stored as percent in Finviz; normalize to percentage units.
        if metric == "dividend_yield" and value > 1_000:
            return None

        return {
            "value": round(value, 4),
            "source": "Finviz",
            "timestamp": datetime.now().isoformat(),
            "confidence": self.confidence_base,
            "stale": False,
        }
    
    def resolve_metrics(self, symbol: str) -> Dict[str, Dict[str, Any]]:
        """
        Resolve all available metrics for a symbol from Finviz.
        
        Returns dict of {metric_name: {value, source, timestamp, confidence, stale}}
        """
        if not self.available:
            return {}

        metrics = [
            "pe_ratio",
            "price_to_book",
            "price_to_sales",
            "price_to_fcf",
            "dividend_yield",
            "market_cap",
            "shares_outstanding",
        ]
        resolved = {}
        for metric in metrics:
            result = self.get_metric(symbol, metric)
            if result and result.get("value") not in (None, "NEEDS_RESEARCH"):
                resolved[metric] = result

        return resolved


if __name__ == "__main__":
    source = FinvizDataSource()
    print(f"✓ Finviz Data Source initialized (API integration pending)")
