import json
import sqlite3

from reports.entry_quality_shadow_report import (
    _load_latest_canonical_payloads,
    canonical_indicator_performance,
    evaluate_entry_quality_shadow,
)


def _trade(
    index,
    *,
    phase,
    conf,
    direction,
    pnl,
    trade_date="2026-07-29",
    score=None,
    indicators=None,
):
    return {
        "broker_entry_order_id": str(index),
        "trade_date": trade_date,
        "direction": direction,
        "phase": phase,
        "cq": 4.0,
        "mas": 4.0,
        "abs": 3.33,
        "conf": conf,
        "pnl_dollars": pnl,
        "checklist_score": score,
        "indicator_labels": indicators or [],
    }


def test_fresh_gate_requires_twenty_per_group_and_both_directions():
    rows = []
    for index in range(20):
        rows.append(_trade(
            index,
            phase="EARLY_CONTINUATION",
            conf=4.2,
            direction="CALL" if index < 10 else "PUT",
            pnl=10,
        ))
    for index in range(20, 40):
        rows.append(_trade(
            index,
            phase="INITIATION",
            conf=3.5,
            direction="CALL" if index < 30 else "PUT",
            pnl=-5,
        ))
    result = evaluate_entry_quality_shadow(
        rows,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )
    hypothesis = result["hypotheses"]["early_continuation_conf_4"]
    assert hypothesis["ready_for_human_review"] is True
    assert hypothesis["decision"] == "ELIGIBLE_FOR_HUMAN_REVIEW"
    assert result["automatic_live_change_allowed"] is False


def test_historical_rows_never_satisfy_fresh_gate():
    rows = [
        _trade(
            index,
            phase="EARLY_CONTINUATION",
            conf=4.2,
            direction="CALL" if index % 2 else "PUT",
            pnl=10,
            trade_date="2026-07-28",
        )
        for index in range(30)
    ]
    result = evaluate_entry_quality_shadow(
        rows,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )
    assert result["historical_comparable_trades"] == 30
    assert result["fresh_comparable_trades"] == 0
    assert result["hypotheses"]["early_continuation_conf_4"]["decision"] == "COLLECT_MORE_DATA"


def test_established_gate_is_separate_for_calls_and_puts():
    rows = []
    index = 0
    for direction in ("CALL", "PUT"):
        for phase in ("ESTABLISHED", "EARLY_CONTINUATION"):
            for _ in range(20):
                rows.append(_trade(
                    index,
                    phase=phase,
                    conf=3.5,
                    direction=direction,
                    pnl=-10 if phase == "ESTABLISHED" else 10,
                ))
                index += 1
    result = evaluate_entry_quality_shadow(
        rows,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )
    hypothesis = result["hypotheses"]["established_shadow_reject_by_direction"]
    assert hypothesis["ready_for_human_review"] is True
    assert all(hypothesis["checks"].values())


def test_incomplete_reconciliation_keeps_every_gate_locked():
    rows = [
        _trade(
            index,
            phase="EARLY_CONTINUATION" if index < 20 else "INITIATION",
            conf=4.2 if index < 20 else 3.0,
            direction="CALL" if index % 2 else "PUT",
            pnl=10,
        )
        for index in range(40)
    ]
    result = evaluate_entry_quality_shadow(
        rows,
        trading_date="2026-07-29",
        reconciliation={"complete": False},
    )
    assert result["conclusions_withheld"] is True
    assert result["hypotheses"]["early_continuation_conf_4"]["ready_for_human_review"] is False


