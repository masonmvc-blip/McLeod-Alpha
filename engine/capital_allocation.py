#!/usr/bin/env python3
"""McLeod Capital Allocation Intelligence Engine v1.0."""

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

from engine.data_sources.capital_allocation_source import CapitalAllocationSource
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
EARNINGS_QUALITY_CSV = DATA_DIR / "earnings_quality_latest.csv"

OUTPUT_JSON = DATA_DIR / "capital_allocation_latest.json"
OUTPUT_CSV = DATA_DIR / "capital_allocation_latest.csv"
OUTPUT_HISTORY_CSV = DATA_DIR / "capital_allocation_history.csv"
REPORT_MD = REPORTS_DIR / "capital_allocation_report.md"

NEEDS_RESEARCH = "NEEDS_RESEARCH"


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
    capital_ic: float
    base_ic: float
    combined_ic: float
    incremental_ic: float


class CapitalAllocationEngine:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.source = CapitalAllocationSource()
        self.close_client = YahooCloseClient()
        self.refresh_limit = int(__import__("os").getenv("CAPITAL_ALLOCATION_REFRESH_LIMIT", "160"))
        self.force_refresh = __import__("os").getenv("CAPITAL_ALLOCATION_FORCE_REFRESH", "0") == "1"
        self.include_full_universe = __import__("os").getenv("CAPITAL_ALLOCATION_INCLUDE_FULL_UNIVERSE", "0") == "1"
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

    def _score_symbol(self, raw: Dict[str, Any], context: Dict[str, str]) -> Dict[str, Any]:
        reinvest = _safe_float(raw.get("reinvestment_rate"), None)
        inc_roic = _safe_float(raw.get("incremental_roic"), None)
        roe_retained = _safe_float(raw.get("return_on_retained_earnings"), None)
        acq_roi = _safe_float(raw.get("acquisition_roi"), None)
        organic_eff = _safe_float(raw.get("organic_investment_efficiency"), None)
        buyback_eff = _safe_float(raw.get("buyback_effectiveness"), None)
        div_eff = _safe_float(raw.get("dividend_policy_effectiveness"), None)
        debt_red = _safe_float(raw.get("debt_reduction_effectiveness"), None)
        share_reduction = _safe_float(raw.get("share_count_reduction_trend"), None)
        dilution = _safe_float(raw.get("dilution_trend"), None)
        sbc_offset = _safe_float(raw.get("sbc_offset_effectiveness"), None)
        acq_count = _safe_float(raw.get("acquisition_history_count"), None)
        capital_consistency = _safe_float(raw.get("capital_allocation_consistency"), None)
        leverage_decisions = _safe_float(raw.get("leverage_decisions"), None)
        liquidity_mgmt = _safe_float(raw.get("liquidity_management"), None)
        bvps_growth = _safe_float(raw.get("book_value_per_share_growth_3y"), None)
        fcf_ps_growth = _safe_float(raw.get("free_cash_flow_per_share_growth_3y"), None)
        owner_growth = _safe_float(raw.get("owner_earnings_growth_3y"), None)

        buyback_auth_amt = _safe_float(raw.get("capital_allocation_buyback_authorized_amount"), None)
        buyback_auth_rem = _safe_float(raw.get("capital_allocation_buyback_remaining_authorization"), None)
        buyback_exec_q = _safe_float(raw.get("capital_allocation_buyback_spend_q"), None)
        buyback_exec_3y = _safe_float(raw.get("capital_allocation_buyback_spend_3y"), None)
        buyback_exec_5y = _safe_float(raw.get("capital_allocation_buyback_spend_5y"), None)
        buyback_shares_ttm_pct = _safe_float(raw.get("capital_allocation_buyback_pct_shares_ttm"), None)
        buyback_share_reduction_pct = _safe_float(raw.get("capital_allocation_buyback_net_diluted_share_reduction_pct"), None)
        buyback_as_pct_sbc = _safe_float(raw.get("capital_allocation_buyback_as_pct_sbc"), None)
        buyback_fcf_used = _safe_float(raw.get("capital_allocation_buyback_fcf_used"), None)
        debt_funded_flag = raw.get("capital_allocation_buyback_debt_funded_flag")
        liquidity_strain_flag = raw.get("capital_allocation_buyback_liquidity_strain_flag")
        buyback_avg_vs_current_pct = _safe_float(raw.get("capital_allocation_buyback_avg_price_vs_current_pct"), None)
        buyback_exec_fcf_yield = _safe_float(raw.get("capital_allocation_buyback_execution_fcf_yield"), None)
        buyback_timing_accuracy = _safe_float(raw.get("capital_allocation_buyback_timing_accuracy"), None)
        buyback_fcf_ps_growth_post = _safe_float(raw.get("capital_allocation_buyback_per_share_fcf_growth_post"), None)
        buyback_eps_growth_post = _safe_float(raw.get("capital_allocation_buyback_per_share_earnings_growth_post"), None)
        buyback_iv_ps_growth_post = _safe_float(raw.get("capital_allocation_buyback_intrinsic_value_per_share_growth_post"), None)

        industry = str(context.get("industry", "") or "").lower()
        sector = str(context.get("sector", "") or "").lower()
        is_financial = bool(raw.get("capital_allocation_buyback_is_financial_company")) or any(k in f"{industry} {sector}" for k in ["bank", "insurance", "asset manager", "financial"])
        is_acquisitive = bool(raw.get("capital_allocation_buyback_is_acquisitive_company"))

        def any_present(values: Sequence[Optional[float]]) -> bool:
            return any(v is not None for v in values)

        cap_parts = []
        if reinvest is not None:
            cap_parts.append(_clamp(65.0 - max(0.0, reinvest - 0.7) * 35.0 + max(0.0, 0.7 - reinvest) * 10.0))
        if organic_eff is not None:
            cap_parts.append(_clamp(50.0 + organic_eff * 6.0))
        if debt_red is not None:
            cap_parts.append(_clamp(50.0 + debt_red * 18.0))
        capital_score = _clamp(_mean(cap_parts)) if cap_parts else None

        buyback_parts = []
        if buyback_eff is not None:
            buyback_parts.append(_clamp(50.0 + buyback_eff * 30.0))
        if share_reduction is not None:
            buyback_parts.append(_clamp(50.0 + share_reduction * 4.0))
        if sbc_offset is not None:
            buyback_parts.append(_clamp(50.0 + sbc_offset * 8.0))

        auth_parts: List[float] = []
        if raw.get("capital_allocation_buyback_authorization_status") not in (None, "", NEEDS_RESEARCH):
            auth_parts.append(70.0)
        if buyback_auth_amt is not None and buyback_auth_amt > 0:
            auth_parts.append(75.0)
        if buyback_auth_amt is not None and buyback_auth_rem is not None and buyback_auth_amt > 0:
            executed_pct = max(0.0, min(1.0, (buyback_auth_amt - buyback_auth_rem) / buyback_auth_amt))
            auth_parts.append(_clamp(45.0 + executed_pct * 55.0))
        buyback_authorization_score = _clamp(_mean(auth_parts)) if auth_parts else None

        execution_parts: List[float] = []
        if buyback_exec_q is not None:
            execution_parts.append(_clamp(40.0 + min(buyback_exec_q / 1_000_000_000.0, 2.0) * 25.0))
        if buyback_exec_3y is not None:
            execution_parts.append(_clamp(40.0 + min(buyback_exec_3y / 5_000_000_000.0, 2.0) * 25.0))
        if buyback_exec_5y is not None:
            execution_parts.append(_clamp(45.0 + min(buyback_exec_5y / 8_000_000_000.0, 2.0) * 20.0))
        buyback_execution_score = _clamp(_mean(execution_parts)) if execution_parts else None

        net_share_reduction_score = None
        if buyback_share_reduction_pct is not None:
            net_share_reduction_score = _clamp(50.0 + buyback_share_reduction_pct * 3.0)
        elif buyback_shares_ttm_pct is not None:
            net_share_reduction_score = _clamp(45.0 + buyback_shares_ttm_pct * 8.0)

        buyback_valuation_score = None
        valuation_parts: List[float] = []
        if buyback_avg_vs_current_pct is not None:
            valuation_parts.append(_clamp(55.0 + buyback_avg_vs_current_pct * 0.8))
        if buyback_exec_fcf_yield is not None:
            valuation_parts.append(_clamp(45.0 + buyback_exec_fcf_yield * 6.0))
        if valuation_parts:
            buyback_valuation_score = _clamp(_mean(valuation_parts))

        funding_parts: List[float] = []
        if buyback_fcf_used is not None:
            funding_parts.append(_clamp(80.0 - max(0.0, buyback_fcf_used - 1.0) * 30.0))
        if debt_funded_flag is not None:
            funding_parts.append(25.0 if bool(debt_funded_flag) else 80.0)
        if liquidity_strain_flag is not None:
            funding_parts.append(35.0 if bool(liquidity_strain_flag) else 75.0)
        buyback_funding_quality_score = _clamp(_mean(funding_parts)) if funding_parts else None

        buyback_sbc_offset_score = None
        if buyback_as_pct_sbc is not None:
            buyback_sbc_offset_score = _clamp(35.0 + min(buyback_as_pct_sbc, 250.0) * 0.26)
        elif sbc_offset is not None:
            buyback_sbc_offset_score = _clamp(50.0 + sbc_offset * 8.0)

        timing_parts: List[float] = []
        if buyback_timing_accuracy is not None:
            timing_parts.append(_clamp(buyback_timing_accuracy))
        if buyback_avg_vs_current_pct is not None:
            timing_parts.append(_clamp(50.0 + buyback_avg_vs_current_pct * 1.0))
        buyback_timing_score = _clamp(_mean(timing_parts)) if timing_parts else None

        effectiveness_parts: List[float] = []
        if buyback_fcf_ps_growth_post is not None:
            effectiveness_parts.append(_clamp(50.0 + buyback_fcf_ps_growth_post * 1.8))
        if buyback_eps_growth_post is not None:
            effectiveness_parts.append(_clamp(50.0 + buyback_eps_growth_post * 1.4))
        if buyback_iv_ps_growth_post is not None:
            effectiveness_parts.append(_clamp(50.0 + buyback_iv_ps_growth_post * 1.4))
        if buyback_eff is not None:
            effectiveness_parts.append(_clamp(50.0 + buyback_eff * 30.0))
        buyback_effectiveness_score = _clamp(_mean(effectiveness_parts)) if effectiveness_parts else None

        buyback_component_values = [
            buyback_authorization_score,
            buyback_execution_score,
            net_share_reduction_score,
            buyback_valuation_score,
            buyback_funding_quality_score,
            buyback_sbc_offset_score,
            buyback_timing_score,
            buyback_effectiveness_score,
        ]
        buyback_component_values = [v for v in buyback_component_values if v is not None]

        if buyback_component_values:
            buyback_score = _clamp(_mean(buyback_component_values))
        elif buyback_parts:
            buyback_score = _clamp(_mean(buyback_parts))
        else:
            buyback_score = None

        # Sector-aware adaptation: financials rely less on leverage/debt-funding penalties.
        if is_financial and buyback_funding_quality_score is not None:
            buyback_funding_quality_score = _clamp((buyback_funding_quality_score * 0.6) + 20.0)
        # Acquisitive firms should not be auto-penalized for slower net-share reduction.
        if is_acquisitive and net_share_reduction_score is not None:
            net_share_reduction_score = _clamp((net_share_reduction_score * 0.75) + 15.0)

        buyback_thesis_impact_score = None
        if buyback_score is not None:
            buyback_thesis_impact_score = _clamp((buyback_score - 50.0) * 1.2 + 50.0)

        acquisition_parts = []
        if acq_roi is not None:
            acquisition_parts.append(_clamp(50.0 + acq_roi * 8.0))
        if acq_count is not None:
            acquisition_parts.append(_clamp(60.0 - max(0.0, acq_count - 3.0) * 5.0))
        acquisition_score = _clamp(_mean(acquisition_parts)) if acquisition_parts else None

        inc_roic_score = _clamp(50.0 + (inc_roic or 0.0) * 220.0) if inc_roic is not None else None
        retained_score = _clamp(50.0 + (roe_retained or 0.0) * 180.0) if roe_retained is not None else None

        align_parts = []
        if dilution is not None:
            align_parts.append(_clamp(80.0 - max(0.0, dilution) * 2.0 + max(0.0, -dilution) * 1.0))
        if div_eff is not None:
            align_parts.append(_clamp(70.0 - max(0.0, div_eff - 60.0) * 0.7))
        if liquidity_mgmt is not None:
            align_parts.append(_clamp(45.0 + liquidity_mgmt * 25.0))
        if leverage_decisions is not None:
            align_parts.append(_clamp(70.0 - leverage_decisions * 20.0))
        if capital_consistency is not None:
            align_parts.append(_clamp(75.0 - capital_consistency * 120.0))
        shareholder_align_score = _clamp(_mean(align_parts)) if align_parts else None

        value_creation_parts = []
        for val in [bvps_growth, fcf_ps_growth, owner_growth]:
            if val is not None:
                value_creation_parts.append(_clamp(50.0 + val * 1.8))

        overall_parts = [p for p in [capital_score, buyback_score, acquisition_score, inc_roic_score, retained_score, shareholder_align_score] if p is not None]
        if value_creation_parts:
            overall_parts.append(_mean(value_creation_parts))
        overall_score = _clamp(_mean(overall_parts)) if overall_parts else 50.0

        strongest_pos = None
        strongest_neg = None
        if buyback_component_values:
            labels = [
                ("authorization", buyback_authorization_score),
                ("execution", buyback_execution_score),
                ("net share reduction", net_share_reduction_score),
                ("valuation", buyback_valuation_score),
                ("funding quality", buyback_funding_quality_score),
                ("SBC offset", buyback_sbc_offset_score),
                ("timing", buyback_timing_score),
                ("effectiveness", buyback_effectiveness_score),
            ]
            labels = [(n, v) for n, v in labels if v is not None]
            if labels:
                strongest_pos = max(labels, key=lambda t: t[1])[0]
                strongest_neg = min(labels, key=lambda t: t[1])[0]

        return {
            "capital_allocation_score": round(capital_score, 2) if capital_score is not None else None,
            "capital_allocation_buyback_quality_score": round(buyback_score, 2) if buyback_score is not None else None,
            "capital_allocation_buyback_authorization_score": round(buyback_authorization_score, 2) if buyback_authorization_score is not None else None,
            "capital_allocation_buyback_execution_score": round(buyback_execution_score, 2) if buyback_execution_score is not None else None,
            "capital_allocation_buyback_net_share_reduction_score": round(net_share_reduction_score, 2) if net_share_reduction_score is not None else None,
            "capital_allocation_buyback_valuation_score": round(buyback_valuation_score, 2) if buyback_valuation_score is not None else None,
            "capital_allocation_buyback_funding_quality_score": round(buyback_funding_quality_score, 2) if buyback_funding_quality_score is not None else None,
            "capital_allocation_buyback_sbc_offset_score": round(buyback_sbc_offset_score, 2) if buyback_sbc_offset_score is not None else None,
            "capital_allocation_buyback_timing_score": round(buyback_timing_score, 2) if buyback_timing_score is not None else None,
            "capital_allocation_buyback_effectiveness_score": round(buyback_effectiveness_score, 2) if buyback_effectiveness_score is not None else None,
            "capital_allocation_buyback_intelligence_score": round(buyback_score, 2) if buyback_score is not None else None,
            "capital_allocation_buyback_thesis_impact_score": round(buyback_thesis_impact_score, 2) if buyback_thesis_impact_score is not None else None,
            "capital_allocation_buyback_authorization_status": raw.get("capital_allocation_buyback_authorization_status"),
            "capital_allocation_buyback_evidence_trail": raw.get("capital_allocation_buyback_evidence_trail"),
            "capital_allocation_buyback_strongest_positive_evidence": strongest_pos,
            "capital_allocation_buyback_strongest_negative_evidence": strongest_neg,
            "capital_allocation_acquisition_quality_score": round(acquisition_score, 2) if acquisition_score is not None else None,
            "capital_allocation_incremental_roic_score": round(inc_roic_score, 2) if inc_roic_score is not None else None,
            "capital_allocation_retained_earnings_efficiency_score": round(retained_score, 2) if retained_score is not None else None,
            "capital_allocation_shareholder_alignment_score": round(shareholder_align_score, 2) if shareholder_align_score is not None else None,
            "capital_allocation_intelligence_score": round(overall_score, 2),
            "capital_allocation_value_creation_proxy": round(_mean(value_creation_parts), 2) if value_creation_parts else None,
        }

    def _build_explainability(self, raw: Dict[str, Any], scored: Dict[str, Any]) -> str:
        lines = ["Capital Allocation:"]
        factors = [
            ("buyback quality", scored.get("capital_allocation_buyback_quality_score")),
            ("acquisition quality", scored.get("capital_allocation_acquisition_quality_score")),
            ("incremental ROIC", scored.get("capital_allocation_incremental_roic_score")),
            ("retained earnings efficiency", scored.get("capital_allocation_retained_earnings_efficiency_score")),
            ("shareholder alignment", scored.get("capital_allocation_shareholder_alignment_score")),
        ]
        avail = [(n, v) for n, v in factors if v not in (None, NEEDS_RESEARCH)]
        if avail:
            pos = max(avail, key=lambda t: float(t[1]))
            neg = min(avail, key=lambda t: float(t[1]))
            lines.append(f"- Strongest positive factor: {pos[0]} ({float(pos[1]):.1f})")
            lines.append(f"- Strongest negative factor: {neg[0]} ({float(neg[1]):.1f})")
        if raw.get("reinvestment_rate") is not None:
            lines.append(f"- Reinvestment rate: {raw.get('reinvestment_rate'):.3f}")
        if raw.get("incremental_roic") is not None:
            lines.append(f"- Incremental ROIC: {raw.get('incremental_roic'):.3f}")
        if raw.get("share_count_reduction_trend") is not None:
            lines.append(f"- Share-count reduction trend: {raw.get('share_count_reduction_trend'):.2f}")
        if raw.get("dilution_trend") is not None:
            lines.append(f"- Dilution trend: {raw.get('dilution_trend'):.2f}")
        if scored.get("capital_allocation_buyback_intelligence_score") is not None:
            lines.append(f"- Buyback intelligence: {float(scored.get('capital_allocation_buyback_intelligence_score')):.1f}")
        if scored.get("capital_allocation_buyback_strongest_positive_evidence"):
            lines.append(f"- Strongest buyback positive evidence: {scored.get('capital_allocation_buyback_strongest_positive_evidence')}")
        if scored.get("capital_allocation_buyback_strongest_negative_evidence"):
            lines.append(f"- Strongest buyback negative evidence: {scored.get('capital_allocation_buyback_strongest_negative_evidence')}")
        if raw.get("capital_allocation_buyback_authorization_status") not in (None, "", NEEDS_RESEARCH):
            lines.append(f"- Buyback authorization status: {raw.get('capital_allocation_buyback_authorization_status')}")
        if raw.get("capital_allocation_buyback_evidence_trail") not in (None, "", NEEDS_RESEARCH):
            lines.append(f"- Buyback evidence trail: {raw.get('capital_allocation_buyback_evidence_trail')}")
        if raw.get("latest_accession_number"):
            lines.append(f"- Evidence trail: latest annual filing accn {raw.get('latest_accession_number')} filed {raw.get('latest_filing_date', 'N/A')}")
        missing = []
        for key in ["incremental_roic", "return_on_retained_earnings", "buyback_effectiveness", "acquisition_roi"]:
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
        required_keys = [
            "snapshot_date",
            "symbol",
            "capital_allocation_intelligence_score",
            "base_composite_score",
            "resolved_6m",
            "resolved_12m",
            "resolved_24m",
            "resolved_60m",
            "resolved_2y",
            "resolved_5y",
            "resolved_10y",
            "return_6m_pct",
            "return_12m_pct",
            "return_24m_pct",
            "return_60m_pct",
            "return_2y_pct",
            "return_5y_pct",
            "return_10y_pct",
            "spy_return_6m_pct",
            "spy_return_12m_pct",
            "spy_return_24m_pct",
            "spy_return_60m_pct",
            "spy_return_2y_pct",
            "spy_return_5y_pct",
            "spy_return_10y_pct",
            "excess_vs_spy_6m_pct",
            "excess_vs_spy_12m_pct",
            "excess_vs_spy_24m_pct",
            "excess_vs_spy_60m_pct",
            "excess_vs_spy_2y_pct",
            "excess_vs_spy_5y_pct",
            "excess_vs_spy_10y_pct",
            "last_evaluated_at",
        ]
        for r in existing:
            for k in required_keys:
                r.setdefault(k, "")
        seen = {(r.get("snapshot_date", ""), r.get("symbol", "")) for r in existing}
        for row in rows:
            sym = str(row.get("symbol", "")).upper()
            key = (as_of.isoformat(), sym)
            if key in seen:
                continue
            context = self.rank_context.get(sym, {})
            existing.append({
                "snapshot_date": as_of.isoformat(),
                "symbol": sym,
                "capital_allocation_intelligence_score": row.get("capital_allocation_intelligence_score", NEEDS_RESEARCH),
                "base_composite_score": context.get("composite_score", ""),
                "resolved_6m": "0",
                "resolved_12m": "0",
                "resolved_24m": "0",
                "resolved_60m": "0",
                "resolved_2y": "0",
                "resolved_5y": "0",
                "resolved_10y": "0",
                "return_6m_pct": "",
                "return_12m_pct": "",
                "return_24m_pct": "",
                "return_60m_pct": "",
                "return_2y_pct": "",
                "return_5y_pct": "",
                "return_10y_pct": "",
                "spy_return_6m_pct": "",
                "spy_return_12m_pct": "",
                "spy_return_24m_pct": "",
                "spy_return_60m_pct": "",
                "spy_return_2y_pct": "",
                "spy_return_5y_pct": "",
                "spy_return_10y_pct": "",
                "excess_vs_spy_6m_pct": "",
                "excess_vs_spy_12m_pct": "",
                "excess_vs_spy_24m_pct": "",
                "excess_vs_spy_60m_pct": "",
                "excess_vs_spy_2y_pct": "",
                "excess_vs_spy_5y_pct": "",
                "excess_vs_spy_10y_pct": "",
                "last_evaluated_at": "",
            })
        self._write_csv(OUTPUT_HISTORY_CSV, existing)

    def _resolve_history_returns(self, as_of: date) -> List[Dict[str, str]]:
        rows = self._read_csv(OUTPUT_HISTORY_CSV)
        updated: List[Dict[str, str]] = []
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
            for label, offset in [("6m", 126), ("12m", 252), ("24m", 504), ("60m", 1260)]:
                res_key = f"resolved_{label}"
                ret_key = f"return_{label}_pct"
                spy_key = f"spy_return_{label}_pct"
                ex_key = f"excess_vs_spy_{label}_pct"
                if str(out.get(res_key, "0")) == "1":
                    continue
                if as_of < snap + timedelta(days=max(365, int(offset * 0.7))):
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
        for label in ["6m", "12m", "24m", "60m"]:
            xc: List[float] = []
            xb: List[float] = []
            y: List[float] = []
            for r in rows:
                if str(r.get(f"resolved_{label}", "0")) != "1":
                    continue
                c = _safe_float(r.get("capital_allocation_intelligence_score"), None)
                b = _safe_float(r.get("base_composite_score"), None)
                ret = _safe_float(r.get(f"excess_vs_spy_{label}_pct"), None)
                if c is None or b is None or ret is None:
                    continue
                xc.append(c)
                xb.append(b)
                y.append(ret)
            if len(y) < 2:
                out.append(PredictiveStats(label, len(y), 0.0, 0.0, 0.0, 0.0))
                continue
            cic = _spearman(xc, y)
            bic = _spearman(xb, y)
            combined = [0.8 * b + 0.2 * c for b, c in zip(xb, xc)]
            comb_ic = _spearman(combined, y)
            out.append(PredictiveStats(label, len(y), cic, bic, comb_ic, comb_ic - bic))
        return out

    def _weight_recommendation(self, stats: List[PredictiveStats]) -> str:
        valid = [s for s in stats if s.resolved_count >= 20 and s.incremental_ic > 0.03]
        if not valid:
            return "No meaningful capital-allocation model weight change recommended yet: insufficient or weak out-of-sample predictive evidence."
        avg_inc = _mean([s.incremental_ic for s in valid])
        weight = min(0.08, max(0.02, avg_inc * 1.4))
        return f"Proposed capital-allocation factor weight: {weight:.2%}, conditioned on manual approval and continued walk-forward OOS validation."

    def _write_reports(self, rows: List[Dict[str, Any]], hist: List[Dict[str, str]], stats: List[PredictiveStats], recommendation: str) -> None:
        vals = [_safe_float(r.get("capital_allocation_intelligence_score"), None) for r in rows]
        vals = [v for v in vals if v is not None]
        total_slots = populated = valuable = 0
        for row in rows:
            for key, value in row.items():
                if key.endswith("_source") or key.endswith("_timestamp") or key.endswith("_confidence") or key.endswith("_stale"):
                    continue
                if key in {"symbol", "as_of", "capital_allocation_engine_version", "refresh_deferred", "sec_cik", "latest_filing_date", "latest_accession_number"}:
                    continue
                total_slots += 1
                if value != NEEDS_RESEARCH:
                    populated += 1
                    conf = _safe_float(row.get(f"{key}_confidence"), 0.0) or 0.0
                    if conf >= 60:
                        valuable += 1
        dq = (populated / total_slots * 100.0) if total_slots else 0.0
        dv = (valuable / total_slots * 100.0) if total_slots else 0.0
        top = sorted(rows, key=lambda r: _safe_float(r.get("capital_allocation_intelligence_score"), -1.0) or -1.0, reverse=True)[:10]

        lines = [
            "# Capital Allocation Report",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Data Quality Dashboard",
            "",
            f"- Universe rows: {len(rows)}",
            f"- Capital-allocation metric coverage: {dq:.2f}%",
            "",
            "## Data Value Dashboard",
            "",
            f"- High-confidence capital-allocation coverage (confidence >= 60): {dv:.2f}%",
            f"- Average Capital Allocation Intelligence Score: {_mean(vals):.2f}" if vals else "- Average Capital Allocation Intelligence Score: N/A",
            "",
            "## Explainability Report",
            "",
        ]
        for row in top:
            lines.extend([
                f"### {row.get('symbol', 'N/A')} (Capital Allocation Score: {row.get('capital_allocation_intelligence_score', NEEDS_RESEARCH)})",
                str(row.get("capital_allocation_explainability", "Capital Allocation: unavailable")),
                "",
            ])
        lines.extend([
            "## Predictive Performance (6m/12m/24m/60m)",
            "",
            "| Horizon | Resolved Samples | Capital IC | Base IC | Combined IC | Incremental IC |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for st in stats:
            lines.append(f"| {st.horizon_label} | {st.resolved_count} | {st.capital_ic:.4f} | {st.base_ic:.4f} | {st.combined_ic:.4f} | {st.incremental_ic:.4f} |")
        lines.extend(["", "## Weight Governance", "", f"- {recommendation}", "- Walk-forward validation only; no automatic production weighting changes.", ""])
        REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        as_of_date = as_of or date.today()
        symbols = self._load_target_symbols()
        rows: List[Dict[str, Any]] = []
        refresh_count = 0
        print(f"[CapitalAllocation] Target symbols: {len(symbols)} | refresh limit: {self.refresh_limit} | full universe: {self.include_full_universe}", flush=True)
        for symbol in symbols:
            has_cache = symbol in self.source.cache
            cached_ts = str((self.source.cache.get(symbol) or {}).get("timestamp", "")) if has_cache else ""
            has_fresh_cache = bool(cached_ts and self.source._cache_is_fresh(cached_ts))
            should_refresh = self.force_refresh and refresh_count < self.refresh_limit or (not self.force_refresh and (has_fresh_cache or refresh_count < self.refresh_limit))
            payload = self.source.fetch_symbol(symbol, force_refresh=self.force_refresh) if should_refresh else {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "source": "SEC XBRL Capital Allocation (refresh deferred)",
                "stale": True,
                "confidence": 0,
                "data": {},
            }
            if should_refresh and (self.force_refresh or not has_fresh_cache):
                refresh_count += 1
            raw = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
            scored = self._score_symbol(raw, self.rank_context.get(symbol, {}))
            merged = dict(raw)
            merged.update(scored)
            merged["capital_allocation_explainability"] = self._build_explainability(raw, scored)
            row = {"symbol": symbol, "as_of": as_of_date.isoformat(), "capital_allocation_engine_version": "1.0.0", "refresh_deferred": "1" if not should_refresh else "0"}
            row.update(self._build_metric_fields(merged, str(payload.get("source", self.source.name)), str(payload.get("timestamp", datetime.now().isoformat())), int(payload.get("confidence", 0)), bool(payload.get("stale", False))))
            rows.append(row)
            if len(rows) % 10 == 0 or len(rows) == len(symbols):
                print(f"[CapitalAllocation] Processed {len(rows)}/{len(symbols)} symbols", flush=True)

        output_json = {"metadata": {"timestamp": datetime.now().isoformat(), "engine": "McLeod Capital Allocation Intelligence Engine", "version": "1.0.0", "symbols": len(symbols), "rows": len(rows)}, "holdings": rows}
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output_json, f, indent=2)
        self._write_csv(OUTPUT_CSV, rows)
        self._append_history(rows, as_of_date)
        fast_mode = __import__("os").getenv(
            "CAPITAL_ALLOCATION_FAST_MODE",
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


def run_capital_allocation(as_of: Optional[date] = None) -> Dict[str, Any]:
    return CapitalAllocationEngine().run(as_of=as_of)


def main() -> int:
    result = run_capital_allocation()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
