#!/usr/bin/env python3
"""Manual test for daily market-close P&L email."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from execution.daily_pnl_email import maybe_send_daily_pnl_email


if __name__ == "__main__":
    sent = maybe_send_daily_pnl_email()
    if sent:
        print("Daily P&L email sent")
    else:
        print("Daily P&L email not sent (before send time, already sent today, or config/transport issue)")
