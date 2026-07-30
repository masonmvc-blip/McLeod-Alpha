#!/usr/bin/env python3
"""Send the reconciled McLeod Alpha bot trade review as a styled HTML email."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LEARNING_DIR = ROOT / "data" / "learning"
REPORT_DIR = ROOT / "reports" / "daily_trade_learning"
ATTRIBUTION_DIR = ROOT / "reports" / "daily_loss_attribution"
STATE_PATH = ROOT / "data" / "daily_bot_trade_review_email_state.json"
DELIVERY_LOG_PATH = LEARNING_DIR / "daily_bot_trade_review_email.log"
EASTERN_TZ = ZoneInfo("America/New_York")
SENDER_DISPLAY_NAME = "McLeod Alpha Daily Review"
EMAIL_HIDDEN_SECTIONS = {
    "## Core Performance",
    "## Exit Reason Breakdown",
    "## Biggest Losses (Top 5)",
    "## Biggest Wins (Top 5)",
    "## Actionable Lessons",
    "## Scale Decision (Next Session)",
    "## Model Learning Jobs",
    "## Trend Lifecycle V2 Shadow Review",
    "## Entry Quality Shadow Studies",
    "## Volume — Daily Shadow Test",
    "## Option Selection — Spread-Aware Shadow Ranking",
    "## Day Trade SPY Five-Test Shadow Review",
    "### Indicator Weight Shadow Comparisons",
    "### Weighted Checklist Score Study",
    "### Alternative Checklist Policies",
    "### Broker-Backed Executed Trades",
    "### Today's Contract Comparisons",
    "### Losses Correctly Avoided",
    "### Recurring Rejection Patterns",
}
EMAIL_HIDDEN_SECTION_TITLES = {
    re.sub(r"^#{1,6}\s+", "", heading)
    for heading in EMAIL_HIDDEN_SECTIONS
}
EMAIL_HIDDEN_SECTION_TITLES.update({
    "Historical Context",
    "Fresh Forward Sample",
    "Locked Evidence Gates",
    "Session Market Trend — Entry Shadow Test",
})
EMAIL_SUPPRESSED_HEADINGS = {
    "Missed Opportunities — Shadow Review",
}


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
    if normalized in {"wins", "losses", "missed", "protected"}:
        return False
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
    lessons = [
        row for row in (learning.get("actionable_lessons") or [])
        if isinstance(row, dict)
    ]
    scale = learning.get("scale_decision") or {}
    changes = [
        str(row.get("action") or "").strip()
        for row in lessons
        if str(row.get("action") or "").strip()
    ]
    scale_action = str(scale.get("rationale") or "").strip()
    if scale_action and scale_action not in changes:
        changes.append(scale_action)
    return {
        "lessons": lessons[:3],
        "changes": changes[:3] or [
            "Keep live settings unchanged until the governed evidence gates are satisfied."
        ],
    }


def _summary_text(summary: dict[str, Any]) -> str:
    lines = ["SUMMARY", "1. What We Learned:"]
    for lesson in summary["lessons"]:
        lines.append(
            f"- {lesson.get('title')}: {lesson.get('signal')}."
        )
    lines.extend(
        ["2. Changes We Need To Make:", *[
            f"- {change}" for change in summary["changes"]
        ]]
    )
    return _normalize_dollar_markdown("\n".join(lines))


def _summary_html(summary: dict[str, Any]) -> str:
    lessons = "".join(
        "<li style=\"margin:7px 0;color:#34445f;font-size:13px;\">"
        f"<strong>{_inline(str(row.get('title') or 'Learning'))}:</strong> "
        f"{_inline(_normalize_dollar_markdown(str(row.get('signal') or '')))}.</li>"
        for row in summary["lessons"]
    )
    changes = "".join(
        "<li style=\"margin:7px 0;color:#34445f;font-size:13px;\">"
        f"{_inline(row)}</li>"
        for row in summary["changes"]
    )
    return f"""
<div style="border:1px solid #d7e2f0;border-radius:14px;overflow:hidden;background:#f9fbfe;margin:0 0 14px;">
  <div style="padding:12px 18px;background:#eaf1fb;color:#173763;font-size:18px;font-weight:750;">Summary</div>
  <div style="padding:12px 18px 14px;">
    <div style="font-size:14px;font-weight:750;color:#173763;">1. What We Learned</div>
    <ul style="margin:4px 0 12px;padding-left:19px;">{lessons}</ul>
    <div style="font-size:14px;font-weight:750;color:#173763;">2. Changes We Need To Make</div>
    <ul style="margin:4px 0 0;padding-left:19px;">{changes}</ul>
  </div>
