#!/usr/bin/env python3
"""Send a one-off test SMS using the configured trade alert sender."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from execution.sms_alerts import send_trade_entry_alert


def main():
    ok = send_trade_entry_alert(
        mode="TEST",
        direction="CALL",
        quantity=1,
        option_symbol="SPY_TEST_OPTION",
        option_entry=1.23,
        spy_entry=550.00,
        reason="MANUAL_CONFIG_TEST",
    )
    if ok:
        print("SMS test sent successfully")
    else:
        print("SMS test not sent. Check ENABLE_TRADE_SMS_ALERTS and transport config (mailapp_sms, email_sms, or twilio).")


if __name__ == "__main__":
    main()
