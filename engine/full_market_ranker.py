#!/usr/bin/env python3
"""
McLeod Full Market Ranker

Expands McLeod Core Rankings from current holdings to a broad U.S. common-stock universe.

Pipeline:
1) Build/refresh universe
2) Fast first-pass screening with liquidity and basic fundamentals
3) Deep SEC/IBD/fundamental scoring for strongest candidates
4) Compare full-market candidates against current holdings
5) Generate ranking/replacement outputs + report

Outputs:
- data/mcleod_full_market_rankings_latest.csv
- data/mcleod_top_100_latest.csv
- data/replacement_candidates_latest.csv
- reports/full_market_core_rankings.md
"""

import csv
import json
import math
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.universe_builder import UniverseBuilder
from engine.data_sources.sec_source import SECDataSource
from engine.data_sources.finviz_source import FinvizDataSource
from engine.data_sources.ibd_source import IBDDataSource


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

UNIVERSE_CSV = DATA_DIR / "us_equity_universe_latest.csv"
POSITIONS_CSV = DATA_DIR / "schwab_positions_latest.csv"
IBD_CSV = DATA_DIR / "ibd_rankings_manual.csv"
ANALYST_CSV = DATA_DIR / "analyst_estimates_latest.csv"
EARNINGS_CALL_CSV = DATA_DIR / "earnings_call_intelligence_latest.csv"
INSIDER_CSV = DATA_DIR / "insider_transactions_latest.csv"
EARNINGS_QUALITY_CSV = DATA_DIR / "earnings_quality_latest.csv"
CAPITAL_ALLOCATION_CSV = DATA_DIR / "capital_allocation_latest.csv"

CHECKPOINT = DATA_DIR / "full_market_ranker_checkpoint.json"
FULL_RANKINGS_CSV = DATA_DIR / "mcleod_full_market_rankings_latest.csv"
TOP100_CSV = DATA_DIR / "mcleod_top_100_latest.csv"
REPLACEMENTS_CSV = DATA_DIR / "replacement_candidates_latest.csv"
REPORT_MD = REPORTS_DIR / "full_market_core_rankings.md"

MIN_DOLLAR_VOLUME = 5_000_000
MIN_MARKET_CAP = 300_000_000
MIN_DATA_QUALITY = 70.0
MAX_DEEP_CANDIDATES = int(os.getenv("MAX_DEEP_CANDIDATES", "1000"))
BATCH_SIZE = 60
MEANINGFUL_MARGIN = 8.0
FIRST_PASS_MAX_PER_RUN = int(os.getenv("FIRST_PASS_MAX_PER_RUN", "700"))

EXCLUDED_REPLACEMENT = {"SPCX"}


