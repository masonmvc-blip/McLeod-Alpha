#!/usr/bin/env python3
"""McLeod Insider Intelligence Engine v1.0.

Collects official SEC Form 4 transactions, classifies and filters them,
builds insider-buying signals, and tracks predictive value.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_sources.insider_source import InsiderDataSource
from engine.universe_builder import UniverseBuilder


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

POSITIONS_CSV = DATA_DIR / "schwab_positions_latest.csv"
TOP100_CSV = DATA_DIR / "mcleod_top_100_latest.csv"
REPLACEMENTS_CSV = DATA_DIR / "replacement_candidates_latest.csv"
UNIVERSE_CSV = DATA_DIR / "us_equity_universe_latest.csv"
FULL_RANKINGS_CSV = DATA_DIR / "mcleod_full_market_rankings_latest.csv"
INTELLIGENCE_JSON = DATA_DIR / "mcleod_intelligence_latest.json"
ANALYST_CSV = DATA_DIR / "analyst_estimates_latest.csv"
EARNINGS_CALL_CSV = DATA_DIR / "earnings_call_intelligence_latest.csv"

OUTPUT_JSON = DATA_DIR / "insider_transactions_latest.json"
OUTPUT_CSV = DATA_DIR / "insider_transactions_latest.csv"
OUTPUT_HISTORY_CSV = DATA_DIR / "insider_signal_history.csv"

REPORT_MD = REPORTS_DIR / "insider_intelligence_report.md"

NEEDS_RESEARCH = "NEEDS_RESEARCH"

SECTOR_ETF_MAP = {
    "INFORMATION_TECHNOLOGY": "XLK",
    "FINANCIALS": "XLF",
    "HEALTH_CARE": "XLV",
    "CONSUMER_DISCRETIONARY": "XLY",
    "CONSUMER_STAPLES": "XLP",
    "INDUSTRIALS": "XLI",
    "MATERIALS": "XLB",
    "UTILITIES": "XLU",
    "COMMUNICATION_SERVICES": "XLC",
    "ENERGY": "XLE",
    "REAL_ESTATE": "XLRE",
}


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, "", "NA", "N/A", NEEDS_RESEARCH):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "NA", "N/A"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx = _mean(x)
    my = _mean(y)
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0 or vy <= 0:
        return 0.0
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return cov / math.sqrt(vx * vy)


def _rankdata(values: Sequence[float]) -> List[float]:
    indexed = sorted(enumerate(values), key=lambda t: t[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def _spearman(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    return _pearson(_rankdata(x), _rankdata(y))


class YahooCloseClient:
    def __init__(self):
        from engine.model_evaluator import YahooDailyClient

        self.client = YahooDailyClient()

    def close_on_or_after(self, symbol: str, target_date: date) -> Optional[float]:
        series = self.client.load(symbol, target_date - timedelta(days=45), date.today() + timedelta(days=2))
        return series.close_on_or_after(target_date)

    def close_around(self, symbol: str, target_date: date, days_offset: int) -> Optional[float]:
        shifted = target_date + timedelta(days=days_offset)
        series = self.client.load(symbol, min(target_date, shifted) - timedelta(days=10), max(target_date, shifted) + timedelta(days=10))
        return series.close_on_or_after(shifted)


@dataclass
class PredictiveStats:
    horizon_label: str
    resolved_count: int
    insider_ic: float
    base_ic: float
    combined_ic: float
    incremental_ic: float


class InsiderIntelligenceEngine:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.source = InsiderDataSource()
        self.close_client = YahooCloseClient()
        self.refresh_limit = int(__import__("os").getenv("INSIDER_REFRESH_LIMIT", "140"))
        self.force_refresh = __import__("os").getenv("INSIDER_FORCE_REFRESH", "0") == "1"
        self.include_full_universe = __import__("os").getenv("INSIDER_INCLUDE_FULL_UNIVERSE", "0") == "1"

        self.rank_context = self._load_rank_context()
        self.analyst_map = self._load_csv_map(ANALYST_CSV, "symbol")
        self.earnings_call_map = self._load_csv_map(EARNINGS_CALL_CSV, "symbol")

    def _load_csv_map(self, path: Path, key: str) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        if not path.exists():
            return out
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                k = str(row.get(key, "")).upper().strip()
                if k:
                    out[k] = row
        return out

    def _load_rank_context(self) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        if FULL_RANKINGS_CSV.exists():
            with open(FULL_RANKINGS_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        out[sym] = row
        if INTELLIGENCE_JSON.exists():
            try:
                with open(INTELLIGENCE_JSON, encoding="utf-8") as f:
                    payload = json.load(f)
                for row in payload.get("holdings", []):
                    sym = str(row.get("symbol", "")).upper().strip()
                    if not sym:
                        continue
                    merged = dict(out.get(sym, {}))
                    merged.update({k: str(v) for k, v in row.items() if not isinstance(v, (dict, list))})
                    out[sym] = merged
            except Exception:
                pass
        return out

    def _load_target_symbols(self) -> List[str]:
        if not UNIVERSE_CSV.exists():
            UniverseBuilder().build()

        holdings: List[str] = []
        if POSITIONS_CSV.exists():
            with open(POSITIONS_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if str(row.get("asset_type", "")).upper() != "EQUITY":
                        continue
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        holdings.append(sym)

        top100: List[str] = []
        if TOP100_CSV.exists():
            with open(TOP100_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        top100.append(sym)

        replacements: List[str] = []
        if REPLACEMENTS_CSV.exists():
            with open(REPLACEMENTS_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    for key in ("candidate_symbol", "replace_symbol"):
                        sym = str(row.get(key, "")).upper().strip()
                        if sym:
                            replacements.append(sym)

        universe: List[str] = []
        if self.include_full_universe and UNIVERSE_CSV.exists():
            with open(UNIVERSE_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        universe.append(sym)

        ordered: List[str] = []
        seen = set()
        for group in [holdings, top100, replacements, universe]:
            for sym in group:
                if sym not in seen:
                    ordered.append(sym)
                    seen.add(sym)
        return ordered

    def _read_csv(self, path: Path) -> List[Dict[str, str]]:
        if not path.exists():
            return []
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _write_csv(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _role_weight(title: str) -> float:
        t = str(title or "").upper()
        if "FOUNDER" in t:
            return 1.0
        if "CEO" in t or "CHIEF EXECUTIVE" in t:
            return 1.0
        if "CFO" in t or "CHIEF FINANCIAL" in t:
            return 0.95
        if "CHAIRMAN" in t:
            return 0.9
        if "PRESIDENT" in t or "COO" in t:
            return 0.85
        if "DIRECTOR" in t:
            return 0.65
        return 0.55

    @staticmethod
    def _valuation_bucket(context: Dict[str, str]) -> str:
        pe = _safe_float(context.get("pe_ratio"), None)
        ps = _safe_float(context.get("price_to_sales"), None)
        if pe is not None and pe > 0:
            if pe < 12:
                return "cheap"
            if pe < 28:
                return "middle"
            return "expensive"
        if ps is not None and ps > 0:
            if ps < 2:
                return "cheap"
            if ps < 6:
                return "middle"
            return "expensive"
        return "unknown"

    def _track_record_score(self, insider_names: Sequence[str]) -> float:
        rows = self._read_csv(OUTPUT_HISTORY_CSV)
        matched: List[float] = []
        names = {str(n).strip().upper() for n in insider_names if str(n).strip()}
        if not names:
            return 50.0
        for row in rows:
            if str(row.get("resolved_6m", "0")) != "1":
                continue
            row_names = {part.strip().upper() for part in str(row.get("primary_buyer_names", "")).split("|") if part.strip()}
            if names.intersection(row_names):
                ret = _safe_float(row.get("excess_vs_spy_6m_pct"), None)
                if ret is not None:
                    matched.append(ret)
        if not matched:
            return 50.0
        return _clamp(50.0 + _mean(matched) * 2.0)

    def _context_alignment_score(self, symbol: str, buy_date: Optional[date], context: Dict[str, str]) -> float:
        if buy_date is None:
            return 50.0
        buy_px = self.close_client.close_on_or_after(symbol, buy_date)
        prev_px = self.close_client.close_around(symbol, buy_date, -30)
        decline_score = 50.0
        if buy_px is not None and prev_px is not None and prev_px > 0:
            change = ((buy_px / prev_px) - 1.0) * 100.0
            decline_score = _clamp(55.0 + max(0.0, -change) * 2.2 - max(0.0, change) * 1.5)

        valuation = _safe_float(context.get("component_valuation") or context.get("valuation_score"), None)
        business = _safe_float(context.get("component_quality") or context.get("business_quality"), None)
        liquidity = _safe_float(context.get("component_liquidity") or context.get("liquidity_score"), None)
        balance = _safe_float(context.get("current_ratio"), None)
        debt = _safe_float(context.get("debt_to_equity"), None)

        parts = [decline_score]
        if valuation is not None:
            parts.append(valuation)
        if business is not None:
            parts.append(business)
        if liquidity is not None:
            parts.append(liquidity)
        if balance is not None:
            parts.append(_clamp(balance * 30.0))
        if debt is not None:
            parts.append(_clamp(100.0 - debt * 18.0))
        return _clamp(_mean(parts)) if parts else 50.0

    def _score_symbol(self, symbol: str, transactions: List[Dict[str, Any]], context: Dict[str, str]) -> Dict[str, Any]:
        open_buys = [t for t in transactions if t.get("transaction_type") == "open-market purchase"]
        open_sales = [t for t in transactions if t.get("transaction_type") == "open-market sale"]
        discounted_sales = [t for t in transactions if t.get("transaction_type") == "automatic 10b5-1 sale"]

        recent_90 = []
        recent_30 = []
        recent_7 = []
        now = datetime.now().date()
        for t in open_buys:
            try:
                d = date.fromisoformat(str(t.get("transaction_date", "")))
            except Exception:
                continue
            age = (now - d).days
            if age <= 90:
                recent_90.append(t)
            if age <= 30:
                recent_30.append(t)
            if age <= 7:
                recent_7.append(t)

        positive_buys = recent_90
        cluster_names = sorted({str(t.get("insider_name", "")).strip() for t in positive_buys if str(t.get("insider_name", "")).strip()})
        executive_buys = [t for t in positive_buys if self._role_weight(str(t.get("insider_title", ""))) >= 0.85]
        director_only = positive_buys and not executive_buys

        total_buy_value = sum(_safe_float(t.get("total_dollar_value"), 0.0) or 0.0 for t in positive_buys)
        max_buy_value = max([_safe_float(t.get("total_dollar_value"), 0.0) or 0.0 for t in positive_buys] + [0.0])
        max_pct_increase = max([_safe_float(t.get("pct_increase_ownership"), 0.0) or 0.0 for t in positive_buys] + [0.0])

        market_cap = _safe_float(context.get("market_cap"), None)
        rel_market_cap = 0.0
        if market_cap and market_cap > 0:
            rel_market_cap = (total_buy_value / market_cap) * 100.0

        avg_hist_value = _mean([_safe_float(t.get("total_dollar_value"), 0.0) or 0.0 for t in transactions]) if transactions else 0.0
        relative_hist = (max_buy_value / avg_hist_value) if avg_hist_value > 0 else 1.0

        primary_buyer_titles = [str(t.get("insider_title", "")) for t in positive_buys]
        role_score = _clamp(_mean([self._role_weight(t) * 100.0 for t in primary_buyer_titles])) if primary_buyer_titles else 0.0
        track_score = self._track_record_score(cluster_names)

        significance_parts = []
        if max_buy_value > 0:
            significance_parts.append(_clamp(25.0 + math.log10(max(1.0, max_buy_value)) * 10.0))
        significance_parts.append(_clamp(45.0 + max_pct_increase * 5.0))
        significance_parts.append(_clamp(50.0 + rel_market_cap * 350.0))
        significance_parts.append(_clamp(40.0 + min(relative_hist, 6.0) * 10.0))
        significance_score = _clamp(_mean([p for p in significance_parts if p > 0])) if significance_parts else 0.0

        open_market_buy_score = _clamp(
            0.45 * significance_score
            + 0.30 * role_score
            + 0.25 * _clamp(35.0 + len(positive_buys) * 8.0)
        ) if positive_buys else 0.0

        cluster_buying_score = 0.0
        if positive_buys:
            cluster_parts = [
                _clamp(35.0 + len(cluster_names) * 18.0),
                _clamp(35.0 + len(recent_30) * 8.0),
                _clamp(45.0 + len(executive_buys) * 14.0),
                _clamp(40.0 + math.log10(max(1.0, total_buy_value)) * 8.0),
            ]
            cluster_buying_score = _clamp(_mean(cluster_parts))

        latest_buy_date = None
        if positive_buys:
            try:
                latest_buy_date = max(date.fromisoformat(str(t.get("transaction_date", ""))) for t in positive_buys)
            except Exception:
                latest_buy_date = None

        alignment_score = self._context_alignment_score(symbol, latest_buy_date, context) if positive_buys else 50.0

        overall_score = _clamp(
            open_market_buy_score * 0.30
            + significance_score * 0.22
            + cluster_buying_score * 0.18
            + alignment_score * 0.12
            + role_score * 0.10
            + track_score * 0.08
        )
        thesis_impact = _clamp(overall_score * 0.7 + cluster_buying_score * 0.15 + alignment_score * 0.15)

        repeated_large_sales_flag = "0"
        large_sales_total = sum(_safe_float(t.get("total_dollar_value"), 0.0) or 0.0 for t in open_sales)
        if len(open_sales) >= 2 and large_sales_total >= 1_000_000:
            repeated_large_sales_flag = "1"

        if thesis_impact >= 70:
            thesis_signal = "strengthening thesis"
        elif thesis_impact >= 50:
            thesis_signal = "stable thesis"
        elif repeated_large_sales_flag == "1":
            thesis_signal = "weakening thesis"
        else:
            thesis_signal = "stable thesis" if not positive_buys else "weakening thesis"

        return {
            "open_market_buys": positive_buys,
            "open_sales": open_sales,
            "discounted_sales": discounted_sales,
            "insider_open_market_buy_score": round(open_market_buy_score, 2),
            "insider_significance_score": round(significance_score, 2),
            "insider_cluster_buying_score": round(cluster_buying_score, 2),
            "insider_alignment_score": round(alignment_score, 2),
            "insider_track_record_score": round(track_score, 2),
            "insider_quality_score": round(role_score, 2),
            "insider_intelligence_score": round(overall_score, 2),
            "insider_thesis_impact_score": round(thesis_impact, 2),
            "insider_thesis_signal": thesis_signal,
            "insider_cluster_buyers_count_7d": len({str(t.get('insider_name', '')).strip() for t in recent_7 if str(t.get('insider_name', '')).strip()}),
            "insider_cluster_buyers_count_30d": len({str(t.get('insider_name', '')).strip() for t in recent_30 if str(t.get('insider_name', '')).strip()}),
            "insider_cluster_buyers_count_90d": len(cluster_names),
            "insider_cluster_dollar_value_90d": round(total_buy_value, 2),
            "insider_executive_cluster_flag": "1" if executive_buys else "0",
            "insider_director_only_cluster_flag": "1" if director_only else "0",
            "insider_repeated_large_sales_flag": repeated_large_sales_flag,
            "insider_large_sales_value_90d": round(large_sales_total, 2),
            "primary_buyer_names": "|".join(cluster_names[:10]) if cluster_names else NEEDS_RESEARCH,
            "primary_buyer_titles": "|".join(sorted({str(t.get('insider_title', '')).strip() for t in positive_buys if str(t.get('insider_title', '')).strip()})[:10]) if positive_buys else NEEDS_RESEARCH,
        }

    def _build_explainability(self, scored: Dict[str, Any]) -> str:
        lines = ["Insider Intelligence:"]
        buyers = scored.get("open_market_buys", [])
        if not buyers:
            lines.append("- No high-signal discretionary open-market purchases found in recent SEC Form 4 filings")
            if scored.get("insider_repeated_large_sales_flag") == "1":
                lines.append("- Repeated large insider sales flagged for review")
            return "\n".join(lines)

        top_buys = sorted(buyers, key=lambda t: _safe_float(t.get("total_dollar_value"), 0.0) or 0.0, reverse=True)[:3]
        for tx in top_buys:
            name = str(tx.get("insider_name", "Unknown"))
            title = str(tx.get("insider_title", "Insider"))
            value = _safe_float(tx.get("total_dollar_value"), 0.0) or 0.0
            pct = _safe_float(tx.get("pct_increase_ownership"), None)
            pct_text = f"{pct:.2f}% ownership increase" if pct is not None else "ownership increase unavailable"
            lines.append(f"- {name} ({title}) bought ${value:,.0f}; {pct_text}")
            lines.append(f"- Source: {tx.get('source_url', 'N/A')}")

        cluster_count = _safe_int(scored.get("insider_cluster_buyers_count_90d"), 0)
        if cluster_count > 1:
            lines.append(f"- Multiple insiders bought within 90 days ({cluster_count} buyers)")
        else:
            lines.append("- Single-insider signal only")

        if scored.get("insider_executive_cluster_flag") == "1":
            lines.append("- Signal is stronger because executive buyers participated")
        if scored.get("insider_repeated_large_sales_flag") == "1":
            lines.append("- Repeated large insider sales also flagged for review")

        return "\n".join(lines)

    def _build_metric_fields(self, row: Dict[str, Any], source: str, timestamp: str, confidence: int, stale: bool) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for metric, value in row.items():
            out[metric] = value if value not in (None, "") else NEEDS_RESEARCH
            out[f"{metric}_source"] = source
            out[f"{metric}_timestamp"] = timestamp
            out[f"{metric}_confidence"] = confidence if value not in (None, "") else 0
            out[f"{metric}_stale"] = stale if value not in (None, "") else True
        return out

    def _append_history(self, rows: List[Dict[str, Any]], as_of: date) -> None:
        existing = self._read_csv(OUTPUT_HISTORY_CSV)
        seen = {(r.get("snapshot_date", ""), r.get("symbol", "")) for r in existing}
        for row in rows:
            sym = str(row.get("symbol", "")).upper()
            key = (as_of.isoformat(), sym)
            if key in seen:
                continue
            context = self.rank_context.get(sym, {})
            existing.append(
                {
                    "snapshot_date": as_of.isoformat(),
                    "symbol": sym,
                    "insider_intelligence_score": row.get("insider_intelligence_score", NEEDS_RESEARCH),
                    "insider_thesis_impact_score": row.get("insider_thesis_impact_score", NEEDS_RESEARCH),
                    "base_composite_score": context.get("composite_score", ""),
                    "analyst_alpha_score": (self.analyst_map.get(sym, {}) or {}).get("analyst_alpha_score", ""),
                    "earnings_call_score": (self.earnings_call_map.get(sym, {}) or {}).get("earnings_call_intelligence_score", ""),
                    "sector": context.get("sector", ""),
                    "sector_benchmark": SECTOR_ETF_MAP.get(str(context.get("sector", "")).upper(), "SPY"),
                    "valuation_bucket": self._valuation_bucket(context),
                    "cluster_type": "executive" if row.get("insider_executive_cluster_flag") == "1" else ("director_only" if row.get("insider_director_only_cluster_flag") == "1" else "none"),
                    "primary_buyer_names": row.get("primary_buyer_names", ""),
                    "resolved_3m": "0",
                    "resolved_6m": "0",
                    "resolved_12m": "0",
                    "resolved_24m": "0",
                    "return_3m_pct": "",
                    "return_6m_pct": "",
                    "return_12m_pct": "",
                    "return_24m_pct": "",
                    "spy_return_3m_pct": "",
                    "spy_return_6m_pct": "",
                    "spy_return_12m_pct": "",
                    "spy_return_24m_pct": "",
                    "sector_return_3m_pct": "",
                    "sector_return_6m_pct": "",
                    "sector_return_12m_pct": "",
                    "sector_return_24m_pct": "",
                    "peer_return_3m_pct": "",
                    "peer_return_6m_pct": "",
                    "peer_return_12m_pct": "",
                    "peer_return_24m_pct": "",
                    "excess_vs_spy_3m_pct": "",
                    "excess_vs_spy_6m_pct": "",
                    "excess_vs_spy_12m_pct": "",
                    "excess_vs_spy_24m_pct": "",
                    "excess_vs_sector_3m_pct": "",
                    "excess_vs_sector_6m_pct": "",
                    "excess_vs_sector_12m_pct": "",
                    "excess_vs_sector_24m_pct": "",
                    "excess_vs_peer_3m_pct": "",
                    "excess_vs_peer_6m_pct": "",
                    "excess_vs_peer_12m_pct": "",
                    "excess_vs_peer_24m_pct": "",
                    "last_evaluated_at": "",
                }
            )
        self._write_csv(OUTPUT_HISTORY_CSV, existing)

    def _resolve_history_returns(self, as_of: date) -> List[Dict[str, str]]:
        rows = self._read_csv(OUTPUT_HISTORY_CSV)
        updated: List[Dict[str, str]] = []
        horizons = [("3m", 63), ("6m", 126), ("12m", 252), ("24m", 504)]
        for row in rows:
            out = dict(row)
            sym = str(row.get("symbol", "")).upper().strip()
            if not sym:
                updated.append(out)
                continue
            try:
                snap = date.fromisoformat(str(row.get("snapshot_date", "")))
            except Exception:
                updated.append(out)
                continue

            for label, offset in horizons:
                res_key = f"resolved_{label}"
                ret_key = f"return_{label}_pct"
                spy_key = f"spy_return_{label}_pct"
                sec_key = f"sector_return_{label}_pct"
                ex_spy = f"excess_vs_spy_{label}_pct"
                ex_sec = f"excess_vs_sector_{label}_pct"
                if str(out.get(res_key, "0")) == "1":
                    continue
                if as_of < snap + timedelta(days=max(45, int(offset * 0.7))):
                    continue
                base = self.close_client.close_on_or_after(sym, snap)
                fut = self.close_client.close_around(sym, snap, offset)
                spy_base = self.close_client.close_on_or_after("SPY", snap)
                spy_fut = self.close_client.close_around("SPY", snap, offset)
                sec_sym = str(out.get("sector_benchmark", "SPY") or "SPY")
                sec_base = self.close_client.close_on_or_after(sec_sym, snap)
                sec_fut = self.close_client.close_around(sec_sym, snap, offset)
                if base is None or fut is None or base <= 0:
                    continue
                ret = ((fut / base) - 1.0) * 100.0
                out[ret_key] = f"{ret:.6f}"
                out[res_key] = "1"
                if spy_base and spy_fut and spy_base > 0:
                    spy_ret = ((spy_fut / spy_base) - 1.0) * 100.0
                    out[spy_key] = f"{spy_ret:.6f}"
                    out[ex_spy] = f"{(ret - spy_ret):.6f}"
                if sec_base and sec_fut and sec_base > 0:
                    sec_ret = ((sec_fut / sec_base) - 1.0) * 100.0
                    out[sec_key] = f"{sec_ret:.6f}"
                    out[ex_sec] = f"{(ret - sec_ret):.6f}"

            out["last_evaluated_at"] = datetime.now().isoformat(timespec="seconds")
            updated.append(out)

        # peer cohorts by snapshot and valuation bucket
        for label, _ in horizons:
            res_key = f"resolved_{label}"
            ret_key = f"return_{label}_pct"
            peer_key = f"peer_return_{label}_pct"
            ex_peer = f"excess_vs_peer_{label}_pct"
            groups: Dict[Tuple[str, str], List[float]] = {}
            for row in updated:
                if str(row.get(res_key, "0")) != "1":
                    continue
                bucket = str(row.get("valuation_bucket", "unknown"))
                snap = str(row.get("snapshot_date", ""))
                ret = _safe_float(row.get(ret_key), None)
                if ret is None:
                    continue
                groups.setdefault((snap, bucket), []).append(ret)
            for row in updated:
                if str(row.get(res_key, "0")) != "1":
                    continue
                bucket = str(row.get("valuation_bucket", "unknown"))
                snap = str(row.get("snapshot_date", ""))
                ret = _safe_float(row.get(ret_key), None)
                peers = groups.get((snap, bucket), [])
                if ret is None or len(peers) < 2:
                    continue
                peer_ret = median(peers)
                row[peer_key] = f"{peer_ret:.6f}"
                row[ex_peer] = f"{(ret - peer_ret):.6f}"

        self._write_csv(OUTPUT_HISTORY_CSV, updated)
        return updated

    def _predictive_stats(self, rows: List[Dict[str, str]]) -> List[PredictiveStats]:
        out: List[PredictiveStats] = []
        for label in ["3m", "6m", "12m", "24m"]:
            x_insider: List[float] = []
            x_base: List[float] = []
            y: List[float] = []
            for r in rows:
                if str(r.get(f"resolved_{label}", "0")) != "1":
                    continue
                insider = _safe_float(r.get("insider_intelligence_score"), None)
                base = _safe_float(r.get("base_composite_score"), None)
                analyst = _safe_float(r.get("analyst_alpha_score"), 0.0) or 0.0
                call = _safe_float(r.get("earnings_call_score"), 0.0) or 0.0
                ret = _safe_float(r.get(f"excess_vs_spy_{label}_pct"), None)
                if insider is None or ret is None:
                    continue
                x_insider.append(insider)
                x_base.append((base or 0.0) * 0.7 + analyst * 0.15 + call * 0.15)
                y.append(ret)
            if len(y) < 2:
                out.append(PredictiveStats(label, len(y), 0.0, 0.0, 0.0, 0.0))
                continue
            insider_ic = _spearman(x_insider, y)
            base_ic = _spearman(x_base, y)
            combined = [0.75 * b + 0.25 * i for b, i in zip(x_base, x_insider)]
            combined_ic = _spearman(combined, y)
            out.append(PredictiveStats(label, len(y), insider_ic, base_ic, combined_ic, combined_ic - base_ic))
        return out

    def _subgroup_summary(self, history_rows: List[Dict[str, str]], label: str) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for group in ["executive", "director_only"]:
            vals = [
                _safe_float(r.get(f"excess_vs_spy_{label}_pct"), None)
                for r in history_rows
                if str(r.get(f"resolved_{label}", "0")) == "1" and str(r.get("cluster_type", "")) == group
            ]
            vals = [v for v in vals if v is not None]
            if vals:
                out[group] = _mean(vals)
        for group in ["cluster", "single"]:
            vals = [
                _safe_float(r.get(f"excess_vs_spy_{label}_pct"), None)
                for r in history_rows
                if str(r.get(f"resolved_{label}", "0")) == "1" and ((group == "cluster" and _safe_int(r.get("insider_cluster_buyers_count_90d", 0), 0) > 1) or (group == "single" and _safe_int(r.get("insider_cluster_buyers_count_90d", 0), 0) <= 1))
            ]
            vals = [v for v in vals if v is not None]
            if vals:
                out[group] = _mean(vals)
        return out

    def _weight_recommendation(self, stats: List[PredictiveStats]) -> str:
        valid = [s for s in stats if s.resolved_count >= 40 and s.incremental_ic > 0.03]
        if not valid:
            return "No meaningful insider model weight change recommended yet: insufficient or weak out-of-sample predictive evidence."
        avg_inc = _mean([s.incremental_ic for s in valid])
        weight = min(0.08, max(0.02, avg_inc * 1.5))
        return (
            f"Proposed insider factor weight: {weight:.2%}, conditioned on manual approval and continued walk-forward OOS validation. "
            "No automatic production weight changes are applied by this engine."
        )

    def _write_reports(self, rows: List[Dict[str, Any]], history_rows: List[Dict[str, str]], stats: List[PredictiveStats], recommendation: str) -> None:
        scores = [_safe_float(r.get("insider_intelligence_score"), None) for r in rows]
        scores = [s for s in scores if s is not None]
        total_slots = 0
        populated = 0
        valuable = 0
        for row in rows:
            for key, value in row.items():
                if key.endswith("_source") or key.endswith("_timestamp") or key.endswith("_confidence") or key.endswith("_stale"):
                    continue
                if key in {"symbol", "as_of", "insider_engine_version", "refresh_deferred", "recent_transactions_json"}:
                    continue
                total_slots += 1
                if value != NEEDS_RESEARCH:
                    populated += 1
                    conf = _safe_float(row.get(f"{key}_confidence"), 0.0) or 0.0
                    if conf >= 60:
                        valuable += 1
        dq = (populated / total_slots * 100.0) if total_slots else 0.0
        dv = (valuable / total_slots * 100.0) if total_slots else 0.0
        top = sorted(rows, key=lambda r: _safe_float(r.get("insider_intelligence_score"), -1.0) or -1.0, reverse=True)[:10]
        subgroup_6m = self._subgroup_summary(history_rows, "6m")

        lines = [
            "# Insider Intelligence Report",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Data Quality Dashboard",
            "",
            f"- Universe rows: {len(rows)}",
            f"- Insider metric coverage: {dq:.2f}%",
            "",
            "## Data Value Dashboard",
            "",
            f"- High-confidence insider coverage (confidence >= 60): {dv:.2f}%",
            f"- Average Insider Intelligence Score: {_mean(scores):.2f}" if scores else "- Average Insider Intelligence Score: N/A",
            "",
            "## Explainability Report",
            "",
        ]
        for row in top:
            lines.extend([
                f"### {row.get('symbol', 'N/A')} (Insider Score: {row.get('insider_intelligence_score', NEEDS_RESEARCH)})",
                str(row.get("insider_explainability", "Insider Intelligence: unavailable")),
                "",
            ])

        lines.extend([
            "## Predictive Performance (3m/6m/12m/24m)",
            "",
            "| Horizon | Resolved Samples | Insider IC | Base IC | Combined IC | Incremental IC |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for st in stats:
            lines.append(f"| {st.horizon_label} | {st.resolved_count} | {st.insider_ic:.4f} | {st.base_ic:.4f} | {st.combined_ic:.4f} | {st.incremental_ic:.4f} |")

        lines.extend([
            "",
            "## Subgroup Checks",
            "",
            f"- Executive buyers 6m avg excess vs SPY: {subgroup_6m.get('executive', 0.0):.2f}%" if 'executive' in subgroup_6m else "- Executive buyers 6m avg excess vs SPY: N/A",
            f"- Director-only buyers 6m avg excess vs SPY: {subgroup_6m.get('director_only', 0.0):.2f}%" if 'director_only' in subgroup_6m else "- Director-only buyers 6m avg excess vs SPY: N/A",
            f"- Cluster-buying 6m avg excess vs SPY: {subgroup_6m.get('cluster', 0.0):.2f}%" if 'cluster' in subgroup_6m else "- Cluster-buying 6m avg excess vs SPY: N/A",
            f"- Single-buyer 6m avg excess vs SPY: {subgroup_6m.get('single', 0.0):.2f}%" if 'single' in subgroup_6m else "- Single-buyer 6m avg excess vs SPY: N/A",
            "",
            "## Weight Governance",
            "",
            f"- {recommendation}",
            "- Non-discretionary transactions are excluded or heavily discounted.",
            "- Insider sales are not treated as automatically bearish; repeated large sales are only flagged for review.",
            "",
        ])
        REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        as_of_date = as_of or date.today()
        symbols = self._load_target_symbols()
        prior_rows = self._read_csv(OUTPUT_CSV)
        prior_by_symbol = {str(r.get("symbol", "")).upper(): r for r in prior_rows}

        rows: List[Dict[str, Any]] = []
        refresh_count = 0
        print(f"[Insider] Target symbols: {len(symbols)} | refresh limit: {self.refresh_limit} | full universe: {self.include_full_universe}", flush=True)
        for symbol in symbols:
            has_cache = symbol in self.source.cache
            cached_ts = str((self.source.cache.get(symbol) or {}).get("timestamp", "")) if has_cache else ""
            has_fresh_cache = bool(cached_ts and self.source._cache_is_fresh(cached_ts))
            if self.force_refresh:
                should_refresh = refresh_count < self.refresh_limit
            else:
                should_refresh = has_fresh_cache or (refresh_count < self.refresh_limit)

            payload = self.source.fetch_symbol(symbol, force_refresh=self.force_refresh) if should_refresh else {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "source": "SEC Form 4 Insider Transactions (refresh deferred)",
                "stale": True,
                "confidence": 0,
                "data": {"transactions": []},
            }
            if should_refresh and (self.force_refresh or not has_fresh_cache):
                refresh_count += 1

            raw = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
            transactions = list(raw.get("transactions", [])) if isinstance(raw.get("transactions"), list) else []
            context = self.rank_context.get(symbol, {})
            scored = self._score_symbol(symbol, transactions, context)
            scored["insider_recent_transactions_count"] = len(transactions)
            scored["recent_transactions_json"] = json.dumps(transactions[:20]) if transactions else NEEDS_RESEARCH
            scored["insider_missing_data_reason"] = NEEDS_RESEARCH if transactions else "No recent SEC Form 4 filings found or parsed for target window"
            scored["insider_source_url_count"] = len({str(t.get('source_url', '')).strip() for t in transactions if str(t.get('source_url', '')).strip()})
            scored["insider_explainability"] = self._build_explainability(scored)

            source_name = str(payload.get("source", self.source.name))
            ts = str(payload.get("timestamp", datetime.now().isoformat()))
            stale = bool(payload.get("stale", False))
            conf = int(payload.get("confidence", 0))

            metric_view = {k: v for k, v in scored.items() if k not in {"open_market_buys", "open_sales", "discounted_sales"}}
            row = {
                "symbol": symbol,
                "as_of": as_of_date.isoformat(),
                "insider_engine_version": "1.0.0",
                "refresh_deferred": "1" if not should_refresh else "0",
            }
            row.update(self._build_metric_fields(metric_view, source_name, ts, conf, stale))
            rows.append(row)

            if len(rows) % 10 == 0 or len(rows) == len(symbols):
                print(f"[Insider] Processed {len(rows)}/{len(symbols)} symbols", flush=True)

        output_json = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "engine": "McLeod Insider Intelligence Engine",
                "version": "1.0.0",
                "symbols": len(symbols),
                "rows": len(rows),
                "refresh_limit": self.refresh_limit,
            },
            "holdings": rows,
        }
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output_json, f, indent=2)
        self._write_csv(OUTPUT_CSV, rows)
        self._append_history(rows, as_of_date)
        fast_mode = __import__("os").getenv(
            "INSIDER_FAST_MODE",
            __import__("os").getenv("SPECIALIST_FAST_MODE", "0"),
        ) == "1"
        if fast_mode:
            history_rows = []
            stats = []
            recommendation = "Fast mode: predictive backtest refresh deferred for this run."
        else:
            history_rows = self._resolve_history_returns(as_of_date)
            stats = self._predictive_stats(history_rows)
            recommendation = self._weight_recommendation(stats)
        self._write_reports(rows, history_rows, stats, recommendation)

        return {
            "as_of": as_of_date.isoformat(),
            "symbols_targeted": len(symbols),
            "rows_written": len(rows),
            "output_json": str(OUTPUT_JSON),
            "output_csv": str(OUTPUT_CSV),
            "history_csv": str(OUTPUT_HISTORY_CSV),
            "report": str(REPORT_MD),
            "weight_recommendation": recommendation,
        }


def run_insider_intelligence(as_of: Optional[date] = None) -> Dict[str, Any]:
    return InsiderIntelligenceEngine().run(as_of=as_of)


def main() -> int:
    result = run_insider_intelligence()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