def test_checklist_scores_are_separated_by_direction_and_phase():
    rows = [
        _trade(
            1,
            phase="EARLY_CONTINUATION",
            conf=4.2,
            direction="CALL",
            pnl=25,
            score=5,
        ),
        _trade(
            2,
            phase="ESTABLISHED",
            conf=3.2,
            direction="CALL",
            pnl=-10,
            score=7,
        ),
        _trade(
            3,
            phase="EARLY_CONTINUATION",
            conf=3.8,
            direction="PUT",
            pnl=-20,
            score=7,
        ),
    ]

    result = evaluate_entry_quality_shadow(
        rows,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )
    fresh = result["checklist_score_study"]["fresh"]["by_direction_and_phase"]

    assert fresh["CALL"]["all_phases"]["5"]["pnl_dollars"] == 25
    assert fresh["CALL"]["by_phase"]["ESTABLISHED"]["7"]["pnl_dollars"] == -10
    assert fresh["PUT"]["by_phase"]["EARLY_CONTINUATION"]["7"]["trades"] == 1
    assert result["checklist_score_study"]["decision"] == "COLLECT_MORE_DATA"


def test_indicator_weight_gate_requires_present_absent_and_phase_coverage():
    rows = []
    for index in range(40):
        indicators = ["macd_improving"] if index < 20 else []
        rows.append(_trade(
            index,
            phase="EARLY_CONTINUATION" if index % 2 else "INITIATION",
            conf=4.0,
            direction="CALL",
            pnl=10 if indicators else -5,
            score=5,
            indicators=indicators,
        ))

    result = evaluate_entry_quality_shadow(
        rows,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )
    hypothesis = (
        result["indicator_weight_study"]["hypotheses"]["call_macd_improving"]
    )

    assert hypothesis["fresh"]["present"]["trades"] == 20
    assert hypothesis["fresh"]["absent_same_direction"]["trades"] == 20
    assert hypothesis["ready_for_human_review"] is True
    assert hypothesis["decision"] == "ELIGIBLE_FOR_HUMAN_REVIEW"


def test_canonical_indicator_performance_uses_same_direction_absent_comparator():
    rows = [
        _trade(
            1,
            phase="EARLY_CONTINUATION",
            conf=4.0,
            direction="CALL",
            pnl=20,
            score=6,
            indicators=["breaks_prev_high"],
        ),
        _trade(
            2,
            phase="EARLY_CONTINUATION",
            conf=4.0,
            direction="CALL",
            pnl=-10,
            score=5,
            indicators=[],
        ),
        _trade(
            3,
            phase="EARLY_CONTINUATION",
            conf=4.0,
            direction="PUT",
            pnl=-100,
            score=7,
            indicators=["breaks_prev_low"],
        ),
    ]

    performance = canonical_indicator_performance(
        rows,
        trading_date="2026-07-29",
        minimum_sample_size=1,
    )
    break_high = next(
        row for row in performance if row["indicator"] == "breaks_prev_high"
    )

    assert break_high["direction"] == "CALL"
    assert break_high["trades"] == 1
    assert break_high["average_return"] == 20
    assert break_high["absent_trades"] == 1
    assert break_high["absent_average_return"] == -10
    assert break_high["guidance"] == "Shadow increase candidate"
    assert break_high["automatic_live_change_allowed"] is False


def test_superseded_duplicate_never_enters_entry_quality_study():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE canonical_completed_trades (
            canonical_trade_id TEXT PRIMARY KEY
        );
        CREATE TABLE canonical_completed_trade_versions (
            canonical_trade_id TEXT,
            canonical_version INTEGER,
            payload TEXT
        );
        CREATE TABLE canonical_trade_supersessions (
            superseded_trade_id TEXT,
            surviving_trade_id TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO canonical_completed_trades VALUES (?)",
        [("survivor",), ("duplicate",)],
    )
    connection.executemany(
        "INSERT INTO canonical_completed_trade_versions VALUES (?, ?, ?)",
        [
            ("survivor", 1, json.dumps({"broker_entry_order_id": "entry-1"})),
            ("duplicate", 1, json.dumps({"broker_entry_order_id": "entry-duplicate"})),
        ],
    )
    connection.execute(
        "INSERT INTO canonical_trade_supersessions VALUES (?, ?)",
        ("duplicate", "survivor"),
    )

    rows = _load_latest_canonical_payloads(connection)

    assert [row["canonical_trade_id"] for row in rows] == ["survivor"]
