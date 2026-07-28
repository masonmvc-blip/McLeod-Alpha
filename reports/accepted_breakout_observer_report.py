"""Offline report for the observe-only accepted-breakout experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from execution.accepted_breakout_observer import MINIMUM_COMPLETED_TRADES_PER_COHORT


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    pnl = [float(record["after_cost_pnl_dollars"]) for record in records]
    running, peak, maximum_drawdown = 0.0, 0.0, 0.0
    for value in pnl:
        running += value
        peak = max(peak, running)
        maximum_drawdown = min(maximum_drawdown, running - peak)
    return {
        "completed_trades": len(pnl),
        "after_cost_total_pnl_dollars": round(sum(pnl), 2),
        "after_cost_expectancy_dollars": round(sum(pnl) / len(pnl), 2) if pnl else None,
        "maximum_drawdown_dollars": round(maximum_drawdown, 2),
    }


def _completed_records(paths: list[Path]) -> tuple[list[dict[str, Any]], int]:
    records, excluded = [], 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event_type") != "option_trade_closed" or event.get("accepted_breakout_admit") is None:
                continue
            entry = _number(event.get("broker_entry_fill_price") or event.get("option_entry"))
            exit_price = _number(event.get("executable_exit_price"))
            quantity = _number(event.get("quantity"))
            fees = _number(event.get("broker_fees_dollars"))
            if None in (entry, exit_price, quantity, fees):
                excluded += 1
                continue
            event["after_cost_pnl_dollars"] = (exit_price - entry) * quantity * 100.0 - fees
            records.append(event)
    return sorted(records, key=lambda item: item.get("recorded_at", "")), excluded


def build_report(paths: list[Path], *, minimum_per_cohort: int = MINIMUM_COMPLETED_TRADES_PER_COHORT) -> dict[str, Any]:
    records, excluded = _completed_records(paths)
    retained = [record for record in records if record["accepted_breakout_admit"]]
    rejected = [record for record in records if not record["accepted_breakout_admit"]]
    retained_metrics, rejected_metrics = _metrics(retained), _metrics(rejected)
    enough = min(retained_metrics["completed_trades"], rejected_metrics["completed_trades"]) >= minimum_per_cohort
    rejected_worse = (
        enough
        and rejected_metrics["after_cost_expectancy_dollars"] < retained_metrics["after_cost_expectancy_dollars"]
        and rejected_metrics["maximum_drawdown_dollars"] <= retained_metrics["maximum_drawdown_dollars"]
    )
    return {
        "experiment": "accepted_breakout_observe_only",
        "status": "ready_for_manual_review" if rejected_worse else "insufficient_or_not_consistent",
        "automatic_live_deployment": False,
        "minimum_completed_trades_per_cohort": minimum_per_cohort,
        "excluded_missing_fill_or_fee_facts": excluded,
        "retained": retained_metrics,
        "rejected": rejected_metrics,
        "interpretation": "Consider deployment only after manual chronological out-of-sample review confirms rejected trades consistently underperform. This report never changes live orders.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Report accepted-breakout observe-only cohorts")
    parser.add_argument("--telemetry-dir", default="data/reports/option_quote_telemetry")
    parser.add_argument("--output", default="reports/accepted_breakout_observer_report.json")
    args = parser.parse_args()
    report = build_report(sorted(Path(args.telemetry_dir).glob("option_management_cycles_*.jsonl")))
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())