#!/usr/bin/env python3
"""
Portfolio Sync - Download and sync portfolio data from Schwab API
Enhanced with comprehensive portfolio analytics and position tracking
Reuses existing project authentication and structure
"""

import json
import os
import csv
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from schwab.auth import easy_client
from schwab.client import Client

# Import account manager
from utils.account_manager import AccountManager

# Project configuration
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
TOKEN_PATH = PROJECT_ROOT / "token.json"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

# Output file paths
PORTFOLIO_JSON_FILE = DATA_DIR / "schwab_portfolio_latest.json"
POSITIONS_CSV_FILE = DATA_DIR / "schwab_positions_latest.csv"
SUMMARY_JSON_FILE = DATA_DIR / "schwab_portfolio_summary_latest.json"
SECTOR_MAPPING_FILE = CONFIG_DIR / "sector_mapping.json"

# Load optional account configuration from environment
SCHWAB_ACCOUNT_HASH = os.getenv("SCHWAB_ACCOUNT_HASH")  # Optional - will auto-select if not set
SCHWAB_ACCOUNT_NUMBER = os.getenv("SCHWAB_ACCOUNT_NUMBER")  # Will be determined


def load_sector_mapping():
    """Load sector mapping from config file"""
    if SECTOR_MAPPING_FILE.exists():
        try:
            with open(SECTOR_MAPPING_FILE, 'r') as f:
                mapping = json.load(f)
            return mapping
        except Exception as e:
            print(f"ERROR loading sector mapping: {e}")
            return {}
    return {}


# Load sector mapping from config
SECTOR_MAPPING = load_sector_mapping()


def get_stock_sector_and_themes(symbol):
    """Get sector for a stock symbol from the sector mapping"""
    sector = "OTHER"
    themes = []
    
    symbol_upper = symbol.upper()
    
    # Check each sector in the mapping
    for sector_name, symbols_list in SECTOR_MAPPING.items():
        if symbol_upper in symbols_list:
            sector = sector_name
            themes.append(sector_name)
            break
    
    return sector, themes


def calculate_position_weight(market_value, total_market_value):
    """Calculate portfolio weight percentage"""
    if total_market_value <= 0:
        return 0.0
    return (market_value / total_market_value) * 100


def calculate_margin_requirement(market_value, asset_type="EQUITY"):
    """
    Calculate margin requirement for a position
    Standard requirement is 50% for equities, varies for options
    """
    if asset_type == "OPTION":
        return market_value * 0.25  # Lower requirement for margin calls on options
    elif asset_type == "EQUITY":
        return market_value * 0.5   # 50% requirement for equities
    else:
        return market_value * 0.5


def calculate_liquidity_score(market_value, avg_daily_volume=None, bid_ask_spread=None):
    """
    Calculate liquidity score (0-100)
    Higher market value = more liquid
    Narrow bid/ask = more liquid
    High volume = more liquid
    """
    score = 50  # Base score
    
    # Market value component (0-30 points)
    if market_value > 100000:
        score += 30
    elif market_value > 50000:
        score += 20
    elif market_value > 10000:
        score += 10
    
    # Average daily volume component (0-20 points)
    if avg_daily_volume and avg_daily_volume > 1000000:
        score += 20
    elif avg_daily_volume and avg_daily_volume > 500000:
        score += 15
    elif avg_daily_volume and avg_daily_volume > 100000:
        score += 10
    
    # Bid/ask spread component (0-20 points)
    if bid_ask_spread is not None:
        if bid_ask_spread < 0.01:
            score += 20
        elif bid_ask_spread < 0.05:
            score += 15
        elif bid_ask_spread < 0.10:
            score += 10
    
    return min(score, 100)


