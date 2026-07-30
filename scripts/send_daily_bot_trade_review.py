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
import statistics
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
    trades = _all_time_study_trades(trading_date)
    wins = sum(float(row.get("pnl_dollars") or 0.0) > 0 for row in trades)
    pnl = sum(float(row.get("pnl_dollars") or 0.0) for row in trades)
    shadow = _load_json(
        REPORT_DIR / f"day_trade_spy_shadow_{trading_date}.json"
    )
    rolling = shadow.get("rolling") or {}
    shadow_sample = int(rolling.get("valid_sample_size") or 0)
    entry_quality = _load_json(
        REPORT_DIR / f"entry_quality_shadow_{trading_date}.json"
    )
    telemetry = entry_quality.get("telemetry_quality") or {}
    complete = int(telemetry.get("rolling_complete") or 0)
    lessons = [
        {
            "title": "All-Time Performance",
            "signal": (
                f"{wins} wins in {len(trades)} canonical broker-backed trades "
                f"({wins / len(trades):.1%}) with {_currency(pnl)} net P&L"
                if trades else "No canonical broker-backed trade history is available"
            ),
        },
        {
            "title": "Five-Rule Research",
            "signal": (
                f"the Day Trade SPY suite has {shadow_sample}/50 valid all-time "
                "trades; it is not yet actionable"
            ),
        },
        {
            "title": "Evidence Quality",
            "signal": (
                f"Phase/CQ/MAS/ABS/CONF are complete on {complete}/{len(trades)} "
                "all-time trades; incomplete historical telemetry limits conclusions"
            ),
        },
    ]
    changes = [
        "Make no strategy or indicator-weight change from a single day.",
        "Treat 20 comparable trades as the earliest directional read and prefer 50 before action.",
        "Continue automatic shadow collection until reconciliation, coverage, representation, and human-review gates pass.",
    ]
    return {
        "lessons": lessons,
        "changes": changes,
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
        "<li style=\"margin:1px 0;color:#34445f;font-size:12px;\">"
        f"<strong>{_inline(str(row.get('title') or 'Learning'))}:</strong> "
        f"{_inline(_normalize_dollar_markdown(str(row.get('signal') or '')))}.</li>"
        for row in summary["lessons"]
    )
    changes = "".join(
        "<li style=\"margin:1px 0;color:#34445f;font-size:12px;\">"
        f"{_inline(row)}</li>"
        for row in summary["changes"]
    )
    return f"""
<div style="border:1px solid #d7e2f0;border-radius:9px;overflow:hidden;background:#f9fbfe;margin:0 0 4px;">
  <div style="padding:4px 7px;background:#eaf1fb;color:#173763;font-size:14px;font-weight:750;">Summary</div>
  <div style="padding:4px 7px 5px;">
    <div style="font-size:14px;font-weight:750;color:#173763;">What We Learned</div>
    <ul style="margin:0 0 3px;padding-left:16px;">{lessons}</ul>
    <div style="font-size:14px;font-weight:750;color:#173763;">Changes We Need To Make</div>
    <ul style="margin:1px 0 0;padding-left:17px;">{changes}</ul>
  </div>
</div>
"""


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
        "<th style=\"padding:3px 3px;"
        "text-align:center;vertical-align:middle;background:#edf3fb;"
        "border-bottom:2px solid #cbd8ea;font-size:14px;letter-spacing:.25px;"
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
                "<td style=\"padding:3px 3px;"
                "text-align:center;vertical-align:middle;"
                f"border-bottom:1px solid #e6ebf2;font-size:12px;color:{color};"
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
        "<div style=\"margin:0 0 4px;border:1px solid #d7e2f0;"
        "border-radius:12px;overflow:hidden;\">"
        "<div style=\"padding:4px 6px;background:#173763;color:#ffffff;"
        "font-size:14px;font-weight:750;text-align:center;\">Today's Trades</div>"
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
                f"<th style=\"padding:3px 4px;text-align:left;border-bottom:2px solid #cbd8ea;"
                f"font-size:14px;color:#24487f;\">{_inline(cell)}</th>"
                for cell in headers
            )
            body = "".join(
                "<tr>" + "".join(
                    f"<td style=\"padding:3px 4px;border-bottom:1px solid #e5ebf4;"
                    f"font-size:12px;color:#3d4960;\">{_inline(cell)}</td>"
                    for cell in row
                ) + "</tr>"
                for row in rows
            )
            blocks.append(
                "<div style=\"overflow-x:auto;margin:3px 0 5px;\">"
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
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>McLeod Alpha Daily Bot Trade Review</title>
</head>
<body style="margin:0!important;padding:0!important;background:#f3f6fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0;padding:0;background:#f3f6fb;border-collapse:collapse;">
    <tr><td align="center" style="margin:0;padding:0 4px 4px;">
      <table role="presentation" width="720" cellspacing="0" cellpadding="0" style="width:100%;max-width:720px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 8px 30px rgba(31,49,82,.10);">
        <tr><td class="review" style="margin:0;padding:0 12px 7px;line-height:1.27;">
          <style>
            .review h1 {{ display:none; }}
            .review h2 {{ color:#173763;font-size:14px;margin:6px 0 3px;background:linear-gradient(90deg,#edf4ff,#f8fbff);border-left:3px solid #4f7ec8;padding:4px 6px;border-radius:6px; }}
            .review h3 {{ color:#172f58;font-size:14px;margin:5px 0 2px; }}
            .review p {{ margin:2px 0;color:#3d4960;font-size:12px; }}
            .review ul {{ margin:2px 0 4px;padding:4px 6px 4px 21px;background:#fbfcff;border:1px solid #e4ebf5;border-radius:6px; }}
            .review li {{ margin:1px 0;color:#3d4960;font-size:12px; }}
            .review strong {{ color:#172033; }}
            .review code {{ background:#eef3fa;border-radius:5px;padding:2px 5px;font-size:12px; }}
            .review .step {{ background:#f5f8fc;border-left:3px solid #4f7ec8;padding:3px 5px;border-radius:4px; }}
            .review tbody tr:nth-child(even) td {{ background:#f4f7fb; }}
            @media only screen and (max-width:600px) {{
              .review {{ padding-left:16px !important;padding-right:16px !important; }}
              .review h2,.review h3 {{ font-size:14px; }}
              .review p,.review li {{ font-size:12px; }}
            }}
          </style>
          {trades_table}
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
        subject = f"Made ${abs(pnl):,.2f} Today On {trades} Trades"
    elif pnl < 0:
        subject = f"Lost ${abs(pnl):,.2f} Today On {trades} Trades"
    else:
        subject = f"Broke Even Today On {trades} Trades"
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
    result = "\n".join(cleaned).strip() + "\n"
    return _reorder_h2_sections(
        result,
        [
            "Daily Scorecard",
            "Bot & Cockpit Failures — Today",
            "Protective Stops -",
            "Execution & Reliability — All Time",
            "Direction Breakdown — All Time",
            "Indicator Results — All Time",
            "Day Trade SPY Review — All Time",
            "Missed Opportunities — All Time",
            "Block Usefulness — All Time",
            "Startup Guard — All Time",
            "Cooling Period — All Time",
        ],
    )


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
    """Summarize accumulated McLeod Alpha SPY day-trading indicator evidence."""
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
    entry_quality = _load_json(
        REPORT_DIR / f"entry_quality_shadow_{trading_date}.json"
    )
    scores = (
        entry_quality.get("checklist_score_study", {})
        .get("historical", {})
        .get("overall", {})
    )
    score_parts = []
    for score in ("5", "6", "7"):
        row = scores.get(score) or {}
        count = int(row.get("trades") or 0)
        if count:
            score_parts.append(
                f"{score}/5: {float(row.get('win_rate') or 0.0):.1%} wins and "
                f"{_currency(row.get('average_pnl_dollars') or 0.0)} average "
                f"across {count} trades"
            )
    call_seven = (
        entry_quality.get("checklist_score_study", {})
        .get("historical", {})
        .get("by_direction_and_phase", {})
        .get("CALL", {})
        .get("all_phases", {})
        .get("7", {})
    )
    put_seven = (
        entry_quality.get("checklist_score_study", {})
        .get("historical", {})
        .get("by_direction_and_phase", {})
        .get("PUT", {})
        .get("all_phases", {})
        .get("7", {})
    )

    def label(row: dict[str, Any]) -> str:
        return str(row.get("indicator") or "Unknown").replace("_", " ").title()

    checklist_line = (
        "- **Checklist results:** " + "; ".join(score_parts) + "."
        if score_parts else ""
    )
    confounding_line = ""
    if call_seven and put_seven:
        confounding_line = (
            "- **Important contrary evidence:** 7/5 CALLs averaged "
            f"**{_currency(call_seven.get('average_pnl_dollars') or 0.0)}** across "
            f"**{int(call_seven.get('trades') or 0)} trades**, while 7/5 PUTs averaged "
            f"**{_currency(put_seven.get('average_pnl_dollars') or 0.0)}** across "
            f"**{int(put_seven.get('trades') or 0)} trades**. Direction and phase "
            "are confounding the raw score comparison."
        )

    return f"""## Indicator Results — All Time

- **Most promising:** {label(helpful)} on {helpful.get('direction')} trades is **{int(helpful.get('wins') or 0)}W/{int(helpful.get('losses') or 0)}L** across **{int(helpful.get('trades') or 0)} trades**, averaging **{_currency(helpful.get('average_return') or 0.0)}** versus **{_currency(helpful.get('absent_average_return') or 0.0)}** when absent.
- **Strongest caution:** {label(caution)} on {caution.get('direction')} trades is **{int(caution.get('wins') or 0)}W/{int(caution.get('losses') or 0)}L** across **{int(caution.get('trades') or 0)} trades**, averaging **{_currency(caution.get('average_return') or 0.0)}** versus **{_currency(caution.get('absent_average_return') or 0.0)}** when absent.
{checklist_line}
{confounding_line}
- **History and decision:** Indicator labels cover **{covered}/{len(trades)}** canonical broker-backed trades through **{trading_date}**. No comparison is actionable below 20 comparable trades, and 50 is preferred before a live change. Correlated indicators, direction, phase, and small absent cohorts remain contrary evidence, so weights stay unchanged pending human review."""


def _day_trade_spy_all_time_summary(trading_date: str) -> str | None:
    payload = _load_json(
        REPORT_DIR / f"day_trade_spy_shadow_{trading_date}.json"
    )
    rolling = payload.get("rolling") or {}
    summaries = rolling.get("test_summary") or {}
    if not summaries:
        return None
    labels = {
        "accepted_break": "Accepted Break",
        "structural_room_execution": "Structural Room & Execution",
        "opening_vs_later_entry": "Opening vs. Later Entry",
        "congestion_reentry": "Congestion & Re-entry",
        "premise_reset_no_repair": "Premise Reset / No Repair",
    }
    rows = []
    for key, label in labels.items():
        groups = summaries.get(key) or {}
        parts = []
        for verdict in ("ADMIT", "REJECT", "DELAY", "TRACK"):
            result = groups.get(verdict) or {}
            count = int(result.get("trades") or 0)
            if not count:
                continue
            wins = int(result.get("wins") or 0)
            parts.append(
                f"{verdict.title()} {wins}/{count} wins, "
                f"{_currency(result.get('pnl_dollars') or 0.0)}"
            )
        rows.append(f"| {label} | {'; '.join(parts) or 'No valid outcomes yet'} |")
    sample = int(rolling.get("valid_sample_size") or 0)
    first_passage = int(rolling.get("known_first_passage") or 0)
    coverage = first_passage / sample if sample else 0.0
    phases = rolling.get("session_phase_counts") or {}
    phase_text = ", ".join(
        f"{str(name).replace('_', ' ').title()} {int(count)}"
        for name, count in phases.items()
    ) or "none"
    return f"""## Day Trade SPY Review — All Time

| Rule | All-Time Result |
| --- | --- |
{chr(10).join(rows)}

- **Evidence:** **{sample}/50** valid trades; **{coverage:.1%}** first-passage coverage; phases: {phase_text}.
- **Decision gate:** Below 20 trades is observation only. Twenty permits an early directional read; **50 valid trades is preferred before any actionable recommendation**, with at least 10 per observed phase, exact reconciliation, at least 80% first-passage coverage, and human review.
- **Current decision:** **COLLECT MORE DATA**. The five rules remain research-only and cannot change entries, exits, sizing, stops, targets, or order behavior automatically."""


def _runtime_failure_counts(trading_date: str) -> dict[str, int]:
    path = ROOT / "data" / "reports" / "runtime_events.jsonl"
    categories = {
        "Manual Exit Failure": "manual exit error",
        "Protective Stop Submission Failure": "protective stop submission failed",
        "Cockpit Unavailable": "cockpit unavailable",
        "Cockpit Port Failure": "cockpit port not listening",
        "Bot Restart Failure": "bot restart api request failed",
        "Restart Budget Exhausted": "restart budget exhausted",
        "Runtime Parity Mismatch": "parity_state='mismatch'",
    }
    counts = {label: 0 for label in categories}
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return counts
    for line in lines:
        try:
            row = json.loads(line)
            observed = datetime.fromisoformat(str(row.get("ts") or ""))
        except (ValueError, TypeError):
            continue
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=EASTERN_TZ)
        if observed.astimezone(EASTERN_TZ).date().isoformat() != trading_date:
            continue
        text = " ".join(
            str(row.get(key) or "") for key in ("event_type", "message", "details")
        ).lower()
        for label, needle in categories.items():
            if needle in text:
                counts[label] += 1
    return counts


def _bot_cockpit_failures_summary(trading_date: str) -> str:
    stop = _load_json(
        REPORT_DIR / f"stop_execution_review_{trading_date}.json"
    ).get("summary") or {}
    cooling = _load_json(
        REPORT_DIR / f"cooling_period_review_{trading_date}.json"
    ).get("summary") or {}
    entry_quality = _load_json(
        REPORT_DIR / f"entry_quality_shadow_{trading_date}.json"
    )
    runtime = _runtime_failure_counts(trading_date)
    failures = [
        f"**Protective-stop handling:** {int(stop.get('ratchet_failures') or 0)} ratchet failures, "
        f"{int(stop.get('protective_submission_failures') or 0)} protective submissions failed, "
        f"{int(stop.get('replacement_rejections') or 0)} replacement rejections, and "
        f"{int(stop.get('protective_stop_missing_decisions') or 0)} missing-protection decisions.",
    ]
    harmful = int(cooling.get("harmful_uncooled_reentries") or 0)
    if harmful:
        failures.append(
            f"**Cooling failed to arm:** {harmful} harmful uncooled same-contract re-entry "
            f"cost {_currency(cooling.get('harmful_uncooled_reentry_pnl') or 0.0)}."
        )
    adverse = float(stop.get("entry_adverse_slippage_dollars_per_contract") or 0.0)
    shortfall = float(stop.get("exit_execution_shortfall_dollars_per_contract") or 0.0)
    if adverse or shortfall:
        failures.append(
            f"**Execution quality:** {_currency(adverse)} adverse entry slippage and "
            f"{_currency(shortfall)} exit shortfall per contract across covered trades."
        )
    audited = sum(
        str(row.get("source") or "") == "broker_duplicate_audit"
        for row in (entry_quality.get("today_trades") or [])
        if isinstance(row, dict)
    )
    if audited:
        failures.append(
            f"**Trade-log integrity:** {audited} duplicate canonical trade required "
            "broker-first audit and repair before the email could be released."
        )
    for label, count in runtime.items():
        if count:
            failures.append(f"**{label}:** {count} recorded occurrence(s).")
    if not failures:
        failures.append("**No recorded failures:** Structured daily telemetry found no bot or Cockpit failure.")
    return (
        "## Bot & Cockpit Failures — Today\n\n"
        + "\n".join(f"- {row}" for row in failures)
    )


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
    patterns = [
        row for row in (payload.get("pattern_summary") or [])
        if isinstance(row, dict)
    ]
    blockers = [
        row for row in (payload.get("blocker_summary") or [])
        if isinstance(row, dict)
    ]
    if patterns:
        missed_count = sum(int(row.get("missed_profitable") or 0) for row in patterns)
        episodes = int(payload.get("rolling_canonical_episodes") or 0)
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
        canonical_summary = f"""## Missed Opportunities — All Time

- **What we missed:** **{missed_count}** profitable misses across **{episodes}** decisive canonical rejected-candidate episodes accumulated through **{trading_date}**.
- **Where it concentrated:** {pattern_text}
- **What we learned:** Improve earlier move recognition and evidence coverage before weakening gates. The latest session’s executable evidence coverage was **{coverage:.1%}**, below the governed 80% threshold, and the leading all-time blocker patterns produced mixed outcomes."""
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
        blocker_summary = f"""## Block Usefulness — All Time

- **Most measurable blocker:** {primary.get('blocker_code', 'Unknown')} was the sole blocker in **{int(primary.get('sole_blocker_episodes') or 0)}** episodes; it missed **{int(primary.get('missed_profitable') or 0)}** profitable moves and protected against **{int(primary.get('losses_avoided') or 0)}** losing moves.
- **Overlap warning:** {overlap.get('blocker_code', 'Overlapping gates')} appeared in **{int(overlap.get('canonical_episodes') or 0)}** episodes but was the sole blocker only **{int(overlap.get('sole_blocker_episodes') or 0)}** time(s), so it cannot receive causal credit.
- **Decision:** Keep blocker logic unchanged. Below 20 comparable episodes is observation only; prefer 50 before action, with at least 80% executable coverage and human review."""
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
    return markdown


def _daily_report_history(prefix: str, trading_date: str) -> list[dict[str, Any]]:
    payloads = []
    for path in sorted(REPORT_DIR.glob(f"{prefix}_*.json")):
        report_date = path.stem.removeprefix(f"{prefix}_")
        if report_date <= trading_date:
            payload = _load_json(path)
            if payload:
                payloads.append(payload)
    return payloads


def _all_time_control_summary(prefix: str, trading_date: str) -> dict[str, Any]:
    payloads = _daily_report_history(prefix, trading_date)
    totals: dict[str, float] = {}
    for payload in payloads:
        for key, value in (payload.get("summary") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0.0) + float(value)
    return {
        "payloads": payloads,
        "totals": totals,
        "latest": payloads[-1] if payloads else {},
    }


def _execution_reliability_summary(trading_date: str) -> str:
    reports = _daily_report_history("stop_execution_review", trading_date)
    trades = [
        trade
        for report in reports
        for trade in (report.get("trades") or [])
        if isinstance(trade, dict)
    ]
    healthy = sum(str(row.get("status") or "") == "HEALTHY" for row in trades)
    reliability = 100.0 * healthy / len(trades) if trades else 0.0
    entry_slippage = []
    exit_shortfall = []
    cycle_medians = []
    estimated_drag = 0.0
    for trade in trades:
        execution = trade.get("execution_quality") or {}
        for values, key in (
            (entry_slippage, "entry_adverse_slippage_dollars"),
            (exit_shortfall, "exit_execution_shortfall_dollars"),
            (cycle_medians, "management_cycle_median_seconds"),
        ):
            value = execution.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        drag = execution.get("estimated_round_trip_execution_drag_dollars")
        if isinstance(drag, (int, float)):
            estimated_drag += float(drag)
    totals = {
        key: sum(int((report.get("summary") or {}).get(key) or 0) for report in reports)
        for key in (
            "ratchet_failures",
            "protective_submission_failures",
            "replacement_rejections",
            "protective_stop_missing_decisions",
        )
    }

    def average(values: list[float]) -> str:
        return _currency(sum(values) / len(values)) if values else "N/A"

    cycle_text = (
        f"{statistics.median(cycle_medians):.2f}s median; "
        f"{max(cycle_medians):.2f}s maximum"
        if cycle_medians else "N/A"
    )
    critical_total = sum(totals.values())
    status = "HEALTHY" if trades and reliability == 100.0 and critical_total == 0 else (
        "RECURRING — REPAIR REQUIRED" if len(reports) > 1 and critical_total else
        "OPEN — REPAIR REQUIRED" if critical_total else "COLLECTING"
    )
    return f"""## Execution & Reliability — All Time

- **Reliability:** **{reliability:.1f}%** — {healthy}/{len(trades)} broker-backed trades had no recorded critical protection defect across {len(reports)} reviewed session(s).
- **Execution:** Average adverse entry slippage **{average(entry_slippage)}** per contract; average exit shortfall **{average(exit_shortfall)}** per contract; estimated covered round-trip drag **{_currency(estimated_drag)}**.
- **Speed:** Management-cycle performance was **{cycle_text}**.
- **Recurring defects:** **{totals['ratchet_failures']}** ratchet failures, **{totals['protective_submission_failures']}** failed protective submissions, **{totals['replacement_rejections']}** rejected replacements, and **{totals['protective_stop_missing_decisions']}** missing-protection decisions.
- **Repair status:** **{status}**."""


def _reorder_h2_sections(markdown: str, ordered_titles: list[str]) -> str:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown))
    if not matches:
        return markdown
    prefix = markdown[:matches[0].start()].strip()
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[match.start():end].strip()))
    selected: set[str] = set()
    arranged = []
    for requested in ordered_titles:
        for title, section in sections:
            if title == requested or (
                requested.endswith("-") and title.startswith(requested)
            ):
                arranged.append(section)
                selected.add(title)
    arranged.extend(
        section for title, section in sections if title not in selected
    )
    return "\n\n".join(([prefix] if prefix else []) + arranged).strip() + "\n"


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
        day_trade_spy = _day_trade_spy_all_time_summary(trading_date)
        if day_trade_spy:
            markdown = _replace_h2_section(
                markdown,
                "Day Trade SPY Five-Test Shadow Review",
                day_trade_spy,
            )
        markdown = _compact_missed_opportunity_sections(markdown, trading_date)
    startup_title = "Startup Guard — Daily Assessment"
    startup_match = re.search(
        rf"(?ms)^##\s+{re.escape(startup_title)}\s*$.*?(?=^##\s+|\Z)",
        markdown,
    )
    if startup_match:
        history = _all_time_control_summary("startup_guard_review", trading_date or "")
        totals = history["totals"]
        latest = history["latest"]
        blocked = int(totals.get("blocked_candidates", 0))
        decisive = int(totals.get("decisive_option_outcomes", 0))
        coverage = decisive / blocked if blocked else 0.0
        startup = f"""## Startup Guard — All Time

- **Setting:** Block the first **{int(latest.get('current_setting') or 1)}** otherwise-qualified signal after startup.
- **Evidence:** **{blocked}** candidates blocked across **{len(history['payloads'])}** daily reviews; **{decisive}** had decisive executable outcomes ({coverage:.1%} coverage), with **{int(totals.get('profitable_candidates_blocked', 0))}** profitable moves blocked and **{int(totals.get('opportunities_preserved_by_prompt_followup', 0))}** opportunities preserved by prompt follow-ups.
- **Decision:** Keep at one. Below 20 decisive episodes is observation only; prefer 50 before action, with at least 80% executable coverage and human review."""
        markdown = _replace_h2_section(markdown, startup_title, startup)

    cooling_title = "Cooling Period — Daily Assessment"
    cooling_match = re.search(
        rf"(?ms)^##\s+{re.escape(cooling_title)}\s*$.*?(?=^##\s+|\Z)",
        markdown,
    )
    if cooling_match:
        history = _all_time_control_summary("cooling_period_review", trading_date or "")
        totals = history["totals"]
        blocked = int(totals.get("cooling_blocks", 0))
        decisive = int(totals.get("decisive_option_outcomes", 0))
        coverage = decisive / blocked if blocked else 0.0
        cooling = f"""## Cooling Period — All Time

- **Setting:** Skip the next **one otherwise-qualified signal** after every confirmed exit.
- **Evidence:** **{blocked}** cooling blocks across **{len(history['payloads'])}** daily reviews; **{decisive}** had decisive executable outcomes ({coverage:.1%} coverage), including **{int(totals.get('profitable_opportunities_blocked', 0))}** profitable moves blocked and **{int(totals.get('harmful_uncooled_reentries', 0))}** harmful uncooled same-contract re-entry worth **{_currency(totals.get('harmful_uncooled_reentry_pnl', 0.0))}**.
- **Decision:** Keep one signal and ensure it arms after every confirmed exit. An arming failure is not evidence that duration is too short. Below 20 decisive blocks is observation only; prefer 50 before action, with 80% coverage and human review."""
        markdown = _replace_h2_section(markdown, cooling_title, cooling)

    stop_title = "Protective Stop and Ratchet Reliability"
    stop_match = re.search(
        rf"(?ms)^##\s+{re.escape(stop_title)}\s*$.*?(?=^##\s+|\Z)",
        markdown,
    )
    if stop_match:
        section = stop_match.group(0)
        stop_payload = _load_json(
            REPORT_DIR / f"stop_execution_review_{trading_date}.json"
        ) if trading_date else {}
        stop_trades = [
            row for row in (stop_payload.get("trades") or [])
            if isinstance(row, dict)
        ]
        healthy_trades = sum(
            str(row.get("status") or "") == "HEALTHY" for row in stop_trades
        )
        reliability = (
            100.0 * healthy_trades / len(stop_trades) if stop_trades else 0.0
        )
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
        stop = f"""## Protective Stops - {reliability:.1f}%

- **Status:** Repair required before considering another stop-policy change.
- **Today:** {stop_activity}.
- **Reliability:** **{healthy_trades}/{len(stop_trades)} trades** had no recorded critical protection defect. {stop_reliability}.
- **Trail rule:** The 4% tier remains a 1%-behind-high synthetic trail armed after +4%.
- **Next:** Eliminate rejected replacements, submission failures, and protection gaps. Statistical policy changes require at least 20 broker-confirmed trades, preferably 50, at least 95% broker verification, and human review."""
        markdown = _replace_h2_section(markdown, stop_title, stop)
    if trading_date:
        markdown += "\n\n" + _bot_cockpit_failures_summary(trading_date) + "\n"
        markdown += "\n\n" + _execution_reliability_summary(trading_date) + "\n"
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
    preview_html = markdown_to_email_html(
        email_markdown,
        trading_date,
        summary=email_summary,
        trades=trade_rows,
    )
    html_path.write_text(preview_html, encoding="utf-8")
    if dry_run:
        return html_path

    html_body = markdown_to_email_html(
        email_markdown,
        trading_date,
        summary=email_summary,
        trades=trade_rows,
    )

    state = _load_json(STATE_PATH)
    digest = hashlib.sha256(
        email_markdown.encode("utf-8")
        + json.dumps(trade_rows, sort_keys=True).encode("utf-8")
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
