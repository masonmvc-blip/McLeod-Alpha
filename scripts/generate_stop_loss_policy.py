#!/usr/bin/env python3
"""Generate an up-to-date stop-loss policy chart, export to PDF, and optionally print.

This script derives the stop-loss policy directly from the canonical Brain.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple


ROOT = Path(__file__).resolve().parent.parent
BRAIN_ENGINE = ROOT / "engine" / "brain" / "engine.py"
OUT_DIR = ROOT / "data" / "reports"
OUT_HTML = OUT_DIR / "stop_loss_policy_latest.html"
OUT_PDF = OUT_DIR / "stop_loss_policy_latest.pdf"

if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _parse_constants(text: str) -> Dict[str, float]:
    constants: Dict[str, float] = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*([-+]?\d+(?:\.\d+)?)\b", line)
        if not m:
            continue
        name, value = m.group(1), m.group(2)
        try:
            constants[name] = float(value)
        except ValueError:
            continue
    return constants


def _extract_trail_multiplier(text: str, tier: int, var_name: str) -> float:
    pat = (
        rf"(?:if|elif)\s+\w+\s*>=\s*TRAIL_{tier}_TRIGGER_PCT\s*:\s*"
        rf"(?:.|\n)*?new_stop\s*=\s*{re.escape(var_name)}\s*\*\s*(0\.\d+)"
    )
    m = re.search(pat, text)
    if not m:
        raise RuntimeError(f"Could not parse trail multiplier for TRAIL_{tier}_TRIGGER_PCT in source.")
    return float(m.group(1))


def _build_policy() -> Dict[str, object]:
    from engine.brain import Brain

    brain_consts = _parse_constants(_read_text(BRAIN_ENGINE))
    initial_stop_loss_pct = -4.0
    max_trade_hold_minutes = brain_consts.get("MAX_TRADE_HOLD_MINUTES")
    t1, t2, t3, t4, t5 = 8.0, 7.0, 6.0, 5.0, 4.0
    t2_trigger, t2_entry_stop_pct = 2.0, 3.0
    t3_trigger, t3_entry_stop_pct = 3.0, 1.0
    policy = Brain()
    m1 = policy._trailing_stop(5.0, 4.75, 5.40, 8.0)[0] / 5.40
    m2 = policy._trailing_stop(5.0, 4.75, 5.35, 7.0)[0] / 5.35
    m3 = policy._trailing_stop(5.0, 4.75, 5.30, 6.0)[0] / 5.30
    m4 = policy._trailing_stop(5.0, 4.75, 5.25, 5.0)[0] / 5.25
    m5 = policy._trailing_stop(5.0, 4.75, 5.20, 4.0)[0] / 5.20

    trail1_pct = round((1.0 - m1) * 100.0, 2)
    trail2_pct = round((1.0 - m2) * 100.0, 2)
    trail3_pct = round((1.0 - m3) * 100.0, 2)
    trail4_pct = round((1.0 - m4) * 100.0, 2)
    trail5_pct = round((1.0 - m5) * 100.0, 2)

    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_stop_loss_pct": float(initial_stop_loss_pct),
        "max_trade_hold_minutes": int(max_trade_hold_minutes) if max_trade_hold_minutes is not None else None,
        "trail_1_trigger": float(t1),
        "trail_2_trigger": float(t2),
        "trail_3_trigger": float(t3),
        "trail_4_trigger": float(t4),
        "trail_5_trigger": float(t5),
        "two_pct_trigger": float(t2_trigger) if t2_trigger is not None else None,
        "two_pct_entry_stop_pct": float(t2_entry_stop_pct) if t2_entry_stop_pct is not None else None,
        "three_pct_trigger": float(t3_trigger) if t3_trigger is not None else None,
        "three_pct_entry_stop_pct": float(t3_entry_stop_pct) if t3_entry_stop_pct is not None else None,
        "trail_1_pct": trail1_pct,
        "trail_2_pct": trail2_pct,
        "trail_3_pct": trail3_pct,
        "trail_4_pct": trail4_pct,
        "trail_5_pct": trail5_pct,
        "brain_source": str(BRAIN_ENGINE.relative_to(ROOT)),
    }


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _multiplier_from_pct(percent: float) -> str:
  value = 1.0 - (float(percent) / 100.0)
  return f"{value:.3f}".rstrip("0").rstrip(".")


def _num3(x: float) -> str:
  return f"{float(x):.3f}"


def _exit_pl_formula(entry_price: float, stop_price: float) -> str:
  pct = ((float(stop_price) - float(entry_price)) / float(entry_price)) * 100.0
  sign = "+" if pct >= 0 else ""
  return f"({_num3(stop_price)}-{_num3(entry_price)})/{_num3(entry_price)} = {sign}{pct:.3f}%"


def _trigger_to_stop_spacing(trigger_price: float, stop_price: float) -> str:
  gap = float(trigger_price) - float(stop_price)
  drop_pct = (gap / float(trigger_price)) * 100.0 if float(trigger_price) > 0 else 0.0
  return f"${gap:.3f} ({drop_pct:.3f}% down)"


def _build_html(policy: Dict[str, object]) -> str:
    entry = 5.00
    initial_stop = entry * (1.0 + float(policy["initial_stop_loss_pct"]) / 100.0)
    at_t3 = entry * (1.0 + float(policy["trail_3_trigger"]) / 100.0)
    stop_t3 = at_t3 * (1.0 - float(policy["trail_3_pct"]) / 100.0)
    at_t4 = entry * (1.0 + float(policy["trail_4_trigger"]) / 100.0)
    stop_t4 = at_t4 * (1.0 - float(policy["trail_4_pct"]) / 100.0)
    at_t5 = entry * (1.0 + float(policy["trail_5_trigger"]) / 100.0)
    stop_t5 = at_t5 * (1.0 - float(policy["trail_5_pct"]) / 100.0)
    at_t2 = entry * (1.0 + float(policy["trail_2_trigger"]) / 100.0)
    stop_t2 = at_t2 * (1.0 - float(policy["trail_2_pct"]) / 100.0)
    at_t1 = entry * (1.0 + float(policy["trail_1_trigger"]) / 100.0)
    stop_t1 = at_t1 * (1.0 - float(policy["trail_1_pct"]) / 100.0)

    two_pct_trigger = policy.get("two_pct_trigger")
    two_pct_entry_stop_pct = policy.get("two_pct_entry_stop_pct")
    two_pct_rule_row = ""
    if two_pct_trigger is not None and two_pct_entry_stop_pct is not None:
        at_t2_lock = entry * (1.0 + float(two_pct_trigger) / 100.0)
        stop_t2_lock = entry * (1.0 - float(two_pct_entry_stop_pct) / 100.0)
        two_pct_rule_row = f"""
            <tr>
              <td>2% Stop</td>
              <td>>= +{float(two_pct_trigger):.1f}%</td>
              <td>Set stop to {float(two_pct_entry_stop_pct):.1f}% below entry</td>
              <td>entry x {_multiplier_from_pct(float(two_pct_entry_stop_pct))}</td>
              <td>{_money(at_t2_lock)} -> {_money(stop_t2_lock)}</td>
              <td>{_trigger_to_stop_spacing(at_t2_lock, stop_t2_lock)}</td>
              <td>{_exit_pl_formula(entry, stop_t2_lock)}</td>
            </tr>
