import csv
import json
from pathlib import Path
from datetime import datetime

LOG_FILE = Path("logs/signals.csv")

def log_signal(price, regime, call_score, put_score, feature_payload=None):
    LOG_FILE.parent.mkdir(exist_ok=True)

    file_exists = LOG_FILE.exists()

    with LOG_FILE.open("a", newline="") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "timestamp",
                "price",
                "regime",
                "call_score",
                "put_score",
                "feature_payload",
            ])

        writer.writerow([
            datetime.now().isoformat(),
            price,
            regime,
            call_score,
            put_score,
            json.dumps(feature_payload) if feature_payload is not None else "",
        ])