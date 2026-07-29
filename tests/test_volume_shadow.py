import json

import pandas as pd

from reports import volume_shadow_report
from strategy.volume_shadow import build_volume_shadow


def _frame(current_volume=150.0):
    index = pd.date_range(
        "2026-07-29 13:30:00+00:00",
        periods=21,
        freq="min",
    )
    rows = []
    for position, _ in enumerate(index):
        rows.append({
            "open": 100.0,
            "high": 101.0,
            "low": 100.0,
            "close": 100.9 if position == 20 else 100.4,
            "volume": current_volume if position == 20 else 100.0,
        })
    return pd.DataFrame(rows, index=index)


def test_volume_shadow_compares_consistent_policies_without_live_change():
    result = build_volume_shadow(
        _frame(),
        "CALL",
        observed_score=5,
        entry_threshold=5,
    )

    assert result["valid"] is True
    assert result["shadow_only"] is True
    assert result["automatic_live_change_allowed"] is False
    assert result["relative_volume_5"] == 1.5
    assert result["relative_volume_20"] == 1.5
    assert result["directional_close_confirmed"] is True
    assert result["score_without_live_volume"] == 4.0
    assert result["policies"]["live_5bar"]["score_delta"] == 1
    assert result["policies"]["no_volume_adjustment"]["would_pass_score_threshold"] is False
    assert result["policies"]["quality_confirmed_20bar"]["would_pass_score_threshold"] is True


def test_volume_shadow_does_not_assign_volume_to_opposite_direction():
    result = build_volume_shadow(
        _frame(),
        "PUT",
        observed_score=4,
        entry_threshold=5,
    )

    assert result["direction_aligned_with_candle"] is False
    assert {
        policy["score_delta"]
        for policy in result["policies"].values()
    } == {0}


def test_daily_report_adds_prior_session_time_of_day_baseline(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    dates_and_volumes = [
        ("2026-07-24", 100.0),
        ("2026-07-27", 120.0),
        ("2026-07-28", 80.0),
        ("2026-07-29", 150.0),
    ]
    for trading_date, current_volume in dates_and_volumes:
        shadow = build_volume_shadow(
            _frame(current_volume),
            "CALL",
            observed_score=5,
            entry_threshold=5,
        )
        event = {
            "event_id": f"{trading_date}T09:50:00-04:00|CALL",
            "candle_time_et": f"{trading_date}T09:50:00-04:00",
            "direction": "CALL",
            "entered": False,
            "stage": {"label": "EARLY_CONTINUATION"},
            "volume_shadow": shadow,
            "estimated_option_outcome": {
                "estimated_option_mfe_pct": 7.0,
                "estimated_option_mae_pct": -2.0,
            },
        }
        (reports_dir / f"daily_opportunity_review_{trading_date}.json").write_text(
            json.dumps({"evaluated_setups": [event]}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        volume_shadow_report,
        "load_study_trades",
        lambda **_: ([], {"distinct_broker_entries": 0}),
    )
    result = volume_shadow_report.evaluate_volume_shadow(
        "2026-07-29",
        root=tmp_path,
    )

    today = result["today"][0]["volume_shadow"]
    assert today["time_of_day_baseline_sessions"] == 3
    assert today["time_of_day_baseline_volume"] == 100.0
    assert today["time_of_day_relative_volume"] == 1.5
    assert result["automatic_live_change_allowed"] is False
