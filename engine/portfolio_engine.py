#!/usr/bin/env python3
"""
McLeod Portfolio Engine v1.0
Comprehensive portfolio analysis, ranking, and allocation optimization.
"""

import json
import csv
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional
import statistics

from engine.phase2_downstream import Phase2DownstreamAdapter
from engine.phase2_research import PHASE2_ONBOARDING_ALLOWLIST

# Configuration
WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

PORTFOLIO_JSON = DATA_DIR / "schwab_portfolio_latest.json"
POSITIONS_CSV = DATA_DIR / "schwab_positions_latest.csv"
SUMMARY_JSON = DATA_DIR / "schwab_portfolio_summary_latest.json"

# Output files
CORE_RANKINGS_OUTPUT = DATA_DIR / "mcleod_core_rankings_latest.csv"
CORE_EXPLAINABILITY_OUTPUT = DATA_DIR / "core_rankings_explainability_latest.csv"
EIPV_RANKINGS_OUTPUT = DATA_DIR / "eipv_rankings_latest.csv"
TARGET_WEIGHTS_OUTPUT = DATA_DIR / "target_weights_latest.csv"

# Research data
RESEARCH_JSON = DATA_DIR / "mcleod_research_latest.json"
INTELLIGENCE_JSON = DATA_DIR / "mcleod_intelligence_latest.json"

# Portfolio constants
EXCLUDE_FROM_REPLACEMENT = {"SPCX"}  # Strategic holdings
CONCENTRATION_WARNING_THRESHOLD = 10.0  # % portfolio value
MAX_POSITION_SIZE = 15.0  # Target max % of portfolio

# Intelligence constants
RESEARCH_NEEDED = "NEEDS_RESEARCH"
MIN_DATA_QUALITY_FOR_RANKING = 70  # % of metrics needed to rank (updated to 70% for intelligence)


