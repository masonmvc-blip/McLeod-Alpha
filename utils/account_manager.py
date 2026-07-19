"""
Account management utilities - handles account number to nickname mapping.
Supports automatic syncing from Schwab API and manual configuration.
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

# Account nicknames configuration file
ACCOUNT_NICKNAMES_FILE = Path(__file__).parent.parent / "config" / "account_nicknames.json"


class AccountManager:
    """Manages account number to nickname mapping."""
    
    _nicknames_cache = None
    _last_loaded = None
    
    @classmethod
    def _load_nicknames(cls) -> Dict[str, str]:
        """Load account nicknames from configuration file."""
        if cls._nicknames_cache is not None:
            return cls._nicknames_cache
        
        # Try to load from config file
        if ACCOUNT_NICKNAMES_FILE.exists():
            try:
                with open(ACCOUNT_NICKNAMES_FILE) as f:
                    data = json.load(f)
                cls._nicknames_cache = data.get("accounts", {})
                cls._last_loaded = datetime.now()
                return cls._nicknames_cache
            except Exception as e:
                print(f"Warning: Could not load account nicknames: {e}")
        
        # Try to load from environment variables (ACCOUNT_NICKNAME_XXX format)
        nicknames = {}
        for key, value in os.environ.items():
            if key.startswith("ACCOUNT_NICKNAME_"):
                account_num = key.replace("ACCOUNT_NICKNAME_", "")
                nicknames[account_num] = value
        
        cls._nicknames_cache = nicknames
        cls._last_loaded = datetime.now()
        return cls._nicknames_cache
    
    @classmethod
    def get_nickname(cls, account_number: str) -> str:
        """
        Get nickname for an account number.
        
        Args:
            account_number: Schwab account number (e.g., "33310903")
        
        Returns:
            Account nickname if configured, otherwise returns account number
        """
        nicknames = cls._load_nicknames()
        # Try exact match first
        if account_number in nicknames:
            return nicknames[account_number]
        
        # Try last 2-3 digits for abbreviated matches
        last_3 = account_number[-3:] if len(account_number) >= 3 else account_number
        for acct, nickname in nicknames.items():
            if acct.endswith(last_3):
                return nickname
        
        # No nickname found, return original account number
        return account_number
    
    @classmethod
    def get_display_name(cls, account_number: str) -> str:
        """
        Get display name for account (nickname or number).
        
        Args:
            account_number: Schwab account number
        
        Returns:
            Formatted display name: "Nickname (XXX903)" or just "33310903" if no nickname
        """
        nickname = cls.get_nickname(account_number)
        if nickname != account_number:
            # Show last 3 digits for clarity
            last_3 = account_number[-3:]
            return f"{nickname} ({last_3})"
        return account_number
    
    @classmethod
    def set_nickname(cls, account_number: str, nickname: str) -> None:
        """
        Set nickname for an account number (persists to config file).
        
        Args:
            account_number: Schwab account number
            nickname: Friendly nickname
        """
        # Ensure config directory exists
        ACCOUNT_NICKNAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing nicknames
        nicknames = cls._load_nicknames().copy()
        nicknames[account_number] = nickname
        
        # Save to config file
        config_data = {"accounts": nicknames, "updated": datetime.now().isoformat()}
        with open(ACCOUNT_NICKNAMES_FILE, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        # Update cache
        cls._nicknames_cache = nicknames
    
    @classmethod
    def get_all_mappings(cls) -> Dict[str, str]:
        """Get all configured account number to nickname mappings."""
        return cls._load_nicknames().copy()
    
    @classmethod
    def refresh_from_schwab(cls, schwab_client) -> Dict[str, str]:
        """
        Attempt to fetch account information from Schwab API.
        Note: Schwab API may not provide account nicknames in get_account_numbers().
        
        Args:
            schwab_client: Initialized Schwab client
        
        Returns:
            Dictionary of account number to available info
        """
        try:
            response = schwab_client.get_account_numbers()
            response.raise_for_status()
            accounts = response.json()
            
            account_info = {}
            for account in accounts:
                account_num = account.get('accountNumber')
                # Schwab API typically doesn't include nickname in get_account_numbers()
                # You would need to check the web UI or account settings for nicknames
                account_info[account_num] = account.get('hashValue', '')
            
            return account_info
        except Exception as e:
            print(f"Error fetching account info from Schwab: {e}")
            return {}
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear the cached nicknames (will reload from file on next access)."""
        cls._nicknames_cache = None
        cls._last_loaded = None


def get_account_display_name(account_number: str) -> str:
    """
    Convenience function to get display name for an account.
    
    Args:
        account_number: Schwab account number
    
    Returns:
        Display name with nickname if available
    """
    return AccountManager.get_display_name(account_number)


def get_account_nickname(account_number: str) -> str:
    """
    Convenience function to get nickname for an account.
    
    Args:
        account_number: Schwab account number
    
    Returns:
        Nickname if configured, otherwise account number
    """
    return AccountManager.get_nickname(account_number)
