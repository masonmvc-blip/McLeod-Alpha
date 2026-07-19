import csv
import os
from datetime import datetime
from pathlib import Path

TODAY = datetime.now().strftime("%Y-%m-%d")
DAY_DIR = Path("data") / TODAY
DAY_DIR.mkdir(parents=True, exist_ok=True)

SIGNALS_FILE = DAY_DIR / "signals.csv"

FIELDS = [
    "timestamp","symbol","price","call_score","put_score",
    "call_pushes","put_pushes","ema10","ema20","ema50",
    "vwap","macd_hist","window","decision"
]

def log_signal(row):
    exists = SIGNALS_FILE.exists()
    with open(SIGNALS_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in FIELDS})
