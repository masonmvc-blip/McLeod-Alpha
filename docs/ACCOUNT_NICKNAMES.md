# Account Nickname Configuration Guide

## Overview

Account nicknames allow you to display friendly names instead of account numbers throughout the McLeod Alpha system. For example, display "Guaranteed Future (903)" instead of "33310903".

**Where Nicknames Are Used:**
- ✅ Cockpit Dashboard
- ✅ Morning CIO Report
- ✅ Portfolio Sync Output
- ✅ API Status Endpoints
- ✅ Console Output

## Configuration Methods

### Method 1: Configuration File (Recommended)

Nicknames are stored in `config/account_nicknames.json`:

```json
{
  "accounts": {
    "33310903": "Guaranteed Future",
    "12345678": "Trading Account",
    "87654321": "Retirement"
  },
  "updated": "2026-07-14T16:30:00",
  "notes": "..."
}
```

**To add a new nickname:**
1. Edit `config/account_nicknames.json`
2. Add entry under `"accounts"` object
3. Save file
4. Changes take effect immediately

### Method 2: Environment Variables

Set environment variables in `.env`:

```bash
ACCOUNT_NICKNAME_33310903=Guaranteed Future
ACCOUNT_NICKNAME_12345678=Trading Account
```

**Priority:** Config file takes precedence over environment variables

### Method 3: Programmatic (Python)

```python
from utils.account_manager import AccountManager

# Set a nickname
AccountManager.set_nickname("33310903", "Guaranteed Future")

# Get display name
display_name = AccountManager.get_display_name("33310903")
# Returns: "Guaranteed Future (903)"

# Get just the nickname
nickname = AccountManager.get_nickname("33310903")
# Returns: "Guaranteed Future"

# Get all mappings
all_nicknames = AccountManager.get_all_mappings()
# Returns: {"33310903": "Guaranteed Future", ...}

# Clear cache (reload from file)
AccountManager.clear_cache()
```

## Display Formats

### Full Display Name
Used in dashboards and reports:
```
Guaranteed Future (903)
    ↑ Nickname          ↑ Last 3 digits
```

### Short Display Name
Used when space is limited:
```
Guaranteed Future
```

### Account Number Only
When no nickname is configured:
```
33310903
```

## Automatic Updates from Schwab

The system supports automatic sync from Schwab API:

```python
from utils.account_manager import AccountManager
from schwab.auth import easy_client

# Initialize Schwab client
client = easy_client(...)

# Fetch account info from Schwab
account_info = AccountManager.refresh_from_schwab(client)
```

**Note:** Schwab's API typically doesn't include account nicknames in `get_account_numbers()`. You may need to:
1. Set nicknames manually in Schwab web interface
2. Configure them in McLeod using methods above
3. Or update manually as needed

## Files Affected

| File | Change | Notes |
|------|--------|-------|
| `cockpit.py` | Dashboard shows nickname | API endpoint includes account_nickname |
| `reports/morning_cio_report.py` | Header shows nickname | Replaces account number |
| `portfolio_sync.py` | Console output shows nickname | Runs during portfolio sync |
| `utils/account_manager.py` | New module | Handles all nickname logic |
| `config/account_nicknames.json` | New config file | Stores all mappings |

## Examples

### Example 1: Update Account Name

```python
from utils.account_manager import AccountManager

AccountManager.set_nickname("33310903", "Main Trading Account")
```

Result in Cockpit:
```
Trading Account: ✅ Main Trading Account (903)
```

### Example 2: Multiple Accounts

`config/account_nicknames.json`:
```json
{
  "accounts": {
    "33310903": "Guaranteed Future",
    "12345678": "Active Trading",
    "87654321": "Long-term Hold"
  }
}
```

Morning CIO Report output:
```
Account: Guaranteed Future (903) (MARGIN)
```

### Example 3: Dynamic Updates

```python
from utils.account_manager import AccountManager

# Check current nickname
current = AccountManager.get_nickname("33310903")

# Update if needed
if current != "Guaranteed Future":
    AccountManager.set_nickname("33310903", "Guaranteed Future")

# Verify
display = AccountManager.get_display_name("33310903")
print(f"Account now displays as: {display}")
# Output: Account now displays as: Guaranteed Future (903)
```

## Troubleshooting

### Nickname Not Showing

1. Check config file exists: `config/account_nicknames.json`
2. Verify JSON syntax is valid
3. Restart services:
   ```bash
   # Restart cockpit
   pkill -f cockpit.py
   python3 cockpit.py
   ```
4. Clear cache:
   ```python
   from utils.account_manager import AccountManager
   AccountManager.clear_cache()
   ```

### Wrong Nickname Displaying

1. Check for conflicts in config file
2. Verify account number format (should be exact string match)
3. Check for environment variable overrides in `.env`

### Performance

- Nicknames are cached in memory
- First lookup reads from file (very fast)
- Subsequent lookups use cache
- No performance impact on trading

## Best Practices

1. **Use Descriptive Names**
   - ✅ "Guaranteed Future", "Trading Account", "Long Hold"
   - ❌ "Account1", "A", "xxx"

2. **Keep Names Concise**
   - ✅ "Guaranteed Future", "Main Trading"
   - ❌ "This is my Schwab account used for guaranteed future monthly income strategies"

3. **Update Schwab UI Too**
   - When you rename in McLeod, update Schwab web interface
   - Keeps consistency across platforms

4. **Use Consistent Formatting**
   - Use title case: "Guaranteed Future" not "guaranteed future"
   - Use spaces instead of underscores

## Technical Details

### AccountManager Class

Located in `utils/account_manager.py`:

```python
class AccountManager:
    """Manages account number to nickname mapping."""
    
    @classmethod
    def get_nickname(account_number: str) -> str
    @classmethod
    def get_display_name(account_number: str) -> str
    @classmethod
    def set_nickname(account_number: str, nickname: str) -> None
    @classmethod
    def get_all_mappings() -> Dict[str, str]
    @classmethod
    def refresh_from_schwab(schwab_client) -> Dict[str, str]
    @classmethod
    def clear_cache() -> None
```

### Lookup Priority

1. Exact match in config file
2. Last 3 digits match in config file
3. Exact match in environment variables
4. Last 3 digits in environment variables
5. Return original account number

### Storage

- **Primary:** `config/account_nicknames.json` (persistent)
- **Secondary:** Environment variables (read-only, lowest priority)
- **Cache:** In-memory (cleared on cache clear or process restart)

## Questions?

The system is designed to be transparent and flexible. Nicknames are display-only - the underlying account number is always stored and used for API operations.