def calculate_portfolio_metrics(account_details, positions):
    """Calculate comprehensive portfolio metrics"""
    total_market_value = account_details.get("total_market_value", 0)
    cash = account_details.get("cash_balance", 0)
    equity = account_details.get("equity", 0)
    
    # Separate equities and options
    equity_market_value = sum(p.get("market_value", 0) for p in positions if p.get("asset_type") == "EQUITY")
    option_market_value = sum(p.get("market_value", 0) for p in positions if p.get("asset_type") == "OPTION")
    
    metrics = {
        "total_account_value": total_market_value + cash,
        "total_market_value": total_market_value,
        "equity_market_value": equity_market_value,
        "option_market_value": option_market_value,
        "cash_balance": cash,
        "cash_percentage": (cash / (total_market_value + cash) * 100) if (total_market_value + cash) > 0 else 0,
        "buying_power": account_details.get("buying_power", 0),
        "available_funds": account_details.get("available_funds", 0),
        "maintenance_requirement": account_details.get("maintenance_requirement", 0),
        "equity": equity,
        "equity_percentage": (equity / (total_market_value + cash) * 100) if (total_market_value + cash) > 0 else 0,
    }
    
    # Margin efficiency score (buying power / total account value)
    if metrics["total_account_value"] > 0:
        metrics["margin_efficiency_score"] = (
            metrics["buying_power"] / metrics["total_account_value"] * 100
        )
    else:
        metrics["margin_efficiency_score"] = 0
    
    return metrics


def calculate_sector_concentration(positions):
    """Calculate sector concentration in portfolio"""
    if not positions:
        return {}
    
    total_market_value = sum(p.get("market_value", 0) for p in positions)
    if total_market_value <= 0:
        return {}
    
    sector_totals = {}
    theme_totals = {}
    
    for pos in positions:
        symbol = pos.get("symbol", "")
        market_value = pos.get("market_value", 0)
        
        sector, themes = get_stock_sector_and_themes(symbol)
        
        # Add to sector
        if sector not in sector_totals:
            sector_totals[sector] = 0
        sector_totals[sector] += market_value
        
        # Add to themes
        for theme in themes:
            if theme not in theme_totals:
                theme_totals[theme] = 0
            theme_totals[theme] += market_value
    
    # Convert to percentages
    sector_concentration = {
        sector: (value / total_market_value * 100)
        for sector, value in sorted(sector_totals.items(), key=lambda x: x[1], reverse=True)
    }
    
    theme_concentration = {
        theme: (value / total_market_value * 100)
        for theme, value in sorted(theme_totals.items(), key=lambda x: x[1], reverse=True)
    }
    
    return {
        "sectors": sector_concentration,
        "themes": theme_concentration,
    }


def calculate_top_concentration(positions, count=5):
    """Calculate top N position concentration"""
    if not positions:
        return {}
    
    total_market_value = sum(p.get("market_value", 0) for p in positions)
    if total_market_value <= 0:
        return {}
    
    # Sort by market value
    sorted_positions = sorted(
        positions, 
        key=lambda x: x.get("market_value", 0), 
        reverse=True
    )[:count]
    
    top_concentration = {}
    total_top_value = 0
    
    for pos in sorted_positions:
        symbol = pos.get("symbol", "")
        market_value = pos.get("market_value", 0)
        weight = (market_value / total_market_value * 100) if total_market_value > 0 else 0
        top_concentration[symbol] = {
            "market_value": market_value,
            "weight_percent": weight,
            "quantity": pos.get("quantity", 0),
        }
        total_top_value += market_value
    
    top_concentration["top_concentration_total_percent"] = (
        (total_top_value / total_market_value * 100) if total_market_value > 0 else 0
    )
    
    return top_concentration


def initialize_client():
    """Initialize Schwab API client using project authentication"""
    try:
        client = easy_client(
            api_key=os.getenv("SCHWAB_APP_KEY"),
            app_secret=os.getenv("SCHWAB_APP_SECRET"),
            callback_url=os.getenv("SCHWAB_CALLBACK_URL"),
            token_path=str(TOKEN_PATH),
            enforce_enums=False,
        )
        
        print(f"✓ Client initialized")
        return client
        
    except Exception as e:
        raise SystemExit(f"ERROR initializing Schwab client: {e}")


