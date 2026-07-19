#!/usr/bin/env python3
"""
Full Intelligence Engine Workflow Test
Runs complete pipeline and generates detailed metrics status report.
"""

import json
import csv
import sys
from pathlib import Path
import subprocess
from datetime import datetime, timedelta

WORKSPACE = Path(__file__).parent
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"


def artifact_set_is_fresh(paths: list[Path], max_age_hours: float = 12.0) -> bool:
    """Return True when all artifacts exist and were updated recently."""
    if not paths:
        return False
    now = datetime.now()
    for path in paths:
        if not path.exists() or path.stat().st_size <= 0:
            return False
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if now - modified > timedelta(hours=max_age_hours):
            return False
    return True

def run_command(cmd: str, description: str, timeout: int = 1200) -> bool:
    """Run command and report status."""
    print(f"\n▶️  {description}...")
    print(f"   Command: {cmd}\n")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            print(f"✅ {description} - SUCCESS")
            return True
        else:
            print(f"❌ {description} - FAILED")
            print(f"Error: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ {description} - TIMEOUT ({timeout}s)")
        return False
    except Exception as e:
        print(f"❌ {description} - ERROR: {e}")
        return False


def run_command_or_skip_if_fresh(
    cmd: str,
    description: str,
    artifact_paths: list[Path],
    timeout: int = 1200,
    max_age_hours: float = 12.0,
    force_rebuild: bool = False,
) -> bool:
    """Skip expensive rebuilds when current artifacts are already fresh."""
    if not force_rebuild and artifact_set_is_fresh(artifact_paths, max_age_hours=max_age_hours):
        print(f"\n▶️  {description}...")
        print("   Using fresh existing artifacts\n")
        print(f"✅ {description} - SKIPPED (fresh artifacts)")
        return True
    return run_command(cmd, description, timeout=timeout)

def analyze_metrics():
    """Analyze and print detailed metrics status."""
    print("\n" + "="*80)
    print("📊 DETAILED METRICS ANALYSIS BY HOLDING")
    print("="*80)
    
    try:
        with open(DATA_DIR / "mcleod_intelligence_latest.json") as f:
            data = json.load(f)
        
        holdings = data.get("holdings", [])
        
        for i, holding in enumerate(holdings, 1):
            symbol = holding.get("symbol", "N/A")
            quality = holding.get("data_quality_score", 0)
            market_val = holding.get("market_value", 0)
            weight = holding.get("weight_pct", 0)
            
            # Count populated metrics
            metric_names = [k for k in holding.keys() if not k.endswith("_source") 
                           and not k.endswith("_timestamp") 
                           and not k.endswith("_confidence")
                           and not k.endswith("_stale")]
            
            populated = 0
            missing = []
            stale = []
            
            for metric in metric_names:
                value = holding.get(metric, "NEEDS_RESEARCH")
                if value != "NEEDS_RESEARCH" and value != "" and metric not in [
                    "symbol", "asset_type", "market_value", "weight_pct", 
                    "intelligence_timestamp", "current_price", "quantity"
                ]:
                    populated += 1
                elif metric not in ["symbol", "asset_type", "market_value", "weight_pct",
                                   "intelligence_timestamp", "current_price", "quantity"]:
                    missing.append(metric)
                    if holding.get(f"{metric}_stale"):
                        stale.append(metric)
            
            print(f"\n{i:2}. {symbol:8} ${market_val:>10,.0f} ({weight:5.2f}%)")
            print(f"    Data Quality: {quality:5.1f}% ({populated} metrics populated)")
            
            if quality >= 70:
                print(f"    Status: ✅ READY FOR RANKING")
            elif quality >= 50:
                print(f"    Status: ⚠️  ACCEPTABLE (needs {70-int(quality)}% more data)")
            else:
                print(f"    Status: 🚫 BLOCKED (needs {70-int(quality)}% more data)")
            
            # Show top populated metrics
            populated_metrics = []
            for metric in metric_names:
                value = holding.get(metric)
                if value != "NEEDS_RESEARCH" and value != "" and metric not in [
                    "symbol", "asset_type", "market_value", "weight_pct",
                    "intelligence_timestamp", "current_price", "quantity"
                ]:
                    source = holding.get(f"{metric}_source", "unknown")
                    populated_metrics.append((metric, value, source))
            
            if populated_metrics:
                print(f"    Populated: {', '.join([f'{m[0]}' for m in populated_metrics[:5]])}")
                if len(populated_metrics) > 5:
                    print(f"               ...and {len(populated_metrics)-5} more")
            
            # Show missing metrics (top 5)
            if missing[:5]:
                print(f"    Missing:   {', '.join(missing[:5])}")
                if len(missing) > 5:
                    print(f"               ...and {len(missing)-5} more")
            
            # Show stale data
            if stale:
                print(f"    ⏰ Stale:    {', '.join(stale)}")
    
    except Exception as e:
        print(f"Error analyzing metrics: {e}")


