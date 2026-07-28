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

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            close_list()
            continue
        if line.startswith("# "):
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
    close_list()

    content = "\n".join(blocks)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>McLeod Alpha Daily Bot Trade Review — {html.escape(trading_date)}</title>
</head>
<body style="margin:0;background:#f3f6fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;">Broker-reconciled McLeod Alpha bot trade review for {html.escape(trading_date)}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f6fb;">
    <tr><td align="center" style="padding:28px 12px;">
      <table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:100%;max-width:720px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 8px 30px rgba(31,49,82,.10);">
        <tr><td style="padding:28px 34px;background:linear-gradient(135deg,#15284c,#365b9d);color:#ffffff;">
          <div style="font-size:12px;letter-spacing:1.7px;text-transform:uppercase;opacity:.78;">McLeod Alpha</div>
          <div style="font-size:28px;font-weight:750;margin-top:7px;">Daily Bot Trade Review</div>
          <div style="font-size:15px;margin-top:7px;opacity:.86;">{html.escape(trading_date)} · Broker-reconciled learning</div>
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


def _subject(trading_date: str) -> str:
    learning = _load_json(REPORT_DIR / f"daily_trade_learning_{trading_date}.json")
    overall = learning.get("summary", {}).get("broker_backed", {})
    trades = int(overall.get("trades") or 0)
    pnl = float(overall.get("pnl") or 0.0)
    return f"McLeod Alpha Daily Bot Review — {trading_date} | {trades} trades | ${pnl:,.2f}"


def _reconciliation_label(trading_date: str) -> str:
    attribution = _load_json(ATTRIBUTION_DIR / f"daily_loss_attribution_{trading_date}.json")
    reconciliation = attribution.get("reconciliation", {})
    if reconciliation.get("complete") is True:
        return "complete"
    if reconciliation:
        return "incomplete"
    return "unknown"


def _attachments(trading_date: str, md_path: Path) -> list[Path]:
    candidates = [
        md_path,
        REPORT_DIR / f"daily_trade_learning_{trading_date}.json",
        REPORT_DIR / f"daily_trade_learning_trades_{trading_date}.csv",
    ]
    return [path for path in candidates if path.exists()]


def _send_smtp(
    *,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
    attachments: list[Path],
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
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    for path in attachments:
        message.add_attachment(
            path.read_bytes(),
            maintype="application",
            subtype="octet-stream",
            filename=path.name,
        )

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
    if not md_path.exists():
        raise FileNotFoundError(f"Review artifact not found: {md_path}")

    markdown = md_path.read_text(encoding="utf-8")
    html_body = markdown_to_email_html(markdown, trading_date)
    html_path.write_text(html_body, encoding="utf-8")
    if dry_run:
        return html_path

    state = _load_json(STATE_PATH)
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
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
        f"McLeod Alpha Daily Bot Trade Review — {trading_date}\n"
        f"Canonical broker reconciliation: {reconciliation}\n\n"
        f"{markdown}\n"
    )
    _send_smtp(
        recipient=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        attachments=_attachments(trading_date, md_path),
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
        },
    )
    DELIVERY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DELIVERY_LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(
            f"{sent_at} | send_success | date={trading_date}"
            f" | recipient={to_email} | reconciliation={reconciliation}\n"
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
