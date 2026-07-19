#!/usr/bin/env python3
"""McLeod Earnings Quality Engine v1.0."""

from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_sources.earnings_quality_source import EarningsQualitySource
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
INSIDER_CSV = DATA_DIR / "insider_transactions_latest.csv"

OUTPUT_JSON = DATA_DIR / "earnings_quality_latest.json"
OUTPUT_CSV = DATA_DIR / "earnings_quality_latest.csv"
OUTPUT_HISTORY_CSV = DATA_DIR / "earnings_quality_history.csv"
REPORT_MD = REPORTS_DIR / "earnings_quality_report.md"

NEEDS_RESEARCH = "NEEDS_RESEARCH"
FINANCIAL_SECTORS = {"FINANCIALS", "BANKS", "INSURANCE"}
SOFTWARE_KEYWORDS = {"SOFTWARE", "SAAS"}
CYCLICAL_SECTORS = {"INDUSTRIALS", "MATERIALS", "ENERGY", "CONSUMER_DISCRETIONARY"}


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

    def close_at_offset(self, symbol: str, baseline_date: date, offset: int) -> Optional[float]:
        series = self.client.load(symbol, baseline_date - timedelta(days=10), date.today() + timedelta(days=2))
        return series.close_at_offset(baseline_date, offset)


@dataclass
class PredictiveStats:
    horizon_label: str
    resolved_count: int
    quality_ic: float
    base_ic: float
    combined_ic: float
    incremental_ic: float


