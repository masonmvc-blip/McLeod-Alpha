import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSITION_FILE = PROJECT_ROOT / "data" / "open_position.json"

def save_position(position):
    POSITION_FILE.parent.mkdir(exist_ok=True)

    data = {
        "direction": position.direction,
        "entry_price": position.entry_price,
        "stop_price": position.stop_price,
        "target_price": position.target_price,
        "quantity": position.quantity,
        "opened": position.opened.isoformat(),
        "reason": position.reason,
        "option_symbol": position.option_symbol,
        "option_entry": position.option_entry,
        "option_delta": position.option_delta,
        "feature_payload": getattr(position, "feature_payload", ""),
        "option_stop": getattr(position, "option_stop", 0),
        "option_initial_stop": getattr(position, "option_initial_stop", 0),
        "schwab_order_id": getattr(position, "schwab_order_id", ""),
        "schwab_fill_price": getattr(position, "schwab_fill_price", 0.0),
        "schwab_fill_timestamp": getattr(position, "schwab_fill_timestamp", ""),
        "submitted_limit_price": getattr(position, "submitted_limit_price", 0.0),
        "protective_stop_order_id": getattr(position, "protective_stop_order_id", ""),
        "protective_stop_price": getattr(position, "protective_stop_price", 0.0),
        "protective_stop_status": getattr(position, "protective_stop_status", ""),
    }

    POSITION_FILE.write_text(json.dumps(data, indent=2))


def load_position(Position):
    if not POSITION_FILE.exists():
        return None

    data = json.loads(POSITION_FILE.read_text())
    data["opened"] = datetime.fromisoformat(data["opened"])

    pos = Position(**{
        k: data[k]
        for k in [
            "direction",
            "entry_price",
            "stop_price",
            "target_price",
            "quantity",
            "opened",
            "reason",
            "option_symbol",
            "option_entry",
            "option_delta",
        ]
    })

    pos.feature_payload = data.get("feature_payload", "")
    pos.option_stop = data.get("option_stop", 0)
    pos.option_initial_stop = data.get("option_initial_stop", 0)
    pos.schwab_order_id = data.get("schwab_order_id", "")
    pos.schwab_fill_price = data.get("schwab_fill_price", 0.0)
    pos.schwab_fill_timestamp = data.get("schwab_fill_timestamp", "")
    pos.submitted_limit_price = data.get("submitted_limit_price", 0.0)
    pos.protective_stop_order_id = data.get("protective_stop_order_id", "")
    pos.protective_stop_price = data.get("protective_stop_price", 0.0)
    pos.protective_stop_status = data.get("protective_stop_status", "")
    return pos


def clear_position():
    if POSITION_FILE.exists():
        POSITION_FILE.unlink()