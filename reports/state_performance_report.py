"""Read-only performance aggregation for shadow market-state observations."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")
REPORTS_DIR = Path("reports")


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _adx_bucket(value: Any) -> str:
    adx = _safe_float(value)
    if adx is None:
        return "UNAVAILABLE"
    if adx < 15:
        return "<15"
    if adx < 20:
        return "15-20"
    if adx < 25:
        return "20-25"
    if adx < 30:
        return "25-30"
    if adx < 35:
        return "30-35"
    return "35+"


def build_state_performance_report(reports_dir: Path = REPORTS_DIR) -> Path:
    """Aggregate enriched daily opportunity reviews by immutable shadow state."""
    events: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("daily_opportunity_review_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        events.extend(payload.get("evaluated_setups") or [])

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        research = event.get("research") or {}
        state = str(research.get("trend_state") or (event.get("shadow_market_state") or {}).get("state") or "UNCLASSIFIED")
        groups[state].append(event)

    adx_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        adx_groups[_adx_bucket(event.get("adx_14"))].append(event)

    rows = []
    for state, members in sorted(groups.items()):
        entered = [item for item in members if (item.get("research") or {}).get("current_engine_entered")]
        rejected = [item for item in members if not (item.get("research") or {}).get("current_engine_entered")]
        outcomes = [item.get("estimated_option_outcome") or {} for item in members]
        mfe = [value for value in (_safe_float(item.get("estimated_option_mfe_pct")) for item in outcomes) if value is not None]
        mae = [value for value in (_safe_float(item.get("estimated_option_mae_pct")) for item in outcomes) if value is not None]
        proxy_wins = sum(1 for value in mfe if value >= 4.0)
        rows.append({
            "market_state": state,
            "observations": len(members),
            "entered": len(entered),
            "rejected": len(rejected),
            "estimated_proxy_win_rate_pct": round((proxy_wins / len(mfe)) * 100.0, 2) if mfe else None,
            "avg_estimated_option_mfe_pct": round(sum(mfe) / len(mfe), 4) if mfe else None,
            "avg_estimated_option_mae_pct": round(sum(mae) / len(mae), 4) if mae else None,
            "actual_reconciled_pnl": None,
            "actual_reconciled_pnl_status": "unavailable: opportunity-to-economic-trade linkage is not yet persisted",
        })

    adx_bucket_order = ("<15", "15-20", "20-25", "25-30", "30-35", "35+", "UNAVAILABLE")
    adx_buckets = []
    for bucket in adx_bucket_order:
        members = adx_groups.get(bucket, [])
        entered = [item for item in members if (item.get("research") or {}).get("current_engine_entered")]
        adx_buckets.append({
            "adx_bucket": bucket,
            "observations": len(members),
            "entered": len(entered),
            "rejected": len(members) - len(entered),
            "reconciled_expectancy": None,
            "reconciled_expectancy_status": "unavailable: counts only until opportunities are linked to sufficient reconciled economic outcomes",
        })

    output = {
        "generated_at": datetime.now(EASTERN_TZ).isoformat(),
        "research_only": True,
        "promotion_eligible": False,
        "actual_pnl_note": "Actual P&L, profit factor, and drawdown remain unavailable until logged opportunities are linked to reconciled economic trades.",
        "states": rows,
        "adx_buckets": adx_buckets,
    }
    output_path = reports_dir / "state_performance_report.json"
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the read-only shadow market-state performance report")
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    args = parser.parse_args()
    print(build_state_performance_report(Path(args.reports_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())