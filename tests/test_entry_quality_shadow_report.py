from reports.entry_quality_shadow_report import evaluate_entry_quality_shadow


def _trade(index, *, phase, conf, direction, pnl, trade_date="2026-07-29"):
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
