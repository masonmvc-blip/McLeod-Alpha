#!/usr/bin/env python3
"""Analyst estimates data source with caching and retries.

Primary source: Yahoo Finance quoteSummary modules.
This source returns only observed values and never fabricates missing fields.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


WORKSPACE = Path(__file__).parent.parent.parent
DATA_DIR = WORKSPACE / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_FILE = CACHE_DIR / "analyst_source_cache.json"

QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
MODULES = [
    "earningsTrend",
    "financialData",
    "recommendationTrend",
    "upgradeDowngradeHistory",
    "price",
    "defaultKeyStatistics",
]


def _raw_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "raw" in value:
            return value.get("raw")
        if "fmt" in value:
            return value.get("fmt")
    return value


class AnalystDataSource:
    """Fetch and cache analyst estimate data by symbol."""

    def __init__(self):
        self.name = "Yahoo QuoteSummary Analyst Data"
        self.confidence_base = 72
        self.available = True
        self.cache_ttl_hours = 24
        self.max_retries = 2
        self.retry_backoff_seconds = 1.0

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                )
            }
        )
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if not CACHE_FILE.exists():
            return {}
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    def _cache_is_fresh(self, timestamp: str) -> bool:
        try:
            cache_dt = datetime.fromisoformat(timestamp)
            age_hours = (datetime.now() - cache_dt).total_seconds() / 3600.0
            return age_hours <= float(self.cache_ttl_hours)
        except Exception:
            return False

    def _request_quote_summary(self, symbol: str) -> Optional[Dict[str, Any]]:
        url = QUOTE_SUMMARY_URL.format(symbol=symbol.upper())
        params = {
            "modules": ",".join(MODULES),
            "formatted": "false",
            "corsDomain": "finance.yahoo.com",
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=6)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                payload = resp.json()
                result = ((payload.get("quoteSummary") or {}).get("result") or [None])[0]
                return result if isinstance(result, dict) else None
            except Exception:
                if attempt >= self.max_retries:
                    return None
                time.sleep(self.retry_backoff_seconds * attempt)
        return None

    @staticmethod
    def _extract_earnings_trend(result: Dict[str, Any]) -> Dict[str, Any]:
        trend_rows = (((result.get("earningsTrend") or {}).get("trend")) or [])
        current = trend_rows[0] if trend_rows else {}

        eps_trend = (current.get("epsTrend") or {}) if isinstance(current, dict) else {}
        rev_est = (current.get("revenueEstimate") or {}) if isinstance(current, dict) else {}

        return {
            "eps_current": _raw_value((eps_trend.get("current") or {})),
            "eps_7d_ago": _raw_value((eps_trend.get("7daysAgo") or {})),
            "eps_30d_ago": _raw_value((eps_trend.get("30daysAgo") or {})),
            "eps_90d_ago": _raw_value((eps_trend.get("90daysAgo") or {})),
            "revenue_current": _raw_value((rev_est.get("avg") or {})),
            "revenue_7d_ago": _raw_value((rev_est.get("7daysAgo") or {})),
            "revenue_30d_ago": _raw_value((rev_est.get("30daysAgo") or {})),
            "revenue_90d_ago": _raw_value((rev_est.get("90daysAgo") or {})),
            "long_term_growth": _raw_value((rev_est.get("growth") or {})),
            "num_analysts_revenue": _raw_value((rev_est.get("numberOfAnalysts") or {})),
        }

    @staticmethod
    def _extract_financial_data(result: Dict[str, Any]) -> Dict[str, Any]:
        fd = result.get("financialData") or {}
        return {
            "target_mean": _raw_value(fd.get("targetMeanPrice")),
            "target_median": _raw_value(fd.get("targetMedianPrice")),
            "target_high": _raw_value(fd.get("targetHighPrice")),
            "target_low": _raw_value(fd.get("targetLowPrice")),
            "recommendation_mean": _raw_value(fd.get("recommendationMean")),
            "num_analysts_recommendation": _raw_value(fd.get("numberOfAnalystOpinions")),
        }

    @staticmethod
    def _extract_upgrades(result: Dict[str, Any]) -> Dict[str, Any]:
        hist = (((result.get("upgradeDowngradeHistory") or {}).get("history")) or [])
        if not isinstance(hist, list):
            hist = []
        return {"upgrade_downgrade_history": hist}

    def fetch_symbol(self, symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Return normalized analyst data for a symbol."""
        symbol = str(symbol or "").upper().strip()
        now_iso = datetime.now().isoformat()
        if not symbol:
            return {
                "symbol": symbol,
                "timestamp": now_iso,
                "source": self.name,
                "stale": True,
                "confidence": 0,
                "data": {},
            }

        cached = self.cache.get(symbol)
        if cached and not force_refresh and self._cache_is_fresh(str(cached.get("timestamp", ""))):
            return {
                "symbol": symbol,
                "timestamp": str(cached.get("timestamp", now_iso)),
                "source": self.name,
                "stale": False,
                "confidence": int(cached.get("confidence", self.confidence_base)),
                "data": cached.get("data", {}),
            }

        result = self._request_quote_summary(symbol)
        if result is None:
            if cached:
                return {
                    "symbol": symbol,
                    "timestamp": str(cached.get("timestamp", now_iso)),
                    "source": self.name,
                    "stale": True,
                    "confidence": max(25, int(cached.get("confidence", self.confidence_base)) - 20),
                    "data": cached.get("data", {}),
                }
            return {
                "symbol": symbol,
                "timestamp": now_iso,
                "source": self.name,
                "stale": True,
                "confidence": 0,
                "data": {},
            }

        normalized: Dict[str, Any] = {}
        normalized.update(self._extract_earnings_trend(result))
        normalized.update(self._extract_financial_data(result))
        normalized.update(self._extract_upgrades(result))

        # Estimate dispersion is derived only when all required values exist.
        target_high = normalized.get("target_high")
        target_low = normalized.get("target_low")
        target_mean = normalized.get("target_mean")
        dispersion = None
        try:
            if target_high not in (None, "") and target_low not in (None, "") and target_mean not in (None, "", 0):
                dispersion = (float(target_high) - float(target_low)) / abs(float(target_mean)) * 100.0
        except Exception:
            dispersion = None
        normalized["estimate_dispersion_pct"] = dispersion

        self.cache[symbol] = {
            "timestamp": now_iso,
            "confidence": self.confidence_base,
            "data": normalized,
        }
        self._save_cache()

        return {
            "symbol": symbol,
            "timestamp": now_iso,
            "source": self.name,
            "stale": False,
            "confidence": self.confidence_base,
            "data": normalized,
        }


if __name__ == "__main__":
    src = AnalystDataSource()
    sample = src.fetch_symbol("AAPL")
    print(json.dumps(sample, indent=2)[:4000])