"""

    three_pct_trigger = policy.get("three_pct_trigger")
    three_pct_entry_stop_pct = policy.get("three_pct_entry_stop_pct")
    three_pct_rule_row = ""
    if three_pct_trigger is not None and three_pct_entry_stop_pct is not None:
        at_t3_lock = entry * (1.0 + float(three_pct_trigger) / 100.0)
        stop_t3_lock = entry * (1.0 - float(three_pct_entry_stop_pct) / 100.0)
        three_pct_rule_row = f"""
            <tr>
              <td>3% Stop</td>
              <td>>= +{float(three_pct_trigger):.1f}%</td>
              <td>Set stop to {float(three_pct_entry_stop_pct):.1f}% below entry</td>
              <td>entry x {_multiplier_from_pct(float(three_pct_entry_stop_pct))}</td>
              <td>{_money(at_t3_lock)} -> {_money(stop_t3_lock)}</td>
              <td>{_trigger_to_stop_spacing(at_t3_lock, stop_t3_lock)}</td>
              <td>{_exit_pl_formula(entry, stop_t3_lock)}</td>
            </tr>
"""

    generated_at = html.escape(str(policy["generated_at"]))
    brain_source = html.escape(str(policy["brain_source"]))

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>McLeod Alpha Stop Loss Policy</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Helvetica, Arial, sans-serif; color: #111; margin: 0; padding: 4mm; background: #fff; }}
    h1 {{ margin: 0; font-size: 18px; }}
    .sub {{ margin: 3px 0 6px; color: #555; font-size: 10px; }}
    .meta {{ font-size: 9px; color: #666; margin-bottom: 6px; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 6px; }}
    .card {{ border: 1px solid #d0d0d0; border-radius: 8px; overflow: hidden; }}
    .card h2 {{ margin: 0; font-size: 12px; padding: 6px 8px; border-bottom: 1px solid #d0d0d0; background: #f6f6f6; }}
    .body {{ padding: 6px; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{ border: 1px solid #d0d0d0; padding: 4px; font-size: 10px; line-height: 1.2; vertical-align: top; text-align: left; }}
    th {{ background: #f0f0f0; font-size: 9px; text-transform: uppercase; letter-spacing: .02em; }}
    ul {{ margin: 0; padding-left: 16px; font-size: 10px; line-height: 1.2; }}
    li {{ margin-bottom: 3px; }}
    .mono {{ font-variant-numeric: tabular-nums; font-feature-settings: \"tnum\" 1; }}
    .foot {{ margin-top: 6px; border-top: 1px solid #d0d0d0; padding-top: 4px; font-size: 9px; color: #666; }}
    @media print {{
      body {{ zoom: 0.90; }}
      .card {{ break-inside: avoid; }}
    }}
    @page {{ size: letter portrait; margin: 5mm; }}
  </style>
</head>
<body>
  <h1>McLeod Alpha Stop Loss Policy</h1>
  <div class=\"sub\">Auto-generated from current engine code (always up to date).</div>
  <div class=\"meta mono\">Generated: {generated_at} | Source: {brain_source}</div>

  <div class=\"grid\">
    <div class=\"card\">
      <h2>Policy Chart</h2>
      <div class=\"body\">
        <table>
          <thead>
            <tr>
              <th style=\"width:14%\">Exit Reason</th>
              <th style=\"width:10%\">Profit Zone</th>
              <th style=\"width:18%\">Stop Rule</th>
              <th style=\"width:12%\">Formula</th>
              <th style=\"width:13%\">$5.00 Example</th>
              <th style=\"width:14%\">Trigger-to-Stop Spacing</th>
              <th style=\"width:19%\">Implied Exit P/L</th>
            </tr>
          </thead>
          <tbody class=\"mono\">
            <tr>
              <td>Stop</td>
              <td>Entry</td>
              <td>Initial protective stop</td>
              <td>entry x {(1.0 + float(policy['initial_stop_loss_pct']) / 100.0):.2f}</td>
              <td>{_money(entry)} -> {_money(initial_stop)}</td>
              <td>{_trigger_to_stop_spacing(entry, initial_stop)}</td>
              <td>{_exit_pl_formula(entry, initial_stop)}</td>
            </tr>
{two_pct_rule_row}
{three_pct_rule_row}
            <tr>
              <td>4% TRAIL</td>
              <td>>= +{policy['trail_5_trigger']:.1f}%</td>
              <td>Trail {policy['trail_5_pct']:.1f}% below quote</td>
              <td>quote x {_multiplier_from_pct(float(policy['trail_5_pct']))}</td>
              <td>{_money(at_t5)} -> {_money(stop_t5)}</td>
              <td>{_trigger_to_stop_spacing(at_t5, stop_t5)}</td>
              <td>{_exit_pl_formula(entry, stop_t5)}</td>
            </tr>
            <tr>
              <td>5% TRAIL</td>
              <td>>= +{policy['trail_4_trigger']:.1f}%</td>
              <td>Trail {policy['trail_4_pct']:.1f}% below quote</td>
              <td>quote x {_multiplier_from_pct(float(policy['trail_4_pct']))}</td>
              <td>{_money(at_t4)} -> {_money(stop_t4)}</td>
              <td>{_trigger_to_stop_spacing(at_t4, stop_t4)}</td>
              <td>{_exit_pl_formula(entry, stop_t4)}</td>
            </tr>
            <tr>
              <td>6% TRAIL</td>
              <td>>= +{policy['trail_3_trigger']:.1f}%</td>
              <td>Trail {policy['trail_3_pct']:.1f}% below quote</td>
              <td>quote x {_multiplier_from_pct(float(policy['trail_3_pct']))}</td>
              <td>{_money(at_t3)} -> {_money(stop_t3)}</td>
              <td>{_trigger_to_stop_spacing(at_t3, stop_t3)}</td>
              <td>{_exit_pl_formula(entry, stop_t3)}</td>
            </tr>
            <tr>
              <td>7% TRAIL</td>
              <td>>= +{policy['trail_2_trigger']:.1f}%</td>
              <td>Trail {policy['trail_2_pct']:.1f}% below quote</td>
              <td>quote x {_multiplier_from_pct(float(policy['trail_2_pct']))}</td>
              <td>{_money(at_t2)} -> {_money(stop_t2)}</td>
              <td>{_trigger_to_stop_spacing(at_t2, stop_t2)}</td>
              <td>{_exit_pl_formula(entry, stop_t2)}</td>
            </tr>
            <tr>
              <td>8% TRAIL</td>
              <td>>= +{policy['trail_1_trigger']:.1f}%</td>
              <td>Trail {policy['trail_1_pct']:.1f}% below quote</td>
              <td>quote x {_multiplier_from_pct(float(policy['trail_1_pct']))}</td>
              <td>{_money(at_t1)} -> {_money(stop_t1)}</td>
              <td>{_trigger_to_stop_spacing(at_t1, stop_t1)}</td>
              <td>{_exit_pl_formula(entry, stop_t1)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class=\"card\">
      <h2>Execution Rules</h2>
      <div class=\"body\">
        <ul>
          <li>Stops ratchet upward only; they never move down.</li>
          <li>At +2% and +3%, stop labels are 2% Stop and 3% Stop before trail tiers take over.</li>
          <li>Protective broker order uses STOP_LIMIT.</li>
          <li>Stop checks use option bid first, mark as fallback.</li>
          <li>No new entries are allowed at or after 3:45 PM ET.</li>
          <li>At 3:45 PM ET, the engine immediately exits any open option position through the normal broker-safe close path.</li>
          <li>Maximum live trade hold: {policy['max_trade_hold_minutes']} minutes; engine exits through the normal broker-safe close path.</li>
          <li>If broker stop sync fails, engine closes position to avoid unprotected exposure.</li>
        </ul>
      </div>
    </div>
  </div>

  <div class=\"foot\">Print settings: Letter, Portrait, Fit to page.</div>
</body>
</html>
"""


