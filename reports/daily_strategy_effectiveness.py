from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.memory import get_memory

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "logs" / "daily_strategy_effectiveness.log"
ET = ZoneInfo("America/New_York")


def maybe_generate_daily_strategy_effectiveness_report() -> None:
    """Best-effort placeholder report hook used by phase3 monitor.

    This keeps the runtime stable even when the full report generator
    is not present. It intentionally does not raise exceptions.
    """
    try:
        ts = datetime.now(ET).isoformat()
        get_memory().append_report_line(
            LOG_FILE, f"{ts} | skipped (placeholder active)", "daily_strategy_effectiveness",
            source="daily_strategy_effectiveness",
        )
    except Exception:
        # Never allow report generation to interrupt live monitoring.
        return
