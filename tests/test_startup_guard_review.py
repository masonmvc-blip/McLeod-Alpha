from pathlib import Path

from reports.startup_guard_review import (
    build_startup_guard_review,
    render_startup_guard_markdown,
)


def test_startup_guard_review_keeps_one_when_prompt_followup_preserves_trade(
    monkeypatch,
    tmp_path: Path,
):
    event = {
        "event_id": "guarded-put",
        "candle_time_et": "2026-07-29T09:47:00-04:00",
        "direction": "PUT",
        "score": 7,
        "rejection_reason": "startup_guard",
        "option_selected": "SPY   260807P00740000",
        "option_quote_snapshot": {
            "entry_executable_price": 7.93,
            "ask": 7.93,
        },
        "option_watch_quotes": [
            {
                "symbol": "SPY   260807P00740000",
                "bid": 8.50,
                "observed_at": "2026-07-29T09:49:00-04:00",
            }
        ],
    }
    monkeypatch.setattr(
        "reports.startup_guard_review.load_opportunity_events",
        lambda *_args, **_kwargs: [event],
    )
    monkeypatch.setattr(
        "reports.startup_guard_review.evaluate_rejected_candidates",
        lambda _events: [{
            "candidate_time_et": "2026-07-29T09:47:00-04:00",
            "direction": "PUT",
            "rejection_reason": "startup_guard",
            "option_symbol": "SPY   260807P00740000",
            "checklist_score": 7,
            "phase": "EARLY_CONTINUATION",
            "classification": "MISSED_PROFITABLE_OPPORTUNITY",
            "first_passage": "TARGET_FIRST",
            "mfe_pct": 7.2,
            "mae_pct": -0.4,
            "entry_executable_ask": 7.93,
            "evidence_gap": None,
        }],
    )
    monkeypatch.setattr(
        "reports.startup_guard_review._load_followup_trades",
        lambda _root: [{
            "entered_at": __import__("datetime").datetime.fromisoformat(
                "2026-07-29T09:49:00-04:00"
            ),
            "direction": "PUT",
            "option_symbol": "SPY   260807P00740000",
            "option_entry": 7.81,
            "pnl_dollars": 496.0,
            "broker_entry_order_id": "entry-1",
        }],
    )

    payload = build_startup_guard_review(
        "2026-07-29",
        root=tmp_path,
        reconciliation_complete=True,
    )

    assert payload["recommendation"] == "KEEP_AT_ONE"
    assert payload["increase_guard"]["recommended"] is False
    assert payload["remove_guard"]["recommended"] is False
    followup = payload["observations"][0]["followup_trade"]
    assert followup["delay_seconds"] == 120.0
    assert followup["entry_improvement_dollars"] == 0.12
    assert followup["pnl_dollars"] == 496.0
    rendered = render_startup_guard_markdown(payload)
    assert "Increase it: **NO**" in rendered
    assert "Remove it: **NO**" in rendered
    assert "$496.00" in rendered


def test_startup_guard_review_does_not_change_without_daily_event(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "reports.startup_guard_review.load_opportunity_events",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "reports.startup_guard_review._load_followup_trades",
        lambda _root: [],
    )

    payload = build_startup_guard_review(
        "2026-07-30",
        root=tmp_path,
        reconciliation_complete=True,
    )

    assert payload["recommendation"] == "KEEP_AT_ONE"
    assert payload["summary"]["blocked_candidates"] == 0