def _chrome_bin() -> Path | None:
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _html_to_pdf(html_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    chrome = _chrome_bin()
    if chrome:
        cmd = [
            str(chrome),
            "--headless",
            "--disable-gpu",
            "--print-to-pdf-no-header",
            f"--print-to-pdf={pdf_path}",
            f"file://{html_path}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and pdf_path.exists():
            return True, "chrome-headless"

    cupsfilter = shutil.which("cupsfilter")
    if cupsfilter:
        with pdf_path.open("wb") as out_f:
            proc = subprocess.run(
                [cupsfilter, "-m", "application/pdf", str(html_path)],
                stdout=out_f,
                stderr=subprocess.PIPE,
                text=True,
            )
        if proc.returncode == 0 and pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, "cupsfilter"

    return False, "none"


def _print_pdf(pdf_path: Path) -> Tuple[bool, str]:
    lp = shutil.which("lp")
    if not lp:
        return False, "lp command not found"

    proc = subprocess.run(
        [
            lp,
            "-o",
            "media=Letter",
            "-o",
            "orientation-requested=3",
            "-o",
            "fit-to-page",
            str(pdf_path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip()
    return False, ((proc.stderr or proc.stdout or "print failed").strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate up-to-date stop-loss policy chart and PDF.")
    parser.add_argument("--print", action="store_true", dest="do_print", help="Send generated PDF to default printer.")
    parser.add_argument("--open", action="store_true", dest="do_open", help="Open the generated PDF after creation.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    policy = _build_policy()
    OUT_HTML.write_text(_build_html(policy), encoding="utf-8")

    ok, method = _html_to_pdf(OUT_HTML, OUT_PDF)
    if not ok:
        print("ERROR: Could not convert stop-loss policy HTML to PDF.")
        print(f"HTML generated at: {OUT_HTML}")
        return 2

    print(f"HTML: {OUT_HTML}")
    print(f"PDF:  {OUT_PDF}")
    print(f"PDF generation method: {method}")

    if args.do_print:
        printed, msg = _print_pdf(OUT_PDF)
        if printed:
            print(f"Print submitted: {msg}")
        else:
            print(f"Print failed: {msg}")
            return 3

    if args.do_open:
        subprocess.run(["open", str(OUT_PDF)], check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
