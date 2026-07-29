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


def markdown_to_email_html(markdown: str, trading_date: str) -> str:
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
    <tr><td align="center" style="padding:28px 12px;">
      <table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:100%;max-width:720px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 8px 30px rgba(31,49,82,.10);">
        <tr><td style="padding:28px 34px;background:linear-gradient(135deg,#15284c,#365b9d);color:#ffffff;">
          <div style="font-size:12px;letter-spacing:1.7px;text-transform:uppercase;opacity:.78;">McLeod Alpha</div>
          <div style="font-size:28px;font-weight:750;margin-top:7px;">Daily Bot Trade Review</div>
          <div style="font-size:15px;margin-top:7px;opacity:.86;">Broker-Reconciled Learning</div>
        </td></tr>
        <tr><td class="review" style="padding:30px 34px;line-height:1.58;">
          <style>
            .review h1 {{ display:none; }}
            .review h2 {{ color:#24487f;font-size:21px;margin:30px 0 12px;border-bottom:1px solid #dce5f2;padding-bottom:8px; }}
            .review h3 {{ color:#172f58;font-size:17px;margin:24px 0 8px; }}
            .review p {{ margin:9px 0;color:#3d4960;font-size:14px; }}
            .review ul {{ margin:8px 0 18px;padding-left:21px; }}
            .review li {{ margin:6px 0;color:#3d4960;font-size:14px; }}
            .review strong {{ color:#172033; }}
            .review code {{ background:#eef3fa;border-radius:5px;padding:2px 5px;font-size:12px; }}
            .review .step {{ background:#f5f8fc;border-left:3px solid #4f7ec8;padding:9px 12px;border-radius:4px; }}
          </style>
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
    email_markdown = _email_markdown(markdown)
    html_body = markdown_to_email_html(email_markdown, trading_date)
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
