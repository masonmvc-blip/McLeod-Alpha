from reports.accepted_breakout_observer_report import build_report


def _closed(*, admit, entry, exit_price, fees):
    return {
        "event_type": "option_trade_closed", "recorded_at": "2026-07-27T10:00:00-04:00",
        "accepted_breakout_admit": admit, "broker_entry_fill_price": entry,
        "executable_exit_price": exit_price, "quantity": 1, "broker_fees_dollars": fees,
    }


def test_report_requires_complete_fill_and_fee_facts_and_never_auto_deploys(tmp_path):
    path = tmp_path / "option_management_cycles_2026-07-27.jsonl"
    path.write_text(
        "\n".join(__import__("json").dumps(event) for event in [
            _closed(admit=True, entry=5, exit_price=6, fees=1),
            _closed(admit=False, entry=5, exit_price=4, fees=1),
            _closed(admit=False, entry=5, exit_price=6, fees=None),
        ]) + "\n",
        encoding="utf-8",
    )
    report = build_report([path], minimum_per_cohort=1)
    assert report["excluded_missing_fill_or_fee_facts"] == 1
    assert report["retained"]["after_cost_expectancy_dollars"] == 99.0
    assert report["rejected"]["after_cost_expectancy_dollars"] == -101.0
    assert report["automatic_live_deployment"] is False
    assert report["status"] == "ready_for_manual_review"