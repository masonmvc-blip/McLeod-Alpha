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

resp = client.get_quote("SPY")
resp.raise_for_status()

print(resp.json())