def select_account(client):
    """
    Select the Schwab account to use.
    If SCHWAB_ACCOUNT_HASH is set in .env, use that.
    Otherwise, auto-select the account with the largest liquidation value.
    Returns: (account_hash, account_number, account_type, account_info)
    """
    try:
        # Use the fields parameter to get positions data
        resp = client.get_accounts(fields=[Client.Account.Fields.POSITIONS])
        resp.raise_for_status()
        accounts = resp.json()
        
        print(f"\n📋 Available Schwab Accounts:")
        print("="*80)
        
        if not accounts:
            raise SystemExit("No accounts found")
        
        # If SCHWAB_ACCOUNT_HASH is explicitly set in .env, find and use that account
        if SCHWAB_ACCOUNT_HASH and SCHWAB_ACCOUNT_NUMBER:
            for account in accounts:
                account_info = account.get("securitiesAccount", {})
                account_num = account_info.get("accountNumber", "")
                if account_num == SCHWAB_ACCOUNT_NUMBER:
                    positions = account_info.get("positions", [])
                    liquidation_value = account_info.get("currentBalances", {}).get("liquidationValue", 0)
                    print(f"  Using configured account: {SCHWAB_ACCOUNT_NUMBER}")
                    print(f"    Type: {account_info.get('type', 'N/A')}")
                    print(f"    Liquidation Value: ${liquidation_value:,.2f}")
                    print(f"    Positions: {len(positions)}")
                    print("="*80)
                    # Get the hash from the account structure or use the configured one
                    account_hash = account.get("hashValue") or SCHWAB_ACCOUNT_HASH
                    return account_hash, SCHWAB_ACCOUNT_NUMBER, account_info.get("type", ""), account
            
            # Debug: print what accounts we got
            print(f"ERROR: Configured account {SCHWAB_ACCOUNT_NUMBER} not found")
            available_nums = [acc.get("securitiesAccount", {}).get("accountNumber", "N/A") for acc in accounts]
            print(f"Available account numbers: {available_nums}")
            print("="*80)
            raise SystemExit(f"Configured account {SCHWAB_ACCOUNT_NUMBER} not found")
        
        # Auto-select the account with the largest liquidation value
        best_account = None
        best_liquidation = -1
        best_hash = None
        best_number = None
        best_type = None
        
        for i, account in enumerate(accounts, 1):
            account_info = account.get("securitiesAccount", {})
            positions = account_info.get("positions", [])
            liquidation_value = account_info.get("currentBalances", {}).get("liquidationValue", 0)
            account_number = account_info.get("accountNumber", "N/A")
            account_hash = account.get("hashValue", "")
            account_type = account_info.get("type", "N/A")
            
            # Mask the account number for display
            masked = f"****{account_number[-4:]}" if account_number != "N/A" and len(account_number) >= 4 else account_number
            
            print(f"  {i}. {masked:10} | Type: {account_type:8} | Value: ${liquidation_value:>12,.2f} | Positions: {len(positions):3}")
            
            if liquidation_value > best_liquidation:
                best_liquidation = liquidation_value
                best_account = account
                best_hash = account_hash
                best_number = account_number
                best_type = account_type
        
        print("="*80)
        print(f"✓ Selected account with largest value: {best_number} (${best_liquidation:,.2f})")
        print("="*80)
        
        return best_hash, best_number, best_type, best_account
        
    except Exception as e:
        raise SystemExit(f"ERROR selecting account: {e}")


