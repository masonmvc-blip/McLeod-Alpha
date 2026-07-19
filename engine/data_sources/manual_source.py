#!/usr/bin/env python3
"""
Manual Research Source
Allows manual entry of research data via CSV or JSON.
Used to supplement automated sources with hand-researched data.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import csv
import json


class ManualResearchSource:
    """Manual research data source."""
    
    def __init__(self, data_path: Optional[Path] = None):
        """
        Initialize manual research source.
        
        Args:
            data_path: Path to manual research data file (JSON or CSV)
        """
        self.name = "Manual Research"
        self.confidence_base = 70  # Lower than automated sources, but vetted
        self.manual_data = {}
        self.data_path = data_path
        
        if data_path and data_path.exists():
            self.load_data()
    
    def load_data(self):
        """Load manual research data from file."""
        if not self.data_path:
            return
        
        try:
            if self.data_path.suffix.lower() == '.json':
                with open(self.data_path) as f:
                    self.manual_data = json.load(f)
            elif self.data_path.suffix.lower() == '.csv':
                with open(self.data_path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        symbol = row.get('Symbol', '').upper()
                        if symbol:
                            self.manual_data[symbol] = row
            
            print(f"✓ Loaded manual research data for {len(self.manual_data)} symbols")
        except Exception as e:
            print(f"⚠️  Error loading manual research data: {e}")
    
    def get_metric(self, symbol: str, metric: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve manual research metric for a symbol.
        
        Returns: {value, source, timestamp, confidence, stale}
        or None if not available
        """
        symbol = symbol.upper()
        
        if symbol not in self.manual_data:
            return None
        
        symbol_data = self.manual_data[symbol]
        
        # Try to find the metric in the data
        if metric not in symbol_data:
            return None
        
        value = symbol_data.get(metric)
        if not value:
            return None
        
        return {
            "value": value,
            "source": "Manual Research",
            "timestamp": datetime.now().isoformat(),
            "confidence": self.confidence_base,
            "stale": False,
            "reason": "Hand-researched and vetted"
        }
    
    def resolve_metrics(self, symbol: str) -> Dict[str, Dict[str, Any]]:
        """
        Resolve all available metrics for a symbol from manual source.
        
        Returns dict of {metric_name: {value, source, timestamp, confidence, stale}}
        """
        symbol = symbol.upper()
        
        if symbol not in self.manual_data:
            return {}
        
        results = {}
        symbol_data = self.manual_data[symbol]
        
        for metric, value in symbol_data.items():
            if metric.upper() not in ['SYMBOL', 'NOTES']:  # Skip metadata
                results[metric.lower()] = {
                    "value": value,
                    "source": "Manual Research",
                    "timestamp": datetime.now().isoformat(),
                    "confidence": self.confidence_base,
                    "stale": False,
                    "reason": "Hand-researched and vetted"
                }
        
        return results


if __name__ == "__main__":
    source = ManualResearchSource()
    print(f"✓ Manual Research Source initialized")
