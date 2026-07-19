#!/usr/bin/env python3
"""
McLeod Research Engine v2.0
Comprehensive fundamental research with multi-source data aggregation.

Integrates:
- SEC Filings (90+ confidence)
- Finviz Elite (when available)
- IBD Ratings
- Manual Research
- Future API providers

Merges results and selects highest-confidence values for all fundamental metrics.
Automatically updates portfolio Data Quality Score.
"""

import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import statistics
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configuration
WORKSPACE = Path(__file__).parent.parent
CONFIG_DIR = WORKSPACE / "config"
DATA_DIR = WORKSPACE / "data"
REPORTS_DIR = WORKSPACE / "reports"

METRICS_CONFIG = CONFIG_DIR / "mcleod_core_metrics.json"
POSITIONS_CSV = DATA_DIR / "schwab_positions_latest.csv"
MANUAL_RESEARCH_CSV = DATA_DIR / "manual_research.csv"  # Optional manual research file

OUTPUT_JSON = DATA_DIR / "mcleod_research_latest.json"
OUTPUT_CSV = DATA_DIR / "mcleod_research_latest.csv"
REPORT_MD = REPORTS_DIR / "research_summary.md"

# Constants
RESEARCH_NEEDED_PLACEHOLDER = "NEEDS_RESEARCH"
DEFAULT_CONFIDENCE_THRESHOLD = 50  # Minimum confidence to use in rankings
MAX_DATA_QUALITY_SCORE = 100.0

# Import data sources
from engine.data_sources.sec_source import SECDataSource
from engine.data_sources.ibd_source import IBDDataSource
from engine.data_sources.finviz_source import FinvizDataSource
from engine.data_sources.manual_source import ManualResearchSource
from engine.data_sources.future_api_source import FutureAPIDataSource


