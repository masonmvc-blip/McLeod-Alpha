#!/usr/bin/env python3
"""Weekly walk-forward evaluator for McLeod Core Rankings.

This module does three things:
1) Snapshots current ranking predictions into persistent history.
2) Resolves realized outcomes once forward windows are observable.
3) Computes weekly health metrics without future leakage.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

CORE_RANKINGS_CSV = DATA_DIR / "mcleod_core_rankings_latest.csv"
REPLACEMENTS_CSV = DATA_DIR / "replacement_candidates_latest.csv"
PREDICTIONS_HISTORY_CSV = DATA_DIR / "model_predictions_history.csv"
WEEKLY_METRICS_CSV = DATA_DIR / "model_weekly_metrics.csv"
MODEL_HEALTH_REPORT = REPORTS_DIR / "model_health_dashboard.md"

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

FORWARD_1W_DAYS = 5
FORWARD_1M_DAYS = 21

DEFAULT_COMPONENT_WEIGHTS = {
    "component_quality": 0.17,
    "component_valuation": 0.15,
    "component_growth": 0.15,
    "component_ibd": 0.10,
    "component_analyst_intelligence": 0.05,
    "component_earnings_call_intelligence": 0.06,
    "component_insider_intelligence": 0.07,
    "component_earnings_quality": 0.09,
    "component_capital_allocation": 0.08,
    "component_liquidity": 0.05,
    "component_thesis": 0.03,
    "component_data_quality": 0.04,
}

PREDICTION_FIELDS = [
    "prediction_id",
    "prediction_date",
    "prediction_week",
    "symbol",
    "rank",
    "universe_size",
    "is_top_decile",
    "composite_score",
    "current_price_snapshot",
    "replace_symbol",
    "replace_score",
    "weight_quality",
    "weight_valuation",
    "weight_growth",
    "weight_ibd",
    "weight_analyst_intelligence",
    "weight_earnings_call_intelligence",
    "weight_insider_intelligence",
    "weight_earnings_quality",
    "weight_capital_allocation",
    "weight_liquidity",
    "weight_thesis",
    "weight_data_quality",
    "component_quality",
    "component_valuation",
    "component_growth",
    "component_ibd",
    "component_analyst_intelligence",
    "component_earnings_call_intelligence",
    "component_insider_intelligence",
    "component_earnings_quality",
    "component_capital_allocation",
    "component_liquidity",
    "component_thesis",
    "component_data_quality",
    "baseline_close",
    "close_1w",
    "close_1m",
    "spy_baseline_close",
    "spy_close_1w",
    "spy_close_1m",
    "replace_baseline_close",
    "replace_close_1w",
    "replace_close_1m",
    "realized_return_1w_pct",
    "realized_return_1m_pct",
    "spy_return_1w_pct",
    "spy_return_1m_pct",
    "excess_vs_spy_1w_pct",
    "excess_vs_spy_1m_pct",
    "replace_return_1w_pct",
    "replace_return_1m_pct",
    "excess_vs_replace_1w_pct",
    "excess_vs_replace_1m_pct",
    "beat_spy_1w",
    "beat_spy_1m",
    "beat_replace_1w",
    "beat_replace_1m",
    "resolved_1w",
    "resolved_1m",
    "last_evaluated_at",
]

WEEKLY_METRIC_FIELDS = [
    "week",
    "records_total",
    "resolved_1w_count",
    "resolved_1m_count",
    "top_decile_count_1w",
    "ranking_hit_rate_1w",
    "top_decile_return_1w_pct",
    "top_decile_sharpe_1w",
    "beat_spy_rate_1w",
    "beat_replace_rate_1w",
    "calibration_error_1w",
    "avg_excess_vs_spy_1w_pct",
    "run_timestamp",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "NA", "N/A", "NEEDS_RESEARCH"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "NA", "N/A"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _date_to_week(d: date) -> str:
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _pct_return(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None or start <= 0:
        return None
    return ((end / start) - 1.0) * 100.0


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    var = sum((v - m) ** 2 for v in values) / float(len(values) - 1)
    return math.sqrt(max(var, 0.0))


def _weekly_sharpe(returns_pct: Sequence[float]) -> float:
    if len(returns_pct) < 2:
        return 0.0
    mu = _mean(returns_pct)
    sigma = _stdev(returns_pct)
    if sigma <= 0:
        return 0.0
    return (mu / sigma) * math.sqrt(52.0)


def _trading_days_between(start: date, end: date) -> int:
    if end < start:
        return 0
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


@dataclass
class SymbolPriceSeries:
    symbol: str
    rows: List[Tuple[date, float]]

    def close_on_or_after(self, target: date, max_calendar_days: int = 7) -> Optional[float]:
        limit = target + timedelta(days=max_calendar_days)
        for d, px in self.rows:
            if d < target:
                continue
            if d > limit:
                break
            return px
        return None

    def close_at_offset(self, baseline_date: date, trading_day_offset: int) -> Optional[float]:
        idx = -1
        for i, (d, _) in enumerate(self.rows):
            if d >= baseline_date:
                idx = i
                break
        if idx < 0:
            return None
        target_idx = idx + trading_day_offset
        if target_idx >= len(self.rows):
            return None
        return self.rows[target_idx][1]


class YahooDailyClient:
    """Simple daily close downloader using Yahoo chart endpoint."""

    def __init__(self):
        self._cache: Dict[Tuple[str, int, int], SymbolPriceSeries] = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def load(self, symbol: str, start: date, end: date) -> SymbolPriceSeries:
        key = (symbol.upper(), int(start.strftime("%s")), int(end.strftime("%s")))
        if key in self._cache:
            return self._cache[key]

        period1 = int(datetime.combine(start, datetime.min.time()).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=1), datetime.min.time()).timestamp())
        url = YAHOO_URL.format(symbol=symbol.upper())
        params = {
            "period1": str(period1),
            "period2": str(period2),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }

        rows: List[Tuple[date, float]] = []
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
            timestamps = result.get("timestamp") or []
            quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
            closes = quote.get("close") or []
            for ts, cl in zip(timestamps, closes):
                if cl is None:
                    continue
                d = datetime.utcfromtimestamp(int(ts)).date()
                rows.append((d, float(cl)))
        except Exception:
            rows = []

        series = SymbolPriceSeries(symbol=symbol.upper(), rows=rows)
        self._cache[key] = series
        return series


class ModelEvaluator:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.prices = YahooDailyClient()

    def run(self, as_of: Optional[date] = None) -> Dict[str, Any]:
        as_of_date = as_of or date.today()
        added = self.snapshot_predictions(as_of_date)
        resolved = self.resolve_outcomes(as_of_date)
        weekly_rows = self.compute_weekly_metrics(as_of_date)
        self.write_model_health_report(as_of_date, weekly_rows)
        return {
            "as_of": as_of_date.isoformat(),
            "predictions_added": added,
            "predictions_resolved": resolved,
            "weekly_rows": len(weekly_rows),
            "history_csv": str(PREDICTIONS_HISTORY_CSV),
            "weekly_metrics_csv": str(WEEKLY_METRICS_CSV),
            "model_health_report": str(MODEL_HEALTH_REPORT),
        }

    def _load_csv(self, path: Path) -> List[Dict[str, str]]:
        if not path.exists():
            return []
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _write_csv(self, path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})

    def snapshot_predictions(self, as_of: date) -> int:
        rankings = self._load_csv(CORE_RANKINGS_CSV)
        if not rankings:
            return 0

        replacements = self._load_csv(REPLACEMENTS_CSV)
        replacement_by_symbol: Dict[str, Dict[str, str]] = {}
        for r in replacements:
            sym = str(r.get("candidate_symbol", "")).upper().strip()
            if sym:
                replacement_by_symbol[sym] = r

        history = self._load_csv(PREDICTIONS_HISTORY_CSV)
        seen_ids = {r.get("prediction_id", "") for r in history}

        n = len(rankings)
        top_decile_cutoff = max(1, math.ceil(n * 0.10))
        week = _date_to_week(as_of)
        added = 0

        for row in rankings:
            symbol = str(row.get("symbol", "")).upper().strip()
            rank = _safe_int(row.get("rank"), 0)
            if not symbol or rank <= 0:
                continue

            prediction_id = f"{as_of.isoformat()}::{symbol}"
            if prediction_id in seen_ids:
                continue

            repl = replacement_by_symbol.get(symbol, {})
            snapshot = {
                "prediction_id": prediction_id,
                "prediction_date": as_of.isoformat(),
                "prediction_week": week,
                "symbol": symbol,
                "rank": str(rank),
                "universe_size": str(n),
                "is_top_decile": "1" if rank <= top_decile_cutoff else "0",
                "composite_score": str(_safe_float(row.get("composite_score"))),
                "current_price_snapshot": str(_safe_float(row.get("current_price"), 0.0)),
                "replace_symbol": str(repl.get("replace_symbol", "")).upper(),
                "replace_score": str(_safe_float(repl.get("replace_score"), 0.0)),
                "weight_quality": str(DEFAULT_COMPONENT_WEIGHTS["component_quality"]),
                "weight_valuation": str(DEFAULT_COMPONENT_WEIGHTS["component_valuation"]),
                "weight_growth": str(DEFAULT_COMPONENT_WEIGHTS["component_growth"]),
                "weight_ibd": str(DEFAULT_COMPONENT_WEIGHTS["component_ibd"]),
                "weight_analyst_intelligence": str(DEFAULT_COMPONENT_WEIGHTS["component_analyst_intelligence"]),
                "weight_earnings_call_intelligence": str(DEFAULT_COMPONENT_WEIGHTS["component_earnings_call_intelligence"]),
                "weight_insider_intelligence": str(DEFAULT_COMPONENT_WEIGHTS["component_insider_intelligence"]),
                "weight_earnings_quality": str(DEFAULT_COMPONENT_WEIGHTS["component_earnings_quality"]),
                "weight_capital_allocation": str(DEFAULT_COMPONENT_WEIGHTS["component_capital_allocation"]),
                "weight_liquidity": str(DEFAULT_COMPONENT_WEIGHTS["component_liquidity"]),
                "weight_thesis": str(DEFAULT_COMPONENT_WEIGHTS["component_thesis"]),
                "weight_data_quality": str(DEFAULT_COMPONENT_WEIGHTS["component_data_quality"]),
                "component_quality": str(_safe_float(row.get("component_quality"))),
                "component_valuation": str(_safe_float(row.get("component_valuation"))),
                "component_growth": str(_safe_float(row.get("component_growth"))),
                "component_ibd": str(_safe_float(row.get("component_ibd"))),
                "component_analyst_intelligence": str(_safe_float(row.get("component_analyst_intelligence"))),
                "component_earnings_call_intelligence": str(_safe_float(row.get("component_earnings_call_intelligence"))),
                "component_insider_intelligence": str(_safe_float(row.get("component_insider_intelligence"))),
                "component_earnings_quality": str(_safe_float(row.get("component_earnings_quality"))),
                "component_capital_allocation": str(_safe_float(row.get("component_capital_allocation"))),
                "component_liquidity": str(_safe_float(row.get("component_liquidity"))),
                "component_thesis": str(_safe_float(row.get("component_thesis"))),
                "component_data_quality": str(_safe_float(row.get("component_data_quality"))),
                "baseline_close": "",
                "close_1w": "",
                "close_1m": "",
                "spy_baseline_close": "",
                "spy_close_1w": "",
                "spy_close_1m": "",
                "replace_baseline_close": "",
                "replace_close_1w": "",
                "replace_close_1m": "",
                "realized_return_1w_pct": "",
                "realized_return_1m_pct": "",
                "spy_return_1w_pct": "",
                "spy_return_1m_pct": "",
                "excess_vs_spy_1w_pct": "",
                "excess_vs_spy_1m_pct": "",
                "replace_return_1w_pct": "",
                "replace_return_1m_pct": "",
                "excess_vs_replace_1w_pct": "",
                "excess_vs_replace_1m_pct": "",
                "beat_spy_1w": "",
                "beat_spy_1m": "",
                "beat_replace_1w": "",
                "beat_replace_1m": "",
                "resolved_1w": "0",
                "resolved_1m": "0",
                "last_evaluated_at": "",
            }
            history.append(snapshot)
            seen_ids.add(prediction_id)
            added += 1

        self._write_csv(PREDICTIONS_HISTORY_CSV, history, PREDICTION_FIELDS)
        return added

    def _resolve_symbol_windows(
        self,
        symbol: str,
        pred_date: date,
        as_of: date,
    ) -> Tuple[Optional[float], Optional[float], Optional[float], bool, bool]:
        start = pred_date - timedelta(days=10)
        end = as_of + timedelta(days=1)
        series = self.prices.load(symbol, start, end)

        baseline = series.close_on_or_after(pred_date, max_calendar_days=7)
        if baseline is None:
            return None, None, None, False, False

        close_1w = series.close_at_offset(pred_date, FORWARD_1W_DAYS)
        close_1m = series.close_at_offset(pred_date, FORWARD_1M_DAYS)

        # Guard resolution by calendar progress to preserve strict walk-forward timing.
        can_resolve_1w = _trading_days_between(pred_date, as_of) >= FORWARD_1W_DAYS + 1
        can_resolve_1m = _trading_days_between(pred_date, as_of) >= FORWARD_1M_DAYS + 1

        if not can_resolve_1w:
            close_1w = None
        if not can_resolve_1m:
            close_1m = None

        return baseline, close_1w, close_1m, close_1w is not None, close_1m is not None

    def resolve_outcomes(self, as_of: date) -> int:
        history = self._load_csv(PREDICTIONS_HISTORY_CSV)
        if not history:
            return 0

        updates = 0
        for row in history:
            symbol = str(row.get("symbol", "")).upper().strip()
            if not symbol:
                continue

            try:
                pred_date = datetime.fromisoformat(str(row.get("prediction_date", ""))).date()
            except Exception:
                continue

            baseline, close_1w, close_1m, ok_1w, ok_1m = self._resolve_symbol_windows(symbol, pred_date, as_of)
            spy_base, spy_1w, spy_1m, spy_ok_1w, spy_ok_1m = self._resolve_symbol_windows("SPY", pred_date, as_of)

            repl_symbol = str(row.get("replace_symbol", "")).upper().strip()
            repl_base = repl_1w = repl_1m = None
            repl_ok_1w = repl_ok_1m = False
            if repl_symbol:
                repl_base, repl_1w, repl_1m, repl_ok_1w, repl_ok_1m = self._resolve_symbol_windows(
                    repl_symbol,
                    pred_date,
                    as_of,
                )

            before = json.dumps(row, sort_keys=True)

            if baseline is not None:
                row["baseline_close"] = f"{baseline:.6f}"
            if close_1w is not None:
                row["close_1w"] = f"{close_1w:.6f}"
            if close_1m is not None:
                row["close_1m"] = f"{close_1m:.6f}"
            if spy_base is not None:
                row["spy_baseline_close"] = f"{spy_base:.6f}"
            if spy_1w is not None:
                row["spy_close_1w"] = f"{spy_1w:.6f}"
            if spy_1m is not None:
                row["spy_close_1m"] = f"{spy_1m:.6f}"
            if repl_base is not None:
                row["replace_baseline_close"] = f"{repl_base:.6f}"
            if repl_1w is not None:
                row["replace_close_1w"] = f"{repl_1w:.6f}"
            if repl_1m is not None:
                row["replace_close_1m"] = f"{repl_1m:.6f}"

            own_1w = _pct_return(baseline, close_1w) if ok_1w else None
            own_1m = _pct_return(baseline, close_1m) if ok_1m else None
            spy_r_1w = _pct_return(spy_base, spy_1w) if spy_ok_1w else None
            spy_r_1m = _pct_return(spy_base, spy_1m) if spy_ok_1m else None
            repl_r_1w = _pct_return(repl_base, repl_1w) if repl_ok_1w else None
            repl_r_1m = _pct_return(repl_base, repl_1m) if repl_ok_1m else None

            if own_1w is not None:
                row["realized_return_1w_pct"] = f"{own_1w:.6f}"
            if own_1m is not None:
                row["realized_return_1m_pct"] = f"{own_1m:.6f}"
            if spy_r_1w is not None:
                row["spy_return_1w_pct"] = f"{spy_r_1w:.6f}"
            if spy_r_1m is not None:
                row["spy_return_1m_pct"] = f"{spy_r_1m:.6f}"
            if repl_r_1w is not None:
                row["replace_return_1w_pct"] = f"{repl_r_1w:.6f}"
            if repl_r_1m is not None:
                row["replace_return_1m_pct"] = f"{repl_r_1m:.6f}"

            ex_spy_1w = (own_1w - spy_r_1w) if own_1w is not None and spy_r_1w is not None else None
            ex_spy_1m = (own_1m - spy_r_1m) if own_1m is not None and spy_r_1m is not None else None
            ex_rep_1w = (own_1w - repl_r_1w) if own_1w is not None and repl_r_1w is not None else None
            ex_rep_1m = (own_1m - repl_r_1m) if own_1m is not None and repl_r_1m is not None else None

            if ex_spy_1w is not None:
                row["excess_vs_spy_1w_pct"] = f"{ex_spy_1w:.6f}"
                row["beat_spy_1w"] = "1" if ex_spy_1w > 0 else "0"
            if ex_spy_1m is not None:
                row["excess_vs_spy_1m_pct"] = f"{ex_spy_1m:.6f}"
                row["beat_spy_1m"] = "1" if ex_spy_1m > 0 else "0"
            if ex_rep_1w is not None:
                row["excess_vs_replace_1w_pct"] = f"{ex_rep_1w:.6f}"
                row["beat_replace_1w"] = "1" if ex_rep_1w > 0 else "0"
            if ex_rep_1m is not None:
                row["excess_vs_replace_1m_pct"] = f"{ex_rep_1m:.6f}"
                row["beat_replace_1m"] = "1" if ex_rep_1m > 0 else "0"

            if own_1w is not None and spy_r_1w is not None:
                row["resolved_1w"] = "1"
            if own_1m is not None and spy_r_1m is not None:
                row["resolved_1m"] = "1"
            row["last_evaluated_at"] = datetime.now().isoformat(timespec="seconds")

            after = json.dumps(row, sort_keys=True)
            if before != after:
                updates += 1

        self._write_csv(PREDICTIONS_HISTORY_CSV, history, PREDICTION_FIELDS)
        return updates

    def compute_weekly_metrics(self, as_of: date) -> List[Dict[str, Any]]:
        history = self._load_csv(PREDICTIONS_HISTORY_CSV)
        by_week: Dict[str, List[Dict[str, str]]] = {}
        for row in history:
            week = str(row.get("prediction_week", "")).strip()
            if not week:
                continue
            by_week.setdefault(week, []).append(row)

        weekly_rows: List[Dict[str, Any]] = []
        run_ts = datetime.now().isoformat(timespec="seconds")

        for week in sorted(by_week.keys()):
            rows = by_week[week]
            resolved_1w = [r for r in rows if _safe_bool(r.get("resolved_1w"))]
            resolved_1m = [r for r in rows if _safe_bool(r.get("resolved_1m"))]
            top_decile_1w = [r for r in resolved_1w if _safe_bool(r.get("is_top_decile"))]

            hit_values = [_safe_bool(r.get("beat_spy_1w")) for r in top_decile_1w if str(r.get("beat_spy_1w", "")) != ""]
            hit_rate = (_mean([1.0 if v else 0.0 for v in hit_values]) * 100.0) if hit_values else 0.0

            top_decile_rets = [_safe_float(r.get("realized_return_1w_pct"), 0.0) for r in top_decile_1w if str(r.get("realized_return_1w_pct", "")) != ""]
            beat_spy_values = [_safe_bool(r.get("beat_spy_1w")) for r in resolved_1w if str(r.get("beat_spy_1w", "")) != ""]
            beat_rep_values = [_safe_bool(r.get("beat_replace_1w")) for r in resolved_1w if str(r.get("beat_replace_1w", "")) != ""]

            calibration_samples: List[Tuple[float, float]] = []
            for r in resolved_1w:
                if str(r.get("beat_spy_1w", "")) == "":
                    continue
                pred_prob = max(0.0, min(1.0, _safe_float(r.get("composite_score"), 0.0) / 100.0))
                actual = 1.0 if _safe_bool(r.get("beat_spy_1w")) else 0.0
                calibration_samples.append((pred_prob, actual))

            if calibration_samples:
                calibration_error = _mean([(p - a) ** 2 for p, a in calibration_samples])
            else:
                calibration_error = 0.0

            avg_excess = _mean([
                _safe_float(r.get("excess_vs_spy_1w_pct"), 0.0)
                for r in resolved_1w
                if str(r.get("excess_vs_spy_1w_pct", "")) != ""
            ])

            weekly_rows.append(
                {
                    "week": week,
                    "records_total": str(len(rows)),
                    "resolved_1w_count": str(len(resolved_1w)),
                    "resolved_1m_count": str(len(resolved_1m)),
                    "top_decile_count_1w": str(len(top_decile_1w)),
                    "ranking_hit_rate_1w": f"{hit_rate:.4f}",
                    "top_decile_return_1w_pct": f"{_mean(top_decile_rets):.6f}",
                    "top_decile_sharpe_1w": f"{_weekly_sharpe(top_decile_rets):.6f}",
                    "beat_spy_rate_1w": f"{_mean([1.0 if v else 0.0 for v in beat_spy_values]) * 100.0 if beat_spy_values else 0.0:.4f}",
                    "beat_replace_rate_1w": f"{_mean([1.0 if v else 0.0 for v in beat_rep_values]) * 100.0 if beat_rep_values else 0.0:.4f}",
                    "calibration_error_1w": f"{calibration_error:.6f}",
                    "avg_excess_vs_spy_1w_pct": f"{avg_excess:.6f}",
                    "run_timestamp": run_ts,
                }
            )

        self._write_csv(WEEKLY_METRICS_CSV, weekly_rows, WEEKLY_METRIC_FIELDS)
        return weekly_rows

    def write_model_health_report(self, as_of: date, weekly_rows: List[Dict[str, Any]]) -> None:
        history = self._load_csv(PREDICTIONS_HISTORY_CSV)
        total = len(history)
        resolved_1w = sum(1 for r in history if _safe_bool(r.get("resolved_1w")))
        resolved_1m = sum(1 for r in history if _safe_bool(r.get("resolved_1m")))

        latest = weekly_rows[-1] if weekly_rows else {}
        lines = [
            "# Model Health Dashboard",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"As of date: {as_of.isoformat()}",
            "",
            "## Coverage",
            "",
            f"- Total predictions tracked: {total}",
            f"- Resolved +1w outcomes: {resolved_1w}",
            f"- Resolved +1m outcomes: {resolved_1m}",
            "",
            "## Latest Weekly Metrics",
            "",
        ]

        if latest:
            lines.extend(
                [
                    f"- Week: {latest.get('week', 'N/A')}",
                    f"- Ranking hit rate (top decile, +1w): {latest.get('ranking_hit_rate_1w', '0')}%",
                    f"- Top-decile return (+1w): {latest.get('top_decile_return_1w_pct', '0')}%",
                    f"- Top-decile Sharpe (+1w): {latest.get('top_decile_sharpe_1w', '0')}",
                    f"- Beat SPY rate (+1w): {latest.get('beat_spy_rate_1w', '0')}%",
                    f"- Beat replaced-holding rate (+1w): {latest.get('beat_replace_rate_1w', '0')}%",
                    f"- Calibration error (Brier, +1w): {latest.get('calibration_error_1w', '0')}",
                    f"- Avg excess vs SPY (+1w): {latest.get('avg_excess_vs_spy_1w_pct', '0')}%",
                ]
            )
        else:
            lines.append("- No weekly metrics available yet.")

        lines.extend(
            [
                "",
                "## Weekly History",
                "",
                "| Week | N | Resolved +1w | Hit Rate +1w | Top-Decile Return +1w | Beat SPY +1w | Calibration Error |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )

        for row in weekly_rows:
            lines.append(
                "| {week} | {records_total} | {resolved_1w_count} | {ranking_hit_rate_1w}% | {top_decile_return_1w_pct}% | {beat_spy_rate_1w}% | {calibration_error_1w} |".format(
                    **row
                )
            )

        MODEL_HEALTH_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_model_evaluator(as_of: Optional[date] = None) -> Dict[str, Any]:
    evaluator = ModelEvaluator()
    return evaluator.run(as_of=as_of)


def main() -> int:
    result = run_model_evaluator()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())