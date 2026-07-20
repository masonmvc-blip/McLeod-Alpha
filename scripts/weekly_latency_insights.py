#!/usr/bin/env python3
"""Generate a weekly latency insights report from phase3 latency JSONL logs."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from engine.memory import get_memory

DEFAULT_INPUT_PATH = Path("data/reports/latency_cycle_history.jsonl")
DEFAULT_OUTPUT_DIR = Path("data/reports/latency_weekly")
DEFAULT_DECISION_INPUT_PATH = Path("data/reports/decision_audit_history.jsonl")


def _parse_iso_utc(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    if pct <= 0:
        return min(values)
    if pct >= 100:
        return max(values)
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    lower_v = ordered[lower]
    upper_v = ordered[upper]
    weight = rank - lower
    return lower_v + (upper_v - lower_v) * weight


def _load_events(input_path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in get_memory().read_report_text(input_path, encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
            except json.JSONDecodeError:
                continue

    return events


def _load_decision_events(input_path: Path) -> List[Dict[str, Any]]:
    return _load_events(input_path)


def _within_days(events: Iterable[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=max(1, days))
    out: List[Dict[str, Any]] = []

    for event in events:
        ts = _parse_iso_utc(str(event.get("ts_utc") or ""))
        if ts is None:
            continue
        if ts >= cutoff:
            out.append(event)

    return out


def _first_touch_outcome(direction: str, entry: float, stop: float, target: float, future_rows: List[Dict[str, Any]]) -> str:
    side = str(direction or "").upper()
    if side not in {"CALL", "PUT"}:
        return "unknown"
    for row in future_rows:
        high = _to_float(row.get("spy_high"))
        low = _to_float(row.get("spy_low"))
        if high is None or low is None:
            continue
        if side == "CALL":
            if low <= stop:
                return "stop_first"
            if high >= target:
                return "target_first"
        else:
            if high >= stop:
                return "stop_first"
            if low <= target:
                return "target_first"
    return "neither"


def _horizon_return_bps(direction: str, entry: float, future_close: float) -> Optional[float]:
    side = str(direction or "").upper()
    if entry <= 0 or future_close <= 0:
        return None
    if side == "CALL":
        ret = ((future_close - entry) / entry) * 10000.0
    elif side == "PUT":
        ret = ((entry - future_close) / entry) * 10000.0
    else:
        return None
    return ret


def _decision_backtest_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    eval_rows = [
        e for e in events
        if str(e.get("event_type") or "") == "entry_evaluation"
    ]
    qualified = [
        e for e in eval_rows
        if str(e.get("candidate_direction") or "").upper() in {"CALL", "PUT"}
        and _to_float(e.get("candidate_entry")) is not None
        and _to_float(e.get("candidate_stop")) is not None
        and _to_float(e.get("candidate_target")) is not None
    ]

    signal_qualified = len(qualified)
    signal_qualified_entered = sum(1 for e in qualified if bool(e.get("entry_opened")))
    signal_qualified_skipped = signal_qualified - signal_qualified_entered

    outcomes_30m = Counter()
    returns_5 = []
    returns_15 = []
    returns_30 = []

    by_candle = {}
    ordered = []
    for row in eval_rows:
        key = str(row.get("candle_time") or "")
        if not key:
            continue
        by_candle[key] = row
        ordered.append(row)

    ordered.sort(key=lambda r: str(r.get("candle_time") or ""))

    for idx, row in enumerate(ordered):
        direction = str(row.get("candidate_direction") or "").upper()
        entry = _to_float(row.get("candidate_entry"))
        stop = _to_float(row.get("candidate_stop"))
        target = _to_float(row.get("candidate_target"))
        if direction not in {"CALL", "PUT"} or entry is None or stop is None or target is None:
            continue

        future_5 = ordered[idx + 1: idx + 6]
        future_15 = ordered[idx + 1: idx + 16]
        future_30 = ordered[idx + 1: idx + 31]

        close_5 = _to_float(future_5[-1].get("spy_close")) if len(future_5) >= 5 else None
        close_15 = _to_float(future_15[-1].get("spy_close")) if len(future_15) >= 15 else None
        close_30 = _to_float(future_30[-1].get("spy_close")) if len(future_30) >= 30 else None

        ret5 = _horizon_return_bps(direction, entry, close_5) if close_5 is not None else None
        ret15 = _horizon_return_bps(direction, entry, close_15) if close_15 is not None else None
        ret30 = _horizon_return_bps(direction, entry, close_30) if close_30 is not None else None
        if ret5 is not None:
            returns_5.append(ret5)
        if ret15 is not None:
            returns_15.append(ret15)
        if ret30 is not None:
            returns_30.append(ret30)

        if len(future_30) >= 1:
            outcomes_30m[_first_touch_outcome(direction, entry, stop, target, future_30)] += 1

    return {
        "evaluation_rows": len(eval_rows),
        "signal_qualified_count": signal_qualified,
        "signal_qualified_entered_count": signal_qualified_entered,
        "signal_qualified_skipped_count": signal_qualified_skipped,
        "signal_enter_rate_pct": (signal_qualified_entered / signal_qualified * 100.0) if signal_qualified > 0 else 0.0,
        "horizon_return_bps": {
            "5m": _metric_stats([{"v": v} for v in returns_5], "v"),
            "15m": _metric_stats([{"v": v} for v in returns_15], "v"),
            "30m": _metric_stats([{"v": v} for v in returns_30], "v"),
        },
        "target_stop_first_touch_30m": dict(outcomes_30m),
    }


def _metric_stats(events: List[Dict[str, Any]], key: str) -> Dict[str, Optional[float]]:
    values = []
    for event in events:
        value = _to_float(event.get(key))
        if value is None:
            continue
        values.append(value)

    if not values:
        return {
            "count": 0,
            "avg": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "max": None,
        }

    return {
        "count": float(len(values)),
        "avg": sum(values) / len(values),
        "p50": _percentile(values, 50),
        "p90": _percentile(values, 90),
        "p95": _percentile(values, 95),
        "max": max(values),
    }


def _fmt_num(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _top_slowest(events: List[Dict[str, Any]], key: str, limit: int = 10) -> List[Dict[str, Any]]:
    enriched = []
    for event in events:
        value = _to_float(event.get(key))
        if value is None:
            continue
        enriched.append((value, event))

    enriched.sort(key=lambda item: item[0], reverse=True)
    out: List[Dict[str, Any]] = []
    for value, event in enriched[:limit]:
        out.append(
            {
                "ts_et": event.get("ts_et"),
                "decision": event.get("entry_decision_reason"),
                "opened": bool(event.get("entry_opened")),
                "filled_via": event.get("entry_filled_via"),
                "block_reason": event.get("entry_block_reason"),
                "value_ms": value,
            }
        )
    return out


def _build_summary(events: List[Dict[str, Any]], decision_events: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    total = len(events)
    attempts = [e for e in events if bool(e.get("entry_attempted"))]
    opened = [e for e in attempts if bool(e.get("entry_opened"))]

    fill_path_counter = Counter(str(e.get("entry_filled_via") or "none") for e in opened)
    decision_counter = Counter(str(e.get("entry_decision_reason") or "unknown") for e in events)
    block_counter = Counter(str(e.get("entry_block_reason") or "none") for e in attempts if e.get("entry_block_reason"))

    metrics = {
        "cycle_total_ms": _metric_stats(events, "cycle_total_ms"),
        "candles_fetch_ms": _metric_stats(events, "candles_fetch_ms"),
        "entry_eval_ms": _metric_stats(events, "entry_eval_ms"),
        "open_trade_ms": _metric_stats(attempts, "open_trade_ms"),
        "entry_submit_order_ms": _metric_stats(attempts, "entry_submit_order_ms"),
        "entry_wait_fill_ms": _metric_stats(attempts, "entry_wait_fill_ms"),
        "entry_market_fallback_wait_ms": _metric_stats(attempts, "entry_market_fallback_wait_ms"),
        "entry_protective_stop_ms": _metric_stats(attempts, "entry_protective_stop_ms"),
        "entry_persist_ms": _metric_stats(attempts, "entry_persist_ms"),
    }

    attempt_count = len(attempts)
    open_count = len(opened)
    open_rate = (open_count / attempt_count) * 100.0 if attempt_count > 0 else 0.0

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "event_count": total,
        "entry_attempt_count": attempt_count,
        "entry_open_count": open_count,
        "entry_open_rate_pct": open_rate,
        "fill_path": dict(fill_path_counter),
        "decision_reason": dict(decision_counter),
        "block_reason": dict(block_counter),
        "metrics": metrics,
        "top_slowest_open_trade": _top_slowest(attempts, "open_trade_ms", limit=12),
        "top_slowest_fill_wait": _top_slowest(attempts, "entry_wait_fill_ms", limit=12),
        "top_slowest_submit": _top_slowest(attempts, "entry_submit_order_ms", limit=12),
        "decision_backtest": _decision_backtest_summary(decision_events),
    }


def _md_metric_table(summary: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    lines.append("| Metric | Count | Avg ms | P50 ms | P90 ms | P95 ms | Max ms |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")

    labels = [
        ("cycle_total_ms", "Cycle Total"),
        ("candles_fetch_ms", "Candles Fetch"),
        ("entry_eval_ms", "Entry Eval"),
        ("open_trade_ms", "Open Trade Total"),
        ("entry_submit_order_ms", "Submit Order"),
        ("entry_wait_fill_ms", "Wait Fill"),
        ("entry_market_fallback_wait_ms", "Fallback Wait Fill"),
        ("entry_protective_stop_ms", "Protective Stop Submit"),
        ("entry_persist_ms", "Persist Position"),
    ]

    for key, label in labels:
        metric = summary["metrics"][key]
        count = int(metric["count"]) if metric["count"] else 0
        lines.append(
            "| {label} | {count} | {avg} | {p50} | {p90} | {p95} | {maxv} |".format(
                label=label,
                count=count,
                avg=_fmt_num(metric["avg"]),
                p50=_fmt_num(metric["p50"]),
                p90=_fmt_num(metric["p90"]),
                p95=_fmt_num(metric["p95"]),
                maxv=_fmt_num(metric["max"]),
            )
        )

    return lines


def _md_counter_section(title: str, payload: Dict[str, Any], limit: int = 12) -> List[str]:
    lines: List[str] = [f"## {title}", ""]
    items = sorted(payload.items(), key=lambda item: item[1], reverse=True)
    if not items:
        lines.append("- none")
        lines.append("")
        return lines

    for name, count in items[:limit]:
        lines.append(f"- {name}: {count}")
    lines.append("")
    return lines


def _md_top_events(title: str, events: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = [f"## {title}", ""]
    if not events:
        lines.append("- none")
        lines.append("")
        return lines

    for event in events:
        lines.append(
            "- {ts} | {value:.2f} ms | decision={decision} opened={opened} filled_via={via} block={block}".format(
                ts=event.get("ts_et") or "unknown",
                value=float(event.get("value_ms") or 0.0),
                decision=event.get("decision") or "unknown",
                opened=event.get("opened"),
                via=event.get("filled_via") or "none",
                block=event.get("block_reason") or "none",
            )
        )
    lines.append("")
    return lines


def _write_outputs(summary: Dict[str, Any], output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = output_dir / f"weekly_latency_insights_{stamp}.json"
    md_path = output_dir / f"weekly_latency_insights_{stamp}.md"
    latest_json = output_dir / "weekly_latency_insights_latest.json"
    latest_md = output_dir / "weekly_latency_insights_latest.md"

    json_blob = json.dumps(summary, indent=2)

    md_lines: List[str] = []
    md_lines.append("# Weekly Latency Insights")
    md_lines.append("")
    md_lines.append(f"Generated UTC: {summary['generated_at_utc']}")
    md_lines.append(f"Window: last {summary['window_days']} days")
    md_lines.append("")
    md_lines.append("## Coverage")
    md_lines.append("")
    md_lines.append(f"- Events: {summary['event_count']}")
    md_lines.append(f"- Entry attempts: {summary['entry_attempt_count']}")
    md_lines.append(f"- Entries opened: {summary['entry_open_count']}")
    md_lines.append(f"- Open rate: {summary['entry_open_rate_pct']:.2f}%")
    md_lines.append("")
    md_lines.append("## Timing Summary")
    md_lines.append("")
    md_lines.extend(_md_metric_table(summary))
    md_lines.append("")

    md_lines.extend(_md_counter_section("Fill Path", summary.get("fill_path", {})))
    md_lines.extend(_md_counter_section("Decision Reasons", summary.get("decision_reason", {})))
    md_lines.extend(_md_counter_section("Entry Block Reasons", summary.get("block_reason", {})))
    md_lines.extend(_md_top_events("Slowest Open Trade Events", summary.get("top_slowest_open_trade", [])))
    md_lines.extend(_md_top_events("Slowest Fill Wait Events", summary.get("top_slowest_fill_wait", [])))
    md_lines.extend(_md_top_events("Slowest Submit Events", summary.get("top_slowest_submit", [])))

    decision_backtest = summary.get("decision_backtest") or {}
    md_lines.append("## Decision Backtest Snapshot")
    md_lines.append("")
    md_lines.append(f"- Evaluation rows: {decision_backtest.get('evaluation_rows', 0)}")
    md_lines.append(f"- Signal-qualified setups: {decision_backtest.get('signal_qualified_count', 0)}")
    md_lines.append(f"- Signal-qualified entered: {decision_backtest.get('signal_qualified_entered_count', 0)}")
    md_lines.append(f"- Signal-qualified skipped: {decision_backtest.get('signal_qualified_skipped_count', 0)}")
    md_lines.append(f"- Signal enter rate: {float(decision_backtest.get('signal_enter_rate_pct') or 0.0):.2f}%")
    md_lines.append("")
    horizon = decision_backtest.get("horizon_return_bps") or {}
    md_lines.append("| Horizon | Count | Avg bps | P50 bps | P90 bps | P95 bps | Max bps |")
    md_lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for key in ("5m", "15m", "30m"):
        metric = horizon.get(key) or {}
        count = int(metric.get("count") or 0)
        md_lines.append(
            "| {h} | {c} | {avg} | {p50} | {p90} | {p95} | {mx} |".format(
                h=key,
                c=count,
                avg=_fmt_num(metric.get("avg")),
                p50=_fmt_num(metric.get("p50")),
                p90=_fmt_num(metric.get("p90")),
                p95=_fmt_num(metric.get("p95")),
                mx=_fmt_num(metric.get("max")),
            )
        )
    md_lines.append("")
    md_lines.extend(_md_counter_section("30m Target/Stop First-Touch", decision_backtest.get("target_stop_first_touch_30m", {}), limit=8))

    md_blob = "\n".join(md_lines).rstrip() + "\n"

    memory = get_memory()
    correlation_id = f"weekly-latency-insights:{summary.get('generated_at') or days}"
    memory.write_report_text(json_path, json_blob, "weekly_latency_insights", source="weekly_latency_insights", correlation_id=correlation_id)
    memory.write_report_text(latest_json, json_blob, "weekly_latency_insights", source="weekly_latency_insights", correlation_id=correlation_id)
    memory.write_report_text(md_path, md_blob, "weekly_latency_insights", source="weekly_latency_insights", correlation_id=correlation_id)
    memory.write_report_text(latest_md, md_blob, "weekly_latency_insights", source="weekly_latency_insights", correlation_id=correlation_id)

    return {
        "json": json_path,
        "md": md_path,
        "latest_json": latest_json,
        "latest_md": latest_md,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly latency insights from JSONL logs")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="Path to latency JSONL")
    parser.add_argument("--decision-input", type=Path, default=DEFAULT_DECISION_INPUT_PATH, help="Path to decision audit JSONL")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for output reports")
    parser.add_argument("--days", type=int, default=7, help="How many trailing days to include")
    args = parser.parse_args()

    events = _load_events(args.input)
    window = _within_days(events, args.days)
    decision_events = _within_days(_load_decision_events(args.decision_input), args.days)

    if not window:
        print(f"No latency events found in the last {args.days} days from {args.input}")
        return 1

    summary = _build_summary(window, decision_events, args.days)
    outputs = _write_outputs(summary, args.output_dir)

    print(f"Latency insights generated from {len(window)} events")
    print(f"Markdown report: {outputs['md']}")
    print(f"Latest markdown: {outputs['latest_md']}")
    print(f"JSON report: {outputs['json']}")
    print(f"Latest json: {outputs['latest_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
