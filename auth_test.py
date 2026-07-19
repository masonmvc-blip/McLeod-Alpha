import os
from dotenv import load_dotenv
from schwab.auth import easy_client

load_dotenv()

APP_KEY = os.getenv("SCHWAB_APP_KEY")
APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
CALLBACK_URL = os.getenv("SCHWAB_CALLBACK_URL")
CONFIGURED_ACCOUNT = os.getenv("SCHWAB_ACCOUNT_NUMBER")
CONFIGURED_HASH = os.getenv("SCHWAB_ACCOUNT_HASH")
TOKEN_PATH = "token.json"

if not APP_KEY or not APP_SECRET or not CALLBACK_URL:
    raise SystemExit("Missing SCHWAB_APP_KEY, SCHWAB_APP_SECRET, or SCHWAB_CALLBACK_URL in .env")

print("=" * 80)
print("SCHWAB ACCOUNT VERIFICATION TEST")
print("=" * 80)

print("\nStarting Schwab login...")
client = easy_client(
    api_key=APP_KEY,
    app_secret=APP_SECRET,
    callback_url=CALLBACK_URL,
    token_path=TOKEN_PATH,
    enforce_enums=False,
)

print("Connected. Retrieving account information...")
response = client.get_account_numbers()
response.raise_for_status()

accounts = response.json()

print("\n" + "=" * 80)
print("AVAILABLE ACCOUNTS:")
print("=" * 80)

for acc in accounts:
    account_num = acc.get('accountNumber')
    account_hash = acc.get('hashValue')
    print(f"\n  Account Number: {account_num}")
    print(f"  Account Hash:   {account_hash}")

print("\n" + "=" * 80)
print("CONFIGURED ACCOUNT:")
print("=" * 80)

if CONFIGURED_ACCOUNT and CONFIGURED_HASH:
    print(f"\n  Configured Account: {CONFIGURED_ACCOUNT}")
    print(f"  Configured Hash:    {CONFIGURED_HASH}")
    
    # Verify configured account exists
    account_hashes = {acc["accountNumber"]: acc["hashValue"] for acc in accounts}
    
    if CONFIGURED_ACCOUNT in account_hashes:
        print(f"\n  ✓ Account {CONFIGURED_ACCOUNT} EXISTS in Schwab")
        
        if account_hashes[CONFIGURED_ACCOUNT] == CONFIGURED_HASH:
            print(f"  ✓ Hash matches configured value")
            print(f"  ✓ READY FOR LIVE TRADING")
        else:
            print(f"\n  ✗ HASH MISMATCH!")
            print(f"    Expected: {CONFIGURED_HASH}")
            print(f"    Actual:   {account_hashes[CONFIGURED_ACCOUNT]}")
            print(f"    Action: Update .env with correct hash")
    else:
        print(f"\n  ✗ Account {CONFIGURED_ACCOUNT} NOT FOUND in Schwab!")
        print(f"  Available accounts: {', '.join(account_hashes.keys())}")
else:
    print(f"\n  ✗ No account configured in .env")
    print(f"    SCHWAB_ACCOUNT_NUMBER: {CONFIGURED_ACCOUNT or 'NOT SET'}")
    print(f"    SCHWAB_ACCOUNT_HASH: {CONFIGURED_HASH or 'NOT SET'}")
    print(f"    Action: Add account configuration to .env")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80 + "\n")

