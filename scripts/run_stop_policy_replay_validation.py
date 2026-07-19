#!/usr/bin/env python3
"""Deterministic replay harness for stop-policy validation.

Replays a synthetic option-price path through paper stop management and
emits a pass/fail matrix for each profit-zone stop rule.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import execution.paper_engine as paper_engine


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "reports"
OUT_FILE = OUT_DIR / "stop_policy_validation_matrix.md"


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 7, 17, 10, 0, 0)
        if tz is not None:
            return base.replace(tzinfo=tz)
        return base


def _build_position(entry: float = 5.0) -> paper_engine.Position:
    return paper_engine.Position(
        direction="CALL",
        entry_price=500.0,
        stop_price=495.0,
        target_price=510.0,
        quantity=1,
        opened=datetime(2026, 7, 17, 9, 50, 0),
        reason="REPLAY_VALIDATION",
        option_symbol="SPY_TEST",
        option_entry=entry,
        option_delta=0.5,
        option_stop=0.0,
        option_initial_stop=0.0,
    )


def _expected_stop(entry: float, trigger_price: float) -> float:
    pnl_pct = ((trigger_price - entry) / entry) * 100.0
    if pnl_pct >= 8.0:
        return trigger_price * 0.99
    if pnl_pct >= 7.0:
        return trigger_price * 0.985
    if pnl_pct >= 6.0:
        return trigger_price * 0.98
    if pnl_pct >= 5.0:
        return trigger_price * 0.975
    if pnl_pct >= 4.0:
        return trigger_price * 0.97
    if pnl_pct >= 3.0:
        return entry * 0.99
    if pnl_pct >= 2.0:
        return entry * 0.97
    return entry * 0.95


def _run_replay() -> List[Dict[str, object]]:
    entry = 5.0
    marks = [5.00, 5.101, 5.151, 5.201, 5.251, 5.301, 5.351, 5.401]

    # Patch paper engine for deterministic, side-effect-free replay.
    paper_engine.datetime = _FixedDateTime
    paper_engine.save_position = lambda _pos: None
    paper_engine.close_trade = lambda *_args, **_kwargs: False

    rows: List[Dict[str, object]] = []

    for mark in marks:
        pos = _build_position(entry=entry)
        paper_engine.current_position = pos
        paper_engine.load_position = lambda _cls, _pos=pos: _pos

        paper_engine.manage_trade(price=500.0, option_mark=mark, option_bid=mark)

        expected = _expected_stop(entry, mark)
        actual = float(pos.option_stop)
        passed = abs(actual - expected) < 1e-6

        pnl_pct = ((mark - entry) / entry) * 100.0
        zone = "Entry" if pnl_pct < 2 else f">= +{pnl_pct:.1f}%"

        rows.append(
            {
                "zone": zone,
                "trigger": mark,
                "expected": expected,
                "actual": actual,
                "pass": passed,
            }
        )

    return rows


def _to_markdown(rows: List[Dict[str, object]]) -> str:
    total = len(rows)
    passed = sum(1 for r in rows if r["pass"])
    failed = total - passed

    lines = [
        "# Stop Policy Replay Validation Matrix",
        "",
        "Deterministic replay using `execution/paper_engine.py` with synthetic trigger prices.",
        "",
        f"Summary: {passed}/{total} passed, {failed} failed.",
        "",
        "| Profit Zone | Trigger Price | Expected Stop | Actual Stop | Pass |",
        "|---|---:|---:|---:|:---:|",
    ]

    for row in rows:
        lines.append(
            f"| {row['zone']} | ${row['trigger']:.3f} | ${row['expected']:.6f} | ${row['actual']:.6f} | {'YES' if row['pass'] else 'NO'} |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    rows = _run_replay()
    md = _to_markdown(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(md, encoding="utf-8")

    print(f"Wrote validation matrix: {OUT_FILE}")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
