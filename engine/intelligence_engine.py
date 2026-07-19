#!/usr/bin/env python3
"""
McLeod Intelligence Engine v1.0
Comprehensive intelligence gathering with modular data sources.
Combines SEC filings, market data, IBD ratings, and portfolio metrics.
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import statistics
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import data sources
from engine.data_sources.sec_source import SECDataSource
from engine.data_sources.market_source import MarketDataSource
from engine.data_sources.ibd_source import IBDDataSource
from engine.data_sources.finviz_source import FinvizDataSource
from engine.data_sources.manual_source import ManualResearchSource
from engine.data_sources.future_api_source import FutureAPIDataSource
from engine.analyst_intelligence import run_analyst_intelligence
from engine.earnings_call_intelligence import run_earnings_call_intelligence
from engine.insider_intelligence import run_insider_intelligence
from engine.earnings_quality import run_earnings_quality
from engine.capital_allocation import run_capital_allocation

# Configuration
WORKSPACE = Path(__file__).parent.parent
CONFIG_DIR = WORKSPACE / "config"
DATA_DIR = WORKSPACE / "data"

METRICS_CONFIG = CONFIG_DIR / "intelligence_metrics.json"
POSITIONS_CSV = DATA_DIR / "schwab_positions_latest.csv"
IBD_CSV = DATA_DIR / "ibd_rankings_manual.csv"
MANUAL_RESEARCH_CSV = DATA_DIR / "manual_research.csv"

OUTPUT_JSON = DATA_DIR / "mcleod_intelligence_latest.json"
OUTPUT_CSV = DATA_DIR / "mcleod_intelligence_latest.csv"
ANALYST_CSV = DATA_DIR / "analyst_estimates_latest.csv"
EARNINGS_CALL_CSV = DATA_DIR / "earnings_call_intelligence_latest.csv"
INSIDER_CSV = DATA_DIR / "insider_transactions_latest.csv"
EARNINGS_QUALITY_CSV = DATA_DIR / "earnings_quality_latest.csv"
CAPITAL_ALLOCATION_CSV = DATA_DIR / "capital_allocation_latest.csv"

# Constants
RESEARCH_NEEDED_PLACEHOLDER = "NEEDS_RESEARCH"
MIN_DATA_QUALITY_FOR_RANKING = 70


class IntelligenceEngine:
    """Main intelligence gathering engine."""
    
    def __init__(self):
        """Initialize intelligence engine with all data sources."""
        self.config = None
        self.positions = []
        self.equities = []
        
        # Data sources
        self.sec_source = None
        self.market_source = None
        self.ibd_source = None
        self.finviz_source = None
        self.manual_source = None
        self.future_api_source = None
        self.analyst_snapshot = {}
        self.earnings_call_snapshot = {}
        self.insider_snapshot = {}
        self.earnings_quality_snapshot = {}
        self.capital_allocation_snapshot = {}
        
        self.intelligence_data = {}
        self.holdings_blocked = []
        self.historical_cache = {}
        
        self.load_config()
        self.load_data_sources()
        self.load_positions()
        self.load_historical_cache()
        self.load_analyst_snapshot()
        self.load_earnings_call_snapshot()
        self.load_insider_snapshot()
        self.load_earnings_quality_snapshot()
        self.load_capital_allocation_snapshot()

    def load_historical_cache(self):
        """Load last-known non-placeholder metric values for historical fallback."""
        cache = {}
        for path in [DATA_DIR / "mcleod_intelligence_latest.json", DATA_DIR / "mcleod_research_latest.json"]:
            if not path.exists():
                continue
            try:
                with open(path) as f:
                    payload = json.load(f)
                for holding in payload.get("holdings", []):
                    symbol = holding.get("symbol")
                    if not symbol:
                        continue
                    sym_cache = cache.setdefault(symbol, {})
                    for key, value in holding.items():
                        if key.endswith("_source") or key.endswith("_timestamp") or key.endswith("_confidence") or key.endswith("_stale"):
                            continue
                        if value in (None, "", RESEARCH_NEEDED_PLACEHOLDER):
                            continue
                        sym_cache[key] = {
                            "value": value,
                            "timestamp": holding.get(f"{key}_timestamp") or datetime.now().isoformat(),
                            "source": holding.get(f"{key}_source") or "Historical Cache",
                            "confidence": holding.get(f"{key}_confidence", 40),
                            "stale": True,
                        }
            except Exception:
                continue
        self.historical_cache = cache
    
    def load_config(self):
        """Load metrics configuration."""
        try:
            with open(METRICS_CONFIG) as f:
                self.config = json.load(f)
            print(f"✓ Loaded metrics config: {len(self.config['metrics'])} metrics")
        except Exception as e:
            raise SystemExit(f"ERROR loading config: {e}")
    
    def load_data_sources(self):
        """Initialize all data sources."""
        try:
            self.sec_source = SECDataSource()
            self.market_source = MarketDataSource()
            self.ibd_source = IBDDataSource(IBD_CSV)
            self.finviz_source = FinvizDataSource()
            self.manual_source = ManualResearchSource(MANUAL_RESEARCH_CSV if MANUAL_RESEARCH_CSV.exists() else None)
            self.future_api_source = FutureAPIDataSource()
            print(f"✓ Initialized data sources: SEC, Market, IBD, Finviz, Manual, Future APIs, Analyst Intelligence")
        except Exception as e:
            raise SystemExit(f"ERROR loading data sources: {e}")

    def load_analyst_snapshot(self):
        """Load analyst intelligence output and index by symbol."""
        if not ANALYST_CSV.exists():
            try:
                run_analyst_intelligence()
            except Exception:
                self.analyst_snapshot = {}
                return

        snapshot = {}
        if ANALYST_CSV.exists():
            try:
                with open(ANALYST_CSV, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        symbol = str(row.get("symbol", "")).upper().strip()
                        if symbol:
                            snapshot[symbol] = row
            except Exception:
                snapshot = {}
        self.analyst_snapshot = snapshot

    def load_earnings_call_snapshot(self):
        """Load earnings call intelligence output and index by symbol."""
        if not EARNINGS_CALL_CSV.exists():
            try:
                run_earnings_call_intelligence()
            except Exception:
                self.earnings_call_snapshot = {}
                return

        snapshot = {}
        if EARNINGS_CALL_CSV.exists():
            try:
                with open(EARNINGS_CALL_CSV, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        symbol = str(row.get("symbol", "")).upper().strip()
                        if symbol:
                            snapshot[symbol] = row
            except Exception:
                snapshot = {}
        self.earnings_call_snapshot = snapshot

    def load_insider_snapshot(self):
        """Load insider intelligence output and index by symbol."""
        if not INSIDER_CSV.exists():
            try:
                run_insider_intelligence()
            except Exception:
                self.insider_snapshot = {}
                return

        snapshot = {}
        if INSIDER_CSV.exists():
            try:
                with open(INSIDER_CSV, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        symbol = str(row.get("symbol", "")).upper().strip()
                        if symbol:
                            snapshot[symbol] = row
            except Exception:
                snapshot = {}
        self.insider_snapshot = snapshot

    def load_earnings_quality_snapshot(self):
        """Load earnings quality output and index by symbol."""
        if not EARNINGS_QUALITY_CSV.exists():
            try:
                run_earnings_quality()
            except Exception:
                self.earnings_quality_snapshot = {}
                return

        snapshot = {}
        if EARNINGS_QUALITY_CSV.exists():
            try:
                with open(EARNINGS_QUALITY_CSV, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        symbol = str(row.get("symbol", "")).upper().strip()
                        if symbol:
                            snapshot[symbol] = row
            except Exception:
                snapshot = {}
        self.earnings_quality_snapshot = snapshot

    def load_capital_allocation_snapshot(self):
        """Load capital allocation output and index by symbol."""
        if not CAPITAL_ALLOCATION_CSV.exists():
            try:
                run_capital_allocation()
            except Exception:
                self.capital_allocation_snapshot = {}
                return

        snapshot = {}
        if CAPITAL_ALLOCATION_CSV.exists():
            try:
                with open(CAPITAL_ALLOCATION_CSV, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        symbol = str(row.get("symbol", "")).upper().strip()
                        if symbol:
                            snapshot[symbol] = row
            except Exception:
                snapshot = {}
        self.capital_allocation_snapshot = snapshot
    
    def load_positions(self):
        """Load positions from portfolio."""
        try:
            with open(POSITIONS_CSV) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.positions.append(row)
            
            # Separate equities from options
            self.equities = [p for p in self.positions if p.get('asset_type', '').upper() == 'EQUITY']
            
            print(f"✓ Loaded {len(self.equities)} equities from portfolio")
        except Exception as e:
            raise SystemExit(f"ERROR loading positions: {e}")
    
    def gather_intelligence(self, symbol: str, position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gather intelligence on a holding.
        
        Returns dict with all metrics, sources, timestamps, and confidence.
        """
        intelligence = {
            'symbol': symbol,
            'asset_type': position.get('asset_type', 'EQUITY'),
            'market_value': float(position.get('market_value', 0)),
            'weight_pct': float(position.get('portfolio_weight_percent', 0)),
            'intelligence_timestamp': datetime.now().isoformat(),
            'current_price': float(position.get('current_price', 0)),
            'quantity': float(position.get('quantity', 0)),
        }
        
        # Populate each metric from the best available source.
        for metric_name in self.config['metrics'].keys():
            metric_data = self.resolve_metric(symbol, metric_name, position, intelligence)
            intelligence[metric_name] = metric_data.get('value', RESEARCH_NEEDED_PLACEHOLDER)
            intelligence[f"{metric_name}_source"] = metric_data.get('source', 'unknown')
            intelligence[f"{metric_name}_timestamp"] = metric_data.get('timestamp', datetime.now().isoformat())
            intelligence[f"{metric_name}_confidence"] = metric_data.get('confidence', 0)
            intelligence[f"{metric_name}_stale"] = metric_data.get('stale', False)
        
        # Calculate data quality
        intelligence['data_quality_score'] = self.calculate_data_quality(intelligence, symbol)
        intelligence['data_quality_score_source'] = 'intelligence_engine'
        intelligence['data_quality_score_timestamp'] = datetime.now().isoformat()
        intelligence['data_quality_score_confidence'] = 100
        intelligence['data_quality_score_stale'] = False
        intelligence['analyst_data_quality_score'] = self.calculate_analyst_data_quality(intelligence)
        intelligence['analyst_data_quality_score_source'] = 'intelligence_engine'
        intelligence['analyst_data_quality_score_timestamp'] = datetime.now().isoformat()
        intelligence['analyst_data_quality_score_confidence'] = 100
        intelligence['analyst_data_quality_score_stale'] = False
        intelligence['earnings_call_data_quality_score'] = self.calculate_earnings_call_data_quality(intelligence)
        intelligence['earnings_call_data_quality_score_source'] = 'intelligence_engine'
        intelligence['earnings_call_data_quality_score_timestamp'] = datetime.now().isoformat()
        intelligence['earnings_call_data_quality_score_confidence'] = 100
        intelligence['earnings_call_data_quality_score_stale'] = False
        intelligence['insider_data_quality_score'] = self.calculate_insider_data_quality(intelligence)
        intelligence['insider_data_quality_score_source'] = 'intelligence_engine'
        intelligence['insider_data_quality_score_timestamp'] = datetime.now().isoformat()
        intelligence['insider_data_quality_score_confidence'] = 100
        intelligence['insider_data_quality_score_stale'] = False
        intelligence['earnings_quality_data_quality_score'] = self.calculate_earnings_quality_data_quality(intelligence)
        intelligence['earnings_quality_data_quality_score_source'] = 'intelligence_engine'
        intelligence['earnings_quality_data_quality_score_timestamp'] = datetime.now().isoformat()
        intelligence['earnings_quality_data_quality_score_confidence'] = 100
        intelligence['earnings_quality_data_quality_score_stale'] = False
        intelligence['capital_allocation_data_quality_score'] = self.calculate_capital_allocation_data_quality(intelligence)
        intelligence['capital_allocation_data_quality_score_source'] = 'intelligence_engine'
        intelligence['capital_allocation_data_quality_score_timestamp'] = datetime.now().isoformat()
        intelligence['capital_allocation_data_quality_score_confidence'] = 100
        intelligence['capital_allocation_data_quality_score_stale'] = False
        intelligence['eligible_for_core_rankings'] = intelligence['data_quality_score'] >= MIN_DATA_QUALITY_FOR_RANKING
        
        return intelligence
    
    def _portfolio_metric_result(
        self,
        symbol: str,
        metric_name: str,
        position: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Return direct portfolio metric payloads when applicable."""
        if metric_name == 'liquidity_score':
            return {
                "value": float(position.get('liquidity_score', 50)),
                "source": "schwab_portfolio",
                "timestamp": datetime.now().isoformat(),
                "confidence": 95,
                "stale": False,
            }

        if metric_name == 'margin_requirement':
            market_val = float(position.get('market_value', 0))
            return {
                "value": market_val * 0.50,
                "source": "portfolio_engine",
                "timestamp": datetime.now().isoformat(),
                "confidence": 95,
                "stale": False,
            }

        if metric_name == 'thesis_health':
            signal = str((self.earnings_call_snapshot.get(symbol, {}) or {}).get("earnings_call_thesis_signal", "")).lower()
            insider_signal = str((self.insider_snapshot.get(symbol, {}) or {}).get("insider_thesis_signal", "")).lower()
            insider_impact = self._to_float((self.insider_snapshot.get(symbol, {}) or {}).get("insider_thesis_impact_score"))
            insider_sales_flag = str((self.insider_snapshot.get(symbol, {}) or {}).get("insider_repeated_large_sales_flag", "0"))
            eq_signal = str((self.earnings_quality_snapshot.get(symbol, {}) or {}).get("earnings_quality_thesis_signal", "")).lower()
            eq_impact = self._to_float((self.earnings_quality_snapshot.get(symbol, {}) or {}).get("earnings_quality_thesis_impact_score"))
            cap_alloc = self._to_float((self.capital_allocation_snapshot.get(symbol, {}) or {}).get("capital_allocation_intelligence_score"))
            thesis_value = "HEALTHY"
            confidence = 50
            if "potential thesis break" in signal:
                thesis_value = "BROKEN"
                confidence = 72
            elif "potential thesis break" in eq_signal:
                thesis_value = "BROKEN"
                confidence = 74
            elif "weakening" in signal:
                thesis_value = "AT_RISK"
                confidence = 68
            elif "weakening" in eq_signal:
                thesis_value = "AT_RISK"
                confidence = 70
            elif "weakening" in insider_signal or insider_sales_flag == "1":
                thesis_value = "AT_RISK"
                confidence = 66
            elif "stable" in signal:
                thesis_value = "HEALTHY"
                confidence = 62
            elif "strengthening" in signal:
                thesis_value = "HEALTHY"
                confidence = 70
            elif eq_impact is not None and eq_impact >= 72:
                thesis_value = "HEALTHY"
                confidence = 72
            elif cap_alloc is not None and cap_alloc < 35:
                thesis_value = "AT_RISK"
                confidence = 68
            elif cap_alloc is not None and cap_alloc >= 70:
                thesis_value = "HEALTHY"
                confidence = 70
            elif insider_impact is not None and insider_impact >= 70:
                thesis_value = "HEALTHY"
                confidence = 70

            return {
                "value": thesis_value,
                "source": "Earnings Call Intelligence",
                "timestamp": datetime.now().isoformat(),
                "confidence": confidence,
                "stale": False,
            }

        return None

    def _historical_result(self, symbol: str, metric_name: str) -> Optional[Dict[str, Any]]:
        """Return last known value for metric when live sources are unavailable."""
        symbol_cache = self.historical_cache.get(symbol, {})
        if metric_name not in symbol_cache:
            return None

        hist = symbol_cache[metric_name]
        return {
            "value": hist.get("value"),
            "source": f"{hist.get('source', 'Historical Cache')} (historical)",
            "timestamp": datetime.now().isoformat(),
            "confidence": min(60, max(30, int(hist.get("confidence", 40)))),
            "stale": True,
        }

    def _analyst_result(self, symbol: str, metric_name: str) -> Optional[Dict[str, Any]]:
        """Return analyst-intelligence metric payload for symbol when available."""
        row = self.analyst_snapshot.get(symbol)
        if not row:
            return None

        value = row.get(metric_name, RESEARCH_NEEDED_PLACEHOLDER)
        if value in (None, "", RESEARCH_NEEDED_PLACEHOLDER):
            return None

        return {
            "value": value,
            "source": row.get(f"{metric_name}_source", "Analyst Intelligence"),
            "timestamp": row.get(f"{metric_name}_timestamp", datetime.now().isoformat()),
            "confidence": int(float(row.get(f"{metric_name}_confidence", 0) or 0)),
            "stale": str(row.get(f"{metric_name}_stale", "False")).lower() in {"1", "true", "yes"},
        }

    def _earnings_call_result(self, symbol: str, metric_name: str) -> Optional[Dict[str, Any]]:
        """Return earnings-call intelligence metric payload for symbol when available."""
        row = self.earnings_call_snapshot.get(symbol)
        if not row:
            return None

        value = row.get(metric_name, RESEARCH_NEEDED_PLACEHOLDER)
        if value in (None, "", RESEARCH_NEEDED_PLACEHOLDER):
            return None

        return {
            "value": value,
            "source": row.get(f"{metric_name}_source", "Earnings Call Intelligence"),
            "timestamp": row.get(f"{metric_name}_timestamp", datetime.now().isoformat()),
            "confidence": int(float(row.get(f"{metric_name}_confidence", 0) or 0)),
            "stale": str(row.get(f"{metric_name}_stale", "False")).lower() in {"1", "true", "yes"},
        }

    def _insider_result(self, symbol: str, metric_name: str) -> Optional[Dict[str, Any]]:
        """Return insider intelligence metric payload for symbol when available."""
        row = self.insider_snapshot.get(symbol)
        if not row:
            return None

        value = row.get(metric_name, RESEARCH_NEEDED_PLACEHOLDER)
        if value in (None, "", RESEARCH_NEEDED_PLACEHOLDER):
            return None

        return {
            "value": value,
            "source": row.get(f"{metric_name}_source", "Insider Intelligence"),
            "timestamp": row.get(f"{metric_name}_timestamp", datetime.now().isoformat()),
            "confidence": int(float(row.get(f"{metric_name}_confidence", 0) or 0)),
            "stale": str(row.get(f"{metric_name}_stale", "False")).lower() in {"1", "true", "yes"},
        }

    def _earnings_quality_result(self, symbol: str, metric_name: str) -> Optional[Dict[str, Any]]:
        """Return earnings-quality metric payload for symbol when available."""
        row = self.earnings_quality_snapshot.get(symbol)
        if not row:
            return None

        value = row.get(metric_name, RESEARCH_NEEDED_PLACEHOLDER)
        if value in (None, "", RESEARCH_NEEDED_PLACEHOLDER):
            return None

        return {
            "value": value,
            "source": row.get(f"{metric_name}_source", "Earnings Quality"),
            "timestamp": row.get(f"{metric_name}_timestamp", datetime.now().isoformat()),
            "confidence": int(float(row.get(f"{metric_name}_confidence", 0) or 0)),
            "stale": str(row.get(f"{metric_name}_stale", "False")).lower() in {"1", "true", "yes"},
        }

    def _capital_allocation_result(self, symbol: str, metric_name: str) -> Optional[Dict[str, Any]]:
        """Return capital-allocation metric payload for symbol when available."""
        row = self.capital_allocation_snapshot.get(symbol)
        if not row:
            return None

        value = row.get(metric_name, RESEARCH_NEEDED_PLACEHOLDER)
        if value in (None, "", RESEARCH_NEEDED_PLACEHOLDER):
            return None

        return {
            "value": value,
            "source": row.get(f"{metric_name}_source", "Capital Allocation Intelligence"),
            "timestamp": row.get(f"{metric_name}_timestamp", datetime.now().isoformat()),
            "confidence": int(float(row.get(f"{metric_name}_confidence", 0) or 0)),
            "stale": str(row.get(f"{metric_name}_stale", "False")).lower() in {"1", "true", "yes"},
        }

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value in (None, "", RESEARCH_NEEDED_PLACEHOLDER):
                return None
            return float(value)
        except (ValueError, TypeError):
            return None

    def _calculated_metric_result(
        self,
        metric_name: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Compute derived quality/framework metrics when direct source data is unavailable."""
        roe = self._to_float(context.get("roe"))
        roic = self._to_float(context.get("roic"))
        net_margin = self._to_float(context.get("net_margin"))
        gross_margin = self._to_float(context.get("gross_margin"))
        op_margin = self._to_float(context.get("operating_margin"))
        debt_to_equity = self._to_float(context.get("debt_to_equity"))
        current_ratio = self._to_float(context.get("current_ratio"))
        pe_ratio = self._to_float(context.get("pe_ratio"))
        pb_ratio = self._to_float(context.get("price_to_book"))
        ps_ratio = self._to_float(context.get("price_to_sales"))
        pfcf_ratio = self._to_float(context.get("price_to_fcf"))
        rev_growth = self._to_float(context.get("revenue_growth_1yr"))
        eq_score = self._to_float(context.get("earnings_quality_score"))
        eq_cash = self._to_float(context.get("earnings_quality_cash_conversion_score"))
        eq_accrual = self._to_float(context.get("earnings_quality_accrual_quality_score"))
        cap_alloc = self._to_float(context.get("capital_allocation_intelligence_score"))

        def clamp(v: float) -> float:
            return max(0.0, min(100.0, v))

        score_value = None

        if metric_name == "business_quality":
            parts = []
            if gross_margin is not None:
                parts.append(clamp(gross_margin * 1.2))
            if op_margin is not None:
                parts.append(clamp((op_margin + 10) * 2.5))
            if roe is not None:
                parts.append(clamp(roe * 3.0))
            if rev_growth is not None:
                parts.append(clamp((rev_growth + 20) * 1.7))
            if eq_score is not None:
                parts.append(clamp(eq_score))
            if cap_alloc is not None:
                parts.append(clamp(cap_alloc))
            if parts:
                score_value = round(sum(parts) / len(parts), 2)

        elif metric_name == "expected_alpha":
            parts = []
            if rev_growth is not None:
                parts.append(clamp((rev_growth + 20) * 1.8))
            if roic is not None:
                parts.append(clamp(roic * 3.5))
            if eq_score is not None:
                parts.append(clamp(eq_score))
            if eq_cash is not None:
                parts.append(clamp(eq_cash))
            if eq_accrual is not None:
                parts.append(clamp(eq_accrual))
            if parts:
                score_value = round(sum(parts) / len(parts), 2)

        elif metric_name == "valuation_score":
            parts = []
            if pe_ratio is not None and pe_ratio > 0:
                parts.append(clamp(120 - pe_ratio * 2.2))
            if pb_ratio is not None and pb_ratio > 0:
                parts.append(clamp(120 - pb_ratio * 14))
            if ps_ratio is not None and ps_ratio > 0:
                parts.append(clamp(120 - ps_ratio * 11))
            if pfcf_ratio is not None and pfcf_ratio > 0:
                parts.append(clamp(120 - pfcf_ratio * 2.6))
            if parts:
                score_value = round(sum(parts) / len(parts), 2)

        elif metric_name == "buffett_score":
            parts = []
            if roe is not None:
                parts.append(clamp(roe * 3.5))
            if debt_to_equity is not None:
                parts.append(clamp(100 - debt_to_equity * 22))
            if net_margin is not None:
                parts.append(clamp((net_margin + 5) * 3.3))
            if current_ratio is not None:
                parts.append(clamp(current_ratio * 25))
            if parts:
                score_value = round(sum(parts) / len(parts), 2)

        elif metric_name == "greenblatt_score":
            parts = []
            if roic is not None:
                parts.append(clamp(roic * 4.0))
            if pe_ratio is not None and pe_ratio > 0:
                earnings_yield = 100 / pe_ratio
                parts.append(clamp(earnings_yield * 5.0))
            if parts:
                score_value = round(sum(parts) / len(parts), 2)

        elif metric_name == "graham_templeton_score":
            parts = []
            if debt_to_equity is not None:
                parts.append(clamp(100 - debt_to_equity * 20))
            if current_ratio is not None:
                parts.append(clamp(current_ratio * 30))
            if pe_ratio is not None and pe_ratio > 0:
                parts.append(clamp(100 - pe_ratio * 2.0))
            if parts:
                score_value = round(sum(parts) / len(parts), 2)

        if score_value is None:
            return None

        return {
            "value": score_value,
            "source": "Calculated",
            "timestamp": datetime.now().isoformat(),
            "confidence": 65,
            "stale": False,
        }

    def _candidate_results(
        self,
        symbol: str,
        metric_name: str,
        position: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Collect candidate metric payloads honoring source priority order."""
        candidates = []

        # 1) SEC EDGAR fundamentals
        if self.sec_source:
            sec_result = self.sec_source.get_financial_metric(symbol, metric_name, position)
            if sec_result and sec_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(sec_result)

        # 2) IBD ratings
        if self.ibd_source and metric_name.startswith('ibd_'):
            ibd_result = self.ibd_source.get_ibd_metric(symbol, metric_name)
            if ibd_result and ibd_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(ibd_result)

        # 3) Finviz fundamentals
        if self.finviz_source:
            finviz_result = self.finviz_source.get_metric(symbol, metric_name)
            if finviz_result and finviz_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(finviz_result)

        # Market source still participates for market-data metrics as a lower-priority fallback.
        if self.market_source:
            market_result = self.market_source.get_market_metric(symbol, metric_name, position)
            if market_result and market_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(market_result)

        if self.manual_source:
            manual_result = self.manual_source.get_metric(symbol, metric_name)
            if manual_result and manual_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(manual_result)

        if self.future_api_source:
            future_result = self.future_api_source.get_metric(symbol, metric_name)
            if future_result and future_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(future_result)

        if metric_name.startswith("analyst_"):
            analyst_result = self._analyst_result(symbol, metric_name)
            if analyst_result and analyst_result.get("value") != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(analyst_result)

        if metric_name.startswith("earnings_call_"):
            call_result = self._earnings_call_result(symbol, metric_name)
            if call_result and call_result.get("value") != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(call_result)

        if metric_name.startswith("insider_") or metric_name in {"primary_buyer_names", "primary_buyer_titles"}:
            insider_result = self._insider_result(symbol, metric_name)
            if insider_result and insider_result.get("value") != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(insider_result)

        if metric_name.startswith("earnings_quality_"):
            eq_result = self._earnings_quality_result(symbol, metric_name)
            if eq_result and eq_result.get("value") != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(eq_result)

        if metric_name.startswith("capital_allocation_"):
            ca_result = self._capital_allocation_result(symbol, metric_name)
            if ca_result and ca_result.get("value") != RESEARCH_NEEDED_PLACEHOLDER:
                candidates.append(ca_result)

        return candidates

    def resolve_metric(
        self,
        symbol: str,
        metric_name: str,
        position: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolve a metric using fallback chain across all configured sources."""
        portfolio_result = self._portfolio_metric_result(symbol, metric_name, position)
        if portfolio_result is not None:
            return portfolio_result

        candidates = self._candidate_results(symbol, metric_name, position)
        if candidates:
            best = max(candidates, key=lambda x: x.get('confidence', 0))
            if len(candidates) > 1:
                best = dict(best)
                best['merged_sources'] = len(candidates)
            return best

        # 4) Cached historical calculations
        historical = self._historical_result(symbol, metric_name)
        if historical:
            return historical

        # Derived calculations from currently available metrics.
        calculated = self._calculated_metric_result(metric_name, context or {})
        if calculated:
            return calculated

        # 5) Truly unavailable
        return {
            "value": RESEARCH_NEEDED_PLACEHOLDER,
            "source": "Multiple Sources",
            "timestamp": datetime.now().isoformat(),
            "confidence": 0,
            "stale": False,
            "reason": "No data from any source",
        }
    
    def calculate_data_quality(self, intelligence: Dict[str, Any], symbol: str) -> float:
        """Calculate data quality score (% of metrics populated)."""
        # Analyst and earnings-call fields are additive evidence and should not block core ranking eligibility.
        metric_names = [
            m
            for m in self.config['metrics'].keys()
            if not m.startswith("analyst_") and not m.startswith("earnings_call_") and not m.startswith("insider_") and not m.startswith("earnings_quality_") and not m.startswith("capital_allocation_") and m not in {"primary_buyer_names", "primary_buyer_titles"}
        ]
        populated = 0
        total = len(metric_names)
        
        for metric in metric_names:
            value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = intelligence.get(f"{metric}_confidence", 0)
            if value != RESEARCH_NEEDED_PLACEHOLDER and value != "NEEDS_RESEARCH" and float(confidence) > 0:
                populated += 1
        
        quality_score = (populated / total * 100) if total > 0 else 0
        return round(quality_score, 1)

    def calculate_analyst_data_quality(self, intelligence: Dict[str, Any]) -> float:
        """Calculate analyst-only data coverage for dashboarding."""
        metric_names = [m for m in self.config['metrics'].keys() if m.startswith("analyst_")]
        if not metric_names:
            return 0.0

        populated = 0
        for metric in metric_names:
            value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = intelligence.get(f"{metric}_confidence", 0)
            if value not in (RESEARCH_NEEDED_PLACEHOLDER, "NEEDS_RESEARCH", None, "") and float(confidence) > 0:
                populated += 1

        return round((populated / len(metric_names) * 100.0), 1)

    def calculate_earnings_call_data_quality(self, intelligence: Dict[str, Any]) -> float:
        """Calculate earnings-call-only data coverage for dashboarding."""
        metric_names = [m for m in self.config['metrics'].keys() if m.startswith("earnings_call_")]
        if not metric_names:
            return 0.0

        populated = 0
        for metric in metric_names:
            value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = intelligence.get(f"{metric}_confidence", 0)
            if value not in (RESEARCH_NEEDED_PLACEHOLDER, "NEEDS_RESEARCH", None, "") and float(confidence) > 0:
                populated += 1

        return round((populated / len(metric_names) * 100.0), 1)

    def calculate_insider_data_quality(self, intelligence: Dict[str, Any]) -> float:
        """Calculate insider-only data coverage for dashboarding."""
        metric_names = [
            m
            for m in self.config['metrics'].keys()
            if m.startswith("insider_") or m in {"primary_buyer_names", "primary_buyer_titles"}
        ]
        if not metric_names:
            return 0.0

        populated = 0
        for metric in metric_names:
            value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = intelligence.get(f"{metric}_confidence", 0)
            if value not in (RESEARCH_NEEDED_PLACEHOLDER, "NEEDS_RESEARCH", None, "") and float(confidence) > 0:
                populated += 1

        return round((populated / len(metric_names) * 100.0), 1)

    def calculate_earnings_quality_data_quality(self, intelligence: Dict[str, Any]) -> float:
        """Calculate earnings-quality-only data coverage for dashboarding."""
        metric_names = [m for m in self.config['metrics'].keys() if m.startswith("earnings_quality_")]
        if not metric_names:
            return 0.0

        populated = 0
        for metric in metric_names:
            value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = intelligence.get(f"{metric}_confidence", 0)
            if value not in (RESEARCH_NEEDED_PLACEHOLDER, "NEEDS_RESEARCH", None, "") and float(confidence) > 0:
                populated += 1

        return round((populated / len(metric_names) * 100.0), 1)

    def calculate_capital_allocation_data_quality(self, intelligence: Dict[str, Any]) -> float:
        """Calculate capital-allocation-only data coverage for dashboarding."""
        metric_names = [m for m in self.config['metrics'].keys() if m.startswith("capital_allocation_")]
        if not metric_names:
            return 0.0

        populated = 0
        for metric in metric_names:
            value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = intelligence.get(f"{metric}_confidence", 0)
            if value not in (RESEARCH_NEEDED_PLACEHOLDER, "NEEDS_RESEARCH", None, "") and float(confidence) > 0:
                populated += 1

        return round((populated / len(metric_names) * 100.0), 1)
    
    def count_populated_metrics(self, intelligence: Dict[str, Any]) -> int:
        """Count populated metrics per holding."""
        metric_names = [m for m in self.config['metrics'].keys()]
        count = 0
        for metric in metric_names:
            value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = intelligence.get(f"{metric}_confidence", 0)
            if value != RESEARCH_NEEDED_PLACEHOLDER and float(confidence) > 0:
                count += 1
        return count
    
    def analyze_all_holdings(self) -> List[Dict[str, Any]]:
        """Gather intelligence on all equities."""
        intelligence_results = []
        
        print(f"\n🧠 Gathering intelligence on {len(self.equities)} holdings...\n")
        
        for i, equity in enumerate(self.equities, 1):
            symbol = equity.get('symbol', '')
            intelligence = self.gather_intelligence(symbol, equity)
            intelligence_results.append(intelligence)
            
            # Progress indicator
            if i % 5 == 0 or i == len(self.equities):
                print(f"  ✓ {i}/{len(self.equities)} holdings analyzed")
        
        return intelligence_results
    
    def save_outputs(self, intelligence_results: List[Dict[str, Any]]):
        """Save intelligence outputs to JSON and CSV."""
        if not intelligence_results:
            print("No intelligence results to save")
            return
        
        # Save JSON
        try:
            output_json = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "version": "1.0.0",
                    "engine": "McLeod Intelligence Engine",
                    "total_holdings": len(intelligence_results),
                    "metrics_defined": len(self.config['metrics']),
                },
                "holdings": intelligence_results,
            }
            
            with open(OUTPUT_JSON, 'w') as f:
                json.dump(output_json, f, indent=2)
            print(f"✓ Intelligence saved to {OUTPUT_JSON}")
        except Exception as e:
            print(f"ERROR saving JSON: {e}")
        
        # Save CSV
        try:
            if intelligence_results:
                with open(OUTPUT_CSV, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=intelligence_results[0].keys())
                    writer.writeheader()
                    writer.writerows(intelligence_results)
                print(f"✓ Intelligence saved to {OUTPUT_CSV}")
        except Exception as e:
            print(f"ERROR saving CSV: {e}")
    
    def generate_summary(self, intelligence_results: List[Dict[str, Any]]):
        """Generate detailed intelligence summary."""
        print(f"\n" + "="*80)
        print(f"📊 INTELLIGENCE ENGINE SUMMARY")
        print(f"="*80 + "\n")
        
        metric_names = [m for m in self.config['metrics'].keys()]
        total_slots = len(intelligence_results) * len(metric_names)
        populated_slots = 0
        populated_by_metric = {m: 0 for m in metric_names}
        
        # Data quality distribution
        quality_scores = []
        
        for intelligence in intelligence_results:
            quality = intelligence.get('data_quality_score', 0)
            quality_scores.append(quality)
            
            for metric in metric_names:
                value = intelligence.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
                if value != RESEARCH_NEEDED_PLACEHOLDER:
                    populated_slots += 1
                    populated_by_metric[metric] += 1
        
        print(f"📈 HOLDINGS ANALYZED")
        print(f"  Total: {len(intelligence_results)}")
        print(f"  Equities: {len(intelligence_results)}")
        
        print(f"\n📋 METRICS POPULATED")
        print(f"  Total Metric Slots: {total_slots}")
        print(f"  Populated: {populated_slots} ({populated_slots/total_slots*100:.1f}%)")
        print(f"  NEEDS_RESEARCH: {total_slots - populated_slots}")
        
        print(f"\n📊 DATA QUALITY SCORE")
        if quality_scores:
            print(f"  Average: {statistics.mean(quality_scores):.1f}%")
            print(f"  Min: {min(quality_scores):.1f}%")
            print(f"  Max: {max(quality_scores):.1f}%")
            print(f"  Median: {statistics.median(quality_scores):.1f}%")
        
        # IBD Integration Report
        print(f"\n📊 IBD RATINGS INTEGRATION")
        ibd_valid = self.ibd_source.valid_symbols_count
        ibd_missing = self.ibd_source.missing_symbols_count
        ibd_total = ibd_valid + ibd_missing
        if ibd_total > 0:
            print(f"  Holdings with valid IBD data: {ibd_valid}/{ibd_total} ({ibd_valid/ibd_total*100:.1f}%)")
            if ibd_missing > 0:
                print(f"  Holdings needing IBD research: {ibd_missing}")
                # Print which symbols are missing IBD data
                missing_symbols = []
                for result in intelligence_results:
                    ibd_composite = result.get('ibd_composite', RESEARCH_NEEDED_PLACEHOLDER)
                    if ibd_composite == RESEARCH_NEEDED_PLACEHOLDER:
                        missing_symbols.append(result.get('symbol', 'UNKNOWN'))
                if missing_symbols:
                    print(f"    Missing: {', '.join(sorted(missing_symbols))}")
        else:
            print(f"  No IBD data processed")
        
        print(f"\n🔍 TOP METRICS POPULATED")
        sorted_metrics = sorted(
            populated_by_metric.items(),
            key=lambda x: x[1],
            reverse=True
        )
        for metric, count in sorted_metrics[:15]:
            pct = count / len(intelligence_results) * 100 if intelligence_results else 0
            print(f"  {metric:35} {count:3}/{len(intelligence_results):3} ({pct:5.1f}%)")
        
        print(f"\n⚠️  TOP METRICS NEEDING RESEARCH")
        sorted_metrics_asc = sorted(
            populated_by_metric.items(),
            key=lambda x: x[1]
        )
        for metric, count in sorted_metrics_asc[:15]:
            missing = len(intelligence_results) - count
            pct = missing / len(intelligence_results) * 100 if intelligence_results else 0
            print(f"  {metric:35} {missing:3}/{len(intelligence_results):3} ({pct:5.1f}%)")
        
        print(f"\n" + "="*80)


def main():
    """Run intelligence engine."""
    print("\n" + "="*80)
    print("🧠 McLeod Intelligence Engine v1.0")
    print("="*80 + "\n")
    
    try:
        engine = IntelligenceEngine()
        
        # Analyze all holdings
        intelligence_results = engine.analyze_all_holdings()
        
        # Save outputs
        engine.save_outputs(intelligence_results)
        
        # Generate summary
        engine.generate_summary(intelligence_results)
        
        print(f"\n✅ Intelligence Engine complete")
        print(f"="*80 + "\n")
        
        return intelligence_results
    
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
