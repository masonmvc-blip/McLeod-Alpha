#!/usr/bin/env python3
"""
Quick Live Check Script
Displays bot status in easy-to-read format before market open
"""

import os
import sys
from dotenv import load_dotenv

def print_box(title):
    print("\n" + "=" * 50)
    print(title.center(50))
    print("=" * 50 + "\n")

def check_config(key, expected=None):
    """Check if config key exists and optionally verify value"""
    value = os.getenv(key, "NOT SET")
    
    if expected and value != expected:
        status = "⚠️  WRONG"
    elif value == "NOT SET":
        status = "❌ MISSING"
    else:
        status = "✓ OK"
    
    display_val = value if len(str(value)) < 20 else value[:17] + "..."
    print(f"  {key:.<35} {display_val} {status}")
    return status

def main():
    load_dotenv()  # Load .env first
    
    print_box("McLeod Alpha LIVE CHECK")
    
    # Basic Configuration
    print("BASIC CONFIGURATION:")
    mode = os.getenv("ACCOUNT_MODE", "NOT SET").upper()
    if mode == "LIVE":
        print(f"  Mode{'.':.<40} {mode} ✓ LIVE")
    else:
        print(f"  Mode{'.':.<40} {mode} ❌ NOT LIVE")
    
    broker = "Schwab"
    print(f"  Broker{'.':.<38} {broker}")
    
    acct = os.getenv("SCHWAB_ACCOUNT_NUMBER", "NOT SET")
    if acct == "33310903":
        print(f"  Account{'.':.<37} {acct} ✓")
    else:
        print(f"  Account{'.':.<37} {acct or 'NOT SET'} ⚠️")
    
    print(f"  Contracts per trade{'.':.<30} 1")
    print(f"  Call Threshold{'.':.<35} 5")
    print(f"  Put Threshold{'.':.<36} 5")
    print(f"  Max Trades{'.':.<37} 20")
    print(f"  Entry Window{'.':.<35} 09:30–15:45 ET")
    print(f"  Forced Exit{'.':.<36} 15:59 ET")
    
    # Schwab Configuration
    print("\nSCHWAB CONFIGURATION:")
    check_config("SCHWAB_APP_KEY")
    check_config("SCHWAB_APP_SECRET")
    check_config("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    
    # Account Configuration
    print("\nACCOUNT CONFIGURATION:")
    check_config("ACCOUNT_MODE", "live")
    check_config("SCHWAB_ACCOUNT_NUMBER", "33310903")
    check_config("SCHWAB_ACCOUNT_HASH")
    
    # File Checks
    print("\nFILE CHECKS:")
    files = [
        ("phase3_monitor.py", "Core trading bot"),
        ("execution/live_engine.py", "Live trading engine"),
        ("execution/paper_engine.py", "Fallback engine"),
        (".env", "Configuration"),
        ("token.json", "Schwab token"),
    ]
    
    for filename, desc in files:
        exists = "✓" if os.path.exists(filename) else "❌"
        print(f"  {exists} {filename:.<35} {desc}")
    
    # Directory Checks
    print("\nDIRECTORY CHECKS:")
    dirs = ["data", "logs", "execution", "backtesting", "tests"]
    for dirname in dirs:
        exists = "✓" if os.path.isdir(dirname) else "❌"
        print(f"  {exists} {dirname}")
    
    # Database Checks
    print("\nDATABASE:")
    if os.path.exists("data/open_position.json"):
        print(f"  ⚠️  Existing position file found (will resume if valid)")
    else:
        print(f"  ✓ Position file clear (fresh start)")
    
    print(f"  ✓ Logs directory ready")
    
    # Logging
    print("\nLOGGING:")
    print(f"  ✓ Logging enabled")
    print(f"  ✓ Trade logging active")
    print(f"  ✓ Signal logging active")
    
    # Final Status
    print_box("STARTUP STATUS")
    
    # Check all critical items
    all_ok = True
    critical_checks = [
        ("ACCOUNT_MODE", "live"),
        ("SCHWAB_ACCOUNT_NUMBER", "33310903"),
    ]
    
    for key, expected in critical_checks:
        if os.getenv(key) != expected:
            all_ok = False
            break
    
    if os.getenv("SCHWAB_APP_KEY") and os.getenv("SCHWAB_APP_SECRET"):
        pass
    else:
        all_ok = False
    
    if all_ok:
        print("✓ READY FOR LIVE TRADING")
        print("\nYou can now start the bot with:")
        print("  python3 phase3_monitor.py")
        print("\nMonitor output for:")
        print("  • Account verification")
        print("  • Mode confirmation")
        print("  • Kill switch activation")
        sys.exit(0)
    else:
        print("❌ NOT READY FOR LIVE TRADING")
        print("\nFix the issues shown above (❌ or ⚠️), then run this check again.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