def print_required_outputs() -> bool:
    """Print required workflow outputs and validate activation/report criteria."""
    intelligence_path = DATA_DIR / "mcleod_intelligence_latest.json"
    core_rankings_path = DATA_DIR / "mcleod_core_rankings_latest.csv"
    report_research = REPORTS_DIR / "research_summary.md"
    report_sec = REPORTS_DIR / "sec_parser_validation.md"
    report_cio = REPORTS_DIR / "morning_cio_report_latest.md"
    report_analyst = REPORTS_DIR / "analyst_intelligence_report.md"
    report_analyst_weekly = REPORTS_DIR / "analyst_predictive_performance_weekly.md"
    report_earnings_call = REPORTS_DIR / "earnings_call_intelligence_report.md"
    report_insider = REPORTS_DIR / "insider_intelligence_report.md"
    report_earnings_quality = REPORTS_DIR / "earnings_quality_report.md"
    report_capital_allocation = REPORTS_DIR / "capital_allocation_report.md"

    if not intelligence_path.exists():
        print("\n❌ Missing intelligence output file")
        return False

    with open(intelligence_path) as f:
        intel = json.load(f)
    holdings = intel.get("holdings", [])
    if not holdings:
        print("\n❌ No holdings in intelligence output")
        return False

    avg_quality = sum(float(h.get("data_quality_score", 0) or 0) for h in holdings) / len(holdings)
    eligible = [h.get("symbol", "N/A") for h in holdings if h.get("eligible_for_core_rankings")]

    ranked = []
    if core_rankings_path.exists():
        with open(core_rankings_path, newline="") as f:
            ranked = list(csv.DictReader(f))

    print("\n" + "=" * 80)
    print("📌 REQUIRED OUTPUT SUMMARY")
    print("=" * 80)
    print(f"Overall Data Quality %: {avg_quality:.1f}%")
    print(f"Eligible holdings ({len(eligible)}): {', '.join(eligible) if eligible else 'None'}")
    print(f"Ranked holdings: {len(ranked)}")

    if ranked:
        print("\nTop 10 ranked stocks:")
        for row in ranked[:10]:
            rank = row.get("rank", "?")
            symbol = row.get("symbol", row.get("Symbol", "N/A"))
            score = row.get("composite_score", row.get("mcleod_core_score", "N/A"))
            print(f"  {rank}. {symbol} (score: {score})")

    print("\nRemaining missing metrics by holding:")
    excluded = {
        "symbol", "asset_type", "market_value", "weight_pct", "intelligence_timestamp", "current_price", "quantity"
    }
    for holding in holdings:
        symbol = holding.get("symbol", "N/A")
        missing = []
        for key, value in holding.items():
            if key in excluded or key.endswith("_source") or key.endswith("_timestamp") or key.endswith("_confidence") or key.endswith("_stale"):
                continue
            if value == "NEEDS_RESEARCH":
                missing.append(key)
        print(f"  - {symbol}: {', '.join(missing[:10])}{' ...' if len(missing) > 10 else ''}")

    reports_ok = (
        report_research.exists()
        and report_sec.exists()
        and report_cio.exists()
        and report_analyst.exists()
        and report_analyst_weekly.exists()
        and report_earnings_call.exists()
        and report_insider.exists()
        and report_earnings_quality.exists()
        and report_capital_allocation.exists()
    )
    rankings_active = len(ranked) > 0

    print("\nRequired reports generated:")
    print(f"  - research_summary.md: {'YES' if report_research.exists() else 'NO'}")
    print(f"  - sec_parser_validation.md: {'YES' if report_sec.exists() else 'NO'}")
    print(f"  - morning_cio_report_latest.md: {'YES' if report_cio.exists() else 'NO'}")
    print(f"  - analyst_intelligence_report.md: {'YES' if report_analyst.exists() else 'NO'}")
    print(f"  - analyst_predictive_performance_weekly.md: {'YES' if report_analyst_weekly.exists() else 'NO'}")
    print(f"  - earnings_call_intelligence_report.md: {'YES' if report_earnings_call.exists() else 'NO'}")
    print(f"  - insider_intelligence_report.md: {'YES' if report_insider.exists() else 'NO'}")
    print(f"  - earnings_quality_report.md: {'YES' if report_earnings_quality.exists() else 'NO'}")
    print(f"  - capital_allocation_report.md: {'YES' if report_capital_allocation.exists() else 'NO'}")

    return rankings_active and reports_ok

