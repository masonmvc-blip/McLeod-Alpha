#!/usr/bin/env python3
"""Backfill missing entry diagnostics from the persisted closed-candle history."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from phase3_monitor import (
    _build_entry_feature_payload,
    add_indicators,
    market_regime,
    score_call,
    score_put,
    volume_momentum,
)


DB_PATH = PROJECT_ROOT / "data" / "mcleod_alpha.db"
CANDLE_PATH = PROJECT_ROOT / "data" / "spy_1min_history.csv"
EASTERN_TZ = ZoneInfo("America/New_York")


def _entry_snapshot(candles, entry_time, direction):
    entry_dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
    if entry_dt.tzinfo is None:
        entry_dt = entry_dt.replace(tzinfo=EASTERN_TZ)
    entry_dt = entry_dt.astimezone(EASTERN_TZ)
    completed = candles[candles.index < entry_dt].tail(390).copy()
    if len(completed) < 15:
        return None

    indicators = add_indicators(completed.copy())
    last = indicators.iloc[-1]
    prev = indicators.iloc[-2]
    regime = market_regime(last, prev)
    call_score, call_reasons = score_call(last, prev)
    put_score, put_reasons = score_put(last, prev)
    volume = volume_momentum(indicators, emit_log=False)
    if volume["trend"] == "INCREASING":
        if float(last.close) > float(last.open):
            call_score += 1
            call_reasons.append("volume_confirming_bullish_move")
        elif float(last.close) < float(last.open):
            put_score += 1
            put_reasons.append("volume_confirming_bearish_move")
    elif volume["trend"] == "DECREASING":
        if float(last.close) > float(last.open):
            call_score -= 1
            call_reasons.append("volume_weakening_bullish_move")
        elif float(last.close) < float(last.open):
            put_score -= 1
            put_reasons.append("volume_weakening_bearish_move")

    return _build_entry_feature_payload(
        indicators, direction, regime, call_score, put_score, call_reasons, put_reasons
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(EASTERN_TZ).date().isoformat())
    args = parser.parse_args()

    candles = pd.read_csv(CANDLE_PATH)
    candles["datetime"] = pd.to_datetime(candles["datetime"], utc=True).dt.tz_convert(EASTERN_TZ)
    candles = candles.set_index("datetime").sort_index()

    updated = 0
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT id, entry_time, direction FROM trade_log
               WHERE substr(entry_time, 1, 10) = ?
                                 AND (feature_payload IS NULL OR trim(feature_payload) = ''
                                            OR instr(feature_payload, '"indicator_count"') = 0
                                            OR instr(feature_payload, '"vwap"') = 0
                                            OR instr(feature_payload, '"support_resistance"') = 0)""",
            (args.date,),
        ).fetchall()
        for row in rows:
            snapshot = _entry_snapshot(candles, row["entry_time"], row["direction"])
            if not snapshot:
                continue
            absorption = json.loads(snapshot).get("absorption_score")
            connection.execute(
                """UPDATE trade_log
                   SET feature_payload = ?, entry_diagnostic_snapshot = ?, absorption_score = ?
                   WHERE id = ?""",
                (snapshot, snapshot, absorption, row["id"]),
            )
            updated += 1
    print(f"Backfilled {updated} trade entry diagnostic snapshots for {args.date}.")


if __name__ == "__main__":
    main()