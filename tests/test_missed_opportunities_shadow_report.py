from reports.missed_opportunities_shadow_report import (
    build_missed_opportunities_payload,
    canonicalize_episodes,
    evaluate_rejected_candidates,
    render_missed_opportunities_markdown,
)


def _event(
    minute,
    *,
    direction="CALL",
    symbol="SPY_TEST_CALL",
    bid=1.00,
    ask=1.02,
    entered=False,
    reason="CALL score below threshold by 1",
    phase="EARLY_CONTINUATION",
):
    return {
        "event_id": f"2026-07-29T10:{minute:02d}:00-04:00|{direction}",
        "candle_time_et": f"2026-07-29T10:{minute:02d}:00-04:00",
        "direction": direction,
        "entered": entered,
        "rejection_reason": reason,
        "market_regime": "BULL_TREND" if direction == "CALL" else "BEAR_TREND",
        "score_distance_to_threshold": -1,
        "stage": {"stage": 2, "label": phase},
        "cq": {"score": 3.8},
        "mas": {"score": 4.1},
        "absorption_score": 3.33,
        "confidence": 4.2,
        "positive_signals": ["macd_improving"],
        "option_selected": symbol,
        "option_quote_snapshot": {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "entry_executable_price": ask,
            "future_exit_executable_price_field": "bid",
            "quote_provenance": "cached_live_option_chain",
        },
    }


def test_executable_target_before_stop_is_a_missed_opportunity():
    events = [
        _event(0, bid=1.00, ask=1.00),
        _event(1, bid=1.02, ask=1.04),
        _event(2, bid=1.07, ask=1.09),
    ]

    row = evaluate_rejected_candidates(events)[0]

    assert row["classification"] == "MISSED_PROFITABLE_OPPORTUNITY"
    assert row["first_passage"] == "TARGET_BEFORE_STOP"
    assert row["mfe_pct"] == 7.0
    assert row["outcome_evidence"] == "ACTUAL_EXECUTABLE_OPTION_QUOTES"


def test_executable_stop_before_target_is_a_correctly_avoided_loss():
    events = [
        _event(0, bid=1.00, ask=1.00),
        _event(1, bid=0.96, ask=0.98),
        _event(2, bid=1.08, ask=1.10),
    ]

    row = evaluate_rejected_candidates(events)[0]

    assert row["classification"] == "LOSS_CORRECTLY_AVOIDED"
    assert row["first_passage"] == "STOP_BEFORE_TARGET"


def test_missing_option_quotes_are_data_gap_not_claimed_profit():
    event = _event(0)
    event["option_quote_snapshot"] = None
    event["option_selected"] = None

    row = evaluate_rejected_candidates([event])[0]

    assert row["classification"] == "INSUFFICIENT_OPTION_EVIDENCE"
    assert row["mfe_pct"] is None


def test_watchlist_quotes_preserve_outcome_when_current_selection_changes():
    first = _event(0, symbol="CALL_OLD", bid=1.00, ask=1.00)
    later = _event(1, symbol="CALL_NEW", bid=2.00, ask=2.02)
    later["option_watch_quotes"] = [
        {"symbol": "CALL_OLD", "bid": 1.07, "ask": 1.09}
    ]

    row = evaluate_rejected_candidates([first, later])[0]

    assert row["classification"] == "MISSED_PROFITABLE_OPPORTUNITY"
    assert row["mfe_pct"] == 7.0


def test_repeated_minute_signals_collapse_to_one_episode():
    rows = [
        {
            **evaluate_rejected_candidates([
                _event(minute, bid=1.00, ask=1.00),
                _event(minute + 1, bid=1.07, ask=1.09),
            ])[0],
            "candidate_time_et": f"2026-07-29T10:{minute:02d}:00-04:00",
        }
        for minute in (0, 2, 5)
    ]

    canonical = canonicalize_episodes(rows)

    assert len(canonical) == 1


def test_payload_and_markdown_separate_missed_from_protected():
    events = [
        _event(0, symbol="CALL_A", bid=1.00, ask=1.00),
        _event(1, symbol="CALL_A", bid=1.07, ask=1.09),
        _event(
            20,
            direction="PUT",
            symbol="PUT_A",
            bid=1.00,
            ask=1.00,
            reason="PUT score below threshold by 1",
        ),
        _event(
            21,
            direction="PUT",
            symbol="PUT_A",
            bid=0.96,
            ask=0.98,
            reason="PUT score below threshold by 1",
        ),
    ]

    payload = build_missed_opportunities_payload(
        events,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )
    markdown = render_missed_opportunities_markdown(payload)

    assert payload["summary"]["canonical_missed_opportunities"] == 1
    assert payload["summary"]["canonical_losses_correctly_avoided"] == 1
    assert payload["automatic_live_change_allowed"] is False
    assert "Canonical Missed Opportunities" in markdown
    assert "Losses Correctly Avoided" in markdown
