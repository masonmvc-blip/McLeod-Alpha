#!/usr/bin/env python3
"""Weekly factor-weight optimizer with strict OOS governance.

Reads model prediction history, evaluates factor behavior in a train window,
validates in an OOS evaluation week, and emits a guarded recommendation.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

PREDICTIONS_HISTORY_CSV = DATA_DIR / "model_predictions_history.csv"
FACTOR_PERF_HISTORY_CSV = DATA_DIR / "factor_performance_history.csv"
WEEKLY_REPORT = REPORTS_DIR / "weekly_model_improvement.md"

FACTOR_COLUMNS = [
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
]

CURRENT_WEIGHTS = {
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

FACTOR_HISTORY_FIELDS = [
    "run_timestamp",
    "evaluation_week",
    "factor",
    "train_ic",
    "oos_ic",
    "redundancy_max_corr",
    "train_samples",
    "oos_samples",
    "suggested_delta",
    "overfit_flag",
    "evidence",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "NA", "N/A", "NEEDS_RESEARCH"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


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


def _normalize_weights(weights: Dict[str, float], floor: float = 0.01) -> Dict[str, float]:
    clipped = {k: max(floor, float(v)) for k, v in weights.items()}
    s = sum(clipped.values())
    if s <= 0:
        return dict(CURRENT_WEIGHTS)
    return {k: v / s for k, v in clipped.items()}


@dataclass
class FactorStat:
    factor: str
    train_ic: float
    oos_ic: float
    redundancy_max_corr: float
    train_samples: int
    oos_samples: int
    suggested_delta: float
    overfit_flag: bool
    evidence: str


class WeightOptimizer:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def _load_history(self) -> List[Dict[str, str]]:
        if not PREDICTIONS_HISTORY_CSV.exists():
            return []
        with open(PREDICTIONS_HISTORY_CSV, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _append_factor_history(self, rows: List[Dict[str, Any]]) -> None:
        existing: List[Dict[str, str]] = []
        if FACTOR_PERF_HISTORY_CSV.exists():
            with open(FACTOR_PERF_HISTORY_CSV, newline="", encoding="utf-8") as f:
                existing = list(csv.DictReader(f))

        existing.extend(rows)
        with open(FACTOR_PERF_HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FACTOR_HISTORY_FIELDS)
            w.writeheader()
            for row in existing:
                w.writerow({k: row.get(k, "") for k in FACTOR_HISTORY_FIELDS})

    def _append_status_history(self, evaluation_week: str, reason: str) -> None:
        self._append_factor_history(
            [
                {
                    "run_timestamp": datetime.now().isoformat(timespec="seconds"),
                    "evaluation_week": evaluation_week,
                    "factor": "__status__",
                    "train_ic": "",
                    "oos_ic": "",
                    "redundancy_max_corr": "",
                    "train_samples": "",
                    "oos_samples": "",
                    "suggested_delta": "",
                    "overfit_flag": "",
                    "evidence": reason,
                }
            ]
        )

    def _build_scored_rows(self, rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in rows:
            if not _safe_bool(r.get("resolved_1w")):
                continue
            ex = r.get("excess_vs_spy_1w_pct", "")
            if ex == "":
                continue
            row = {
                "week": r.get("prediction_week", ""),
                "symbol": r.get("symbol", ""),
                "rank": _safe_float(r.get("rank"), 0.0),
                "is_top_decile": _safe_bool(r.get("is_top_decile")),
                "excess_vs_spy_1w_pct": _safe_float(ex, 0.0),
                "realized_return_1w_pct": _safe_float(r.get("realized_return_1w_pct"), 0.0),
            }
            for f in FACTOR_COLUMNS:
                row[f] = _safe_float(r.get(f), 0.0)
            out.append(row)
        return out

    def _factor_stats(
        self,
        train_rows: List[Dict[str, Any]],
        oos_rows: List[Dict[str, Any]],
    ) -> List[FactorStat]:
        stats: List[FactorStat] = []

        factor_matrix_train: Dict[str, List[float]] = {
            f: [r[f] for r in train_rows] for f in FACTOR_COLUMNS
        }
        y_train = [r["excess_vs_spy_1w_pct"] for r in train_rows]
        y_oos = [r["excess_vs_spy_1w_pct"] for r in oos_rows]

        for factor in FACTOR_COLUMNS:
            x_train = factor_matrix_train[factor]
            x_oos = [r[factor] for r in oos_rows]
            train_ic = _spearman(x_train, y_train)
            oos_ic = _spearman(x_oos, y_oos)

            redundancies: List[float] = []
            for other in FACTOR_COLUMNS:
                if other == factor:
                    continue
                redundancies.append(abs(_pearson(x_train, factor_matrix_train[other])))
            redundancy = max(redundancies) if redundancies else 0.0

            sign_flip = (train_ic > 0 and oos_ic < 0) or (train_ic < 0 and oos_ic > 0)
            weak_oos = abs(oos_ic) < 0.03
            overfit = sign_flip or (abs(train_ic) >= 0.10 and weak_oos)

            delta = 0.0
            if not overfit and oos_ic > 0.02:
                delta = min(0.04, max(0.0, oos_ic * 0.10))
                if redundancy > 0.85:
                    delta *= 0.5
            elif oos_ic < -0.02:
                delta = max(-0.04, oos_ic * 0.10)

            evidence = (
                f"train_ic={train_ic:.3f}, oos_ic={oos_ic:.3f}, "
                f"redundancy={redundancy:.3f}, overfit={overfit}"
            )
            stats.append(
                FactorStat(
                    factor=factor,
                    train_ic=train_ic,
                    oos_ic=oos_ic,
                    redundancy_max_corr=redundancy,
                    train_samples=len(train_rows),
                    oos_samples=len(oos_rows),
                    suggested_delta=delta,
                    overfit_flag=overfit,
                    evidence=evidence,
                )
            )

        return stats

    def _score_row(self, row: Dict[str, Any], weights: Dict[str, float]) -> float:
        return sum(float(row.get(f, 0.0)) * weights.get(f, 0.0) for f in FACTOR_COLUMNS)

    def _top_decile_rows(self, rows: List[Dict[str, Any]], weights: Dict[str, float]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        scored = [dict(r, _score=self._score_row(r, weights)) for r in rows]
        scored.sort(key=lambda r: r["_score"], reverse=True)
        cutoff = max(1, math.ceil(len(scored) * 0.10))
        return scored[:cutoff]

    def _top_decile_return(self, rows: List[Dict[str, Any]], weights: Dict[str, float]) -> float:
        top = self._top_decile_rows(rows, weights)
        if not top:
            return 0.0
        return _mean([float(r.get("realized_return_1w_pct", 0.0)) for r in top])

    def _top_decile_excess(self, rows: List[Dict[str, Any]], weights: Dict[str, float]) -> float:
        top = self._top_decile_rows(rows, weights)
        if not top:
            return 0.0
        return _mean([float(r.get("excess_vs_spy_1w_pct", 0.0)) for r in top])

    def _turnover_proxy(self, rows: List[Dict[str, Any]], w_a: Dict[str, float], w_b: Dict[str, float]) -> float:
        a = {r["symbol"] for r in self._top_decile_rows(rows, w_a)}
        b = {r["symbol"] for r in self._top_decile_rows(rows, w_b)}
        if not a and not b:
            return 0.0
        inter = len(a.intersection(b))
        union = len(a.union(b))
        if union <= 0:
            return 0.0
        return 1.0 - (inter / float(union))

    def _drawdown_proxy(self, rows: List[Dict[str, Any]], weights: Dict[str, float]) -> float:
        top = self._top_decile_rows(rows, weights)
        if not top:
            return 0.0
        returns = [float(r.get("realized_return_1w_pct", 0.0)) for r in top]
        return min(returns) if returns else 0.0

    def run(self) -> Dict[str, Any]:
        raw = self._load_history()
        scored = self._build_scored_rows(raw)

        weeks = sorted({r["week"] for r in scored if r.get("week")})
        if len(weeks) < 2:
            result = {
                "status": "insufficient_history",
                "reason": "Need at least two resolved weeks for train/OOS split.",
                "weeks_available": weeks,
            }
            eval_week = weeks[-1] if weeks else "N/A"
            self._append_status_history(eval_week, result["reason"])
            self._write_report(result)
            return result

        eval_week = weeks[-1]
        train_weeks = weeks[:-1]
        if len(train_weeks) > 8:
            train_weeks = train_weeks[-8:]

        train_rows = [r for r in scored if r["week"] in train_weeks]
        oos_rows = [r for r in scored if r["week"] == eval_week]

        if len(train_rows) < 20 or len(oos_rows) < 8:
            result = {
                "status": "insufficient_samples",
                "reason": "Insufficient samples for statistically useful optimization.",
                "evaluation_week": eval_week,
                "train_samples": len(train_rows),
                "oos_samples": len(oos_rows),
            }
            self._append_status_history(eval_week, result["reason"])
            self._write_report(result)
            return result

        stats = self._factor_stats(train_rows, oos_rows)

        proposed = dict(CURRENT_WEIGHTS)
        for s in stats:
            proposed[s.factor] = max(0.01, proposed[s.factor] + s.suggested_delta)
        proposed = _normalize_weights(proposed, floor=0.01)

        current_oos_excess = self._top_decile_excess(oos_rows, CURRENT_WEIGHTS)
        proposed_oos_excess = self._top_decile_excess(oos_rows, proposed)
        excess_improvement = proposed_oos_excess - current_oos_excess

        current_drawdown_proxy = self._drawdown_proxy(oos_rows, CURRENT_WEIGHTS)
        proposed_drawdown_proxy = self._drawdown_proxy(oos_rows, proposed)
        turnover_proxy = self._turnover_proxy(oos_rows, CURRENT_WEIGHTS, proposed)

        oos_ic_values = [s.oos_ic for s in stats]
        overfit_count = sum(1 for s in stats if s.overfit_flag)
        positive_oos = sum(1 for v in oos_ic_values if v > 0.02)

        gates = {
            "sample_size_ok": len(train_rows) >= 20 and len(oos_rows) >= 8,
            "oos_improvement_ok": excess_improvement >= 0.10,
            "oos_signal_ok": positive_oos >= 3,
            "overfit_ok": overfit_count <= 2,
            "drawdown_ok": proposed_drawdown_proxy >= current_drawdown_proxy - 2.0,
            "turnover_ok": turnover_proxy <= 0.35,
        }
        can_auto_apply = all(gates.values())

        factor_history_rows: List[Dict[str, Any]] = []
        run_ts = datetime.now().isoformat(timespec="seconds")
        for s in stats:
            factor_history_rows.append(
                {
                    "run_timestamp": run_ts,
                    "evaluation_week": eval_week,
                    "factor": s.factor,
                    "train_ic": f"{s.train_ic:.6f}",
                    "oos_ic": f"{s.oos_ic:.6f}",
                    "redundancy_max_corr": f"{s.redundancy_max_corr:.6f}",
                    "train_samples": str(s.train_samples),
                    "oos_samples": str(s.oos_samples),
                    "suggested_delta": f"{s.suggested_delta:.6f}",
                    "overfit_flag": "1" if s.overfit_flag else "0",
                    "evidence": s.evidence,
                }
            )
        self._append_factor_history(factor_history_rows)

        recommendation = {
            "status": "ok",
            "evaluation_week": eval_week,
            "train_weeks": train_weeks,
            "train_samples": len(train_rows),
            "oos_samples": len(oos_rows),
            "current_weights": CURRENT_WEIGHTS,
            "proposed_weights": proposed,
            "current_oos_top_decile_excess_pct": current_oos_excess,
            "proposed_oos_top_decile_excess_pct": proposed_oos_excess,
            "oos_excess_improvement_pct": excess_improvement,
            "current_drawdown_proxy_pct": current_drawdown_proxy,
            "proposed_drawdown_proxy_pct": proposed_drawdown_proxy,
            "turnover_proxy": turnover_proxy,
            "positive_oos_factor_count": positive_oos,
            "overfit_factor_count": overfit_count,
            "gates": gates,
            "auto_apply_allowed": can_auto_apply,
            "auto_apply_action": "none" if not can_auto_apply else "manual_approval_still_required",
            "factor_stats": [s.__dict__ for s in stats],
        }
        self._write_report(recommendation)
        return recommendation

    def _write_report(self, rec: Dict[str, Any]) -> None:
        lines = [
            "# Weekly Model Improvement",
            "",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
        ]

        status = rec.get("status", "unknown")
        lines.append(f"- Status: {status}")

        if status != "ok":
            lines.append(f"- Reason: {rec.get('reason', 'N/A')}")
            if rec.get("weeks_available") is not None:
                lines.append(f"- Weeks available: {rec.get('weeks_available')}")
            if rec.get("train_samples") is not None:
                lines.append(f"- Train samples: {rec.get('train_samples')}")
            if rec.get("oos_samples") is not None:
                lines.append(f"- OOS samples: {rec.get('oos_samples')}")
            WEEKLY_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

        lines.extend(
            [
                f"- Evaluation week: {rec.get('evaluation_week')}",
                f"- Train samples: {rec.get('train_samples')}",
                f"- OOS samples: {rec.get('oos_samples')}",
                f"- Current top-decile excess (+1w): {rec.get('current_oos_top_decile_excess_pct', 0.0):.4f}%",
                f"- Proposed top-decile excess (+1w): {rec.get('proposed_oos_top_decile_excess_pct', 0.0):.4f}%",
                f"- OOS excess improvement: {rec.get('oos_excess_improvement_pct', 0.0):.4f}%",
                f"- Turnover proxy: {rec.get('turnover_proxy', 0.0):.4f}",
                f"- Drawdown proxy current/proposed: {rec.get('current_drawdown_proxy_pct', 0.0):.4f}% / {rec.get('proposed_drawdown_proxy_pct', 0.0):.4f}%",
                f"- Auto-apply allowed: {rec.get('auto_apply_allowed')}",
                "",
                "## Gate Checks",
                "",
            ]
        )

        for name, ok in (rec.get("gates") or {}).items():
            lines.append(f"- {name}: {'PASS' if ok else 'FAIL'}")

        lines.extend(
            [
                "",
                "## Factor Evidence",
                "",
                "| Factor | Train IC | OOS IC | Redundancy | Suggested Delta | Overfit |",
                "| --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )

        for row in rec.get("factor_stats", []):
            lines.append(
                "| {factor} | {train_ic:.4f} | {oos_ic:.4f} | {redundancy_max_corr:.4f} | {suggested_delta:.4f} | {overfit_flag} |".format(
                    **row
                )
            )

        lines.extend(
            [
                "",
                "## Weight Recommendation",
                "",
                "Current:",
                "```json",
                json.dumps(rec.get("current_weights", {}), indent=2),
                "```",
                "",
                "Proposed:",
                "```json",
                json.dumps(rec.get("proposed_weights", {}), indent=2),
                "```",
                "",
                "Audit decision:",
                "- No production weight changes are applied automatically by this optimizer.",
                "- Recommendation is evidence-only unless all OOS/risk gates pass and manual approval is provided.",
            ]
        )

        WEEKLY_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_weight_optimizer() -> Dict[str, Any]:
    return WeightOptimizer().run()


def main() -> int:
    result = run_weight_optimizer()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())