#!/usr/bin/env python3
"""Generate and email daily latency insights summary."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEEKLY_SCRIPT = PROJECT_ROOT / "scripts" / "weekly_latency_insights.py"
REPORT_DIR = PROJECT_ROOT / "data" / "reports" / "latency_weekly"
LATEST_JSON = REPORT_DIR / "weekly_latency_insights_latest.json"
LATEST_MD = REPORT_DIR / "weekly_latency_insights_latest.md"
RUN_LOG = PROJECT_ROOT / "logs" / "daily_latency_email.jsonl"

SMTP_TIMEOUT_SECONDS = 20
SMTP_MAX_ATTEMPTS = 3
SMTP_BACKOFF_SECONDS = 2


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _append_log(payload: Dict[str, Any]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = dict(payload)
    record.setdefault("logged_at", datetime.now().isoformat())
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _ensure_email_config() -> Tuple[bool, Sequence[str], Dict[str, str]]:
    required = ["EMAIL_ADDRESS", "EMAIL_APP_PASSWORD", "EMAIL_TO"]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    cfg = {
        "address": os.getenv("EMAIL_ADDRESS", "").strip(),
        "password": os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip(),
        "to": os.getenv("EMAIL_TO", "").strip(),
        "from_name": os.getenv("EMAIL_FROM_NAME", "McLeod Alpha").strip() or "McLeod Alpha",
    }
    return not missing, missing, cfg


def _run_latency_report(days: int) -> None:
    cmd = [sys.executable, str(WEEKLY_SCRIPT), "--days", str(max(1, days))]
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "latency report generation failed: "
            f"rc={result.returncode} stdout={result.stdout.strip()} stderr={result.stderr.strip()}"
        )


def _load_latest_summary() -> Dict[str, Any]:
    if not LATEST_JSON.exists():
        raise FileNotFoundError(f"Missing latency summary JSON: {LATEST_JSON}")
    return json.loads(LATEST_JSON.read_text(encoding="utf-8"))


def _fmt_ms(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f} ms"


def _fmt_bps(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f} bps"


def _metric(summary: Dict[str, Any], key: str, field: str) -> Optional[float]:
    metrics = summary.get("metrics") or {}
    item = metrics.get(key) or {}
    value = item.get(field)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top_bottlenecks(summary: Dict[str, Any], limit: int = 3) -> Sequence[Dict[str, Any]]:
    catalog = [
        (
            "open_trade_ms",
            "Open Trade Total",
            "Use stage metrics below to isolate the largest sub-step and tighten that path first.",
        ),
        (
            "entry_wait_fill_ms",
            "Wait Fill",
            "Broker fill wait is dominant; consider even more aggressive entry pricing or fallback timing.",
        ),
        (
            "entry_submit_order_ms",
            "Submit Order",
            "Submission time is elevated; inspect broker/API responsiveness and order payload readiness.",
        ),
        (
            "entry_protective_stop_ms",
            "Protective Stop Submit",
            "Stop placement is slow; monitor broker stop-order acknowledgements and retry behavior.",
        ),
        (
            "entry_market_fallback_wait_ms",
            "Fallback Wait Fill",
            "Fallback fills are slow; verify market-fallback timeout and post-fallback fill behavior.",
        ),
        (
            "candles_fetch_ms",
            "Candles Fetch",
            "Data retrieval is expensive; prioritize direct quote-heartbeat continuity over repeated REST pulls.",
        ),
        (
            "entry_eval_ms",
            "Entry Eval",
            "Decision path is slower than expected; profile indicators and option-selection overhead.",
        ),
        (
            "entry_persist_ms",
            "Persist Position",
            "Persistence overhead detected; verify disk I/O and serialization path.",
        ),
    ]

    ranked = []
    for key, label, action in catalog:
        p95 = _metric(summary, key, "p95")
        if p95 is None:
            continue
        ranked.append(
            {
                "key": key,
                "label": label,
                "p95_ms": float(p95),
                "avg_ms": _metric(summary, key, "avg"),
                "action": action,
            }
        )

    ranked.sort(key=lambda item: item.get("p95_ms") or 0.0, reverse=True)
    return ranked[: max(1, int(limit or 3))]


def _text_report(summary: Dict[str, Any]) -> str:
    open_rate = float(summary.get("entry_open_rate_pct") or 0.0)
    events = int(summary.get("event_count") or 0)
    attempts = int(summary.get("entry_attempt_count") or 0)
    opened = int(summary.get("entry_open_count") or 0)

    lines = []
    lines.append("Daily Latency Insights")
    lines.append("")
    lines.append(f"Generated UTC: {summary.get('generated_at_utc')}")
    lines.append(f"Window: last {summary.get('window_days')} days")
    lines.append("")
    lines.append("Coverage")
    lines.append(f"- events: {events}")
    lines.append(f"- entry attempts: {attempts}")
    lines.append(f"- entries opened: {opened}")
    lines.append(f"- open rate: {open_rate:.2f}%")

    backtest = summary.get("decision_backtest") or {}
    lines.append(f"- signal-qualified setups: {int(backtest.get('signal_qualified_count') or 0)}")
    lines.append(f"- signal-qualified entered: {int(backtest.get('signal_qualified_entered_count') or 0)}")
    lines.append(f"- signal-qualified skipped: {int(backtest.get('signal_qualified_skipped_count') or 0)}")
    lines.append(f"- signal enter rate: {float(backtest.get('signal_enter_rate_pct') or 0.0):.2f}%")
    lines.append("")
    lines.append("Primary Timing (P95)")
    lines.append(f"- open trade total: {_fmt_ms(_metric(summary, 'open_trade_ms', 'p95'))}")
    lines.append(f"- submit order: {_fmt_ms(_metric(summary, 'entry_submit_order_ms', 'p95'))}")
    lines.append(f"- wait fill: {_fmt_ms(_metric(summary, 'entry_wait_fill_ms', 'p95'))}")
    lines.append(f"- protective stop submit: {_fmt_ms(_metric(summary, 'entry_protective_stop_ms', 'p95'))}")
    lines.append("")

    bottlenecks = _top_bottlenecks(summary, limit=3)
    lines.append("Top 3 Bottlenecks and Actions")
    if bottlenecks:
        for idx, item in enumerate(bottlenecks, start=1):
            lines.append(
                "- {idx}. {label}: p95={p95} avg={avg} | action: {action}".format(
                    idx=idx,
                    label=item.get("label") or "unknown",
                    p95=_fmt_ms(item.get("p95_ms")),
                    avg=_fmt_ms(item.get("avg_ms")),
                    action=item.get("action") or "Review stage timing.",
                )
            )
    else:
        lines.append("- Not enough data yet to rank bottlenecks.")
    lines.append("")

    fill_path = summary.get("fill_path") or {}
    if fill_path:
        lines.append("Fill Path")
        for name, count in sorted(fill_path.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- {name}: {count}")
        lines.append("")

    slowest = summary.get("top_slowest_open_trade") or []
    if slowest:
        lines.append("Slowest Open-Trade Events")
        for row in slowest[:5]:
            lines.append(
                "- {ts} | {ms:.2f} ms | decision={decision} opened={opened} via={via} block={block}".format(
                    ts=row.get("ts_et") or "unknown",
                    ms=float(row.get("value_ms") or 0.0),
                    decision=row.get("decision") or "unknown",
                    opened=bool(row.get("opened")),
                    via=row.get("filled_via") or "none",
                    block=row.get("block_reason") or "none",
                )
            )
        lines.append("")

    horizon = backtest.get("horizon_return_bps") or {}
    lines.append("Hypothetical Forward Returns (bps)")
    for key in ("5m", "15m", "30m"):
        metric = horizon.get(key) or {}
        lines.append(
            f"- {key}: avg={_fmt_bps(metric.get('avg'))} p95={_fmt_bps(metric.get('p95'))} samples={int(metric.get('count') or 0)}"
        )
    lines.append("")

    touch = backtest.get("target_stop_first_touch_30m") or {}
    if touch:
        lines.append("30m Target/Stop First-Touch")
        for name, count in sorted(touch.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- {name}: {count}")
        lines.append("")

    lines.append(f"Detailed markdown report: {LATEST_MD}")
    return "\n".join(lines).rstrip() + "\n"


def _html_report(summary: Dict[str, Any], text_body: str) -> str:
    p95_open = _fmt_ms(_metric(summary, "open_trade_ms", "p95"))
    p95_submit = _fmt_ms(_metric(summary, "entry_submit_order_ms", "p95"))
    p95_fill = _fmt_ms(_metric(summary, "entry_wait_fill_ms", "p95"))
    p95_stop = _fmt_ms(_metric(summary, "entry_protective_stop_ms", "p95"))

    html_lines = []
    html_lines.append("<!DOCTYPE html><html><head><meta charset='utf-8'><style>")
    html_lines.append("body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;line-height:1.45;color:#0f172a}")
    html_lines.append(".card{border:1px solid #dbe4f0;border-radius:12px;padding:12px 14px;margin:8px 0;background:#f8fbff}")
    html_lines.append(".k{color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.06em}")
    html_lines.append(".v{font-size:20px;font-weight:700}")
    html_lines.append("pre{white-space:pre-wrap;border:1px solid #e2e8f0;border-radius:8px;padding:10px;background:#f8fafc}")
    html_lines.append("</style></head><body>")
    html_lines.append("<h2>Daily Latency Insights</h2>")
    html_lines.append(f"<p><strong>Generated UTC:</strong> {escape(str(summary.get('generated_at_utc')))}</p>")
    html_lines.append(f"<p><strong>Window:</strong> last {escape(str(summary.get('window_days')))} days</p>")
    html_lines.append(f"<div class='card'><div class='k'>P95 Open Trade</div><div class='v'>{escape(p95_open)}</div></div>")
    html_lines.append(f"<div class='card'><div class='k'>P95 Submit Order</div><div class='v'>{escape(p95_submit)}</div></div>")
    html_lines.append(f"<div class='card'><div class='k'>P95 Wait Fill</div><div class='v'>{escape(p95_fill)}</div></div>")
    html_lines.append(f"<div class='card'><div class='k'>P95 Protective Stop</div><div class='v'>{escape(p95_stop)}</div></div>")
    html_lines.append("<h3>Top 3 Bottlenecks and Actions</h3>")
    bottlenecks = _top_bottlenecks(summary, limit=3)
    if bottlenecks:
        html_lines.append("<ol>")
        for item in bottlenecks:
            html_lines.append(
                "<li><strong>{label}</strong>: p95={p95}, avg={avg}<br><span>{action}</span></li>".format(
                    label=escape(str(item.get("label") or "unknown")),
                    p95=escape(_fmt_ms(item.get("p95_ms"))),
                    avg=escape(_fmt_ms(item.get("avg_ms"))),
                    action=escape(str(item.get("action") or "Review stage timing.")),
                )
            )
        html_lines.append("</ol>")
    else:
        html_lines.append("<p>Not enough data yet to rank bottlenecks.</p>")
    html_lines.append("<h3>Plaintext Summary</h3>")
    html_lines.append(f"<pre>{escape(text_body)}</pre>")
    html_lines.append("</body></html>")
    return "".join(html_lines)


def _smtp_send(subject: str, text_body: str, html_body: str) -> Dict[str, Any]:
    ok, missing, cfg = _ensure_email_config()
    if not ok:
        raise RuntimeError("Missing email configuration: " + ", ".join(missing))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{cfg['from_name']} <{cfg['address']}>"
    message["To"] = cfg["to"]
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    password = cfg["password"]
    last_error: Optional[Exception] = None

    for attempt in range(1, SMTP_MAX_ATTEMPTS + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
                smtp.login(cfg["address"], password)
                refused = smtp.send_message(message)
            if refused:
                raise RuntimeError(f"SMTP refused recipients: {refused}")
            return {"accepted": True, "attempt": attempt, "transport": "smtp"}
        except Exception as exc:
            last_error = exc
            if attempt < SMTP_MAX_ATTEMPTS:
                delay_seconds = SMTP_BACKOFF_SECONDS ** attempt
                subprocess.run(["/bin/sleep", str(delay_seconds)], check=False)

    raise RuntimeError(f"SMTP delivery failed after {SMTP_MAX_ATTEMPTS} attempts: {last_error}")


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and send daily latency insights by email")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Generate report only")
    mode.add_argument("--send", action="store_true", help="Generate and send report")
    parser.add_argument("--days", type=int, default=7, help="Trailing lookback window")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _load_env()
    args = _parse_args(argv)
    if not args.dry_run and not args.send:
        args.dry_run = True

    mode = "send" if args.send else "dry_run"
    days = max(1, int(args.days or 7))

    _append_log({"event": "run_started", "mode": mode, "days": days})

    try:
        _run_latency_report(days)
        summary = _load_latest_summary()
        text_body = _text_report(summary)
        html_body = _html_report(summary, text_body)
        subject = f"McLeod Daily Latency Insights | {datetime.now().strftime('%Y-%m-%d')}"

        if args.send:
            result = _smtp_send(subject, text_body, html_body)
            _append_log({
                "event": "send_succeeded",
                "mode": mode,
                "days": days,
                "subject": subject,
                "recipient": os.getenv("EMAIL_TO", "").strip(),
                "result": result,
                "latest_report": str(LATEST_MD),
            })
            print(f"Email sent: {subject}")
        else:
            _append_log({
                "event": "dry_run_completed",
                "mode": mode,
                "days": days,
                "subject": subject,
                "latest_report": str(LATEST_MD),
            })
            print(text_body)

        return 0
    except Exception as exc:
        _append_log({"event": "run_failed", "mode": mode, "days": days, "error": str(exc)})
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
