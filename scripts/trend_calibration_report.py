#!/usr/bin/env python3
import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DB_PATH = Path("data/mcleod_alpha.db")
OUT_PATH = Path("data/reports/trend_calibration_report.md")


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_payload(raw):
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _metric_bin(value):
    if value is None:
        return "unknown"
    if value < 2.0:
        return "[0.0,2.0)"
    if value < 3.0:
        return "[2.0,3.0)"
    if value < 4.0:
        return "[3.0,4.0)"
    return "[4.0,5.0]"


def _summarize(rows, key_fn):
    buckets = defaultdict(list)
    for row in rows:
        buckets[key_fn(row)].append(row)

    out = []
    for key, items in sorted(buckets.items(), key=lambda x: str(x[0])):
        pnl_vals = [r["option_pnl_pct"] for r in items if r.get("option_pnl_pct") is not None]
        wins = [r for r in items if (r.get("option_pnl_pct") is not None and r["option_pnl_pct"] > 0)]
        avg_pnl = (sum(pnl_vals) / len(pnl_vals)) if pnl_vals else None
        win_rate = (len(wins) / len(pnl_vals) * 100.0) if pnl_vals else None
        out.append(
            {
                "bucket": key,
                "count": len(items),
                "with_pnl": len(pnl_vals),
                "win_rate": win_rate,
                "avg_pnl": avg_pnl,
            }
        )
    return out


def _table_md(summary, title):
    lines = [f"### {title}", "", "| Bucket | Trades | Trades with PnL% | Win Rate | Avg PnL% |", "|---|---:|---:|---:|---:|"]
    for row in summary:
        wr = "n/a" if row["win_rate"] is None else f"{row['win_rate']:.1f}%"
        avg = "n/a" if row["avg_pnl"] is None else f"{row['avg_pnl']:.2f}%"
        lines.append(f"| {row['bucket']} | {row['count']} | {row['with_pnl']} | {wr} | {avg} |")
    lines.append("")
    return "\n".join(lines)