def main():
    """Run complete workflow."""
    print("\n" + "="*80)
    print("🔧 McLeod INTELLIGENCE ENGINE v1.0 - COMPLETE WORKFLOW TEST")
    print("="*80)
    
    success = True
    
    # 0. Sync latest Schwab portfolio
    if not run_command(
        "venv/bin/python portfolio_sync.py",
        "0. Syncing Latest Schwab Portfolio"
    ):
        success = False

    # 1. Run SEC parser
    if not run_command(
        "venv/bin/python engine/data_sources/sec_source.py",
        "1. Running SEC Parser"
    ):
        success = False

    # 2. Run research engine
    if not run_command(
        "venv/bin/python engine/research_engine.py",
        "2. Running Research Engine"
    ):
        success = False

    # 3. Run analyst intelligence engine
    if not run_command_or_skip_if_fresh(
        "venv/bin/python engine/analyst_intelligence.py",
        "3. Running Analyst Intelligence Engine",
        artifact_paths=[
            DATA_DIR / "analyst_estimates_latest.json",
            DATA_DIR / "analyst_estimates_latest.csv",
            REPORTS_DIR / "analyst_intelligence_report.md",
            REPORTS_DIR / "analyst_predictive_performance_weekly.md",
        ],
        timeout=2400,
    ):
        success = False

    # 4. Run earnings call intelligence engine
    if not run_command_or_skip_if_fresh(
        "venv/bin/python engine/earnings_call_intelligence.py",
        "4. Running Earnings Call Intelligence Engine",
        artifact_paths=[
            DATA_DIR / "earnings_call_intelligence_latest.json",
            DATA_DIR / "earnings_call_intelligence_latest.csv",
            DATA_DIR / "earnings_call_history.csv",
            REPORTS_DIR / "earnings_call_intelligence_report.md",
        ],
        timeout=2400,
    ):
        success = False

    # 5. Run insider intelligence engine
    if not run_command_or_skip_if_fresh(
        "venv/bin/python engine/insider_intelligence.py",
        "5. Running Insider Intelligence Engine",
        artifact_paths=[
            DATA_DIR / "insider_transactions_latest.json",
            DATA_DIR / "insider_transactions_latest.csv",
            DATA_DIR / "insider_signal_history.csv",
            REPORTS_DIR / "insider_intelligence_report.md",
        ],
        timeout=2400,
        force_rebuild=__import__("os").getenv("INSIDER_INCLUDE_FULL_UNIVERSE", "0") == "1",
    ):
        success = False

    # 6. Run earnings quality engine
    if not run_command_or_skip_if_fresh(
        "venv/bin/python engine/earnings_quality.py",
        "6. Running Earnings Quality Engine",
        artifact_paths=[
            DATA_DIR / "earnings_quality_latest.json",
            DATA_DIR / "earnings_quality_latest.csv",
            DATA_DIR / "earnings_quality_history.csv",
            REPORTS_DIR / "earnings_quality_report.md",
        ],
        timeout=2400,
        force_rebuild=__import__("os").getenv("EARNINGS_QUALITY_INCLUDE_FULL_UNIVERSE", "0") == "1",
    ):
        success = False

    # 7. Run capital allocation engine
    if not run_command_or_skip_if_fresh(
        "venv/bin/python engine/capital_allocation.py",
        "7. Running Capital Allocation Engine",
        artifact_paths=[
            DATA_DIR / "capital_allocation_latest.json",
            DATA_DIR / "capital_allocation_latest.csv",
            DATA_DIR / "capital_allocation_history.csv",
            REPORTS_DIR / "capital_allocation_report.md",
        ],
        timeout=2400,
        force_rebuild=__import__("os").getenv("CAPITAL_ALLOCATION_INCLUDE_FULL_UNIVERSE", "0") == "1",
    ):
        success = False

    # 8. Run intelligence engine
    if not run_command(
        "venv/bin/python engine/intelligence_engine.py",
        "8. Running Intelligence Engine"
    ):
        success = False
    
    # 9. Run portfolio engine
    if not run_command(
        "venv/bin/python engine/portfolio_engine.py",
        "9. Running Portfolio Engine with Intelligence Data"
    ):
        success = False
    
    # 10. Generate morning report
    if not run_command(
        "venv/bin/python reports/morning_cio_report.py",
        "10. Generating Morning CIO Report"
    ):
        success = False
    
    # 11. Analyze metrics in detail
    analyze_metrics()

    # 12. Print required outputs and enforce activation/report generation criteria
    criteria_ok = print_required_outputs()
    if not criteria_ok:
        success = False
    
    # Final summary
    print("\n" + "="*80)
    print("📈 WORKFLOW SUMMARY")
    print("="*80)
    
    try:
        with open(DATA_DIR / "mcleod_intelligence_latest.json") as f:
            data = json.load(f)
        
        holdings = data.get("holdings", [])
        
        # Count quality levels
        ready_for_ranking = sum(1 for h in holdings if h.get("data_quality_score", 0) >= 70)
        acceptable = sum(1 for h in holdings if 50 <= h.get("data_quality_score", 0) < 70)
        blocked = sum(1 for h in holdings if h.get("data_quality_score", 0) < 50)
        
        print(f"\nHoldings Status:")
        print(f"  ✅ Ready for Ranking (≥70%):  {ready_for_ranking}/{len(holdings)}")
        print(f"  ⚠️  Acceptable (50-70%):       {acceptable}/{len(holdings)}")
        print(f"  🚫 Blocked (<50%):             {blocked}/{len(holdings)}")
        
        # Metrics summary
        metadata = data.get("metadata", {})
        print(f"\nMetrics Summary:")
        print(f"  Total Metrics: {metadata.get('metrics_defined', 0)}")
        print(f"  Total Holdings: {len(holdings)}")
        print(f"  Average Data Quality: {sum(h.get('data_quality_score', 0) for h in holdings)/len(holdings):.1f}%")
        
        # Output files
        print(f"\nOutput Files Generated:")
        for fname in ["mcleod_intelligence_latest.json", "mcleod_intelligence_latest.csv",
                 "analyst_estimates_latest.json", "analyst_estimates_latest.csv",
                 "earnings_call_intelligence_latest.json", "earnings_call_intelligence_latest.csv",
                 "insider_transactions_latest.json", "insider_transactions_latest.csv",
                 "earnings_quality_latest.json", "earnings_quality_latest.csv",
                 "capital_allocation_latest.json", "capital_allocation_latest.csv",
                     "mcleod_core_rankings_latest.csv", "eipv_rankings_latest.csv",
                     "target_weights_latest.csv"]:
            fpath = DATA_DIR / fname
            if fpath.exists():
                size = fpath.stat().st_size
                print(f"  ✓ {fname:40} ({size:>10,} bytes)")
            else:
                print(f"  ✗ {fname:40} (NOT FOUND)")
        
        report_path = Path(__file__).parent / "reports" / "morning_cio_report_latest.md"
        if report_path.exists():
            size = report_path.stat().st_size
            print(f"  ✓ {'morning_cio_report_latest.md':40} ({size:>10,} bytes)")
        
    except Exception as e:
        print(f"Error in summary: {e}")
    
    print("\n" + "="*80)
    if success:
        print("✅ WORKFLOW COMPLETE - ALL SYSTEMS OPERATIONAL")
    else:
        print("⚠️  WORKFLOW COMPLETE - RANKINGS NOT ACTIVE OR REQUIRED REPORTS MISSING")
    print("="*80 + "\n")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
