#!/usr/bin/env python3
"""Send the reconciled McLeod Alpha bot trade review as a styled HTML email."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
LEARNING_DIR = ROOT / "data" / "learning"
REPORT_DIR = ROOT / "reports" / "daily_trade_learning"
ATTRIBUTION_DIR = ROOT / "reports" / "daily_loss_attribution"
STATE_PATH = ROOT / "data" / "daily_bot_trade_review_email_state.json"
DELIVERY_LOG_PATH = LEARNING_DIR / "daily_bot_trade_review_email.log"
EASTERN_TZ = ZoneInfo("America/New_York")
SENDER_DISPLAY_NAME = "McLeod Alpha Daily Review"


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _currency(value: Any) -> str:
    try:
        number = float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return str(value)
    prefix = "-" if number < 0 else ""
    return f"{prefix}${abs(number):,.2f}"


def _monetary_header(header: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(header).lower()).strip()
    if any(
        excluded in normalized
        for excluded in (
            "time", "minute", "count", "trades", "rate", "pct", "percent",
            "quantity", "contracts", "score", "id", "reason",
        )
    ):
        return False
    return any(
        marker in normalized
        for marker in (
            "pnl", "p l", "profit", "loss", "average", "entry", "exit",
            "price", "bid", "ask", "spread", "drag", "shortfall", "saving",
            "cost", "stop", "mfe", "mae",
        )
    )


def _normalize_dollar_markdown(markdown: str) -> str:
    """Add consistent currency symbols to monetary Markdown values."""
    lines = markdown.splitlines()
    output: list[str] = []
    headers: list[str] | None = None
    in_table = False
    for index, raw in enumerate(lines):
        line = raw.strip()
        if (
            line.startswith("|")
            and index + 1 < len(lines)
            and re.match(r"^\|\s*:?-{3,}", lines[index + 1].strip())
        ):
            headers = [cell.strip() for cell in line.strip("|").split("|")]
            in_table = True
            output.append(raw)
            continue
        if in_table and line.startswith("|") and headers:
            if re.match(r"^\|\s*:?-{3,}", line):
                output.append(raw)
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            for cell_index, cell in enumerate(cells):
                cells[cell_index] = re.sub(
                    r"\$-([\d,]+(?:\.\d+)?)",
                    r"-$\1",
                    cell,
                )
                if cell_index >= len(headers) or not _monetary_header(headers[cell_index]):
                    continue
                if re.fullmatch(r"\$?-?[\d,]+(?:\.\d+)?", cells[cell_index]):
                    cells[cell_index] = _currency(cells[cell_index])
            output.append("| " + " | ".join(cells) + " |")
            continue
        if in_table and not line.startswith("|"):
            in_table = False
            headers = None

        normalized = re.sub(
            r"(?i)\b(pnl|p&l|broker_pnl|unlinked_pnl|stop_pnl|price|cost|drag|shortfall|saving)"
            r"=(-?[\d,]+(?:\.\d+)?)",
            lambda match: f"{match.group(1)}={_currency(match.group(2))}",
            raw,
        )
        normalized = re.sub(
            r"(?i)(\boutperformed\b.+?\bby\s+)(-?[\d,]+\.\d{2})\b",
            lambda match: match.group(1) + _currency(match.group(2)),
            normalized,
        )
        normalized = re.sub(
            r"\$-([\d,]+(?:\.\d+)?)",
            r"-$\1",
            normalized,
        )
        output.append(normalized)
    return "\n".join(output)


def _build_email_summary(trading_date: str) -> dict[str, Any]:
    learning = _load_json(REPORT_DIR / f"daily_trade_learning_{trading_date}.json")
    broker = (learning.get("summary") or {}).get("broker_backed") or {}
    lessons = [
        row for row in (learning.get("actionable_lessons") or [])
        if isinstance(row, dict)
    ]
    scale = learning.get("scale_decision") or {}
    trades = int(broker.get("trades") or 0)
    wins = int(broker.get("wins") or 0)
    pnl = float(broker.get("pnl") or 0.0)
    return {
        "pnl": pnl,
        "trades": trades,
        "wins": wins,
        "losses": int(broker.get("losses") or 0),
        "win_rate": float(broker.get("win_rate") or 0.0),
        "lessons": lessons[:3],
        "next_session": str(
            scale.get("rationale")
            or "Keep live settings unchanged until the evidence gates are satisfied."
        ),
        "measurements": [
            (
                "Continue protective-stop and ratchet reliability measurement, "
                "including desired, submitted, and broker-verified stop states."
            ),
            (
                "Begin spread-aware contract-selection comparison using actual "
                "ask entry and subsequent executable bid evidence."
            ),
            (
                "Continue entry/exit slippage, management-cycle latency, blockers, "
                "cooling, startup guard, and missed-opportunity tracking."
            ),
        ],
    }


def _summary_text(summary: dict[str, Any]) -> str:
    lines = [
        "SUMMARY",
        (
            f"Result: {_currency(summary['pnl'])} over {summary['trades']} trades; "
            f"{summary['wins']} wins, {summary['losses']} losses, "
            f"{summary['win_rate']:.1%} win rate."
        ),
        "What We Learned:",
    ]
    for lesson in summary["lessons"]:
        lines.append(
            f"- {lesson.get('title')}: {lesson.get('signal')}. "
            f"{lesson.get('action')}"
        )
    lines.extend([
        f"Next Session: {summary['next_session']}",
        "Measurements Starting Or Continuing:",
        *[f"- {measurement}" for measurement in summary["measurements"]],
    ])
    return _normalize_dollar_markdown("\n".join(lines))


def _summary_html(summary: dict[str, Any]) -> str:
    pnl = float(summary["pnl"])
    result_color = "#147a45" if pnl >= 0 else "#b42335"
    result_background = "#eaf8f0" if pnl >= 0 else "#fff0f1"
    lessons = "".join(
        "<li style=\"margin:7px 0;color:#34445f;font-size:13px;\">"
        f"<strong>{_inline(str(row.get('title') or 'Learning'))}:</strong> "
        f"{_inline(_normalize_dollar_markdown(str(row.get('signal') or '')))}. "
        f"{_inline(str(row.get('action') or ''))}</li>"
        for row in summary["lessons"]
    )
    measurements = "".join(
        "<li style=\"margin:7px 0;color:#34445f;font-size:13px;\">"
        f"{_inline(row)}</li>"
        for row in summary["measurements"]
    )
    return f"""
