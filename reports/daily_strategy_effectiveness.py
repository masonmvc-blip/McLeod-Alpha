from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "logs" / "daily_strategy_effectiveness.log"
ET = ZoneInfo("America/New_York")


def maybe_generate_daily_strategy_effectiveness_report() -> None:
    """Best-effort placeholder report hook used by phase3 monitor.

    This keeps the runtime stable even when the full report generator
    is not present. It intentionally does not raise exceptions.
    """
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(ET).isoformat()
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{ts} | skipped (placeholder active)\n")
    except Exception:
        # Never allow report generation to interrupt live monitoring.
        return
