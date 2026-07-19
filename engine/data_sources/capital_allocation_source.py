#!/usr/bin/env python3
"""SEC-derived capital allocation source."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.data_sources.sec_source import SECDataSource


WORKSPACE = Path(__file__).parent.parent.parent
DATA_DIR = WORKSPACE / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_FILE = CACHE_DIR / "capital_allocation_source_cache.json"
SUBMISSIONS_CACHE_FILE = CACHE_DIR / "capital_allocation_submissions_cache.json"


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, "", "NA", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class CapitalAllocationSource:
    """Compute raw capital-allocation metrics from SEC annual facts."""

    def __init__(self):
        self.name = "SEC XBRL Capital Allocation"
        self.confidence_base = 90
        self.cache_ttl_hours = 24
        self.sec = SECDataSource()
        self.cache = self._load_cache()
        self.submissions_cache = self._load_submissions_cache()

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

    def _load_submissions_cache(self) -> Dict[str, Any]:
        if not SUBMISSIONS_CACHE_FILE.exists():
            return {}
        try:
            with open(SUBMISSIONS_CACHE_FILE, encoding="utf-8") as f:
                payload = json.load(f)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_submissions_cache(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(SUBMISSIONS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.submissions_cache, f, indent=2)

    def _cache_is_fresh(self, ts: str) -> bool:
        try:
            dt = datetime.fromisoformat(ts)
            age_hours = (datetime.now() - dt).total_seconds() / 3600.0
            return age_hours <= self.cache_ttl_hours
        except Exception:
            return False

    def _annual_entries(self, facts: Dict[str, Any], concepts: List[str], preferred_units: Optional[List[str]] = None) -> List[Dict[str, Any]]:
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

    def _period_entries(
        self,
        facts: Dict[str, Any],
        concepts: List[str],
        forms: List[str],
        fps: Optional[List[str]] = None,
        preferred_units: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        gaap = (facts.get("facts") or {}).get("us-gaap") or {}
        entries: Dict[str, Dict[str, Any]] = {}
        forms_upper = {f.upper() for f in forms}
        fps_upper = {f.upper() for f in (fps or [])}

        for concept in concepts:
            concept_data = gaap.get(concept) or {}
            units = concept_data.get("units") or {}
            unit_rows = self.sec._select_unit_data(units, preferred_units or ["USD"])
            for item in unit_rows:
                form = str(item.get("form") or "").upper()
                fp = str(item.get("fp") or "").upper()
                val = item.get("val")
                end = str(item.get("end") or "")
                filed = str(item.get("filed") or "")
                accn = str(item.get("accn") or "")
                frame = item.get("frame")

                if form not in forms_upper or val is None or not end:
                    continue
                if fps_upper and fp not in fps_upper:
                    continue
                # Keep annual rows only when explicitly requested via FP=FY.
                if "FY" in fps_upper and isinstance(frame, str) and any(q in frame for q in ["Q1", "Q2", "Q3", "Q4"]):
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
                        "fp": fp,
                    }
            if entries:
                break

        return [entries[k] for k in sorted(entries.keys())]

    def _fetch_submissions(self, cik: str, force_refresh: bool = False) -> Dict[str, Any]:
        now_iso = datetime.now().isoformat()
        cache_row = self.submissions_cache.get(cik)
        if cache_row and not force_refresh and self._cache_is_fresh(str(cache_row.get("timestamp", ""))):
            return cache_row.get("data") or {}

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            resp = self.sec.session.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            data = payload if isinstance(payload, dict) else {}
            self.submissions_cache[cik] = {"timestamp": now_iso, "data": data}
            self._save_submissions_cache()
            return data
        except Exception:
            if cache_row:
                return cache_row.get("data") or {}
            return {}

    @staticmethod
    def _safe_ratio(n: Optional[float], d: Optional[float]) -> Optional[float]:
        if n is None or d in (None, 0):
            return None
        return n / d

    @staticmethod
    def _sum_values(rows: List[Dict[str, Any]], n: int) -> float:
        if not rows or n <= 0:
            return 0.0
        return float(sum((_to_float(r.get("value"), 0.0) or 0.0) for r in rows[-n:]))

    @staticmethod
    def _pct_of(n: Optional[float], d: Optional[float]) -> Optional[float]:
        if n is None or d in (None, 0):
            return None
        return (n / d) * 100.0

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
        if curr is None or prev is None or curr <= 0 or prev <= 0 or years <= 0:
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
        submissions = self._fetch_submissions(cik, force_refresh=force_refresh)
        if not facts:
            if cached:
                return {"symbol": symbol, "timestamp": cached.get("timestamp", now_iso), "source": self.name, "stale": True, "confidence": max(25, int(cached.get("confidence", self.confidence_base)) - 20), "data": cached.get("data", {})}
            return {"symbol": symbol, "timestamp": now_iso, "source": self.name, "stale": True, "confidence": 0, "data": {}}

        revenue_hist = self._annual_entries(facts, ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"])
        ni_hist = self._annual_entries(facts, ["NetIncomeLoss"])
        ocf_hist = self._annual_entries(facts, ["OperatingActivitiesCashFlows", "NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"])
        capex_hist = self._annual_entries(facts, ["PaymentsForCapitalExpenditures", "PaymentsToAcquirePropertyPlantAndEquipment"])
        op_income_hist = self._annual_entries(facts, ["OperatingIncomeLoss"])
        equity_hist = self._annual_entries(facts, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
        debt_hist = self._annual_entries(facts, ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"])
        cash_hist = self._annual_entries(facts, ["CashAndCashEquivalentsAtCarryingValue"])
        buyback_hist = self._annual_entries(facts, ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"])
        issuance_hist = self._annual_entries(facts, ["ProceedsFromIssuanceOfCommonStock", "ProceedsFromStockOptionsExercised", "ProceedsFromIssuanceOfCommonShares"])
        acq_hist = self._annual_entries(facts, ["PaymentsToAcquireBusinessesNetOfCashAcquired", "BusinessAcquisitionCostOfAcquiredEntityTransactionCosts"])
        shares_hist = self._annual_entries(facts, ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"], preferred_units=["shares", "pure"])
        shares_q_hist = self._period_entries(
            facts,
            ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
            forms=["10-Q", "10-K"],
            fps=["Q1", "Q2", "Q3", "FY"],
            preferred_units=["shares", "pure"],
        )
        shares_repur_q_hist = self._period_entries(
            facts,
            ["CommonStockSharesRepurchased", "TreasuryStockSharesAcquired"],
            forms=["10-Q", "10-K"],
            fps=["Q1", "Q2", "Q3", "FY"],
            preferred_units=["shares", "pure"],
        )
        buyback_q_hist = self._period_entries(
            facts,
            ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
            forms=["10-Q", "10-K"],
            fps=["Q1", "Q2", "Q3", "FY"],
            preferred_units=["USD", "USD/shares"],
        )
        retained_hist = self._annual_entries(facts, ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings"])
        dividends_hist = self._annual_entries(facts, ["PaymentsOfDividendsCommonStock", "DividendsCommonStockCash"])
        interest_hist = self._annual_entries(facts, ["InterestExpenseAndOther", "InterestExpense"])
        sbc_hist = self._annual_entries(facts, ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"])

        latest_rev = self._latest(revenue_hist)
        latest_ni = self._latest(ni_hist)
        latest_ocf = self._latest(ocf_hist)
        latest_capex = self._latest(capex_hist)
        latest_op = self._latest(op_income_hist)
        latest_eq = self._latest(equity_hist)
        latest_debt = self._latest(debt_hist)
        latest_cash = self._latest(cash_hist)
        latest_buyback = self._latest(buyback_hist)
        latest_issuance = self._latest(issuance_hist)
        latest_acq = self._latest(acq_hist)
        latest_shares = self._latest(shares_hist)
        latest_retained = self._latest(retained_hist)
        latest_dividends = self._latest(dividends_hist)
        latest_interest = self._latest(interest_hist)

        rev = latest_rev["value"] if latest_rev else None
        ni = latest_ni["value"] if latest_ni else None
        ocf = latest_ocf["value"] if latest_ocf else None
        capex = abs(latest_capex["value"]) if latest_capex else None
        op_inc = latest_op["value"] if latest_op else None
        equity = latest_eq["value"] if latest_eq else None
        debt = latest_debt["value"] if latest_debt else 0.0
        cash = latest_cash["value"] if latest_cash else 0.0
        shares = latest_shares["value"] if latest_shares else None
        buyback = abs(latest_buyback["value"]) if latest_buyback else 0.0
        issuance = latest_issuance["value"] if latest_issuance else 0.0
        acq = latest_acq["value"] if latest_acq else 0.0
        dividends = abs(latest_dividends["value"]) if latest_dividends else 0.0

        fcf = (ocf - capex) if ocf is not None and capex is not None else None
        owner_earnings = fcf
        invested_capital = (equity if equity is not None else 0.0) + debt - cash

        data: Dict[str, Any] = {
            "sec_cik": cik,
            "latest_filing_date": (latest_rev or latest_ni or latest_eq or {}).get("filed", ""),
            "latest_accession_number": (latest_rev or latest_ni or latest_eq or {}).get("accn", ""),
        }

        # Buyback intelligence defaults (set only when evidence exists; never invent values).
        buyback_defaults = {
            "capital_allocation_buyback_authorization_date": None,
            "capital_allocation_buyback_authorized_amount": None,
            "capital_allocation_buyback_remaining_authorization": None,
            "capital_allocation_buyback_authorization_expiration_date": None,
            "capital_allocation_buyback_board_approval_source": None,
            "capital_allocation_buyback_authorization_status": None,
            "capital_allocation_buyback_shares_repur_q": None,
            "capital_allocation_buyback_spend_q": None,
            "capital_allocation_buyback_avg_price_q": None,
            "capital_allocation_buyback_pct_market_cap_ttm": None,
            "capital_allocation_buyback_pct_shares_ttm": None,
            "capital_allocation_buyback_yield_ttm": None,
            "capital_allocation_buyback_spend_3y": None,
            "capital_allocation_buyback_spend_5y": None,
            "capital_allocation_buyback_basic_share_change_pct": None,
            "capital_allocation_buyback_diluted_share_change_pct": None,
            "capital_allocation_buyback_sbc_issuance": None,
            "capital_allocation_buyback_acquisition_issuance": None,
            "capital_allocation_buyback_option_exercise_issuance": None,
            "capital_allocation_buyback_net_diluted_share_reduction_pct": None,
            "capital_allocation_buyback_as_pct_sbc": None,
            "capital_allocation_buyback_as_pct_fcf": None,
            "capital_allocation_buyback_fcf_used": None,
            "capital_allocation_buyback_cash_balance_change": None,
            "capital_allocation_buyback_debt_issuance": None,
            "capital_allocation_buyback_net_debt_change": None,
            "capital_allocation_buyback_interest_coverage_change": None,
            "capital_allocation_buyback_debt_funded_flag": None,
            "capital_allocation_buyback_liquidity_strain_flag": None,
            "capital_allocation_buyback_avg_price_vs_current_pct": None,
            "capital_allocation_buyback_avg_price_vs_intrinsic_value_pct": None,
            "capital_allocation_buyback_execution_pe": None,
            "capital_allocation_buyback_execution_ev_fcf": None,
            "capital_allocation_buyback_execution_fcf_yield": None,
            "capital_allocation_buyback_timing_valuation_percentile": None,
            "capital_allocation_buyback_subsequent_return_12m": None,
            "capital_allocation_buyback_authorization_to_execution_ratio": None,
            "capital_allocation_buyback_consistency_of_execution": None,
            "capital_allocation_buyback_timing_accuracy": None,
            "capital_allocation_buyback_per_share_fcf_growth_post": None,
            "capital_allocation_buyback_per_share_earnings_growth_post": None,
            "capital_allocation_buyback_intrinsic_value_per_share_growth_post": None,
            "capital_allocation_buyback_program_created_value_flag": None,
            "capital_allocation_buyback_evidence_trail": None,
            "capital_allocation_buyback_is_financial_company": None,
            "capital_allocation_buyback_is_acquisitive_company": None,
        }
        data.update(buyback_defaults)

        data["reinvestment_rate"] = ((capex + acq) / ocf) if ocf not in (None, 0) and capex is not None else None
        data["organic_investment_efficiency"] = (((self._cagr(revenue_hist[-1]["value"], revenue_hist[-4]["value"], 3) if len(revenue_hist) >= 4 else None) or 0.0) / max((capex / rev) * 100.0, 0.1)) if capex is not None and rev not in (None, 0) else None

        if len(op_income_hist) >= 4 and len(equity_hist) >= 4:
            prior_op = op_income_hist[-4]["value"]
            prior_eq = equity_hist[-4]["value"]
            prior_debt = debt_hist[-4]["value"] if len(debt_hist) >= 4 else 0.0
            prior_cash = cash_hist[-4]["value"] if len(cash_hist) >= 4 else 0.0
            prior_ic = prior_eq + prior_debt - prior_cash
            latest_nopat = op_inc * (1 - 0.21) if op_inc is not None else None
            prior_nopat = prior_op * (1 - 0.21)
            delta_ic = invested_capital - prior_ic
            if latest_nopat is not None and delta_ic not in (None, 0):
                data["incremental_roic"] = (latest_nopat - prior_nopat) / delta_ic
            else:
                data["incremental_roic"] = None
        else:
            data["incremental_roic"] = None

        if len(retained_hist) >= 4 and len(ni_hist) >= 4:
            delta_ni = ni_hist[-1]["value"] - ni_hist[-4]["value"]
            delta_ret = retained_hist[-1]["value"] - retained_hist[-4]["value"]
            data["return_on_retained_earnings"] = (delta_ni / delta_ret) if delta_ret not in (None, 0) else None
        else:
            data["return_on_retained_earnings"] = None

        if len(acq_hist) >= 2 and acq > 0:
            rev_growth = self._cagr(revenue_hist[-1]["value"], revenue_hist[-4]["value"], 3) if len(revenue_hist) >= 4 else None
            data["acquisition_roi"] = (rev_growth / ((acq / rev) * 100.0)) if rev_growth is not None and rev not in (None, 0) and acq > 0 else None
        else:
            data["acquisition_roi"] = None

        data["buyback_timing"] = None
        data["buyback_valuation"] = None
        data["buyback_effectiveness"] = ((buyback - issuance) / buyback) if buyback > 0 else None
        data["dividend_policy_effectiveness"] = ((dividends / fcf) * 100.0) if dividends > 0 and fcf not in (None, 0) else None
        if len(debt_hist) >= 2:
            debt_delta = debt_hist[-1]["value"] - debt_hist[-2]["value"]
            data["debt_reduction_effectiveness"] = (-debt_delta / max(abs(ni or 0.0), 1.0)) if ni is not None else None
        else:
            data["debt_reduction_effectiveness"] = None

        if len(shares_hist) >= 2:
            data["share_count_reduction_trend"] = -self._pct_change(shares_hist[-1]["value"], shares_hist[-2]["value"])
            data["dilution_trend"] = self._pct_change(shares_hist[-1]["value"], shares_hist[-2]["value"])
        else:
            data["share_count_reduction_trend"] = None
            data["dilution_trend"] = None
        data["sbc_offset_effectiveness"] = ((buyback - issuance) / issuance) if issuance not in (None, 0) else None

        data["acquisition_history_count"] = len([r for r in acq_hist if _to_float(r.get("value"), 0.0) not in (None, 0.0)])
        data["acquisition_success_rate"] = data["acquisition_roi"]
        data["capital_allocation_consistency"] = None
        if len(capex_hist) >= 3:
            capex_rates = []
            rev_by_end = {r["end"]: r["value"] for r in revenue_hist}
            for row in capex_hist[-3:]:
                rv = rev_by_end.get(row["end"])
                if rv not in (None, 0):
                    capex_rates.append(abs(row["value"]) / rv)
            if len(capex_rates) >= 2:
                data["capital_allocation_consistency"] = max(capex_rates) - min(capex_rates)
        data["leverage_decisions"] = (debt / equity) if equity not in (None, 0) else None
        data["liquidity_management"] = (cash / debt) if debt not in (None, 0) else None
        data["capital_discipline"] = None

        bvps_latest = (equity / shares) if equity not in (None, 0) and shares not in (None, 0) else None
        if len(equity_hist) >= 4 and len(shares_hist) >= 4:
            prior_bvps = equity_hist[-4]["value"] / shares_hist[-4]["value"] if shares_hist[-4]["value"] not in (None, 0) else None
            data["book_value_per_share_growth_3y"] = self._cagr(bvps_latest, prior_bvps, 3) if bvps_latest is not None and prior_bvps is not None else None
        else:
            data["book_value_per_share_growth_3y"] = None
        if len(ocf_hist) >= 4 and len(capex_hist) >= 4 and len(shares_hist) >= 4:
            latest_fcf_ps = (fcf / shares) if fcf not in (None, 0) and shares not in (None, 0) else None
            prior_fcf = ocf_hist[-4]["value"] - abs(capex_hist[-4]["value"])
            prior_shares = shares_hist[-4]["value"]
            prior_fcf_ps = (prior_fcf / prior_shares) if prior_shares not in (None, 0) else None
            data["free_cash_flow_per_share_growth_3y"] = self._cagr(latest_fcf_ps, prior_fcf_ps, 3) if latest_fcf_ps is not None and prior_fcf_ps is not None else None
        else:
            data["free_cash_flow_per_share_growth_3y"] = None
        data["owner_earnings_growth_3y"] = data.get("free_cash_flow_per_share_growth_3y")
        data["intrinsic_value_per_share_growth"] = _to_float(data.get("free_cash_flow_per_share_growth_3y"), None)

        if latest_interest and latest_interest["value"] not in (None, 0) and op_inc is not None:
            data["interest_coverage"] = op_inc / latest_interest["value"]
        else:
            data["interest_coverage"] = None

        # ------------------------------------------------------------------
        # Share Buyback Intelligence raw metrics
        # ------------------------------------------------------------------
        repur_q = self._latest(shares_repur_q_hist)
        spend_q = self._latest(buyback_q_hist)
        shares_q = self._latest(shares_q_hist)

        shares_repur_q = abs(_to_float((repur_q or {}).get("value"), 0.0) or 0.0)
        spend_q_val = abs(_to_float((spend_q or {}).get("value"), 0.0) or 0.0)
        avg_repur_price_q = self._safe_ratio(spend_q_val, shares_repur_q) if shares_repur_q > 0 else None

        buyback_ttm = abs(self._sum_values(buyback_q_hist, 4))
        buyback_3y = abs(self._sum_values(buyback_q_hist, 12))
        buyback_5y = abs(self._sum_values(buyback_q_hist, 20))
        shares_repurchased_ttm = abs(self._sum_values(shares_repur_q_hist, 4))

        diluted_change_pct = None
        basic_change_pct = None
        if len(shares_q_hist) >= 5:
            curr_shares = _to_float(shares_q_hist[-1].get("value"), None)
            prev_shares = _to_float(shares_q_hist[-5].get("value"), None)
            if curr_shares is not None and prev_shares not in (None, 0):
                diluted_change_pct = ((curr_shares / prev_shares) - 1.0) * 100.0
                basic_change_pct = diluted_change_pct

        sbc_latest = abs(_to_float((self._latest(sbc_hist) or {}).get("value"), 0.0) or 0.0)
        debt_prev = _to_float((debt_hist[-2] if len(debt_hist) >= 2 else {}).get("value"), None)
        debt_curr = _to_float((debt_hist[-1] if len(debt_hist) >= 1 else {}).get("value"), None)
        cash_prev = _to_float((cash_hist[-2] if len(cash_hist) >= 2 else {}).get("value"), None)
        cash_curr = _to_float((cash_hist[-1] if len(cash_hist) >= 1 else {}).get("value"), None)
        ic_prev = None
        ic_curr = data.get("interest_coverage")
        if len(interest_hist) >= 2 and len(op_income_hist) >= 2:
            prev_int = _to_float(interest_hist[-2].get("value"), None)
            prev_op = _to_float(op_income_hist[-2].get("value"), None)
            if prev_int not in (None, 0) and prev_op is not None:
                ic_prev = prev_op / prev_int

        net_debt_change = None
        if debt_curr is not None and cash_curr is not None and debt_prev is not None and cash_prev is not None:
            net_debt_change = (debt_curr - cash_curr) - (debt_prev - cash_prev)

        # Market-cap-relative metrics use current ranking context if available in downstream stage.
        market_cap_proxy = None

        data.update(
            {
                "capital_allocation_buyback_shares_repur_q": shares_repur_q if shares_repur_q > 0 else None,
                "capital_allocation_buyback_spend_q": spend_q_val if spend_q_val > 0 else None,
                "capital_allocation_buyback_avg_price_q": avg_repur_price_q,
                "capital_allocation_buyback_pct_market_cap_ttm": self._pct_of(buyback_ttm, market_cap_proxy),
                "capital_allocation_buyback_pct_shares_ttm": self._pct_of(shares_repurchased_ttm, _to_float((shares_q or {}).get("value"), None)),
                "capital_allocation_buyback_yield_ttm": self._pct_of(buyback_ttm, market_cap_proxy),
                "capital_allocation_buyback_spend_3y": buyback_3y if buyback_3y > 0 else None,
                "capital_allocation_buyback_spend_5y": buyback_5y if buyback_5y > 0 else None,
                "capital_allocation_buyback_basic_share_change_pct": basic_change_pct,
                "capital_allocation_buyback_diluted_share_change_pct": diluted_change_pct,
                "capital_allocation_buyback_sbc_issuance": sbc_latest if sbc_latest > 0 else None,
                "capital_allocation_buyback_acquisition_issuance": abs(acq) if acq else None,
                "capital_allocation_buyback_option_exercise_issuance": abs(issuance) if issuance else None,
                "capital_allocation_buyback_net_diluted_share_reduction_pct": (-diluted_change_pct) if diluted_change_pct is not None else None,
                "capital_allocation_buyback_as_pct_sbc": self._pct_of(buyback_ttm, sbc_latest),
                "capital_allocation_buyback_as_pct_fcf": self._pct_of(buyback_ttm, abs(fcf) if fcf is not None else None),
                "capital_allocation_buyback_fcf_used": self._safe_ratio(buyback_ttm, abs(fcf) if fcf is not None else None),
                "capital_allocation_buyback_cash_balance_change": (cash_curr - cash_prev) if cash_curr is not None and cash_prev is not None else None,
                "capital_allocation_buyback_debt_issuance": (debt_curr - debt_prev) if debt_curr is not None and debt_prev is not None else None,
                "capital_allocation_buyback_net_debt_change": net_debt_change,
                "capital_allocation_buyback_interest_coverage_change": (ic_curr - ic_prev) if ic_curr is not None and ic_prev is not None else None,
                "capital_allocation_buyback_debt_funded_flag": bool((debt_curr - debt_prev) > 0 and buyback_ttm > 0) if debt_curr is not None and debt_prev is not None else None,
                "capital_allocation_buyback_liquidity_strain_flag": bool((cash_curr - cash_prev) < 0 and buyback_ttm > 0) if cash_curr is not None and cash_prev is not None else None,
                "capital_allocation_buyback_authorization_to_execution_ratio": None,
                "capital_allocation_buyback_consistency_of_execution": None,
                "capital_allocation_buyback_timing_accuracy": None,
                "capital_allocation_buyback_per_share_fcf_growth_post": data.get("free_cash_flow_per_share_growth_3y"),
                "capital_allocation_buyback_per_share_earnings_growth_post": self._cagr(_to_float((self._latest(ni_hist) or {}).get("value"), None), _to_float((ni_hist[-4] if len(ni_hist) >= 4 else {}).get("value"), None), 3) if len(ni_hist) >= 4 else None,
                "capital_allocation_buyback_intrinsic_value_per_share_growth_post": data.get("intrinsic_value_per_share_growth"),
                "capital_allocation_buyback_is_financial_company": None,
                "capital_allocation_buyback_is_acquisitive_company": bool((abs(acq) / abs(rev)) > 0.05) if rev not in (None, 0) else None,
            }
        )

        # Submissions-based authorization/event metadata (when available in SEC recent feed).
        recent = ((submissions.get("filings") or {}).get("recent") or {}) if isinstance(submissions, dict) else {}
        forms = recent.get("form") or []
        filing_dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        primary_desc = recent.get("primaryDocDescription") or []

        auth_event = None
        for i in range(len(forms) - 1, -1, -1):
            form = str(forms[i]).upper() if i < len(forms) else ""
            desc = str(primary_desc[i]).lower() if i < len(primary_desc) else ""
            if form in {"8-K", "10-Q", "10-K"} and any(k in desc for k in ["repurchase", "buyback", "authorization"]):
                auth_event = {
                    "form": form,
                    "filing_date": filing_dates[i] if i < len(filing_dates) else None,
                    "accn": accessions[i] if i < len(accessions) else None,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{str(accessions[i]).replace('-', '')}/{primary_docs[i]}" if i < len(accessions) and i < len(primary_docs) else None,
                    "description": primary_desc[i] if i < len(primary_desc) else None,
                }
                break

        if auth_event:
            data["capital_allocation_buyback_authorization_date"] = auth_event.get("filing_date")
            data["capital_allocation_buyback_board_approval_source"] = auth_event.get("form")
            data["capital_allocation_buyback_authorization_status"] = "AUTHORIZED_EVENT_DETECTED"

        evidence = {
            "source_url": auth_event.get("url") if auth_event else None,
            "sec_accession_number": auth_event.get("accn") if auth_event else data.get("latest_accession_number"),
            "filing_form": auth_event.get("form") if auth_event else "10-K",
            "filing_date": auth_event.get("filing_date") if auth_event else data.get("latest_filing_date"),
            "raw_tag": (repur_q or spend_q or {}).get("concept"),
            "timestamp": now_iso,
            "confidence": self.confidence_base,
            "stale": False,
        }
        data["capital_allocation_buyback_evidence_trail"] = json.dumps(evidence)

        if data.get("capital_allocation_buyback_avg_price_q") is not None and data.get("capital_allocation_buyback_avg_price_vs_current_pct") is None:
            data["capital_allocation_buyback_program_created_value_flag"] = None

        self.cache[symbol] = {"timestamp": now_iso, "confidence": self.confidence_base, "data": data}
        self._save_cache()

        return {"symbol": symbol, "timestamp": now_iso, "source": self.name, "stale": False, "confidence": self.confidence_base, "data": data}
