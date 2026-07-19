#!/usr/bin/env python3
"""SEC-derived earnings quality source.

Builds raw earnings-quality metrics from official SEC XBRL company facts using
annual filing periods to avoid quarter/YTD double counting.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.data_sources.sec_source import SECDataSource


WORKSPACE = Path(__file__).parent.parent.parent
DATA_DIR = WORKSPACE / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_FILE = CACHE_DIR / "earnings_quality_source_cache.json"


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, "", "NA", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class EarningsQualitySource:
    """Compute raw earnings-quality metrics from SEC facts."""

    def __init__(self):
        self.name = "SEC XBRL Earnings Quality"
        self.confidence_base = 92
        self.cache_ttl_hours = 24
        self.sec = SECDataSource()
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if not CACHE_FILE.exists():
            return {}
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                payload = json.load(f)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_cache(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    def _cache_is_fresh(self, ts: str) -> bool:
        try:
            dt = datetime.fromisoformat(ts)
            age_hours = (datetime.now() - dt).total_seconds() / 3600.0
            return age_hours <= self.cache_ttl_hours
        except Exception:
            return False

    def _annual_entries(
        self,
        facts: Dict[str, Any],
        concepts: List[str],
        preferred_units: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        gaap = (facts.get("facts") or {}).get("us-gaap") or {}
        entries: Dict[str, Dict[str, Any]] = {}

        for concept in concepts:
            concept_data = gaap.get(concept) or {}
            units = concept_data.get("units") or {}
            unit_rows = self.sec._select_unit_data(units, preferred_units or ["USD"])
            for item in unit_rows:
                form = str(item.get("form") or "").upper()
                fp = str(item.get("fp") or "").upper()
                frame = item.get("frame")
                val = item.get("val")
                end = str(item.get("end") or "")
                filed = str(item.get("filed") or "")
                accn = str(item.get("accn") or "")
                if "10-K" not in form or fp != "FY" or not end or val is None:
                    continue
                if isinstance(frame, str) and any(q in frame for q in ["Q1", "Q2", "Q3", "Q4"]):
                    continue
                val_f = _to_float(val, None)
                if val_f is None:
                    continue
                current = entries.get(end)
                if current is None or filed > str(current.get("filed") or ""):
                    entries[end] = {
                        "concept": concept,
                        "value": val_f,
                        "end": end,
                        "filed": filed,
                        "accn": accn,
                        "form": form,
                    }
            if entries:
                break

        return [entries[k] for k in sorted(entries.keys())]

    @staticmethod
    def _latest(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return rows[-1] if rows else None

    @staticmethod
    def _pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
        if curr is None or prev is None or prev == 0:
            return None
        return ((curr / prev) - 1.0) * 100.0

    @staticmethod
    def _cagr(curr: Optional[float], prev: Optional[float], years: int) -> Optional[float]:
        if curr is None or prev is None or prev <= 0 or curr <= 0 or years <= 0:
            return None
        return ((curr / prev) ** (1 / years) - 1.0) * 100.0

    def fetch_symbol(self, symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
        symbol = str(symbol or "").upper().strip()
        now_iso = datetime.now().isoformat()
        if not symbol:
            return {"symbol": symbol, "timestamp": now_iso, "source": self.name, "stale": True, "confidence": 0, "data": {}}

        cached = self.cache.get(symbol)
        if cached and not force_refresh and self._cache_is_fresh(str(cached.get("timestamp", ""))):
            return {"symbol": symbol, "timestamp": cached.get("timestamp", now_iso), "source": self.name, "stale": False, "confidence": int(cached.get("confidence", self.confidence_base)), "data": cached.get("data", {})}

        cik = self.sec.get_cik_for_ticker(symbol)
        if not cik:
            return {"symbol": symbol, "timestamp": now_iso, "source": self.name, "stale": True, "confidence": 0, "data": {}}

        facts = self.sec.fetch_companyfacts(cik)
        if not facts:
            if cached:
                return {"symbol": symbol, "timestamp": cached.get("timestamp", now_iso), "source": self.name, "stale": True, "confidence": max(25, int(cached.get("confidence", self.confidence_base)) - 20), "data": cached.get("data", {})}
            return {"symbol": symbol, "timestamp": now_iso, "source": self.name, "stale": True, "confidence": 0, "data": {}}

        revenue_hist = self._annual_entries(facts, ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"])
        net_income_hist = self._annual_entries(facts, ["NetIncomeLoss"])
        ocf_hist = self._annual_entries(facts, ["OperatingActivitiesCashFlows", "NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"])
        capex_hist = self._annual_entries(facts, ["PaymentsForCapitalExpenditures", "PaymentsToAcquirePropertyPlantAndEquipment"])
        assets_hist = self._annual_entries(facts, ["Assets"])
        receivables_hist = self._annual_entries(facts, ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent", "AccountsNotesAndLoansReceivableNetCurrent"])
        inventory_hist = self._annual_entries(facts, ["InventoryNet", "InventoriesNetOfReserves", "Inventories"])
        payables_hist = self._annual_entries(facts, ["AccountsPayableCurrent", "AccountsPayableAndAccruedLiabilitiesCurrent"])
        deferred_rev_hist = self._annual_entries(facts, ["DeferredRevenueCurrent", "ContractWithCustomerLiabilityCurrent", "ContractWithCustomerLiability", "ContractLiabilities"])
        sbc_hist = self._annual_entries(facts, ["ShareBasedCompensation", "StockBasedCompensation"])
        software_cap_hist = self._annual_entries(facts, ["CapitalizedComputerSoftwareNet", "CapitalizedSoftwareDevelopmentCosts", "DeferredContractAcquisitionCosts"])
        restructuring_hist = self._annual_entries(facts, ["RestructuringCharges", "RestructuringReserve", "EmployeeTerminationBenefits"])
        diluted_shares_hist = self._annual_entries(facts, ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"], preferred_units=["shares", "pure"])
        interest_expense_hist = self._annual_entries(facts, ["InterestExpenseAndOther", "InterestExpense"])
        debt_hist = self._annual_entries(facts, ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"])
        cash_hist = self._annual_entries(facts, ["CashAndCashEquivalentsAtCarryingValue"])
        buyback_hist = self._annual_entries(facts, ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"])
        issuance_hist = self._annual_entries(facts, ["ProceedsFromIssuanceOfCommonStock", "ProceedsFromStockOptionsExercised", "ProceedsFromIssuanceOfCommonShares"])
        acquisitions_hist = self._annual_entries(facts, ["PaymentsToAcquireBusinessesNetOfCashAcquired", "BusinessAcquisitionCostOfAcquiredEntityTransactionCosts"])
        eps_diluted_hist = self._annual_entries(facts, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], preferred_units=["USD/shares", "USD/share", "USD/*", "pure"])

        latest_rev = self._latest(revenue_hist)
        latest_ni = self._latest(net_income_hist)
        latest_ocf = self._latest(ocf_hist)
        latest_capex = self._latest(capex_hist)
        latest_assets = self._latest(assets_hist)
        latest_receivables = self._latest(receivables_hist)
        latest_inventory = self._latest(inventory_hist)
        latest_payables = self._latest(payables_hist)
        latest_defrev = self._latest(deferred_rev_hist)
        latest_sbc = self._latest(sbc_hist)
        latest_softcap = self._latest(software_cap_hist)
        latest_restruct = self._latest(restructuring_hist)
        latest_shares = self._latest(diluted_shares_hist)
        latest_interest = self._latest(interest_expense_hist)
        latest_debt = self._latest(debt_hist)
        latest_cash = self._latest(cash_hist)
        latest_buyback = self._latest(buyback_hist)
        latest_issuance = self._latest(issuance_hist)
        latest_acq = self._latest(acquisitions_hist)
        latest_eps = self._latest(eps_diluted_hist)

        data: Dict[str, Any] = {
            "sec_cik": cik,
            "latest_filing_date": (latest_rev or latest_ni or latest_assets or {}).get("filed", ""),
            "latest_accession_number": (latest_rev or latest_ni or latest_assets or {}).get("accn", ""),
        }

        rev = latest_rev["value"] if latest_rev else None
        ni = latest_ni["value"] if latest_ni else None
        ocf = latest_ocf["value"] if latest_ocf else None
        capex = abs(latest_capex["value"]) if latest_capex else None
        assets = latest_assets["value"] if latest_assets else None
        fcf = (ocf - capex) if ocf is not None and capex is not None else None
        sbc = latest_sbc["value"] if latest_sbc else None
        eps = latest_eps["value"] if latest_eps else None
        shares = latest_shares["value"] if latest_shares else None

        data["cash_conversion_ocf_net_income"] = (ocf / ni) if ocf is not None and ni not in (None, 0) else None
        data["cash_conversion_fcf_net_income"] = (fcf / ni) if fcf is not None and ni not in (None, 0) else None
        data["free_cash_flow_margin"] = ((fcf / rev) * 100.0) if fcf is not None and rev not in (None, 0) else None
        cash_eps = (ocf / shares) if ocf is not None and shares not in (None, 0) else None
        data["cash_eps"] = cash_eps
        data["cash_eps_vs_gaap_eps_gap"] = (cash_eps - eps) if cash_eps is not None and eps is not None else None

        if len(ocf_hist) >= 3 and len(net_income_hist) >= 3:
            ratios = []
            ni_by_end = {r["end"]: r["value"] for r in net_income_hist}
            for row in ocf_hist[-3:]:
                ni_val = ni_by_end.get(row["end"])
                if ni_val not in (None, 0):
                    ratios.append(row["value"] / ni_val)
            data["multi_year_cash_conversion_trend"] = (ratios[-1] - ratios[0]) if len(ratios) >= 2 else None

        avg_assets = None
        if len(assets_hist) >= 2:
            avg_assets = (assets_hist[-1]["value"] + assets_hist[-2]["value"]) / 2.0
        elif assets is not None:
            avg_assets = assets

        total_accruals = (ni - ocf) if ni is not None and ocf is not None else None
        data["total_accruals_avg_assets"] = (total_accruals / avg_assets) if total_accruals is not None and avg_assets not in (None, 0) else None
        data["sloan_accrual_ratio"] = data["total_accruals_avg_assets"]

        if len(receivables_hist) >= 2:
            data["change_receivables"] = latest_receivables["value"] - receivables_hist[-2]["value"] if latest_receivables else None
        if len(inventory_hist) >= 2:
            data["change_inventory"] = latest_inventory["value"] - inventory_hist[-2]["value"] if latest_inventory else None
        if len(payables_hist) >= 2:
            data["change_payables"] = latest_payables["value"] - payables_hist[-2]["value"] if latest_payables else None
        if len(deferred_rev_hist) >= 2:
            data["change_deferred_revenue"] = latest_defrev["value"] - deferred_rev_hist[-2]["value"] if latest_defrev else None

        wc_accrual_num = 0.0
        wc_has = False
        for key in ["change_receivables", "change_inventory", "change_payables", "change_deferred_revenue"]:
            val = data.get(key)
            if val is not None:
                wc_has = True
        if data.get("change_receivables") is not None:
            wc_accrual_num += data["change_receivables"]
        if data.get("change_inventory") is not None:
            wc_accrual_num += data["change_inventory"]
        if data.get("change_payables") is not None:
            wc_accrual_num -= data["change_payables"]
        if data.get("change_deferred_revenue") is not None:
            wc_accrual_num -= data["change_deferred_revenue"]
        data["working_capital_accruals"] = (wc_accrual_num / avg_assets) if wc_has and avg_assets not in (None, 0) else None

        if len(revenue_hist) >= 2 and len(receivables_hist) >= 2:
            rev_growth = self._pct_change(revenue_hist[-1]["value"], revenue_hist[-2]["value"])
            rec_growth = self._pct_change(receivables_hist[-1]["value"], receivables_hist[-2]["value"])
            data["receivables_growth_vs_revenue_growth"] = (rec_growth - rev_growth) if rev_growth is not None and rec_growth is not None else None
        if len(deferred_rev_hist) >= 2:
            data["deferred_revenue_growth"] = self._pct_change(deferred_rev_hist[-1]["value"], deferred_rev_hist[-2]["value"])
            data["contract_liability_growth"] = data["deferred_revenue_growth"]

        data["customer_concentration"] = None
        data["organic_vs_acquisition_growth"] = None

        data["stock_based_comp_pct_revenue"] = ((sbc / rev) * 100.0) if sbc is not None and rev not in (None, 0) else None
        data["stock_based_comp_pct_fcf"] = ((sbc / fcf) * 100.0) if sbc is not None and fcf not in (None, 0) else None
        data["capitalized_software_dev_costs"] = latest_softcap["value"] if latest_softcap else None
        data["restructuring_charges"] = latest_restruct["value"] if latest_restruct else None
        data["recurring_one_time_adjustments"] = None
        data["adjusted_eps_vs_gaap_gap"] = None

        data["capex_pct_revenue"] = ((capex / rev) * 100.0) if capex is not None and rev not in (None, 0) else None
        data["maintenance_vs_growth_capex"] = None
        data["free_cash_flow_after_sbc"] = (fcf - sbc) if fcf is not None and sbc is not None else None
        rev_growth_3yr = self._cagr(revenue_hist[-1]["value"], revenue_hist[-4]["value"], 3) if len(revenue_hist) >= 4 else None
        data["reinvestment_efficiency"] = (rev_growth_3yr / data["capex_pct_revenue"]) if rev_growth_3yr is not None and data.get("capex_pct_revenue") not in (None, 0) else None

        if len(diluted_shares_hist) >= 2:
            data["diluted_share_count_growth_1y"] = self._pct_change(diluted_shares_hist[-1]["value"], diluted_shares_hist[-2]["value"])
        if len(diluted_shares_hist) >= 4:
            data["diluted_share_count_growth_3y"] = self._cagr(diluted_shares_hist[-1]["value"], diluted_shares_hist[-4]["value"], 3)
        if len(diluted_shares_hist) >= 6:
            data["diluted_share_count_growth_5y"] = self._cagr(diluted_shares_hist[-1]["value"], diluted_shares_hist[-6]["value"], 5)
        data["buybacks_vs_stock_issuance"] = ((abs(latest_buyback["value"]) if latest_buyback else 0.0) - (latest_issuance["value"] if latest_issuance else 0.0))
        data["net_share_reduction_or_dilution"] = -data["diluted_share_count_growth_1y"] if data.get("diluted_share_count_growth_1y") is not None else None
        data["acquisition_related_issuance"] = None

        if len(debt_hist) >= 2 and len(cash_hist) >= 2:
            latest_net = (latest_debt["value"] if latest_debt else 0.0) - (latest_cash["value"] if latest_cash else 0.0)
            prior_net = debt_hist[-2]["value"] - cash_hist[-2]["value"]
            data["net_cash_or_net_debt_trend"] = latest_net - prior_net
        data["debt_funded_buybacks"] = None
        if latest_buyback and len(debt_hist) >= 2:
            debt_change = debt_hist[-1]["value"] - debt_hist[-2]["value"]
            if debt_change > 0 and abs(latest_buyback["value"]) > 0:
                data["debt_funded_buybacks"] = min(abs(latest_buyback["value"]), debt_change)
        data["debt_funded_acquisitions"] = None
        if latest_acq and len(debt_hist) >= 2:
            debt_change = debt_hist[-1]["value"] - debt_hist[-2]["value"]
            if debt_change > 0 and latest_acq["value"] > 0:
                data["debt_funded_acquisitions"] = min(latest_acq["value"], debt_change)
        data["interest_coverage"] = ((latest_ni["value"] + latest_interest["value"]) / latest_interest["value"]) if latest_ni and latest_interest and latest_interest["value"] not in (None, 0) else None
        data["off_balance_sheet_obligations"] = None

        self.cache[symbol] = {
            "timestamp": now_iso,
            "confidence": self.confidence_base,
            "data": data,
        }
        self._save_cache()

        return {
            "symbol": symbol,
            "timestamp": now_iso,
            "source": self.name,
            "stale": False,
            "confidence": self.confidence_base,
            "data": data,
        }
