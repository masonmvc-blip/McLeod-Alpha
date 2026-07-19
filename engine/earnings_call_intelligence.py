#!/usr/bin/env python3
"""McLeod Earnings Call Intelligence Engine v1.0.

Builds legally-safe earnings-call intelligence using official public materials
from SEC sources, scores thesis-relevant dimensions, tracks history, and
publishes explainability and predictive-performance artifacts.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_sources.transcript_source import TranscriptDataSource
from engine.universe_builder import UniverseBuilder


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

UNIVERSE_CSV = DATA_DIR / "us_equity_universe_latest.csv"
FULL_RANKINGS_CSV = DATA_DIR / "mcleod_full_market_rankings_latest.csv"

OUTPUT_JSON = DATA_DIR / "earnings_call_intelligence_latest.json"
OUTPUT_CSV = DATA_DIR / "earnings_call_intelligence_latest.csv"
OUTPUT_HISTORY_CSV = DATA_DIR / "earnings_call_history.csv"
POSITIONS_CSV = DATA_DIR / "schwab_positions_latest.csv"

REPORT_MD = REPORTS_DIR / "earnings_call_intelligence_report.md"

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


def _clamp_score(v: float) -> float:
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
    call_ic: float
    base_ic: float
    combined_ic: float
    incremental_ic: float


def _keyword_score(text: str, positives: Sequence[str], negatives: Sequence[str], scale: float = 6.0) -> Tuple[float, int, int]:
    low = text.lower()

    def _count_terms(terms: Sequence[str]) -> int:
        total = 0
        for term in terms:
            t = str(term or "").strip().lower()
            if not t:
                continue
            # Phrase and stem-friendly matching improves robustness on filing prose.
            total += low.count(t)
        return total

    pos = _count_terms(positives)
    neg = _count_terms(negatives)
    score = _clamp_score(50.0 + (pos - neg) * scale)
    return score, pos, neg


def _excerpt_for_terms(text: str, terms: Sequence[str], limit: int = 220) -> str:
    if not text:
        return ""
    low_terms = [t.lower() for t in terms]
    sentences = re.split(r"(?<=[.!?])\\s+", text)
    for sentence in sentences:
        s = sentence.strip()
        if len(s) < 40:
            continue
        low = s.lower()
        if any(t in low for t in low_terms):
            return s[:limit]
    return ""


class EarningsCallIntelligenceEngine:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.source = TranscriptDataSource()
        self.close_client = YahooCloseClient()
        self.refresh_limit = int(__import__("os").getenv("CALL_REFRESH_LIMIT", "150"))
        self.force_refresh = __import__("os").getenv("CALL_FORCE_REFRESH", "0") == "1"

    def _load_universe_symbols(self) -> List[str]:
        if not UNIVERSE_CSV.exists():
            UniverseBuilder().build()

        symbols: List[str] = []
        if UNIVERSE_CSV.exists():
            with open(UNIVERSE_CSV, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        symbols.append(sym)

        if symbols:
            return sorted(set(symbols))

        # fallback to portfolio symbols
        positions = DATA_DIR / "schwab_positions_latest.csv"
        fallback: List[str] = []
        if positions.exists():
            with open(positions, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if str(row.get("asset_type", "")).upper() != "EQUITY":
                        continue
                    sym = str(row.get("symbol", "")).upper().strip()
                    if sym:
                        fallback.append(sym)
        return sorted(set(fallback))

    def _load_base_rankings(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if not FULL_RANKINGS_CSV.exists():
            return out
        with open(FULL_RANKINGS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("symbol", "")).upper().strip()
                if not sym:
                    continue
                out[sym] = _safe_float(row.get("composite_score"), 0.0) or 0.0
        return out

    def _load_equity_holdings(self) -> List[str]:
        if not POSITIONS_CSV.exists():
            return []
        out: List[str] = []
        with open(POSITIONS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if str(row.get("asset_type", "")).upper() != "EQUITY":
                    continue
                sym = str(row.get("symbol", "")).upper().strip()
                if sym:
                    out.append(sym)
        return out

    def _priority_symbols(self, symbols: List[str], base_scores: Dict[str, float]) -> List[str]:
        holdings = self._load_equity_holdings()
        ranked = sorted(base_scores.items(), key=lambda item: item[1], reverse=True)
        priority = holdings + [sym for sym, _ in ranked[:200]]

        seen = set()
        ordered: List[str] = []
        symbol_set = set(symbols)
        for sym in priority:
            if sym in symbol_set and sym not in seen:
                seen.add(sym)
                ordered.append(sym)
        for sym in symbols:
            if sym not in seen:
                seen.add(sym)
                ordered.append(sym)
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

    def _comparison_deltas(self, symbol: str, score: Optional[float], as_of_date: date) -> Tuple[Optional[float], Optional[float]]:
        if score is None:
            return None, None
        history = self._read_csv(OUTPUT_HISTORY_CSV)
        rows = [r for r in history if str(r.get("symbol", "")).upper() == symbol]
        if not rows:
            return None, None

        parsed: List[Tuple[date, float]] = []
        for r in rows:
            try:
                d = date.fromisoformat(str(r.get("snapshot_date", "")))
                v = _safe_float(r.get("earnings_call_intelligence_score"), None)
                if v is not None and d < as_of_date:
                    parsed.append((d, v))
            except Exception:
                continue

        if not parsed:
            return None, None

        parsed.sort(key=lambda t: t[0])
        prev_q = parsed[-1][1]
        one_year_target = as_of_date - timedelta(days=365)
        prev_y_candidates = sorted(parsed, key=lambda t: abs((t[0] - one_year_target).days))
        prev_y = prev_y_candidates[0][1] if prev_y_candidates else None

        delta_q = round(score - prev_q, 2) if prev_q is not None else None
        delta_y = round(score - prev_y, 2) if prev_y is not None else None
        return delta_q, delta_y

    def _score_material(self, text: str) -> Dict[str, Any]:
        demand_score, demand_pos, demand_neg = _keyword_score(
            text,
            positives=[
                "demand",
                "strong demand",
                "accelerat",
                "backlog growth",
                "bookings growth",
                "customer win",
                "expansion",
                "pipeline growth",
                "healthy order",
            ],
            negatives=[
                "demand soften",
                "demand weakened",
                "slow",
                "decelerat",
                "backlog decline",
                "bookings decline",
                "cancel",
                "weak demand",
                "order slowdown",
            ],
            scale=5.0,
        )
        pricing_score, pricing_pos, pricing_neg = _keyword_score(
            text,
            positives=[
                "pricing power",
                "price increase",
                "premium",
                "mix shift",
                "elasticity resilient",
                "stable pricing",
                "improved pricing",
            ],
            negatives=["discount", "price pressure", "promotional", "concession", "price cut", "pricing headwind"],
            scale=7.0,
        )
        margin_score, margin_pos, margin_neg = _keyword_score(
            text,
            positives=[
                "margin expansion",
                "gross margin improvement",
                "operating leverage",
                "productivity",
                "efficiency",
                "cost control",
            ],
            negatives=["margin pressure", "cost inflation", "input cost", "gross margin decline", "higher costs"],
            scale=7.0,
        )
        mgmt_conf_score, conf_pos, conf_neg = _keyword_score(
            text,
            positives=["confident", "visibility", "on track", "raise guidance", "execution", "momentum continues"],
            negatives=["uncertain", "challenging", "headwind", "lower guidance", "volatile", "limited visibility"],
            scale=6.0,
        )
        mgmt_cred_score, cred_pos, cred_neg = _keyword_score(
            text,
            positives=["specific", "quantified", "committed", "delivered", "ahead of plan", "detailed outlook"],
            negatives=["cannot comment", "too early", "limited visibility", "no update", "unclear", "not providing"],
            scale=6.5,
        )
        comp_score, comp_pos, comp_neg = _keyword_score(
            text,
            positives=["market share gain", "competitive advantage", "switching costs", "differentiated", "leadership position"],
            negatives=["competitive pressure", "share loss", "new entrant", "commoditized", "intense competition"],
            scale=7.0,
        )
        cap_alloc_score, cap_pos, cap_neg = _keyword_score(
            text,
            positives=[
                "buyback",
                "deleveraging",
                "disciplined",
                "high return investment",
                "capital efficiency",
                "repurchase",
                "debt reduction",
            ],
            negatives=["dilution", "aggressive acquisition", "uncertain return", "high leverage", "share issuance"],
            scale=6.0,
        )
        risk_deterioration_score, risk_pos, risk_neg = _keyword_score(
            text,
            positives=["risk", "litigation", "regulatory", "customer concentration", "financing need", "geopolitical", "compliance issue"],
            negatives=["de-risk", "mitigated", "diversified", "resolved", "improved visibility", "risk reduced"],
            scale=6.0,
        )

        # For risk score, higher means worse deterioration by design.
        risk_deterioration_score = _clamp_score(100.0 - risk_deterioration_score)

        guidance_consistency, guide_pos, guide_neg = _keyword_score(
            text,
            positives=["reaffirm guidance", "in line", "beat", "ahead", "guidance raised", "better than expected"],
            negatives=["miss", "below guidance", "cut guidance", "withdraw guidance", "guidance lowered"],
            scale=8.0,
        )
        results_alignment, results_pos, results_neg = _keyword_score(
            text,
            positives=["above expectations", "better than expected", "outperformed", "record revenue", "record earnings"],
            negatives=["below expectations", "shortfall", "underperformed", "disappointing results"],
            scale=8.0,
        )

        total_keyword_hits = (
            demand_pos
            + demand_neg
            + pricing_pos
            + pricing_neg
            + margin_pos
            + margin_neg
            + conf_pos
            + conf_neg
            + cred_pos
            + cred_neg
            + comp_pos
            + comp_neg
            + cap_pos
            + cap_neg
            + risk_pos
            + risk_neg
            + guide_pos
            + guide_neg
            + results_pos
            + results_neg
        )

        thesis_impact = _clamp_score(
            (
                demand_score * 0.18
                + pricing_score * 0.12
                + margin_score * 0.12
                + mgmt_conf_score * 0.14
                + mgmt_cred_score * 0.12
                + comp_score * 0.12
                + cap_alloc_score * 0.10
                + (100.0 - risk_deterioration_score) * 0.10
            )
        )
        overall_score = _clamp_score((thesis_impact * 0.65) + ((100.0 - risk_deterioration_score) * 0.35))

        if thesis_impact >= 65:
            thesis_signal = "strengthening thesis"
        elif thesis_impact >= 50:
            thesis_signal = "stable thesis"
        elif thesis_impact >= 35:
            thesis_signal = "weakening thesis"
        else:
            thesis_signal = "potential thesis break"

        strongest_positive = max(
            [
                ("demand", demand_score),
                ("pricing", pricing_score),
                ("margins", margin_score),
                ("management confidence", mgmt_conf_score),
                ("management credibility", mgmt_cred_score),
                ("competitive position", comp_score),
                ("capital allocation", cap_alloc_score),
            ],
            key=lambda t: t[1],
        )
        strongest_negative = min(
            [
                ("demand", demand_score),
                ("pricing", pricing_score),
                ("margins", margin_score),
                ("management confidence", mgmt_conf_score),
                ("management credibility", mgmt_cred_score),
                ("competitive position", comp_score),
                ("capital allocation", cap_alloc_score),
            ],
            key=lambda t: t[1],
        )

        return {
            "earnings_call_demand_momentum_score": round(demand_score, 2),
            "earnings_call_pricing_power_score": round(pricing_score, 2),
            "earnings_call_margin_outlook_score": round(margin_score, 2),
            "earnings_call_management_confidence_score": round(mgmt_conf_score, 2),
            "earnings_call_management_credibility_score": round(mgmt_cred_score, 2),
            "earnings_call_competitive_position_score": round(comp_score, 2),
            "earnings_call_capital_allocation_commentary_score": round(cap_alloc_score, 2),
            "earnings_call_risk_deterioration_score": round(risk_deterioration_score, 2),
            "earnings_call_guidance_consistency_score": round(guidance_consistency, 2),
            "earnings_call_vs_reported_results_score": round(results_alignment, 2),
            "earnings_call_thesis_impact_score": round(thesis_impact, 2),
            "earnings_call_intelligence_score": round(overall_score, 2),
            "earnings_call_thesis_signal": thesis_signal,
            "earnings_call_strongest_positive_change": f"{strongest_positive[0]} ({strongest_positive[1]:.1f})",
            "earnings_call_strongest_negative_change": f"{strongest_negative[0]} ({strongest_negative[1]:.1f})",
            "earnings_call_demand_pos_hits": int(demand_pos),
            "earnings_call_demand_neg_hits": int(demand_neg),
            "earnings_call_total_keyword_hits": int(total_keyword_hits),
        }

    def _build_explainability(
        self,
        symbol: str,
        scores: Dict[str, Any],
        material_payload: Dict[str, Any],
        delta_q: Optional[float],
        delta_y: Optional[float],
    ) -> str:
        lines: List[str] = ["Earnings Call Intelligence:"]
        lines.append(f"- Thesis signal: {scores.get('earnings_call_thesis_signal', NEEDS_RESEARCH)}")
        lines.append(f"- Strongest positive change: {scores.get('earnings_call_strongest_positive_change', NEEDS_RESEARCH)}")
        lines.append(f"- Strongest negative change: {scores.get('earnings_call_strongest_negative_change', NEEDS_RESEARCH)}")
        if delta_q is not None:
            sign = "+" if delta_q >= 0 else ""
            lines.append(f"- Change vs previous quarter: {sign}{delta_q:.2f}")
        else:
            lines.append("- Change vs previous quarter: unavailable")
        if delta_y is not None:
            sign = "+" if delta_y >= 0 else ""
            lines.append(f"- Change vs same quarter last year: {sign}{delta_y:.2f}")
        else:
            lines.append("- Change vs same quarter last year: unavailable")

        materials = material_payload.get("materials", []) if isinstance(material_payload, dict) else []
        if not materials:
            lines.append("- Missing data: official transcript/material unavailable from SEC sources")
            return "\n".join(lines)

        # Copyright-safe: short excerpts only.
        for m in materials[:2]:
            excerpt = str(m.get("excerpt", "")).strip()
            url = str(m.get("url", "")).strip()
            if excerpt:
                lines.append(f"- Excerpt: \"{excerpt[:220]}\"")
            if url:
                lines.append(f"- Source: {url}")

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

    def _append_history(self, rows: List[Dict[str, Any]], base_scores: Dict[str, float], as_of: date) -> None:
        existing = self._read_csv(OUTPUT_HISTORY_CSV)
        seen = {(r.get("snapshot_date", ""), r.get("symbol", "")) for r in existing}
        for row in rows:
            symbol = str(row.get("symbol", "")).upper()
            key = (as_of.isoformat(), symbol)
            if key in seen:
                continue
            existing.append(
                {
                    "snapshot_date": as_of.isoformat(),
                    "symbol": symbol,
                    "earnings_call_intelligence_score": row.get("earnings_call_intelligence_score", NEEDS_RESEARCH),
                    "earnings_call_thesis_impact_score": row.get("earnings_call_thesis_impact_score", NEEDS_RESEARCH),
                    "core_composite_score": base_scores.get(symbol, ""),
                    "resolved_3m": "0",
                    "resolved_6m": "0",
                    "resolved_12m": "0",
                    "resolved_24m": "0",
                    "return_3m_pct": "",
                    "return_6m_pct": "",
                    "return_12m_pct": "",
                    "return_24m_pct": "",
                    "last_evaluated_at": "",
                }
            )
        self._write_csv(OUTPUT_HISTORY_CSV, existing)

    def _resolve_history_returns(self, as_of: date) -> List[Dict[str, str]]:
        rows = self._read_csv(OUTPUT_HISTORY_CSV)
        updated: List[Dict[str, str]] = []
        for row in rows:
            out = dict(row)
            symbol = str(row.get("symbol", "")).upper().strip()
            snap_str = str(row.get("snapshot_date", ""))
            if not symbol:
                updated.append(out)
                continue
            try:
                baseline_date = date.fromisoformat(snap_str)
            except Exception:
                updated.append(out)
                continue

            now = as_of
            for label, days, res_key, ret_key in [
                ("3m", 63, "resolved_3m", "return_3m_pct"),
                ("6m", 126, "resolved_6m", "return_6m_pct"),
                ("12m", 252, "resolved_12m", "return_12m_pct"),
                ("24m", 504, "resolved_24m", "return_24m_pct"),
            ]:
                if str(out.get(res_key, "0")) == "1":
                    continue
                if now < baseline_date + timedelta(days=max(5, int(days * 0.7))):
                    continue
                base = self.close_client.close_at_offset(symbol, baseline_date, 0)
                fwd = self.close_client.close_at_offset(symbol, baseline_date, days)
                if base is None or fwd is None or base <= 0:
                    continue
                ret = ((fwd / base) - 1.0) * 100.0
                out[res_key] = "1"
                out[ret_key] = f"{ret:.6f}"

            out["last_evaluated_at"] = datetime.now().isoformat(timespec="seconds")
            updated.append(out)

        self._write_csv(OUTPUT_HISTORY_CSV, updated)
        return updated

    def _predictive_stats(self, rows: List[Dict[str, str]]) -> List[PredictiveStats]:
        out: List[PredictiveStats] = []
        horizons = [
            ("3m", "resolved_3m", "return_3m_pct"),
            ("6m", "resolved_6m", "return_6m_pct"),
            ("12m", "resolved_12m", "return_12m_pct"),
            ("24m", "resolved_24m", "return_24m_pct"),
        ]
        for label, res_key, ret_key in horizons:
            call_scores: List[float] = []
            base_scores: List[float] = []
            realized: List[float] = []
            for r in rows:
                if str(r.get(res_key, "0")) != "1":
                    continue
                call = _safe_float(r.get("earnings_call_intelligence_score"), None)
                base = _safe_float(r.get("core_composite_score"), None)
                ret = _safe_float(r.get(ret_key), None)
                if call is None or base is None or ret is None:
                    continue
                call_scores.append(call)
                base_scores.append(base)
                realized.append(ret)
            if len(realized) < 2:
                out.append(PredictiveStats(label, len(realized), 0.0, 0.0, 0.0, 0.0))
                continue
            call_ic = _spearman(call_scores, realized)
            base_ic = _spearman(base_scores, realized)
            combined = [0.6 * b + 0.4 * c for b, c in zip(base_scores, call_scores)]
            combined_ic = _spearman(combined, realized)
            out.append(PredictiveStats(label, len(realized), call_ic, base_ic, combined_ic, combined_ic - base_ic))
        return out

    def _weight_recommendation(self, stats: List[PredictiveStats]) -> str:
        # Governance: no meaningful production weight without proven OOS edge.
        min_samples = min((s.resolved_count for s in stats), default=0)
        avg_incremental = _mean([s.incremental_ic for s in stats]) if stats else 0.0
        if min_samples < 40:
            return "No meaningful production weight yet: insufficient out-of-sample resolved samples (need >= 40 across horizons)."
        if avg_incremental < 0.03:
            return "No meaningful production weight yet: incremental predictive value not strong enough out-of-sample."
        return "Small additive production weight may be considered (<= 5%) with ongoing OOS monitoring and manual approval."

    def _write_reports(self, rows: List[Dict[str, Any]], stats: List[PredictiveStats], recommendation: str) -> None:
        score_vals = [_safe_float(r.get("earnings_call_intelligence_score"), None) for r in rows]
        score_vals = [v for v in score_vals if v is not None]

        total_slots = 0
        populated = 0
        valuable = 0
        for row in rows:
            for key, value in row.items():
                if key.endswith("_source") or key.endswith("_timestamp") or key.endswith("_confidence") or key.endswith("_stale"):
                    continue
                if key in {"symbol", "as_of", "earnings_call_engine_version", "refresh_deferred"}:
                    continue
                total_slots += 1
                if value != NEEDS_RESEARCH:
                    populated += 1
                    conf = _safe_float(row.get(f"{key}_confidence"), 0.0) or 0.0
                    if conf >= 55:
                        valuable += 1

        coverage = (populated / total_slots * 100.0) if total_slots else 0.0
        value_pct = (valuable / total_slots * 100.0) if total_slots else 0.0

        top = sorted(rows, key=lambda r: _safe_float(r.get("earnings_call_intelligence_score"), -1.0) or -1.0, reverse=True)[:10]

        lines = [
            "# Earnings Call Intelligence Report",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Data Quality Dashboard",
            "",
            f"- Universe rows: {len(rows)}",
            f"- Earnings-call metric coverage: {coverage:.2f}%",
            "",
            "## Data Value Dashboard",
            "",
            f"- High-confidence earnings-call coverage (confidence >= 55): {value_pct:.2f}%",
            f"- Average Earnings Call Intelligence Score: {_mean(score_vals):.2f}" if score_vals else "- Average Earnings Call Intelligence Score: N/A",
            "",
            "## Explainability Report",
            "",
        ]

        for row in top:
            lines.extend(
                [
                    f"### {row.get('symbol', 'N/A')} (Score: {row.get('earnings_call_intelligence_score', NEEDS_RESEARCH)})",
                    str(row.get("earnings_call_explainability", "Earnings Call Intelligence: unavailable")),
                    "",
                ]
            )

        lines.extend(
            [
                "## Predictive Performance (3m/6m/12m/24m)",
                "",
                "| Horizon | Resolved Samples | Call IC | Base IC | Combined IC | Incremental IC |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for st in stats:
            lines.append(
                f"| {st.horizon_label} | {st.resolved_count} | {st.call_ic:.4f} | {st.base_ic:.4f} | {st.combined_ic:.4f} | {st.incremental_ic:.4f} |"
            )

        lines.extend(
            [
                "",
                "## Weight Governance",
                "",
                f"- {recommendation}",
                "- Earnings Call Intelligence remains additive and does not override Business Quality, Thesis Health, or Valuation.",
                "- No paywalled or access-controlled source was used.",
                "",
            ]
        )

        REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        as_of_date = as_of or date.today()
        symbols = self._load_universe_symbols()
        base_scores = self._load_base_rankings()
        symbols = self._priority_symbols(symbols, base_scores)

        rows: List[Dict[str, Any]] = []
        refresh_count = 0
        for symbol in symbols:
            has_cache = symbol in self.source.cache
            cached_ts = str((self.source.cache.get(symbol) or {}).get("timestamp", "")) if has_cache else ""
            has_fresh_cache = bool(cached_ts and self.source._cache_is_fresh(cached_ts))
            if self.force_refresh:
                should_refresh = refresh_count < self.refresh_limit
            else:
                should_refresh = has_fresh_cache or (refresh_count < self.refresh_limit)

            payload = self.source.fetch_symbol(symbol, force_refresh=self.force_refresh) if should_refresh else {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "source": "SEC Official Earnings Materials (refresh deferred)",
                "stale": True,
                "confidence": 0,
                "source_urls": [],
                "data": {},
            }
            if should_refresh and (self.force_refresh or not has_fresh_cache):
                refresh_count += 1

            data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
            combined_text = str(data.get("combined_text", "") or "")
            has_material = bool(data.get("transcript_available", False)) and bool(combined_text)

            if has_material:
                scores = self._score_material(combined_text)
                total_hits = int(_safe_float(scores.get("earnings_call_total_keyword_hits"), 0.0) or 0)
                if total_hits < 3:
                    has_material = False
                    scores = {
                        "earnings_call_demand_momentum_score": None,
                        "earnings_call_pricing_power_score": None,
                        "earnings_call_margin_outlook_score": None,
                        "earnings_call_management_confidence_score": None,
                        "earnings_call_management_credibility_score": None,
                        "earnings_call_competitive_position_score": None,
                        "earnings_call_capital_allocation_commentary_score": None,
                        "earnings_call_risk_deterioration_score": None,
                        "earnings_call_guidance_consistency_score": None,
                        "earnings_call_vs_reported_results_score": None,
                        "earnings_call_thesis_impact_score": None,
                        "earnings_call_intelligence_score": None,
                        "earnings_call_thesis_signal": "stable thesis",
                        "earnings_call_strongest_positive_change": NEEDS_RESEARCH,
                        "earnings_call_strongest_negative_change": NEEDS_RESEARCH,
                        "earnings_call_demand_pos_hits": 0,
                        "earnings_call_demand_neg_hits": 0,
                        "earnings_call_total_keyword_hits": 0,
                    }
            else:
                scores = {
                    "earnings_call_demand_momentum_score": None,
                    "earnings_call_pricing_power_score": None,
                    "earnings_call_margin_outlook_score": None,
                    "earnings_call_management_confidence_score": None,
                    "earnings_call_management_credibility_score": None,
                    "earnings_call_competitive_position_score": None,
                    "earnings_call_capital_allocation_commentary_score": None,
                    "earnings_call_risk_deterioration_score": None,
                    "earnings_call_guidance_consistency_score": None,
                    "earnings_call_vs_reported_results_score": None,
                    "earnings_call_thesis_impact_score": None,
                    "earnings_call_intelligence_score": None,
                    "earnings_call_thesis_signal": "stable thesis",
                    "earnings_call_strongest_positive_change": NEEDS_RESEARCH,
                    "earnings_call_strongest_negative_change": NEEDS_RESEARCH,
                    "earnings_call_demand_pos_hits": 0,
                    "earnings_call_demand_neg_hits": 0,
                    "earnings_call_total_keyword_hits": 0,
                }

            score_val = _safe_float(scores.get("earnings_call_intelligence_score"), None)
            delta_q, delta_y = self._comparison_deltas(symbol, score_val, as_of_date)
            scores["earnings_call_change_vs_prev_quarter"] = delta_q
            scores["earnings_call_change_vs_prev_year"] = delta_y

            source_urls = payload.get("source_urls", []) if isinstance(payload.get("source_urls"), list) else []
            scores["earnings_call_source_urls"] = json.dumps(source_urls[:10]) if source_urls else NEEDS_RESEARCH
            scores["earnings_call_material_count"] = int(data.get("material_count", 0) or 0)
            scores["earnings_call_transcript_available"] = "1" if has_material else "0"
            if has_material:
                scores["earnings_call_data_missing_reason"] = NEEDS_RESEARCH
            else:
                if int(_safe_float(scores.get("earnings_call_total_keyword_hits"), 0.0) or 0) == 0 and int(data.get("material_count", 0) or 0) > 0:
                    scores["earnings_call_data_missing_reason"] = "Official filing materials found but call-specific signal density was too low"
                else:
                    scores["earnings_call_data_missing_reason"] = "Official transcript/material unavailable from SEC sources"

            explain = self._build_explainability(symbol, scores, data, delta_q, delta_y)
            scores["earnings_call_explainability"] = explain

            source_name = str(payload.get("source", "SEC Official Earnings Materials"))
            ts = str(payload.get("timestamp", datetime.now().isoformat()))
            stale = bool(payload.get("stale", False))
            conf = int(payload.get("confidence", 0))

            row = {
                "symbol": symbol,
                "as_of": as_of_date.isoformat(),
                "earnings_call_engine_version": "1.0.0",
                "refresh_deferred": "1" if not should_refresh else "0",
            }
            row.update(self._build_metric_fields(scores, source_name, ts, conf, stale))
            rows.append(row)

        self._write_csv(OUTPUT_CSV, rows)
        OUTPUT_JSON.write_text(
            json.dumps(
                {
                    "as_of": as_of_date.isoformat(),
                    "engine": "earnings_call_intelligence",
                    "version": "1.0.0",
                    "universe_size": len(symbols),
                    "rows_written": len(rows),
                    "rows": rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        self._append_history(rows, base_scores, as_of_date)
        fast_mode = __import__("os").getenv(
            "CALL_FAST_MODE",
            __import__("os").getenv("SPECIALIST_FAST_MODE", "0"),
        ) == "1"
        if fast_mode:
            stats = []
            recommendation = "Fast mode: predictive backtest refresh deferred for this run."
        else:
            hist = self._resolve_history_returns(as_of_date)
            stats = self._predictive_stats(hist)
            recommendation = self._weight_recommendation(stats)
        self._write_reports(rows, stats, recommendation)

        return {
            "as_of": as_of_date.isoformat(),
            "rows_written": len(rows),
            "output_json": str(OUTPUT_JSON),
            "output_csv": str(OUTPUT_CSV),
            "output_history_csv": str(OUTPUT_HISTORY_CSV),
            "report": str(REPORT_MD),
            "recommendation": recommendation,
        }


def run_earnings_call_intelligence(as_of: Optional[date] = None) -> Dict[str, Any]:
    return EarningsCallIntelligenceEngine().run(as_of=as_of)


def main() -> None:
    out = run_earnings_call_intelligence()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
