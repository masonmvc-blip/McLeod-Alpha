import os
from dotenv import load_dotenv
from schwab.auth import easy_client

load_dotenv()

client = easy_client(
    api_key=os.getenv("SCHWAB_APP_KEY"),
    app_secret=os.getenv("SCHWAB_APP_SECRET"),
    callback_url=os.getenv("SCHWAB_CALLBACK_URL"),
    token_path="token.json",
    enforce_enums=False,
)

resp = client.get_option_chain(
    symbol="SPY",
    contract_type="ALL",
    strike_count=10,
    strategy="SINGLE",
)

resp.raise_for_status()
data = resp.json()

print(data.keys())
print("Underlying:", data.get("underlyingPrice"))
print("Status:", data.get("status"))

print("Calls:", list(data.get("callExpDateMap", {}).keys())[:3])
print("Puts:", list(data.get("putExpDateMap", {}).keys())[:3])