class ResearchEngine:
    """Fundamental research engine with multi-source data aggregation."""
    
    def __init__(self):
        """Initialize research engine with all data sources."""
        self.config = None
        self.positions = []
        self.equities = []
        self.research_data = {}
        
        # Data sources
        self.sec_source = None
        self.ibd_source = None
        self.finviz_source = None
        self.manual_source = None
        self.future_api_source = None
        
        # Statistics
        self.metrics_merged_count = 0
        self.holdings_eligible_for_ranking = 0
        
        self.load_config()
        self.load_data_sources()
        self.load_positions()
    
    def load_config(self):
        """Load metrics configuration."""
        try:
            with open(METRICS_CONFIG) as f:
                self.config = json.load(f)
            print(f"✓ Loaded metrics config: {len(self.config['metrics'])} metrics")
        except Exception as e:
            raise SystemExit(f"ERROR loading config: {e}")
    
    def load_data_sources(self):
        """Initialize all data sources."""
        try:
            self.sec_source = SECDataSource()
            self.ibd_source = IBDDataSource(DATA_DIR / "ibd_rankings_manual.csv")
            self.finviz_source = FinvizDataSource()
            self.manual_source = ManualResearchSource(MANUAL_RESEARCH_CSV if MANUAL_RESEARCH_CSV.exists() else None)
            self.future_api_source = FutureAPIDataSource()
            
            print(f"✓ Initialized data sources: SEC, IBD, Finviz, Manual, Future APIs")
        except Exception as e:
            raise SystemExit(f"ERROR loading data sources: {e}")
    
    def load_positions(self):
        """Load positions from portfolio."""
        try:
            with open(POSITIONS_CSV) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.positions.append(row)
            
            # Separate equities from options
            self.equities = [p for p in self.positions if p.get('asset_type', '').upper() == 'EQUITY']
            
            print(f"✓ Loaded {len(self.equities)} equities from portfolio")
        except Exception as e:
            raise SystemExit(f"ERROR loading positions: {e}")
    
    def resolve_metric(self, symbol: str, metric: str) -> Dict[str, Any]:
        """
        Resolve a metric by checking all sources and selecting highest confidence.
        
        Returns: {value, source, timestamp, confidence, stale}
        """
        results = []
        
        # Check all data sources
        if self.sec_source:
            sec_result = self.sec_source.get_financial_metric(symbol, metric)
            if sec_result and sec_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                results.append(sec_result)
        
        if self.ibd_source and 'ibd_' in metric:
            ibd_result = self.ibd_source.get_ibd_metric(symbol, metric)
            if ibd_result and ibd_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                results.append(ibd_result)
        
        if self.finviz_source:
            finviz_result = self.finviz_source.get_metric(symbol, metric)
            if finviz_result and finviz_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                results.append(finviz_result)
        
        if self.manual_source:
            manual_result = self.manual_source.get_metric(symbol, metric)
            if manual_result and manual_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                results.append(manual_result)
        
        if self.future_api_source:
            api_result = self.future_api_source.get_metric(symbol, metric)
            if api_result and api_result.get('value') != RESEARCH_NEEDED_PLACEHOLDER:
                results.append(api_result)
        
        # Select highest confidence result
        if results:
            self.metrics_merged_count += 1
            best_result = max(results, key=lambda x: x.get('confidence', 0))
            
            # Add "merged" indicator if multiple sources provided data
            if len(results) > 1:
                best_result['merged_sources'] = len(results)
            
            return best_result
        
        # Default: research needed
        return {
            "value": RESEARCH_NEEDED_PLACEHOLDER,
            "source": "Multiple Sources",
            "timestamp": datetime.now().isoformat(),
            "confidence": 0,
            "stale": False,
            "reason": "No data from any source"
        }
    
    def research_holding(self, symbol: str, position: Dict[str, Any]) -> Dict[str, Any]:
        """Conduct research on a holding."""
        research = {
            'symbol': symbol,
            'asset_type': position.get('asset_type', 'EQUITY'),
            'market_value': float(position.get('market_value', 0)),
            'weight_pct': float(position.get('portfolio_weight_percent', 0)),
            'research_timestamp': datetime.now().isoformat(),
        }
        
        # Resolve each metric from all sources
        for metric_name in self.config['metrics'].keys():
            metric_data = self.resolve_metric(symbol, metric_name)
            research[metric_name] = metric_data['value']
            research[f"{metric_name}_source"] = metric_data.get('source', 'unknown')
            research[f"{metric_name}_confidence"] = metric_data.get('confidence', 0)
            research[f"{metric_name}_stale"] = metric_data.get('stale', False)
            
            # Add merged sources count if applicable
            if 'merged_sources' in metric_data:
                research[f"{metric_name}_merged_sources"] = metric_data['merged_sources']
        
        # Calculate data quality score
        research['data_quality_score'] = self.calculate_data_quality(research, symbol)
        research['data_quality_score_source'] = 'research_engine'
        research['data_quality_score_confidence'] = 100
        research['data_quality_score_stale'] = False
        
        # Determine eligibility for McLeod Core Rankings
        eligible = research['data_quality_score'] >= 50  # Minimum threshold
        research['eligible_for_core_rankings'] = eligible
        if eligible:
            self.holdings_eligible_for_ranking += 1
        
        return research
        research['mcleod_core_composite'] = self.calculate_mcleod_composite(research)
        research['mcleod_core_composite_source'] = 'research_engine'
        research['mcleod_core_composite_confidence'] = (
            75 if research['mcleod_core_composite'] != RESEARCH_NEEDED_PLACEHOLDER else 0
        )
        
        return research
    
    def calculate_data_quality(self, research: Dict[str, Any], symbol: str) -> float:
        """
        Calculate data quality score (% of metrics populated from any source).
        Higher score means better data coverage for fundamental analysis.
        """
        metric_names = [m for m in self.config['metrics'].keys()]
        populated = 0
        total = len(metric_names)
        
        for metric in metric_names:
            value = research.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = research.get(f"{metric}_confidence", 0)
            
            # Count as populated if it has a value AND meaningful confidence
            if value != RESEARCH_NEEDED_PLACEHOLDER and confidence >= DEFAULT_CONFIDENCE_THRESHOLD:
                populated += 1
        
        quality_score = (populated / total * 100) if total > 0 else 0
        return round(quality_score, 1)
    
    def count_populated_metrics(self, research: Dict[str, Any]) -> int:
        """Count populated metrics per holding (with minimum confidence)."""
        metric_names = [m for m in self.config['metrics'].keys()]
        count = 0
        for metric in metric_names:
            value = research.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
            confidence = research.get(f"{metric}_confidence", 0)
            if value != RESEARCH_NEEDED_PLACEHOLDER and confidence >= DEFAULT_CONFIDENCE_THRESHOLD:
                count += 1
        return count
    
    def research_all_holdings(self) -> List[Dict[str, Any]]:
        """Conduct research on all equities."""
        research_results = []
        
        print(f"\n🔬 Researching {len(self.equities)} holdings with multi-source data aggregation...\n")
        
        for i, equity in enumerate(self.equities, 1):
            symbol = equity.get('symbol', '')
            research = self.research_holding(symbol, equity)
            research_results.append(research)
            
            # Progress indicator
            if i % 5 == 0 or i == len(self.equities):
                print(f"  ✓ {i}/{len(self.equities)} holdings researched")
        
        return research_results
    
    def save_outputs(self, research_results: List[Dict[str, Any]]):
        """Save research outputs to JSON, CSV, and Markdown report."""
        if not research_results:
            print("No research results to save")
            return
        
        # Ensure reports directory exists
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Save JSON
        try:
            output_json = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "version": "2.0.0",
                    "engine": "McLeod Research Engine",
                    "total_holdings": len(research_results),
                    "metrics_defined": len(self.config['metrics']),
                    "metrics_merged": self.metrics_merged_count,
                    "holdings_eligible_for_core_rankings": self.holdings_eligible_for_ranking,
                },
                "holdings": research_results,
            }
            
            with open(OUTPUT_JSON, 'w') as f:
                json.dump(output_json, f, indent=2)
            print(f"✓ Research saved to {OUTPUT_JSON}")
        except Exception as e:
            print(f"ERROR saving JSON: {e}")
        
        # Save CSV
        try:
            if research_results:
                with open(OUTPUT_CSV, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=research_results[0].keys())
                    writer.writeheader()
                    writer.writerows(research_results)
                print(f"✓ Research saved to {OUTPUT_CSV}")
        except Exception as e:
            print(f"ERROR saving CSV: {e}")

        # Save Markdown summary report
        try:
            metric_names = [m for m in self.config['metrics'].keys()]
            quality_scores = [r.get('data_quality_score', 0) for r in research_results]
            avg_quality = statistics.mean(quality_scores) if quality_scores else 0.0
            eligible = [r for r in research_results if r.get('eligible_for_core_rankings')]

            missing_by_symbol = {}
            for r in research_results:
                missing = []
                for metric in metric_names:
                    if r.get(metric, RESEARCH_NEEDED_PLACEHOLDER) == RESEARCH_NEEDED_PLACEHOLDER:
                        missing.append(metric)
                missing_by_symbol[r.get('symbol', 'UNKNOWN')] = missing

            lines = []
            lines.append("# Research Summary")
            lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            lines.append("## Portfolio Data Quality")
            lines.append(f"- Overall Data Quality Score: **{avg_quality:.1f}%**")
            lines.append(f"- Eligible Holdings (>=50%): **{len(eligible)}/{len(research_results)}**")
            lines.append("")
            lines.append("## Eligible Holdings")
            if eligible:
                for row in sorted(eligible, key=lambda x: x.get('data_quality_score', 0), reverse=True):
                    lines.append(f"- {row.get('symbol')}: {row.get('data_quality_score', 0):.1f}%")
            else:
                lines.append("- None")
            lines.append("")
            lines.append("## Remaining Missing Metrics By Holding")
            for symbol in sorted(missing_by_symbol.keys()):
                missing = missing_by_symbol[symbol]
                if missing:
                    lines.append(f"- {symbol}: {', '.join(missing[:12])}{' ...' if len(missing) > 12 else ''}")
                else:
                    lines.append(f"- {symbol}: none")

            with open(REPORT_MD, 'w') as f:
                f.write("\n".join(lines) + "\n")
            print(f"✓ Research summary report saved to {REPORT_MD}")
        except Exception as e:
            print(f"ERROR saving research summary report: {e}")
    
    def generate_summary(self, research_results: List[Dict[str, Any]]):
        """Generate comprehensive research summary."""
        print(f"\n" + "="*80)
        print(f"📊 MCLEOD RESEARCH ENGINE SUMMARY")
        print(f"="*80 + "\n")
        
        metric_names = [m for m in self.config['metrics'].keys()]
        total_slots = len(research_results) * len(metric_names)
        populated_slots = 0
        populated_by_metric = {m: 0 for m in metric_names}
        populated_by_confidence = {m: 0 for m in metric_names}
        
        # Data quality distribution
        quality_scores = []
        eligible_for_ranking = 0
        
        for research in research_results:
            quality = research.get('data_quality_score', 0)
            quality_scores.append(quality)
            
            if research.get('eligible_for_core_rankings', False):
                eligible_for_ranking += 1
            
            for metric in metric_names:
                value = research.get(metric, RESEARCH_NEEDED_PLACEHOLDER)
                confidence = research.get(f"{metric}_confidence", 0)
                
                if value != RESEARCH_NEEDED_PLACEHOLDER:
                    populated_slots += 1
                    populated_by_metric[metric] += 1
                
                if confidence >= DEFAULT_CONFIDENCE_THRESHOLD:
                    populated_by_confidence[metric] += 1
        
        print(f"📈 HOLDINGS RESEARCHED")
        print(f"  Total: {len(research_results)}")
        print(f"  Equities: {len(research_results)}")
        
        print(f"\n📊 DATA QUALITY METRICS")
        print(f"  Overall Data Quality Score: {statistics.mean(quality_scores):.1f}% (Portfolio Average)")
        if quality_scores:
            print(f"    Min: {min(quality_scores):.1f}%")
            print(f"    Max: {max(quality_scores):.1f}%")
            print(f"    Median: {statistics.median(quality_scores):.1f}%")
        
        print(f"\n📋 METRICS POPULATED")
        print(f"  Total Metric Slots: {total_slots}")
        print(f"  Populated: {populated_slots} ({populated_slots/total_slots*100:.1f}%)")
        print(f"  High-Confidence (≥50): {sum(populated_by_confidence.values())} ({sum(populated_by_confidence.values())/total_slots*100:.1f}%)")
        print(f"  NEEDS_RESEARCH: {total_slots - populated_slots}")
        
        print(f"\n✅ HOLDINGS ELIGIBLE FOR MCLEOD CORE RANKINGS")
        print(f"  Count: {eligible_for_ranking}/{len(research_results)}")
        print(f"  Percentage: {eligible_for_ranking/len(research_results)*100:.1f}%")
        print(f"  Requirement: Data Quality Score ≥ 50%")
        
        print(f"\n🔀 MULTI-SOURCE DATA MERGING")
        print(f"  Metrics merged from multiple sources: {self.metrics_merged_count}")
        
        print(f"\n🔍 TOP METRICS POPULATED (Any Confidence)")
        sorted_metrics = sorted(
            populated_by_metric.items(),
            key=lambda x: x[1],
            reverse=True
        )
        for metric, count in sorted_metrics[:15]:
            pct = count / len(research_results) * 100 if research_results else 0
            print(f"  {metric:35} {count:3}/{len(research_results):3} ({pct:5.1f}%)")
        
        print(f"\n💪 TOP METRICS POPULATED (High Confidence ≥50)")
        sorted_confident = sorted(
            populated_by_confidence.items(),
            key=lambda x: x[1],
            reverse=True
        )
        for metric, count in sorted_confident[:15]:
            pct = count / len(research_results) * 100 if research_results else 0
            print(f"  {metric:35} {count:3}/{len(research_results):3} ({pct:5.1f}%)")
        
        print(f"\n⚠️  TOP METRICS NEEDING RESEARCH")
        sorted_metrics_asc = sorted(
            populated_by_metric.items(),
            key=lambda x: x[1]
        )
        for metric, count in sorted_metrics_asc[:15]:
            missing = len(research_results) - count
            pct = missing / len(research_results) * 100 if research_results else 0
            print(f"  {metric:35} {missing:3}/{len(research_results):3} ({pct:5.1f}%)")
        
        print(f"\n" + "="*80)


def main():
    """Run research engine with multi-source data aggregation."""
    print("\n" + "="*80)
    print("🔬 McLeod Research Engine v2.0 - Multi-Source Data Aggregation")
    print("="*80 + "\n")
    
    try:
        engine = ResearchEngine()
        
        # Research all holdings
        research_results = engine.research_all_holdings()
        
        # Save outputs
        engine.save_outputs(research_results)
        
        # Generate summary
        engine.generate_summary(research_results)
        
        print(f"\n✅ Research Engine complete")
        print(f"="*80 + "\n")
        
        return research_results
    
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
