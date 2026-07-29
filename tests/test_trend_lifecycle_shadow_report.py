from reports.trend_lifecycle_shadow_report import _first_passage


def test_first_passage_uses_executable_quotes_and_initial_stop():
    trade = {"option_entry": 10.0, "mfe_pct": None, "mae_pct": None}
    cycles = [
        {
            "recorded_at": "2026-07-28T10:00:00-04:00",
            "executable_exit_price": 10.10,
            "option_initial_stop": 9.50,
            "option_stop": 9.50,
        },
        {
            "recorded_at": "2026-07-28T10:01:00-04:00",
            "executable_exit_price": 10.61,
            "option_initial_stop": 9.50,
            "option_stop": 10.10,
        },
        {
            "recorded_at": "2026-07-28T10:02:00-04:00",
            "executable_exit_price": 9.40,
            "option_initial_stop": 9.50,
            "option_stop": 10.10,
        },
    ]
    outcome = _first_passage(trade, cycles)
    assert outcome["status"] == "TARGET_FIRST"
    assert outcome["target_before_initial_stop"] is True
    assert outcome["initial_stop_source"] == "position_initial_stop"


def test_complete_quote_series_without_either_barrier_is_negative_target_outcome():
    outcome = _first_passage(
        {"option_entry": 10.0},
        [{
            "recorded_at": "2026-07-28T10:00:00-04:00",
            "executable_exit_price": 10.20,
            "option_stop": 9.50,
        }],
    )
    assert outcome["status"] == "NEITHER_OBSERVED"
    assert outcome["target_before_initial_stop"] is False
