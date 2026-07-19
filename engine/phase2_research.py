#!/usr/bin/env python3
"""Phase 2 research scoring from Phase 1 artifacts only.

This module intentionally does not scrape raw sources. It loads a completed
Phase 1 artifact bundle, filters to verified facts, and produces a structured
RKLB-only Phase 2 scorecard plus a human-readable review.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
PHASE2_DIR = DATA_DIR / "research" / "phase2"
PHASE2_SCHEMA_VERSION = "2026-07-18.phase2.v2"
PHASE2_LOCK_NAME = "Phase2_Framework_Locked"
PHASE2_ONBOARDING_ALLOWLIST = ("RKLB", "NBIS")
PHASE2_TICKER_REGISTRY = {
    "RKLB": {
        "ticker": "RKLB",
        "phase1_fact_path": DATA_DIR / "research" / "facts" / "RKLB_phase1_facts.json",
        "phase1_review_path": DATA_DIR / "research" / "review" / "RKLB_phase1_facts.md",
        "output_dir": PHASE2_DIR / "RKLB",
    },
    "NBIS": {
        "ticker": "NBIS",
        "phase1_fact_path": DATA_DIR / "research" / "facts" / "NBIS_phase1_facts.json",
        "phase1_review_path": DATA_DIR / "research" / "review" / "NBIS_phase1_facts.md",
        "output_dir": PHASE2_DIR / "NBIS",
    },
}

PHASE1_FACTS_PATH = PHASE2_TICKER_REGISTRY["RKLB"]["phase1_fact_path"]
PHASE1_REVIEW_PATH = PHASE2_TICKER_REGISTRY["RKLB"]["phase1_review_path"]


class Phase2OnboardingError(ValueError):
    pass


class Phase2ReadinessError(ValueError):
    pass


def _normalize_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def _resolve_ticker_config(ticker: str) -> Dict[str, Any]:
    normalized = _normalize_ticker(ticker)
    if normalized not in PHASE2_ONBOARDING_ALLOWLIST:
        raise Phase2OnboardingError(f"Ticker {normalized or ticker!r} is not approved for Phase 2 onboarding.")
    try:
        return dict(PHASE2_TICKER_REGISTRY[normalized])
    except KeyError as exc:
        raise Phase2OnboardingError(f"Ticker {normalized!r} is allowed but missing a Phase 2 registry entry.") from exc


def _phase1_readiness_from_review(review_text: str) -> bool:
    return bool(re.search(r"^\- Phase 2 readiness:\s*True$", review_text, flags=re.MULTILINE))


def _phase2_readiness_gate(review_text: str, facts_payload: Dict[str, Any]) -> None:
    if not _phase1_readiness_from_review(review_text):
        raise Phase2ReadinessError(f"Phase 1 artifact is not ready for Phase 2: {facts_payload.get('ticker', '')}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, "", "NA", "N/A", "NEEDS_RESEARCH"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _linear_score(value: Optional[float], low: float, high: float) -> Optional[float]:
    if value is None:
        return None
    if high <= low:
        return 0.0
    return _clamp(((value - low) / (high - low)) * 100.0)


def _inverse_linear_score(value: Optional[float], low: float, high: float) -> Optional[float]:
    if value is None:
        return None
    if high <= low:
        return 0.0
    return _clamp(((high - value) / (high - low)) * 100.0)


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _unique_dicts(dicts: Sequence[Dict[str, Any]], key_fields: Sequence[str]) -> List[Dict[str, Any]]:
    seen: set[Tuple[Any, ...]] = set()
    unique: List[Dict[str, Any]] = []
    for entry in dicts:
        key = tuple(entry.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _latest_verified_fact(facts: Sequence[Dict[str, Any]], field: str) -> Optional[Dict[str, Any]]:
    matches = [
        fact
        for fact in facts
        if str(fact.get("normalized_field") or fact.get("field") or "").strip().lower() == field.lower()
        and str(fact.get("fact_status") or "") == "verified"
    ]
    if not matches:
        return None

    def sort_key(fact: Dict[str, Any]) -> Tuple[str, str, str]:
        return (
            str(fact.get("period") or ""),
            str(fact.get("extracted_at") or ""),
            str(fact.get("source_date") or ""),
        )

    return sorted(matches, key=sort_key, reverse=True)[0]


def _fact_ref(fact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "field": fact.get("normalized_field") or fact.get("field") or "",
        "value": fact.get("value"),
        "unit": fact.get("unit") or "",
        "period": fact.get("period") or "",
        "source_document_id": fact.get("source_document_id") or "",
        "source_url": fact.get("source_url") or "",
        "source_date": fact.get("source_date") or "",
        "fact_status": fact.get("fact_status") or "",
        "confidence": fact.get("confidence") or 0.0,
        "extraction_method": fact.get("extraction_method") or "",
    }


def _input_metric(
    name: str,
    fact: Optional[Dict[str, Any]],
    *,
    weight: float,
    score: Optional[float],
    missing_inputs: Sequence[str],
    note: str = "",
) -> Dict[str, Any]:
    confidence = 0.0
    provenance: List[Dict[str, Any]] = []
    if fact is not None:
        confidence = float(fact.get("confidence") or 0.0)
        provenance = [_fact_ref(fact)]
    return {
        "name": name,
        "weight": round(weight, 4),
        "score": round(_clamp(score if score is not None else 50.0), 2),
        "confidence": round(confidence, 2),
        "provenance": provenance,
        "missing_inputs": list(missing_inputs),
        "note": note,
    }


def _combine_metrics(metrics: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    present = [metric for metric in metrics if metric["provenance"]]
    total_weight = sum(float(metric["weight"]) for metric in metrics)
    available_weight = sum(float(metric["weight"]) for metric in present)
    if present:
        score = sum(float(metric["score"]) * float(metric["weight"]) for metric in present) / available_weight
        mean_conf = sum(float(metric["confidence"]) for metric in present) / len(present)
        confidence = mean_conf * (available_weight / total_weight if total_weight else 0.0)
    else:
        score = 50.0
        confidence = 0.0

    missing_inputs: List[str] = []
    for metric in metrics:
        for item in metric.get("missing_inputs", []):
            if item not in missing_inputs:
                missing_inputs.append(item)

    return {
        "score": round(_clamp(score), 2),
        "confidence": round(_clamp(confidence, 0.0, 100.0), 2),
        "weight": round(total_weight, 4),
        "missing_inputs": missing_inputs,
        "submetrics": list(metrics),
    }


class Phase2ResearchEngine:
    """Load verified Phase 1 facts and score RKLB for Phase 2."""

    component_weights = {
        "business_quality": 0.20,
        "competitive_moat": 0.15,
        "management": 0.15,
        "capital_allocation": 0.15,
        "balance_sheet": 0.15,
        "growth": 0.10,
        "valuation": 0.10,
    }

    def __init__(
        self,
        ticker: str = "RKLB",
        phase1_fact_path: Optional[Path] = None,
        phase1_review_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        config = _resolve_ticker_config(ticker)
        self.ticker = _normalize_ticker(config["ticker"])
        self.phase1_fact_path = Path(phase1_fact_path or config["phase1_fact_path"])
        self.phase1_review_path = Path(phase1_review_path or config["phase1_review_path"])
        self.output_dir = Path(output_dir or config["output_dir"])
        self.schema_version = PHASE2_SCHEMA_VERSION
        self.lock_name = PHASE2_LOCK_NAME

    def load_phase1_artifacts(self) -> Dict[str, Any]:
        facts_payload = _load_json(self.phase1_fact_path)
        review_text = self.phase1_review_path.read_text(encoding="utf-8") if self.phase1_review_path.exists() else ""
        return {
            "facts_payload": facts_payload,
            "review_text": review_text,
        }

    def verify_phase1_ready(self) -> None:
        artifact = self.load_phase1_artifacts()
        _phase2_readiness_gate(artifact["review_text"], artifact["facts_payload"])

    def _verified_facts(self, facts_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        facts = list(facts_payload.get("facts") or [])
        return [fact for fact in facts if str(fact.get("fact_status") or "") == "verified"]

    def _field(self, facts: Sequence[Dict[str, Any]], field: str) -> Optional[Dict[str, Any]]:
        return _latest_verified_fact(facts, field)

    def _score_business_quality(self, facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        gross_margin = self._field(facts, "gross_margin")
        operating_margin = self._field(facts, "operating_margin")
        free_cash_flow_margin = self._field(facts, "free_cash_flow_margin")
        revenue_growth = self._field(facts, "revenue_growth")

        metrics = [
            _input_metric(
                "gross_margin",
                gross_margin,
                weight=0.30,
                score=_linear_score(_safe_float(gross_margin.get("value") if gross_margin else None), 20.0, 60.0),
                missing_inputs=["gross_margin"] if gross_margin is None else [],
                note="Higher gross margin implies more pricing power and operating leverage.",
            ),
            _input_metric(
                "operating_margin",
                operating_margin,
                weight=0.25,
                score=_linear_score(_safe_float(operating_margin.get("value") if operating_margin else None), -40.0, 20.0),
                missing_inputs=["operating_margin"] if operating_margin is None else [],
                note="Operating margin remains negative; better execution improves the score.",
            ),
            _input_metric(
                "free_cash_flow_margin",
                free_cash_flow_margin,
                weight=0.25,
                score=_linear_score(_safe_float(free_cash_flow_margin.get("value") if free_cash_flow_margin else None), -40.0, 20.0),
                missing_inputs=["free_cash_flow_margin"] if free_cash_flow_margin is None else [],
                note="Positive free cash flow margin is rewarded; negative margins are penalized.",
            ),
            _input_metric(
                "revenue_growth",
                revenue_growth,
                weight=0.20,
                score=_linear_score(_safe_float(revenue_growth.get("value") if revenue_growth else None), -20.0, 80.0),
                missing_inputs=["revenue_growth"] if revenue_growth is None else [],
                note="Growth matters, but the score is limited to verified Phase 1 growth only.",
            ),
        ]
        result = _combine_metrics(metrics)
        result["label"] = "Business Quality Score"
        result["formula"] = "Weighted average of gross margin, operating margin, free cash flow margin, and revenue growth."
        return result

    def _score_competitive_moat(self, facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        gross_margin = self._field(facts, "gross_margin")
        operating_margin = self._field(facts, "operating_margin")
        revenue_growth = self._field(facts, "revenue_growth")
        backlog = self._field(facts, "backlog")
        customer_concentration = self._field(facts, "customer_concentration")

        metrics = [
            _input_metric(
                "gross_margin",
                gross_margin,
                weight=0.30,
                score=_linear_score(_safe_float(gross_margin.get("value") if gross_margin else None), 25.0, 65.0),
                missing_inputs=["gross_margin"] if gross_margin is None else [],
                note="Margin structure is the most durable verified moat proxy available in Phase 1.",
            ),
            _input_metric(
                "operating_margin",
                operating_margin,
                weight=0.20,
                score=_linear_score(_safe_float(operating_margin.get("value") if operating_margin else None), -40.0, 20.0),
                missing_inputs=["operating_margin"] if operating_margin is None else [],
                note="Operating leverage supports moat durability when it turns positive.",
            ),
            _input_metric(
                "revenue_growth",
                revenue_growth,
                weight=0.20,
                score=_linear_score(_safe_float(revenue_growth.get("value") if revenue_growth else None), -20.0, 80.0),
                missing_inputs=["revenue_growth"] if revenue_growth is None else [],
                note="Verified growth helps separate momentum from one-off contract revenue.",
            ),
            _input_metric(
                "backlog",
                backlog,
                weight=0.15,
                score=_linear_score(_safe_float(backlog.get("value") if backlog else None), 250_000_000.0, 2_500_000_000.0),
                missing_inputs=["backlog"] if backlog is None else [],
                note="Verified backlog would be a strong moat signal; it is absent from the verified fact set.",
            ),
            _input_metric(
                "customer_concentration",
                customer_concentration,
                weight=0.15,
                score=_inverse_linear_score(_safe_float(customer_concentration.get("value") if customer_concentration else None), 5.0, 40.0),
                missing_inputs=["customer_concentration"] if customer_concentration is None else [],
                note="Lower customer concentration is better; the verified fact is currently missing.",
            ),
        ]
        result = _combine_metrics(metrics)
        result["label"] = "Competitive Moat Score"
        result["formula"] = "Weighted verified proxies for pricing power, operating leverage, growth, backlog, and customer concentration."
        return result

    def _score_management(self, facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        share_count_change = self._field(facts, "share_count_change")
        operating_margin = self._field(facts, "operating_margin")
        free_cash_flow_margin = self._field(facts, "free_cash_flow_margin")
        capital_expenditures = self._field(facts, "capital_expenditures")
        revenue = self._field(facts, "revenue")
        guidance = self._field(facts, "guidance")

        capex_ratio = None
        if capital_expenditures is not None and revenue is not None:
            capex_ratio = abs(_safe_float(capital_expenditures.get("value"))) / max(1.0, abs(_safe_float(revenue.get("value"), 1.0) or 1.0)) * 100.0

        metrics = [
            _input_metric(
                "share_count_change",
                share_count_change,
                weight=0.35,
                score=_inverse_linear_score(_safe_float(share_count_change.get("value") if share_count_change else None), -10.0, 10.0),
                missing_inputs=["share_count_change"] if share_count_change is None else [],
                note="Net dilution is penalized; buybacks and count reduction are rewarded.",
            ),
            _input_metric(
                "operating_margin",
                operating_margin,
                weight=0.20,
                score=_linear_score(_safe_float(operating_margin.get("value") if operating_margin else None), -40.0, 20.0),
                missing_inputs=["operating_margin"] if operating_margin is None else [],
                note="Management should improve operating leverage over time.",
            ),
            _input_metric(
                "free_cash_flow_margin",
                free_cash_flow_margin,
                weight=0.20,
                score=_linear_score(_safe_float(free_cash_flow_margin.get("value") if free_cash_flow_margin else None), -40.0, 20.0),
                missing_inputs=["free_cash_flow_margin"] if free_cash_flow_margin is None else [],
                note="Capital discipline should move free cash flow margin toward positive territory.",
            ),
            _input_metric(
                "capital_expenditures_intensity",
                capital_expenditures,
                weight=0.15,
                score=_inverse_linear_score(capex_ratio, 2.0, 20.0),
                missing_inputs=["capital_expenditures", "revenue"] if capex_ratio is None else [],
                note="Lower capex intensity is better when growth is not being sacrificed.",
            ),
            _input_metric(
                "guidance",
                guidance,
                weight=0.10,
                score=None,
                missing_inputs=["guidance"] if guidance is None else [],
                note="Guidance exists in Phase 1 only as an uncertain fact, so it is excluded from scoring and noted as missing.",
            ),
        ]
        result = _combine_metrics(metrics)
        result["label"] = "Management Score"
        result["formula"] = "Weighted verified dilution, profitability, cash discipline, and guidance availability proxies."
        return result

    def _score_capital_allocation(self, facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        share_count_change = self._field(facts, "share_count_change")
        free_cash_flow = self._field(facts, "free_cash_flow")
        capital_expenditures = self._field(facts, "capital_expenditures")
        cash = self._field(facts, "cash")
        debt = self._field(facts, "debt")
        revenue = self._field(facts, "revenue")

        capex_ratio = None
        fcf_margin = None
        net_cash_ratio = None
        if capital_expenditures is not None and revenue is not None:
            capex_ratio = abs(_safe_float(capital_expenditures.get("value"))) / max(1.0, abs(_safe_float(revenue.get("value"), 1.0) or 1.0)) * 100.0
        if free_cash_flow is not None and revenue is not None:
            fcf_margin = (_safe_float(free_cash_flow.get("value"), 0.0) / max(1.0, abs(_safe_float(revenue.get("value"), 1.0) or 1.0))) * 100.0
        if cash is not None and debt is not None:
            net_cash_ratio = (_safe_float(cash.get("value"), 0.0) - _safe_float(debt.get("value"), 0.0)) / max(1.0, abs(_safe_float(revenue.get("value"), 1.0) or 1.0)) * 100.0

        metrics = [
            _input_metric(
                "share_count_change",
                share_count_change,
                weight=0.30,
                score=_inverse_linear_score(_safe_float(share_count_change.get("value") if share_count_change else None), -10.0, 10.0),
                missing_inputs=["share_count_change"] if share_count_change is None else [],
                note="Per-share value creation should not come at the expense of dilution.",
            ),
            _input_metric(
                "free_cash_flow_margin",
                free_cash_flow,
                weight=0.25,
                score=_linear_score(fcf_margin, -40.0, 20.0),
                missing_inputs=["free_cash_flow", "revenue"] if fcf_margin is None else [],
                note="Free cash flow margin is the clearest verified capital-allocation outcome available.",
            ),
            _input_metric(
                "capital_expenditures_intensity",
                capital_expenditures,
                weight=0.15,
                score=_inverse_linear_score(capex_ratio, 2.0, 20.0),
                missing_inputs=["capital_expenditures", "revenue"] if capex_ratio is None else [],
                note="Capex is scored as a fraction of revenue to avoid size bias.",
            ),
            _input_metric(
                "net_cash_ratio",
                cash,
                weight=0.15,
                score=_linear_score(net_cash_ratio, 0.0, 200.0),
                missing_inputs=["cash", "debt", "revenue"] if net_cash_ratio is None else [],
                note="Excess net cash strengthens optionality for future capital deployment.",
            ),
            _input_metric(
                "debt",
                debt,
                weight=0.15,
                score=_inverse_linear_score(_safe_float(debt.get("value") if debt else None), 0.0, 250_000_000.0),
                missing_inputs=["debt"] if debt is None else [],
                note="Lower debt preserves capital allocation flexibility.",
            ),
        ]
        result = _combine_metrics(metrics)
        result["label"] = "Capital Allocation Score"
        result["formula"] = "Weighted verified dilution, free cash flow, capex intensity, net cash strength, and debt burden."
        return result

    def _score_balance_sheet(self, facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        cash = self._field(facts, "cash")
        debt = self._field(facts, "debt")
        net_cash = self._field(facts, "net_cash")
        common_equity = self._field(facts, "common_equity")
        marketable_securities = self._field(facts, "marketable_securities")
        revenue = self._field(facts, "revenue")

        cash_ratio = None
        debt_ratio = None
        net_cash_ratio = None
        equity_ratio = None
        securities_ratio = None
        if cash is not None and revenue is not None:
            cash_ratio = _safe_float(cash.get("value"), 0.0) / max(1.0, abs(_safe_float(revenue.get("value"), 1.0) or 1.0)) * 100.0
        if debt is not None and cash is not None:
            debt_ratio = _safe_float(debt.get("value"), 0.0) / max(1.0, _safe_float(cash.get("value"), 1.0) or 1.0) * 100.0
        if net_cash is not None and revenue is not None:
            net_cash_ratio = _safe_float(net_cash.get("value"), 0.0) / max(1.0, abs(_safe_float(revenue.get("value"), 1.0) or 1.0)) * 100.0
        if common_equity is not None and debt is not None:
            equity_ratio = _safe_float(common_equity.get("value"), 0.0) / max(1.0, abs(_safe_float(debt.get("value"), 1.0) or 1.0))
        if marketable_securities is not None and revenue is not None:
            securities_ratio = _safe_float(marketable_securities.get("value"), 0.0) / max(1.0, abs(_safe_float(revenue.get("value"), 1.0) or 1.0)) * 100.0

        metrics = [
            _input_metric(
                "cash_ratio",
                cash,
                weight=0.25,
                score=_linear_score(cash_ratio, 0.0, 200.0),
                missing_inputs=["cash", "revenue"] if cash_ratio is None else [],
                note="Liquid resources relative to revenue indicate balance-sheet resilience.",
            ),
            _input_metric(
                "debt_ratio",
                debt,
                weight=0.20,
                score=_inverse_linear_score(debt_ratio, 0.0, 40.0),
                missing_inputs=["debt", "cash"] if debt_ratio is None else [],
                note="Debt is penalized relative to cash because fixed obligations reduce flexibility.",
            ),
            _input_metric(
                "net_cash_ratio",
                net_cash,
                weight=0.30,
                score=_linear_score(net_cash_ratio, 0.0, 200.0),
                missing_inputs=["net_cash", "revenue"] if net_cash_ratio is None else [],
                note="Net cash is a strong defense against cyclicality and execution risk.",
            ),
            _input_metric(
                "equity_coverage",
                common_equity,
                weight=0.15,
                score=_linear_score(equity_ratio, 1.0, 80.0),
                missing_inputs=["common_equity", "debt"] if equity_ratio is None else [],
                note="Equity coverage versus debt captures capital structure strength.",
            ),
            _input_metric(
                "marketable_securities",
                marketable_securities,
                weight=0.10,
                score=_linear_score(securities_ratio, 0.0, 50.0),
                missing_inputs=["marketable_securities", "revenue"] if securities_ratio is None else [],
                note="Marketable securities increase near-term flexibility.",
            ),
        ]
        result = _combine_metrics(metrics)
        result["label"] = "Balance Sheet Score"
        result["formula"] = "Weighted verified cash, debt, net cash, equity coverage, and marketable securities."
        return result

    def _score_growth(self, facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        revenue_growth = self._field(facts, "revenue_growth")
        gross_margin = self._field(facts, "gross_margin")
        free_cash_flow_margin = self._field(facts, "free_cash_flow_margin")
        backlog = self._field(facts, "backlog")

        metrics = [
            _input_metric(
                "revenue_growth",
                revenue_growth,
                weight=0.45,
                score=_linear_score(_safe_float(revenue_growth.get("value") if revenue_growth else None), -20.0, 80.0),
                missing_inputs=["revenue_growth"] if revenue_growth is None else [],
                note="Top-line growth is the primary growth score driver.",
            ),
            _input_metric(
                "gross_margin",
                gross_margin,
                weight=0.25,
                score=_linear_score(_safe_float(gross_margin.get("value") if gross_margin else None), 20.0, 60.0),
                missing_inputs=["gross_margin"] if gross_margin is None else [],
                note="Sustained growth is more valuable when gross margin remains healthy.",
            ),
            _input_metric(
                "free_cash_flow_margin",
                free_cash_flow_margin,
                weight=0.15,
                score=_linear_score(_safe_float(free_cash_flow_margin.get("value") if free_cash_flow_margin else None), -40.0, 20.0),
                missing_inputs=["free_cash_flow_margin"] if free_cash_flow_margin is None else [],
                note="Growth with improving cash generation is rewarded.",
            ),
            _input_metric(
                "backlog",
                backlog,
                weight=0.15,
                score=_linear_score(_safe_float(backlog.get("value") if backlog else None), 250_000_000.0, 2_500_000_000.0),
                missing_inputs=["backlog"] if backlog is None else [],
                note="Backlog would strengthen the growth outlook, but it is not a verified input here.",
            ),
        ]
        result = _combine_metrics(metrics)
        result["label"] = "Growth Score"
        result["formula"] = "Weighted verified revenue growth, margin quality, cash conversion, and backlog."
        return result

    def _score_valuation(self, facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        market_cap = self._field(facts, "market_cap")
        price = self._field(facts, "price")
        revenue = self._field(facts, "revenue")
        net_cash = self._field(facts, "net_cash")
        free_cash_flow_margin = self._field(facts, "free_cash_flow_margin")

        revenue_value = _safe_float(revenue.get("value") if revenue else None)
        net_cash_value = _safe_float(net_cash.get("value") if net_cash else None)
        fcf_margin_value = _safe_float(free_cash_flow_margin.get("value") if free_cash_flow_margin else None)

        net_cash_to_revenue = None
        if revenue_value not in (None, 0.0) and net_cash_value is not None:
            net_cash_to_revenue = (net_cash_value / abs(revenue_value)) * 100.0

        market_cap_proxy = _safe_float(market_cap.get("value") if market_cap is not None else None)
        price_proxy = _safe_float(price.get("value") if price is not None else None)

        submetrics = [
            _input_metric(
                "market_cap",
                market_cap,
                weight=0.40,
                score=_inverse_linear_score(market_cap_proxy, 500_000_000.0, 30_000_000_000.0),
                missing_inputs=["market_cap"] if market_cap is None else [],
                note="Market capitalization is the preferred direct valuation input, but it is absent from the verified Phase 1 fact set.",
            ),
            _input_metric(
                "price",
                price,
                weight=0.25,
                score=_inverse_linear_score(price_proxy, 5.0, 250.0),
                missing_inputs=["price"] if price is None else [],
                note="Share price is the direct market valuation anchor; Phase 1 does not provide a verified price fact.",
            ),
            _input_metric(
                "net_cash_to_revenue",
                net_cash,
                weight=0.20,
                score=_linear_score(net_cash_to_revenue, 0.0, 200.0),
                missing_inputs=["net_cash", "revenue"] if net_cash_to_revenue is None else [],
                note="A stronger net-cash position improves the valuation proxy when direct market data is unavailable.",
            ),
            _input_metric(
                "free_cash_flow_margin",
                free_cash_flow_margin,
                weight=0.15,
                score=_linear_score(fcf_margin_value, -40.0, 20.0),
                missing_inputs=["free_cash_flow_margin"] if free_cash_flow_margin is None else [],
                note="Cash generation quality is a supporting valuation proxy.",
            ),
        ]
        result = _combine_metrics(submetrics)
        result["label"] = "Valuation Score"
        result["formula"] = "Market-cap/price preferred; verified net cash and free cash flow margin act as fallback valuation proxies when market data is absent."
        return result

    def build_canonical_score(self) -> Dict[str, Any]:
        artifact = self.load_phase1_artifacts()
        facts_payload = artifact["facts_payload"]
        self.verify_phase1_ready()
        facts = self._verified_facts(facts_payload)
        verified_fields = sorted({str(f.get("normalized_field") or f.get("field") or "") for f in facts if f.get("normalized_field") or f.get("field")})

        components = {
            "business_quality": self._score_business_quality(facts),
            "competitive_moat": self._score_competitive_moat(facts),
            "management": self._score_management(facts),
            "capital_allocation": self._score_capital_allocation(facts),
            "balance_sheet": self._score_balance_sheet(facts),
            "growth": self._score_growth(facts),
            "valuation": self._score_valuation(facts),
        }

        weighted_numerator = 0.0
        weighted_denominator = 0.0
        for key, component in components.items():
            base_weight = self.component_weights[key]
            confidence_factor = float(component["confidence"]) / 100.0
            effective_weight = base_weight * confidence_factor
            weighted_numerator += float(component["score"]) * effective_weight
            weighted_denominator += effective_weight

        overall_score = round(weighted_numerator / weighted_denominator, 2) if weighted_denominator else 50.0
        overall_confidence = round(sum(component["confidence"] * self.component_weights[name] for name, component in components.items()), 2)

        contributing_verified_facts = _unique_dicts(
            [
                provenance
                for component in components.values()
                for metric in component["submetrics"]
                for provenance in metric["provenance"]
            ],
            ["field", "period", "source_document_id", "source_url", "value"],
        )

        return {
            "schema_version": self.schema_version,
            "schema_name": "Phase 2 Canonical Score",
            "ticker": self.ticker,
            "phase": 2,
            "phase2_framework_locked": True,
            "phase2_lock_name": self.lock_name,
            "source_phase1_artifact_fingerprint": _file_fingerprint(self.phase1_fact_path),
            "source_phase1_fact_path": str(self.phase1_fact_path),
            "source_phase1_review_path": str(self.phase1_review_path),
            "verified_fact_count": len(facts),
            "verified_fields": verified_fields,
            "component_scores": components,
            "overall_score": {
                "label": "Overall Phase 2 Score",
                "score": overall_score,
                "confidence": overall_confidence,
                "formula": "Confidence-weighted average of component scores.",
                "missing_inputs": sorted({item for component in components.values() for item in component["missing_inputs"]}),
            },
            "confidence": overall_confidence,
            "missing_inputs": sorted({item for component in components.values() for item in component["missing_inputs"]}),
            "weights": self.component_weights,
            "contributing_verified_facts": contributing_verified_facts,
            "provenance": {
                "phase1_fact_count": len(facts),
                "phase1_fact_source": str(self.phase1_fact_path),
                "phase1_review_source": str(self.phase1_review_path),
                "source_phase1_artifact_fingerprint": _file_fingerprint(self.phase1_fact_path),
                "schema_version": self.schema_version,
                "ticker": self.ticker,
            },
        }

    def _build_score_audit(self, canonical_score: Dict[str, Any], review_text: str) -> Dict[str, Any]:
        component_scores = canonical_score["component_scores"]
        audit: Dict[str, Any] = {"overall": {}, "components": {}, "component_metrics": {}, "passed": True}

        overall_match = re.search(r"^- Overall Phase 2 Score: ([0-9]+(?:\.[0-9]+)?)$", review_text, flags=re.MULTILINE)
        review_overall = round(float(overall_match.group(1)), 2) if overall_match else None
        canonical_overall = round(float(canonical_score["overall_score"]["score"]), 2)
        audit["overall"] = {
            "canonical": canonical_overall,
            "review": review_overall,
            "match": review_overall == canonical_overall,
        }
        audit["passed"] = audit["passed"] and audit["overall"]["match"]

        current_label = None
        current_metric_component = None
        component_heading = re.compile(r"^## (.+)$")
        component_score = re.compile(r"^- Score: ([0-9]+(?:\.[0-9]+)?)$")
        metric_line = re.compile(r"^  - ([^:]+): score=([0-9]+(?:\.[0-9]+)?) \| weight=([0-9]+(?:\.[0-9]+)?) \| confidence=([0-9]+(?:\.[0-9]+)?) \| (.+)$")

        for raw_line in review_text.splitlines():
            heading_match = component_heading.match(raw_line)
            if heading_match and heading_match.group(1) != "Overall":
                current_label = heading_match.group(1)
                current_metric_component = current_label
                continue

            score_match = component_score.match(raw_line)
            if score_match and current_label:
                component_entry = next(
                    (component for component in component_scores.values() if component["label"] == current_label),
                    None,
                )
                if component_entry is not None:
                    canonical_score_value = round(float(component_entry["score"]), 2)
                    review_score_value = round(float(score_match.group(1)), 2)
                    audit["components"][current_label] = {
                        "canonical": canonical_score_value,
                        "review": review_score_value,
                        "match": canonical_score_value == review_score_value,
                    }
                    audit["passed"] = audit["passed"] and audit["components"][current_label]["match"]
                continue

            metric_match = metric_line.match(raw_line)
            if metric_match and current_metric_component:
                metric_name = metric_match.group(1)
                component_entry = next(
                    (component for component in component_scores.values() if component["label"] == current_metric_component),
                    None,
                )
                if component_entry is not None:
                    metric_entry = next((metric for metric in component_entry["submetrics"] if metric["name"] == metric_name), None)
                    if metric_entry is not None:
                        canonical_metric_score = round(float(metric_entry["score"]), 2)
                        review_metric_score = round(float(metric_match.group(2)), 2)
                        audit["component_metrics"].setdefault(current_metric_component, {})[metric_name] = {
                            "canonical": canonical_metric_score,
                            "review": review_metric_score,
                            "match": review_metric_score == canonical_metric_score,
                            "has_provenance": bool(metric_entry["provenance"]),
                        }
                        audit["passed"] = audit["passed"] and audit["component_metrics"][current_metric_component][metric_name]["match"]

        for component in component_scores.values():
            label = component["label"]
            audit["components"].setdefault(
                label,
                {
                    "canonical": round(float(component["score"]), 2),
                    "review": None,
                    "match": False,
                },
            )

        for component in component_scores.values():
            component_label = component["label"]
            audit["component_metrics"].setdefault(component_label, {})
            for metric in component["submetrics"]:
                audit["component_metrics"][component_label].setdefault(
                    metric["name"],
                    {
                        "canonical": round(float(metric["score"]), 2),
                        "review": None,
                        "match": False,
                        "has_provenance": bool(metric["provenance"]),
                    },
                )

        return audit

    def render_review(self, canonical_score: Dict[str, Any]) -> str:
        lines: List[str] = []
        lines.append(f"# {canonical_score['ticker']} Phase 2 Review")
        lines.append("")
        lines.append(f"- Schema Version: {canonical_score['schema_version']}")
        lines.append(f"- Lock Name: {canonical_score['phase2_lock_name']}")
        lines.append(f"- Framework Locked: {canonical_score['phase2_framework_locked']}")
        lines.append(f"- Source Phase 1 facts: {canonical_score['source_phase1_fact_path']}")
        lines.append(f"- Source Phase 1 review: {canonical_score['source_phase1_review_path']}")
        lines.append(f"- Verified Phase 1 facts loaded: {canonical_score['verified_fact_count']}")
        lines.append("- Verified-only rule: true")
        lines.append("")
        lines.append("## Overall")
        lines.append(f"- Overall Phase 2 Score: {canonical_score['overall_score']['score']:.2f}")
        lines.append(f"- Overall Confidence: {canonical_score['overall_score']['confidence']:.2f}")
        if canonical_score['missing_inputs']:
            lines.append(f"- Missing Inputs: {', '.join(canonical_score['missing_inputs'])}")
        else:
            lines.append("- Missing Inputs: none")
        lines.append("")

        for key in [
            "business_quality",
            "competitive_moat",
            "management",
            "capital_allocation",
            "balance_sheet",
            "growth",
            "valuation",
        ]:
            component = canonical_score["component_scores"][key]
            lines.append(f"## {component['label']}")
            lines.append(f"- Score: {component['score']:.2f}")
            lines.append(f"- Weight: {component['weight']:.2f}")
            lines.append(f"- Confidence: {component['confidence']:.2f}")
            lines.append(f"- Formula: {component['formula']}")
            if component["missing_inputs"]:
                lines.append(f"- Missing inputs: {', '.join(component['missing_inputs'])}")
            else:
                lines.append("- Missing inputs: none")
            lines.append("- Submetrics:")
            for metric in component["submetrics"]:
                provenance = metric["provenance"]
                if provenance:
                    p = provenance[0]
                    prov_text = f"{p['field']}={p['value']} ({p['source_document_id']})"
                else:
                    prov_text = "missing verified input"
                lines.append(
                    f"  - {metric['name']}: score={metric['score']:.2f} | weight={metric['weight']:.2f} | confidence={metric['confidence']:.2f} | {prov_text}"
                )
                if metric["missing_inputs"]:
                    lines.append(f"    - missing: {', '.join(metric['missing_inputs'])}")
                if metric.get("note"):
                    lines.append(f"    - note: {metric['note']}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def score(self) -> Dict[str, Any]:
        canonical_score = self.build_canonical_score()
        review_text = self.render_review(canonical_score)
        score_audit = self._build_score_audit(canonical_score, review_text)

        artifact_payload = {
            "schema_version": self.schema_version,
            "ticker": self.ticker,
            "phase": 2,
            "generated_at": _utc_now_iso(),
            "source_phase1_artifact_fingerprint": canonical_score["source_phase1_artifact_fingerprint"],
            "source_phase1_fact_path": canonical_score["source_phase1_fact_path"],
            "source_phase1_review_path": canonical_score["source_phase1_review_path"],
            "canonical_score": canonical_score,
            "score_audit": score_audit,
        }

        self.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.output_dir / f"{self.ticker}_phase2_artifact.json", artifact_payload)
        _write_text(self.output_dir / f"{self.ticker}_phase2_review.md", review_text)

        return artifact_payload


def run_phase2(tickers: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Run Phase 2 for one or more approved tickers."""

    if isinstance(tickers, str):
        normalized_tickers = [_normalize_ticker(tickers)]
    else:
        normalized_tickers = [_normalize_ticker(ticker) for ticker in tickers]
    if not normalized_tickers:
        raise Phase2OnboardingError("At least one ticker is required for Phase 2 execution.")

    results: Dict[str, Dict[str, Any]] = {}
    for ticker in normalized_tickers:
        engine = Phase2ResearchEngine(ticker=ticker)
        results[engine.ticker] = engine.score()
    return results


def run_phase2_rklb(
    phase1_fact_path: Optional[Path] = None,
    phase1_review_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for the RKLB reference implementation."""

    return Phase2ResearchEngine(
        ticker="RKLB",
        phase1_fact_path=phase1_fact_path,
        phase1_review_path=phase1_review_path,
        output_dir=output_dir,
    ).score()