class PortfolioEngine:
    """Main portfolio analysis engine."""
    
    def __init__(self):
        """Initialize engine with latest portfolio data."""
        self.portfolio_data = None
        self.summary_data = None
        self.positions = []
        self.equities = []
        self.options = []
        self.research_data = {}
        self.phase2_context = {}
        self.holdings_blocked = []
        self.eipv_blocked = []
        self.load_portfolio()
        self.load_research()
        self.load_phase2_context()

    @staticmethod
    def _parse_iso_timestamp(value: Any) -> Any:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(datetime.now().astimezone().tzinfo).replace(tzinfo=None)
            return parsed
        except Exception:
            return None
    
    def load_portfolio(self):
        """Load latest portfolio data from JSON files."""
        try:
            with open(PORTFOLIO_JSON) as f:
                self.portfolio_data = json.load(f)
            
            with open(SUMMARY_JSON) as f:
                self.summary_data = json.load(f)
            
            # Separate equities and options
            self.positions = self.portfolio_data.get("positions", [])
            self.equities = [p for p in self.positions if p.get("asset_type") == "EQUITY"]
            self.options = [p for p in self.positions if p.get("asset_type") == "OPTION"]
            
            print(f"✓ Loaded portfolio: {len(self.positions)} positions ({len(self.equities)} equities, {len(self.options)} options)")
            
        except Exception as e:
            raise SystemExit(f"ERROR loading portfolio: {e}")
    
    def load_research(self):
        """Load intelligence/research data from JSON output."""
        try:
            # Try intelligence data first (v1.0), fall back to research data
            if INTELLIGENCE_JSON.exists():
                with open(INTELLIGENCE_JSON) as f:
                    research_metadata = json.load(f)
                print(f"✓ Loaded intelligence data (v1.0)")
            elif RESEARCH_JSON.exists():
                with open(RESEARCH_JSON) as f:
                    research_metadata = json.load(f)
                print(f"✓ Loaded research data (legacy)")
            else:
                print(f"⚠️  No intelligence or research data found")
                return
            
            option_map = self._build_option_underlying_map()
            holdings = research_metadata.get("holdings", [])
            for holding in holdings:
                symbol = holding.get("symbol", "")
                normalized = self._build_canonical_research_record(holding, option_map.get(symbol, []))
                enriched = dict(holding)
                enriched.update(normalized)
                self.research_data[symbol] = enriched
            
            print(f"✓ Loaded research data: {len(self.research_data)} holdings with metrics")
        
        except Exception as e:
            print(f"⚠️  ERROR loading research: {e}")
            self.research_data = {}

    def load_phase2_context(self):
        """Load validated Phase 2 snapshots as read-only research context."""
        try:
            adapter = Phase2DownstreamAdapter()
            self.phase2_context = adapter.load_many(list(PHASE2_ONBOARDING_ALLOWLIST))
            print(f"✓ Loaded Phase 2 context: {len(self.phase2_context)} tickers")
        except Exception as e:
            print(f"⚠️  ERROR loading Phase 2 context: {e}")
            self.phase2_context = {}

    def get_phase2_snapshot(self, symbol: str):
        """Return the validated Phase 2 snapshot for a symbol if available."""
        context = getattr(self, "phase2_context", {}) or {}
        return context.get(str(symbol).strip().upper())

    def _build_option_underlying_map(self) -> Dict[str, List[str]]:
        """Map equity symbols to option contracts that reference them."""
        option_map: Dict[str, List[str]] = {}
        for option in self.options:
            option_symbol = str(option.get("symbol", "")).strip()
            if not option_symbol:
                continue
            underlying = option_symbol.split(" ", 1)[0].strip().upper()
            if not underlying:
                continue
            option_map.setdefault(underlying, []).append(option_symbol)
        return option_map

    @staticmethod
    def _is_missing_value(value: Any) -> bool:
        return value in (None, "", RESEARCH_NEEDED)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value in (None, "", RESEARCH_NEEDED):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _confidence_label(score: float) -> str:
        if score >= 80:
            return "HIGH"
        if score >= 60:
            return "MEDIUM"
        if score >= 35:
            return "LOW"
        return "UNAVAILABLE"

    def _derive_expected_return_metrics(self, holding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build expected return metrics from validated, already-collected fundamentals."""
        growth_inputs = [
            self._to_float(holding.get("revenue_growth_1yr")),
            self._to_float(holding.get("revenue_growth_3yr")),
            self._to_float(holding.get("eps_growth_1yr")),
            self._to_float(holding.get("eps_growth_3yr")),
        ]
        growth_inputs = [v for v in growth_inputs if v is not None]

        business_quality = self._to_float(holding.get("business_quality"))
        valuation_score = self._to_float(holding.get("valuation_score"))
        if valuation_score is None:
            valuation_score = self._to_float(holding.get("valuation"))
        roic = self._to_float(holding.get("roic"))

        if not growth_inputs or business_quality is None or valuation_score is None:
            return None

        base_growth = statistics.mean(growth_inputs)
        quality_uplift = ((business_quality - 50.0) / 100.0) * 4.0
        valuation_edge = ((valuation_score - 50.0) / 100.0) * 6.0
        alpha_pct = (base_growth * 0.35) + quality_uplift + valuation_edge

        two_year_cagr = (base_growth * 0.60) + (alpha_pct * 0.40)
        ten_year_cagr = (base_growth * 0.45) + (alpha_pct * 0.25)
        if roic is not None and roic > 8:
            ten_year_cagr += min(4.0, (roic - 8.0) * 0.10)

        # Clamp to conservative bounds to avoid outlier-induced distortions.
        alpha_pct = max(-35.0, min(35.0, alpha_pct))
        two_year_cagr = max(-40.0, min(45.0, two_year_cagr))
        ten_year_cagr = max(-25.0, min(30.0, ten_year_cagr))

        confidence_fields = [
            "business_quality_confidence",
            "valuation_score_confidence",
            "revenue_growth_1yr_confidence",
            "revenue_growth_3yr_confidence",
            "eps_growth_1yr_confidence",
            "eps_growth_3yr_confidence",
            "roic_confidence",
        ]
        confidence_values = [
            self._to_float(holding.get(name)) for name in confidence_fields if self._to_float(holding.get(name)) is not None
        ]
        confidence_score = statistics.mean(confidence_values) if confidence_values else 0.0
        confidence_label = self._confidence_label(confidence_score)

        timestamp_fields = [
            "business_quality_timestamp",
            "valuation_score_timestamp",
            "revenue_growth_1yr_timestamp",
            "revenue_growth_3yr_timestamp",
            "eps_growth_1yr_timestamp",
            "eps_growth_3yr_timestamp",
            "roic_timestamp",
        ]
        parsed_times = [
            self._parse_iso_timestamp(holding.get(name)) for name in timestamp_fields if self._parse_iso_timestamp(holding.get(name))
        ]
        derived_timestamp = min(parsed_times).isoformat() if parsed_times else datetime.now().isoformat()

        source_notes = (
            "Derived from revenue/eps growth, business quality, valuation score, and ROIC using weighted CAGR/alpha formulas"
        )

        return {
            "expected_alpha": round(alpha_pct, 2),
            "expected_2yr_cagr": round(two_year_cagr, 2),
            "expected_10yr_cagr": round(ten_year_cagr, 2),
            "expected_alpha_source": "Portfolio Engine Derived",
            "expected_2yr_cagr_source": "Portfolio Engine Derived",
            "expected_10yr_cagr_source": "Portfolio Engine Derived",
            "expected_alpha_timestamp": derived_timestamp,
            "expected_2yr_cagr_timestamp": derived_timestamp,
            "expected_10yr_cagr_timestamp": derived_timestamp,
            "expected_alpha_confidence": round(confidence_score, 1),
            "expected_2yr_cagr_confidence": round(confidence_score, 1),
            "expected_10yr_cagr_confidence": round(confidence_score, 1),
            "expected_alpha_confidence_label": confidence_label,
            "expected_2yr_cagr_confidence_label": confidence_label,
            "expected_10yr_cagr_confidence_label": confidence_label,
            "expected_alpha_source_notes": source_notes,
            "expected_2yr_cagr_source_notes": source_notes,
            "expected_10yr_cagr_source_notes": source_notes,
            "expected_return_formula": (
                "alpha=0.35*avg_growth + 0.04*(business_quality-50) + 0.06*(valuation_score-50); "
                "cagr2=0.60*avg_growth + 0.40*alpha; cagr10=0.45*avg_growth + 0.25*alpha + max(0,0.10*(roic-8))"
            ),
        }

    def _build_canonical_research_record(self, holding: Dict[str, Any], linked_options: List[str]) -> Dict[str, Any]:
        """Build canonical, non-invented research fields used by ranking and EIPV."""
        canonical: Dict[str, Any] = {
            "canonical_research_record": {
                "symbol": holding.get("symbol", ""),
                "asset_type": "EQUITY",
                "linked_option_symbols": linked_options,
                "generated_at": datetime.now().isoformat(),
            }
        }

        # Canonical valuation field for report/ranking compatibility.
        if self._is_missing_value(holding.get("valuation")) and not self._is_missing_value(holding.get("valuation_score")):
            canonical["valuation"] = holding.get("valuation_score")
            canonical["valuation_source"] = holding.get("valuation_score_source", "Portfolio Engine Canonical Alias")
            canonical["valuation_timestamp"] = holding.get("valuation_score_timestamp", datetime.now().isoformat())
            canonical["valuation_confidence"] = holding.get("valuation_score_confidence", 0)
            canonical["valuation_confidence_label"] = self._confidence_label(float(canonical["valuation_confidence"] or 0))
            canonical["valuation_source_notes"] = "Aliased from valuation_score to support canonical required field."

        derived = self._derive_expected_return_metrics(holding)
        if derived:
            # Only fill fields that are currently missing to avoid overriding sourced research.
            for field in ["expected_alpha", "expected_2yr_cagr", "expected_10yr_cagr"]:
                if self._is_missing_value(holding.get(field)):
                    canonical[field] = derived[field]
                    canonical[f"{field}_source"] = derived[f"{field}_source"]
                    canonical[f"{field}_timestamp"] = derived[f"{field}_timestamp"]
                    canonical[f"{field}_confidence"] = derived[f"{field}_confidence"]
                    canonical[f"{field}_confidence_label"] = derived[f"{field}_confidence_label"]
                    canonical[f"{field}_source_notes"] = derived[f"{field}_source_notes"]
                    canonical["expected_return_formula"] = derived["expected_return_formula"]

        return canonical
    
    def get_research_value(self, symbol: str, field: str) -> Any:
        """Get research value for a symbol/field pair."""
        if symbol not in self.research_data:
            return RESEARCH_NEEDED
        
        holding_research = self.research_data[symbol]
        value = holding_research.get(field, RESEARCH_NEEDED)
        return value

    def _field_confidence(self, research: Dict[str, Any], field_name: str) -> float:
        raw = research.get(f"{field_name}_confidence", 0)
        parsed = self._to_float(raw)
        return float(parsed) if parsed is not None else 0.0

    def _field_confidence_label(self, research: Dict[str, Any], field_name: str) -> str:
        explicit = str(research.get(f"{field_name}_confidence_label", "")).strip().upper()
        if explicit in {"HIGH", "MEDIUM", "LOW", "UNAVAILABLE"}:
            return explicit
        return self._confidence_label(self._field_confidence(research, field_name))
    
    def get_portfolio_metrics(self) -> Dict[str, Any]:
        """Get key portfolio metrics."""
        account = self.portfolio_data.get("account", {})
        metrics = self.portfolio_data.get("metrics", {})
        margin = self.portfolio_data.get("margin", {})
        
        total_value = metrics.get("total_market_value", 0)
        buying_power = metrics.get("buying_power", 0)
        maintenance_req = metrics.get("maintenance_requirement", 0)
        
        return {
            "account_number": account.get("account_number", "N/A"),
            "account_type": account.get("account_type", "N/A"),
            "total_portfolio_value": total_value,
            "equity_value": metrics.get("equity", 0),
            "cash_balance": metrics.get("cash_balance", 0),
            "buying_power": buying_power,
            "maintenance_requirement": maintenance_req,
            "margin_efficiency_score": metrics.get("margin_efficiency_score", 0),
            "num_positions": len(self.positions),
            "num_equities": len(self.equities),
            "num_options": len(self.options),
        }
    
    def calculate_portfolio_health_score(self) -> float:
        """
        Calculate overall portfolio health score (0-100).
        Factors: diversification, concentration, margin efficiency, liquidity.
        """
        score = 100.0
        
        # Penalty for high concentration (top 5 > 50%)
        concentration = self.summary_data.get("concentration", {})
        top_5 = concentration.get("top_5_positions", {})
        top_5_pct = sum(v.get("weight_percent", 0) for v in top_5.values())
        if top_5_pct > 50:
            score -= min(10, (top_5_pct - 50) * 0.5)
        
        # Penalty for extreme positions (>15% each)
        large_positions = [p for p in self.equities if p.get("portfolio_weight_percent", 0) > 15]
        score -= len(large_positions) * 5
        
        # Bonus for good diversification (>15 positions)
        if len(self.equities) >= 15:
            score += 5
        
        # Penalty for low margin efficiency (< 40%)
        margin_eff = self.get_portfolio_metrics().get("margin_efficiency_score", 0)
        if margin_eff < 40:
            score -= (40 - margin_eff) * 0.1
        
        return max(0, min(100, score))
    
    def calculate_liquidity_risk_score(self) -> float:
        """Calculate portfolio liquidity risk (0=healthy, 100=illiquid)."""
        if not self.equities:
            return 0
        
        avg_liquidity = statistics.mean([p.get("liquidity_score", 50) for p in self.equities])
        return 100 - avg_liquidity
    
    def rank_core_holdings(self) -> List[Dict[str, Any]]:
        """
        Rank all holdings using McLeod Core Rankings.
        
        Ranking factors:
        - Position quality (fundamental metrics from research)
        - Current portfolio weight
        - Day P&L %
        - Liquidity score
        - Thesis health status
        
        BLOCKED holdings: Insufficient data quality for ranking
        """
        rankings = []
        self.holdings_blocked = []

        def to_float(value: Any) -> float:
            try:
                if value in (None, "", RESEARCH_NEEDED):
                    return 0.0
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        def normalize(value: float, min_v: float, max_v: float) -> float:
            if max_v <= min_v:
                return 0.0
            clipped = max(min_v, min(max_v, value))
            return ((clipped - min_v) / (max_v - min_v)) * 100.0

        def score_from_letter(letter: Any) -> float:
            if letter in (None, "", RESEARCH_NEEDED):
                return 0.0
            mapping = {"A+": 95, "A": 90, "B+": 80, "B": 75, "C": 60, "D": 45, "E": 30}
            return float(mapping.get(str(letter).strip().upper(), 0.0))

        def thesis_score(status: Any) -> float:
            status_norm = str(status or "HEALTHY").upper()
            if status_norm in {"HEALTHY", "INTACT"}:
                return 80.0
            if status_norm in {"AT_RISK", "WATCH"}:
                return 50.0
            if status_norm in {"BROKEN", "FAILED"}:
                return 0.0
            return 60.0
        
        for i, pos in enumerate(self.equities, 1):
            symbol = pos.get("symbol", "")
            market_value = pos.get("market_value", 0)
            weight_pct = pos.get("portfolio_weight_percent", 0)
            day_pl_pct = pos.get("day_pl_pct", 0) or 0
            liquidity = pos.get("liquidity_score", 50)
            themes = pos.get("themes", [])
            
            # Get research data
            research = self.research_data.get(symbol, {})
            data_quality = research.get("data_quality_score", 0)
            
            # Check if holding is blocked from ranking
            if data_quality < MIN_DATA_QUALITY_FOR_RANKING:
                self.holdings_blocked.append({
                    "symbol": symbol,
                    "reason": f"Insufficient data quality ({data_quality:.1f}% < {MIN_DATA_QUALITY_FOR_RANKING}%)",
                    "data_quality": data_quality,
                })
                continue
            
            # Get core metrics and score components from research/intelligence data
            business_quality = self.get_research_value(symbol, "business_quality")
            valuation = self.get_research_value(symbol, "valuation_score")
            if valuation == RESEARCH_NEEDED:
                valuation = self.get_research_value(symbol, "valuation")
            expected_alpha = self.get_research_value(symbol, "expected_alpha")
            thesis_health = self.get_research_value(symbol, "thesis_health") or "HEALTHY"
            expected_2yr_cagr = self.get_research_value(symbol, "expected_2yr_cagr")
            expected_10yr_cagr = self.get_research_value(symbol, "expected_10yr_cagr")
            mcleod_composite = self.get_research_value(symbol, "mcleod_core_composite")
            analyst_alpha = to_float(self.get_research_value(symbol, "analyst_alpha_score"))
            analyst_explainability = self.get_research_value(symbol, "analyst_intelligence_explainability")
            earnings_call_score = to_float(self.get_research_value(symbol, "earnings_call_intelligence_score"))
            earnings_call_thesis_impact = to_float(self.get_research_value(symbol, "earnings_call_thesis_impact_score"))
            earnings_call_explainability = self.get_research_value(symbol, "earnings_call_explainability")
            insider_score = to_float(self.get_research_value(symbol, "insider_intelligence_score"))
            insider_thesis_impact = to_float(self.get_research_value(symbol, "insider_thesis_impact_score"))
            insider_explainability = self.get_research_value(symbol, "insider_explainability")
            earnings_quality_score = to_float(self.get_research_value(symbol, "earnings_quality_score"))
            earnings_quality_thesis_impact = to_float(self.get_research_value(symbol, "earnings_quality_thesis_impact_score"))
            earnings_quality_explainability = self.get_research_value(symbol, "earnings_quality_explainability")
            capital_allocation_score = to_float(self.get_research_value(symbol, "capital_allocation_intelligence_score"))
            buyback_intelligence_score = to_float(self.get_research_value(symbol, "capital_allocation_buyback_intelligence_score"))
            buyback_thesis_impact = to_float(self.get_research_value(symbol, "capital_allocation_buyback_thesis_impact_score"))
            capital_allocation_explainability = self.get_research_value(symbol, "capital_allocation_explainability")

            # Pull additional raw metrics for explainable ranking components.
            roic = to_float(self.get_research_value(symbol, "roic"))
            roe = to_float(self.get_research_value(symbol, "roe"))
            net_margin = to_float(self.get_research_value(symbol, "net_margin"))
            rev_growth_1y = to_float(self.get_research_value(symbol, "revenue_growth_1yr"))
            rev_growth_3y = to_float(self.get_research_value(symbol, "revenue_growth_3yr"))
            eps_growth_1y = to_float(self.get_research_value(symbol, "eps_growth_1yr"))
            eps_growth_3y = to_float(self.get_research_value(symbol, "eps_growth_3yr"))
            ibd_composite = to_float(self.get_research_value(symbol, "ibd_composite"))
            ibd_eps = to_float(self.get_research_value(symbol, "ibd_eps_rating"))
            ibd_rs = to_float(self.get_research_value(symbol, "ibd_rs_rating"))
            ibd_smr = score_from_letter(self.get_research_value(symbol, "ibd_smr_rating"))
            pe_ratio = to_float(self.get_research_value(symbol, "pe_ratio"))
            pb_ratio = to_float(self.get_research_value(symbol, "price_to_book"))
            ps_ratio = to_float(self.get_research_value(symbol, "price_to_sales"))
            price_to_fcf = to_float(self.get_research_value(symbol, "price_to_fcf"))

            quality_component = 0.0
            if business_quality != RESEARCH_NEEDED:
                quality_component = to_float(business_quality)
            else:
                quality_parts = [
                    normalize(roic, 0, 25),
                    normalize(roe, 0, 30),
                    normalize(net_margin, 0, 30),
                ]
                quality_component = statistics.mean([v for v in quality_parts if v > 0]) if any(v > 0 for v in quality_parts) else 0.0

            valuation_component = 0.0
            if valuation != RESEARCH_NEEDED:
                valuation_component = to_float(valuation)
            else:
                valuation_parts = []
                if pe_ratio > 0:
                    valuation_parts.append(normalize(35 - pe_ratio, 0, 35))
                if pb_ratio > 0:
                    valuation_parts.append(normalize(8 - pb_ratio, 0, 8))
                if ps_ratio > 0:
                    valuation_parts.append(normalize(10 - ps_ratio, 0, 10))
                if price_to_fcf > 0:
                    valuation_parts.append(normalize(45 - price_to_fcf, 0, 45))
                valuation_component = statistics.mean(valuation_parts) if valuation_parts else 0.0

            growth_component_parts = []
            if expected_2yr_cagr != RESEARCH_NEEDED:
                growth_component_parts.append(normalize(to_float(expected_2yr_cagr), -20, 40))
            if expected_10yr_cagr != RESEARCH_NEEDED:
                growth_component_parts.append(normalize(to_float(expected_10yr_cagr), -10, 25))
            growth_component_parts.extend([
                normalize(rev_growth_1y, -20, 50),
                normalize(rev_growth_3y, -20, 40),
                normalize(eps_growth_1y, -30, 70),
                normalize(eps_growth_3y, -20, 50),
            ])
            growth_component = statistics.mean([v for v in growth_component_parts if v > 0]) if any(v > 0 for v in growth_component_parts) else 0.0

            ibd_component_parts = [v for v in [ibd_composite, ibd_eps, ibd_rs, ibd_smr] if v > 0]
            ibd_component = statistics.mean(ibd_component_parts) if ibd_component_parts else 0.0
            analyst_component = max(0.0, min(100.0, analyst_alpha))
            earnings_call_component = max(0.0, min(100.0, earnings_call_score))
            if earnings_call_thesis_impact > 0:
                earnings_call_component = (earnings_call_component * 0.7) + (earnings_call_thesis_impact * 0.3)
            insider_component = max(0.0, min(100.0, insider_score))
            if insider_thesis_impact > 0:
                insider_component = (insider_component * 0.7) + (insider_thesis_impact * 0.3)
            earnings_quality_component = max(0.0, min(100.0, earnings_quality_score))
            if earnings_quality_thesis_impact > 0:
                earnings_quality_component = (earnings_quality_component * 0.7) + (earnings_quality_thesis_impact * 0.3)
            capital_allocation_component = max(0.0, min(100.0, capital_allocation_score))
            # Buyback intelligence is already embedded in capital_allocation_intelligence_score.
            # Do not re-blend buyback fields here to avoid double-counting the same signal.

            if expected_alpha == RESEARCH_NEEDED:
                alpha_support_components = [
                    analyst_component,
                    earnings_call_component,
                    insider_component,
                    earnings_quality_component,
                    capital_allocation_component,
                    growth_component,
                ]
                alpha_support = statistics.mean(alpha_support_components)
                expected_alpha = round((alpha_support - 50.0) / 5.0, 2)

            liquidity_component = float(liquidity)
            thesis_component = thesis_score(thesis_health)

            # Penalize positions with weak data quality and avoid overweight bias.
            data_quality_component = float(data_quality)
            weight_penalty = max(0.0, weight_pct - 8.0) * 2.0

            component_weights = {
                "quality": 0.17,
                "valuation": 0.15,
                "growth": 0.15,
                "ibd": 0.10,
                "analyst": 0.05,
                "earnings_call": 0.06,
                "insider": 0.07,
                "earnings_quality": 0.09,
                "capital_allocation": 0.08,
                "liquidity": 0.05,
                "thesis": 0.03,
                "data_quality": 0.04,
            }

            composite_score = (
                quality_component * component_weights["quality"]
                + valuation_component * component_weights["valuation"]
                + growth_component * component_weights["growth"]
                + ibd_component * component_weights["ibd"]
                + analyst_component * component_weights["analyst"]
                + earnings_call_component * component_weights["earnings_call"]
                + insider_component * component_weights["insider"]
                + earnings_quality_component * component_weights["earnings_quality"]
                + capital_allocation_component * component_weights["capital_allocation"]
                + liquidity_component * component_weights["liquidity"]
                + thesis_component * component_weights["thesis"]
                + data_quality_component * component_weights["data_quality"]
                - weight_penalty
            )
            composite_score = max(0.0, min(100.0, composite_score))

            if mcleod_composite != RESEARCH_NEEDED:
                composite_score = (composite_score * 0.7) + (to_float(mcleod_composite) * 0.3)

            missing_for_score = 0
            for v in [business_quality, valuation, expected_2yr_cagr, expected_10yr_cagr]:
                if v == RESEARCH_NEEDED:
                    missing_for_score += 1
            
            rankings.append({
                "rank": i,
                "symbol": symbol,
                "asset_type": pos.get("asset_type", "EQUITY"),
                "market_value": market_value,
                "weight_pct": weight_pct,
                "quantity": pos.get("quantity", 0),
                "avg_price": pos.get("average_price", 0),
                "current_price": pos.get("current_price", 0),
                "day_pl": pos.get("day_pl", 0),
                "day_pl_pct": day_pl_pct,
                "liquidity_score": liquidity,
                "themes": ",".join(themes) if themes else "",
                "composite_score": round(composite_score, 2),
                "business_quality": business_quality,
                "business_quality_timestamp": self.get_research_value(symbol, "business_quality_timestamp"),
                "expected_alpha": expected_alpha,
                "expected_alpha_timestamp": self.get_research_value(symbol, "expected_alpha_timestamp"),
                "valuation": valuation,
                "valuation_timestamp": self.get_research_value(symbol, "valuation_timestamp"),
                "thesis_health": thesis_health,
                "expected_2yr_cagr": expected_2yr_cagr,
                "expected_2yr_cagr_timestamp": self.get_research_value(symbol, "expected_2yr_cagr_timestamp"),
                "expected_10yr_cagr": expected_10yr_cagr,
                "expected_10yr_cagr_timestamp": self.get_research_value(symbol, "expected_10yr_cagr_timestamp"),
                "mcleod_core_composite": mcleod_composite,
                "analyst_alpha_score": round(analyst_component, 2),
                "analyst_intelligence_explainability": analyst_explainability,
                "earnings_call_intelligence_score": round(earnings_call_component, 2),
                "earnings_call_explainability": earnings_call_explainability,
                "insider_intelligence_score": round(insider_component, 2),
                "insider_explainability": insider_explainability,
                "earnings_quality_score": round(earnings_quality_component, 2),
                "earnings_quality_explainability": earnings_quality_explainability,
                "capital_allocation_intelligence_score": round(capital_allocation_component, 2),
                "capital_allocation_buyback_intelligence_score": round(max(0.0, min(100.0, buyback_intelligence_score)), 2),
                "capital_allocation_buyback_thesis_impact_score": round(max(0.0, min(100.0, buyback_thesis_impact)), 2),
                "capital_allocation_explainability": capital_allocation_explainability,
                "data_quality": data_quality,
                "component_quality": round(quality_component, 2),
                "component_valuation": round(valuation_component, 2),
                "component_growth": round(growth_component, 2),
                "component_ibd": round(ibd_component, 2),
                "component_analyst_intelligence": round(analyst_component, 2),
                "component_earnings_call_intelligence": round(earnings_call_component, 2),
                "component_insider_intelligence": round(insider_component, 2),
                "component_earnings_quality": round(earnings_quality_component, 2),
                "component_capital_allocation": round(capital_allocation_component, 2),
                "component_liquidity": round(liquidity_component, 2),
                "component_thesis": round(thesis_component, 2),
                "component_data_quality": round(data_quality_component, 2),
                "weight_penalty": round(weight_penalty, 2),
                "missing_core_inputs": missing_for_score,
            })
        
        # Sort by composite score (descending)
        rankings.sort(key=lambda x: x["composite_score"], reverse=True)
        
        # Re-rank after sorting
        for i, r in enumerate(rankings, 1):
            r["rank"] = i
        
        return rankings
    
    def calculate_eipv_rankings(self, allocation_amount: float = 1000.0) -> List[Dict[str, Any]]:
        """
        Calculate Expected Investor Portfolio Value (EIPV) rankings.
        
        EIPV = Expected contribution to portfolio value if $1,000 is allocated.
        
        Factors considered:
        - Momentum (day P&L %)
        - Liquidity (ability to add/remove positions)
        - Expected alpha (NEEDS_RESEARCH)
        - Current underweight vs target
        - Position quality (NEEDS_RESEARCH)
        """
        rankings = []
        self.eipv_blocked = []
        total_portfolio_value = self.get_portfolio_metrics()["total_portfolio_value"]
        max_age_hours = int(os.getenv("MORNING_CIO_MAX_RESEARCH_AGE_HOURS", "48") or "48")
        min_confidence = float(os.getenv("MORNING_CIO_MIN_EIPV_CONFIDENCE", "60") or "60")
        required_fields = ["business_quality", "valuation", "expected_alpha", "expected_2yr_cagr", "expected_10yr_cagr"]
        now = datetime.now()
        
        for pos in self.equities:
            symbol = pos.get("symbol", "")
            weight_pct = pos.get("portfolio_weight_percent", 0)
            day_pl_pct = pos.get("day_pl_pct", 0) or 0
            liquidity = pos.get("liquidity_score", 50)
            market_value = pos.get("market_value", 0)

            research = self.research_data.get(symbol, {})
            phase2_snapshot = self.get_phase2_snapshot(symbol)
            model_type = str(research.get("research_model_type") or "").strip().lower()
            eipv_exclusion = research.get("eipv_exclusion") or {}
            exclude_from_company_eipv = (
                model_type in {"fund_etf", "fund", "etf"}
                and str(eipv_exclusion.get("policy") or "").strip().upper() == "EXCLUDE_FROM_COMPANY_EIPV"
            )
            if exclude_from_company_eipv:
                self.eipv_blocked.append(
                    {
                        "symbol": symbol,
                        "missing_fields": [],
                        "stale_fields": [],
                        "low_confidence_fields": [],
                        "missing_assumptions": [],
                        "reason": str(
                            eipv_exclusion.get("reason")
                            or "Excluded from company-level EIPV: fund/ETF requires separate fund model"
                        ),
                    }
                )
                continue

            approved_for_eipv = bool(research.get("approved_for_eipv", True))
            if phase2_snapshot and phase2_snapshot.available:
                approved_for_eipv = bool(phase2_snapshot.approved_for_eipv)
            assumption_payload = research.get("expected_return_assumptions")
            has_explicit_assumptions = (
                isinstance(assumption_payload, dict)
                and bool(assumption_payload.get("explicit_company_assumptions"))
                and bool(
                    assumption_payload.get("starting_revenue")
                    or assumption_payload.get("starting_earnings")
                    or assumption_payload.get("starting_metric")
                )
                and bool(assumption_payload.get("source_timestamps"))
            )

            missing_fields = []
            stale_fields = []
            low_confidence_fields = []
            missing_assumptions = []

            if not approved_for_eipv:
                missing_assumptions.append("approved_for_eipv")

            if not has_explicit_assumptions:
                missing_assumptions.append("expected_return_assumptions")

            for field_name in required_fields:
                value = research.get(field_name, RESEARCH_NEEDED)
                if value in (None, "", RESEARCH_NEEDED):
                    missing_fields.append(field_name)
                    continue

                field_confidence = self._field_confidence(research, field_name)
                field_confidence_label = self._field_confidence_label(research, field_name)
                if field_confidence < min_confidence or field_confidence_label in {"LOW", "UNAVAILABLE"}:
                    low_confidence_fields.append(field_name)
                    continue

                ts_key = f"{field_name}_timestamp"
                ts_value = research.get(ts_key)
                parsed = self._parse_iso_timestamp(ts_value)
                if parsed is None:
                    stale_fields.append(field_name)
                    continue
                if parsed.tzinfo is not None:
                    age_hours = (datetime.now(parsed.tzinfo) - parsed).total_seconds() / 3600
                else:
                    age_hours = (now - parsed).total_seconds() / 3600
                if age_hours > max(1, max_age_hours):
                    stale_fields.append(field_name)

            if missing_fields or stale_fields or low_confidence_fields or missing_assumptions:
                self.eipv_blocked.append(
                    {
                        "symbol": symbol,
                        "missing_fields": missing_fields,
                        "stale_fields": stale_fields,
                        "low_confidence_fields": low_confidence_fields,
                        "missing_assumptions": missing_assumptions,
                        "reason": "EIPV requires fresh, confidence-qualified research inputs backed by explicit company-level assumptions",
                    }
                )
                continue
            
            # Calculate target weight (equal-weight across equities)
            target_weight = 100.0 / len(self.equities) if self.equities else 0
            underweight_pct = target_weight - weight_pct
            
            # EIPV score components
            # 1. Momentum contribution (recent performance)
            momentum_score = max(-5, min(10, day_pl_pct))
            
            # 2. Liquidity contribution (can trade this easily)
            liquidity_contribution = liquidity / 100.0 * 5
            
            # 3. Underweight opportunity (more room to add)
            if underweight_pct > 0:
                underweight_contribution = min(10, underweight_pct / 5)
            else:
                underweight_contribution = -min(5, abs(underweight_pct) / 5)
            
            # 4. Expected return from validated growth/alpha assumptions.
            expected_alpha = self._to_float(research.get("expected_alpha")) or 0.0
            expected_2yr_cagr = self._to_float(research.get("expected_2yr_cagr")) or 0.0
            expected_10yr_cagr = self._to_float(research.get("expected_10yr_cagr")) or 0.0
            expected_return = (expected_alpha * 0.40) + (expected_2yr_cagr * 0.40) + (expected_10yr_cagr * 0.20)
            expected_return = max(-25.0, min(25.0, expected_return))
            
            # Total EIPV score
            eipv_score = (
                momentum_score * 0.3 +
                liquidity_contribution * 0.3 +
                underweight_contribution * 0.2 +
                expected_return * 0.2
            )
            
            # Calculate new weight if $1,000 added
            new_portfolio_value = total_portfolio_value + allocation_amount
            new_position_value = market_value + allocation_amount
            new_weight = (new_position_value / new_portfolio_value) * 100
            
            rankings.append({
                "symbol": symbol,
                "market_value": market_value,
                "current_weight_pct": weight_pct,
                "target_weight_pct": target_weight,
                "underweight_pct": underweight_pct,
                "momentum_score": round(momentum_score, 2),
                "liquidity_score": liquidity,
                "expected_alpha": round(expected_alpha, 2),
                "expected_2yr_cagr": round(expected_2yr_cagr, 2),
                "expected_10yr_cagr": round(expected_10yr_cagr, 2),
                "expected_return_pct": round(expected_return, 2),
                "expected_return_formula": research.get("expected_return_formula", "0.40*alpha + 0.40*cagr2 + 0.20*cagr10"),
                "expected_return_confidence_label": self._field_confidence_label(research, "expected_alpha"),
                "eipv_score": round(eipv_score, 2),
                "allocation_amount": allocation_amount,
                "new_position_value": new_position_value,
                "new_portfolio_value": new_portfolio_value,
                "new_weight_pct": round(new_weight, 2),
                "potential_value_add": round(allocation_amount * (1 + eipv_score / 100), 2),
            })
        
        # Sort by EIPV score (descending)
        rankings.sort(key=lambda x: x["eipv_score"], reverse=True)
        
        return rankings
    
    def identify_replacement_candidates(self, min_weight: float = 0.5) -> List[Dict[str, Any]]:
        """
        Identify replacement candidates (lowest-ranked positions).
        Excludes: SPCX (strategic), positions under min_weight, and options.
        """
        candidates = []
        core_rankings = self.rank_core_holdings()
        
        for ranking in core_rankings:
            symbol = ranking["symbol"]
            weight = ranking["weight_pct"]
            
            # Skip exclusions
            if symbol in EXCLUDE_FROM_REPLACEMENT:
                continue
            if weight < min_weight:
                continue
            
            candidates.append({
                "symbol": symbol,
                "rank": ranking["rank"],
                "market_value": ranking["market_value"],
                "weight_pct": weight,
                "day_pl_pct": ranking["day_pl_pct"],
                "liquidity_score": ranking["liquidity_score"],
                "composite_score": ranking["composite_score"],
                "insider_intelligence_score": ranking.get("insider_intelligence_score", 0),
                "insider_explainability": ranking.get("insider_explainability", RESEARCH_NEEDED),
                "earnings_quality_score": ranking.get("earnings_quality_score", 0),
                "earnings_quality_explainability": ranking.get("earnings_quality_explainability", RESEARCH_NEEDED),
                "capital_allocation_intelligence_score": ranking.get("capital_allocation_intelligence_score", 0),
                "capital_allocation_explainability": ranking.get("capital_allocation_explainability", RESEARCH_NEEDED),
                "reason": "Lowest composite score among replaceable holdings" if ranking["rank"] == len(core_rankings) else "Lower-ranked holding",
            })
        
        return candidates
    
    def flag_concentration_risks(self) -> List[Dict[str, Any]]:
        """Identify positions with concentration risk."""
        risks = []
        
        for pos in self.equities:
            symbol = pos.get("symbol", "")
            weight = pos.get("portfolio_weight_percent", 0)
            
            if weight > CONCENTRATION_WARNING_THRESHOLD:
                risks.append({
                    "symbol": symbol,
                    "weight_pct": weight,
                    "market_value": pos.get("market_value", 0),
                    "threshold": CONCENTRATION_WARNING_THRESHOLD,
                    "excess_pct": round(weight - CONCENTRATION_WARNING_THRESHOLD, 2),
                    "severity": "CRITICAL" if weight > 15 else "WARNING",
                })
        
        return sorted(risks, key=lambda x: x["weight_pct"], reverse=True)
    
    def estimate_target_weights(self, method: str = "equal_weight") -> List[Dict[str, Any]]:
        """
        Estimate target portfolio weights.
        
        Methods:
        - equal_weight: Each equity gets equal weight
        - cap_weight: Size-weighted (current approach)
        - mcleod_optimized: Target optimization respecting constraints
        """
        target_weights = []
        total_value = self.get_portfolio_metrics()["total_portfolio_value"]
        
        if method == "equal_weight":
            target_weight = 100.0 / len(self.equities) if self.equities else 0
            for pos in self.equities:
                symbol = pos.get("symbol", "")
                current_weight = pos.get("portfolio_weight_percent", 0)
                current_value = pos.get("market_value", 0)
                target_value = (target_weight / 100) * total_value
                diff_value = target_value - current_value
                diff_pct = target_weight - current_weight
                
                target_weights.append({
                    "symbol": symbol,
                    "current_weight_pct": round(current_weight, 2),
                    "target_weight_pct": round(target_weight, 2),
                    "diff_pct": round(diff_pct, 2),
                    "current_value": round(current_value, 2),
                    "target_value": round(target_value, 2),
                    "diff_value": round(diff_value, 2),
                    "action": "BUY" if diff_pct > 0 else "SELL" if diff_pct < -0.5 else "HOLD",
                    "priority": abs(diff_pct),
                })
        
        elif method == "mcleod_optimized":
            # Cap positions at MAX_POSITION_SIZE, distribute remainder equally
            allocated = {}
            remaining = []
            
            for pos in self.equities:
                symbol = pos.get("symbol", "")
                current_weight = pos.get("portfolio_weight_percent", 0)
                
                if current_weight > MAX_POSITION_SIZE:
                    allocated[symbol] = MAX_POSITION_SIZE
                else:
                    remaining.append(symbol)
            
            # Distribute remaining weight equally among non-capped positions
            allocated_weight = sum(allocated.values())
            remaining_weight = 100 - allocated_weight
            target_for_remaining = remaining_weight / len(remaining) if remaining else 0
            
            for symbol in remaining:
                allocated[symbol] = target_for_remaining
            
            for pos in self.equities:
                symbol = pos.get("symbol", "")
                current_weight = pos.get("portfolio_weight_percent", 0)
                current_value = pos.get("market_value", 0)
                target_weight = allocated.get(symbol, 0)
                target_value = (target_weight / 100) * total_value
                diff_value = target_value - current_value
                diff_pct = target_weight - current_weight
                
                target_weights.append({
                    "symbol": symbol,
                    "current_weight_pct": round(current_weight, 2),
                    "target_weight_pct": round(target_weight, 2),
                    "diff_pct": round(diff_pct, 2),
                    "current_value": round(current_value, 2),
                    "target_value": round(target_value, 2),
                    "diff_value": round(diff_value, 2),
                    "action": "BUY" if diff_pct > 0.5 else "SELL" if diff_pct < -0.5 else "HOLD",
                    "priority": abs(diff_pct),
                })
        
        else:  # cap_weight (current)
            for pos in self.equities:
                symbol = pos.get("symbol", "")
                current_weight = pos.get("portfolio_weight_percent", 0)
                
                target_weights.append({
                    "symbol": symbol,
                    "current_weight_pct": round(current_weight, 2),
                    "target_weight_pct": round(current_weight, 2),
                    "diff_pct": 0.0,
                    "current_value": round(pos.get("market_value", 0), 2),
                    "target_value": round(pos.get("market_value", 0), 2),
                    "diff_value": 0.0,
                    "action": "HOLD",
                    "priority": 0.0,
                })
        
        return sorted(target_weights, key=lambda x: x["priority"], reverse=True)
    
    def save_core_rankings(self, rankings: List[Dict[str, Any]]):
        """Save core rankings to CSV."""
        if not rankings:
            print("No rankings to save")
            return
        
        try:
            with open(CORE_RANKINGS_OUTPUT, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=rankings[0].keys())
                writer.writeheader()
                writer.writerows(rankings)
            print(f"✓ Core rankings saved to {CORE_RANKINGS_OUTPUT}")
            self.save_core_explainability(rankings)
        except Exception as e:
            print(f"ERROR saving core rankings: {e}")

    def save_core_explainability(self, rankings: List[Dict[str, Any]]):
        """Save explainability rows for ranked holdings."""
        if not rankings:
            return

        rows = []
        for r in rankings:
            rows.append(
                {
                    "rank": r.get("rank"),
                    "symbol": r.get("symbol"),
                    "composite_score": r.get("composite_score"),
                    "component_quality": r.get("component_quality"),
                    "component_valuation": r.get("component_valuation"),
                    "component_growth": r.get("component_growth"),
                    "component_ibd": r.get("component_ibd"),
                    "component_analyst_intelligence": r.get("component_analyst_intelligence"),
                    "component_earnings_call_intelligence": r.get("component_earnings_call_intelligence"),
                    "component_insider_intelligence": r.get("component_insider_intelligence"),
                    "component_earnings_quality": r.get("component_earnings_quality"),
                    "component_capital_allocation": r.get("component_capital_allocation"),
                    "component_liquidity": r.get("component_liquidity"),
                    "component_thesis": r.get("component_thesis"),
                    "component_data_quality": r.get("component_data_quality"),
                    "analyst_alpha_score": r.get("analyst_alpha_score"),
                    "analyst_intelligence_explainability": r.get("analyst_intelligence_explainability"),
                    "earnings_call_intelligence_score": r.get("earnings_call_intelligence_score"),
                    "earnings_call_explainability": r.get("earnings_call_explainability"),
                    "insider_intelligence_score": r.get("insider_intelligence_score"),
                    "insider_explainability": r.get("insider_explainability"),
                    "earnings_quality_score": r.get("earnings_quality_score"),
                    "earnings_quality_explainability": r.get("earnings_quality_explainability"),
                    "capital_allocation_intelligence_score": r.get("capital_allocation_intelligence_score"),
                    "capital_allocation_explainability": r.get("capital_allocation_explainability"),
                    "data_quality": r.get("data_quality"),
                }
            )

        with open(CORE_EXPLAINABILITY_OUTPUT, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"✓ Core explainability saved to {CORE_EXPLAINABILITY_OUTPUT}")
    
    def save_eipv_rankings(self, rankings: List[Dict[str, Any]]):
        """Save EIPV rankings to CSV."""
        if not rankings:
            print("No EIPV rankings to save")
            return
        
        try:
            with open(EIPV_RANKINGS_OUTPUT, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=rankings[0].keys())
                writer.writeheader()
                writer.writerows(rankings)
            print(f"✓ EIPV rankings saved to {EIPV_RANKINGS_OUTPUT}")
        except Exception as e:
            print(f"ERROR saving EIPV rankings: {e}")
    
    def save_target_weights(self, target_weights: List[Dict[str, Any]]):
        """Save target weights to CSV."""
        if not target_weights:
            print("No target weights to save")
            return
        
        try:
            with open(TARGET_WEIGHTS_OUTPUT, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=target_weights[0].keys())
                writer.writeheader()
                writer.writerows(target_weights)
            print(f"✓ Target weights saved to {TARGET_WEIGHTS_OUTPUT}")
        except Exception as e:
            print(f"ERROR saving target weights: {e}")


def main():
    """Run full portfolio analysis engine."""
    print("\n" + "="*80)
    print("🏛️  McLeod Portfolio Engine v1.0")
    print("="*80)
    
    try:
        engine = PortfolioEngine()
        
        # Get portfolio metrics
        metrics = engine.get_portfolio_metrics()
        print(f"\n📊 Portfolio Metrics:")
        print(f"  Account: {metrics['account_number']} ({metrics['account_type']})")
        print(f"  Total Value: ${metrics['total_portfolio_value']:,.2f}")
        print(f"  Positions: {metrics['num_equities']} equities, {metrics['num_options']} options")
        
        # Calculate health scores
        health_score = engine.calculate_portfolio_health_score()
        liquidity_risk = engine.calculate_liquidity_risk_score()
        print(f"\n💪 Portfolio Health:")
        print(f"  Portfolio Health Score: {health_score:.1f}/100")
        print(f"  Liquidity Risk Score: {liquidity_risk:.1f}/100")
        print(f"  Margin Efficiency: {metrics['margin_efficiency_score']:.1f}%")
        
        # Core rankings
        print(f"\n📈 Running McLeod Core Rankings analysis...")
        core_rankings = engine.rank_core_holdings()
        engine.save_core_rankings(core_rankings)
        
        # Report on blocked holdings
        if engine.holdings_blocked:
            print(f"  🚫 {len(engine.holdings_blocked)} holdings blocked from ranking:")
            for blocked in engine.holdings_blocked:
                print(f"    {blocked['symbol']:8} - {blocked['reason']}")
        
        if core_rankings:
            print(f"  ✓ Top 5 holdings by composite score:")
            for r in core_rankings[:5]:
                print(f"    {r['rank']}. {r['symbol']:8} {r['weight_pct']:6.2f}% ${r['market_value']:>10,.0f} (score: {r['composite_score']:.1f})")
        else:
            print(f"  ⚠️  No holdings ranked (insufficient research data)")
        
        # EIPV rankings
        print(f"\n💰 Running EIPV analysis (best $1,000 allocation)...")
        eipv_rankings = engine.calculate_eipv_rankings(1000.0)
        engine.save_eipv_rankings(eipv_rankings)
        print(f"  ✓ Top destination for next $1,000:")
        if eipv_rankings:
            top = eipv_rankings[0]
            print(f"    {top['symbol']:8} (EIPV: {top['eipv_score']:.2f}, new weight: {top['new_weight_pct']:.2f}%)")
        
        # Target weights
        print(f"\n🎯 Calculating target weights...")
        target_weights = engine.estimate_target_weights(method="mcleod_optimized")
        engine.save_target_weights(target_weights)
        top_actions = [t for t in target_weights if t['action'] != 'HOLD'][:3]
        if top_actions:
            print(f"  ✓ Top rebalancing actions:")
            for t in top_actions:
                action = t['action']
                diff = t['diff_pct']
                print(f"    {action:4} {t['symbol']:8} {diff:+.2f}% (to {t['target_weight_pct']:.2f}%)")
        
        # Concentration risks
        print(f"\n⚠️  Concentration Analysis:")
        concentration_risks = engine.flag_concentration_risks()
        if concentration_risks:
            print(f"  ⚠️  {len(concentration_risks)} positions with concentration risk:")
            for risk in concentration_risks[:3]:
                print(f"    {risk['symbol']:8} {risk['weight_pct']:6.2f}% ({risk['severity']})")
        else:
            print(f"  ✓ No concentration risks detected")
        
        # Replacement candidates
        print(f"\n🔄 Replacement Candidates:")
        candidates = engine.identify_replacement_candidates()
        if candidates:
            print(f"  ✓ Lowest-ranked replaceable holding:")
            lowest = candidates[-1]  # Last is lowest ranked
            print(f"    {lowest['symbol']:8} rank {lowest['rank']} (score: {lowest['composite_score']:.1f})")
        else:
            print(f"  ✓ No replacement candidates")
        
        print(f"\n" + "="*80)
        print(f"✓ Portfolio Engine analysis complete")
        print(f"="*80 + "\n")
        
        return {
            "metrics": metrics,
            "health_score": health_score,
            "liquidity_risk": liquidity_risk,
            "core_rankings": core_rankings,
            "eipv_rankings": eipv_rankings,
            "target_weights": target_weights,
            "concentration_risks": concentration_risks,
            "replacement_candidates": candidates,
        }
    
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
