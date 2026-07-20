#!/usr/bin/env python3
"""Health check for Morning CIO pipeline runtime and output quality."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parent.parent
RUN_LOG = ROOT / "logs" / "morning_cio_email.jsonl"
LATEST_JSON = ROOT / "data" / "reports" / "morning_cio_email" / "latest_morning_cio_report.json"


def _latest_send_event() -> Dict[str, Any]:
    if not RUN_LOG.exists():
        return {}
    latest: Dict[str, Any] = {}
    for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("event") in {"send_succeeded", "send_failed"}:
            latest = row
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Morning CIO pipeline health.")
    parser.add_argument("--max-age-hours", type=int, default=26)
    parser.add_argument("--min-data-quality", type=int, default=0)
    parser.add_argument("--require-smtp", action="store_true")
    parser.add_argument("--require-approved-transport", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    issues = []

    send_event = _latest_send_event()
    if not send_event:
        issues.append("no_send_event")
    else:
        ts_text = str(send_event.get("logged_at", "")).strip()
        try:
            ts = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                age_hours = (datetime.now() - ts).total_seconds() / 3600
            else:
                age_hours = (datetime.now(ts.tzinfo) - ts).total_seconds() / 3600
            if age_hours > args.max_age_hours:
                issues.append("send_event_stale")
        except Exception:
            issues.append("send_event_timestamp_invalid")

        if args.require_smtp and send_event.get("transport") != "smtp":
            issues.append("non_smtp_transport")
        if args.require_approved_transport and send_event.get("transport") not in {"smtp", "outlook", "outlook_fallback"}:
            issues.append("unapproved_transport")

    report_payload: Dict[str, Any] = {}
    if LATEST_JSON.exists():
        try:
            report_payload = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
        except Exception:
            issues.append("latest_json_unreadable")
    else:
        issues.append("latest_json_missing")

    if report_payload:
        if bool(report_payload.get("stale")):
            issues.append("report_stale")
        dq = int(report_payload.get("data_quality_score", 0) or 0)
        if dq < args.min_data_quality:
            issues.append("data_quality_below_threshold")

    if not args.quiet:
        print("Morning CIO Health")
        print(f"run_log: {RUN_LOG}")
        print(f"latest_json: {LATEST_JSON}")
        print(f"latest_transport: {send_event.get('transport', 'n/a') if send_event else 'n/a'}")
        print(f"latest_status: {send_event.get('status', 'n/a') if send_event else 'n/a'}")
        print(f"latest_subject: {send_event.get('subject', 'n/a') if send_event else 'n/a'}")
        print(f"issues: {','.join(issues) if issues else 'none'}")

    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
