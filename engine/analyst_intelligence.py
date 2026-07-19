#!/usr/bin/env python3
"""McLeod Analyst Intelligence Engine v1.0.

Collects analyst estimate revisions, scores analyst momentum/confidence,
produces explainability artifacts, and tracks predictive performance.
"""

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

from engine.data_sources.analyst_source import AnalystDataSource
from engine.universe_builder import UniverseBuilder


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

UNIVERSE_CSV = DATA_DIR / "us_equity_universe_latest.csv"
FULL_RANKINGS_CSV = DATA_DIR / "mcleod_full_market_rankings_latest.csv"

OUTPUT_JSON = DATA_DIR / "analyst_estimates_latest.json"
OUTPUT_CSV = DATA_DIR / "analyst_estimates_latest.csv"
OUTPUT_HISTORY_CSV = DATA_DIR / "analyst_estimates_history.csv"

REPORT_MD = REPORTS_DIR / "analyst_intelligence_report.md"
WEEKLY_PERF_REPORT_MD = REPORTS_DIR / "analyst_predictive_performance_weekly.md"

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


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None or prev == 0:
        return None
    return ((curr / prev) - 1.0) * 100.0


def _metric_payload(value: Any, source: str, timestamp: str, confidence: int, stale: bool) -> Dict[str, Any]:
    return {
        "value": value if value not in (None, "") else NEEDS_RESEARCH,
        "source": source,
        "timestamp": timestamp,
        "confidence": int(confidence),
        "stale": bool(stale),
    }


def _trading_days_between(start: date, end: date) -> int:
    if end < start:
        return 0
    count = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


class YahooCloseClient:
    def __init__(self):
        from engine.model_evaluator import YahooDailyClient  # Reuse existing client

        self.client = YahooDailyClient()

    def close_on_or_after(self, symbol: str, target_date: date) -> Optional[float]:
        series = self.client.load(symbol, target_date - timedelta(days=10), date.today() + timedelta(days=2))
        return series.close_on_or_after(target_date)

    def close_at_offset(self, symbol: str, baseline_date: date, offset: int) -> Optional[float]:
        series = self.client.load(symbol, baseline_date - timedelta(days=10), date.today() + timedelta(days=2))
        return series.close_at_offset(baseline_date, offset)


@dataclass
class PredictiveStats:
    horizon_label: str
    resolved_count: int
    analyst_ic: float
    base_ic: float
    combined_ic: float
    incremental_ic: float


