from datetime import datetime
from pathlib import Path

from reports.cooling_period_review import (
    build_cooling_period_review,
    render_cooling_period_markdown,
)


def test_harmful_uncooled_reentry_supports_existing_one_signal_rule(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "reports.cooling_period_review.load_opportunity_events",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "reports.cooling_period_review.evaluate_rejected_candidates",
        lambda _events: [],
    )
    monkeypatch.setattr(
        "reports.cooling_period_review._load_broker_trades",
        lambda _root: [
            {
                "entered_at": datetime.fromisoformat("2026-07-29T09:49:04-04:00"),
                "exited_at": datetime.fromisoformat("2026-07-29T09:51:22-04:00"),
                "direction": "PUT",
                "option_symbol": "SPY   260807P00740000",
                "option_entry": 7.81,
                "pnl_dollars": 496.0,
                "broker_entry_order_id": "entry-1",
                "broker_exit_order_id": "exit-1",
            },
            {
                "entered_at": datetime.fromisoformat("2026-07-29T09:52:04-04:00"),
                "exited_at": datetime.fromisoformat("2026-07-29T09:54:07-04:00"),
                "direction": "PUT",
                "option_symbol": "SPY   260807P00740000",
                "option_entry": 8.65,
                "pnl_dollars": -134.41,
                "broker_entry_order_id": "entry-2",
                "broker_exit_order_id": "exit-2",
            },
        ],
    )

    payload = build_cooling_period_review(
        "2026-07-29",
        root=tmp_path,
        reconciliation_complete=True,
    )

    assert payload["recommendation"] == "KEEP_AT_ONE"
    assert payload["increase_to_two_signals"]["recommended"] is False
    assert payload["remove_cooling"]["recommended"] is False
    assert payload["summary"]["harmful_uncooled_reentries"] == 1
    assert payload["summary"]["harmful_uncooled_reentry_pnl"] == -134.41
    rendered = render_cooling_period_markdown(payload)
    assert "Increase to two signals: **NO**" in rendered
    assert "Drop cooling entirely: **NO**" in rendered
    assert "-$134.41" in rendered


def test_cooling_watchlist_reconstruction_produces_executable_outcome(
    monkeypatch,
    tmp_path: Path,
):
    events = [
        {
            "event_id": "cooling-call",
            "candle_time_et": "2026-07-29T14:00:00-04:00",
            "direction": "CALL",
            "score": 7,
            "rejection_reason": "Cooling Period",
            "option_watch_quotes": [{
                "symbol": "SPY   260807C00740000",
                "bid": 7.29,
                "ask": 7.62,
            }],
        },
        {
            "event_id": "future-call",
            "candle_time_et": "2026-07-29T14:01:00-04:00",
            "direction": "CALL",
            "score": 6,
            "rejection_reason": "test",
            "option_watch_quotes": [{
                "symbol": "SPY   260807C00740000",
                "bid": 8.10,
                "ask": 8.14,
            }],
        },
    ]
    monkeypatch.setattr(
        "reports.cooling_period_review.load_opportunity_events",
        lambda *_args, **_kwargs: events,
    )
    monkeypatch.setattr(
        "reports.cooling_period_review._load_broker_trades",
        lambda _root: [],
    )

    payload = build_cooling_period_review(
        "2026-07-29",
        root=tmp_path,
        reconciliation_complete=True,
    )

    assert payload["summary"]["cooling_blocks"] == 1
    assert payload["summary"]["decisive_option_outcomes"] == 1
    assert payload["summary"]["option_evidence_coverage"] == 1.0
    assert payload["blocked_observations"][0]["classification"] == "MISSED_PROFITABLE_OPPORTUNITY"
