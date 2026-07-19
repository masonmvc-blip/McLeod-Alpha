#!/usr/bin/env python3
"""
McLeod Portfolio Engine v1.0 - Full Integration Test & Runner
Run complete workflow: Portfolio Sync → Engine Analysis → Morning Report
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).parent
ENGINE_SCRIPT = WORKSPACE / "engine" / "portfolio_engine.py"
SYNC_SCRIPT = WORKSPACE / "portfolio_sync.py"

DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

# Expected output files
EXPECTED_OUTPUTS = [
    DATA_DIR / "mcleod_core_rankings_latest.csv",
    DATA_DIR / "eipv_rankings_latest.csv",
    DATA_DIR / "target_weights_latest.csv",
    REPORTS_DIR / "morning_cio_report_latest.md",
]


def run_command(cmd: list, description: str) -> bool:
    """Run a command and report results."""
    print(f"\n{'='*80}")
    print(f"🔄 Step: {description}")
    print(f"{'='*80}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(WORKSPACE),
            capture_output=False,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"✅ {description} - SUCCESS")
            return True
        else:
            print(f"❌ {description} - FAILED (exit code: {result.returncode})")
            return False
    
    except subprocess.TimeoutExpired:
        print(f"❌ {description} - TIMEOUT (60s)")
        return False
    except Exception as e:
        print(f"❌ {description} - ERROR: {e}")
        return False


def verify_outputs() -> bool:
    """Verify all expected output files exist and have content."""
    print(f"\n{'='*80}")
    print(f"📋 Verifying Output Files")
    print(f"{'='*80}\n")
    
    all_good = True
    
    for output_file in EXPECTED_OUTPUTS:
        if output_file.exists():
            size = output_file.stat().st_size
            if size > 0:
                print(f"✅ {output_file.name:50} ({size:,} bytes)")
            else:
                print(f"⚠️  {output_file.name:50} (empty - {size} bytes)")
                all_good = False
        else:
            print(f"❌ {output_file.name:50} (missing)")
            all_good = False
    
    return all_good


def main():
    """Run complete integration test."""
    print(f"\n{'='*80}")
    print(f"🏛️  McLeod Portfolio Engine v1.0 - Full Integration Test")
    print(f"{'='*80}")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    steps_completed = []
    steps_failed = []
    
    # Step 1: Portfolio Sync (optional - if running fresh)
    print("Would you like to run portfolio_sync.py first? (optional)")
    print("This downloads latest Schwab portfolio data.")
    user_input = input("Run portfolio_sync? (y/n): ").strip().lower()
    
    if user_input == 'y':
        success = run_command(
            ["./venv/bin/python3", str(SYNC_SCRIPT)],
            "Download Latest Portfolio Data (portfolio_sync.py)"
        )
        if success:
            steps_completed.append("Portfolio Sync")
        else:
            steps_failed.append("Portfolio Sync")
    else:
        print("Skipping portfolio_sync.py (using cached data)")
        steps_completed.append("Portfolio Sync (cached)")
    
    # Step 2: Portfolio Engine Analysis
    success = run_command(
        ["./venv/bin/python3", str(ENGINE_SCRIPT)],
        "Portfolio Engine Analysis"
    )
    if success:
        steps_completed.append("Portfolio Engine")
    else:
        steps_failed.append("Portfolio Engine")
        print("⚠️  Stopping here - Portfolio Engine is required for report generation")
        return False
    
    # Step 3: Morning CIO Report
    success = run_command(
        ["./venv/bin/python3", "-m", "cio_email.morning_report", "--dry-run"],
        "Generate Morning CIO Report"
    )
    if success:
        steps_completed.append("Morning CIO Report")
    else:
        steps_failed.append("Morning CIO Report")
    
    # Verify outputs
    outputs_ok = verify_outputs()
    
    # Summary
    print(f"\n{'='*80}")
    print(f"📊 Integration Test Summary")
    print(f"{'='*80}\n")
    
    print(f"✅ Completed Steps ({len(steps_completed)}):")
    for step in steps_completed:
        print(f"   • {step}")
    
    if steps_failed:
        print(f"\n❌ Failed Steps ({len(steps_failed)}):")
        for step in steps_failed:
            print(f"   • {step}")
    
    print(f"\n📁 Output Files:")
    if outputs_ok:
        print(f"   ✅ All output files verified")
    else:
        print(f"   ⚠️  Some output files missing or empty")
    
    print(f"\n{'='*80}")
    if not steps_failed and outputs_ok:
        print("✅ INTEGRATION TEST PASSED - All systems operational")
    elif not steps_failed:
        print("⚠️  PARTIAL SUCCESS - Steps complete but verify output files")
    else:
        print("❌ INTEGRATION TEST FAILED - See errors above")
    
    print(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")
    
    return not steps_failed and outputs_ok


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