</div>
"""


def _spy_trade_tracker_html(tracker: dict[str, Any]) -> str:
    """Render the canonical all-time SPY scorecard as compact Outlook-safe KPIs."""
    cells = (
        ("All-Time Trades", f"{int(tracker.get('trades') or 0):,}"),
        ("Win Rate", f"{float(tracker.get('win_rate') or 0.0):.1%}"),
        ("Net P&L", _currency(tracker.get("pnl_dollars") or 0.0)),
        ("Average / Trade", _currency(tracker.get("average_pnl_dollars") or 0.0)),
    )
    rendered = "".join(
        "<td width=\"25%\" align=\"center\" style=\"padding:11px 5px;"
        "border-right:1px solid #dce5f2;\">"
        f"<div style=\"font-size:10px;letter-spacing:.35px;text-transform:uppercase;"
        f"color:#617087;\">{html.escape(label)}</div>"
        f"<div style=\"margin-top:4px;font-size:18px;font-weight:750;color:#173763;\">"
        f"{html.escape(value)}</div></td>"
        for label, value in cells
    )
    through = html.escape(str(tracker.get("through_date") or ""))
    days = int(tracker.get("trading_days") or 0)
    return (
        "<div style=\"margin:0 0 14px;border:1px solid #d7e2f0;"
        "border-radius:12px;overflow:hidden;background:#f9fbfe;\">"
        "<div style=\"padding:10px 14px;background:#eaf1fb;color:#173763;"
        "font-size:17px;font-weight:750;text-align:center;\">SPY Trade Tracker</div>"
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" "
        "style=\"width:100%;border-collapse:collapse;\"><tr>"
        f"{rendered}</tr></table>"
        f"<div style=\"padding:7px 12px;text-align:center;color:#64748b;"
        f"font-size:11px;\">Canonical broker-backed history through {through} "
        f"across {days} trading day{'s' if days != 1 else ''}; refreshed daily.</div>"
        "</div>"
    )


def _strike_from_symbol(symbol: Any) -> str:
    match = re.search(r"[CP]0*(\d{3,8})$", str(symbol or "").replace(" ", ""))
    if not match:
        return "—"
    try:
        return f"{int(match.group(1)) / 1000:g}"
    except ValueError:
        return "—"


def _metric(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("score")
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _snapshot_trade_rows(trading_date: str) -> list[dict[str, str]]:
    """Load the same canonical completed-trade objects used by the Cockpit."""
    from engine.memory import get_memory

    trades: list[dict[str, Any]] = []
    try:
        with urlopen(
            f"http://127.0.0.1:5001/api/today-trades?date={trading_date}",
            timeout=8,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if str(payload.get("trading_date") or "") == trading_date:
            trades = [
                row for row in (payload.get("trades") or [])
                if isinstance(row, dict)
            ]
    except Exception:
        trades = []
    if not trades:
        trades = get_memory().load_completed_trades_for_date(trading_date)
    rows: list[dict[str, str]] = []
    for trade in sorted(trades, key=lambda row: str(row.get("entry_time") or "")):
        entry = str(trade.get("entry_time") or "")
        exit_at = str(trade.get("exit_time") or "")
        try:
            entry_label = datetime.fromisoformat(entry.replace("Z", "+00:00")).astimezone(
                EASTERN_TZ
            ).strftime("%-I:%M")
            exit_label = datetime.fromisoformat(exit_at.replace("Z", "+00:00")).astimezone(
                EASTERN_TZ
            ).strftime("%-I:%M")
            time_label = f"{entry_label} – {exit_label}"
        except ValueError:
            time_label = "—"
        direction = str(trade.get("direction") or "").upper()
        strike = trade.get("strike_price")
        strike_label = (
            f"{float(strike):g}"
            if strike is not None
            else _strike_from_symbol(trade.get("option_symbol"))
        )
        phase = str(
            trade.get("momentum_phase")
            or trade.get("trend_stage")
            or "UNKNOWN"
        ).replace("_", " ").title()
        pnl = float(trade.get("pnl") or trade.get("option_pnl_dollars") or 0.0)
        option_entry = float(trade.get("option_entry") or trade.get("entry_price") or 0.0)
        option_exit = float(trade.get("option_exit") or trade.get("exit_price") or 0.0)
        recorded_pnl_pct = trade.get("pnl_pct")
        pnl_pct = (
            float(recorded_pnl_pct)
            if recorded_pnl_pct not in (None, "")
            else ((option_exit - option_entry) / option_entry) * 100.0 if option_entry else 0.0
        )
        feature = trade.get("feature_snapshot") or {}
        if isinstance(feature, dict):
            feature = feature.get("all_features") or feature
        feature = feature if isinstance(feature, dict) else {}
        checklist = feature.get("checklist") or {}
        passed = (
            trade.get("indicator_count")
            or trade.get("entry_gate_score")
            or checklist.get("passed")
            or feature.get("entry_score")
            or "—"
        )
        total = trade.get("indicator_total") or checklist.get("total") or 5
        rows.append({
            "time": time_label,
            "option": f"{strike_label} {direction}",
            "contracts": str(
                int(float(trade.get("contracts") or trade.get("option_quantity") or 0))
            ),
            "entry": _currency(option_entry),
            "exit": _currency(option_exit),
            "checklist": f"{passed} / {total}",
            "phase": phase,
            "cq": _metric(
                trade.get("continuation_quality_score")
                or feature.get("continuation_quality")
            ),
            "mas": _metric(
                trade.get("momentum_acceleration_score")
                or feature.get("momentum_acceleration")
            ),
            "abs": _metric(
                trade.get("absorption_score")
                or feature.get("absorption_score")
            ),
            "conf": _metric(
                trade.get("confidence_score")
                or feature.get("confidence_score")
            ),
            "pnl": f"{_currency(pnl)} · {pnl_pct:+.1f}%",
            "exit_reason": (
                "Mason"
                if str(trade.get("manual_label") or "").strip() == "Mason"
                else str(trade.get("exit_reason") or "—").replace("_", " ").title()
            ),
            "positive": pnl >= 0,
        })
    return rows


def _today_trades_svg(trading_date: str, rows: list[dict[str, str]]) -> str:
    columns = [
        ("Time", "time", 145),
        ("Option", "option", 115),
        ("#", "contracts", 42),
        ("Entry", "entry", 76),
        ("Exit", "exit", 76),
        ("Checklist", "checklist", 85),
        ("Phase", "phase", 165),
        ("P&L", "pnl", 130),
        ("Exit", "exit_reason", 130),
    ]
    width = sum(column[2] for column in columns) + 40
    header_height = 96
    row_height = 52
    height = header_height + 42 + max(1, len(rows)) * row_height + 24
    x_positions = []
    cursor = 20
    for _, _, column_width in columns:
        x_positions.append(cursor)
        cursor += column_width
    header_cells = "".join(
        f"<text x='{x_positions[index] + column_width / 2:.1f}' y='122' "
        "text-anchor='middle' font-size='14' font-weight='700' fill='#617087'>"
        f"{xml_escape(label)}</text>"
        for index, (label, _, column_width) in enumerate(columns)
    )
    rendered_rows = []
    for row_index, row in enumerate(rows):
        top = 138 + row_index * row_height
        fill = "#ffffff" if row_index % 2 == 0 else "#f8fafc"
        cells = []
        for column_index, (_, key, column_width) in enumerate(columns):
            color = "#159447" if key == "pnl" and row["positive"] else (
                "#d9364f" if key == "pnl" else "#334155"
            )
            cells.append(
                f"<text x='{x_positions[column_index] + column_width / 2:.1f}' "
                f"y='{top + 32}' text-anchor='middle' font-size='14' "
                f"font-weight='500' fill='{color}'>"
                f"{xml_escape(str(row.get(key) or '—'))}</text>"
            )
        rendered_rows.append(
            f"<rect x='20' y='{top}' width='{width - 40}' height='{row_height}' "
            f"fill='{fill}' stroke='#e6ebf2'/>" + "".join(cells)
        )
    if not rows:
        rendered_rows.append(
            f"<text x='{width / 2:.1f}' y='176' text-anchor='middle' "
            "font-size='16' fill='#64748b'>No completed trades</text>"
        )
    return f"""<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>
  <rect width='{width}' height='{height}' rx='18' fill='#ffffff'/>
  <rect x='1' y='1' width='{width - 2}' height='{height - 2}' rx='17' fill='none' stroke='#d7e2f0' stroke-width='2'/>
  <text x='{width / 2:.1f}' y='42' text-anchor='middle' font-size='25' font-weight='800' fill='#173763'>Today's Trades</text>
  <text x='{width / 2:.1f}' y='68' text-anchor='middle' font-size='14' fill='#64748b'>Broker-reconciled completed trades</text>
  <rect x='20' y='92' width='{width - 40}' height='46' rx='8' fill='#edf3fb'/>
  {header_cells}
  {''.join(rendered_rows)}