def get_account_details(client, account_hash, account_number, account_data):
    """Get account details including cash, buying power, margin requirements"""
    try:
        # Use the account data we already have from get_accounts
        account = account_data
        
        account_details = {
            "account_number": account_number,
            "sync_timestamp": datetime.now().isoformat(),
        }
        
        # Extract account balances from response
        if "securitiesAccount" in account:
            sec_acct = account["securitiesAccount"]
            
            # Add full account data for debugging
            account_details["account_type"] = sec_acct.get("type", "")
            
            # Use currentBalances (correct field structure)
            if "currentBalances" in sec_acct:
                balances = sec_acct["currentBalances"]
                # Portfolio value is liquidationValue (total market value)
                account_details["portfolio_value"] = balances.get("liquidationValue", 0)
                # Investment holdings
                account_details["long_market_value"] = balances.get("longMarketValue", 0)
                account_details["short_market_value"] = balances.get("shortMarketValue", 0)
                account_details["total_market_value"] = (
                    balances.get("longMarketValue", 0) + 
                    balances.get("shortMarketValue", 0)
                )
                # Cash and margin balance
                cash_balance = balances.get("cashBalance", 0)
                margin_balance = balances.get("marginBalance", 0)
                
                # For margin accounts with negative margin balance, show the margin balance
                # (e.g., -$72,500 means you've borrowed that amount)
                if sec_acct.get("type") in ["MARGIN", "MARGIN_IRA"] and margin_balance < 0 and cash_balance == 0:
                    account_details["cash_balance"] = margin_balance
                    account_details["cash_type"] = "margin_borrowed"
                else:
                    account_details["cash_balance"] = cash_balance
                    account_details["cash_type"] = "cash" if cash_balance >= 0 else "negative_cash"
                
                account_details["buying_power"] = balances.get("buyingPower", 0)
                account_details["available_funds"] = balances.get("availableFunds", 0)
                account_details["equity"] = balances.get("equity", 0)
                # Margin info
                account_details["margin_balance"] = balances.get("marginBalance", 0)
                account_details["maintenance_requirement"] = balances.get("maintenanceRequirement", 0)
                # Options
                account_details["long_option_value"] = balances.get("longOptionMarketValue", 0)
                account_details["short_option_value"] = balances.get("shortOptionMarketValue", 0)
            
            # Account details
            if "accountStatus" in sec_acct:
                account_details["account_status"] = sec_acct["accountStatus"]
            
            # Day trading buying power if available
            if "dayTradingBuyingPower" in sec_acct:
                account_details["day_trading_buying_power"] = sec_acct["dayTradingBuyingPower"]
        
        return account_details
    
    except Exception as e:
        print(f"ERROR getting account details: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_positions(client, account_hash, account_data):
    """Get current positions from account"""
    try:
        positions = []
        
        if "securitiesAccount" in account_data:
            sec_acct = account_data["securitiesAccount"]
            
            if "positions" in sec_acct:
                for pos in sec_acct["positions"]:
                    symbol = pos.get("instrument", {}).get("symbol", "")
                    asset_type = pos.get("instrument", {}).get("assetType", "EQUITY")
                    market_value = pos.get("marketValue", 0)
                    quantity = pos.get("longQuantity", 0) - pos.get("shortQuantity", 0)
                    
                    # Get sector and themes
                    sector, themes = get_stock_sector_and_themes(symbol)
                    
                    position_data = {
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "quantity": quantity,
                        "long_quantity": pos.get("longQuantity", 0),
                        "short_quantity": pos.get("shortQuantity", 0),
                        "market_value": market_value,
                        "average_price": pos.get("averagePrice", 0),
                        "current_price": market_value / max(quantity, 1) if quantity != 0 else 0,
                        "day_pl": pos.get("currentDayProfitLoss", 0),
                        "day_pl_pct": pos.get("currentDayProfitLossPct", 0),
                        "sector": sector,
                        "themes": themes,
                        "portfolio_weight_percent": 0,
                        "margin_requirement": calculate_margin_requirement(market_value, asset_type),
                        "liquidity_score": calculate_liquidity_score(market_value),
                    }
                    positions.append(position_data)
        
        # Calculate portfolio weights
        total_market_value = sum(p.get("market_value", 0) for p in positions)
        for pos in positions:
            pos["portfolio_weight_percent"] = calculate_position_weight(
                pos.get("market_value", 0), 
                total_market_value
            )
        
        return positions
    
    except Exception as e:
        print(f"ERROR getting positions: {e}")
        return []


def get_margin_requirements(account_data):
    """Get margin requirements and calculations from account data"""
    try:
        margin_info = {
            "margin_account": False,
            "initial_margin_requirement": 0,
            "maintenance_margin_requirement": 0,
            "excess_margin": 0,
            "margin_balance": 0,
        }
        
        if "securitiesAccount" in account_data:
            sec_acct = account_data["securitiesAccount"]
            
            # Check if margin account
            margin_info["margin_account"] = sec_acct.get("type") in ["MARGIN", "MARGIN_IRA"]
            
            # Margin details if available
            if "marginBalance" in sec_acct:
                margin_balance = sec_acct["marginBalance"]
                margin_info["margin_balance"] = margin_balance.get("marginBalance", 0)
                margin_info["excess_margin"] = margin_balance.get("excessMargin", 0)
        
        return margin_info
    
    except Exception as e:
        print(f"ERROR getting margin requirements: {e}")
        return {}


def sync_portfolio(client):
    """Download and sync all portfolio data with comprehensive analytics"""
    print("\n" + "="*70)
    print("📊 PORTFOLIO SYNC - Downloading Schwab portfolio data...")
    print("="*70)
    
    # Select the account to use
    print("\nSelecting account...")
    account_hash, account_number, account_type, account_data = select_account(client)
    
    # Get account details
    print("Fetching account details...")
    account_details = get_account_details(client, account_hash, account_number, account_data)
    
    # Get positions
    print("Fetching positions...")
    positions = get_positions(client, account_hash, account_data)
    
    # Get margin requirements
    print("Fetching margin requirements...")
    margin_info = get_margin_requirements(account_data)
    
    # Calculate metrics
    print("Calculating portfolio metrics...")
    portfolio_metrics = calculate_portfolio_metrics(account_details, positions)
    concentration = calculate_sector_concentration(positions)
    top_5 = calculate_top_concentration(positions, 5)
    
    # Combine into portfolio object
    equity_total = sum(p.get("market_value", 0) for p in positions if p.get("asset_type") == "EQUITY")
    option_total = sum(p.get("market_value", 0) for p in positions if p.get("asset_type") == "OPTION")
    portfolio = {
        "sync_timestamp": datetime.now().isoformat(),
        "account": account_details,
        "margin": margin_info,
        "metrics": portfolio_metrics,
        "positions_summary": {
            "total_positions": len(positions),
            "equity_positions": len([p for p in positions if p.get("asset_type") == "EQUITY"]),
            "option_positions": len([p for p in positions if p.get("asset_type") == "OPTION"]),
            "equity_market_value": equity_total,
            "option_market_value": option_total,
            "total_market_value": sum(p.get("market_value", 0) for p in positions),
            "total_day_pl": sum(p.get("day_pl", 0) for p in positions),
        },
        "positions": positions,
    }
    
    # Create summary object
    summary = {
        "sync_timestamp": datetime.now().isoformat(),
        "account_number": account_details.get("account_number", "N/A"),
        "account_type": account_details.get("account_type", "N/A"),
        "metrics": portfolio_metrics,
        "concentration": concentration,
        "top_5_positions": top_5,
        "positions_summary": {
            "total_positions": len(positions),
            "equity_positions": len([p for p in positions if p.get("asset_type") == "EQUITY"]),
            "option_positions": len([p for p in positions if p.get("asset_type") == "OPTION"]),
            "equity_market_value": portfolio_metrics.get("equity_market_value", 0),
            "option_market_value": portfolio_metrics.get("option_market_value", 0),
            "total_market_value": portfolio_metrics.get("total_market_value", 0),
            "total_day_pl": portfolio["positions_summary"]["total_day_pl"],
        },
    }
    
    # Save portfolio to JSON
    try:
        with open(PORTFOLIO_JSON_FILE, 'w') as f:
            json.dump(portfolio, f, indent=2)
        print(f"✓ Portfolio saved to {PORTFOLIO_JSON_FILE}")
    except Exception as e:
        print(f"ERROR saving portfolio JSON: {e}")
    
    # Save summary to JSON
    try:
        with open(SUMMARY_JSON_FILE, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"✓ Summary saved to {SUMMARY_JSON_FILE}")
    except Exception as e:
        print(f"ERROR saving summary JSON: {e}")
    
    # Save positions to CSV with enhanced fields
    try:
        if positions:
            # Get all unique keys from positions
            fieldnames = set()
            for pos in positions:
                fieldnames.update(pos.keys())
            fieldnames = sorted(list(fieldnames))
            
            with open(POSITIONS_CSV_FILE, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for pos in positions:
                    # Convert list fields (themes) to string for CSV
                    row = pos.copy()
                    if isinstance(row.get("themes"), list):
                        row["themes"] = ", ".join(row["themes"])
                    writer.writerow(row)
            print(f"✓ Positions saved to {POSITIONS_CSV_FILE}")
        else:
            print("ℹ️  No positions to save to CSV")
    except Exception as e:
        print(f"ERROR saving positions CSV: {e}")
    
    # Print comprehensive summary
    print("\n" + "="*70)
    print("📈 PORTFOLIO SUMMARY")
    print("="*70)
    
    print(f"\n💼 ACCOUNT INFORMATION")
    account_num = account_details.get('account_number', 'N/A')
    account_display = AccountManager.get_display_name(account_num) if account_num != 'N/A' else account_num
    print(f"  Account: {account_display}")
    print(f"  Type: {account_details.get('account_type', 'N/A')}")
    
    print(f"\n💰 ACCOUNT VALUATION")
    print(f"  Total Account Value: ${portfolio_metrics.get('total_account_value', 0):,.2f}")
    print(f"  Core Equity Investments: ${portfolio_metrics.get('equity_market_value', 0):,.2f}")
    print(f"  Option Positions: ${portfolio_metrics.get('option_market_value', 0):,.2f}")
    print(f"  Total Investments: ${portfolio_metrics.get('equity_market_value', 0) + portfolio_metrics.get('option_market_value', 0):,.2f}")
    print(f"  Cash Balance (Margin): ${portfolio_metrics.get('cash_balance', 0):,.2f} ({portfolio_metrics.get('cash_percentage', 0):.1f}%)")
    print(f"  Equity: ${portfolio_metrics.get('equity', 0):,.2f} ({portfolio_metrics.get('equity_percentage', 0):.1f}%)")
    
    print(f"\n📊 LIQUIDITY & MARGIN")
    print(f"  Available Funds: ${portfolio_metrics.get('available_funds', 0):,.2f}")
    print(f"  Buying Power: ${portfolio_metrics.get('buying_power', 0):,.2f}")
    print(f"  Maintenance Requirement: ${portfolio_metrics.get('maintenance_requirement', 0):,.2f}")
    print(f"  Margin Efficiency Score: {portfolio_metrics.get('margin_efficiency_score', 0):.1f}%")
    
    print(f"\n📍 POSITIONS & HOLDINGS")
    print(f"  Total Positions: {len(positions)}")
    print(f"  Total Position Value: ${portfolio['positions_summary']['total_market_value']:,.2f}")
    print(f"  Total Day P&L: ${portfolio['positions_summary']['total_day_pl']:,.2f}")
    
    if not positions and portfolio_metrics.get('total_market_value', 0) > 0:
        print(f"\n  ℹ️  Note: Positions data not available from this API endpoint.")
        print(f"     See detailed holdings at: https://client.schwab.com")
    
    # Show top 5
    if top_5:
        print(f"\n🔝 TOP 5 POSITIONS")
        total_top_pct = top_5.pop("top_concentration_total_percent", 0)
        for i, (symbol, data) in enumerate(list(top_5.items())[:5], 1):
            weight = data.get("weight_percent", 0)
            market_val = data.get("market_value", 0)
            qty = data.get("quantity", 0)
            print(f"  {i}. {symbol:6} | {weight:5.1f}% | ${market_val:>12,.0f} | Qty: {qty:>8}")
        print(f"  Total Top 5: {total_top_pct:.1f}% of portfolio")
    
    # Show sector concentration
    if concentration.get("sectors"):
        print(f"\n🏢 SECTOR CONCENTRATION")
        for sector, pct in sorted(concentration["sectors"].items(), key=lambda x: x[1], reverse=True):
            if pct >= 1:  # Only show sectors with >= 1%
                print(f"  {sector:15} | {pct:5.1f}%")
    
    # Show theme concentration
    if concentration.get("themes"):
        print(f"\n🎯 THEME CONCENTRATION")
        for theme, pct in sorted(concentration["themes"].items(), key=lambda x: x[1], reverse=True):
            if pct >= 1:  # Only show themes with >= 1%
                print(f"  {theme:15} | {pct:5.1f}%")
    
    print("\n" + "="*70)
    print(f"Last sync: {portfolio['sync_timestamp']}\n")
    
    return portfolio


def main():
    """Main entry point"""
    try:
        print(f"\n🔐 Initializing portfolio sync from {PROJECT_ROOT}")
        client = initialize_client()
        portfolio = sync_portfolio(client)
        print("✓ Portfolio sync completed successfully")
        
    except SystemExit as e:
        print(f"❌ {e}")
        return 1
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
