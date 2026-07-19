#!/usr/bin/env python3
"""
IBD Data Source
Imports IBD ratings from manual CSV file.
Supports: Composite, RS, EPS, SMR, Acc/Dis, Industry Group Rank

Letter Rating Conversion to Numeric (for model calculations only):
  A+ → 95, A → 90, B+ → 80, B → 75, C → 60, D → 45, E → 30
  Original letter ratings are preserved in storage.
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

class IBDDataSource:
    """IBD manual import data source with letter-to-numeric conversion."""
    
    # Rating conversion table for calculations
    LETTER_TO_NUMERIC = {
        "A+": 95,
        "A": 90,
        "B+": 80,
        "B": 75,
        "C": 60,
        "D": 45,
        "E": 30,
    }
    
    def __init__(self, ibd_csv_path: Path):
        """
        Initialize IBD data source.
        
        Args:
            ibd_csv_path: Path to IBD rankings CSV file
        """
        self.ibd_csv_path = ibd_csv_path
        self.ibd_data = {}
        self.load_ibd_data()
        self.valid_symbols_count = 0
        self.missing_symbols_count = 0
    
    def load_ibd_data(self):
        """Load IBD data from CSV file."""
        if not self.ibd_csv_path.exists():
            print(f"⚠️  IBD CSV not found at {self.ibd_csv_path}")
            return
        
        try:
            with open(self.ibd_csv_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    symbol = row.get("Symbol", "").upper()
                    if symbol:
                        self.ibd_data[symbol] = row
            
            print(f"✓ Loaded IBD data for {len(self.ibd_data)} symbols from {self.ibd_csv_path.name}")
        
        except Exception as e:
            print(f"ERROR loading IBD CSV: {e}")
    
    def _parse_ibd_date(self, date_str: str) -> Optional[datetime]:
        """Parse IBD date from CSV (expected format: YYYY-MM-DD)."""
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except:
            return None
    
    def _letter_to_numeric(self, letter_rating: str) -> int:
        """Convert letter rating to numeric value for calculations."""
        letter_rating = letter_rating.strip().upper()
        return self.LETTER_TO_NUMERIC.get(letter_rating, None)
    
    def _is_data_stale(self, date_str: str) -> bool:
        """Check if IBD data is older than 7 days."""
        ibd_date = self._parse_ibd_date(date_str)
        if not ibd_date:
            return True  # Mark unparseable dates as stale
        
        age = datetime.now() - ibd_date
        return age > timedelta(days=7)
    
    def get_ibd_metric(
        self,
        symbol: str,
        metric: str
    ) -> Dict[str, Any]:
        """
        Get IBD metric for a symbol.
        
        Args:
            symbol: Stock ticker
            metric: IBD metric name
        
        Returns:
            Dict with value, source, timestamp, confidence, stale_flag
        """
        result = {
            "value": "NEEDS_RESEARCH",
            "source": "IBD Manual Import",
            "timestamp": datetime.now().isoformat(),
            "confidence": 0,
            "stale": False,
            "reason": "IBD data not available for symbol"
        }
        
        # Normalize symbol for lookup
        symbol_upper = symbol.upper()
        
        # Check if symbol has IBD data
        if symbol_upper not in self.ibd_data:
            result["reason"] = f"Symbol {symbol} not in IBD import file"
            self.missing_symbols_count += 1
            return result
        
        symbol_data = self.ibd_data[symbol_upper]
        
        # Map metrics to CSV column names
        metric_map = {
            "ibd_composite": "Composite",
            "ibd_eps_rating": "EPS",
            "ibd_rs_rating": "RS",
            "ibd_smr_rating": "SMR",
            "ibd_acc_dist_rating": "Acc/Dis",  # Backward-compatible alias
            "ibd_acc_dis": "Acc/Dis",
            "ibd_industry_group_rank": "Industry Rank",  # Backward-compatible alias
            "ibd_industry_rank": "Industry Rank",
        }
        
        if metric not in metric_map:
            result["reason"] = f"Unknown IBD metric: {metric}"
            return result
        
        csv_column = metric_map[metric]
        value = symbol_data.get(csv_column, "").strip()
        
        if not value:
            result["reason"] = f"No {csv_column} value in IBD import"
            return result
        
        # Extract date from CSV
        date_str = symbol_data.get("Date", "").strip()
        result["stale"] = self._is_data_stale(date_str) if date_str else True
        
        # Parse and return value
        try:
            # Handle numeric ratings (Composite, EPS, RS, Industry Rank)
            if metric in ["ibd_composite", "ibd_eps_rating", "ibd_rs_rating"]:
                numeric_value = float(value)
                result["value"] = numeric_value
                result["confidence"] = 90
                result["reason"] = ""
                self.valid_symbols_count += 1
                return result
            
            # Handle letter ratings (SMR, Acc/Dis) - preserve original, provide numeric for calculations
            if metric in ["ibd_smr_rating", "ibd_acc_dist_rating", "ibd_acc_dis"]:
                letter_value = value.upper()
                numeric_value = self._letter_to_numeric(letter_value)
                
                # Store original letter rating
                result["value"] = letter_value
                result["numeric_value"] = numeric_value  # For model calculations
                result["confidence"] = 90
                result["reason"] = ""
                self.valid_symbols_count += 1
                return result
            
            # Handle Industry Rank (numeric)
            if metric in ["ibd_industry_group_rank", "ibd_industry_rank"]:
                numeric_value = int(value)
                result["value"] = numeric_value
                result["confidence"] = 90
                result["reason"] = ""
                self.valid_symbols_count += 1
                return result
        
        except (ValueError, TypeError) as e:
            result["reason"] = f"Error parsing IBD value '{value}' for {csv_column}: {str(e)}"
        
        return result


if __name__ == "__main__":
    # Test instantiation
    from pathlib import Path
    test_path = Path("data/ibd_rankings_manual.csv")
    ibd_source = IBDDataSource(test_path)
    print("✓ IBD Data Source loaded")
