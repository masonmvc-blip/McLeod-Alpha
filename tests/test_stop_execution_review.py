from reports.stop_execution_review import (
    build_stop_execution_review,
    render_stop_execution_markdown,
)


def test_stop_review_detects_rejected_replacement_and_rate_limit():
    trade_key = "SPY_TEST:2026-07-29T15:24:06-04:00"
    events = [
        {
            "recorded_at": "2026-07-29T15:24:07-04:00",
            "event_type": "option_quote_observed",
            "trade_key": trade_key,
            "option_symbol": "SPY_TEST",
            "bid": 6.60,
        },
        {
            "recorded_at": "2026-07-29T15:24:08-04:00",
            "event_type": "stop_management_decision",
            "trade_key": trade_key,
            "option_symbol": "SPY_TEST",
            "action": "UPDATE_STOP",
            "candidate_stop": 6.53,
            "ratchet_lag_dollars": 0.37,
        },
        {
            "recorded_at": "2026-07-29T15:24:09-04:00",
            "event_type": "protective_stop_submitted",
            "option_symbol": "SPY_TEST",
            "stop_price": 6.16,
            "broker_order_id": "rejected-stop",
        },
        {
            "recorded_at": "2026-07-29T15:24:10-04:00",
            "event_type": "protective_stop_submission_failed",
            "trade_key": trade_key,
            "option_symbol": "SPY_TEST",
            "response_text": '{"message":"Order in status REJECTED cannot be replaced"}',
            "error": "400 Bad Request",
        },
        {
            "recorded_at": "2026-07-29T15:24:11-04:00",
            "event_type": "protective_stop_submission_failed",
            "trade_key": trade_key,
            "option_symbol": "SPY_TEST",
            "error": "429 Too Many Requests",
        },
    ]

    payload = build_stop_execution_review(
        events,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )

    trade = payload["trades"][0]
    assert trade["replacement_rejections"] == 1
    assert trade["rate_limit_failures"] == 1
    assert trade["highest_desired_stop"] == 6.53
    assert trade["highest_submitted_stop"] == 6.16
    assert trade["status"] == "REVIEW_REQUIRED"
    assert payload["gate"]["decision"] == "COLLECT_AND_REPAIR"
    assert "Protective Stop and Ratchet Reliability" in render_stop_execution_markdown(payload)


def test_stop_review_tracks_pending_submission_and_broker_verification():
    trade_key = "SPY_TEST:2026-07-29T14:42:07-04:00"
    events = [
        {
            "recorded_at": "2026-07-29T14:42:07-04:00",
            "event_type": "option_quote_observed",
            "trade_key": trade_key,
            "option_symbol": "SPY_TEST",
            "bid": 8.35,
        },
        {
            "recorded_at": "2026-07-29T14:42:08-04:00",
            "event_type": "stop_ratchet_submission_accepted_pending_verification",
            "trade_key": trade_key,
            "option_symbol": "SPY_TEST",
            "desired_stop": 8.27,
            "submitted_stop": 8.27,
            "submission_latency_ms": 180.0,
        },
        {
            "recorded_at": "2026-07-29T14:42:10-04:00",
            "event_type": "stop_ratchet_broker_verified",
            "trade_key": trade_key,
            "option_symbol": "SPY_TEST",
            "broker_confirmed_stop": 8.27,
        },
    ]

    payload = build_stop_execution_review(
        events,
        trading_date="2026-07-29",
        reconciliation={"complete": True},
    )

    assert payload["summary"]["prospective_ratchet_submissions"] == 1
    assert payload["summary"]["broker_verified_ratchets"] == 1
    assert payload["summary"]["broker_verification_rate"] == 1.0
