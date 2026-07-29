from datetime import date, timedelta

from reports.option_selection_shadow_report import (
    evaluate_option_selection_events,
    evaluate_option_selection_shadow,
)
from strategy.option_selection_shadow import (
    build_option_selection_shadow,
    reset_option_selection_shadow_history,
)


def _friday_at_least_week_away() -> date:
    expiry = date.today() + timedelta(days=(4 - date.today().weekday()) % 7 or 7)
    while (expiry - date.today()).days < 7:
        expiry += timedelta(days=7)
    return expiry


def _contract(symbol, strike, bid, ask, volume, open_interest=1_000):
    return {
        "symbol": symbol,
        "strikePrice": strike,
        "bid": bid,
        "ask": ask,
        "mark": round((bid + ask) / 2, 3),
        "totalVolume": volume,
        "openInterest": open_interest,
    }


def _chain(*contracts):
    expiry = _friday_at_least_week_away()
    strike_map = {}
    for contract in contracts:
        strike_map.setdefault(str(contract["strikePrice"]), []).append(contract)
    return {
        "callExpDateMap": {
            f"{expiry.isoformat()}:{(expiry - date.today()).days}": strike_map,
        }
    }


def test_shadow_prefers_tighter_spread_without_changing_live_selection():
    reset_option_selection_shadow_history()
    live_contract = _contract("SPY_LIVE", 750, 5.00, 5.05, 5_000)
    tight_contract = _contract("SPY_TIGHT", 751, 5.01, 5.03, 900)
    chain = _chain(live_contract, tight_contract)
    expiration = next(iter(chain["callExpDateMap"]))
    live_selection = {
        **live_contract,
        "direction": "CALL",
        "expiration": expiration,
        "strike": "750",
        "volume": 5_000,
        "open_interest": 1_000,
        "spread": 0.05,
        "spread_pct": 0.995,
    }

    result = build_option_selection_shadow(
        chain,
        "CALL",
        750.0,
        live_selection,
    )

    assert result["valid"] is True
    assert result["shadow_only"] is True
    assert result["automatic_live_change_allowed"] is False
    assert result["live_selection"]["symbol"] == "SPY_LIVE"
    assert result["shadow_selection"]["symbol"] == "SPY_TIGHT"
    assert result["selection_differs"] is True
    assert result["estimated_spread_saving_total"] == 24.0


def test_shadow_only_compares_contracts_that_pass_live_filters():
    reset_option_selection_shadow_history()
    live_contract = _contract("SPY_LIVE", 750, 5.00, 5.04, 800)
    illiquid = _contract("SPY_ILLIQUID", 750, 5.01, 5.02, 10, open_interest=10)
    chain = _chain(live_contract, illiquid)
    expiration = next(iter(chain["callExpDateMap"]))
    live_selection = {
        **live_contract,
        "direction": "CALL",
        "expiration": expiration,
        "strike": "750",
        "volume": 800,
        "open_interest": 1_000,
        "spread": 0.04,
        "spread_pct": 0.7968,
    }

    result = build_option_selection_shadow(chain, "CALL", 750.0, live_selection)

    assert [row["symbol"] for row in result["ranked_candidates"]] == ["SPY_LIVE"]
    assert result["selection_differs"] is False


def test_report_compares_live_and_shadow_using_ask_then_future_bid():
    base_shadow = {
        "valid": True,
        "selection_differs": True,
        "liquidity_tier": "DAILY_VOLUME",
        "estimated_spread_saving_per_contract": 3.0,
        "estimated_spread_saving_total": 24.0,
        "stability_evidence_ready": True,
        "live_selection": {
            "symbol": "SPY_LIVE",
            "ask": 5.05,
            "bid": 5.00,
            "spread": 0.05,
            "spread_pct": 0.995,
        },
        "shadow_selection": {
            "symbol": "SPY_SHADOW",
            "ask": 5.03,
            "bid": 5.01,
            "spread": 0.02,
            "spread_pct": 0.398,
        },
    }
    events = [
        {
            "event_id": "2026-07-29T10:00:00-04:00|CALL",
            "candle_time_et": "2026-07-29T10:00:00-04:00",
            "direction": "CALL",
            "stage": {"label": "INITIATION"},
            "option_selection_shadow": base_shadow,
            "option_quote_snapshot": base_shadow["live_selection"],
            "option_watch_quotes": [],
        },
        {
            "event_id": "2026-07-29T10:01:00-04:00|CALL",
            "candle_time_et": "2026-07-29T10:01:00-04:00",
            "direction": "CALL",
            "option_watch_quotes": [
                {"symbol": "SPY_LIVE", "bid": 5.10},
                {"symbol": "SPY_SHADOW", "bid": 5.36},
            ],
        },
    ]

    rows = evaluate_option_selection_events(events)

    assert len(rows) == 1
    assert rows[0]["both_executable"] is True
    assert rows[0]["live"]["first_passage"] == "NEITHER"
    assert rows[0]["shadow"]["first_passage"] == "TARGET_BEFORE_STOP"
    assert rows[0]["comparison"] == "SHADOW_BETTER"


def test_report_governance_keeps_live_ranking_unchanged_without_sample(tmp_path):
    result = evaluate_option_selection_shadow("2026-07-29", root=tmp_path)

    assert result["recommendation"] == "KEEP_LIVE_HIGHEST_VOLUME_RANKING_UNCHANGED"
    assert result["governance"]["ready_for_human_review"] is False
    assert result["automatic_live_change_allowed"] is False