class AnalystIntelligenceEngine:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.source = AnalystDataSource()
        self.close_client = YahooCloseClient()

        self.refresh_limit = int(__import__("os").getenv("ANALYST_REFRESH_LIMIT", "40"))
        self.force_refresh = __import__("os").getenv("ANALYST_FORCE_REFRESH", "0") == "1"

    def _load_universe_symbols(self) -> List[str]:
        if not UNIVERSE_CSV.exists():
            UniverseBuilder().build()
        symbols: List[str] = []
        with open(UNIVERSE_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("symbol", "")).upper().strip()
                if sym:
                    symbols.append(sym)
        return sorted(set(symbols))

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

    def _recent_upgrade_downgrade_counts(self, history_rows: List[Dict[str, Any]], days: int = 90) -> Tuple[int, int]:
        cutoff = datetime.now() - timedelta(days=days)
        up = 0
        down = 0
        for row in history_rows:
            try:
                ts = row.get("epochGradeDate")
                dt = datetime.utcfromtimestamp(int(ts)) if ts is not None else None
            except Exception:
                dt = None
            if dt is None or dt < cutoff:
                continue

            action = str(row.get("action") or "").lower()
            to_grade = str(row.get("toGrade") or "").lower()
            from_grade = str(row.get("fromGrade") or "").lower()

            if "up" in action or ("buy" in to_grade and "buy" not in from_grade):
                up += 1
            if "down" in action or ("sell" in to_grade and "sell" not in from_grade):
                down += 1
        return up, down

    def _score_record(self, metrics: Dict[str, Any]) -> Dict[str, Optional[float]]:
        eps_curr = _safe_float(metrics.get("analyst_eps_estimate_current"), None)
        eps_7 = _safe_float(metrics.get("analyst_eps_estimate_7d_ago"), None)
        eps_30 = _safe_float(metrics.get("analyst_eps_estimate_30d_ago"), None)
        eps_90 = _safe_float(metrics.get("analyst_eps_estimate_90d_ago"), None)

        rev_curr = _safe_float(metrics.get("analyst_revenue_estimate_current"), None)
        rev_7 = _safe_float(metrics.get("analyst_revenue_estimate_7d_ago"), None)
        rev_30 = _safe_float(metrics.get("analyst_revenue_estimate_30d_ago"), None)
        rev_90 = _safe_float(metrics.get("analyst_revenue_estimate_90d_ago"), None)

        target_rev_30 = _safe_float(metrics.get("analyst_target_price_revision_30d_pct"), None)
        rec_consensus = _safe_float(metrics.get("analyst_recommendation_consensus"), None)
        n_analysts = _safe_float(metrics.get("analyst_num_analysts"), None)
        dispersion = _safe_float(metrics.get("analyst_estimate_dispersion"), None)
        upgrades = _safe_float(metrics.get("analyst_upgrade_count_90d"), 0.0) or 0.0
        downgrades = _safe_float(metrics.get("analyst_downgrade_count_90d"), 0.0) or 0.0

        eps_changes = [
            _pct_change(eps_curr, eps_7),
            _pct_change(eps_curr, eps_30),
            _pct_change(eps_curr, eps_90),
        ]
        eps_weights = [0.25, 0.35, 0.40]
        eps_vals = [50.0 + (chg * 2.5) for chg in eps_changes if chg is not None]
        eps_score = _clamp_score(_mean(eps_vals)) if eps_vals else None

        rev_changes = [
            _pct_change(rev_curr, rev_7),
            _pct_change(rev_curr, rev_30),
            _pct_change(rev_curr, rev_90),
        ]
        rev_vals = [50.0 + (chg * 2.0) for chg in rev_changes if chg is not None]
        rev_score = _clamp_score(_mean(rev_vals)) if rev_vals else None

        momentum_parts: List[float] = []
        if eps_score is not None:
            momentum_parts.append(eps_score)
        if rev_score is not None:
            momentum_parts.append(rev_score)
        momentum_parts.append(_clamp_score(50.0 + (upgrades - downgrades) * 8.0))
        if target_rev_30 is not None:
            momentum_parts.append(_clamp_score(50.0 + target_rev_30 * 1.5))
        momentum_score = _clamp_score(_mean(momentum_parts)) if momentum_parts else None

        confidence_parts: List[float] = []
        if n_analysts is not None:
            confidence_parts.append(_clamp_score(min(100.0, n_analysts * 4.5)))
        if dispersion is not None:
            confidence_parts.append(_clamp_score(100.0 - min(100.0, dispersion * 2.0)))
        if rec_consensus is not None:
            # Yahoo recommendationMean: lower is stronger buy.
            confidence_parts.append(_clamp_score(120.0 - rec_consensus * 22.0))
        confidence_score = _clamp_score(_mean(confidence_parts)) if confidence_parts else None

        alpha_parts: List[Tuple[float, float]] = []
        if eps_score is not None:
            alpha_parts.append((eps_score, 0.35))
        if rev_score is not None:
            alpha_parts.append((rev_score, 0.20))
        if momentum_score is not None:
            alpha_parts.append((momentum_score, 0.25))
        if confidence_score is not None:
            alpha_parts.append((confidence_score, 0.20))

        alpha_score = None
        if alpha_parts:
            num = sum(v * w for v, w in alpha_parts)
            den = sum(w for _, w in alpha_parts)
            alpha_score = _clamp_score(num / den) if den > 0 else None

        return {
            "analyst_eps_revision_score": eps_score,
            "analyst_revenue_revision_score": rev_score,
            "analyst_estimate_momentum_score": momentum_score,
            "analyst_confidence_score": confidence_score,
            "analyst_alpha_score": alpha_score,
        }

    def _build_explainability(self, row: Dict[str, Any]) -> str:
        lines: List[str] = ["Analyst Intelligence:"]

        eps_curr = _safe_float(row.get("analyst_eps_estimate_current"), None)
        eps_90 = _safe_float(row.get("analyst_eps_estimate_90d_ago"), None)
        eps_delta_90 = _pct_change(eps_curr, eps_90)
        if eps_delta_90 is not None:
            sign = "+" if eps_delta_90 >= 0 else ""
            lines.append(f"+ EPS estimates revised {sign}{eps_delta_90:.1f}% in 90 days")

        rev_curr = _safe_float(row.get("analyst_revenue_estimate_current"), None)
        rev_90 = _safe_float(row.get("analyst_revenue_estimate_90d_ago"), None)
        rev_delta_90 = _pct_change(rev_curr, rev_90)
        if rev_delta_90 is not None:
            if rev_delta_90 >= 0:
                lines.append("+ Revenue estimates revised upward")
            else:
                lines.append("- Revenue estimates revised downward")

        upgrades = int(_safe_float(row.get("analyst_upgrade_count_90d"), 0.0) or 0)
        downgrades = int(_safe_float(row.get("analyst_downgrade_count_90d"), 0.0) or 0)
        if upgrades > 0:
            lines.append(f"+ {upgrades} recent upgrades")
        if downgrades > 0:
            lines.append(f"- {downgrades} recent downgrades")

        target_delta = _safe_float(row.get("analyst_target_price_revision_30d_pct"), None)
        if target_delta is None:
            lines.append("- Target price revision unavailable")
        elif abs(target_delta) < 0.10:
            lines.append("- Target price unchanged")
        elif target_delta > 0:
            lines.append("+ Target price revised higher")
        else:
            lines.append("- Target price revised lower")

        return "\n".join(lines)

    def _build_metric_fields(self, row: Dict[str, Any], source: str, timestamp: str, confidence: int, stale: bool) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for metric, value in row.items():
            out[metric] = value if value is not None else NEEDS_RESEARCH
            out[f"{metric}_source"] = source
            out[f"{metric}_timestamp"] = timestamp
            out[f"{metric}_confidence"] = confidence if value is not None else 0
            out[f"{metric}_stale"] = stale if value is not None else True
        return out

    def _read_csv(self, path: Path) -> List[Dict[str, str]]:
        if not path.exists():
            return []
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _write_csv(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            with open(path, "w", newline="", encoding="utf-8") as f:
                f.write("")
            return
        fields = list(rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    def _append_history(self, rows: List[Dict[str, Any]], base_scores: Dict[str, float], as_of: date) -> None:
        existing = self._read_csv(OUTPUT_HISTORY_CSV)
        seen = {(r.get("snapshot_date", ""), r.get("symbol", "")) for r in existing}

        for row in rows:
            sym = row.get("symbol", "")
            key = (as_of.isoformat(), sym)
            if key in seen:
                continue
            existing.append(
                {
                    "snapshot_date": as_of.isoformat(),
                    "symbol": sym,
                    "analyst_alpha_score": row.get("analyst_alpha_score", NEEDS_RESEARCH),
                    "core_composite_score": base_scores.get(sym, ""),
                    "target_price_consensus": row.get("analyst_target_price_consensus", NEEDS_RESEARCH),
                    "resolved_6m": "0",
                    "resolved_12m": "0",
                    "resolved_24m": "0",
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

        horizon_map = {
            "6m": (126, "resolved_6m", "return_6m_pct"),
            "12m": (252, "resolved_12m", "return_12m_pct"),
            "24m": (504, "resolved_24m", "return_24m_pct"),
        }

        for row in rows:
            sym = str(row.get("symbol", "")).upper().strip()
            try:
                snap = datetime.fromisoformat(str(row.get("snapshot_date", ""))).date()
            except Exception:
                updated.append(row)
                continue

            baseline = self.close_client.close_on_or_after(sym, snap)
            if baseline is None or baseline <= 0:
                updated.append(row)
                continue

            for _, (offset, resolved_key, return_key) in horizon_map.items():
                if row.get(resolved_key) == "1":
                    continue
                if _trading_days_between(snap, as_of) < (offset + 1):
                    continue
                px = self.close_client.close_at_offset(sym, snap, offset)
                if px is None:
                    continue
                ret = ((px / baseline) - 1.0) * 100.0
                row[return_key] = f"{ret:.6f}"
                row[resolved_key] = "1"

            row["last_evaluated_at"] = datetime.now().isoformat(timespec="seconds")
            updated.append(row)

        self._write_csv(OUTPUT_HISTORY_CSV, updated)
        return updated

    def _predictive_stats(self, history_rows: List[Dict[str, str]]) -> List[PredictiveStats]:
        stats: List[PredictiveStats] = []
        horizons = [
            ("6m", "return_6m_pct", "resolved_6m"),
            ("12m", "return_12m_pct", "resolved_12m"),
            ("24m", "return_24m_pct", "resolved_24m"),
        ]

        for label, ret_key, resolved_key in horizons:
            sample = [r for r in history_rows if r.get(resolved_key) == "1" and r.get(ret_key, "") != ""]
            x_analyst: List[float] = []
            x_base: List[float] = []
            y: List[float] = []
            for r in sample:
                a = _safe_float(r.get("analyst_alpha_score"), None)
                b = _safe_float(r.get("core_composite_score"), None)
                ret = _safe_float(r.get(ret_key), None)
                if a is None or ret is None:
                    continue
                x_analyst.append(a)
                x_base.append(b if b is not None else 0.0)
                y.append(ret)

            analyst_ic = _spearman(x_analyst, y)
            base_ic = _spearman(x_base, y)
            combined = [0.8 * b + 0.2 * a for a, b in zip(x_analyst, x_base)]
            combined_ic = _spearman(combined, y)
            stats.append(
                PredictiveStats(
                    horizon_label=label,
                    resolved_count=len(y),
                    analyst_ic=analyst_ic,
                    base_ic=base_ic,
                    combined_ic=combined_ic,
                    incremental_ic=combined_ic - base_ic,
                )
            )

        return stats

    def _weight_recommendation(self, stats: List[PredictiveStats]) -> str:
        valid = [s for s in stats if s.resolved_count >= 50]
        if not valid:
            return "No analyst model weight change recommended yet: insufficient out-of-sample resolved samples (need >= 50 per horizon)."

        positive = [s for s in valid if s.analyst_ic > 0 and s.incremental_ic > 0]
        if len(positive) >= 2:
            avg_inc = _mean([s.incremental_ic for s in positive])
            weight = min(0.10, max(0.02, avg_inc * 2.0))
            return (
                f"Proposed analyst factor weight: {weight:.2%}, conditioned on manual approval and continued OOS validation. "
                "No automatic production weight changes are applied by this engine."
            )
        return "No analyst model weight increase recommended: incremental predictive value is not yet consistently positive OOS."

    def run(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        as_of_date = as_of or date.today()
        symbols = self._load_universe_symbols()
        base_scores = self._load_base_rankings()

        rows: List[Dict[str, Any]] = []
        refresh_count = 0

        prior_rows = self._read_csv(OUTPUT_CSV)
        prior_by_symbol: Dict[str, Dict[str, str]] = {str(r.get("symbol", "")).upper(): r for r in prior_rows}

        for symbol in symbols:
            has_cache = symbol in self.source.cache
            cached_ts = str((self.source.cache.get(symbol) or {}).get("timestamp", "")) if has_cache else ""
            has_fresh_cache = bool(cached_ts and self.source._cache_is_fresh(cached_ts))
            should_refresh = False
            if self.force_refresh:
                should_refresh = refresh_count < self.refresh_limit
            else:
                # Default mode: process full universe but limit outbound refresh calls.
                should_refresh = has_fresh_cache or (refresh_count < self.refresh_limit)

            if should_refresh:
                payload = self.source.fetch_symbol(symbol, force_refresh=self.force_refresh)
                # Count only symbols that required a live refresh attempt.
                if self.force_refresh or not has_fresh_cache:
                    refresh_count += 1
            else:
                payload = {
                    "symbol": symbol,
                    "timestamp": datetime.now().isoformat(),
                    "source": "Analyst Source (refresh deferred)",
                    "stale": True,
                    "confidence": 0,
                    "data": {},
                }
            raw = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}

            upgrades_90, downgrades_90 = self._recent_upgrade_downgrade_counts(raw.get("upgrade_downgrade_history", []), days=90)

            prev = prior_by_symbol.get(symbol, {})
            current_target = _safe_float(raw.get("target_mean"), None)
            prev_target = _safe_float(prev.get("analyst_target_price_consensus"), None)
            target_revision_30d = _pct_change(current_target, prev_target) if current_target is not None and prev_target is not None else None

            core_metrics = {
                "analyst_eps_estimate_current": _safe_float(raw.get("eps_current"), None),
                "analyst_eps_estimate_7d_ago": _safe_float(raw.get("eps_7d_ago"), None),
                "analyst_eps_estimate_30d_ago": _safe_float(raw.get("eps_30d_ago"), None),
                "analyst_eps_estimate_90d_ago": _safe_float(raw.get("eps_90d_ago"), None),
                "analyst_revenue_estimate_current": _safe_float(raw.get("revenue_current"), None),
                "analyst_revenue_estimate_7d_ago": _safe_float(raw.get("revenue_7d_ago"), None),
                "analyst_revenue_estimate_30d_ago": _safe_float(raw.get("revenue_30d_ago"), None),
                "analyst_revenue_estimate_90d_ago": _safe_float(raw.get("revenue_90d_ago"), None),
                "analyst_long_term_growth_estimate": _safe_float(raw.get("long_term_growth"), None),
                "analyst_recommendation_consensus": _safe_float(raw.get("recommendation_mean"), None),
                "analyst_num_analysts": _safe_float(raw.get("num_analysts_recommendation"), None)
                or _safe_float(raw.get("num_analysts_revenue"), None),
                "analyst_estimate_dispersion": _safe_float(raw.get("estimate_dispersion_pct"), None),
                "analyst_target_price_consensus": _safe_float(raw.get("target_mean"), None),
                "analyst_target_price_revision_30d_pct": target_revision_30d,
                "analyst_upgrade_count_90d": float(upgrades_90),
                "analyst_downgrade_count_90d": float(downgrades_90),
                "analyst_upgrade_downgrade_history": json.dumps(raw.get("upgrade_downgrade_history", [])[:20]),
            }

            score_metrics = self._score_record(core_metrics)
            merged = dict(core_metrics)
            merged.update(score_metrics)

            explain = self._build_explainability(merged)
            merged["analyst_intelligence_explainability"] = explain

            source_name = str(payload.get("source", "Analyst Source"))
            ts = str(payload.get("timestamp", datetime.now().isoformat()))
            stale = bool(payload.get("stale", False))
            conf = int(payload.get("confidence", 0))

            row = {
                "symbol": symbol,
                "as_of": as_of_date.isoformat(),
                "analyst_engine_version": "1.0.0",
                "refresh_deferred": "1" if not should_refresh else "0",
            }
            row.update(self._build_metric_fields(merged, source_name, ts, conf, stale))
            rows.append(row)

        output_json = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "engine": "McLeod Analyst Intelligence Engine",
                "version": "1.0.0",
                "universe_size": len(symbols),
                "rows": len(rows),
                "refresh_limit": self.refresh_limit,
                "force_refresh": self.force_refresh,
            },
            "holdings": rows,
        }
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output_json, f, indent=2)

        self._write_csv(OUTPUT_CSV, rows)
        self._append_history(rows, base_scores, as_of_date)

        fast_mode = __import__("os").getenv(
            "ANALYST_FAST_MODE",
            __import__("os").getenv("SPECIALIST_FAST_MODE", "0"),
        ) == "1"
        if fast_mode:
            stats = []
            recommendation = "Fast mode: predictive backtest refresh deferred for this run."
        else:
            history_rows = self._resolve_history_returns(as_of_date)
            stats = self._predictive_stats(history_rows)
            recommendation = self._weight_recommendation(stats)

        self._write_reports(rows, stats, recommendation)

        return {
            "as_of": as_of_date.isoformat(),
            "universe_size": len(symbols),
            "rows_written": len(rows),
            "output_json": str(OUTPUT_JSON),
            "output_csv": str(OUTPUT_CSV),
            "report": str(REPORT_MD),
            "weekly_performance_report": str(WEEKLY_PERF_REPORT_MD),
            "weight_recommendation": recommendation,
        }

    def _write_reports(self, rows: List[Dict[str, Any]], stats: List[PredictiveStats], recommendation: str) -> None:
        alpha_values = [
            _safe_float(r.get("analyst_alpha_score"), None)
            for r in rows
            if _safe_float(r.get("analyst_alpha_score"), None) is not None
        ]
        dq_count = 0
        value_count = 0
        total_slots = 0
        for row in rows:
            for key in list(row.keys()):
                if key.endswith("_source") or key.endswith("_timestamp") or key.endswith("_confidence") or key.endswith("_stale"):
                    continue
                if key in {"symbol", "as_of", "analyst_engine_version", "refresh_deferred"}:
                    continue
                total_slots += 1
                if row.get(key) != NEEDS_RESEARCH:
                    dq_count += 1
                    conf = _safe_float(row.get(f"{key}_confidence"), 0.0) or 0.0
                    value_count += (1 if conf >= 50 else 0)

        data_quality_pct = (dq_count / total_slots * 100.0) if total_slots else 0.0
        data_value_pct = (value_count / total_slots * 100.0) if total_slots else 0.0

        top_explain = sorted(
            rows,
            key=lambda r: _safe_float(r.get("analyst_alpha_score"), -1.0) or -1.0,
            reverse=True,
        )[:10]

        lines = [
            "# Analyst Intelligence Report",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Data Quality Dashboard",
            "",
            f"- Universe rows: {len(rows)}",
            f"- Analyst metric coverage: {data_quality_pct:.2f}%",
            "",
            "## Data Value Dashboard",
            "",
            f"- High-confidence analyst coverage (confidence >= 50): {data_value_pct:.2f}%",
            f"- Average Analyst Alpha Score (available rows): {_mean(alpha_values):.2f}" if alpha_values else "- Average Analyst Alpha Score: N/A",
            "",
            "## Explainability Report",
            "",
        ]

        for row in top_explain:
            lines.extend(
                [
                    f"### {row.get('symbol', 'N/A')} (Analyst Alpha: {row.get('analyst_alpha_score', NEEDS_RESEARCH)})",
                    str(row.get("analyst_intelligence_explainability", "Analyst Intelligence: unavailable")),
                    "",
                ]
            )

        lines.extend(
            [
                "## Predictive Performance (6m/12m/24m)",
                "",
                "| Horizon | Resolved Samples | Analyst IC | Base IC | Combined IC | Incremental IC |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for st in stats:
            lines.append(
                f"| {st.horizon_label} | {st.resolved_count} | {st.analyst_ic:.4f} | {st.base_ic:.4f} | {st.combined_ic:.4f} | {st.incremental_ic:.4f} |"
            )

        lines.extend([
            "",
            "## Weight Governance",
            "",
            f"- {recommendation}",
            "- Analyst Intelligence is an additive evidence source and does not override Business Quality, Thesis Health, or Valuation.",
            "",
        ])

        REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

        weekly_lines = [
            "# Weekly Analyst Predictive Performance",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "| Horizon | Resolved Samples | Analyst IC | Base IC | Combined IC | Incremental IC |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for st in stats:
            weekly_lines.append(
                f"| {st.horizon_label} | {st.resolved_count} | {st.analyst_ic:.4f} | {st.base_ic:.4f} | {st.combined_ic:.4f} | {st.incremental_ic:.4f} |"
            )
        weekly_lines.extend(["", "Recommendation:", f"- {recommendation}", ""])
        WEEKLY_PERF_REPORT_MD.write_text("\n".join(weekly_lines), encoding="utf-8")



def run_analyst_intelligence(as_of: Optional[date] = None) -> Dict[str, Any]:
    return AnalystIntelligenceEngine().run(as_of=as_of)


def main() -> int:
    result = run_analyst_intelligence()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
