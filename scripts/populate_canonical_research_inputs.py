#!/usr/bin/env python3
"""Populate canonical research records for current equity holdings.

This script reuses existing validated data files and writes assumption-backed
canonical records into data/mcleod_intelligence_latest.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PORTFOLIO_PATH = DATA_DIR / "schwab_portfolio_latest.json"
INTELLIGENCE_PATH = DATA_DIR / "mcleod_intelligence_latest.json"
SEC_PATH = DATA_DIR / "sec_fundamentals_latest.json"
EARNINGS_QUALITY_PATH = DATA_DIR / "earnings_quality_latest.json"
CAPITAL_ALLOCATION_PATH = DATA_DIR / "capital_allocation_latest.json"
EARNINGS_CALL_PATH = DATA_DIR / "earnings_call_intelligence_latest.json"
OUTPUT_SUMMARY_PATH = DATA_DIR / "canonical_research_population_summary_latest.json"

BENCHMARK_RETURN_PCT = 8.0


@dataclass
class ConfidenceResult:
    label: str
    score: float
    rationale: str


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "NEEDS_RESEARCH"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _age_hours(value: Any, now: datetime) -> Optional[float]:
    parsed = _parse_ts(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now.astimezone(parsed.tzinfo) - parsed).total_seconds() / 3600.0)


def _first_non_null(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", "NEEDS_RESEARCH"):
            return value
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _confidence_label(score: float) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    if score >= 35:
        return "LOW"
    return "UNAVAILABLE"


def _business_quality_components(record: Dict[str, Any], eq_row: Dict[str, Any], ca_row: Dict[str, Any]) -> Tuple[float, Dict[str, Any], List[Dict[str, Any]]]:
    roic = _to_float(record.get("roic"))
    fcf_conv = _to_float(_first_non_null(eq_row.get("cash_conversion_fcf_net_income"), record.get("cash_conversion_fcf_net_income")))
    op_margin = _to_float(record.get("operating_margin"))
    rev_growth = _to_float(_first_non_null(record.get("revenue_growth_3yr"), record.get("revenue_growth_1yr")))
    debt_to_equity = _to_float(record.get("debt_to_equity"))
    current_ratio = _to_float(record.get("current_ratio"))
    competitive = _to_float(record.get("earnings_call_competitive_position_score"))
    customer_concentration = _to_float(eq_row.get("customer_concentration"))
    capital_allocation = _to_float(_first_non_null(ca_row.get("capital_allocation_score"), record.get("capital_allocation_score")))

    missing: List[Dict[str, Any]] = []

    def ensure(value: Optional[float], assumption: str, expected_source: str, blocks: bool) -> float:
        if value is None:
            missing.append(
                {
                    "missing_assumption": assumption,
                    "expected_source": expected_source,
                    "age_of_latest_available_input_hours": None,
                    "blocks_eipv": blocks,
                    "next_action": f"Populate {assumption} in the {expected_source} pipeline.",
                }
            )
            return 50.0
        return value

    roic_score = _clamp(ensure(roic, "roic", "sec_fundamentals_latest.json / mcleod_intelligence_latest.json", False) * 4.0, 0.0, 100.0)
    fcf_quality_score = _clamp((ensure(fcf_conv, "free_cash_flow_quality", "earnings_quality_latest.json", False) + 0.2) * 55.0, 0.0, 100.0)
    margin_stability_score = _clamp((ensure(op_margin, "margin_stability", "sec_fundamentals_latest.json / mcleod_intelligence_latest.json", False) + 5.0) * 2.5, 0.0, 100.0)
    revenue_durability_score = _clamp((ensure(rev_growth, "revenue_durability", "sec_fundamentals_latest.json / mcleod_intelligence_latest.json", False) + 15.0) * 2.5, 0.0, 100.0)

    bs_de = ensure(debt_to_equity, "balance_sheet_leverage", "sec_fundamentals_latest.json / mcleod_intelligence_latest.json", False)
    bs_cr = ensure(current_ratio, "balance_sheet_liquidity", "sec_fundamentals_latest.json / mcleod_intelligence_latest.json", False)
    balance_sheet_score = _clamp((100.0 - (bs_de * 25.0)) * 0.6 + _clamp(bs_cr * 30.0, 0.0, 100.0) * 0.4, 0.0, 100.0)

    competitive_position_score = _clamp(ensure(competitive, "competitive_position", "earnings_call_intelligence_latest.json", False), 0.0, 100.0)
    if competitive is None:
        signal = str(record.get("earnings_call_thesis_signal") or "").strip().lower()
        if signal == "stable thesis":
            competitive_position_score = 60.0

    if customer_concentration is None:
        customer_concentration_score = 50.0
        missing.append(
            {
                "missing_assumption": "customer_concentration",
                "expected_source": "earnings_quality_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": False,
                "next_action": "Populate customer concentration fields from latest SEC filing notes.",
            }
        )
    else:
        customer_concentration_score = _clamp(100.0 - customer_concentration, 0.0, 100.0)

    capital_allocation_score = _clamp(ensure(capital_allocation, "capital_allocation", "capital_allocation_latest.json", False), 0.0, 100.0)

    weights = {
        "roic": 0.20,
        "free_cash_flow_quality": 0.15,
        "margin_stability": 0.12,
        "revenue_durability": 0.12,
        "balance_sheet": 0.14,
        "competitive_position": 0.12,
        "customer_concentration": 0.07,
        "capital_allocation": 0.08,
    }

    component_values = {
        "roic": roic_score,
        "free_cash_flow_quality": fcf_quality_score,
        "margin_stability": margin_stability_score,
        "revenue_durability": revenue_durability_score,
        "balance_sheet": balance_sheet_score,
        "competitive_position": competitive_position_score,
        "customer_concentration": customer_concentration_score,
        "capital_allocation": capital_allocation_score,
    }

    total = sum(component_values[name] * weights[name] for name in weights)
    return round(total, 2), {"weights": weights, "components": component_values}, missing


def _build_forecast(record: Dict[str, Any], now: datetime) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    missing: List[Dict[str, Any]] = []
    market_cap = _to_float(record.get("market_cap"))
    price_to_sales = _to_float(record.get("price_to_sales"))
    pe_ratio = _to_float(record.get("pe_ratio"))
    net_margin_pct = _to_float(_first_non_null(record.get("net_margin"), record.get("operating_margin")))
    rev_growth = _to_float(_first_non_null(record.get("revenue_growth_3yr"), record.get("revenue_growth_1yr"), record.get("eps_growth_3yr"), record.get("eps_growth_1yr")))

    if market_cap is None:
        missing.append(
            {
                "missing_assumption": "market_cap",
                "expected_source": "mcleod_intelligence_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": True,
                "next_action": "Populate market_cap from SEC/XBRL snapshot refresh.",
            }
        )

    if rev_growth is None:
        missing.append(
            {
                "missing_assumption": "growth_rate",
                "expected_source": "sec_fundamentals_latest.json / mcleod_intelligence_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": True,
                "next_action": "Populate at least one revenue/eps growth field for this ticker.",
            }
        )

    if net_margin_pct is None:
        missing.append(
            {
                "missing_assumption": "margin_path",
                "expected_source": "sec_fundamentals_latest.json / mcleod_intelligence_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": True,
                "next_action": "Populate net_margin or operating_margin from fundamentals feed.",
            }
        )

    if market_cap is None or rev_growth is None or net_margin_pct is None:
        return None, missing

    net_margin = net_margin_pct / 100.0
    if abs(net_margin) < 1e-8:
        net_margin = 0.02
        missing.append(
            {
                "missing_assumption": "nonzero_margin_floor",
                "expected_source": "sec_fundamentals_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": True,
                "next_action": "Replace margin floor with reported trailing margin once available.",
            }
        )

    starting_revenue = None
    if price_to_sales and price_to_sales > 0:
        starting_revenue = market_cap / price_to_sales

    if starting_revenue is None:
        if pe_ratio and pe_ratio > 0:
            implied_earnings = market_cap / pe_ratio
            starting_revenue = implied_earnings / max(0.02, abs(net_margin))
            missing.append(
                {
                    "missing_assumption": "starting_revenue_direct",
                    "expected_source": "price_to_sales in mcleod_intelligence_latest.json",
                    "age_of_latest_available_input_hours": None,
                    "blocks_eipv": False,
                    "next_action": "Add direct price_to_sales so starting revenue is directly observable.",
                }
            )
        else:
            missing.append(
                {
                    "missing_assumption": "starting_revenue",
                    "expected_source": "market_cap + price_to_sales from mcleod_intelligence_latest.json",
                    "age_of_latest_available_input_hours": None,
                    "blocks_eipv": True,
                    "next_action": "Populate price_to_sales or pe_ratio for this ticker.",
                }
            )
            return None, missing

    terminal_multiple = pe_ratio if pe_ratio and pe_ratio > 0 else (price_to_sales / max(0.02, abs(net_margin)) if price_to_sales else None)
    if terminal_multiple is None:
        missing.append(
            {
                "missing_assumption": "terminal_multiple",
                "expected_source": "pe_ratio from mcleod_intelligence_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": True,
                "next_action": "Populate pe_ratio or equivalent valuation multiple.",
            }
        )
        return None, missing

    share_count_change = _to_float(_first_non_null(
        record.get("capital_allocation_buyback_diluted_share_change_pct"),
        record.get("capital_allocation_buyback_basic_share_change_pct"),
        record.get("capital_allocation_buyback_net_diluted_share_reduction_pct"),
    ))
    share_count_estimated = share_count_change is None
    if share_count_change is None:
        share_count_change = 0.0
        missing.append(
            {
                "missing_assumption": "share_count_change",
                "expected_source": "capital_allocation_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": False,
                "next_action": "Populate diluted/basic share change percentages from SEC filings.",
            }
        )

    debt_to_equity = _to_float(record.get("debt_to_equity"))
    net_debt_haircut = _clamp((debt_to_equity or 0.0) * 0.02, 0.0, 0.20)
    if debt_to_equity is None:
        missing.append(
            {
                "missing_assumption": "net_debt_adjustment",
                "expected_source": "sec_fundamentals_latest.json / mcleod_intelligence_latest.json",
                "age_of_latest_available_input_hours": None,
                "blocks_eipv": False,
                "next_action": "Populate debt_to_equity or net debt fields for explicit net debt adjustment.",
            }
        )

    dividend_yield = _to_float(record.get("dividend_yield")) or 0.0

    def scenario(years: int, growth_shift: float, margin_shift: float, multiple_shift: float) -> float:
        growth = _clamp((rev_growth + growth_shift) / 100.0, -0.30, 0.60)
        margin = _clamp(net_margin + margin_shift, -0.20, 0.60)
        terminal = _clamp(terminal_multiple * multiple_shift, 1.0, 150.0)

        forecast_revenue = starting_revenue * ((1.0 + growth) ** years)
        forecast_earnings = forecast_revenue * margin
        expected_equity_value = forecast_earnings * terminal
        expected_equity_value *= (1.0 - net_debt_haircut)
        expected_equity_value *= max(0.70, 1.0 - ((share_count_change / 100.0) * years))
        expected_equity_value *= (1.0 + ((dividend_yield / 100.0) * years))

        if expected_equity_value <= 0 or market_cap <= 0:
            return -100.0
        return (((expected_equity_value / market_cap) ** (1.0 / years)) - 1.0) * 100.0

    base_2y = scenario(2, 0.0, 0.0, 1.0)
    base_10y = scenario(10, 0.0, 0.0, 1.0)
    down_2y = scenario(2, -4.0, -0.02, 0.80)
    down_10y = scenario(10, -4.0, -0.02, 0.80)
    up_2y = scenario(2, 4.0, 0.02, 1.20)
    up_10y = scenario(10, 4.0, 0.02, 1.20)

    expected_alpha = base_2y - BENCHMARK_RETURN_PCT

    assumptions = {
        "explicit_company_assumptions": True,
        "model": "expected_equity_value = forecast_revenue * expected_margin * terminal_multiple adjusted for dilution, net debt, and dividends",
        "starting_revenue": round(starting_revenue, 4),
        "growth_rate_pct": round(rev_growth, 4),
        "margin_path_pct": round(net_margin * 100.0, 4),
        "share_count_change_pct": round(share_count_change, 4),
        "terminal_multiple": round(terminal_multiple, 4),
        "benchmark_return_pct": BENCHMARK_RETURN_PCT,
        "valuation_date": now.date().isoformat(),
        "source_timestamps": {
            "market_cap_timestamp": record.get("market_cap_timestamp"),
            "price_to_sales_timestamp": record.get("price_to_sales_timestamp"),
            "pe_ratio_timestamp": record.get("pe_ratio_timestamp"),
            "growth_timestamp": _first_non_null(record.get("revenue_growth_3yr_timestamp"), record.get("revenue_growth_1yr_timestamp"), record.get("eps_growth_3yr_timestamp"), record.get("eps_growth_1yr_timestamp")),
            "margin_timestamp": _first_non_null(record.get("net_margin_timestamp"), record.get("operating_margin_timestamp")),
            "share_count_timestamp": _first_non_null(record.get("capital_allocation_buyback_diluted_share_change_pct_timestamp"), record.get("capital_allocation_buyback_basic_share_change_pct_timestamp"), record.get("capital_allocation_buyback_net_diluted_share_reduction_pct_timestamp")),
            "debt_timestamp": record.get("debt_to_equity_timestamp"),
            "dividend_timestamp": record.get("dividend_yield_timestamp"),
        },
    }

    scenarios = {
        "downside": {
            "expected_2yr_cagr": round(down_2y, 2),
            "expected_10yr_cagr": round(down_10y, 2),
            "assumptions": {"growth_shift_pct": -4.0, "margin_shift_pct": -2.0, "terminal_multiple_shift": -20.0},
        },
        "base": {
            "expected_2yr_cagr": round(base_2y, 2),
            "expected_10yr_cagr": round(base_10y, 2),
            "expected_alpha_vs_spy": round(expected_alpha, 2),
            "assumptions": {"growth_shift_pct": 0.0, "margin_shift_pct": 0.0, "terminal_multiple_shift": 0.0},
        },
        "upside": {
            "expected_2yr_cagr": round(up_2y, 2),
            "expected_10yr_cagr": round(up_10y, 2),
            "assumptions": {"growth_shift_pct": 4.0, "margin_shift_pct": 2.0, "terminal_multiple_shift": 20.0},
        },
    }

    critical_sourced = all(
        assumptions["source_timestamps"].get(k)
        for k in ["market_cap_timestamp", "growth_timestamp", "margin_timestamp"]
    )

    estimated_count = 0
    if share_count_estimated:
        estimated_count += 1
    if debt_to_equity is None:
        estimated_count += 1

    if not critical_sourced:
        confidence = ConfidenceResult("LOW", 45.0, "Missing critical source timestamps for core forecast assumptions")
    elif estimated_count == 0:
        confidence = ConfidenceResult("HIGH", 85.0, "All critical and adjustment assumptions are sourced from current project datasets")
    elif estimated_count == 1:
        confidence = ConfidenceResult("MEDIUM", 70.0, "One non-critical adjustment assumption is estimated while core assumptions are sourced")
    else:
        confidence = ConfidenceResult("LOW", 50.0, "Multiple adjustment assumptions are estimated")

    return {
        "expected_alpha": round(expected_alpha, 2),
        "expected_2yr_cagr": round(base_2y, 2),
        "expected_10yr_cagr": round(base_10y, 2),
        "assumptions": assumptions,
        "scenarios": scenarios,
        "confidence": confidence,
        "terminal_multiple": round(terminal_multiple, 4),
    }, missing


def main() -> int:
    now = datetime.now(timezone.utc)

    portfolio = _load_json(PORTFOLIO_PATH)
    intelligence = _load_json(INTELLIGENCE_PATH)
    sec = _load_json(SEC_PATH)
    earnings_quality_rows = {row.get("symbol"): row for row in _load_json(EARNINGS_QUALITY_PATH).get("holdings", [])}
    capital_allocation_rows = {row.get("symbol"): row for row in _load_json(CAPITAL_ALLOCATION_PATH).get("holdings", [])}
    earnings_call_rows = {row.get("symbol"): row for row in _load_json(EARNINGS_CALL_PATH).get("rows", [])}

    holdings = [row for row in portfolio.get("positions", []) if row.get("asset_type") == "EQUITY"]
    holdings.sort(key=lambda row: float(row.get("market_value") or 0.0), reverse=True)

    int_rows = intelligence.get("holdings", [])
    by_symbol = {row.get("symbol"): row for row in int_rows}

    summary: Dict[str, Any] = {
        "generated_at": now.isoformat(),
        "benchmark_return_pct": BENCHMARK_RETURN_PCT,
        "eligible": [],
        "blocked": [],
        "coverage": {},
    }

    for idx, pos in enumerate(holdings, start=1):
        symbol = str(pos.get("symbol") or "").strip()
        if not symbol:
            continue
        row = by_symbol.get(symbol)
        if row is None:
            continue

        sec_row = sec.get(symbol, {}) if isinstance(sec, dict) else {}
        eq_row = earnings_quality_rows.get(symbol, {})
        ca_row = capital_allocation_rows.get(symbol, {})
        ec_row = earnings_call_rows.get(symbol, {})

        merged = dict(row)
        for src in (sec_row, eq_row, ca_row, ec_row):
            if isinstance(src, dict):
                for k, v in src.items():
                    merged.setdefault(k, v)

        company_name = _first_non_null(sec_row.get("entity_name"), row.get("company_name"), symbol)
        bq_score, bq_detail, bq_missing = _business_quality_components(merged, eq_row, ca_row)
        forecast, forecast_missing = _build_forecast(merged, now)
        missing_fields = bq_missing + forecast_missing

        valuation_score = _to_float(_first_non_null(row.get("valuation_score"), row.get("valuation")))
        current_multiple = _to_float(row.get("pe_ratio"))
        if current_multiple is None:
            ps = _to_float(row.get("price_to_sales"))
            margin = _to_float(_first_non_null(row.get("net_margin"), row.get("operating_margin")))
            if ps is not None and margin not in (None, 0):
                current_multiple = ps / max(0.02, abs(margin / 100.0))

        valuation_payload = {
            "current_multiple": current_multiple,
            "historical_range": None,
            "peer_range": None,
            "fair_value_range": (
                [round(current_multiple * 0.85, 2), round(current_multiple * 1.15, 2)]
                if current_multiple is not None
                else None
            ),
            "valuation_score": valuation_score,
            "confidence": _confidence_label(_to_float(row.get("valuation_score_confidence")) or 0.0),
            "data_timestamp": _first_non_null(row.get("pe_ratio_timestamp"), row.get("valuation_score_timestamp"), row.get("intelligence_timestamp")),
        }

        valuation_missing: List[Dict[str, Any]] = []
        if valuation_payload["historical_range"] is None:
            valuation_missing.append(
                {
                    "missing_assumption": "historical_valuation_range",
                    "expected_source": "historical valuation dataset (not yet present)",
                    "age_of_latest_available_input_hours": None,
                    "blocks_eipv": False,
                    "next_action": "Add historical multiple series and persist a rolling valuation range by ticker.",
                }
            )
        if valuation_payload["peer_range"] is None:
            valuation_missing.append(
                {
                    "missing_assumption": "peer_valuation_range",
                    "expected_source": "peer comp dataset (not yet present)",
                    "age_of_latest_available_input_hours": None,
                    "blocks_eipv": False,
                    "next_action": "Add peer multiple comps for each sector to support relative valuation checks.",
                }
            )

        missing_fields.extend(valuation_missing)

        confidence_label = "UNAVAILABLE"
        confidence_score = 0.0
        confidence_rationale = "Forecast model unavailable"
        expected_alpha = "NEEDS_RESEARCH"
        expected_2yr_cagr = "NEEDS_RESEARCH"
        expected_10yr_cagr = "NEEDS_RESEARCH"

        if forecast:
            confidence_label = forecast["confidence"].label
            confidence_score = forecast["confidence"].score
            confidence_rationale = forecast["confidence"].rationale
            expected_alpha = forecast["expected_alpha"]
            expected_2yr_cagr = forecast["expected_2yr_cagr"]
            expected_10yr_cagr = forecast["expected_10yr_cagr"]

        if confidence_label not in {"HIGH", "MEDIUM"}:
            # Keep diagnostics in canonical record, but do not qualify EIPV fields.
            expected_alpha = "NEEDS_RESEARCH"
            expected_2yr_cagr = "NEEDS_RESEARCH"
            expected_10yr_cagr = "NEEDS_RESEARCH"

        data_as_of_candidates = [
            _first_non_null(row.get("intelligence_timestamp"), row.get("valuation_score_timestamp")),
            sec_row.get("timestamp"),
            eq_row.get("as_of"),
            ca_row.get("as_of"),
            ec_row.get("as_of"),
        ]
        data_as_of = _first_non_null(*data_as_of_candidates)

        canonical = {
            "ticker": symbol,
            "company_name": company_name,
            "business_quality": bq_score,
            "valuation": valuation_payload,
            "expected_alpha": expected_alpha,
            "expected_2yr_cagr": expected_2yr_cagr,
            "expected_10yr_cagr": expected_10yr_cagr,
            "thesis_health": _first_non_null(row.get("thesis_health"), ec_row.get("earnings_call_thesis_signal"), "NEEDS_RESEARCH"),
            "confidence_score": round(confidence_score, 1),
            "confidence_label": confidence_label,
            "confidence_rationale": confidence_rationale,
            "data_as_of": data_as_of,
            "last_reviewed": now.isoformat(),
            "source_notes": {
                "sec": "sec_fundamentals_latest.json",
                "earnings_quality": "earnings_quality_latest.json",
                "capital_allocation": "capital_allocation_latest.json",
                "earnings_call": "earnings_call_intelligence_latest.json",
                "intelligence": "mcleod_intelligence_latest.json",
                "portfolio": "schwab_portfolio_latest.json",
            },
            "assumptions": forecast["assumptions"] if forecast else {
                "explicit_company_assumptions": False,
                "model": "unavailable",
            },
            "forecast_scenarios": forecast["scenarios"] if forecast else None,
            "business_quality_detail": bq_detail,
            "missing_fields": missing_fields,
            "priority_rank_by_weight": idx,
            "position_weight_pct": round((float(pos.get("market_value") or 0.0) / max(1e-9, sum(float(h.get("market_value") or 0.0) for h in holdings))) * 100.0, 4),
        }

        row["company_name"] = company_name
        row["business_quality"] = bq_score
        row["business_quality_source"] = "Canonical Evidence-Weighted Components"
        row["business_quality_timestamp"] = now.isoformat()
        row["business_quality_confidence"] = round(75.0 if confidence_label in {"HIGH", "MEDIUM"} else 55.0, 1)
        row["business_quality_confidence_label"] = "MEDIUM" if confidence_label in {"HIGH", "MEDIUM"} else "LOW"

        row["valuation"] = valuation_score if valuation_score is not None else row.get("valuation", "NEEDS_RESEARCH")
        row["valuation_source"] = "Canonical Valuation Object"
        row["valuation_timestamp"] = now.isoformat()
        row["valuation_confidence"] = _to_float(row.get("valuation_score_confidence")) or 60.0
        row["valuation_confidence_label"] = _confidence_label(float(row["valuation_confidence"]))

        row["expected_alpha"] = expected_alpha
        row["expected_2yr_cagr"] = expected_2yr_cagr
        row["expected_10yr_cagr"] = expected_10yr_cagr
        row["expected_alpha_source"] = "Canonical Company Model"
        row["expected_2yr_cagr_source"] = "Canonical Company Model"
        row["expected_10yr_cagr_source"] = "Canonical Company Model"
        row["expected_alpha_timestamp"] = now.isoformat()
        row["expected_2yr_cagr_timestamp"] = now.isoformat()
        row["expected_10yr_cagr_timestamp"] = now.isoformat()
        row["expected_alpha_confidence"] = round(confidence_score, 1)
        row["expected_2yr_cagr_confidence"] = round(confidence_score, 1)
        row["expected_10yr_cagr_confidence"] = round(confidence_score, 1)
        row["expected_alpha_confidence_label"] = confidence_label
        row["expected_2yr_cagr_confidence_label"] = confidence_label
        row["expected_10yr_cagr_confidence_label"] = confidence_label
        row["expected_alpha_source_notes"] = "Company-level assumptions sourced from auditable project datasets"
        row["expected_2yr_cagr_source_notes"] = row["expected_alpha_source_notes"]
        row["expected_10yr_cagr_source_notes"] = row["expected_alpha_source_notes"]
        row["expected_return_formula"] = "expected_equity_value = forecast_revenue * expected_margin * terminal_multiple adjusted for dilution, net debt, and dividends"
        row["expected_return_assumptions"] = canonical["assumptions"]
        row["expected_return_scenarios"] = canonical["forecast_scenarios"]

        row["thesis_health"] = canonical["thesis_health"]
        row["thesis_health_timestamp"] = now.isoformat()
        row["thesis_health_source"] = "Earnings Call Intelligence"

        row["confidence_score"] = round(confidence_score, 1)
        row["data_as_of"] = data_as_of
        row["last_reviewed"] = now.isoformat()
        row["source_notes"] = canonical["source_notes"]
        row["assumptions"] = canonical["assumptions"]
        row["missing_fields"] = canonical["missing_fields"]
        row["canonical_research_record"] = canonical

        coverage = {
            "sec_available": bool(sec_row),
            "earnings_quality_available": bool(eq_row),
            "capital_allocation_available": bool(ca_row),
            "earnings_call_available": bool(ec_row),
        }
        summary["coverage"][symbol] = coverage
        if confidence_label in {"HIGH", "MEDIUM"}:
            summary["eligible"].append(symbol)
        else:
            summary["blocked"].append(symbol)

    intelligence.setdefault("metadata", {})["canonical_population_timestamp"] = now.isoformat()
    intelligence["metadata"]["canonical_population_version"] = "v1"

    INTELLIGENCE_PATH.write_text(json.dumps(intelligence, indent=2), encoding="utf-8")
    OUTPUT_SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Updated canonical records for {len(holdings)} holdings")
    print(f"EIPV-eligible (HIGH/MEDIUM): {len(summary['eligible'])}")
    print(f"Blocked (LOW/UNAVAILABLE): {len(summary['blocked'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