class EarningsQualityEngine:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.source = EarningsQualitySource()
        self.close_client = YahooCloseClient()
        self.refresh_limit = int(__import__("os").getenv("EARNINGS_QUALITY_REFRESH_LIMIT", "160"))
        self.force_refresh = __import__("os").getenv("EARNINGS_QUALITY_FORCE_REFRESH", "0") == "1"
        self.include_full_universe = __import__("os").getenv("EARNINGS_QUALITY_INCLUDE_FULL_UNIVERSE", "0") == "1"
        self.rank_context = self._load_rank_context()

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
                    if sym:
                        merged = dict(out.get(sym, {}))
                        merged.update({k: str(v) for k, v in row.items() if not isinstance(v, (dict, list))})
                        out[sym] = merged
            except Exception:
                pass
        return out

    def _load_target_symbols(self) -> List[str]:
        if not UNIVERSE_CSV.exists():
            UniverseBuilder().build()
        groups: List[List[str]] = []

        holdings: List[str] = []
        if POSITIONS_CSV.exists():
            with open(POSITIONS_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if str(row.get("asset_type", "")).upper() == "EQUITY":
                        sym = str(row.get("symbol", "")).upper().strip()
                        if sym:
                            holdings.append(sym)
        groups.append(holdings)

        top100: List[str] = []
        if TOP100_CSV.exists():
            with open(TOP100_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        top100.append(sym)
        groups.append(top100)

        replacements: List[str] = []
        if REPLACEMENTS_CSV.exists():
            with open(REPLACEMENTS_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    for key in ("candidate_symbol", "replace_symbol"):
                        sym = str(row.get(key, "")).upper().strip()
                        if sym:
                            replacements.append(sym)
        groups.append(replacements)

        if self.include_full_universe and UNIVERSE_CSV.exists():
            universe: List[str] = []
            with open(UNIVERSE_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        universe.append(sym)
            groups.append(universe)

        ordered: List[str] = []
        seen = set()
        for group in groups:
            for sym in group:
                if sym and sym not in seen:
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
    def _sector_bucket(context: Dict[str, str]) -> str:
        sector = str(context.get("sector", "")).upper().strip()
        industry = str(context.get("industry", "")).upper().strip()
        if sector in FINANCIAL_SECTORS or "BANK" in industry or "INSURANCE" in industry:
            return "financials"
        if sector == "HEALTH_CARE":
            return "healthcare"
        if any(k in industry for k in SOFTWARE_KEYWORDS):
            return "software"
        if sector in CYCLICAL_SECTORS:
            return "cyclicals"
        if sector == "INDUSTRIALS":
            return "industrials"
        return "general"

    def _score_symbol(self, symbol: str, raw: Dict[str, Any], context: Dict[str, str]) -> Dict[str, Any]:
        sector_bucket = self._sector_bucket(context)
        is_financial = sector_bucket == "financials"

        ocf_ni = _safe_float(raw.get("cash_conversion_ocf_net_income"), None)
        fcf_ni = _safe_float(raw.get("cash_conversion_fcf_net_income"), None)
        fcf_margin = _safe_float(raw.get("free_cash_flow_margin"), None)
        cash_eps_gap = _safe_float(raw.get("cash_eps_vs_gaap_eps_gap"), None)
        cash_conv_trend = _safe_float(raw.get("multi_year_cash_conversion_trend"), None)
        accruals = _safe_float(raw.get("total_accruals_avg_assets"), None)
        wc_accruals = _safe_float(raw.get("working_capital_accruals"), None)
        recv_vs_rev = _safe_float(raw.get("receivables_growth_vs_revenue_growth"), None)
        deferred_growth = _safe_float(raw.get("deferred_revenue_growth"), None)
        sbc_rev = _safe_float(raw.get("stock_based_comp_pct_revenue"), None)
        sbc_fcf = _safe_float(raw.get("stock_based_comp_pct_fcf"), None)
        soft_cap = _safe_float(raw.get("capitalized_software_dev_costs"), None)
        restruct = _safe_float(raw.get("restructuring_charges"), None)
        capex_rev = _safe_float(raw.get("capex_pct_revenue"), None)
        fcf_after_sbc = _safe_float(raw.get("free_cash_flow_after_sbc"), None)
        reinvest_eff = _safe_float(raw.get("reinvestment_efficiency"), None)
        dil_1y = _safe_float(raw.get("diluted_share_count_growth_1y"), None)
        dil_3y = _safe_float(raw.get("diluted_share_count_growth_3y"), None)
        dil_5y = _safe_float(raw.get("diluted_share_count_growth_5y"), None)
        buyback_vs_issue = _safe_float(raw.get("buybacks_vs_stock_issuance"), None)
        net_cash_trend = _safe_float(raw.get("net_cash_or_net_debt_trend"), None)
        debt_buybacks = _safe_float(raw.get("debt_funded_buybacks"), None)
        debt_acq = _safe_float(raw.get("debt_funded_acquisitions"), None)
        interest_cov = _safe_float(raw.get("interest_coverage"), None)

        cash_parts: List[float] = []
        if ocf_ni is not None:
            cash_parts.append(_clamp(50.0 + (ocf_ni - 1.0) * 40.0))
        if fcf_ni is not None:
            cash_parts.append(_clamp(45.0 + (fcf_ni - 1.0) * 35.0))
        if fcf_margin is not None:
            cash_parts.append(_clamp(40.0 + fcf_margin * 1.5))
        if cash_conv_trend is not None:
            cash_parts.append(_clamp(50.0 + cash_conv_trend * 25.0))
        cash_score = _clamp(_mean(cash_parts)) if cash_parts else None

        accrual_parts: List[float] = []
        if accruals is not None:
            accrual_parts.append(_clamp(75.0 - abs(accruals) * 500.0))
        if wc_accruals is not None:
            accrual_parts.append(_clamp(75.0 - abs(wc_accruals) * 450.0))
        if recv_vs_rev is not None:
            accrual_parts.append(_clamp(70.0 - max(0.0, recv_vs_rev) * 2.0 + max(0.0, -recv_vs_rev) * 0.5))
        accrual_score = _clamp(_mean(accrual_parts)) if accrual_parts else None

        revenue_parts: List[float] = []
        if recv_vs_rev is not None:
            revenue_parts.append(_clamp(70.0 - max(0.0, recv_vs_rev) * 2.5))
        if deferred_growth is not None:
            revenue_parts.append(_clamp(50.0 + deferred_growth * 1.2))
        revenue_score = _clamp(_mean(revenue_parts)) if revenue_parts else None

        expense_parts: List[float] = []
        if sbc_rev is not None:
            expense_parts.append(_clamp(85.0 - sbc_rev * 5.0))
        if sbc_fcf is not None:
            expense_parts.append(_clamp(85.0 - max(0.0, sbc_fcf) * 0.7))
        if soft_cap is not None:
            expense_parts.append(_clamp(70.0 - math.log10(max(1.0, abs(soft_cap))) * 5.0))
        if restruct is not None:
            expense_parts.append(_clamp(70.0 - math.log10(max(1.0, abs(restruct))) * 5.0))
        expense_score = _clamp(_mean(expense_parts)) if expense_parts else None

        dilution_parts: List[float] = []
        for dil in [dil_1y, dil_3y, dil_5y]:
            if dil is not None:
                dilution_parts.append(_clamp(80.0 - max(0.0, dil) * 2.5 + max(0.0, -dil) * 1.0))
        if buyback_vs_issue is not None:
            dilution_parts.append(_clamp(50.0 + math.copysign(min(30.0, math.log10(max(1.0, abs(buyback_vs_issue))) * 5.0), buyback_vs_issue)))
        dilution_score = _clamp(_mean(dilution_parts)) if dilution_parts else None

        capital_parts: List[float] = []
        if capex_rev is not None:
            capital_parts.append(_clamp(70.0 - max(0.0, capex_rev - 8.0) * 2.0))
        if fcf_after_sbc is not None:
            capital_parts.append(_clamp(55.0 + math.copysign(min(35.0, math.log10(max(1.0, abs(fcf_after_sbc))) * 4.0), fcf_after_sbc)))
        if reinvest_eff is not None:
            capital_parts.append(_clamp(50.0 + reinvest_eff * 8.0))
        capital_score = _clamp(_mean(capital_parts)) if capital_parts else None

        balance_parts: List[float] = []
        if net_cash_trend is not None:
            balance_parts.append(_clamp(50.0 - math.copysign(min(30.0, math.log10(max(1.0, abs(net_cash_trend))) * 4.0), net_cash_trend)))
        if debt_buybacks is not None:
            balance_parts.append(_clamp(70.0 - math.log10(max(1.0, debt_buybacks)) * 5.0))
        if debt_acq is not None:
            balance_parts.append(_clamp(70.0 - math.log10(max(1.0, debt_acq)) * 5.0))
        if interest_cov is not None:
            balance_parts.append(_clamp(35.0 + min(interest_cov, 15.0) * 4.0))
        balance_score = _clamp(_mean(balance_parts)) if balance_parts else None

        if is_financial:
            # Banks/insurers are less comparable on standard cash-flow metrics.
            cash_score = None
            capital_score = None
            comparability_flag = "financial_company_adjusted"
            overall_parts = [p for p in [accrual_score, revenue_score, expense_score, dilution_score, balance_score] if p is not None]
        else:
            comparability_flag = "standard"
            overall_parts = [p for p in [cash_score, accrual_score, revenue_score, expense_score, dilution_score, capital_score, balance_score] if p is not None]

        overall_score = _clamp(_mean(overall_parts)) if overall_parts else 50.0
        thesis_impact = _clamp(overall_score * 0.75 + (balance_score or 50.0) * 0.10 + (accrual_score or 50.0) * 0.15)

        if thesis_impact >= 70:
            thesis_signal = "strengthening thesis"
        elif thesis_impact >= 50:
            thesis_signal = "stable thesis"
        elif thesis_impact >= 35:
            thesis_signal = "weakening thesis"
        else:
            thesis_signal = "potential thesis break"

        positive_factors: List[Tuple[str, float]] = []
        negative_factors: List[Tuple[str, float]] = []
        for name, score in [
            ("cash conversion", cash_score),
            ("accrual quality", accrual_score),
            ("revenue quality", revenue_score),
            ("expense quality", expense_score),
            ("dilution", dilution_score),
            ("capital intensity", capital_score),
            ("balance sheet", balance_score),
        ]:
            if score is None:
                continue
            if score >= 55:
                positive_factors.append((name, score))
            else:
                negative_factors.append((name, score))

        strongest_positive = max(positive_factors, key=lambda t: t[1])[0] + f" ({max(positive_factors, key=lambda t: t[1])[1]:.1f})" if positive_factors else NEEDS_RESEARCH
        strongest_negative = min(negative_factors, key=lambda t: t[1])[0] + f" ({min(negative_factors, key=lambda t: t[1])[1]:.1f})" if negative_factors else NEEDS_RESEARCH

        return {
            "earnings_quality_cash_conversion_score": round(cash_score, 2) if cash_score is not None else None,
            "earnings_quality_accrual_quality_score": round(accrual_score, 2) if accrual_score is not None else None,
            "earnings_quality_revenue_quality_score": round(revenue_score, 2) if revenue_score is not None else None,
            "earnings_quality_expense_quality_score": round(expense_score, 2) if expense_score is not None else None,
            "earnings_quality_dilution_score": round(dilution_score, 2) if dilution_score is not None else None,
            "earnings_quality_capital_intensity_score": round(capital_score, 2) if capital_score is not None else None,
            "earnings_quality_balance_sheet_score": round(balance_score, 2) if balance_score is not None else None,
            "earnings_quality_score": round(overall_score, 2),
            "earnings_quality_thesis_impact_score": round(thesis_impact, 2),
            "earnings_quality_thesis_signal": thesis_signal,
            "earnings_quality_cash_conversion_trend": round(cash_conv_trend, 4) if cash_conv_trend is not None else None,
            "earnings_quality_dilution_trend": round((dil_3y if dil_3y is not None else dil_1y), 4) if (dil_3y is not None or dil_1y is not None) else None,
            "earnings_quality_accrual_trend": round((wc_accruals if wc_accruals is not None else accruals), 4) if (wc_accruals is not None or accruals is not None) else None,
            "earnings_quality_recurring_adjustments_flag": "1" if (restruct is not None and abs(restruct) > 0) else "0",
            "earnings_quality_strongest_positive_factor": strongest_positive,
            "earnings_quality_strongest_negative_factor": strongest_negative,
            "earnings_quality_comparability_flag": comparability_flag,
        }

    def _build_explainability(self, raw: Dict[str, Any], scored: Dict[str, Any]) -> str:
        lines = ["Earnings Quality:"]
        lines.append(f"- Strongest positive factor: {scored.get('earnings_quality_strongest_positive_factor', NEEDS_RESEARCH)}")
        lines.append(f"- Strongest negative factor: {scored.get('earnings_quality_strongest_negative_factor', NEEDS_RESEARCH)}")
        lines.append(f"- Cash conversion trend: {raw.get('multi_year_cash_conversion_trend', NEEDS_RESEARCH)}")
        lines.append(f"- Dilution trend: {scored.get('earnings_quality_dilution_trend', NEEDS_RESEARCH)}")
        lines.append(f"- Accrual trend: {scored.get('earnings_quality_accrual_trend', NEEDS_RESEARCH)}")
        if scored.get("earnings_quality_recurring_adjustments_flag") == "1":
            lines.append("- Recurring adjustments flagged: restructuring or similar charges present")
        if scored.get("earnings_quality_comparability_flag") == "financial_company_adjusted":
            lines.append("- Financial-company adjusted logic used; standard industrial cash-flow comparisons are less reliable")
        if raw.get("latest_accession_number"):
            lines.append(f"- Evidence trail: latest annual filing accn {raw.get('latest_accession_number')} filed {raw.get('latest_filing_date', 'N/A')}")
        missing = []
        for key in [
            "cash_conversion_ocf_net_income",
            "total_accruals_avg_assets",
            "stock_based_comp_pct_revenue",
            "diluted_share_count_growth_1y",
        ]:
            if raw.get(key) is None:
                missing.append(key)
        if missing:
            lines.append(f"- Missing data: {', '.join(missing[:6])}")
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
                    "earnings_quality_score": row.get("earnings_quality_score", NEEDS_RESEARCH),
                    "earnings_quality_thesis_impact_score": row.get("earnings_quality_thesis_impact_score", NEEDS_RESEARCH),
                    "base_composite_score": context.get("composite_score", ""),
                    "sector_bucket": self._sector_bucket(context),
                    "resolved_6m": "0",
                    "resolved_12m": "0",
                    "resolved_24m": "0",
                    "resolved_36m": "0",
                    "return_6m_pct": "",
                    "return_12m_pct": "",
                    "return_24m_pct": "",
                    "return_36m_pct": "",
                    "spy_return_6m_pct": "",
                    "spy_return_12m_pct": "",
                    "spy_return_24m_pct": "",
                    "spy_return_36m_pct": "",
                    "excess_vs_spy_6m_pct": "",
                    "excess_vs_spy_12m_pct": "",
                    "excess_vs_spy_24m_pct": "",
                    "excess_vs_spy_36m_pct": "",
                    "last_evaluated_at": "",
                }
            )
        self._write_csv(OUTPUT_HISTORY_CSV, existing)

    def _resolve_history_returns(self, as_of: date) -> List[Dict[str, str]]:
        rows = self._read_csv(OUTPUT_HISTORY_CSV)
        updated: List[Dict[str, str]] = []
        horizons = [("6m", 126), ("12m", 252), ("24m", 504), ("36m", 756)]
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
                ex_key = f"excess_vs_spy_{label}_pct"
                if str(out.get(res_key, "0")) == "1":
                    continue
                if as_of < snap + timedelta(days=max(90, int(offset * 0.7))):
                    continue
                base = self.close_client.close_at_offset(sym, snap, 0)
                fut = self.close_client.close_at_offset(sym, snap, offset)
                spy_base = self.close_client.close_at_offset("SPY", snap, 0)
                spy_fut = self.close_client.close_at_offset("SPY", snap, offset)
                if base is None or fut is None or base <= 0:
                    continue
                ret = ((fut / base) - 1.0) * 100.0
                out[ret_key] = f"{ret:.6f}"
                out[res_key] = "1"
                if spy_base and spy_fut and spy_base > 0:
                    spy_ret = ((spy_fut / spy_base) - 1.0) * 100.0
                    out[spy_key] = f"{spy_ret:.6f}"
                    out[ex_key] = f"{(ret - spy_ret):.6f}"
            out["last_evaluated_at"] = datetime.now().isoformat(timespec="seconds")
            updated.append(out)
        self._write_csv(OUTPUT_HISTORY_CSV, updated)
        return updated

    def _predictive_stats(self, rows: List[Dict[str, str]]) -> List[PredictiveStats]:
        out: List[PredictiveStats] = []
        for label in ["6m", "12m", "24m", "36m"]:
            xq: List[float] = []
            xb: List[float] = []
            y: List[float] = []
            for r in rows:
                if str(r.get(f"resolved_{label}", "0")) != "1":
                    continue
                q = _safe_float(r.get("earnings_quality_score"), None)
                b = _safe_float(r.get("base_composite_score"), None)
                ret = _safe_float(r.get(f"excess_vs_spy_{label}_pct"), None)
                if q is None or b is None or ret is None:
                    continue
                xq.append(q)
                xb.append(b)
                y.append(ret)
            if len(y) < 2:
                out.append(PredictiveStats(label, len(y), 0.0, 0.0, 0.0, 0.0))
                continue
            q_ic = _spearman(xq, y)
            b_ic = _spearman(xb, y)
            combined = [0.75 * b + 0.25 * q for b, q in zip(xb, xq)]
            c_ic = _spearman(combined, y)
            out.append(PredictiveStats(label, len(y), q_ic, b_ic, c_ic, c_ic - b_ic))
        return out

    def _weight_recommendation(self, stats: List[PredictiveStats]) -> str:
        valid = [s for s in stats if s.resolved_count >= 40 and s.incremental_ic > 0.03]
        if not valid:
            return "No meaningful earnings-quality model weight change recommended yet: insufficient or weak out-of-sample predictive evidence."
        avg_inc = _mean([s.incremental_ic for s in valid])
        weight = min(0.08, max(0.02, avg_inc * 1.5))
        return f"Proposed earnings-quality factor weight: {weight:.2%}, conditioned on manual approval and continued walk-forward OOS validation."

    def _write_reports(self, rows: List[Dict[str, Any]], hist: List[Dict[str, str]], stats: List[PredictiveStats], recommendation: str) -> None:
        eq_vals = [_safe_float(r.get("earnings_quality_score"), None) for r in rows]
        eq_vals = [v for v in eq_vals if v is not None]
        total_slots = populated = valuable = 0
        for row in rows:
            for key, value in row.items():
                if key.endswith("_source") or key.endswith("_timestamp") or key.endswith("_confidence") or key.endswith("_stale"):
                    continue
                if key in {"symbol", "as_of", "earnings_quality_engine_version", "refresh_deferred", "sec_cik", "latest_filing_date", "latest_accession_number"}:
                    continue
                total_slots += 1
                if value != NEEDS_RESEARCH:
                    populated += 1
                    conf = _safe_float(row.get(f"{key}_confidence"), 0.0) or 0.0
                    if conf >= 60:
                        valuable += 1
        dq = (populated / total_slots * 100.0) if total_slots else 0.0
        dv = (valuable / total_slots * 100.0) if total_slots else 0.0
        top = sorted(rows, key=lambda r: _safe_float(r.get("earnings_quality_score"), -1.0) or -1.0, reverse=True)[:10]

        sector_lines = []
        for bucket in ["industrials", "software", "financials", "healthcare", "cyclicals"]:
            vals = [_safe_float(r.get("excess_vs_spy_12m_pct"), None) for r in hist if str(r.get("resolved_12m", "0")) == "1" and str(r.get("sector_bucket", "")) == bucket]
            vals = [v for v in vals if v is not None]
            sector_lines.append(f"- {bucket}: {_mean(vals):.2f}% avg 12m excess vs SPY" if vals else f"- {bucket}: N/A")

        lines = [
            "# Earnings Quality Report",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Data Quality Dashboard",
            "",
            f"- Universe rows: {len(rows)}",
            f"- Earnings-quality metric coverage: {dq:.2f}%",
            "",
            "## Data Value Dashboard",
            "",
            f"- High-confidence earnings-quality coverage (confidence >= 60): {dv:.2f}%",
            f"- Average Earnings Quality Score: {_mean(eq_vals):.2f}" if eq_vals else "- Average Earnings Quality Score: N/A",
            "",
            "## Explainability Report",
            "",
        ]
        for row in top:
            lines.extend([
                f"### {row.get('symbol', 'N/A')} (Earnings Quality Score: {row.get('earnings_quality_score', NEEDS_RESEARCH)})",
                str(row.get("earnings_quality_explainability", "Earnings Quality: unavailable")),
                "",
            ])
        lines.extend([
            "## Predictive Performance (6m/12m/24m/36m)",
            "",
            "| Horizon | Resolved Samples | Quality IC | Base IC | Combined IC | Incremental IC |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for st in stats:
            lines.append(f"| {st.horizon_label} | {st.resolved_count} | {st.quality_ic:.4f} | {st.base_ic:.4f} | {st.combined_ic:.4f} | {st.incremental_ic:.4f} |")
        lines.extend(["", "## Sector Backtests", ""] + sector_lines + ["", "## Weight Governance", "", f"- {recommendation}", "- Financial companies use adjusted sector-specific logic where standard industrial cash-flow comparisons are unreliable.", ""])
        REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        as_of_date = as_of or date.today()
        symbols = self._load_target_symbols()
        rows: List[Dict[str, Any]] = []
        refresh_count = 0
        print(f"[EarningsQuality] Target symbols: {len(symbols)} | refresh limit: {self.refresh_limit} | full universe: {self.include_full_universe}", flush=True)
        for symbol in symbols:
            has_cache = symbol in self.source.cache
            cached_ts = str((self.source.cache.get(symbol) or {}).get("timestamp", "")) if has_cache else ""
            has_fresh_cache = bool(cached_ts and self.source._cache_is_fresh(cached_ts))
            should_refresh = self.force_refresh and refresh_count < self.refresh_limit or (not self.force_refresh and (has_fresh_cache or refresh_count < self.refresh_limit))
            payload = self.source.fetch_symbol(symbol, force_refresh=self.force_refresh) if should_refresh else {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "source": "SEC XBRL Earnings Quality (refresh deferred)",
                "stale": True,
                "confidence": 0,
                "data": {},
            }
            if should_refresh and (self.force_refresh or not has_fresh_cache):
                refresh_count += 1
            raw = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
            context = self.rank_context.get(symbol, {})
            scored = self._score_symbol(symbol, raw, context)
            scored["earnings_quality_explainability"] = self._build_explainability(raw, scored)
            merged = dict(raw)
            merged.update(scored)
            row = {
                "symbol": symbol,
                "as_of": as_of_date.isoformat(),
                "earnings_quality_engine_version": "1.0.0",
                "refresh_deferred": "1" if not should_refresh else "0",
            }
            row.update(self._build_metric_fields(merged, str(payload.get("source", self.source.name)), str(payload.get("timestamp", datetime.now().isoformat())), int(payload.get("confidence", 0)), bool(payload.get("stale", False))))
            rows.append(row)
            if len(rows) % 10 == 0 or len(rows) == len(symbols):
                print(f"[EarningsQuality] Processed {len(rows)}/{len(symbols)} symbols", flush=True)

        output_json = {"metadata": {"timestamp": datetime.now().isoformat(), "engine": "McLeod Earnings Quality Engine", "version": "1.0.0", "symbols": len(symbols), "rows": len(rows)}, "holdings": rows}
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output_json, f, indent=2)
        self._write_csv(OUTPUT_CSV, rows)
        self._append_history(rows, as_of_date)
        fast_mode = __import__("os").getenv(
            "EARNINGS_QUALITY_FAST_MODE",
            __import__("os").getenv("SPECIALIST_FAST_MODE", "0"),
        ) == "1"
        if fast_mode:
            hist = []
            stats = []
            recommendation = "Fast mode: predictive backtest refresh deferred for this run."
        else:
            hist = self._resolve_history_returns(as_of_date)
            stats = self._predictive_stats(hist)
            recommendation = self._weight_recommendation(stats)
        self._write_reports(rows, hist, stats, recommendation)
        return {"as_of": as_of_date.isoformat(), "symbols_targeted": len(symbols), "rows_written": len(rows), "output_json": str(OUTPUT_JSON), "output_csv": str(OUTPUT_CSV), "history_csv": str(OUTPUT_HISTORY_CSV), "report": str(REPORT_MD), "weight_recommendation": recommendation}


def run_earnings_quality(as_of: Optional[date] = None) -> Dict[str, Any]:
    return EarningsQualityEngine().run(as_of=as_of)


def main() -> int:
    result = run_earnings_quality()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
