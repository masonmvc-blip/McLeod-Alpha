#!/usr/bin/env python3
"""One-command McLeod report launcher.

Runs the full McLeod workflow, regenerates required reports, writes a detailed
log file, and opens the core rankings report in VS Code when complete.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from engine.memory import get_memory

WORKSPACE = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"
LOG_DIR = WORKSPACE / "logs"
LOG_FILE = LOG_DIR / "mcleod_report_latest.log"

CORE_RANKINGS_CSV = DATA_DIR / "mcleod_core_rankings_latest.csv"
FULL_MARKET_CSV = DATA_DIR / "mcleod_full_market_rankings_latest.csv"
REPLACEMENTS_CSV = DATA_DIR / "replacement_candidates_latest.csv"
EIPV_CSV = DATA_DIR / "eipv_rankings_latest.csv"
TARGET_WEIGHTS_CSV = DATA_DIR / "target_weights_latest.csv"
MODEL_WEEKLY_CSV = DATA_DIR / "model_weekly_metrics.csv"
BUYBACK_IMPACT_CSV = DATA_DIR / "buyback_ranking_impact_latest.csv"

CORE_REPORT_MD = REPORTS_DIR / "mcleod_core_rankings_latest.md"
REPLACEMENT_REPORT_MD = REPORTS_DIR / "replacement_candidates_latest.md"
MORNING_REPORT_MD = REPORTS_DIR / "morning_cio_report_latest.md"
MODEL_HEALTH_MD = REPORTS_DIR / "model_health_dashboard.md"
BUYBACK_AUDIT_MD = REPORTS_DIR / "share_buyback_audit.md"
BUYBACK_PERF_MD = REPORTS_DIR / "buyback_factor_performance.md"


@dataclass(frozen=True)
class Step:
    name: str
    command: Sequence[str]
    critical: bool = True
    timeout_seconds: int = 2400
    env: Optional[Dict[str, str]] = None


class StepFailed(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pick_python() -> str:
    preferred = [
        WORKSPACE / "venv" / "bin" / "python",
        WORKSPACE / ".venv" / "bin" / "python",
    ]

    def has_schwab(py_bin: Path) -> bool:
        try:
            res = subprocess.run(
                [str(py_bin), "-c", "import schwab"],
                cwd=str(WORKSPACE),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    py311 = Path("/opt/homebrew/bin/python3.11")
    if py311.exists() and has_schwab(py311):
        return str(py311)

    for path in preferred:
        if path.exists() and has_schwab(path):
            return str(path)
    if py311.exists():
        return str(py311)
    return sys.executable


def _append_log(message: str) -> None:
    get_memory().append_report_line(LOG_FILE, message, "mcleod_report_run_log", source="run_mcleod_report")


def _run_step(step: Step) -> None:
    start = datetime.now()
    banner = f"\n[{_now()}] === {step.name} ===\n"
    print(banner, end="")
    _append_log(banner)
    _append_log(f"[{_now()}] COMMAND: {' '.join(step.command)}\n")

    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    if step.env:
        env.update(step.env)

    try:
        result = subprocess.run(
            list(step.command),
            cwd=str(WORKSPACE),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=step.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        if output:
            print(output, end="")
            _append_log(output)
        raise StepFailed(f"{step.name} timed out after {step.timeout_seconds}s")

    output = result.stdout or ""
    if output:
        print(output, end="")
        _append_log(output)

    return_code = result.returncode
    elapsed = (datetime.now() - start).total_seconds()
    done = f"[{_now()}] Step finished with code {return_code} in {elapsed:.1f}s\n"
    print(done, end="")
    _append_log(done)

    if return_code != 0:
        raise StepFailed(f"{step.name} failed with exit code {return_code}")


def _read_csv(path: Path) -> List[dict]:
    text = get_memory().read_report_text(path, encoding="utf-8")
    return list(csv.DictReader(text.splitlines())) if text else []


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        if value in (None, "", "NEEDS_RESEARCH"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _model_confidence(weekly_rows: List[dict]) -> tuple[str, str]:
    if not weekly_rows:
        return "Low", "No model weekly history found."
    latest = weekly_rows[-1]
    resolved = int(_to_float(latest.get("resolved_1w_count", "0"), 0.0))
    beat_spy_pct = _to_float(latest.get("beat_spy_rate_1w", "0"), 0.0)
    if resolved < 10:
        return "Low", f"Only {resolved} resolved +1w outcomes; confidence is preliminary."
    if beat_spy_pct >= 60:
        return "High", f"Beat SPY rate is {beat_spy_pct:.2f}% with {resolved} resolved +1w outcomes."
    if beat_spy_pct >= 52:
        return "Medium", f"Beat SPY rate is {beat_spy_pct:.2f}% with {resolved} resolved +1w outcomes."
    return "Low", f"Beat SPY rate is {beat_spy_pct:.2f}% with {resolved} resolved +1w outcomes."


def _write_replacement_report(replacements: List[dict]) -> None:
    lines: List[str] = []
    lines.append("# McLeod Replacement Candidates")
    lines.append("")
    lines.append(f"Last updated: {_now()}")
    lines.append("")

    if not replacements:
        lines.append("No replacement candidates found in latest run.")
    else:
        lines.append("| Candidate | Candidate Rank | Candidate Score | Replace Holding | Replace Rank | Score Improvement | Expected Alpha Improvement |")
        lines.append("| --- | ---: | ---: | --- | ---: | ---: | ---: |")
        for row in replacements[:25]:
            lines.append(
                "| {cand} | {cr} | {cs} | {rep} | {rr} | {imp} | {alpha} |".format(
                    cand=row.get("candidate_symbol", ""),
                    cr=row.get("candidate_rank", ""),
                    cs=row.get("candidate_score", ""),
                    rep=row.get("replace_symbol", ""),
                    rr=row.get("replace_rank", ""),
                    imp=row.get("score_improvement", ""),
                    alpha=row.get("expected_alpha_improvement", ""),
                )
            )

    get_memory().write_report_text(REPLACEMENT_REPORT_MD, "\n".join(lines) + "\n", "replacement_candidates", source="run_mcleod_report")


def _write_core_report() -> None:
    core_rows = _read_csv(CORE_RANKINGS_CSV)
    full_rows = _read_csv(FULL_MARKET_CSV)
    replacement_rows = _read_csv(REPLACEMENTS_CSV)
    eipv_rows = _read_csv(EIPV_CSV)
    target_rows = _read_csv(TARGET_WEIGHTS_CSV)
    weekly_rows = _read_csv(MODEL_WEEKLY_CSV)

    if not core_rows:
        raise StepFailed("Core rankings CSV is missing or empty; cannot write core report.")

    full_by_symbol = {str(r.get("symbol", "")).upper(): r for r in full_rows}
    holdings = [str(r.get("symbol", "")).upper() for r in core_rows]

    avg_dq = sum(_to_float(r.get("data_quality", "0"), 0.0) for r in core_rows) / max(1, len(core_rows))
    confidence_label, confidence_detail = _model_confidence(weekly_rows)

    warnings: List[str] = []
    required_inputs = [
        CORE_RANKINGS_CSV,
        FULL_MARKET_CSV,
        REPLACEMENTS_CSV,
        EIPV_CSV,
        TARGET_WEIGHTS_CSV,
        MORNING_REPORT_MD,
        MODEL_HEALTH_MD,
    ]
    for p in required_inputs:
        if not p.exists() or p.stat().st_size == 0:
            warnings.append(f"Missing or empty required artifact: {p.relative_to(WORKSPACE)}")

    stale_cutoff_seconds = 24 * 3600
    now_ts = datetime.now().timestamp()
    for p in required_inputs:
        if not p.exists():
            continue
        age_seconds = now_ts - p.stat().st_mtime
        if age_seconds > stale_cutoff_seconds:
            warnings.append(f"Potentially stale artifact (>24h): {p.relative_to(WORKSPACE)}")

    missing_core_inputs = sum(1 for r in core_rows if str(r.get("missing_core_inputs", "")).strip() not in ("", "0", "[]"))
    if missing_core_inputs:
        warnings.append(f"{missing_core_inputs} holdings have missing core inputs flagged.")

    thesis_alerts = [
        r for r in core_rows if str(r.get("thesis_health", "HEALTHY")).upper() not in {"HEALTHY", "INTACT"}
    ]

    lines: List[str] = []
    lines.append("# McLeod Core Rankings Report")
    lines.append("")
    lines.append(f"Last updated: {_now()}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Holdings scored: {len(core_rows)}")
    lines.append(f"- Average Data Quality Score: {avg_dq:.2f}")
    lines.append(f"- Model Confidence: {confidence_label}")
    lines.append(f"- Confidence detail: {confidence_detail}")
    lines.append("")

    lines.append("## Top 20 McLeod Core Rankings")
    lines.append("")
    lines.append("| Rank | Symbol | Composite Score | Data Quality | Current Holding |")
    lines.append("| ---: | --- | ---: | ---: | --- |")
    top20 = sorted(full_rows, key=lambda r: _to_float(r.get("composite_score", "0"), 0.0), reverse=True)[:20]
    for row in top20:
        is_holding = str(row.get("is_current_holding", "")).lower() in {"1", "true", "yes"}
        lines.append(
            f"| {row.get('rank', '') or row.get('rank_all', '')} | {row.get('symbol', '')} | {row.get('composite_score', '')} | {row.get('data_quality', '')} | {'✅ HOLDING' if is_holding else 'Candidate'} |"
        )
    lines.append("")

    lines.append("## Score For Every Stock In Current Portfolio")
    lines.append("")
    lines.append("| Rank | Symbol | Composite Score | Weight | Thesis Health | Data Quality |")
    lines.append("| ---: | --- | ---: | ---: | --- | ---: |")
    for row in sorted(core_rows, key=lambda r: _to_float(r.get("rank", "9999"), 9999.0)):
        lines.append(
            f"| {row.get('rank', '')} | **{row.get('symbol', '')}** | {row.get('composite_score', '')} | {row.get('weight_pct', '')}% | {row.get('thesis_health', '')} | {row.get('data_quality', '')} |"
        )
    lines.append("")

    lines.append("## Rank And Percentile Of Every Current Holding")
    lines.append("")
    lines.append("| Symbol | Rank (Full Market) | Percentile | Composite Score |")
    lines.append("| --- | ---: | ---: | ---: |")
    for symbol in holdings:
        row = full_by_symbol.get(symbol, {})
        lines.append(
            f"| {symbol} | {row.get('rank', 'N/A')} | {row.get('percentile', 'N/A')} | {row.get('composite_score', 'N/A')} |"
        )
    lines.append("")

    lines.append("## Top Replacement Candidates")
    lines.append("")
    lines.append("| Candidate | Candidate Rank | Candidate Score | Replace Holding | Replace Rank | Score Improvement |")
    lines.append("| --- | ---: | ---: | --- | ---: | ---: |")
    for row in replacement_rows[:15]:
        lines.append(
            f"| {row.get('candidate_symbol', '')} | {row.get('candidate_rank', '')} | {row.get('candidate_score', '')} | {row.get('replace_symbol', '')} | {row.get('replace_rank', '')} | {row.get('score_improvement', '')} |"
        )
    if not replacement_rows:
        lines.append("| N/A |  |  |  |  |  |")
    lines.append("")

    lines.append("## Best Next $1,000 By EIPV")
    lines.append("")
    if eipv_rows:
        top = eipv_rows[0]
        lines.append(f"- Recommendation: **{top.get('symbol', 'N/A')}**")
        lines.append(f"- EIPV Score: {top.get('eipv_score', 'N/A')}")
        lines.append(f"- Current Weight: {top.get('current_weight_pct', 'N/A')}%")
        lines.append(f"- Target Weight: {top.get('target_weight_pct', 'N/A')}%")
        lines.append(f"- New Weight After $1,000: {top.get('new_weight_pct', 'N/A')}%")
        lines.append(f"- Potential Value Add: {top.get('potential_value_add', 'N/A')}")
    else:
        lines.append("- EIPV output unavailable")
    lines.append("")

    lines.append("## Current Versus Target Portfolio Weights")
    lines.append("")
    lines.append("| Symbol | Current Weight | Target Weight | Diff | Action |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for row in sorted(target_rows, key=lambda r: abs(_to_float(r.get("diff_pct", "0"), 0.0)), reverse=True):
        lines.append(
            f"| {row.get('symbol', '')} | {_fmt_pct(_to_float(row.get('current_weight_pct', '0')))} | {_fmt_pct(_to_float(row.get('target_weight_pct', '0')))} | {_fmt_pct(_to_float(row.get('diff_pct', '0')))} | {row.get('action', '')} |"
        )
    if not target_rows:
        lines.append("| N/A |  |  |  |  |")
    lines.append("")

    lines.append("## Thesis Health Alerts")
    lines.append("")
    if thesis_alerts:
        for row in thesis_alerts:
            lines.append(
                f"- ⚠️ {row.get('symbol', '')}: thesis_health={row.get('thesis_health', '')}, score={row.get('composite_score', '')}"
            )
    else:
        lines.append("- ✅ No thesis health alerts")
    lines.append("")

    lines.append("## Data Quality Score")
    lines.append("")
    lines.append(f"- Average portfolio Data Quality Score: {avg_dq:.2f}")
    dq_low = [r for r in core_rows if _to_float(r.get("data_quality", "0"), 0.0) < 70.0]
    if dq_low:
        lines.append(f"- ⚠️ Holdings below 70 data quality: {', '.join(r.get('symbol', '') for r in dq_low)}")
    else:
        lines.append("- ✅ All ranked holdings are at or above data quality threshold")
    lines.append("")

    lines.append("## Model Confidence")
    lines.append("")
    lines.append(f"- Model Confidence: **{confidence_label}**")
    lines.append(f"- {confidence_detail}")
    lines.append("")

    lines.append("## Warnings")
    lines.append("")
    if warnings:
        for warning in warnings:
            lines.append(f"- ⚠️ {warning}")
    else:
        lines.append("- ✅ No missing or stale data warnings detected")
    lines.append("")

    get_memory().write_report_text(CORE_REPORT_MD, "\n".join(lines) + "\n", "mcleod_core_rankings", source="run_mcleod_report")
    _write_replacement_report(replacement_rows)


def _ensure_outputs_exist(paths: Iterable[Path]) -> None:
    missing = [p for p in paths if not p.exists() or p.stat().st_size == 0]
    if missing:
        rel = ", ".join(str(p.relative_to(WORKSPACE)) for p in missing)
        raise StepFailed(f"Required outputs missing or empty: {rel}")


def _open_report_in_vscode(report: Path) -> None:
    if shutil.which("code"):
        subprocess.run(["code", "--reuse-window", str(report)], cwd=str(WORKSPACE), check=False)
        return
    subprocess.run(["open", "-a", "Visual Studio Code", str(report)], cwd=str(WORKSPACE), check=False)


def _build_steps(python_exec: str) -> List[Step]:
    default_fast_mode = os.getenv("LAUNCHER_SPECIALIST_FAST_MODE", "1")
    bounded_specialist_env = {
        "SPECIALIST_FAST_MODE": default_fast_mode,
        "ANALYST_FAST_MODE": os.getenv("LAUNCHER_ANALYST_FAST_MODE", default_fast_mode),
        "CALL_FAST_MODE": os.getenv("LAUNCHER_CALL_FAST_MODE", default_fast_mode),
        "INSIDER_FAST_MODE": os.getenv("LAUNCHER_INSIDER_FAST_MODE", default_fast_mode),
        "EARNINGS_QUALITY_FAST_MODE": os.getenv("LAUNCHER_EARNINGS_QUALITY_FAST_MODE", default_fast_mode),
        "CAPITAL_ALLOCATION_FAST_MODE": os.getenv("LAUNCHER_CAPITAL_ALLOCATION_FAST_MODE", default_fast_mode),
        "ANALYST_FORCE_REFRESH": "0",
        "ANALYST_REFRESH_LIMIT": "0",
        "CALL_FORCE_REFRESH": "0",
        "CALL_REFRESH_LIMIT": "0",
        "INSIDER_FORCE_REFRESH": "0",
        "INSIDER_REFRESH_LIMIT": "0",
        "EARNINGS_QUALITY_FORCE_REFRESH": "0",
        "EARNINGS_QUALITY_REFRESH_LIMIT": "0",
        "CAPITAL_ALLOCATION_FORCE_REFRESH": "0",
        "CAPITAL_ALLOCATION_REFRESH_LIMIT": "0",
        "MAX_DEEP_CANDIDATES": "1000",
    }

    return [
        Step("1. Schwab portfolio sync", [python_exec, "portfolio_sync.py"]),
        Step("2. SEC parser", [python_exec, "engine/data_sources/sec_source.py"]),
        Step("3. Research engine", [python_exec, "engine/research_engine.py"]),
        Step("4. Intelligence engine", [python_exec, "engine/intelligence_engine.py"], timeout_seconds=1800),
        Step("5. Analyst intelligence engine", [python_exec, "engine/analyst_intelligence.py"], timeout_seconds=3000, env=bounded_specialist_env),
        Step("6. Earnings call intelligence engine", [python_exec, "engine/earnings_call_intelligence.py"], timeout_seconds=3000, env=bounded_specialist_env),
        Step("7. Insider intelligence engine", [python_exec, "engine/insider_intelligence.py"], timeout_seconds=3000, env=bounded_specialist_env),
        Step("8. Earnings quality engine", [python_exec, "engine/earnings_quality.py"], timeout_seconds=3000, env=bounded_specialist_env),
        Step("9. Capital allocation intelligence engine", [python_exec, "engine/capital_allocation.py"], timeout_seconds=3000, env=bounded_specialist_env),
        Step("9b. Refresh intelligence with latest specialist outputs", [python_exec, "engine/intelligence_engine.py"], timeout_seconds=1800),
        Step("10. Full-market ranker", [python_exec, "engine/full_market_ranker.py"], timeout_seconds=3000, env=bounded_specialist_env),
        Step("11. Portfolio engine", [python_exec, "engine/portfolio_engine.py"]),
        Step("12a. Morning CIO report", [python_exec, "-m", "cio_email.morning_report", "--dry-run"]),
        Step("12b. Model health dashboard", [python_exec, "engine/model_evaluator.py"]),
        Step("12c. Auto-refresh share buyback audit", [python_exec, "scripts/refresh_share_buyback_audit.py"]),
    ]


def main() -> int:
    get_memory().write_report_text(
        LOG_FILE,
        f"[{_now()}] McLeod report launcher start\n",
        "mcleod_report_run_log",
        source="run_mcleod_report",
    )

    python_exec = _pick_python()
    print(f"Using Python: {python_exec}")
    _append_log(f"[{_now()}] Using Python: {python_exec}\n")

    try:
        for step in _build_steps(python_exec):
            _run_step(step)

        _write_core_report()

        _ensure_outputs_exist(
            [
                CORE_REPORT_MD,
                REPLACEMENT_REPORT_MD,
                MORNING_REPORT_MD,
                MODEL_HEALTH_MD,
                LOG_FILE,
                BUYBACK_AUDIT_MD,
                BUYBACK_PERF_MD,
                BUYBACK_IMPACT_CSV,
            ]
        )

        _open_report_in_vscode(CORE_REPORT_MD)

        done = f"\n[{_now()}] SUCCESS: McLeod report workflow completed.\n"
        print(done)
        _append_log(done)
        return 0
    except Exception as exc:
        msg = f"\n[{_now()}] ERROR: {exc}\n"
        print(msg)
        _append_log(msg)
        _append_log(traceback.format_exc() + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
