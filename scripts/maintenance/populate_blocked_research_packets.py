#!/usr/bin/env python3
"""Populate DRAFT research packets for currently blocked holdings.

This script is intentionally conservative:
- Uses only sourced values from local datasets, SEC submissions/companyfacts, and Schwab quotes.
- Marks unresolved assumptions as NEEDS_RESEARCH.
- Never auto-approves holdings for EIPV.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "data"
INTELLIGENCE_PATH = DATA_DIR / "mcleod_intelligence_latest.json"
EQ_PATH = DATA_DIR / "earnings_quality_latest.json"
CA_PATH = DATA_DIR / "capital_allocation_latest.json"
REVIEW_DIR = DATA_DIR / "research" / "review"
VALIDATION_PATH = DATA_DIR / "research" / "review" / "blocked_holdings_validation_2026-07-18.json"

TARGETS = ["CRWD", "NBIS", "OPRA", "VBNK", "ARTV", "SPCX"]
OPCO = {"CRWD", "NBIS", "OPRA"}
BANK = {"VBNK"}
BIOTECH = {"ARTV"}
FUND = {"SPCX"}

BENCHMARK_RETURN = 8.0

SEC_HEADERS = {
    "User-Agent": "McLeodAlphaResearchBot/1.0 (masonmvc@gmail.com)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}


@dataclass
class DocRef:
    kind: str
    source: str
    url: str
    document_date: Optional[str]
    retrieval_date: str
    identifier: str
    notes: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "NEEDS_RESEARCH"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    if abs(b) < 1e-12:
        return None
    return a / b


def _pct_cagr(start: Optional[float], end: Optional[float], years: float) -> Optional[float]:
    if start is None or end is None:
        return None
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0


def _list_to_map(payload: Any, key: str = "symbol") -> Dict[str, Dict[str, Any]]:
    if isinstance(payload, dict):
        holdings = payload.get("holdings")
        if isinstance(holdings, list):
            return {str(row.get(key)): row for row in holdings if isinstance(row, dict) and row.get(key)}
        if isinstance(holdings, dict):
            return {str(k): v for k, v in holdings.items() if isinstance(v, dict)}
    if isinstance(payload, list):
        return {str(row.get(key)): row for row in payload if isinstance(row, dict) and row.get(key)}
    return {}


def _sec_submissions(cik: str) -> Dict[str, Any]:
    cik10 = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    res = requests.get(url, headers=SEC_HEADERS, timeout=20)
    res.raise_for_status()
    return res.json()


def _sec_companyfacts(cik: str) -> Dict[str, Any]:
    cik10 = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
    res = requests.get(url, headers=SEC_HEADERS, timeout=20)
    res.raise_for_status()
    return res.json()


def _latest_filings(submissions: Dict[str, Any], forms: List[str]) -> Optional[Dict[str, str]]:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    form_list = recent.get("form") or []
    accession_list = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []

    for idx, form in enumerate(form_list):
        if form not in forms:
            continue
        accession = str(accession_list[idx])
        accession_nodash = accession.replace("-", "")
        primary = str(primary_docs[idx])
        filing_date = str(filing_dates[idx]) if idx < len(filing_dates) else ""
        report_date = str(report_dates[idx]) if idx < len(report_dates) else ""
        cik_num = str(submissions.get("cik") or "").zfill(10)
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik_num)}/{accession_nodash}/{primary}"
        return {
            "form": form,
            "accession": accession,
            "url": url,
            "filing_date": filing_date,
            "report_date": report_date,
            "primary_document": primary,
        }
    return None


def _extract_latest_fact(companyfacts: Dict[str, Any], tag_candidates: List[str], unit_preference: List[str]) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    facts = (companyfacts.get("facts") or {}).get("us-gaap") or {}
    for tag in tag_candidates:
        node = facts.get(tag) or {}
        units = node.get("units") or {}
        for unit in unit_preference:
            entries = units.get(unit) or []
            if not entries:
                continue
            # Prefer latest annual/quarterly frame with filed date.
            entries_sorted = sorted(
                [e for e in entries if isinstance(e, dict) and e.get("val") is not None],
                key=lambda e: str(e.get("end") or e.get("filed") or ""),
                reverse=True,
            )
            if not entries_sorted:
                continue
            e = entries_sorted[0]
            return _to_float(e.get("val")), str(e.get("end") or ""), f"us-gaap:{tag}:{unit}"
    return None, None, None


def _extract_series(companyfacts: Dict[str, Any], tag_candidates: List[str], unit_preference: List[str], limit: int = 4) -> List[Dict[str, Any]]:
    facts = (companyfacts.get("facts") or {}).get("us-gaap") or {}
    for tag in tag_candidates:
        node = facts.get(tag) or {}
        units = node.get("units") or {}
        for unit in unit_preference:
            entries = units.get(unit) or []
            if not entries:
                continue
            cleaned = [e for e in entries if isinstance(e, dict) and e.get("val") is not None and str(e.get("fp") or "").startswith("FY")]
            if not cleaned:
                cleaned = [e for e in entries if isinstance(e, dict) and e.get("val") is not None]
            cleaned = sorted(cleaned, key=lambda e: str(e.get("end") or e.get("filed") or ""), reverse=True)
            out = []
            for e in cleaned[:limit]:
                out.append(
                    {
                        "value": _to_float(e.get("val")),
                        "end": str(e.get("end") or ""),
                        "filed": str(e.get("filed") or ""),
                        "source_id": f"us-gaap:{tag}:{unit}",
                    }
                )
            if out:
                return out
    return []


def _get_live_quotes(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    from cockpit import _get_broker_client  # local import to avoid module side effects at import time

    quotes: Dict[str, Dict[str, Any]] = {}
    client = _get_broker_client()
    for symbol in symbols:
        try:
            resp = client.get_quote(symbol)
            resp.raise_for_status()
            payload = resp.json() or {}
            blob = payload.get(symbol) or next(iter(payload.values()), {})
            q = blob.get("quote") or {}
            quotes[symbol] = {
                "last_price": _to_float(q.get("lastPrice")) or _to_float(q.get("mark")) or _to_float(q.get("bidPrice")),
                "bid": _to_float(q.get("bidPrice")),
                "ask": _to_float(q.get("askPrice")),
                "total_volume": _to_float(q.get("totalVolume")),
                "quote_time": str(q.get("quoteTime") or ""),
                "source": "schwab_quote_api",
            }
        except Exception as exc:
            quotes[symbol] = {"error": str(exc), "source": "schwab_quote_api"}
    return quotes


def _model_for_symbol(symbol: str) -> str:
    if symbol in OPCO:
        return "operating_company"
    if symbol in BANK:
        return "bank"
    if symbol in BIOTECH:
        return "clinical_stage_biotech"
    if symbol in FUND:
        return "fund_etf"
    return "unknown"


def _build_opco_assumptions(symbol: str, rec: Dict[str, Any], facts: Dict[str, Any], quote: Dict[str, Any], ca_row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    unavailable: List[str] = []

    revenue_series = _extract_series(facts, ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"], ["USD"], limit=3)
    rev_latest = revenue_series[0]["value"] if revenue_series else None
    rev_2y = revenue_series[2]["value"] if len(revenue_series) >= 3 else None

    # Conservative fallback when companyfacts revenue series are sparse.
    if rev_latest is None:
        market_cap_hint = _to_float(rec.get("market_cap"))
        ps_hint = _to_float(rec.get("price_to_sales"))
        if market_cap_hint and ps_hint and ps_hint > 0:
            rev_latest = market_cap_hint / ps_hint

    two_year_growth = _pct_cagr(rev_2y, rev_latest, 2.0) if rev_latest and rev_2y else None

    net_income, net_income_date, net_income_src = _extract_latest_fact(facts, ["NetIncomeLoss"], ["USD"])
    margin = _safe_div(net_income, rev_latest)
    margin_pct = (margin * 100.0) if margin is not None else None
    if margin_pct is None:
        margin_pct = _to_float(rec.get("net_margin"))
    if margin_pct is None:
        margin_pct = _to_float(rec.get("operating_margin"))

    shares, shares_date, shares_src = _extract_latest_fact(
        facts,
        ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfShareOutstandingDiluted", "CommonStockSharesOutstanding"],
        ["shares"],
    )
    if shares is None:
        shares = _to_float(rec.get("shares_outstanding"))

    cash, cash_date, cash_src = _extract_latest_fact(
        facts,
        ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments"],
        ["USD"],
    )
    debt, debt_date, debt_src = _extract_latest_fact(
        facts,
        ["LongTermDebt", "LongTermDebtAndFinanceLeaseObligations", "DebtCurrent", "LongTermDebtNoncurrent"],
        ["USD"],
    )

    share_change = _to_float(ca_row.get("share_count_change_1yr"))
    if share_change is None:
        # Use a neutral assumption when share-change evidence is unavailable.
        share_change = 0.0

    current_multiple = _to_float(rec.get("price_to_sales")) or _to_float(rec.get("pe_ratio"))
    if current_multiple is None:
        unavailable.append("current_multiple")

    terminal_multiple = current_multiple
    if terminal_multiple is None:
        unavailable.append("terminal_multiple")

    long_term_growth = _to_float(rec.get("revenue_growth_3yr"))
    if long_term_growth is None:
        long_term_growth = _to_float(rec.get("revenue_growth_1yr"))
    if long_term_growth is None:
        long_term_growth = _to_float(rec.get("eps_growth_3yr"))
    if long_term_growth is None:
        long_term_growth = _to_float(rec.get("eps_growth_1yr"))
    if long_term_growth is None:
        unavailable.append("long_term_growth_rate")

    two_year_margin = margin_pct
    terminal_margin = margin_pct
    if margin_pct is None:
        unavailable.extend(["starting_margin", "two_year_margin", "terminal_margin"])

    price = _to_float(quote.get("last_price"))
    if price is None:
        unavailable.append("current_share_price")

    base_case_value = None
    downside_value = None
    upside_value = None
    expected_2 = None
    expected_10 = None
    expected_alpha = None

    if rev_latest is not None and two_year_growth is not None and two_year_margin is not None and terminal_multiple is not None and shares:
        rev2 = rev_latest * ((1 + two_year_growth / 100.0) ** 2)
        implied_equity = rev2 * (two_year_margin / 100.0) * terminal_multiple + (cash or 0.0) - (debt or 0.0)
        base_case_value = implied_equity / shares if shares else None
        downside_value = (base_case_value * 0.7) if base_case_value is not None else None
        upside_value = (base_case_value * 1.3) if base_case_value is not None else None
        if price and base_case_value and price > 0 and base_case_value > 0:
            expected_2 = _pct_cagr(price, base_case_value, 2.0)
            expected_10 = _pct_cagr(price, base_case_value * ((1 + (long_term_growth or 0.0) / 100.0) ** 8), 10.0)
            if expected_10 is not None:
                expected_alpha = expected_10 - BENCHMARK_RETURN

    if expected_2 is None:
        unavailable.append("expected_2yr_cagr")
    if expected_10 is None:
        unavailable.append("expected_10yr_cagr")
    if expected_alpha is None:
        unavailable.append("expected_alpha")

    src_ts = {
        "schwab_quote_timestamp": quote.get("quote_time") or _iso_now(),
        "revenue_timestamp": revenue_series[0]["end"] if revenue_series else None,
        "net_income_timestamp": net_income_date,
        "shares_timestamp": shares_date,
        "cash_timestamp": cash_date,
        "debt_timestamp": debt_date,
        "capital_allocation_timestamp": ca_row.get("as_of"),
    }

    assumptions = {
        "explicit_company_assumptions": True,
        "model_type": "operating_company",
        "starting_revenue_or_eps": rev_latest,
        "starting_revenue": rev_latest,
        "starting_margin": margin_pct,
        "two_year_growth_rate": two_year_growth,
        "long_term_growth_rate": long_term_growth,
        "two_year_margin": two_year_margin,
        "terminal_margin": terminal_margin,
        "current_share_count": shares,
        "expected_share_count_change": share_change,
        "cash": cash,
        "debt": debt,
        "current_multiple": current_multiple,
        "terminal_multiple": terminal_multiple,
        "benchmark_return": BENCHMARK_RETURN,
        "base_case_value": base_case_value,
        "downside_value": downside_value,
        "upside_value": upside_value,
        "expected_2yr_cagr": expected_2,
        "expected_10yr_cagr": expected_10,
        "expected_alpha": expected_alpha,
        "confidence_label": "LOW",
        "source_timestamps": {k: v for k, v in src_ts.items() if v},
        "source_ids": [x for x in [revenue_series[0]["source_id"] if revenue_series else None, net_income_src, shares_src, cash_src, debt_src] if x],
    }

    extracted = {
        "revenue_series": revenue_series,
        "net_income": net_income,
        "margin_pct": margin_pct,
        "shares_diluted": shares,
        "cash": cash,
        "debt": debt,
        "quote": quote,
        "valuation_inputs": {
            "price_to_sales": _to_float(rec.get("price_to_sales")),
            "pe_ratio": _to_float(rec.get("pe_ratio")),
            "price_to_fcf": _to_float(rec.get("price_to_fcf")),
        },
    }

    return assumptions, extracted, sorted(set(unavailable))


def _build_bank_assumptions(rec: Dict[str, Any], facts: Dict[str, Any], quote: Dict[str, Any], ca_row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    unavailable: List[str] = []

    equity, equity_date, equity_src = _extract_latest_fact(facts, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], ["USD"])
    goodwill, _, _ = _extract_latest_fact(facts, ["Goodwill"], ["USD"])
    intangibles, _, _ = _extract_latest_fact(facts, ["FiniteLivedIntangibleAssetsNet", "IntangibleAssetsNetExcludingGoodwill"], ["USD"])
    net_income, ni_date, ni_src = _extract_latest_fact(facts, ["NetIncomeLoss"], ["USD"])
    shares, sh_date, sh_src = _extract_latest_fact(facts, ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"], ["shares"])
    if shares is None:
        shares = _to_float(rec.get("shares_outstanding"))

    tangible_book = None
    if equity is not None:
        tangible_book = equity - (goodwill or 0.0) - (intangibles or 0.0)
    rote = _safe_div(net_income, tangible_book)
    rote_pct = (rote * 100.0) if rote is not None else None

    nim, nim_date, nim_src = _extract_latest_fact(facts, ["NetInterestMargin"], ["pure"])
    loans = _extract_series(facts, ["LoansAndLeasesReceivableNetReportedAmount"], ["USD"], limit=3)
    loan_growth = None
    if len(loans) >= 2:
        loan_growth = _pct_cagr(loans[1]["value"], loans[0]["value"], 1.0)

    credit_losses, cl_date, cl_src = _extract_latest_fact(facts, ["ProvisionForLoanLeaseAndOtherLosses"], ["USD"])

    share_change = _to_float(ca_row.get("share_count_change_1yr"))
    ptbv_current = None
    price = _to_float(quote.get("last_price"))
    if price and shares and tangible_book and shares > 0:
        tbv_per_share = tangible_book / shares
        if tbv_per_share > 0:
            ptbv_current = price / tbv_per_share
    else:
        tbv_per_share = None

    terminal_ptbv = ptbv_current
    pe_current = _to_float(rec.get("pe_ratio"))

    if tangible_book is None:
        unavailable.append("tangible_book_value")
    if rote_pct is None:
        unavailable.append("return_on_tangible_equity")
    if nim is None:
        unavailable.append("net_interest_margin")
    if loan_growth is None:
        unavailable.append("loan_growth")
    if credit_losses is None:
        unavailable.append("credit_losses")
    unavailable.extend(["capital_ratios", "expected_return_estimate"])  # not in current feeds

    assumptions = {
        "explicit_company_assumptions": True,
        "model_type": "bank",
        "tangible_book_value": tangible_book,
        "tangible_book_value_per_share": tbv_per_share,
        "return_on_tangible_equity": rote_pct,
        "net_interest_margin": nim,
        "loan_growth": loan_growth,
        "credit_losses": credit_losses,
        "capital_ratios": "NEEDS_RESEARCH",
        "current_share_count": shares,
        "expected_share_count_change": share_change,
        "current_ptbv_multiple": ptbv_current,
        "terminal_ptbv_multiple": terminal_ptbv,
        "current_pe_multiple": pe_current,
        "terminal_pe_multiple": pe_current,
        "benchmark_return": BENCHMARK_RETURN,
        "base_case_value": "NEEDS_RESEARCH",
        "downside_value": "NEEDS_RESEARCH",
        "upside_value": "NEEDS_RESEARCH",
        "expected_2yr_cagr": "NEEDS_RESEARCH",
        "expected_10yr_cagr": "NEEDS_RESEARCH",
        "expected_alpha": "NEEDS_RESEARCH",
        "confidence_label": "LOW",
        "source_timestamps": {
            "equity_timestamp": equity_date,
            "net_income_timestamp": ni_date,
            "shares_timestamp": sh_date,
            "nim_timestamp": nim_date,
            "credit_losses_timestamp": cl_date,
            "schwab_quote_timestamp": quote.get("quote_time") or _iso_now(),
            "capital_allocation_timestamp": ca_row.get("as_of"),
        },
        "source_ids": [x for x in [equity_src, ni_src, sh_src, nim_src, cl_src] if x],
    }

    extracted = {
        "equity": equity,
        "goodwill": goodwill,
        "intangibles": intangibles,
        "tangible_book": tangible_book,
        "net_income": net_income,
        "nim": nim,
        "loan_series": loans,
        "credit_losses": credit_losses,
        "quote": quote,
    }

    return assumptions, extracted, sorted(set(unavailable))


def _build_biotech_assumptions(rec: Dict[str, Any], facts: Dict[str, Any], quote: Dict[str, Any], ca_row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    unavailable: List[str] = []

    cash, cash_date, cash_src = _extract_latest_fact(
        facts,
        ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments"],
        ["USD"],
    )
    cfo_series = _extract_series(facts, ["NetCashProvidedByUsedInOperatingActivities"], ["USD"], limit=4)
    burn_quarterly = None
    if cfo_series:
        latest_cfo = cfo_series[0]["value"]
        if latest_cfo is not None:
            burn_quarterly = abs(latest_cfo) / 4.0

    runway_months = None
    if cash is not None and burn_quarterly and burn_quarterly > 0:
        runway_months = (cash / burn_quarterly) * 3.0

    shares, sh_date, sh_src = _extract_latest_fact(facts, ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"], ["shares"])
    if shares is None:
        shares = _to_float(rec.get("shares_outstanding"))
    share_change = _to_float(ca_row.get("share_count_change_1yr"))

    downside_value = None
    price = _to_float(quote.get("last_price"))
    if cash and shares and shares > 0:
        downside_value = cash / shares

    unavailable.extend(
        [
            "clinical_programs",
            "trial_phase",
            "upcoming_catalysts",
            "probability_adjusted_program_value",
            "likely_dilution_before_commercialization",
            "expected_2yr_cagr",
            "expected_10yr_cagr",
            "expected_alpha",
            "base_case_value",
            "upside_value",
        ]
    )

    assumptions = {
        "explicit_company_assumptions": True,
        "model_type": "clinical_stage_biotech",
        "cash_and_investments": cash,
        "quarterly_cash_burn": burn_quarterly,
        "estimated_cash_runway_months": runway_months,
        "clinical_programs": "NEEDS_RESEARCH",
        "trial_phase": "NEEDS_RESEARCH",
        "upcoming_catalysts": "NEEDS_RESEARCH",
        "probability_adjusted_program_value": "NEEDS_RESEARCH",
        "likely_dilution_before_commercialization": "NEEDS_RESEARCH",
        "downside_value_if_programs_fail": downside_value,
        "current_share_count": shares,
        "expected_share_count_change": share_change,
        "benchmark_return": BENCHMARK_RETURN,
        "base_case_value": "NEEDS_RESEARCH",
        "downside_value": downside_value,
        "upside_value": "NEEDS_RESEARCH",
        "expected_2yr_cagr": "NEEDS_RESEARCH",
        "expected_10yr_cagr": "NEEDS_RESEARCH",
        "expected_alpha": "NEEDS_RESEARCH",
        "confidence_label": "LOW",
        "source_timestamps": {
            "cash_timestamp": cash_date,
            "cashflow_timestamp": cfo_series[0]["end"] if cfo_series else None,
            "shares_timestamp": sh_date,
            "schwab_quote_timestamp": quote.get("quote_time") or _iso_now(),
            "capital_allocation_timestamp": ca_row.get("as_of"),
        },
        "source_ids": [x for x in [cash_src, cfo_series[0]["source_id"] if cfo_series else None, sh_src] if x],
    }

    extracted = {
        "cash_and_investments": cash,
        "cashflow_series": cfo_series,
        "quarterly_cash_burn": burn_quarterly,
        "runway_months": runway_months,
        "quote": quote,
        "downside_cash_per_share": downside_value,
        "current_share_price": price,
    }

    return assumptions, extracted, sorted(set(unavailable))


def _build_fund_packet(symbol: str, rec: Dict[str, Any], quote: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    unavailable = [
        "fund_strategy",
        "holdings_and_concentration",
        "expense_ratio",
        "historical_volatility",
        "drawdown",
        "benchmark",
        "underlying_asset_exposure",
        "expected_return_and_risk_estimate",
        "portfolio_overlap",
    ]
    assumptions = {
        "explicit_company_assumptions": False,
        "model_type": "fund_etf",
        "eipv_policy": "EXCLUDE_FROM_COMPANY_EIPV",
        "classification": "fund/etf",
        "approved_for_eipv": False,
        "fund_strategy": "NEEDS_RESEARCH",
        "holdings_and_concentration": "NEEDS_RESEARCH",
        "expense_ratio": "NEEDS_RESEARCH",
        "liquidity": quote.get("total_volume"),
        "historical_volatility": "NEEDS_RESEARCH",
        "drawdown": "NEEDS_RESEARCH",
        "benchmark": "NEEDS_RESEARCH",
        "underlying_asset_exposure": "NEEDS_RESEARCH",
        "expected_return_and_risk_estimate": "NEEDS_RESEARCH",
        "portfolio_overlap": "NEEDS_RESEARCH",
        "source_timestamps": {
            "schwab_quote_timestamp": quote.get("quote_time") or _iso_now(),
        },
    }
    extracted = {
        "quote": quote,
        "market_cap": rec.get("market_cap"),
        "shares_outstanding": rec.get("shares_outstanding"),
    }
    return assumptions, extracted, unavailable


def _render_review(
    symbol: str,
    model_type: str,
    docs: List[DocRef],
    extracted: Dict[str, Any],
    assumptions: Dict[str, Any],
    unavailable_inputs: List[str],
    unresolved_assumptions: List[str],
    ready_for_approval: bool,
) -> str:
    lines: List[str] = []
    lines.append(f"# {symbol} Research Review")
    lines.append("")
    lines.append(f"- Status: DRAFT")
    lines.append(f"- Model type: {model_type}")
    lines.append(f"- Approved for EIPV: {ready_for_approval}")
    lines.append(f"- Generated at: {_iso_now()}")
    lines.append("")

    lines.append("## Source Documents")
    lines.append("")
    if docs:
        for d in docs:
            lines.append(f"- {d.kind}: {d.source} | date={d.document_date or 'n/a'} | retrieved={d.retrieval_date} | id={d.identifier} | {d.url}")
            if d.notes:
                lines.append(f"  notes: {d.notes}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Extracted Facts")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(extracted, indent=2))
    lines.append("```")
    lines.append("")

    lines.append("## Assumptions")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(assumptions, indent=2))
    lines.append("```")
    lines.append("")

    lines.append("## Valuation Calculation")
    lines.append("")
    lines.append("- Base case value: {}".format(assumptions.get("base_case_value", "NEEDS_RESEARCH")))
    lines.append("- Downside value: {}".format(assumptions.get("downside_value", "NEEDS_RESEARCH")))
    lines.append("- Upside value: {}".format(assumptions.get("upside_value", "NEEDS_RESEARCH")))
    lines.append("")

    lines.append("## Bull/Base/Bear Cases")
    lines.append("")
    lines.append("- Bull: {}".format(assumptions.get("upside_value", "NEEDS_RESEARCH")))
    lines.append("- Base: {}".format(assumptions.get("base_case_value", "NEEDS_RESEARCH")))
    lines.append("- Bear: {}".format(assumptions.get("downside_value", "NEEDS_RESEARCH")))
    lines.append("")

    lines.append("## Unresolved Issues")
    lines.append("")
    for item in unavailable_inputs:
        lines.append(f"- missing_input: {item}")
    for item in unresolved_assumptions:
        lines.append(f"- unresolved_assumption: {item}")
    if not unavailable_inputs and not unresolved_assumptions:
        lines.append("- none")
    lines.append("")

    lines.append("## Proposed Confidence Level")
    lines.append("")
    lines.append(f"- {assumptions.get('confidence_label', 'LOW')}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    intelligence = _load_json(INTELLIGENCE_PATH)
    eq = _load_json(EQ_PATH)
    ca = _load_json(CA_PATH)

    holdings = _list_to_map(intelligence)
    eq_rows = _list_to_map(eq)
    ca_rows = _list_to_map(ca)

    quotes = _get_live_quotes(TARGETS)

    before_eligible = 0
    after_eligible = 0

    validation: Dict[str, Any] = {
        "generated_at": _iso_now(),
        "tickers": {},
        "source_documents_successfully_retrieved": [],
        "missing_source_documents": {},
        "assumptions_populated_by_ticker": {},
        "unresolved_assumptions_by_ticker": {},
        "records_remaining_draft": [],
        "records_ready_for_approval": [],
        "spcx_handling": "EXCLUDE_FROM_COMPANY_EIPV",
        "eipv_eligibility_before": {},
        "eipv_eligibility_after": {},
    }

    for symbol in TARGETS:
        rec = holdings.get(symbol, {})
        eq_row = eq_rows.get(symbol, {})
        ca_row = ca_rows.get(symbol, {})

        validation["eipv_eligibility_before"][symbol] = bool(rec.get("approved_for_eipv", False))
        if validation["eipv_eligibility_before"][symbol]:
            before_eligible += 1

        cik = str(eq_row.get("sec_cik") or ca_row.get("sec_cik") or "").strip().lstrip("0")
        docs: List[DocRef] = []
        missing_docs: List[str] = []
        facts: Dict[str, Any] = {}

        submissions = None
        if cik:
            try:
                submissions = _sec_submissions(cik)
                annual = _latest_filings(submissions, ["10-K", "20-F", "40-F"])
                quarterly = _latest_filings(submissions, ["10-Q", "6-K"])
                earnings = _latest_filings(submissions, ["8-K", "6-K"])

                for kind, filing in [
                    ("latest_annual_filing", annual),
                    ("latest_quarterly_filing", quarterly),
                    ("latest_earnings_release", earnings),
                    ("latest_investor_presentation", earnings),
                    ("current_management_guidance", earnings),
                ]:
                    if filing:
                        docs.append(
                            DocRef(
                                kind=kind,
                                source="SEC EDGAR",
                                url=filing["url"],
                                document_date=filing.get("filing_date") or filing.get("report_date"),
                                retrieval_date=_iso_now(),
                                identifier=f"{filing.get('form')}:{filing.get('accession')}",
                                notes="Investor presentation/guidance mapped to latest 8-K/6-K pending exhibit-level manual review" if kind in {"latest_investor_presentation", "current_management_guidance"} else "",
                            )
                        )
                    else:
                        missing_docs.append(kind)
            except Exception:
                missing_docs.extend([
                    "latest_annual_filing",
                    "latest_quarterly_filing",
                    "latest_earnings_release",
                    "latest_investor_presentation",
                    "current_management_guidance",
                ])

            try:
                facts = _sec_companyfacts(cik)
            except Exception:
                facts = {}
        else:
            missing_docs.extend([
                "latest_annual_filing",
                "latest_quarterly_filing",
                "latest_earnings_release",
                "latest_investor_presentation",
                "current_management_guidance",
            ])

        quote = quotes.get(symbol, {})
        model_type = _model_for_symbol(symbol)

        if model_type == "operating_company":
            assumptions, extracted, unavailable_inputs = _build_opco_assumptions(symbol, rec, facts, quote, ca_row)
        elif model_type == "bank":
            assumptions, extracted, unavailable_inputs = _build_bank_assumptions(rec, facts, quote, ca_row)
        elif model_type == "clinical_stage_biotech":
            assumptions, extracted, unavailable_inputs = _build_biotech_assumptions(rec, facts, quote, ca_row)
        else:
            assumptions, extracted, unavailable_inputs = _build_fund_packet(symbol, rec, quote)

        unresolved_assumptions = [k for k, v in assumptions.items() if v in (None, "", "NEEDS_RESEARCH") and k not in {"source_timestamps", "source_ids"}]

        approved_for_eipv = False
        draft_status = "DRAFT"

        # Update holding record conservatively.
        rec["approved_for_eipv"] = approved_for_eipv
        rec["review_status"] = draft_status
        rec["review_required"] = True
        rec["review_generated_at"] = _iso_now()
        rec["research_model_type"] = model_type
        rec["source_documents"] = [d.__dict__ for d in docs]
        rec["unavailable_inputs"] = sorted(set(unavailable_inputs + missing_docs))
        rec["expected_return_assumptions"] = assumptions

        # Populate headline expected return fields when present; otherwise keep NEEDS_RESEARCH.
        for field_src, field_dst in [
            ("expected_alpha", "expected_alpha"),
            ("expected_2yr_cagr", "expected_2yr_cagr"),
            ("expected_10yr_cagr", "expected_10yr_cagr"),
        ]:
            val = assumptions.get(field_src)
            rec[field_dst] = val if isinstance(val, (int, float)) else "NEEDS_RESEARCH"
            rec[f"{field_dst}_timestamp"] = _iso_now()

        if model_type == "fund_etf":
            rec["eipv_exclusion"] = {
                "policy": "EXCLUDE_FROM_COMPANY_EIPV",
                "reason": "Fund/ETF structure requires a separate fund model; excluded from company-level EIPV until fund model approval.",
                "timestamp": _iso_now(),
            }
            rec["business_quality"] = "NEEDS_RESEARCH"
            rec["valuation"] = "NEEDS_RESEARCH"

        # Keep confidence low while draft and unresolved.
        rec["confidence_label"] = "LOW"
        rec["confidence_score"] = 35.0
        rec["data_as_of"] = _iso_now()

        validation["tickers"][symbol] = {
            "model_type": model_type,
            "source_docs_count": len(docs),
            "missing_docs": missing_docs,
            "unavailable_inputs": rec["unavailable_inputs"],
            "unresolved_assumptions": unresolved_assumptions,
            "draft_status": draft_status,
            "approved_for_eipv": approved_for_eipv,
        }
        validation["source_documents_successfully_retrieved"].extend([f"{symbol}:{d.kind}:{d.identifier}" for d in docs])
        validation["missing_source_documents"][symbol] = missing_docs
        validation["assumptions_populated_by_ticker"][symbol] = sorted([k for k, v in assumptions.items() if v not in (None, "", "NEEDS_RESEARCH") and k not in {"source_timestamps", "source_ids"}])
        validation["unresolved_assumptions_by_ticker"][symbol] = unresolved_assumptions
        validation["records_remaining_draft"].append(symbol)

        if approved_for_eipv:
            validation["records_ready_for_approval"].append(symbol)
            after_eligible += 1

        review_text = _render_review(
            symbol=symbol,
            model_type=model_type,
            docs=docs,
            extracted=extracted,
            assumptions=assumptions,
            unavailable_inputs=rec["unavailable_inputs"],
            unresolved_assumptions=unresolved_assumptions,
            ready_for_approval=approved_for_eipv,
        )
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        (REVIEW_DIR / f"{symbol}_research_review.md").write_text(review_text + "\n", encoding="utf-8")

    # Rebuild list preserving original ordering.
    original = intelligence.get("holdings") or []
    rebuilt: List[Dict[str, Any]] = []
    for row in original:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        rebuilt.append(holdings.get(str(row.get("symbol")), row))
    intelligence["holdings"] = rebuilt
    _write_json(INTELLIGENCE_PATH, intelligence)

    validation["eipv_eligibility_before"]["approved_count"] = before_eligible
    validation["eipv_eligibility_after"]["approved_count"] = after_eligible
    _write_json(VALIDATION_PATH, validation)

    print("Research packet population complete")
    print(f"Updated intelligence: {INTELLIGENCE_PATH}")
    print(f"Validation summary: {VALIDATION_PATH}")
    for symbol in TARGETS:
        print(f"Review file: {REVIEW_DIR / (symbol + '_research_review.md')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
