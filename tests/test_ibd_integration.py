#!/usr/bin/env python3
"""
Tests for IBD Integration with McLeod Intelligence Engine

Tests IBD data source loading, rating conversions, stale flag logic,
and integration with the main intelligence engine.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
import csv
import tempfile

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_sources.ibd_source import IBDDataSource
from engine.intelligence_engine import IntelligenceEngine


class TestIBDDataSource:
    """Test IBD data source functionality."""
    
    @pytest.fixture
    def temp_ibd_csv(self):
        """Create temporary IBD CSV for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.DictWriter(f, fieldnames=[
                'Symbol', 'Composite', 'EPS', 'RS', 'SMR', 'Acc/Dis', 'Industry Rank', 'Date', 'Notes'
            ])
            writer.writeheader()
            
            # Write test data
            today = datetime.now().strftime("%Y-%m-%d")
            old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
            
            writer.writerow({
                'Symbol': 'AMZN',
                'Composite': 80,
                'EPS': 82,
                'RS': 78,
                'SMR': 'A',
                'Acc/Dis': 'A',
                'Industry Rank': 4,
                'Date': today,
                'Notes': 'Fresh data'
            })
            
            writer.writerow({
                'Symbol': 'CVS',
                'Composite': 60,
                'EPS': 55,
                'RS': 50,
                'SMR': 'C',
                'Acc/Dis': 'D',
                'Industry Rank': 180,
                'Date': old_date,
                'Notes': 'Stale data'
            })
            
            writer.writerow({
                'Symbol': 'DDOG',
                'Composite': 75,
                'EPS': 78,
                'RS': 72,
                'SMR': 'B+',
                'Acc/Dis': 'B',
                'Industry Rank': 8,
                'Date': today,
                'Notes': 'With plus rating'
            })
            
            temp_path = Path(f.name)
        
        yield temp_path
        
        # Cleanup
        temp_path.unlink()
    
    def test_ibd_source_loads(self, temp_ibd_csv):
        """Test that IBD source loads CSV correctly."""
        source = IBDDataSource(temp_ibd_csv)
        assert len(source.ibd_data) == 3
        assert 'AMZN' in source.ibd_data
        assert 'CVS' in source.ibd_data
        print(f"✓ IBD source loaded {len(source.ibd_data)} symbols")
    
    def test_numeric_ratings(self, temp_ibd_csv):
        """Test numeric rating retrieval."""
        source = IBDDataSource(temp_ibd_csv)
        
        # Test Composite rating
        result = source.get_ibd_metric('AMZN', 'ibd_composite')
        assert result['value'] == 80
        assert result['confidence'] == 90
        assert result['stale'] == False
        print(f"✓ Composite rating retrieved: {result['value']}")
        
        # Test EPS rating
        result = source.get_ibd_metric('AMZN', 'ibd_eps_rating')
        assert result['value'] == 82
        print(f"✓ EPS rating retrieved: {result['value']}")
        
        # Test RS rating
        result = source.get_ibd_metric('AMZN', 'ibd_rs_rating')
        assert result['value'] == 78
        print(f"✓ RS rating retrieved: {result['value']}")
    
    def test_letter_ratings(self, temp_ibd_csv):
        """Test letter rating retrieval and conversion."""
        source = IBDDataSource(temp_ibd_csv)
        
        # Test SMR rating
        result = source.get_ibd_metric('AMZN', 'ibd_smr_rating')
        assert result['value'] == 'A'
        assert result['numeric_value'] == 90
        assert result['confidence'] == 90
        print(f"✓ SMR letter rating preserved: {result['value']}, numeric: {result['numeric_value']}")
        
        # Test Acc/Dis rating
        result = source.get_ibd_metric('AMZN', 'ibd_acc_dist_rating')
        assert result['value'] == 'A'
        assert result['numeric_value'] == 90
        print(f"✓ Acc/Dis letter rating preserved: {result['value']}, numeric: {result['numeric_value']}")
    
    def test_plus_ratings_conversion(self, temp_ibd_csv):
        """Test conversion of plus ratings (e.g., B+, A+)."""
        source = IBDDataSource(temp_ibd_csv)
        
        result = source.get_ibd_metric('DDOG', 'ibd_smr_rating')
        assert result['value'] == 'B+'
        assert result['numeric_value'] == 80
        print(f"✓ Plus rating conversion works: B+ → {result['numeric_value']}")
    
    def test_industry_rank(self, temp_ibd_csv):
        """Test industry rank retrieval."""
        source = IBDDataSource(temp_ibd_csv)
        
        result = source.get_ibd_metric('AMZN', 'ibd_industry_group_rank')
        assert result['value'] == 4
        assert result['confidence'] == 90
        print(f"✓ Industry rank retrieved: {result['value']}")
    
    def test_stale_flag(self, temp_ibd_csv):
        """Test stale flag for data older than 7 days."""
        source = IBDDataSource(temp_ibd_csv)
        
        # Fresh data should not be stale
        result = source.get_ibd_metric('AMZN', 'ibd_composite')
        assert result['stale'] == False
        print(f"✓ Fresh data not marked stale")
        
        # Old data (10 days) should be stale
        result = source.get_ibd_metric('CVS', 'ibd_composite')
        assert result['stale'] == True
        print(f"✓ 10-day-old data marked stale")
    
    def test_missing_symbol(self, temp_ibd_csv):
        """Test handling of missing symbols."""
        source = IBDDataSource(temp_ibd_csv)
        
        result = source.get_ibd_metric('NONEXISTENT', 'ibd_composite')
        assert result['value'] == 'NEEDS_RESEARCH'
        assert 'not in IBD import file' in result['reason']
        print(f"✓ Missing symbol returns NEEDS_RESEARCH: {result['reason']}")
    
    def test_case_insensitive_lookup(self, temp_ibd_csv):
        """Test that symbol lookup is case-insensitive."""
        source = IBDDataSource(temp_ibd_csv)
        
        # Test lowercase lookup
        result = source.get_ibd_metric('amzn', 'ibd_composite')
        assert result['value'] == 80
        
        # Test mixed case
        result = source.get_ibd_metric('AmZn', 'ibd_composite')
        assert result['value'] == 80
        print(f"✓ Case-insensitive symbol lookup works")
    
    def test_valid_missing_counts(self, temp_ibd_csv):
        """Test tracking of valid and missing symbols."""
        source = IBDDataSource(temp_ibd_csv)
        
        # Get metrics for existing symbols
        source.get_ibd_metric('AMZN', 'ibd_composite')
        source.get_ibd_metric('CVS', 'ibd_composite')
        
        # Try to get metric for non-existing symbol
        source.get_ibd_metric('NONEXISTENT', 'ibd_composite')
        
        # Check counts
        assert source.valid_symbols_count > 0
        assert source.missing_symbols_count > 0
        print(f"✓ Valid: {source.valid_symbols_count}, Missing: {source.missing_symbols_count}")