<div style="border:1px solid #d7e2f0;border-radius:14px;overflow:hidden;background:#f9fbfe;margin:0 0 22px;">
  <div style="padding:14px 18px;background:#eaf1fb;color:#173763;font-size:18px;font-weight:750;">Summary</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
    <tr>
      <td style="width:34%;padding:14px 10px 14px 18px;background:{result_background};">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#67768c;">Net P&amp;L</div>
        <div style="font-size:24px;font-weight:800;color:{result_color};margin-top:3px;">{_currency(pnl)}</div>
      </td>
      <td style="width:33%;padding:14px 10px;text-align:center;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#67768c;">Trades</div>
        <div style="font-size:24px;font-weight:800;color:#173763;margin-top:3px;">{summary['trades']}</div>
      </td>
      <td style="width:33%;padding:14px 18px 14px 10px;text-align:right;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#67768c;">Win Rate</div>
        <div style="font-size:24px;font-weight:800;color:#173763;margin-top:3px;">{summary['win_rate']:.1%}</div>
      </td>
    </tr>
  </table>
  <div style="padding:2px 18px 16px;">
    <div style="font-size:14px;font-weight:750;color:#173763;margin-top:12px;">What We Learned</div>
    <ul style="margin:4px 0 12px;padding-left:19px;">{lessons}</ul>
    <div style="padding:11px 13px;border-left:4px solid #4f7ec8;background:#eef4fc;border-radius:6px;color:#34445f;font-size:13px;">
      <strong>Next Session:</strong> {_inline(summary['next_session'])}
    </div>
    <div style="font-size:14px;font-weight:750;color:#173763;margin-top:14px;">Measurements Starting Or Continuing</div>
    <ul style="margin:4px 0 0;padding-left:19px;">{measurements}</ul>
  </div>
