#!/usr/bin/env python3
"""End-to-end weekly model-improvement workflow runner."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from engine.model_evaluator import run_model_evaluator
from engine.weight_optimizer import run_weight_optimizer


WORKSPACE = Path(__file__).parent


def _run_cmd(cmd: str, timeout: int = 1800) -> Dict[str, str]:
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "command": cmd,
        "returncode": str(result.returncode),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _tail(text: str, max_chars: int = 2000) -> str:
    if not text:
        return ""
    return text[-max_chars:]


def _run_fallback_core_steps() -> Tuple[bool, List[Dict[str, str]]]:
    """Run core workflow steps directly when wrapper workflow returns non-zero."""
    steps = [
        ("venv/bin/python engine/intelligence_engine.py", "intelligence_engine"),
        ("venv/bin/python engine/portfolio_engine.py", "portfolio_engine"),
        ("venv/bin/python reports/morning_cio_report.py", "morning_cio_report"),
    ]
    results: List[Dict[str, str]] = []
    ok = True

    for cmd, name in steps:
        step = _run_cmd(cmd, timeout=1800)
        step["step"] = name
        results.append(step)
        if step.get("returncode") != "0":
            ok = False

    return ok, results


def main() -> int:
    started = datetime.now().isoformat(timespec="seconds")
    print(f"Weekly model improvement started at {started}")

    workflow = _run_cmd("venv/bin/python run_intelligence_workflow.py", timeout=2400)
    fallback_ok = True
    fallback_results: List[Dict[str, str]] = []
    warnings: List[str] = []

    if workflow["returncode"] != "0":
        print("Core workflow returned non-zero. Running hardened fallback steps...")
        if workflow.get("stderr"):
            print(_tail(workflow["stderr"], 3000))
        elif workflow.get("stdout"):
            print(_tail(workflow["stdout"], 3000))

        fallback_ok, fallback_results = _run_fallback_core_steps()
        if not fallback_ok:
            warnings.append("Fallback core steps encountered failures.")
        else:
            warnings.append("Fallback core steps succeeded after wrapper non-zero exit.")

    evaluator = run_model_evaluator()
    optimizer = run_weight_optimizer()
    optimizer_status = str(optimizer.get("status", "unknown"))

    nonfatal_optimizer_statuses = {"ok", "insufficient_history", "insufficient_samples"}
    optimizer_nonfatal = optimizer_status in nonfatal_optimizer_statuses
    if not optimizer_nonfatal:
        warnings.append(f"Unexpected optimizer status: {optimizer_status}")

    core_ok = workflow["returncode"] == "0" or fallback_ok
    overall_success = core_ok and optimizer_nonfatal

    summary = {
        "started": started,
        "completed": datetime.now().isoformat(timespec="seconds"),
        "workflow_returncode": workflow["returncode"],
        "core_workflow_ok": core_ok,
        "fallback_ran": workflow["returncode"] != "0",
        "fallback_ok": fallback_ok,
        "fallback_results": [
            {
                "step": r.get("step", "unknown"),
                "returncode": r.get("returncode", "1"),
                "stdout_tail": _tail(r.get("stdout", ""), 400),
                "stderr_tail": _tail(r.get("stderr", ""), 400),
            }
            for r in fallback_results
        ],
        "evaluator": evaluator,
        "optimizer": optimizer,
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2))
    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())