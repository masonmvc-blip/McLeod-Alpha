from reports.daily_loss_attribution import (
    build_loss_attribution,
    maybe_send_operator_warning,
)


def _row(
    trade_id,
    *,
    trade_date="2026-07-27",
    pnl=-10.0,
    direction="CALL",
    regime="RANGE",
    admit=False,
    exit_reason="STOP",
):
    return {
        "id": trade_id,
        "trade_date": trade_date,
        "direction": direction,
        "exit_reason": exit_reason,
        "pnl": pnl,
        "option_pnl_dollars": pnl,
        "option_symbol": "SPY_TEST",
        "broker_entry_order_id": f"entry-{trade_id}",
        "broker_exit_order_id": f"exit-{trade_id}",
        "feature_payload": {
            "direction": direction,
            "regime": regime,
            "accepted_breakout_admit": admit,
            "accepted_breakout_reason": "no_prior_breakout",
            "support_resistance": {"distance_to_resistance_pct": 0.02},
        },
        "exit_efficiency_pct": 10.0,
        "peak_capture_pct": 15.0,
    }


def test_loss_attribution_is_multi_label_and_diagnostic_only():
    report = build_loss_attribution([_row(1)], trading_date="2026-07-27")
    loss = report["today"]["losses"][0]
    categories = {item["category"] for item in loss["flags"]}
    assert categories == {"confirmation", "congestion", "structural_room", "risk", "execution"}
    assert report["diagnostic_only"] is True
    assert report["automatic_live_change"] is False
    assert report["operator_warning"]["active"] is False


def test_conservative_negative_setup_warning_requires_trades_and_days(tmp_path):
    rows = []
    for index in range(12):
        day = f"2026-07-{25 + (index % 3):02d}"
        rows.append(_row(index, trade_date=day, pnl=-20.0, regime="TREND"))
    report = build_loss_attribution(rows, trading_date="2026-07-27")
    assert report["operator_warning"]["active"] is True
    assert report["rolling_setup_evidence"][0]["conservative_expectancy_upper_bound_dollars"] < 0

    alerts = []
    state_path = tmp_path / "alert.json"
    sender = lambda title, details: alerts.append((title, details)) or True
    assert maybe_send_operator_warning(report, state_path=state_path, alert_sender=sender) is True
    assert maybe_send_operator_warning(report, state_path=state_path, alert_sender=sender) is False
    assert len(alerts) == 1


def test_positive_variability_does_not_trigger_warning():
    rows = [
        _row(index, trade_date=f"2026-07-{25 + (index % 3):02d}", pnl=(-20.0 if index % 2 else 40.0), regime="TREND")
        for index in range(12)
    ]
    report = build_loss_attribution(rows, trading_date="2026-07-27")
    assert report["operator_warning"]["active"] is False
