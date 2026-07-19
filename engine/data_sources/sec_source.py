#!/usr/bin/env python3
"""
SEC Data Source - Official SEC EDGAR API Integration
Extracts financial metrics directly from SEC XBRL filings.
No external dependencies (yfinance, pandas, etc.) required.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import json
from pathlib import Path
import os
import sys
import time

# Add parent to path for env loading
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import requests
except ImportError:
    print("ERROR: requests library required. Install: pip install requests")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Optional: dotenv not required if variables are in environment
    pass

# SEC Configuration
SEC_API_BASE = "https://data.sec.gov/api/xbrl"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "McLeod Capital Research Engine 1.0 (mason@mcleodcapital.com)")

# CIK Mapping for portfolio companies
TICKER_TO_CIK = {
    "AAPL": "0000320193",
    "AMZN": "0001018724",
    "MU": "0000723125",
    "NVDA": "0001045810",
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "GOOG": "0001652044",
    "META": "0001326801",
    "TSLA": "0001618724",
    "JPM": "0000019617",
    "JNJ": "0000200406",
    "BA": "0000012927",
    "CVS": "0000884996",
    "C": "0000831001",
    "CRWD": "0001679900",
    "DDOG": "0001618432",
    "FISV": "0000798354",
    "NBIS": "0001494215",
    "RKLB": "0001871238",
    "ARTV": "0001872362",
    "TGTX": "0001575136",
    "ANET": "0001606841",
    "APLD": "0000816709",
    "MELI": "0001391735",
    "MOG.A": "0001579821",
    "SPCX": "0001881839",
    "VMD": "0000858031",
    "AGX": "0001081869",
    "VBNK": "0001412957",
    "OPRA": "0001657797",
}

# XBRL Tags for key financial metrics
XBRL_CONCEPTS = {
    "revenue": "Revenues",
    "gross_profit": "GrossProfit",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "assets": "Assets",
    "current_assets": "AssetsCurrent",
    "liabilities": "Liabilities",
    "current_liabilities": "LiabilitiesCurrent",
    "equity": "StockholdersEquity",
    "long_term_debt": "LongTermDebt",
    "operating_cash_flow": "OperatingActivitiesCashFlows",
    "capex": "PaymentsForCapitalExpenditures",
    "shares_outstanding": "EntityCommonStockSharesOutstanding",
    "eps_basic": "EarningsPerShareBasic",
}


class SECDataSource:
    """
    SEC EDGAR financial data extraction using official SEC XBRL APIs.
    No external dependencies beyond requests library.
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize SEC data source."""
        self.cache_dir = cache_dir or Path.home() / ".sec_cache"
        self.cache_dir.mkdir(exist_ok=True, parents=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": SEC_USER_AGENT})
        self.metrics_cache = {}
        self.dynamic_ticker_to_cik = None

    def _load_sec_ticker_map(self, force_refresh: bool = False) -> Dict[str, str]:
        """Load SEC ticker-to-CIK map from SEC-maintained list (cached locally)."""
        if self.dynamic_ticker_to_cik is not None and not force_refresh:
            return self.dynamic_ticker_to_cik

        cache_file = self.cache_dir / "sec_company_tickers.json"
        ticker_map: Dict[str, str] = {}

        if not force_refresh and cache_file.exists():
            try:
                with open(cache_file) as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    ticker_map = payload
            except Exception:
                ticker_map = {}

        if not ticker_map:
            try:
                response = self.session.get(SEC_TICKERS_URL, timeout=30)
                response.raise_for_status()
                data = response.json()

                # SEC payload shape: {"0": {"ticker": "AAPL", "cik_str": 320193, ...}, ...}
                if isinstance(data, dict):
                    for item in data.values():
                        if not isinstance(item, dict):
                            continue
                        ticker = str(item.get("ticker", "")).upper().strip()
                        cik_raw = item.get("cik_str")
                        if ticker and cik_raw is not None:
                            try:
                                ticker_map[ticker] = f"{int(cik_raw):010d}"
                            except (ValueError, TypeError):
                                continue

                if ticker_map:
                    with open(cache_file, "w") as f:
                        json.dump(ticker_map, f, indent=2)
            except Exception:
                # Keep fallback behavior via static map below.
                pass

        self.dynamic_ticker_to_cik = ticker_map
        return ticker_map

    def _get_latest_from_concepts(
        self,
        facts: Dict,
        concepts: List[str],
        preferred_units: Optional[List[str]] = None,
    ) -> Optional[Tuple[float, str]]:
        """Return latest value using first concept that yields annual data."""
        for concept in concepts:
            value = self._get_latest_value(facts, concept, preferred_units=preferred_units)
            if value:
                return value
        return None

    def _get_history_from_concepts(
        self,
        facts: Dict,
        concepts: List[str],
        preferred_units: Optional[List[str]] = None,
    ) -> Optional[List[Tuple[float, str]]]:
        """Return annual history using first concept that yields data."""
        for concept in concepts:
            values = self._get_values_by_period(facts, concept, preferred_units=preferred_units)
            if values:
                return values
        return None

    @staticmethod
    def _select_unit_data(units: Dict[str, Any], preferred_units: Optional[List[str]]) -> List[Dict[str, Any]]:
        """
        Select SEC unit arrays in priority order.

        Preferred unit entries can be exact matches (e.g. "USD") or prefix matches
        using a trailing asterisk (e.g. "USD/").
        """
        if not units:
            return []

        selected: List[Dict[str, Any]] = []

        if preferred_units:
            for preferred in preferred_units:
                if preferred.endswith("*"):
                    prefix = preferred[:-1]
                    for unit_name, data in units.items():
                        if unit_name.startswith(prefix):
                            selected.extend(data)
                elif preferred in units:
                    selected.extend(units[preferred])

        # Fallback: include all units if preferred units are unavailable.
        if not selected:
            for data in units.values():
                selected.extend(data)

        return selected
    
    def get_cik_for_ticker(self, ticker: str) -> Optional[str]:
        """Get CIK for a ticker."""
        normalized = ticker.upper().strip()
        sec_normalized = normalized.replace(".", "-")

        ticker_map = self._load_sec_ticker_map()
        if sec_normalized in ticker_map:
            return ticker_map[sec_normalized]
        if normalized in ticker_map:
            return ticker_map[normalized]

        # Static map remains as a fallback for any non-standard symbols.
        return TICKER_TO_CIK.get(normalized)
    
    def fetch_companyfacts(self, cik: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Fetch company facts from SEC EDGAR API.
        
        Args:
            cik: 10-digit CIK number (with leading zeros)
            force_refresh: Force refetch even if cached
        
        Returns:
            Company facts dictionary or None if error
        """
        cache_file = self.cache_dir / f"facts_{cik}.json"
        
        # Return cached if available and not forcing refresh
        if not force_refresh and cache_file.exists():
            try:
                with open(cache_file) as f:
                    return json.load(f)
            except Exception as e:
                pass
        
        # Fetch from SEC API
        try:
            # Format CIK with leading zeros for URL (SEC API expects CIK0000723125 format)
            cik_formatted = f"CIK{cik}"
            url = f"{SEC_API_BASE}/companyfacts/{cik_formatted}.json"
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Cache the results
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            return data
        
        except requests.exceptions.RequestException as e:
            print(f"  ✗ Error fetching {cik}: {e}")
            return None
        except Exception as e:
            print(f"  ✗ Unexpected error for {cik}: {e}")
            return None
    
    def _get_latest_value(
        self,
        facts: Dict,
        concept: str,
        preferred_units: Optional[List[str]] = None,
    ) -> Optional[Tuple[float, str]]:
        """
        Get the latest value for a concept from company facts.
        Filters for consolidated full-year data from 10-K filings.
        Deduplicates by fiscal year, selecting most recent filing date.
        
        Returns:
            Tuple of (value, end_date) or None
        """
        try:
            if "facts" not in facts or "us-gaap" not in facts["facts"]:
                return None
            
            gaap_facts = facts["facts"]["us-gaap"]
            if concept not in gaap_facts:
                return None
            
            concept_data = gaap_facts[concept]
            if "units" not in concept_data:
                return None
            
            units = concept_data.get("units", {})
            unit_data = self._select_unit_data(units, preferred_units or ["USD"])

            if not unit_data:
                return None
            
            # Filter for annual (FY) data without quarters (Q1, Q2, Q3, Q4)
            annual_values = {}  # Dict keyed by end_date to deduplicate
            for item in unit_data:
                form = (item.get("form") or "").upper()  # Handle None
                fp = (item.get("fp") or "").upper()  # FY = Fiscal Year
                frame = item.get("frame", "")    # e.g., "CY2025" not "CY2025Q1"
                val = item.get("val")
                end_date = item.get("end")
                filed = item.get("filed", "")
                
                # Keep 10-K forms that are full fiscal years (not quarters)
                if "10-K" in form and fp == "FY" and val is not None and end_date:
                    # Make sure frame doesn't include quarter markers (or frame is None which is OK)
                    frame_is_annual = (frame is None or 
                                     (isinstance(frame, str) and 
                                      "Q1" not in frame and "Q2" not in frame and 
                                      "Q3" not in frame and "Q4" not in frame))
                    if frame_is_annual:
                        try:
                            val_float = float(val)
                            # Keep latest filing for each end_date (fiscal year)
                            if end_date not in annual_values or filed > annual_values[end_date][1]:
                                annual_values[end_date] = (val_float, filed)
                        except (ValueError, TypeError):
                            pass
            
            # Get most recent by end date
            if annual_values:
                # Sort by end_date and get the last one
                sorted_dates = sorted(annual_values.keys())
                latest_date = sorted_dates[-1]
                latest_value = annual_values[latest_date][0]
                return (latest_value, latest_date)
            
            return None
        
        except Exception:
            return None
    
    def _get_values_by_period(
        self,
        facts: Dict,
        concept: str,
        periods: int = 1,
        preferred_units: Optional[List[str]] = None,
    ) -> Optional[List[Tuple[float, str]]]:
        """
        Get multiple values for a concept (for growth calculations).
        Filters for consolidated full-year data from 10-K filings.
        
        Returns:
            List of [(value, end_date), ...] sorted by date
        """
        try:
            if "facts" not in facts or "us-gaap" not in facts["facts"]:
                return None
            
            gaap_facts = facts["facts"]["us-gaap"]
            if concept not in gaap_facts:
                return None
            
            concept_data = gaap_facts[concept]
            if "units" not in concept_data:
                return None
            
            units = concept_data.get("units", {})
            unit_data = self._select_unit_data(units, preferred_units or ["USD"])

            if not unit_data:
                return None
            
            # Filter for annual full-year 10-K data only
            annual_values = {}  # Dict keyed by end_date to deduplicate
            for item in unit_data:
                form = (item.get("form") or "").upper()  # Handle None
                fp = (item.get("fp") or "").upper()  # Handle None
                frame = item.get("frame", "")
                val = item.get("val")
                end_date = item.get("end")
                filed = item.get("filed", "")
                
                # Keep only 10-K full fiscal year entries
                if "10-K" in form and fp == "FY" and val is not None and end_date:
                    # Make sure frame doesn't include quarter markers (or frame is None which is OK)
                    frame_is_annual = (frame is None or 
                                     (isinstance(frame, str) and 
                                      "Q1" not in frame and "Q2" not in frame and 
                                      "Q3" not in frame and "Q4" not in frame))
                    if frame_is_annual:
                        try:
                            val_float = float(val)
                            # Keep latest filing for each end_date
                            if end_date not in annual_values or filed > annual_values[end_date][1]:
                                annual_values[end_date] = (val_float, filed)
                        except (ValueError, TypeError):
                            pass
            
            # Convert to list and sort by date
            result = sorted([(val, end_date) for end_date, (val, filed) in annual_values.items()], key=lambda x: x[1])
            
            return result if result else None
        
        except Exception:
            return None
    
    def calculate_metrics(self, symbol: str, facts: Dict) -> Dict[str, Any]:
        """
        Calculate all financial metrics from company facts.
        
        Args:
            symbol: Stock ticker
            facts: Company facts dictionary from SEC API
        
        Returns:
            Dictionary of metrics
        """
        metrics = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "cik": facts.get("cik"),
            "entity_name": facts.get("entityName"),
        }
        
        # Get latest annual values (for most recent fiscal year)
        revenue_latest = self._get_latest_from_concepts(
            facts,
            [
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet",
            ],
        )
        net_income_latest = self._get_latest_from_concepts(facts, ["NetIncomeLoss"])
        gross_profit_latest = self._get_latest_from_concepts(facts, ["GrossProfit"])
        operating_income_latest = self._get_latest_from_concepts(facts, ["OperatingIncomeLoss"])
        assets_latest = self._get_latest_from_concepts(facts, ["Assets"])
        liabilities_latest = self._get_latest_from_concepts(facts, ["Liabilities"])
        equity_latest = self._get_latest_from_concepts(
            facts,
            [
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ],
        )
        ocf_latest = self._get_latest_from_concepts(
            facts,
            [
                "OperatingActivitiesCashFlows",
                "NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            ],
        )
        capex_latest = self._get_latest_from_concepts(
            facts,
            [
                "PaymentsForCapitalExpenditures",
                "PaymentsToAcquirePropertyPlantAndEquipment",
            ],
        )
        long_term_debt_latest = self._get_latest_from_concepts(
            facts,
            [
                "LongTermDebt",
                "LongTermDebtNoncurrent",
                "LongTermDebtAndCapitalLeaseObligations",
            ],
        )
        current_assets_latest = self._get_latest_from_concepts(facts, ["AssetsCurrent"])
        current_liabilities_latest = self._get_latest_from_concepts(facts, ["LiabilitiesCurrent"])
        cash_latest = self._get_latest_from_concepts(facts, ["CashAndCashEquivalentsAtCarryingValue"])
        inventories_latest = self._get_latest_from_concepts(facts, ["Inventories"])
        eps_basic_latest = self._get_latest_from_concepts(
            facts,
            ["EarningsPerShareBasic", "EarningsPerShareDiluted"],
            preferred_units=["USD/shares", "USD/share", "USD/*", "pure"],
        )

        # Derive liabilities when issuer does not report a standalone Liabilities fact.
        if not liabilities_latest and assets_latest and equity_latest:
            derived_liabilities = assets_latest[0] - equity_latest[0]
            if derived_liabilities > 0:
                liabilities_latest = (derived_liabilities, assets_latest[1])
        
        # Store raw values
        if revenue_latest:
            metrics["revenue"] = revenue_latest[0]
            metrics["revenue_date"] = revenue_latest[1]
        if net_income_latest:
            metrics["net_income"] = net_income_latest[0]
            metrics["net_income_date"] = net_income_latest[1]
        if eps_basic_latest:
            metrics["eps_basic"] = eps_basic_latest[0]
            metrics["eps_basic_date"] = eps_basic_latest[1]
        if gross_profit_latest:
            metrics["gross_profit"] = gross_profit_latest[0]
        if operating_income_latest:
            metrics["operating_income"] = operating_income_latest[0]
        if assets_latest:
            metrics["total_assets"] = assets_latest[0]
        if liabilities_latest:
            metrics["total_liabilities"] = liabilities_latest[0]
        if equity_latest:
            metrics["shareholder_equity"] = equity_latest[0]
        if ocf_latest:
            metrics["operating_cash_flow"] = ocf_latest[0]
        if capex_latest:
            metrics["capex"] = abs(capex_latest[0]) if capex_latest[0] < 0 else capex_latest[0]
        if long_term_debt_latest:
            metrics["long_term_debt"] = long_term_debt_latest[0]
        if current_assets_latest:
            metrics["current_assets"] = current_assets_latest[0]
        if current_liabilities_latest:
            metrics["current_liabilities"] = current_liabilities_latest[0]
        
        # Calculate derived metrics
        
        # Margins
        if revenue_latest and revenue_latest[0] > 0 and gross_profit_latest:
            gross_margin = (gross_profit_latest[0] / revenue_latest[0]) * 100
            metrics["gross_margin"] = round(gross_margin, 2)
        
        if revenue_latest and revenue_latest[0] > 0 and operating_income_latest:
            operating_margin = (operating_income_latest[0] / revenue_latest[0]) * 100
            metrics["operating_margin"] = round(operating_margin, 2)
        
        if revenue_latest and revenue_latest[0] > 0 and net_income_latest:
            net_margin = (net_income_latest[0] / revenue_latest[0]) * 100
            metrics["net_margin"] = round(net_margin, 2)
        
        # Returns
        if equity_latest and equity_latest[0] > 0 and net_income_latest:
            roe = (net_income_latest[0] / equity_latest[0]) * 100
            metrics["roe"] = round(roe, 2)
        
        if assets_latest and assets_latest[0] > 0 and net_income_latest:
            roa = (net_income_latest[0] / assets_latest[0]) * 100
            metrics["roa"] = round(roa, 2)
        
        # Liquidity
        if current_assets_latest and current_liabilities_latest and current_liabilities_latest[0] > 0:
            current_ratio = current_assets_latest[0] / current_liabilities_latest[0]
            metrics["current_ratio"] = round(current_ratio, 2)
        
        # Leverage
        if equity_latest and equity_latest[0] > 0:
            debt_value = None
            if long_term_debt_latest:
                debt_value = long_term_debt_latest[0]
            elif liabilities_latest:
                debt_value = liabilities_latest[0]

            if debt_value is not None:
                debt_to_equity = debt_value / equity_latest[0]
                metrics["debt_to_equity"] = round(debt_to_equity, 2)

        # Net debt
        if long_term_debt_latest and cash_latest:
            metrics["net_debt"] = round(long_term_debt_latest[0] - cash_latest[0], 2)

        # Quick ratio
        if current_assets_latest and current_liabilities_latest and current_liabilities_latest[0] > 0:
            inventory = inventories_latest[0] if inventories_latest else 0.0
            quick_assets = current_assets_latest[0] - inventory
            if quick_assets > 0:
                metrics["quick_ratio"] = round(quick_assets / current_liabilities_latest[0], 2)
        
        # Growth rates (compare to prior year)
        revenue_history = self._get_history_from_concepts(
            facts,
            [
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet",
            ],
        )
        if revenue_history and len(revenue_history) >= 2:
            latest_rev = revenue_history[-1][0]
            prior_rev = revenue_history[-2][0]
            if prior_rev > 0:
                rev_growth = ((latest_rev / prior_rev) - 1) * 100
                metrics["revenue_growth_1yr"] = round(rev_growth, 2)

        if revenue_history and len(revenue_history) >= 4:
            latest_rev = revenue_history[-1][0]
            rev_3yr_ago = revenue_history[-4][0]
            if rev_3yr_ago > 0 and latest_rev > 0:
                rev_cagr_3yr = ((latest_rev / rev_3yr_ago) ** (1 / 3) - 1) * 100
                metrics["revenue_growth_3yr"] = round(rev_cagr_3yr, 2)
        
        net_income_history = self._get_history_from_concepts(facts, ["NetIncomeLoss"])
        if net_income_history and len(net_income_history) >= 2:
            latest_ni = net_income_history[-1][0]
            prior_ni = net_income_history[-2][0]
            if prior_ni > 0:
                ni_growth = ((latest_ni / prior_ni) - 1) * 100
                metrics["net_income_growth_1yr"] = round(ni_growth, 2)

        eps_history = self._get_history_from_concepts(
            facts,
            ["EarningsPerShareBasic", "EarningsPerShareDiluted"],
            preferred_units=["USD/shares", "USD/share", "USD/*", "pure"],
        )
        if eps_history and len(eps_history) >= 2:
            latest_eps = eps_history[-1][0]
            prior_eps = eps_history[-2][0]
            if prior_eps > 0:
                eps_growth = ((latest_eps / prior_eps) - 1) * 100
                metrics["eps_growth_1yr"] = round(eps_growth, 2)

        if eps_history and len(eps_history) >= 4:
            latest_eps = eps_history[-1][0]
            eps_3yr_ago = eps_history[-4][0]
            if eps_3yr_ago > 0 and latest_eps > 0:
                eps_cagr_3yr = ((latest_eps / eps_3yr_ago) ** (1 / 3) - 1) * 100
                metrics["eps_growth_3yr"] = round(eps_cagr_3yr, 2)
        
        # Free cash flow
        if ocf_latest and capex_latest:
            fcf = ocf_latest[0] - capex_latest[0]
            metrics["free_cash_flow"] = round(fcf, 2)
            metrics["free_cash_flow_1yr"] = round(fcf, 2)
            
            if revenue_latest and revenue_latest[0] > 0:
                fcf_margin = (fcf / revenue_latest[0]) * 100
                metrics["fcf_margin"] = round(fcf_margin, 2)

        # Free cash flow growth (1Y)
        ocf_history = self._get_history_from_concepts(
            facts,
            [
                "OperatingActivitiesCashFlows",
                "NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            ],
        )
        capex_history = self._get_history_from_concepts(
            facts,
            [
                "PaymentsForCapitalExpenditures",
                "PaymentsToAcquirePropertyPlantAndEquipment",
            ],
        )
        if ocf_history and capex_history:
            ocf_by_date = {d: v for v, d in ocf_history}
            capex_by_date = {d: abs(v) for v, d in capex_history}
            aligned_dates = sorted(set(ocf_by_date.keys()) & set(capex_by_date.keys()))
            if len(aligned_dates) >= 2:
                latest_date = aligned_dates[-1]
                prior_date = aligned_dates[-2]
                latest_fcf = ocf_by_date[latest_date] - capex_by_date[latest_date]
                prior_fcf = ocf_by_date[prior_date] - capex_by_date[prior_date]
                if prior_fcf > 0:
                    fcf_growth = ((latest_fcf / prior_fcf) - 1) * 100
                    metrics["free_cash_flow_growth"] = round(fcf_growth, 2)

        # ROIC approximation from available annual values.
        if operating_income_latest and equity_latest:
            invested_capital = equity_latest[0]
            if long_term_debt_latest:
                invested_capital += long_term_debt_latest[0]
            if invested_capital > 0:
                nopat = operating_income_latest[0] * (1 - 0.21)
                metrics["roic"] = round((nopat / invested_capital) * 100, 2)
        
        return metrics
    
    def get_financial_metric(
        self,
        symbol: str,
        metric: str,
        position_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get SEC financial metric for a symbol.
        
        Args:
            symbol: Stock ticker
            metric: Metric name
            position_data: Optional position data
        
        Returns:
            Dict with value, source, timestamp, confidence, stale_flag
        """
        result = {
            "value": "NEEDS_RESEARCH",
            "source": "SEC EDGAR",
            "timestamp": datetime.now().isoformat(),
            "confidence": 0,
            "stale": False,
        }
        
        try:
            # Reuse previously computed metrics for this symbol to avoid repeated SEC calls.
            cached_symbol_metrics = self.metrics_cache.get(symbol)
            if cached_symbol_metrics is not None:
                if "__error__" in cached_symbol_metrics:
                    result["reason"] = cached_symbol_metrics["__error__"]
                    return result
                if metric in cached_symbol_metrics and cached_symbol_metrics[metric] is not None:
                    result["value"] = cached_symbol_metrics[metric]
                    result["confidence"] = 95
                    return result

            # Get CIK for ticker
            cik = self.get_cik_for_ticker(symbol)
            if not cik:
                result["reason"] = f"CIK not found for {symbol}"
                self.metrics_cache[symbol] = {"__error__": result["reason"]}
                return result
            
            # Fetch company facts
            facts = self.fetch_companyfacts(cik)
            if not facts:
                result["reason"] = f"Failed to fetch facts for {symbol}"
                self.metrics_cache[symbol] = {"__error__": result["reason"]}
                return result
            
            # Calculate metrics
            metrics = self.calculate_metrics(symbol, facts)
            self.metrics_cache[symbol] = metrics
            
            # Get requested metric
            if metric in metrics:
                value = metrics[metric]
                if value is not None:
                    result["value"] = value
                    result["confidence"] = 95  # SEC data is highly reliable
                    return result
            
            result["reason"] = f"Metric {metric} not calculated"
            return result
        
        except Exception as e:
            result["reason"] = f"Error: {str(e)}"
            return result
    
    def fetch_all_metrics(self, symbols: list) -> Dict[str, Dict]:
        """
        Fetch all metrics for multiple symbols.
        
        Args:
            symbols: List of tickers
        
        Returns:
            Dictionary of symbol -> metrics
        """
        all_metrics = {}
        
        for symbol in symbols:
            print(f"  Fetching SEC data for {symbol}...", end=" ", flush=True)
            
            try:
                cik = self.get_cik_for_ticker(symbol)
                if not cik:
                    print(f"✗ (CIK not found)")
                    continue
                
                facts = self.fetch_companyfacts(cik)
                if not facts:
                    print(f"✗ (API error)")
                    continue
                
                metrics = self.calculate_metrics(symbol, facts)
                all_metrics[symbol] = metrics
                print("✓")
                time.sleep(0.5)  # Rate limiting
            
            except Exception as e:
                print(f"✗ ({e})")
        
        return all_metrics


if __name__ == "__main__":
    print("✓ SEC Data Source (Official SEC EDGAR API)\n")
    
    # Test with MU and AMZN
    sec_source = SECDataSource()
    all_metrics = sec_source.fetch_all_metrics(["MU", "AMZN"])
    
    # Display results
    for symbol in ["MU", "AMZN"]:
        if symbol in all_metrics:
            metrics = all_metrics[symbol]
            print(f"\n{'='*70}")
            print(f"{symbol} - SEC Fundamentals")
            print(f"{'='*70}")
            
            print(f"\nRevenue & Profitability:")
            print(f"  Revenue: ${metrics.get('revenue', 'N/A'):,.0f}" if isinstance(metrics.get('revenue'), (int, float)) else f"  Revenue: {metrics.get('revenue', 'N/A')}")
            print(f"  Net Income: ${metrics.get('net_income', 'N/A'):,.0f}" if isinstance(metrics.get('net_income'), (int, float)) else f"  Net Income: {metrics.get('net_income', 'N/A')}")
            print(f"  Operating Cash Flow: ${metrics.get('operating_cash_flow', 'N/A'):,.0f}" if isinstance(metrics.get('operating_cash_flow'), (int, float)) else f"  Operating Cash Flow: {metrics.get('operating_cash_flow', 'N/A')}")
            print(f"  Capex: ${metrics.get('capex', 'N/A'):,.0f}" if isinstance(metrics.get('capex'), (int, float)) else f"  Capex: {metrics.get('capex', 'N/A')}")
            
            print(f"\nBalance Sheet:")
            print(f"  Total Assets: ${metrics.get('total_assets', 'N/A'):,.0f}" if isinstance(metrics.get('total_assets'), (int, float)) else f"  Total Assets: {metrics.get('total_assets', 'N/A')}")
            print(f"  Total Debt: ${metrics.get('long_term_debt', 'N/A'):,.0f}" if isinstance(metrics.get('long_term_debt'), (int, float)) else f"  Total Debt: {metrics.get('long_term_debt', 'N/A')}")
            print(f"  Shareholder Equity: ${metrics.get('shareholder_equity', 'N/A'):,.0f}" if isinstance(metrics.get('shareholder_equity'), (int, float)) else f"  Shareholder Equity: {metrics.get('shareholder_equity', 'N/A')}")
            
            print(f"\nMargins & Returns:")
            print(f"  Gross Margin: {metrics.get('gross_margin', 'N/A')}%" if 'gross_margin' in metrics else f"  Gross Margin: N/A")
            print(f"  Operating Margin: {metrics.get('operating_margin', 'N/A')}%" if 'operating_margin' in metrics else f"  Operating Margin: N/A")
            print(f"  Net Margin: {metrics.get('net_margin', 'N/A')}%" if 'net_margin' in metrics else f"  Net Margin: N/A")
            print(f"  ROE: {metrics.get('roe', 'N/A')}%" if 'roe' in metrics else f"  ROE: N/A")
            print(f"  ROA: {metrics.get('roa', 'N/A')}%" if 'roa' in metrics else f"  ROA: N/A")
            
            print(f"\nRatios & Growth:")
            print(f"  Current Ratio: {metrics.get('current_ratio', 'N/A')}" if 'current_ratio' in metrics else f"  Current Ratio: N/A")
            print(f"  Debt-to-Equity: {metrics.get('debt_to_equity', 'N/A')}" if 'debt_to_equity' in metrics else f"  Debt-to-Equity: N/A")
            print(f"  Revenue Growth (1Y): {metrics.get('revenue_growth_1yr', 'N/A')}%" if 'revenue_growth_1yr' in metrics else f"  Revenue Growth (1Y): N/A")
            print(f"  Net Income Growth (1Y): {metrics.get('net_income_growth_1yr', 'N/A')}%" if 'net_income_growth_1yr' in metrics else f"  Net Income Growth (1Y): N/A")
            print(f"  FCF Margin: {metrics.get('fcf_margin', 'N/A')}%" if 'fcf_margin' in metrics else f"  FCF Margin: N/A")
    
    # Save to file
    output_file = Path("data/sec_fundamentals_latest.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(all_metrics, f, indent=2, default=str)
    print(f"\n✓ Saved to {output_file}")

    # Save validation report
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    validation_file = reports_dir / "sec_parser_validation.md"

    def has_real_fundamentals(metrics: Dict[str, Any]) -> bool:
        required = ["revenue", "net_income", "operating_cash_flow", "gross_margin", "roe", "debt_to_equity"]
        return all(metrics.get(k) not in (None, "N/A", "NEEDS_RESEARCH") for k in required)

    lines = []
    lines.append("# SEC Parser Validation")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Symbol Validation")

    for symbol in ["MU", "AMZN"]:
        metrics = all_metrics.get(symbol, {})
        status = "PASS" if has_real_fundamentals(metrics) else "FAIL"
        lines.append(f"### {symbol}: {status}")
        lines.append(f"- Revenue: {metrics.get('revenue', 'N/A')}")
        lines.append(f"- Net Income: {metrics.get('net_income', 'N/A')}")
        lines.append(f"- Operating Cash Flow: {metrics.get('operating_cash_flow', 'N/A')}")
        lines.append(f"- Gross Margin: {metrics.get('gross_margin', 'N/A')}")
        lines.append(f"- ROE: {metrics.get('roe', 'N/A')}")
        lines.append(f"- Debt-to-Equity: {metrics.get('debt_to_equity', 'N/A')}")
        lines.append("")

    with open(validation_file, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"✓ SEC parser validation report saved to {validation_file}")
