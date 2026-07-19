#!/usr/bin/env python3
"""
Test IBD Integration with McLeod Intelligence Engine (No Pytest Required)

Simple direct tests for IBD data source loading, rating conversions, and integration.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import csv
import tempfile

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_sources.ibd_source import IBDDataSource


def create_test_ibd_csv():
    """Create temporary IBD CSV for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
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
    
    return temp_path


def test_ibd_source_loads():
    """Test that IBD source loads CSV correctly."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        assert len(source.ibd_data) == 3
        assert 'AMZN' in source.ibd_data
        assert 'CVS' in source.ibd_data
        print(f"✓ IBD source loaded {len(source.ibd_data)} symbols")
        return True
    finally:
        temp_csv.unlink()


def test_numeric_ratings():
    """Test numeric rating retrieval."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        
        # Test Composite rating
        result = source.get_ibd_metric('AMZN', 'ibd_composite')
        assert result['value'] == 80, f"Expected 80, got {result['value']}"
        assert result['confidence'] == 90, f"Expected confidence 90, got {result['confidence']}"
        assert result['stale'] == False, f"Expected not stale"
        print(f"✓ Composite rating retrieved: {result['value']}")
        
        # Test EPS rating
        result = source.get_ibd_metric('AMZN', 'ibd_eps_rating')
        assert result['value'] == 82
        print(f"✓ EPS rating retrieved: {result['value']}")
        
        # Test RS rating
        result = source.get_ibd_metric('AMZN', 'ibd_rs_rating')
        assert result['value'] == 78
        print(f"✓ RS rating retrieved: {result['value']}")
        return True
    finally:
        temp_csv.unlink()


def test_letter_ratings():
    """Test letter rating retrieval and conversion."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        
        # Test SMR rating
        result = source.get_ibd_metric('AMZN', 'ibd_smr_rating')
        assert result['value'] == 'A', f"Expected 'A', got {result['value']}"
        assert result['numeric_value'] == 90, f"Expected numeric 90, got {result['numeric_value']}"
        assert result['confidence'] == 90
        print(f"✓ SMR letter rating preserved: {result['value']}, numeric: {result['numeric_value']}")
        
        # Test Acc/Dis rating
        result = source.get_ibd_metric('AMZN', 'ibd_acc_dist_rating')
        assert result['value'] == 'A'
        assert result['numeric_value'] == 90
        print(f"✓ Acc/Dis letter rating preserved: {result['value']}, numeric: {result['numeric_value']}")
        return True
    finally:
        temp_csv.unlink()


def test_plus_ratings_conversion():
    """Test conversion of plus ratings (e.g., B+, A+)."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        
        result = source.get_ibd_metric('DDOG', 'ibd_smr_rating')
        assert result['value'] == 'B+', f"Expected 'B+', got {result['value']}"
        assert result['numeric_value'] == 80, f"Expected numeric 80, got {result['numeric_value']}"
        print(f"✓ Plus rating conversion works: B+ → {result['numeric_value']}")
        return True
    finally:
        temp_csv.unlink()


def test_industry_rank():
    """Test industry rank retrieval."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        
        result = source.get_ibd_metric('AMZN', 'ibd_industry_group_rank')
        assert result['value'] == 4
        assert result['confidence'] == 90
        print(f"✓ Industry rank retrieved: {result['value']}")
        return True
    finally:
        temp_csv.unlink()


def test_stale_flag():
    """Test stale flag for data older than 7 days."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        
        # Fresh data should not be stale
        result = source.get_ibd_metric('AMZN', 'ibd_composite')
        assert result['stale'] == False, f"Fresh data should not be stale"
        print(f"✓ Fresh data not marked stale")
        
        # Old data (10 days) should be stale
        result = source.get_ibd_metric('CVS', 'ibd_composite')
        assert result['stale'] == True, f"10-day-old data should be stale"
        print(f"✓ 10-day-old data marked stale")
        return True
    finally:
        temp_csv.unlink()


def test_missing_symbol():
    """Test handling of missing symbols."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        
        result = source.get_ibd_metric('NONEXISTENT', 'ibd_composite')
        assert result['value'] == 'NEEDS_RESEARCH', f"Expected NEEDS_RESEARCH, got {result['value']}"
        assert 'not in IBD import file' in result['reason'], f"Expected reason about missing symbol"
        print(f"✓ Missing symbol returns NEEDS_RESEARCH: {result['reason']}")
        return True
    finally:
        temp_csv.unlink()


def test_case_insensitive_lookup():
    """Test that symbol lookup is case-insensitive."""
    temp_csv = create_test_ibd_csv()
    try:
        source = IBDDataSource(temp_csv)
        
        # Test lowercase lookup
        result = source.get_ibd_metric('amzn', 'ibd_composite')
        assert result['value'] == 80
        
        # Test mixed case
        result = source.get_ibd_metric('AmZn', 'ibd_composite')
        assert result['value'] == 80
        print(f"✓ Case-insensitive symbol lookup works")
        return True
    finally:
        temp_csv.unlink()


def test_letter_conversions():
    """Test all letter-to-numeric conversions."""
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
        assert actual == expected_numeric, f"Failed for {letter}: expected {expected_numeric}, got {actual}"
        print(f"✓ {letter:3} → {actual:2}")
    
    return True


def test_real_ibd_csv():
    """Test with the actual IBD CSV file if it exists."""
    workspace = Path(__file__).parent.parent
    ibd_csv_path = workspace / "data" / "ibd_rankings_manual.csv"
    
    if not ibd_csv_path.exists():
        print(f"⚠️  Skipping real CSV test (not found at {ibd_csv_path})")
        return True
    
    try:
        source = IBDDataSource(ibd_csv_path)
        print(f"\n📊 Real IBD CSV Test")
        print(f"  Loaded symbols: {len(source.ibd_data)}")
        
        # Test a few symbols
        for symbol in list(source.ibd_data.keys())[:3]:
            result = source.get_ibd_metric(symbol, 'ibd_composite')
            print(f"  {symbol}: Composite={result['value']}, Stale={result['stale']}")
        
        return True
    except Exception as e:
        print(f"❌ Error testing real CSV: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("🧪 IBD Integration Tests (No Pytest)")
    print("="*80 + "\n")
    
    tests = [
        ("IBD Source Loading", test_ibd_source_loads),
        ("Numeric Ratings", test_numeric_ratings),
        ("Letter Ratings", test_letter_ratings),
        ("Plus Ratings Conversion", test_plus_ratings_conversion),
        ("Industry Rank", test_industry_rank),
        ("Stale Flag Logic", test_stale_flag),
        ("Missing Symbol Handling", test_missing_symbol),
        ("Case-Insensitive Lookup", test_case_insensitive_lookup),
        ("Letter-to-Numeric Conversions", test_letter_conversions),
        ("Real IBD CSV File", test_real_ibd_csv),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        print(f"\n🔧 {name}")
        print("-" * 40)
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n" + "="*80)
    print(f"✅ RESULTS: {passed} passed, {failed} failed")
    print(f"="*80 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
