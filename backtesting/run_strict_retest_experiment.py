"""Run a backtest-only strict SPY break-retest-continuation experiment."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtesting.alpaca_full_backtest import run_alpaca_full_backtest


@dataclass
class PendingBreak:
    direction: str
    breakout_close: float


class StrictRetestSelector:
    """Require an initial break, pullback, then reclaim/rejection before entry."""

    def __init__(self) -> None:
        self.pending: Dict[str, PendingBreak] = {}

    def __call__(
        self,
        signal: Dict[str, Any],
        history: List[Dict[str, Any]],
    ) -> Optional[Tuple[str, int, List[str]]]:
        close = float(signal["close"])
        previous_close = float(history[-1]["close"]) if history else close
        direction = self._retest_direction(signal, previous_close)
        self._record_breaks(signal)
        if direction is None:
            return None
        score = int(signal[f"{direction.lower()}_score"] or 0)
        return direction, score, list(signal.get(f"{direction.lower()}_reasons", [])) + ["strict_retest_confirmation"]

    def _retest_direction(self, signal: Dict[str, Any], previous_close: float) -> Optional[str]:
        for direction in ("CALL", "PUT"):
            pending = self.pending.get(direction)
            if pending is None:
                continue
            prefix = direction.lower()
            score = int(signal.get(f"{prefix}_score", 0) or 0)
            qualified = bool(signal.get(f"{prefix}_qualified", False))
            above_vwap = bool(signal.get("price_above_vwap", False))
            close = float(signal["close"])
            if direction == "CALL":
                confirmed = above_vwap and previous_close < pending.breakout_close and close >= pending.breakout_close
            else:
                confirmed = (not above_vwap) and previous_close > pending.breakout_close and close <= pending.breakout_close
            if qualified and score >= 7 and confirmed:
                self.pending.pop(direction, None)
                return direction
        return None

    def _record_breaks(self, signal: Dict[str, Any]) -> None:
        close = float(signal["close"])
        for direction, breakout_reason in (("CALL", "breaks_prev_high"), ("PUT", "breaks_prev_low")):
            prefix = direction.lower()
            reasons = set(signal.get(f"{prefix}_reasons", []))
            is_vwap_aligned = bool(signal.get("price_above_vwap", False)) == (direction == "CALL")
            if breakout_reason in reasons and is_vwap_aligned:
                self.pending[direction] = PendingBreak(direction=direction, breakout_close=close)


def _metrics(frame: pd.DataFrame) -> Dict[str, Any]:
    pnl = frame["option_pnl_dollars"].dropna().astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    return {
        "official_trades": int(len(pnl)),
        "net_pnl": round(float(pnl.sum()), 2),
        "win_rate_pct": round(float((pnl > 0).mean() * 100), 2) if len(pnl) else 0.0,
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if len(losses) else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the backtest-only strict retest experiment")
    parser.add_argument("--data", required=True, help="SPY one-minute OHLCV CSV")
    parser.add_argument("--cache-root", default="data/historical/options/alpaca")
    parser.add_argument("--output-dir", default="backtesting/output/strict_retest")
    parser.add_argument("--holdout-start", default="2026-07-06")
    args = parser.parse_args()

    result = run_alpaca_full_backtest(
        spy_csv_path=args.data,
        call_threshold=7,
        put_threshold=7,
        max_hold_minutes=15,
        max_trades_per_day=1,
        cache_root=args.cache_root,
        output_dir=args.output_dir,
        entry_selector=StrictRetestSelector(),
        progress_callback=print,
    )
    trades = pd.read_csv(result["files"]["trades"])
    official = trades[(trades["excluded_from_official"] == False) & trades["option_pnl_dollars"].notna()].copy()
    official["entry_date"] = pd.to_datetime(official["entry_fill_time"]).dt.date.astype(str)
    development = official[official["entry_date"] < args.holdout_start]
    holdout = official[official["entry_date"] >= args.holdout_start]
    report = {
        "experiment": "strict_retest_backtest_only",
        "rule": "score >= 7; initial VWAP-aligned break; pullback; reclaim/rejection; one position; 15-minute maximum hold",
        "holdout_start": args.holdout_start,
        "development": _metrics(development),
        "holdout": _metrics(holdout),
        "combined": _metrics(official),
        "engine_summary": result["summary"],
    }
    output_path = Path(args.output_dir) / "strict_retest_holdout_report.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())