</svg>"""


def _today_trades_email_html(rows: list[dict[str, str]]) -> str:
    """Render Today's Trades natively so Outlook creates no image attachment."""
    columns = (
        ("Time", "time"),
        ("Option", "option"),
        ("#", "contracts"),
        ("Entry", "entry"),
        ("Exit", "exit"),
        ("Checklist", "checklist"),
        ("Phase", "phase"),
        ("P&L", "pnl"),
        ("Exit", "exit_reason"),
    )
    head = "".join(
        "<th style=\"padding:8px 7px;"
        "text-align:center;vertical-align:middle;background:#edf3fb;"
        "border-bottom:2px solid #cbd8ea;font-size:10px;letter-spacing:.25px;"
        f"text-transform:uppercase;color:#52657f;white-space:nowrap;\">{html.escape(label)}</th>"
        for label, _ in columns
    )
    body_rows = []
    for index, row in enumerate(rows):
        cells = []
        for _, key in columns:
            color = (
                "#159447" if key == "pnl" and row["positive"]
                else "#d9364f" if key == "pnl"
                else "#334155"
            )
            cells.append(
                "<td style=\"padding:9px 7px;"
                "text-align:center;vertical-align:middle;"
                f"border-bottom:1px solid #e6ebf2;font-size:11px;color:{color};"
                "font-weight:500;white-space:nowrap;\">"
                f"{html.escape(str(row.get(key) or '—'))}</td>"
            )
        background = "#ffffff" if index % 2 == 0 else "#f8fafc"
        body_rows.append(f"<tr style=\"background:{background};\">{''.join(cells)}</tr>")
    if not body_rows:
        body_rows.append(
            "<tr><td colspan=\"9\" style=\"padding:18px;text-align:center;"
            "color:#64748b;font-size:12px;\">No completed trades</td></tr>"
        )
    return (
        "<div style=\"margin:0 0 14px;border:1px solid #d7e2f0;"
        "border-radius:12px;overflow:hidden;\">"
        "<div style=\"padding:12px 14px;background:#173763;color:#ffffff;"
        "font-size:17px;font-weight:750;text-align:center;\">Today's Trades</div>"
        "<div style=\"overflow-x:auto;\">"
        "<table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\" "
        "style=\"width:100%;table-layout:auto;border-collapse:collapse;\">"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        "</div></div>"
    )