</div>
"""


def markdown_to_email_html(
    markdown: str,
    trading_date: str,
    *,
    summary: dict[str, Any] | None = None,
) -> str:
    """Render the review's constrained Markdown into email-safe HTML."""
    blocks: list[str] = []
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            blocks.append("</ul>")
            list_open = False

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        if (
            line.startswith("|")
            and index + 1 < len(lines)
            and re.match(r"^\|\s*:?-{3,}", lines[index + 1].strip())
        ):
            close_list()
            headers = [cell.strip() for cell in line.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([
                    cell.strip() for cell in lines[index].strip().strip("|").split("|")
                ])
                index += 1
            head = "".join(
                f"<th style=\"padding:8px 9px;text-align:left;border-bottom:2px solid #cbd8ea;"
                f"font-size:12px;color:#24487f;\">{_inline(cell)}</th>"
                for cell in headers
            )
            body = "".join(
                "<tr>" + "".join(
                    f"<td style=\"padding:8px 9px;border-bottom:1px solid #e5ebf4;"
                    f"font-size:12px;color:#3d4960;\">{_inline(cell)}</td>"
                    for cell in row
                ) + "</tr>"
                for row in rows
            )
            blocks.append(
                "<div style=\"overflow-x:auto;margin:12px 0 20px;\">"
                "<table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\" "
                "style=\"width:100%;border-collapse:collapse;background:#f9fbfe;"
                "border:1px solid #dce5f2;border-radius:8px;\">"
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
            )
            continue
        if not line:
            close_list()
        elif line.startswith("# "):
            close_list()
            blocks.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            close_list()
            blocks.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            close_list()
            blocks.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("- "):
            if not list_open:
                blocks.append("<ul>")
                list_open = True
            blocks.append(f"<li>{_inline(line[2:])}</li>")
        elif re.match(r"^\d+\.\s+", line):
            close_list()
            blocks.append(f"<p class=\"step\">{_inline(line)}</p>")
        else:
            close_list()
            blocks.append(f"<p>{_inline(line)}</p>")
        index += 1
    close_list()

    content = "\n".join(blocks)
    summary_card = _summary_html(summary) if summary else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>McLeod Alpha Daily Bot Trade Review</title>
</head>
<body style="margin:0;background:#f3f6fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;">Broker-reconciled McLeod Alpha bot trade review</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f6fb;">
    <tr><td align="center" style="padding:8px 10px 18px;">
      <table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:100%;max-width:720px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 8px 30px rgba(31,49,82,.10);">
        <tr><td style="padding:20px 28px;background:linear-gradient(135deg,#15284c,#365b9d);color:#ffffff;">
          <div style="font-size:12px;letter-spacing:1.7px;text-transform:uppercase;opacity:.78;">McLeod Alpha</div>
          <div style="font-size:28px;font-weight:750;margin-top:7px;">Daily Bot Trade Review</div>
          <div style="font-size:15px;margin-top:7px;opacity:.86;">Broker-Reconciled Learning</div>
        </td></tr>
        <tr><td class="review" style="padding:18px 28px 28px;line-height:1.52;">
          <style>
            .review h1 {{ display:none; }}
            .review h2 {{ color:#24487f;font-size:20px;margin:22px 0 10px;border-bottom:1px solid #dce5f2;padding-bottom:7px; }}
            .review h3 {{ color:#172f58;font-size:16px;margin:18px 0 7px; }}
            .review p {{ margin:9px 0;color:#3d4960;font-size:14px; }}
            .review ul {{ margin:8px 0 18px;padding-left:21px; }}
            .review li {{ margin:6px 0;color:#3d4960;font-size:14px; }}
            .review strong {{ color:#172033; }}
            .review code {{ background:#eef3fa;border-radius:5px;padding:2px 5px;font-size:12px; }}
            .review .step {{ background:#f5f8fc;border-left:3px solid #4f7ec8;padding:9px 12px;border-radius:4px; }}
          </style>
          {summary_card}
          {content}
        </td></tr>
        <tr><td style="padding:20px 34px;background:#edf3fb;color:#5a6780;font-size:12px;line-height:1.5;">
          Evidence is diagnostic and falsifiable. No live sizing, admission logic, strategy parameters, or stop percentages are changed by this report.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _review_paths(trading_date: str) -> tuple[Path, Path]:
    md_path = LEARNING_DIR / f"mcleod-alpha-trade-review-{trading_date}.md"
    html_path = LEARNING_DIR / f"mcleod-alpha-trade-review-{trading_date}.html"
    return md_path, html_path


def _reconciliation(trading_date: str) -> dict[str, Any]:
    attribution = _load_json(
        ATTRIBUTION_DIR / f"daily_loss_attribution_{trading_date}.json"
    )
    value = attribution.get("reconciliation", {})
    return value if isinstance(value, dict) else {}


def _reconciliation_is_sendable(reconciliation: dict[str, Any]) -> bool:
    """Require exact broker/canonical parity and an empty pending outbox."""
    try:
        broker_count = int(reconciliation.get("broker_trades_today"))
        canonical_count = int(reconciliation.get("canonical_completed_trades"))
        broker_pnl = float(reconciliation.get("broker_pnl_dollars"))
        canonical_pnl = float(reconciliation.get("canonical_pnl_dollars"))
        pending = int(reconciliation.get("pending_outbox_entries"))
    except (TypeError, ValueError):
        return False
    return all((
        reconciliation.get("complete") is True,
        reconciliation.get("count_reconciled") is True,
        reconciliation.get("pnl_reconciled") is True,
        broker_count == canonical_count,
        abs(broker_pnl - canonical_pnl) < 0.005,
        pending == 0,
    ))


def _subject(trading_date: str) -> str:
    reconciliation = _reconciliation(trading_date)
    if not _reconciliation_is_sendable(reconciliation):
        raise RuntimeError(
            "Daily review email withheld: broker/canonical trade logs are not exactly reconciled"
        )
    trades = int(reconciliation["broker_trades_today"])
    pnl = float(reconciliation["broker_pnl_dollars"])
    if pnl > 0:
        subject = f"You Made Today ${abs(pnl):,.2f} Over {trades} Trades"
    elif pnl < 0:
        subject = f"You Lost Today ${abs(pnl):,.2f} Over {trades} Trades"
    else:
        subject = f"You Broke Even Today Over {trades} Trades"
    return subject.title()


def _reconciliation_label(trading_date: str) -> str:
    reconciliation = _reconciliation(trading_date)
    if _reconciliation_is_sendable(reconciliation):
        return "complete"
    if reconciliation:
        return "incomplete"
    return "unknown"


def _email_markdown(markdown: str) -> str:
    """Remove generator metadata and the redundant core performance table."""
    lines = markdown.splitlines()
    cleaned: list[str] = []
    skipping_core_performance = False
    for raw in lines:
        line = raw.strip()
        if line == "## Core Performance":
            skipping_core_performance = True
            continue
        if skipping_core_performance:
            if line.startswith("## "):
                skipping_core_performance = False
            else:
                continue
        if line == "# Daily Trade Learning Report":
            continue
        if re.match(r"^(Date|Generated):\s*", line, flags=re.IGNORECASE):
            continue
        cleaned.append(raw)
    return "\n".join(cleaned).strip() + "\n"


def _merge_shadow_studies(markdown: str, trading_date: str) -> str:
    """Idempotently add all shadow worksheets to the pretty daily review."""
    lifecycle_path = REPORT_DIR / f"trend_lifecycle_shadow_{trading_date}.md"
    if not lifecycle_path.exists():
        try:
            from reports.trend_lifecycle_shadow_report import (
                write_trend_lifecycle_shadow_report,
            )
            write_trend_lifecycle_shadow_report(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Trend lifecycle shadow report warning: {exc}")
    entry_quality_path = REPORT_DIR / f"entry_quality_shadow_{trading_date}.md"
    if not entry_quality_path.exists():
        try:
            from reports.entry_quality_shadow_report import (
                write_entry_quality_shadow_report,
            )
            write_entry_quality_shadow_report(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Entry quality shadow report warning: {exc}")
    volume_shadow_path = REPORT_DIR / f"volume_shadow_{trading_date}.md"
    if not volume_shadow_path.exists():
        try:
            from reports.volume_shadow_report import write_volume_shadow_report

            write_volume_shadow_report(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Volume shadow report warning: {exc}")
    option_selection_path = REPORT_DIR / f"option_selection_shadow_{trading_date}.md"
    if not option_selection_path.exists():
        try:
            from reports.option_selection_shadow_report import (
                write_option_selection_shadow_report,
            )

            write_option_selection_shadow_report(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Option selection shadow report warning: {exc}")
    day_trade_spy_path = REPORT_DIR / f"day_trade_spy_shadow_{trading_date}.md"
    if not day_trade_spy_path.exists():
        try:
            from reports.day_trade_spy_shadow_report import (
                write_day_trade_spy_shadow_report,
            )
            write_day_trade_spy_shadow_report(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Day Trade SPY shadow report warning: {exc}")
    missed_opportunities_path = (
        REPORT_DIR / f"missed_opportunities_shadow_{trading_date}.md"
    )
    if not missed_opportunities_path.exists():
        try:
            from reports.missed_opportunities_shadow_report import (
                write_missed_opportunities_shadow_report,
            )
            write_missed_opportunities_shadow_report(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Missed opportunities shadow report warning: {exc}")
    startup_guard_path = REPORT_DIR / f"startup_guard_review_{trading_date}.md"
    if not startup_guard_path.exists():
        try:
            from reports.startup_guard_review import write_startup_guard_review

            reconciliation_complete = _reconciliation_label(trading_date) == "complete"
            write_startup_guard_review(
                trading_date,
                root=ROOT,
                reconciliation_complete=reconciliation_complete,
            )
        except Exception as exc:
            print(f"Startup guard review warning: {exc}")
    cooling_period_path = REPORT_DIR / f"cooling_period_review_{trading_date}.md"
    if not cooling_period_path.exists():
        try:
            from reports.cooling_period_review import write_cooling_period_review

            reconciliation_complete = _reconciliation_label(trading_date) == "complete"
            write_cooling_period_review(
                trading_date,
                root=ROOT,
                reconciliation_complete=reconciliation_complete,
            )
        except Exception as exc:
            print(f"Cooling period review warning: {exc}")
    market_trend_path = REPORT_DIR / f"market_trend_shadow_{trading_date}.md"
    if not market_trend_path.exists():
        try:
            from reports.market_trend_shadow_report import (
                write_market_trend_shadow_report,
            )

            write_market_trend_shadow_report(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Market trend shadow report warning: {exc}")
    stop_execution_path = REPORT_DIR / f"stop_execution_review_{trading_date}.md"
    if not stop_execution_path.exists():
        try:
            from reports.stop_execution_review import write_stop_execution_review

            write_stop_execution_review(trading_date, root=ROOT)
        except Exception as exc:
            print(f"Stop execution review warning: {exc}")

    headings = (
        "## Trend Lifecycle V2 Shadow Review",
        "## Entry Quality Shadow Studies",
        "## Volume — Daily Shadow Test",
        "## Option Selection — Spread-Aware Shadow Ranking",
        "## Day Trade SPY Five-Test Shadow Review",
        "## Missed Opportunities — Shadow Review",
        "## Startup Guard — Daily Assessment",
        "## Cooling Period — Daily Assessment",
        "## Session Market Trend — Entry Shadow Test",
        "## Protective Stop and Ratchet Reliability",
    )
    positions = [markdown.find(heading) for heading in headings if heading in markdown]
    if positions:
        markdown = markdown[:min(positions)].rstrip()
    sections = [
        path.read_text(encoding="utf-8").strip()
        for path in (
            lifecycle_path,
            entry_quality_path,
            volume_shadow_path,
            option_selection_path,
            day_trade_spy_path,
            missed_opportunities_path,
            startup_guard_path,
            cooling_period_path,
            market_trend_path,
            stop_execution_path,
        )
        if path.exists()
    ]
    if not sections:
        return markdown
    return markdown.rstrip() + "\n\n" + "\n\n".join(sections) + "\n"


def _send_smtp(
    *,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    username = (
        os.getenv("SMTP_USERNAME", "").strip()
        or os.getenv("EMAIL_ADDRESS", "").strip()
    )
    password = (
        os.getenv("SMTP_PASSWORD", "").strip()
        or os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    )
    host = os.getenv("SMTP_HOST", "").strip() or (
        "smtp.gmail.com" if username.lower().endswith("@gmail.com") else ""
    )
    port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    sender = (
        os.getenv("SMTP_FROM", "").strip()
        or os.getenv("EMAIL_ADDRESS", "").strip()
        or username
    )
    if not all((host, username, password, sender, recipient)):
        raise RuntimeError("SMTP configuration or review recipient is incomplete")

    message = EmailMessage()
    message["Subject"] = subject
    sender_address = parseaddr(sender)[1] or sender
    message["From"] = formataddr((SENDER_DISPLAY_NAME, sender_address))
    message["To"] = recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


def send_review(
    trading_date: str,
    *,
    recipient: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> Path:
    _load_dotenv()
    md_path, html_path = _review_paths(trading_date)
    generated_review = REPORT_DIR / f"daily_trade_learning_{trading_date}.md"
    if generated_review.exists():
        LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            generated_review.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    elif not md_path.exists():
        raise FileNotFoundError(f"Review artifact not found: {md_path}")

    markdown = _merge_shadow_studies(
        md_path.read_text(encoding="utf-8"),
        trading_date,
    )
    md_path.write_text(markdown, encoding="utf-8")
    email_markdown = _normalize_dollar_markdown(_email_markdown(markdown))
    email_summary = _build_email_summary(trading_date)
    html_body = markdown_to_email_html(
        email_markdown,
        trading_date,
        summary=email_summary,
    )
    html_path.write_text(html_body, encoding="utf-8")
    if dry_run:
        return html_path

    reconciliation_data = _reconciliation(trading_date)
    if not _reconciliation_is_sendable(reconciliation_data):
        raise RuntimeError(
            "Daily review email withheld: exact broker trade-count/P&L parity "
            "and zero pending outbox entries are required"
        )

    state = _load_json(STATE_PATH)
    digest = hashlib.sha256(email_markdown.encode("utf-8")).hexdigest()
    if (
        not force
        and state.get("last_sent_date") == trading_date
        and state.get("last_artifact_sha256") == digest
    ):
        print(f"Daily bot trade review already sent for {trading_date}")
        return html_path

    to_email = (
        recipient
        or os.getenv("DAILY_BOT_REVIEW_TO_EMAIL", "").strip()
        or os.getenv("DAILY_TRADE_LOG_TO_EMAIL", "").strip()
        or os.getenv("DAILY_PNL_TO_EMAIL", "").strip()
        or os.getenv("EMAIL_TO", "").strip()
    )
    if not to_email:
        raise RuntimeError("No daily bot review recipient is configured")

    subject = _subject(trading_date)
    reconciliation = _reconciliation_label(trading_date)
    text_body = (
        "McLeod Alpha Daily Bot Trade Review\n"
        "Canonical broker reconciliation: complete\n\n"
        f"{_summary_text(email_summary)}\n\n"
        f"{email_markdown}\n"
    )
    _send_smtp(
        recipient=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    sent_at = datetime.now(EASTERN_TZ).isoformat(timespec="seconds")
    _save_json(
        STATE_PATH,
        {
            "last_sent_date": trading_date,
            "last_sent_at": sent_at,
            "last_recipient": to_email,
            "last_subject": subject,
            "last_artifact_sha256": digest,
            "reconciliation": reconciliation,
            "last_html_path": str(html_path),
            "attachments_sent": 0,
        },
    )
    DELIVERY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DELIVERY_LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(
            f"{sent_at} | send_success | date={trading_date}"
            f" | recipient={to_email} | reconciliation={reconciliation}"
            " | attachments=0\n"
        )
    print(f"Daily bot trade review emailed for {trading_date} to {to_email}")
    return html_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=datetime.now(EASTERN_TZ).date().isoformat(),
        help="Eastern trading date (YYYY-MM-DD)",
    )
    parser.add_argument("--to", help="Recipient override")
    parser.add_argument("--dry-run", action="store_true", help="Render HTML without sending")
    parser.add_argument("--force", action="store_true", help="Send even if this artifact was already delivered")
    args = parser.parse_args()
    send_review(args.date, recipient=args.to, dry_run=args.dry_run, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