def build_report(lookback, db_path, out_path):
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    cur.execute(
        """
        SELECT
            entry_time,
            exit_time,
            direction,
            option_pnl_pct,
            feature_payload
        FROM trade_log
        WHERE exit_time IS NOT NULL AND TRIM(exit_time) <> ''
        ORDER BY datetime(exit_time) DESC
        LIMIT ?
        """,
        (lookback,),
    )
    raw_rows = cur.fetchall()
    con.close()

    rows = []
    for entry_time, exit_time, direction, option_pnl_pct, feature_payload in raw_rows:
        payload = _parse_payload(feature_payload)
        trend_stage = payload.get("trend_stage")
        if isinstance(trend_stage, dict):
            trend_stage_val = _safe_int(trend_stage.get("stage"))
        else:
            trend_stage_val = _safe_int(trend_stage)

        row = {
            "entry_time": entry_time,
            "exit_time": exit_time,
            "direction": direction or "UNKNOWN",
            "option_pnl_pct": _safe_float(option_pnl_pct),
            "trend_stage": trend_stage_val,
            "continuation_quality_score": _safe_float(payload.get("continuation_quality_score")),
            "confidence_score": _safe_float(payload.get("confidence_score")),
            "trend_determinator_score": _safe_float(payload.get("trend_determinator_score")),
            "trend_determinator_label": str(payload.get("trend_determinator_label") or "UNKNOWN"),
        }
        rows.append(row)

    with_pnl = [r for r in rows if r.get("option_pnl_pct") is not None]
    overall_avg = (sum(r["option_pnl_pct"] for r in with_pnl) / len(with_pnl)) if with_pnl else None
    overall_wr = (sum(1 for r in with_pnl if r["option_pnl_pct"] > 0) / len(with_pnl) * 100.0) if with_pnl else None

    by_stage = _summarize(rows, lambda r: f"Stage {r['trend_stage']}" if r.get("trend_stage") is not None else "Stage unknown")
    by_cq = _summarize(rows, lambda r: _metric_bin(r.get("continuation_quality_score")))
    by_conf = _summarize(rows, lambda r: _metric_bin(r.get("confidence_score")))
    by_td = _summarize(rows, lambda r: _metric_bin(r.get("trend_determinator_score")))
    by_side = _summarize(rows, lambda r: r.get("direction") or "UNKNOWN")

    cq_pass = [r for r in with_pnl if (r.get("continuation_quality_score") is not None and r["continuation_quality_score"] >= 3.0)]
    cq_pass_wr = (sum(1 for r in cq_pass if r["option_pnl_pct"] > 0) / len(cq_pass) * 100.0) if cq_pass else None
    cq_pass_avg = (sum(r["option_pnl_pct"] for r in cq_pass) / len(cq_pass)) if cq_pass else None

    td_pass = [r for r in with_pnl if (r.get("trend_determinator_score") is not None and r["trend_determinator_score"] >= 3.0)]
    td_pass_wr = (sum(1 for r in td_pass if r["option_pnl_pct"] > 0) / len(td_pass) * 100.0) if td_pass else None
    td_pass_avg = (sum(r["option_pnl_pct"] for r in td_pass) / len(td_pass)) if td_pass else None

    now = datetime.now().isoformat(timespec="seconds")
    lines = []
    lines.append("# Quick Trend Calibration Report")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Lookback trades: {len(rows)}")
    lines.append(f"Trades with option_pnl_pct: {len(with_pnl)}")
    lines.append("")

    if overall_avg is None:
        lines.append("No closed trades with option_pnl_pct found. Report is informational only.")
    else:
        lines.append(f"Overall win rate: {overall_wr:.1f}%")
        lines.append(f"Overall avg option PnL: {overall_avg:.2f}%")
    lines.append("")

    lines.append(_table_md(by_side, "By Direction"))
    lines.append(_table_md(by_stage, "By Trend Stage"))
    lines.append(_table_md(by_cq, "By Continuation Quality Score"))
    lines.append(_table_md(by_conf, "By Confidence Score"))
    lines.append(_table_md(by_td, "By Trend Determinator Score"))

    lines.append("## Gate Benchmarks")
    lines.append("")
    cq_wr_text = "n/a" if cq_pass_wr is None else f"{cq_pass_wr:.1f}%"
    cq_avg_text = "n/a" if cq_pass_avg is None else f"{cq_pass_avg:.2f}%"
    td_wr_text = "n/a" if td_pass_wr is None else f"{td_pass_wr:.1f}%"
    td_avg_text = "n/a" if td_pass_avg is None else f"{td_pass_avg:.2f}%"
    lines.append(f"- CQ >= 3.0: trades={len(cq_pass)} win_rate={cq_wr_text} avg_pnl={cq_avg_text}")
    lines.append(f"- Trend Determinator >= 3.0: trades={len(td_pass)} win_rate={td_wr_text} avg_pnl={td_avg_text}")
    lines.append("")

    lines.append("## Suggested Next Tuning Pass")
    lines.append("")
    lines.append("- If Stage 4/5 underperform Stage 1-3, tighten entries in mature stages by raising CQ minimum by 0.2-0.4.")
    lines.append("- If [3.0,4.0) CQ bucket is negative expectancy, lift CQ gate to 3.2 for that side/time window.")
    lines.append("- If low confidence buckets are consistently negative, raise confidence minimum in weak regimes.")
    lines.append("- Re-run this report weekly and compare drift before changing core weights.")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Generate quick trend calibration report from trade_log")
    parser.add_argument("--lookback", type=int, default=200, help="Number of most recent closed trades to analyze")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to SQLite database")
    parser.add_argument("--out", type=Path, default=OUT_PATH, help="Path to output markdown report")
    args = parser.parse_args()

    report_path = build_report(args.lookback, args.db, args.out)
    print(f"Wrote report: {report_path}")


if __name__ == "__main__":
    main()