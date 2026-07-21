#!/usr/bin/env python3
"""Daily execution validation report for McLeod Cockpit."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "config" / "cockpit.env", override=True)
EASTERN_NOW = datetime.now().astimezone()
TODAY = EASTERN_NOW.date().isoformat()
BASE_URL = os.environ["COCKPIT_PUBLIC_URL"].rstrip("/")
REPORT_DIR = Path("data/reports/execution_validation")


def _get_json(path: str, params: Dict[str, str] | None = None) -> Dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    url = f"{BASE_URL}{path}{query}"
    with urlopen(url, timeout=15) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _build_checks(status: Dict[str, Any], execq: Dict[str, Any], trades: List[Dict[str, Any]], logs: List[str]) -> List[Tuple[str, bool, str]]:
    checks: List[Tuple[str, bool, str]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append((name, passed, detail))

    bot_running = bool(status.get("bot_running"))
    heartbeat_ok = bool(status.get("heartbeat_ok"))
    heartbeat_age_seconds = status.get("heartbeat_age_seconds")
    add(
        "Bot runtime alive",
        bot_running and heartbeat_ok,
        f"bot_running={bot_running} heartbeat_ok={heartbeat_ok} age_s={heartbeat_age_seconds}",
    )

    broker_recon = str(status.get("broker_reconciliation") or "")
    add(
        "Broker reconciliation status",
        broker_recon.upper() == "SUCCESS",
        f"broker_reconciliation={broker_recon or 'UNKNOWN'}",
    )

    attempt_count = int(execq.get("attempt_count") or 0)
    filled_count = int(execq.get("filled_count") or 0)
    fill_rate_pct = float(execq.get("fill_rate_pct") or 0.0)
    fallback_rate_pct = float(execq.get("fallback_rate_pct") or 0.0)

    if attempt_count > 0:
        add(
            "Entry fill rate",
            fill_rate_pct >= 90.0,
            f"fill_rate_pct={fill_rate_pct:.1f}% ({filled_count}/{attempt_count})",
        )
        add(
            "Market fallback usage",
            fallback_rate_pct <= 40.0,
            f"fallback_rate_pct={fallback_rate_pct:.1f}%",
        )
    else:
        add("Entry fill rate", True, "No entry attempts today (no sample)")
        add("Market fallback usage", True, "No fills today (no sample)")

    avg_slippage_bps = execq.get("avg_slippage_bps")
    if avg_slippage_bps is None:
        add("Average slippage", True, "No slippage sample today")
    else:
        slippage = float(avg_slippage_bps)
        add("Average slippage", slippage <= 25.0, f"avg_slippage_bps={slippage:.1f}")

    stop_like = {"STOP", "1% STOP", "2% STOP", "3% STOP", "4% STOP", "PROTECTIVE_STOP_SYNC_FAILED"}
    sync_fail_exits = 0
    for trade in trades:
        reason = str(trade.get("exit_reason") or "").upper()
        if reason == "PROTECTIVE_STOP_SYNC_FAILED":
            sync_fail_exits += 1

    pattern_map = {
        "protective_stop_sync_failed": "PROTECTIVE_STOP_SYNC_FAILED",
        "order_timeout": "ORDER TIMEOUT",
        "submission_failed": "SUBMISSION FAILED",
        "unprotected": "UNPROTECTED",
        "traceback": "Traceback",
    }

    log_counts: Dict[str, int] = {k: 0 for k in pattern_map}
    for line in logs:
        text = str(line)
        for key, needle in pattern_map.items():
            if needle.lower() in text.lower():
                log_counts[key] += 1

    add(
        "Protective-stop sync failures",
        sync_fail_exits == 0 and log_counts["protective_stop_sync_failed"] == 0,
        f"trade_exits={sync_fail_exits} log_hits={log_counts['protective_stop_sync_failed']}",
    )
    add(
        "Order timeout noise",
        log_counts["order_timeout"] <= 2,
        f"order_timeout_log_hits={log_counts['order_timeout']}",
    )
    add(
        "Unprotected position alerts",
        log_counts["unprotected"] == 0,
        f"unprotected_log_hits={log_counts['unprotected']}",
    )
    add(
        "Traceback errors",
        log_counts["traceback"] == 0,
        f"traceback_log_hits={log_counts['traceback']}",
    )

    return checks


def _markdown_report(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# Daily Execution Validation - {payload['date']}")
    lines.append("")
    lines.append(f"Generated at: {payload['generated_at']}")
    lines.append("")
    lines.append("## Scorecard")
    lines.append("")
    for item in payload["checks"]:
        lines.append(f"- {item['status']} | {item['name']}: {item['detail']}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Passed: {payload['passed_checks']}/{payload['total_checks']}")
    lines.append(f"- Failed: {payload['failed_checks']}")
    lines.append(f"- Trade count: {payload['trade_count']}")
    lines.append(f"- Execution attempts: {payload['attempt_count']}")
    lines.append(f"- Filled count: {payload['filled_count']}")
    lines.append(f"- Fill rate: {payload['fill_rate_pct']:.1f}%")
    if payload.get("avg_slippage_bps") is not None:
        lines.append(f"- Avg slippage (bps): {payload['avg_slippage_bps']:.1f}")
    else:
        lines.append("- Avg slippage (bps): n/a")
    lines.append("")
    lines.append("## Endpoints")
    lines.append("")
    lines.append(f"- Base URL: {payload['base_url']}")
    lines.append(f"- Status: /api/status")
    lines.append(f"- Execution quality: /api/execution-quality-summary?date={payload['date']}")
    lines.append(f"- Today trades: /api/today-trades")
    lines.append(f"- Logs: /api/logs?lines=500")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    status = _get_json("/api/status")
    execq = _get_json("/api/execution-quality-summary", {"date": TODAY})
    trades_payload = _get_json("/api/today-trades")
    logs_payload = _get_json("/api/logs", {"lines": "500"})

    trades = trades_payload.get("trades") or []
    logs = logs_payload.get("logs") or []

    checks_raw = _build_checks(status, execq, trades, logs)
    checks = [
        {
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
            "passed": passed,
        }
        for (name, passed, detail) in checks_raw
    ]

    total_checks = len(checks)
    failed_checks = sum(1 for item in checks if not item["passed"])
    passed_checks = total_checks - failed_checks

    payload: Dict[str, Any] = {
        "date": TODAY,
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_url": BASE_URL,
        "checks": checks,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "trade_count": len(trades),
        "attempt_count": int(execq.get("attempt_count") or 0),
        "filled_count": int(execq.get("filled_count") or 0),
        "fill_rate_pct": float(execq.get("fill_rate_pct") or 0.0),
        "avg_slippage_bps": (None if execq.get("avg_slippage_bps") is None else float(execq.get("avg_slippage_bps"))),
    }

    daily_json = REPORT_DIR / f"execution_validation_{TODAY}.json"
    daily_md = REPORT_DIR / f"execution_validation_{TODAY}.md"
    latest_json = REPORT_DIR / "latest_execution_validation.json"
    latest_md = REPORT_DIR / "latest_execution_validation.md"

    daily_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    daily_md.write_text(_markdown_report(payload), encoding="utf-8")
    latest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_md.write_text(_markdown_report(payload), encoding="utf-8")

    print(f"Validation complete: {passed_checks}/{total_checks} checks passed")
    print(f"Report: {daily_md}")

    # Return non-zero when checks fail to make scheduler logs obvious.
    return 0 if failed_checks == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