def _write_today_trades_snapshot(trading_date: str) -> Path:
    """Render an email-safe PNG of the Cockpit Today's Trades table."""
    output_dir = LEARNING_DIR / "email_images"
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / f"todays-trades-{trading_date}.svg"
    png_path = output_dir / f"todays-trades-{trading_date}.png"
    rows = _snapshot_trade_rows(trading_date)
    svg_path.write_text(_today_trades_svg(trading_date, rows), encoding="utf-8")
    renderer = shutil.which("sips")
    if not renderer:
        raise RuntimeError("Today's Trades image renderer is unavailable")
    completed = subprocess.run(
        [renderer, "-s", "format", "png", str(svg_path), "--out", str(png_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0 or not png_path.exists():
        raise RuntimeError(
            "Today's Trades image render failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    return png_path


def markdown_to_email_html(
    markdown: str,
    trading_date: str,
    *,
    summary: dict[str, Any] | None = None,
    trades: list[dict[str, str]] | None = None,
    tracker: dict[str, Any] | None = None,
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
    trades_table = _today_trades_email_html(trades) if trades is not None else ""
    tracker_card = _spy_trade_tracker_html(tracker) if tracker else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>McLeod Alpha Daily Bot Trade Review</title>
</head>
<body style="margin:0!important;padding:0!important;background:#f3f6fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0;padding:0;background:#f3f6fb;border-collapse:collapse;">
    <tr><td align="center" style="margin:0;padding:0 10px 18px;">
      <table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:100%;max-width:720px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 8px 30px rgba(31,49,82,.10);">
        <tr><td class="review" style="margin:0;padding:0 28px 28px;line-height:1.52;">
          <style>
            .review h1 {{ display:none; }}
            .review h2 {{ color:#173763;font-size:19px;margin:24px 0 11px;background:linear-gradient(90deg,#edf4ff,#f8fbff);border-left:4px solid #4f7ec8;padding:10px 12px;border-radius:8px; }}
            .review h3 {{ color:#172f58;font-size:16px;margin:18px 0 7px; }}
            .review p {{ margin:9px 0;color:#3d4960;font-size:14px; }}
            .review ul {{ margin:8px 0 18px;padding:11px 14px 11px 32px;background:#fbfcff;border:1px solid #e4ebf5;border-radius:9px; }}
            .review li {{ margin:7px 0;color:#3d4960;font-size:14px; }}
            .review strong {{ color:#172033; }}
            .review code {{ background:#eef3fa;border-radius:5px;padding:2px 5px;font-size:12px; }}
            .review .step {{ background:#f5f8fc;border-left:3px solid #4f7ec8;padding:9px 12px;border-radius:4px; }}
            .review tbody tr:nth-child(even) td {{ background:#f4f7fb; }}
            @media only screen and (max-width:600px) {{
              .review {{ padding-left:16px !important;padding-right:16px !important; }}
              .review h2 {{ font-size:17px; }}
              .review p,.review li {{ font-size:13px; }}
            }}
          </style>
          {trades_table}
          {tracker_card}
          {summary_card}
          {content}
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


def _email_markdown(markdown: str, *, trading_date: str | None = None) -> str:
    """Apply the lean email view without deleting any underlying learning data."""
    markdown = _compact_operational_sections(markdown, trading_date=trading_date)
    lines = markdown.splitlines()
    cleaned: list[str] = []
    skipped_heading_level: int | None = None
    for raw in lines:
        line = raw.strip()
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        heading_level = len(heading_match.group(1)) if heading_match else None
        heading_title = heading_match.group(2).strip() if heading_match else ""
        hide_heading = (
            heading_title in EMAIL_HIDDEN_SECTION_TITLES
            or heading_title.startswith("Evidence Gate")
        )
        if hide_heading:
            skipped_heading_level = heading_level
            continue
        if skipped_heading_level is not None:
            if heading_level is not None and heading_level <= skipped_heading_level:
                skipped_heading_level = None
            else:
                continue
        if heading_title in EMAIL_SUPPRESSED_HEADINGS:
            continue
        if line == "# Daily Trade Learning Report":
            continue
        if re.match(r"^(Date|Generated):\s*", line, flags=re.IGNORECASE):
            continue
        cleaned.append(raw)
    return "\n".join(cleaned).strip() + "\n"


def _section_value(section: str, label: str) -> str:
    match = re.search(
        rf"(?m)^-\s+{re.escape(label)}:\s*(.+?)\.?\s*$",
        section,
    )
    return match.group(1).rstrip(".") if match else "Not recorded"


def _replace_h2_section(markdown: str, title: str, replacement: str) -> str:
    pattern = re.compile(
        rf"(?ms)^##\s+{re.escape(title)}\s*$.*?(?=^##\s+|\Z)"
    )
    return pattern.sub(replacement.rstrip() + "\n\n", markdown, count=1)


def _all_time_study_trades(trading_date: str) -> list[dict[str, Any]]:
    try:
        from reports.entry_quality_shadow_report import load_study_trades

        trades, _ = load_study_trades(root=ROOT)
    except Exception:
        return []
    return [
        row for row in trades
        if str(row.get("trade_date") or "") <= trading_date
    ]


def _all_time_trade_tracker(trading_date: str) -> dict[str, Any]:
    trades = _all_time_study_trades(trading_date)
    pnl = sum(float(row.get("pnl_dollars") or 0.0) for row in trades)
    wins = sum(float(row.get("pnl_dollars") or 0.0) > 0 for row in trades)
    return {
        "through_date": trading_date,
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate": wins / len(trades) if trades else 0.0,
        "pnl_dollars": round(pnl, 2),
        "average_pnl_dollars": round(pnl / len(trades), 2) if trades else 0.0,
        "trading_days": len({
            str(row.get("trade_date") or "")
            for row in trades
            if row.get("trade_date")
        }),
    }


def _all_time_direction_breakdown(trading_date: str) -> str | None:
    trades = _all_time_study_trades(trading_date)
    rows = []
    for direction in ("CALL", "PUT"):
        selected = [row for row in trades if row.get("direction") == direction]
        if not selected:
            continue
        wins = sum(float(row.get("pnl_dollars") or 0.0) > 0 for row in selected)
        pnl = sum(float(row.get("pnl_dollars") or 0.0) for row in selected)
        rows.append(
            f"| {direction} | {len(selected)} | {wins} | {len(selected) - wins} | "
            f"{wins / len(selected):.1%} | {_currency(pnl)} | "
            f"{_currency(pnl / len(selected))} |"
        )
    if not rows:
        return None
    return """## Direction Breakdown — All Time

| Direction | Trades | Wins | Losses | Win Rate | Net P&L | Average P&L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
""" + "\n".join(rows)


def _indicator_usefulness_summary(trading_date: str) -> str | None:
    """Summarize accumulated canonical indicator evidence through this date."""
    trades = _all_time_study_trades(trading_date)
    if not trades:
        return None
    try:
        from reports.entry_quality_shadow_report import (
            canonical_indicator_performance,
        )

        indicators = canonical_indicator_performance(
            trades,
            trading_date=trading_date,
            minimum_sample_size=20,
        )
    except Exception:
        return None

    comparable = [
        row for row in indicators
        if int(row.get("trades") or 0) >= 10
        and int(row.get("absent_trades") or 0) >= 3
    ]
    if not comparable:
        return None
    for row in comparable:
        row["average_delta"] = round(
            float(row.get("average_return") or 0.0)
            - float(row.get("absent_average_return") or 0.0),
            2,
        )
        row["win_rate_delta"] = round(
            float(row.get("win_rate_pct") or 0.0)
            - float(row.get("absent_win_rate_pct") or 0.0),
            1,
        )
    helpful = max(comparable, key=lambda row: float(row["average_delta"]))
    caution = min(comparable, key=lambda row: float(row["average_delta"]))
    covered = sum(bool(row.get("indicator_labels")) for row in trades)

    def label(row: dict[str, Any]) -> str:
        return str(row.get("indicator") or "Unknown").replace("_", " ").title()

    return f"""## Indicator Usefulness — All Time

- **Most promising:** {label(helpful)} on {helpful.get('direction')} trades is **{int(helpful.get('wins') or 0)}W/{int(helpful.get('losses') or 0)}L** across **{int(helpful.get('trades') or 0)} trades**, averaging **{_currency(helpful.get('average_return') or 0.0)}** versus **{_currency(helpful.get('absent_average_return') or 0.0)}** when absent.
- **Strongest caution:** {label(caution)} on {caution.get('direction')} trades is **{int(caution.get('wins') or 0)}W/{int(caution.get('losses') or 0)}L** across **{int(caution.get('trades') or 0)} trades**, averaging **{_currency(caution.get('average_return') or 0.0)}** versus **{_currency(caution.get('absent_average_return') or 0.0)}** when absent.
- **History and decision:** Indicator labels cover **{covered}/{len(trades)}** canonical broker-backed trades through **{trading_date}**. These are all-time directional comparisons refreshed after every session; correlated indicators and small absent cohorts remain contrary evidence, so weights stay unchanged until governed samples support human review."""


def _replace_h3_section(markdown: str, title: str, replacement: str) -> str:
    pattern = re.compile(
        rf"(?ms)^###\s+{re.escape(title)}\s*$.*?(?=^###\s+|^##\s+|\Z)"
    )
    return pattern.sub(replacement.rstrip() + "\n\n", markdown, count=1)


def _compact_missed_opportunity_sections(markdown: str, trading_date: str) -> str:
    markdown = re.sub(
        r"(?ms)^##\s+Missed Opportunities — Shadow Review\s*$.*?"
        r"(?=^###\s+Daily Scorecard\s*$)",
        "",
        markdown,
        count=1,
    )
    payload = _load_json(
        REPORT_DIR / f"missed_opportunities_shadow_{trading_date}.json"
    )
    summary = payload.get("summary") or {}
    missed = [
        row for row in (payload.get("missed_opportunities") or [])
        if isinstance(row, dict)
    ]
    patterns = [
        row for row in (payload.get("today_pattern_summary") or [])
        if isinstance(row, dict)
    ]
    blockers = [
        row for row in (payload.get("today_blocker_summary") or [])
        if isinstance(row, dict)
    ]
    if missed:
        missed_count = int(summary.get("canonical_missed_opportunities") or len(missed))
        unseen = int(summary.get("unseen_market_moves") or 0)
        near = int(summary.get("near_miss_opportunities") or 0)
        coverage = float(summary.get("option_evidence_coverage") or 0.0)
        top_pattern = max(
            patterns,
            key=lambda row: (
                int(row.get("missed_profitable") or 0),
                int(row.get("canonical_episodes") or 0),
            ),
            default={},
        )
        pattern_text = (
            f"The largest repeatable cluster was {top_pattern.get('direction', 'unknown')} "
            f"{str(top_pattern.get('phase') or 'unknown').replace('_', ' ').title()} "
            f"blocked by {top_pattern.get('rejection_reason', 'an unclassified gate')}: "
            f"{int(top_pattern.get('missed_profitable') or 0)} misses in "
            f"{int(top_pattern.get('canonical_episodes') or 0)} canonical episodes."
        )
        canonical_summary = f"""### Canonical Missed Opportunities

- **What we missed:** **{missed_count}** executable +6%-before-stop opportunities: **{unseen}** were moves the live setup did not recognize and **{near}** were near-miss rejections.
- **Where it concentrated:** {pattern_text}
- **What we learned:** Improve earlier move recognition and candidate coverage before weakening gates. Executable evidence coverage was **{coverage:.1%}**, below the governed 80% threshold, and the leading blocker patterns produced mixed outcomes."""
        markdown = _replace_h3_section(
            markdown,
            "Canonical Missed Opportunities",
            canonical_summary,
        )

    if blockers:
        primary = max(
            blockers,
            key=lambda row: int(row.get("sole_blocker_episodes") or 0),
        )
        overlap = max(
            (
                row for row in blockers
                if int(row.get("canonical_episodes") or 0)
                > int(row.get("sole_blocker_episodes") or 0)
            ),
            key=lambda row: int(row.get("canonical_episodes") or 0),
            default={},
        )
        blocker_summary = f"""### Blocker Usefulness

- **Most measurable blocker:** {primary.get('blocker_code', 'Unknown')} was the sole blocker in **{int(primary.get('sole_blocker_episodes') or 0)}** episodes; it missed **{int(primary.get('missed_profitable') or 0)}** profitable moves and protected against **{int(primary.get('losses_avoided') or 0)}** losing moves.
- **Overlap warning:** {overlap.get('blocker_code', 'Overlapping gates')} appeared in **{int(overlap.get('canonical_episodes') or 0)}** episodes but was the sole blocker only **{int(overlap.get('sole_blocker_episodes') or 0)}** time(s), so it cannot receive causal credit.
- **Decision:** Keep blocker logic unchanged. Continue collecting executable outcomes until each proposed change has at least 20 canonical episodes and 80% coverage."""
        markdown = _replace_h3_section(
            markdown,
            "Blocker Usefulness",
            blocker_summary,
        )
    markdown = markdown.replace(
        "### Daily Scorecard",
        "## Daily Scorecard",
        1,
    )
    canonical_match = re.search(
        r"(?ms)^###\s+Canonical Missed Opportunities\s*$.*?"
        r"(?=^###\s+|^##\s+|\Z)",
        markdown,
    )
    blocker_match = re.search(
        r"(?ms)^###\s+Blocker Usefulness\s*$.*?"
        r"(?=^###\s+|^##\s+|\Z)",
        markdown,
    )
    matched = [match for match in (canonical_match, blocker_match) if match]
    if matched:
        combined_parts = [
            re.sub(r"^###\s+.+?\n+", "", match.group(0).strip())
            for match in matched
        ]
        insert_at = min(match.start() for match in matched)
        for match in sorted(matched, key=lambda item: item.start(), reverse=True):
            markdown = markdown[:match.start()] + markdown[match.end():]
        combined = (
            "## Missed Opportunities & Block Usefulness\n\n"
            + "\n\n".join(part for part in combined_parts if part)
            + "\n\n"
        )
        markdown = markdown[:insert_at] + combined + markdown[insert_at:]
    return markdown


def _compact_operational_sections(
    markdown: str,
    *,
    trading_date: str | None = None,
) -> str:
    """Create concise email-only control summaries from the full worksheets."""
    direction = (
        _all_time_direction_breakdown(trading_date)
        if trading_date
        else None
    )
    if direction:
        indicator = _indicator_usefulness_summary(trading_date) if trading_date else None
        replacement = direction
        if indicator:
            replacement += "\n\n" + indicator
        markdown = _replace_h2_section(
            markdown,
            "Direction Breakdown",
            replacement,
        )
    if trading_date:
        markdown = _compact_missed_opportunity_sections(markdown, trading_date)
    startup_title = "Startup Guard — Daily Assessment"
    startup_match = re.search(
        rf"(?ms)^##\s+{re.escape(startup_title)}\s*$.*?(?=^##\s+|\Z)",
        markdown,
    )
    if startup_match:
        section = startup_match.group(0)
        decision = _section_value(section, "Today’s recommendation").replace("_", " ")
        startup = f"""## Startup Guard

- **Setting:** {_section_value(section, "Current setting")}.
- **Decision:** {decision}.
- **Today:** {_section_value(section, "Qualified candidates blocked today")} candidates blocked; {_section_value(section, "Prompt same-contract opportunities preserved")} prompt follow-ups preserved; {_section_value(section, "Executable outcome coverage")} executable coverage.
- **Why:** {_section_value(section, "Rationale")}.
- **Next:** Keep the live guard unchanged unless human review approves a change after {_section_value(section, "Change gate")}."""
        markdown = _replace_h2_section(markdown, startup_title, startup)

    cooling_title = "Cooling Period — Daily Assessment"
    cooling_match = re.search(
        rf"(?ms)^##\s+{re.escape(cooling_title)}\s*$.*?(?=^##\s+|\Z)",
        markdown,
    )
    if cooling_match:
        section = cooling_match.group(0)
        decision = _section_value(section, "Today’s recommendation").replace("_", " ")
        harmful_reentries = _section_value(section, "Harmful uncooled re-entries")
        cooling = f"""## Cooling Period

- **Setting:** {_section_value(section, "Current behavior")}.
- **Decision:** {decision}.
- **Today:** {_section_value(section, "Cooling blocks observed today")} signals blocked; {_section_value(section, "Profitable opportunities blocked").split(';')[0]} profitable opportunities blocked; {harmful_reentries} harmful uncooled re-entry; {_section_value(section, "Executable blocked-signal coverage")} executable coverage.
- **Why:** {_section_value(section, "Rationale")}.
- **Next:** Ensure cooling arms reliably after every confirmed exit; do not change its duration unless human review approves a change after {_section_value(section, "Change gate")}."""
        markdown = _replace_h2_section(markdown, cooling_title, cooling)

    stop_title = "Protective Stop and Ratchet Reliability"
    stop_match = re.search(
        rf"(?ms)^##\s+{re.escape(stop_title)}\s*$.*?(?=^##\s+|\Z)",
        markdown,
    )
    if stop_match:
        section = stop_match.group(0)
        stop_activity = re.sub(
            r"^(\*\*\d+\*\*);\s*broker stop submissions:\s*(\*\*\d+\*\*)$",
            r"\1 trades; \2 broker stop submissions",
            _section_value(section, "Trades observed"),
        )
        stop_reliability = re.sub(
            r"^(\*\*\d+\*\*);\s*rejected replacements:\s*(\*\*\d+\*\*);\s*identity recoveries:\s*(\*\*\d+\*\*)$",
            r"\1 ratchet failures; \2 rejected replacements; \3 identity recoveries",
            _section_value(section, "Ratchet failures"),
        )
        stop = f"""## Protective Stops

- **Status:** Repair required before considering another stop-policy change.
- **Today:** {stop_activity}.
- **Reliability:** {stop_reliability}.
- **Trail rule:** The 4% tier remains a 1%-behind-high synthetic trail armed after +4%.
- **Next:** Eliminate rejected replacements, submission failures, and protection gaps; require at least 95% broker verification before human review of any policy change."""
        markdown = _replace_h2_section(markdown, stop_title, stop)
    return markdown


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
    email_markdown = _normalize_dollar_markdown(
        _email_markdown(markdown, trading_date=trading_date)
    )
    email_summary = _build_email_summary(trading_date)
    if not dry_run:
        reconciliation_data = _reconciliation(trading_date)
        if not _reconciliation_is_sendable(reconciliation_data):
            raise RuntimeError(
                "Daily review email withheld: exact broker trade-count/P&L parity "
                "and zero pending outbox entries are required"
            )

    trade_rows = _snapshot_trade_rows(trading_date)
    tracker = _all_time_trade_tracker(trading_date)
    preview_html = markdown_to_email_html(
        email_markdown,
        trading_date,
        summary=email_summary,
        trades=trade_rows,
        tracker=tracker,
    )
    html_path.write_text(preview_html, encoding="utf-8")
    if dry_run:
        return html_path

    html_body = markdown_to_email_html(
        email_markdown,
        trading_date,
        summary=email_summary,
        trades=trade_rows,
        tracker=tracker,
    )

    state = _load_json(STATE_PATH)
    digest = hashlib.sha256(
        email_markdown.encode("utf-8")
        + json.dumps(trade_rows, sort_keys=True).encode("utf-8")
        + json.dumps(tracker, sort_keys=True).encode("utf-8")
    ).hexdigest()
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
            "inline_images_sent": 0,
        },
    )
    DELIVERY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DELIVERY_LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(
            f"{sent_at} | send_success | date={trading_date}"
            f" | recipient={to_email} | reconciliation={reconciliation}"
            " | attachments=0 | inline_images=0\n"
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