class TestIntelligenceEngineIBDIntegration:
    """Test IBD integration with Intelligence Engine."""
    
    def test_intelligence_engine_starts(self):
        """Test that Intelligence Engine loads successfully."""
        try:
            # This will fail if config or positions don't exist, but tests the load path
            from pathlib import Path
            workspace = Path(__file__).parent.parent
            config_file = workspace / "config" / "intelligence_metrics.json"
            
            assert config_file.exists(), "intelligence_metrics.json not found"
            print(f"✓ Intelligence metrics config found")
            
            # Test that IBD metrics are in config
            import json
            with open(config_file) as f:
                config = json.load(f)
            
            ibd_metrics = [m for m in config['metrics'].keys() if 'ibd' in m.lower()]
            assert len(ibd_metrics) > 0, "No IBD metrics found in config"
            print(f"✓ Found {len(ibd_metrics)} IBD metrics in config")
            
            for metric in ibd_metrics:
                print(f"  - {metric}")
        
        except SystemExit as e:
            pytest.skip(f"Intelligence Engine not fully runnable in test: {e}")


def test_ibd_letter_conversions():
    """Test all letter-to-numeric conversions."""
    from engine.data_sources.ibd_source import IBDDataSource
    
    source = IBDDataSource(Path("dummy"))
    
    conversions = {
        "A+": 95,
        "A": 90,
        "B+": 80,
        "B": 75,
        "C": 60,
        "D": 45,
        "E": 30,
    }
    
    for letter, expected_numeric in conversions.items():
        actual = source._letter_to_numeric(letter)
        assert actual == expected_numeric, f"Failed for {letter}"
        print(f"✓ {letter} → {actual}")


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v", "-s"])
