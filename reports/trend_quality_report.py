"""Read-only trend-quality analysis for enriched opportunity reviews."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
REPORTS_DIR = Path("reports")
MINIMUM_SAMPLE_SIZE = 10
DEEP_VALIDATION_SAMPLE_SIZE = 30
PROMOTION_REVIEW_SAMPLE_SIZE = 100


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _bucket(value: float | None, boundaries: tuple[float, ...]) -> str:
    if value is None:
        return "UNAVAILABLE"
    for boundary in boundaries:
        if value < boundary:
            return f"<{boundary:g}"
    return f">={boundaries[-1]:g}"


def _quality_row(event: dict[str, Any], report_date: date) -> dict[str, Any] | None:
    outcome = event.get("estimated_option_outcome") or {}
    mfe = _number(outcome.get("estimated_option_mfe_pct"))
    mae = _number(outcome.get("estimated_option_mae_pct"))
    if mfe is None or mae is None:
        return None

    market_state = event.get("shadow_market_state") or {}
    metrics = market_state.get("metrics") or {}
    continuation = event.get("cq") or {}
    components = continuation.get("components") or {}
    lifecycle = continuation.get("trend_lifecycle") or {}
    trend_age = _number(lifecycle.get("trend_age_candles"))
    if trend_age is None:
        trend_age = _number((components.get("trend_age") or {}).get("age_candles"))

    return {
        "report_date": report_date,
        "entered": bool(event.get("entered")),
        "market_state": str((event.get("research") or {}).get("trend_state") or market_state.get("state") or "UNCLASSIFIED"),
        "trend_age": trend_age,
        "adx": _number(event.get("adx_14")),
        "directional_efficiency": _number(metrics.get("directional_efficiency_10")),
        "relative_volume": _number(metrics.get("relative_volume_20") or event.get("candle_relative_volume_20")),
        "ema_separation": _number(metrics.get("ema10_ema20_separation_in_avg_range") or event.get("ema10_ema20_separation")),
        "pullback_depth": _number((components.get("pullback_depth") or {}).get("depth_candles")),
        "extension_from_ema10": _number(metrics.get("extension_from_ema10_in_avg_range")),
        "estimated_mfe_pct": mfe,
        "estimated_mae_pct": mae,
    }


def _mean_confidence_interval(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    margin = 1.96 * math.sqrt(variance / len(values))
    return [round(mean - margin, 4), round(mean + margin, 4)]


def _research_stage(observations: int) -> str:
    if observations >= PROMOTION_REVIEW_SAMPLE_SIZE:
        return "promotion_review_requires_cross_regime_out_of_sample_validation"
    if observations >= DEEP_VALIDATION_SAMPLE_SIZE:
        return "eligible_for_deep_validation"
    if observations >= MINIMUM_SAMPLE_SIZE:
        return "candidate_for_validation"
    return "exploratory_insufficient_sample"


def _summarize(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    mfe = [row["estimated_mfe_pct"] for row in rows]
    mae = [row["estimated_mae_pct"] for row in rows]
    entered = sum(row["entered"] for row in rows)
    return {
        "cohort": label,
        "observations": len(rows),
        "entered": entered,
        "rejected": len(rows) - entered,
        "avg_estimated_option_mfe_pct": round(sum(mfe) / len(mfe), 4),
        "avg_estimated_option_mae_pct": round(sum(mae) / len(mae), 4),
        "estimated_option_mfe_pct_95ci": _mean_confidence_interval(mfe),
        "estimated_option_mae_pct_95ci": _mean_confidence_interval(mae),
        "research_status": _research_stage(len(rows)),
    }


def _group(rows: list[dict[str, Any]], label_for) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[label_for(row)].append(row)
    return [_summarize(members, label) for label, members in sorted(groups.items())]


def _feature_buckets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    definitions = {
        "trend_age_candles": ("trend_age", (3, 6, 9)),
        "adx_14": ("adx", (15, 20, 25, 30, 35)),
        "directional_efficiency_10": ("directional_efficiency", (0.35, 0.45, 0.60)),
        "relative_volume_20": ("relative_volume", (0.80, 1.00, 1.25)),
        "ema_separation_in_avg_range": ("ema_separation", (0.35, 0.50, 1.00)),
        "pullback_depth_candles": ("pullback_depth", (1, 3, 6)),
        "extension_from_ema10_in_avg_range": ("extension_from_ema10", (0.50, 1.00, 1.50)),
    }
    return {
        name: _group(rows, lambda row, key=key, bounds=bounds: _bucket(row[key], bounds))
        for name, (key, bounds) in definitions.items()
    }


def _combination_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _group(
        rows,
        lambda row: " | ".join((
            row["market_state"],
            f"efficiency {_bucket(row['directional_efficiency'], (0.35, 0.45, 0.60))}",
            f"relative_volume {_bucket(row['relative_volume'], (0.80, 1.00, 1.25))}",
            f"extension {_bucket(row['extension_from_ema10'], (0.50, 1.00, 1.50))}",
        )),
    )


def _market_state_adx_trend_age_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _group(
        rows,
        lambda row: " | ".join((
            row["market_state"],
            f"ADX {_bucket(row['adx'], (18, 25, 30, 35))}",
            f"trend_age {_bucket(row['trend_age'], (3, 6, 9))}",
        )),
    )


def _interaction_label(row: dict[str, Any]) -> str:
    return " | ".join((
        row["market_state"],
        f"ADX {_bucket(row['adx'], (18, 25, 30, 35))}",
        f"trend_age {_bucket(row['trend_age'], (3, 6, 9))}",
    ))


def _stability_rows(rows: list[dict[str, Any]], as_of: date) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_interaction_label(row)].append(row)

    cutoff = as_of - timedelta(days=29)
    stability = []
    for label, members in groups.items():
        all_time = _summarize(members, label)
        if all_time["observations"] < MINIMUM_SAMPLE_SIZE:
            continue
        rolling = [row for row in members if row["report_date"] >= cutoff]
        rolling_summary = _summarize(rolling, label) if rolling else None
        if not rolling_summary or rolling_summary["observations"] < MINIMUM_SAMPLE_SIZE:
            state = "insufficient_rolling_sample"
        elif (
            rolling_summary["avg_estimated_option_mfe_pct"] < all_time["avg_estimated_option_mfe_pct"]
            and rolling_summary["avg_estimated_option_mae_pct"] < all_time["avg_estimated_option_mae_pct"]
        ):
            state = "deteriorating"
        else:
            state = "stable_or_improving"
        stability.append({
            "cohort": label,
            "all_time": all_time,
            "rolling_30_day": rolling_summary,
            "stability_state": state,
        })
    return sorted(stability, key=lambda row: row["cohort"])


def build_trend_quality_report(reports_dir: Path = REPORTS_DIR, output_path: Path | None = None) -> Path:
    """Aggregate immutable daily reviews without changing live-trading behavior."""
    quality_rows: list[dict[str, Any]] = []
    source_reports = []
    for path in sorted(reports_dir.glob("daily_opportunity_review_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            report_date = date.fromisoformat(path.stem.removeprefix("daily_opportunity_review_"))
        except ValueError:
            continue
        source_reports.append(path.name)
        for event in payload.get("evaluated_setups") or []:
            row = _quality_row(event, report_date)
            if row is not None:
                quality_rows.append(row)

    combinations = _combination_rows(quality_rows)
    ranked_combinations = sorted(
        combinations,
        key=lambda row: (
            row["research_status"] != "candidate_for_validation",
            -row["avg_estimated_option_mfe_pct"],
            -row["avg_estimated_option_mae_pct"],
        ),
    )
    state_adx_age_rows = _market_state_adx_trend_age_rows(quality_rows)
    qualified_state_adx_age_rows = [
        row for row in state_adx_age_rows
        if row["observations"] >= MINIMUM_SAMPLE_SIZE
    ]
    as_of = max((row["report_date"] for row in quality_rows), default=datetime.now(EASTERN_TZ).date())
    output = {
        "generated_at": datetime.now(EASTERN_TZ).isoformat(),
        "research_only": True,
        "promotion_eligible": False,
        "minimum_sample_size": MINIMUM_SAMPLE_SIZE,
        "deep_validation_minimum_sample_size": DEEP_VALIDATION_SAMPLE_SIZE,
        "promotion_review_minimum_sample_size": PROMOTION_REVIEW_SAMPLE_SIZE,
        "promotion_policy": "Manual-only. A 100+ observation cohort requires multi-regime, statistical, and out-of-sample validation before live-rule promotion can be considered.",
        "outcome_note": "MFE and MAE are estimated option-return proxies from the daily opportunity review, not reconciled option P&L.",
        "realized_outcome_status": "unavailable: opportunity-to-trade linkage for actual option P&L, slippage, theta, and exit quality is not yet persisted",
        "source_reports": source_reports,
        "observations": len(quality_rows),
        "entered": sum(row["entered"] for row in quality_rows),
        "rejected": sum(not row["entered"] for row in quality_rows),
        "feature_buckets": _feature_buckets(quality_rows),
        "market_states": _group(quality_rows, lambda row: row["market_state"]),
        "quality_combinations": ranked_combinations,
        "top_candidate_combinations": [row for row in ranked_combinations if row["observations"] >= MINIMUM_SAMPLE_SIZE][:10],
        "market_state_adx_trend_age_interactions": qualified_state_adx_age_rows,
        "market_state_adx_trend_age_deferred_sparse_combinations": len(state_adx_age_rows) - len(qualified_state_adx_age_rows),
        "market_state_adx_trend_age_stability": _stability_rows(quality_rows, as_of),
    }
    destination = output_path or reports_dir / "trend_quality_report.json"
    destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the shadow-only trend quality report")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(build_trend_quality_report(args.reports_dir, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())