class FullMarketRanker:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        self.sec = SECDataSource()
        self.finviz = FinvizDataSource()
        self.ibd = IBDDataSource(IBD_CSV)

        self.universe = self._load_universe()
        self.universe_by_symbol = {u.get("symbol", ""): u for u in self.universe if u.get("symbol")}
        self.holdings = self._load_holdings()
        self.checkpoint = self._load_checkpoint()
        self.analyst_map = self._load_csv_map(ANALYST_CSV)
        self.earnings_call_map = self._load_csv_map(EARNINGS_CALL_CSV)
        self.insider_map = self._load_csv_map(INSIDER_CSV)
        self.earnings_quality_map = self._load_csv_map(EARNINGS_QUALITY_CSV)
        self.capital_allocation_map = self._load_csv_map(CAPITAL_ALLOCATION_CSV)

    def _load_universe(self) -> List[Dict[str, Any]]:
        if not UNIVERSE_CSV.exists():
            UniverseBuilder().build()
        with open(UNIVERSE_CSV) as f:
            return list(csv.DictReader(f))

    def _load_holdings(self) -> Dict[str, Dict[str, Any]]:
        out = {}
        if POSITIONS_CSV.exists():
            with open(POSITIONS_CSV) as f:
                for row in csv.DictReader(f):
                    if row.get("asset_type", "").upper() == "EQUITY":
                        out[row.get("symbol", "").upper()] = row
        return out

    def _load_csv_map(self, path: Path) -> Dict[str, Dict[str, Any]]:
        out = {}
        if not path.exists():
            return out
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("symbol", "")).upper().strip()
                if sym:
                    out[sym] = row
        return out

    def _load_checkpoint(self) -> Dict[str, Any]:
        if CHECKPOINT.exists():
            try:
                with open(CHECKPOINT) as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "metadata": {"created_at": datetime.now().isoformat()},
            "processed": {},
            "deep_scored": {},
        }

    def _save_checkpoint(self):
        with open(CHECKPOINT, "w") as f:
            json.dump(self.checkpoint, f, indent=2)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value in (None, "", "NEEDS_RESEARCH"):
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _normalize(value: float, min_v: float, max_v: float) -> float:
        if max_v <= min_v:
            return 0.0
        v = max(min_v, min(max_v, value))
        return ((v - min_v) / (max_v - min_v)) * 100.0

    @staticmethod
    def _letter_to_score(letter: Any) -> float:
        mapping = {"A+": 95, "A": 90, "B+": 80, "B": 75, "C": 60, "D": 45, "E": 30}
        if letter in (None, "", "NEEDS_RESEARCH"):
            return 0.0
        return float(mapping.get(str(letter).strip().upper(), 0.0))

    def _snapshot_value(self, snapshot: Dict[str, str], key: str) -> Optional[str]:
        if not snapshot:
            return None
        return snapshot.get(key)

    def first_pass_screen(self):
        symbols_to_process = [u["symbol"] for u in self.universe if u.get("symbol") and u["symbol"] not in self.checkpoint["processed"]]
        if not symbols_to_process:
            return

        # Prioritize current holdings first, then alphabetical sweep of remaining universe.
        holding_priority = [s for s in self.holdings.keys() if s in symbols_to_process]
        remaining = sorted([s for s in symbols_to_process if s not in set(holding_priority)])
        ordered = holding_priority + remaining

        # Limit each run to a bounded slice; checkpoint resume handles full-universe completion over time.
        symbols_this_run = ordered[:FIRST_PASS_MAX_PER_RUN]

        for i in range(0, len(symbols_this_run), BATCH_SIZE):
            batch = symbols_this_run[i : i + BATCH_SIZE]
            for symbol in batch:
                entry = {
                    "symbol": symbol,
                    "status": "blocked",
                    "reason": "insufficient_data",
                    "exchange": "",
                    "company_name": "",
                    "sector": "",
                    "industry": "",
                    "market_cap": 0.0,
                    "avg_volume": 0.0,
                    "price": 0.0,
                    "avg_dollar_volume": 0.0,
                    "first_pass_score": 0.0,
                    "last_refresh": datetime.now().isoformat(),
                }

                u = self.universe_by_symbol.get(symbol)
                if u:
                    entry["exchange"] = u.get("exchange", "")
                    entry["company_name"] = u.get("company_name", "")

                try:
                    snapshot = self.finviz._fetch_snapshot(symbol)
                    if not snapshot:
                        entry["reason"] = "finviz_unavailable"
                        self.checkpoint["processed"][symbol] = entry
                        continue

                    mc = self.finviz._parse_numeric_value(self._snapshot_value(snapshot, "Market Cap") or "") or 0.0
                    avg_vol = self.finviz._parse_numeric_value(self._snapshot_value(snapshot, "Avg Volume") or "") or 0.0
                    price = self.finviz._parse_numeric_value(self._snapshot_value(snapshot, "Price") or "") or 0.0
                    sector = self._snapshot_value(snapshot, "Sector") or ""
                    industry = self._snapshot_value(snapshot, "Industry") or ""

                    entry.update(
                        {
                            "market_cap": mc,
                            "avg_volume": avg_vol,
                            "price": price,
                            "avg_dollar_volume": avg_vol * price,
                            "sector": sector,
                            "industry": industry,
                        }
                    )

                    mc_score = self._normalize(math.log10(mc + 1), 7, 13)
                    liq_score = self._normalize(math.log10(entry["avg_dollar_volume"] + 1), 6, 10)
                    entry["first_pass_score"] = round((mc_score * 0.45) + (liq_score * 0.55), 2)

                    if mc >= MIN_MARKET_CAP and entry["avg_dollar_volume"] >= MIN_DOLLAR_VOLUME:
                        entry["status"] = "pass"
                        entry["reason"] = ""
                    else:
                        entry["status"] = "blocked"
                        entry["reason"] = "liquidity_or_size_gate"

                except Exception as exc:
                    entry["status"] = "blocked"
                    entry["reason"] = f"error:{type(exc).__name__}"

                self.checkpoint["processed"][symbol] = entry

            self._save_checkpoint()

    def _sec_metric(self, symbol: str, metric: str) -> Any:
        result = self.sec.get_financial_metric(symbol, metric)
        return result.get("value", "NEEDS_RESEARCH")

    def deep_score(self):
        processed = self.checkpoint["processed"]
        pass_list = [x for x in processed.values() if x.get("status") == "pass"]

        # Ensure current holdings are always included in deep research comparison.
        hold_syms = set(self.holdings.keys())
        for sym in hold_syms:
            if sym in processed and processed[sym].get("status") != "pass":
                processed[sym]["status"] = "pass"
                processed[sym]["reason"] = "forced_holding_compare"
                pass_list.append(processed[sym])

        pass_list.sort(key=lambda x: x.get("first_pass_score", 0.0), reverse=True)

        # Expand coverage across runs by scoring previously unscored pass candidates first.
        unscored = [p for p in pass_list if p.get("symbol") not in self.checkpoint["deep_scored"]]
        already_scored = [p for p in pass_list if p.get("symbol") in self.checkpoint["deep_scored"]]
        candidates = (unscored + already_scored)[:MAX_DEEP_CANDIDATES]

        for i in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[i : i + BATCH_SIZE]
            for item in batch:
                symbol = item["symbol"]
                sec_metrics = {
                    "revenue_growth_1yr": self._sec_metric(symbol, "revenue_growth_1yr"),
                    "revenue_growth_3yr": self._sec_metric(symbol, "revenue_growth_3yr"),
                    "eps_growth_1yr": self._sec_metric(symbol, "eps_growth_1yr"),
                    "eps_growth_3yr": self._sec_metric(symbol, "eps_growth_3yr"),
                    "gross_margin": self._sec_metric(symbol, "gross_margin"),
                    "operating_margin": self._sec_metric(symbol, "operating_margin"),
                    "net_margin": self._sec_metric(symbol, "net_margin"),
                    "roic": self._sec_metric(symbol, "roic"),
                    "roe": self._sec_metric(symbol, "roe"),
                    "roa": self._sec_metric(symbol, "roa"),
                    "debt_to_equity": self._sec_metric(symbol, "debt_to_equity"),
                    "current_ratio": self._sec_metric(symbol, "current_ratio"),
                }

                # Finviz metrics from first-pass snapshot cache
                fin_metrics = self.finviz.resolve_metrics(symbol)
                pe = self._to_float(fin_metrics.get("pe_ratio", {}).get("value"))
                pb = self._to_float(fin_metrics.get("price_to_book", {}).get("value"))
                ps = self._to_float(fin_metrics.get("price_to_sales", {}).get("value"))
                pfcf = self._to_float(fin_metrics.get("price_to_fcf", {}).get("value"))

                ibd_metrics = {
                    "ibd_composite": self.ibd.get_ibd_metric(symbol, "ibd_composite").get("value", "NEEDS_RESEARCH"),
                    "ibd_eps_rating": self.ibd.get_ibd_metric(symbol, "ibd_eps_rating").get("value", "NEEDS_RESEARCH"),
                    "ibd_rs_rating": self.ibd.get_ibd_metric(symbol, "ibd_rs_rating").get("value", "NEEDS_RESEARCH"),
                    "ibd_smr_rating": self.ibd.get_ibd_metric(symbol, "ibd_smr_rating").get("value", "NEEDS_RESEARCH"),
                }

                # Data quality gate based on populated signals.
                gate_metrics = list(sec_metrics.values()) + [pe, pb, ps, pfcf]
                populated = sum(1 for v in gate_metrics if v not in ("NEEDS_RESEARCH", None, "") and self._to_float(v, None) is not None)
                total = len(gate_metrics)
                data_quality = round((populated / total) * 100 if total else 0.0, 1)

                # Scoring components (aligned with calibrated core ranking philosophy)
                quality = statistics.mean([
                    self._normalize(self._to_float(sec_metrics.get("roic")), 0, 25),
                    self._normalize(self._to_float(sec_metrics.get("roe")), 0, 30),
                    self._normalize(self._to_float(sec_metrics.get("net_margin")), 0, 30),
                ])

                valuation_parts = []
                if pe > 0:
                    valuation_parts.append(self._normalize(35 - pe, 0, 35))
                if pb > 0:
                    valuation_parts.append(self._normalize(8 - pb, 0, 8))
                if ps > 0:
                    valuation_parts.append(self._normalize(10 - ps, 0, 10))
                if pfcf > 0:
                    valuation_parts.append(self._normalize(45 - pfcf, 0, 45))
                valuation = statistics.mean(valuation_parts) if valuation_parts else 0.0

                growth = statistics.mean([
                    self._normalize(self._to_float(sec_metrics.get("revenue_growth_1yr")), -20, 50),
                    self._normalize(self._to_float(sec_metrics.get("revenue_growth_3yr")), -20, 40),
                    self._normalize(self._to_float(sec_metrics.get("eps_growth_1yr")), -30, 70),
                    self._normalize(self._to_float(sec_metrics.get("eps_growth_3yr")), -20, 50),
                ])

                ibd_score = statistics.mean([
                    self._to_float(ibd_metrics.get("ibd_composite")),
                    self._to_float(ibd_metrics.get("ibd_eps_rating")),
                    self._to_float(ibd_metrics.get("ibd_rs_rating")),
                    self._letter_to_score(ibd_metrics.get("ibd_smr_rating")),
                ])

                analyst_row = self.analyst_map.get(symbol, {})
                earnings_call_row = self.earnings_call_map.get(symbol, {})
                insider_row = self.insider_map.get(symbol, {})
                earnings_quality_row = self.earnings_quality_map.get(symbol, {})
                capital_allocation_row = self.capital_allocation_map.get(symbol, {})

                analyst_component = self._to_float(analyst_row.get("analyst_alpha_score"), 0.0)
                earnings_call_component = self._to_float(earnings_call_row.get("earnings_call_intelligence_score"), 0.0)
                insider_component = self._to_float(insider_row.get("insider_intelligence_score"), 0.0)
                earnings_quality_component = self._to_float(earnings_quality_row.get("earnings_quality_score"), 0.0)
                capital_allocation_component = self._to_float(capital_allocation_row.get("capital_allocation_intelligence_score"), 0.0)

                intelligence_components = [
                    analyst_component,
                    earnings_call_component,
                    insider_component,
                    earnings_quality_component,
                    capital_allocation_component,
                ]
                populated_intelligence = [component for component in intelligence_components if component > 0]
                intelligence_breadth = (
                    round((len(populated_intelligence) / len(intelligence_components)) * 100.0, 2)
                    if intelligence_components
                    else 0.0
                )

                liq = self._normalize(math.log10(item.get("avg_dollar_volume", 0) + 1), 6, 10)
                dq = data_quality

                score = (
                    quality * 0.17
                    + valuation * 0.15
                    + growth * 0.15
                    + ibd_score * 0.10
                    + analyst_component * 0.05
                    + earnings_call_component * 0.06
                    + insider_component * 0.07
                    + earnings_quality_component * 0.09
                    + capital_allocation_component * 0.08
                    + liq * 0.05
                    + intelligence_breadth * 0.03
                    + dq * 0.04
                )

                eligible = data_quality >= MIN_DATA_QUALITY and item.get("avg_dollar_volume", 0) >= MIN_DOLLAR_VOLUME

                scored = {
                    "symbol": symbol,
                    "company_name": item.get("company_name", ""),
                    "exchange": item.get("exchange", ""),
                    "sector": item.get("sector", ""),
                    "industry": item.get("industry", ""),
                    "market_cap": round(self._to_float(item.get("market_cap")), 2),
                    "avg_dollar_volume": round(self._to_float(item.get("avg_dollar_volume")), 2),
                    "data_quality": data_quality,
                    "eligible": bool(eligible),
                    "blocked_reason": "" if eligible else "insufficient_data_or_liquidity",
                    "component_quality": round(quality, 2),
                    "component_valuation": round(valuation, 2),
                    "component_growth": round(growth, 2),
                    "component_ibd": round(ibd_score, 2),
                    "component_analyst_intelligence": round(analyst_component, 2),
                    "component_earnings_call_intelligence": round(earnings_call_component, 2),
                    "component_insider_intelligence": round(insider_component, 2),
                    "component_earnings_quality": round(earnings_quality_component, 2),
                    "component_capital_allocation": round(capital_allocation_component, 2),
                    "component_intelligence_breadth": intelligence_breadth,
                    "component_liquidity": round(liq, 2),
                    "component_thesis": 0.0,
                    "component_data_quality": dq,
                    "composite_score": round(max(0.0, min(100.0, score)), 2),
                    "analyst_alpha_score": analyst_component,
                    "earnings_call_intelligence_score": earnings_call_component,
                    "insider_intelligence_score": insider_component,
                    "earnings_quality_score": earnings_quality_component,
                    "capital_allocation_intelligence_score": capital_allocation_component,
                    "pe_ratio": pe,
                    "price_to_book": pb,
                    "price_to_sales": ps,
                    "price_to_fcf": pfcf,
                    "revenue_growth_1yr": sec_metrics.get("revenue_growth_1yr"),
                    "revenue_growth_3yr": sec_metrics.get("revenue_growth_3yr"),
                    "eps_growth_1yr": sec_metrics.get("eps_growth_1yr"),
                    "eps_growth_3yr": sec_metrics.get("eps_growth_3yr"),
                    "roe": sec_metrics.get("roe"),
                    "roic": sec_metrics.get("roic"),
                    "net_margin": sec_metrics.get("net_margin"),
                    "debt_to_equity": sec_metrics.get("debt_to_equity"),
                    "current_ratio": sec_metrics.get("current_ratio"),
                    "ibd_composite": ibd_metrics.get("ibd_composite"),
                    "ibd_eps_rating": ibd_metrics.get("ibd_eps_rating"),
                    "ibd_rs_rating": ibd_metrics.get("ibd_rs_rating"),
                    "ibd_smr_rating": ibd_metrics.get("ibd_smr_rating"),
                    "is_current_holding": symbol in self.holdings,
                    "last_refresh": datetime.now().isoformat(),
                    "evidence_trail": (
                        f"score={round(score,2)} from q={round(quality,2)}, val={round(valuation,2)}, "
                        f"growth={round(growth,2)}, ibd={round(ibd_score,2)}, analyst={round(analyst_component,2)}, "
                        f"call={round(earnings_call_component,2)}, insider={round(insider_component,2)}, "
                        f"eq={round(earnings_quality_component,2)}, capalloc={round(capital_allocation_component,2)}, "
                        f"breadth={intelligence_breadth}, liq={round(liq,2)}, dq={dq}"
                    ),
                }

                self.checkpoint["deep_scored"][symbol] = scored

            self._save_checkpoint()

    def _build_ranked_frames(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        processed = self.checkpoint.get("processed", {})
        deep_scored = self.checkpoint.get("deep_scored", {})

        rows: List[Dict[str, Any]] = []
        for symbol, proc in processed.items():
            deep_row = deep_scored.get(symbol)
            if deep_row:
                row = dict(deep_row)
                row["score_basis"] = "deep"
                rows.append(row)
                continue

            # Coarse fallback ranking for symbols that failed first-pass and were not deep-scored.
            coarse_score = round(max(0.0, min(100.0, self._to_float(proc.get("first_pass_score"), 0.0) * 0.5)), 2)
            rows.append(
                {
                    "symbol": symbol,
                    "company_name": proc.get("company_name", ""),
                    "exchange": proc.get("exchange", ""),
                    "sector": proc.get("sector", ""),
                    "industry": proc.get("industry", ""),
                    "market_cap": round(self._to_float(proc.get("market_cap")), 2),
                    "avg_dollar_volume": round(self._to_float(proc.get("avg_dollar_volume")), 2),
                    "data_quality": 0.0,
                    "eligible": False,
                    "blocked_reason": proc.get("reason", "insufficient_data_or_liquidity"),
                    "component_quality": 0.0,
                    "component_valuation": 0.0,
                    "component_growth": 0.0,
                    "component_ibd": 0.0,
                    "component_analyst_intelligence": 0.0,
                    "component_earnings_call_intelligence": 0.0,
                    "component_insider_intelligence": 0.0,
                    "component_earnings_quality": 0.0,
                    "component_capital_allocation": 0.0,
                    "component_intelligence_breadth": 0.0,
                    "component_liquidity": 0.0,
                    "component_thesis": 0.0,
                    "component_data_quality": 0.0,
                    "composite_score": coarse_score,
                    "pe_ratio": 0.0,
                    "price_to_book": 0.0,
                    "price_to_sales": 0.0,
                    "price_to_fcf": 0.0,
                    "revenue_growth_1yr": "NEEDS_RESEARCH",
                    "revenue_growth_3yr": "NEEDS_RESEARCH",
                    "eps_growth_1yr": "NEEDS_RESEARCH",
                    "eps_growth_3yr": "NEEDS_RESEARCH",
                    "roe": "NEEDS_RESEARCH",
                    "roic": "NEEDS_RESEARCH",
                    "net_margin": "NEEDS_RESEARCH",
                    "debt_to_equity": "NEEDS_RESEARCH",
                    "current_ratio": "NEEDS_RESEARCH",
                    "ibd_composite": "NEEDS_RESEARCH",
                    "ibd_eps_rating": "NEEDS_RESEARCH",
                    "ibd_rs_rating": "NEEDS_RESEARCH",
                    "ibd_smr_rating": "NEEDS_RESEARCH",
                    "analyst_alpha_score": 0.0,
                    "earnings_call_intelligence_score": 0.0,
                    "insider_intelligence_score": 0.0,
                    "earnings_quality_score": 0.0,
                    "capital_allocation_intelligence_score": 0.0,
                    "is_current_holding": symbol in self.holdings,
                    "last_refresh": datetime.now().isoformat(),
                    "evidence_trail": f"coarse_rank_from_first_pass={coarse_score}",
                    "score_basis": "first_pass_fallback",
                }
            )

        eligible = [r for r in rows if r.get("eligible")]
        eligible.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
        for i, r in enumerate(eligible, 1):
            r["rank"] = i

        eligible_map = {r["symbol"]: r for r in eligible}
        for r in rows:
            r["rank"] = eligible_map[r["symbol"]]["rank"] if r["symbol"] in eligible_map else ""
            if eligible:
                if r["symbol"] in eligible_map:
                    r["percentile"] = round((1 - ((r["rank"] - 1) / max(1, len(eligible)))) * 100, 2)
                else:
                    r["percentile"] = 0.0
            else:
                r["percentile"] = 0.0

        # Rank all names, including ineligible/blocked names.
        all_sorted = sorted(rows, key=lambda x: (x.get("composite_score", 0.0), x.get("symbol", "")), reverse=True)
        for i, r in enumerate(all_sorted, 1):
            r["rank_all"] = i
            r["percentile_all"] = round((1 - ((i - 1) / max(1, len(all_sorted)))) * 100, 2)

        rows = sorted(all_sorted, key=lambda x: x.get("rank_all", 10**9))
        return rows, eligible

    def _write_csv(self, path: Path, rows: List[Dict[str, Any]]):
        if not rows:
            return
        fields = sorted({k for row in rows for k in row.keys()})
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _replacement_candidates(self, eligible: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        holdings_syms = set(self.holdings.keys())
        eligible_map = {r["symbol"]: r for r in eligible}

        holding_scored = [eligible_map[s] for s in holdings_syms if s in eligible_map and s not in EXCLUDED_REPLACEMENT]
        if not holding_scored:
            return []

        holding_scored.sort(key=lambda x: x.get("composite_score", 0.0))
        weakest = holding_scored[0]
        weakest_score = weakest.get("composite_score", 0.0)

        not_owned = [r for r in eligible if not r.get("is_current_holding")]
        not_owned.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

        out = []
        for cand in not_owned:
            improvement = cand.get("composite_score", 0.0) - weakest_score
            if improvement < MEANINGFUL_MARGIN:
                continue

            cand_liq = cand.get("avg_dollar_volume", 0.0)
            repl_liq = weakest.get("avg_dollar_volume", 0.0)
            liquidity_impact = round((cand_liq - repl_liq) / max(1.0, repl_liq) * 100, 2)

            # Margin impact proxy: same-dollar replacement expected neutral margin unless liquidity is much lower.
            margin_impact = "Neutral"
            if liquidity_impact < -30:
                margin_impact = "Negative"
            elif liquidity_impact > 30:
                margin_impact = "Positive"

            portfolio_fit = "Neutral"
            if cand.get("sector") and cand.get("sector") != weakest.get("sector"):
                portfolio_fit = "Diversifies sector exposure"

            out.append(
                {
                    "candidate_symbol": cand["symbol"],
                    "candidate_rank": cand.get("rank", ""),
                    "candidate_score": cand.get("composite_score", 0.0),
                    "replace_symbol": weakest["symbol"],
                    "replace_rank": weakest.get("rank", ""),
                    "replace_score": weakest_score,
                    "score_improvement": round(improvement, 2),
                    "expected_alpha_improvement": round(improvement / 100.0, 4),
                    "liquidity_impact_pct": liquidity_impact,
                    "margin_impact": margin_impact,
                    "portfolio_fit_impact": portfolio_fit,
                    "hurdle_margin": MEANINGFUL_MARGIN,
                    "evidence_trail": (
                        f"cand={cand['symbol']}({cand.get('composite_score')}), "
                        f"repl={weakest['symbol']}({weakest_score}), delta={round(improvement,2)}"
                    ),
                }
            )

            if len(out) >= 25:
                break

        return out

    def _write_report(self, all_rows: List[Dict[str, Any]], eligible: List[Dict[str, Any]], replacements: List[Dict[str, Any]]):
        holdings_syms = set(self.holdings.keys())
        eligible_map = {r["symbol"]: r for r in eligible}

        top20 = eligible[:20]
        top10_not_owned = [r for r in eligible if not r.get("is_current_holding")][:10]

        blocked = [r for r in all_rows if not r.get("eligible")]
        blocked.sort(key=lambda x: x.get("data_quality", 0.0))

        lines: List[str] = []
        lines.append("# Full Market Core Rankings")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("## Universe Coverage")
        lines.append(f"- Total universe size: {len(self.universe):,}")
        lines.append(f"- First-pass processed: {len(self.checkpoint.get('processed', {})):,}")
        lines.append(f"- Deep scored: {len(self.checkpoint.get('deep_scored', {})):,}")
        lines.append(f"- Successfully ranked (eligible): {len(eligible):,} ({(len(eligible)/max(1,len(self.universe))*100):.2f}%)")
        lines.append("")

        lines.append("## Top 20 U.S. Stocks Overall")
        for row in top20:
            lines.append(
                f"- #{row.get('rank')} {row['symbol']} ({row.get('exchange','')}): score {row.get('composite_score')}, "
                f"DQ {row.get('data_quality')}%, sector {row.get('sector','N/A')}, evidence: {row.get('evidence_trail','')}"
            )
        lines.append("")

        lines.append("## Current Holdings: Rank and Percentile")
        for sym in sorted(holdings_syms):
            if sym in eligible_map:
                r = eligible_map[sym]
                lines.append(
                    f"- {sym}: rank #{r.get('rank')} / {len(eligible)} ({r.get('percentile')}th pct), score {r.get('composite_score')}, DQ {r.get('data_quality')}%"
                )
            else:
                deep = self.checkpoint.get("deep_scored", {}).get(sym)
                if deep:
                    lines.append(
                        f"- {sym}: BLOCKED ({deep.get('blocked_reason')}), DQ {deep.get('data_quality')}%, score {deep.get('composite_score')}"
                    )
                else:
                    lines.append(f"- {sym}: NOT SCORED")
        lines.append("")

        lines.append("## Top 10 Stocks Not Currently Owned")
        for row in top10_not_owned:
            lines.append(
                f"- #{row.get('rank')} {row['symbol']}: score {row.get('composite_score')}, DQ {row.get('data_quality')}%, "
                f"liq ${row.get('avg_dollar_volume'):,.0f}/day"
            )
        lines.append("")

        lines.append("## Replacement Analysis")
        lines.append("- SPCX is excluded from replacement analysis.")
        if replacements:
            for r in replacements:
                lines.append(
                    f"- {r['candidate_symbol']} -> replace {r['replace_symbol']}: "
                    f"score +{r['score_improvement']}, expected alpha +{r['expected_alpha_improvement']}, "
                    f"liquidity impact {r['liquidity_impact_pct']}%, margin impact {r['margin_impact']}, "
                    f"portfolio-fit: {r['portfolio_fit_impact']}"
                )
        else:
            lines.append("- No candidates cleared the meaningful-margin replacement hurdle.")
        lines.append("")

        lines.append("## Candidates Blocked by Insufficient Data")
        for row in blocked[:30]:
            lines.append(
                f"- {row['symbol']}: reason={row.get('blocked_reason')}, DQ {row.get('data_quality')}%, "
                f"liq ${row.get('avg_dollar_volume',0):,.0f}/day"
            )
        lines.append("")

        lines.append("## Manual Validation of Top Ranked Names")
        for row in top20[:10]:
            lines.append(
                f"- {row['symbol']}: rev1y={row.get('revenue_growth_1yr')}, eps1y={row.get('eps_growth_1yr')}, "
                f"roe={row.get('roe')}, pe={row.get('pe_ratio')}, ibd={row.get('ibd_composite')}, evidence={row.get('evidence_trail')}"
            )

        with open(REPORT_MD, "w") as f:
            f.write("\n".join(lines) + "\n")

    def run(self):
        self.first_pass_screen()
        self.deep_score()

        all_rows, eligible = self._build_ranked_frames()
        top100 = eligible[:100]
        replacements = self._replacement_candidates(eligible)

        self._write_csv(FULL_RANKINGS_CSV, all_rows)
        self._write_csv(TOP100_CSV, top100)
        self._write_csv(REPLACEMENTS_CSV, replacements)
        self._write_report(all_rows, eligible, replacements)

        print(f"✓ Universe size: {len(self.universe):,}")
        print(f"✓ First-pass processed total: {len(self.checkpoint.get('processed', {})):,}")
        print(f"✓ Ranked eligible: {len(eligible):,}")
        print(f"✓ Full rankings: {FULL_RANKINGS_CSV}")
        print(f"✓ Top 100: {TOP100_CSV}")
        print(f"✓ Replacement candidates: {REPLACEMENTS_CSV}")
        print(f"✓ Report: {REPORT_MD}")


def main():
    # Ensure universe is fresh before ranking.
    UniverseBuilder().build()
    ranker = FullMarketRanker()
    ranker.run()


if __name__ == "__main__":
    main()
