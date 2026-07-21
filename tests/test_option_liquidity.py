from datetime import date, timedelta

from execution.option_selector import MIN_OPTION_DAILY_VOLUME, get_nearest_expiration, select_option_from_chain
from engine.brain import Brain


def _chain_with_contracts(*contracts):
    expiry = date.today() + timedelta(days=(4 - date.today().weekday()) % 7 or 7)
    while (expiry - date.today()).days < 7:
        expiry += timedelta(days=7)
    expiry_key = f"{expiry.isoformat()}:7"
    return {"callExpDateMap": {expiry_key: {"750.0": list(contracts)}}}


def _expiration_key(expiry):
    return f"{expiry.isoformat()}:7"


def _contract(symbol, volume):
    return {
        "symbol": symbol,
        "bid": 5.00,
        "ask": 5.04,
        "mark": 5.02,
        "totalVolume": volume,
        "openInterest": 1_000,
    }


def test_selector_rejects_options_below_daily_volume_minimum():
    chain = _chain_with_contracts(_contract("SPY_LOW", MIN_OPTION_DAILY_VOLUME - 1))

    assert select_option_from_chain(chain, "CALL", 750.0) is None


def test_selector_accepts_option_at_daily_volume_minimum():
    chain = _chain_with_contracts(_contract("SPY_MIN", MIN_OPTION_DAILY_VOLUME))

    selected = select_option_from_chain(chain, "CALL", 750.0)

    assert selected["symbol"] == "SPY_MIN"
    assert selected["volume"] == MIN_OPTION_DAILY_VOLUME


def test_brain_owns_option_ranking_policy():
    chain = _chain_with_contracts(
        _contract("SPY_LOWER_VOLUME", MIN_OPTION_DAILY_VOLUME),
        _contract("SPY_HIGHER_VOLUME", MIN_OPTION_DAILY_VOLUME + 1),
    )

    selected = Brain().select_option_contract(chain, "CALL", 750.0)

    assert selected["symbol"] == "SPY_HIGHER_VOLUME"


def test_nearest_expiration_does_not_require_a_liquid_contract():
    chain = _chain_with_contracts(_contract("SPY_LOW", MIN_OPTION_DAILY_VOLUME - 1))["callExpDateMap"]

    assert get_nearest_expiration(chain) in chain


def test_selector_falls_through_to_next_liquid_weekly_expiration():
    today = date.today()
    nearest = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    while (nearest - today).days < 7:
        nearest += timedelta(days=7)
    later = nearest + timedelta(days=7)
    chain = {
        "callExpDateMap": {
            _expiration_key(nearest): {"750.0": [_contract("SPY_ILLIQUID", MIN_OPTION_DAILY_VOLUME - 1)]},
            _expiration_key(later): {"750.0": [_contract("SPY_LIQUID", MIN_OPTION_DAILY_VOLUME)]},
        }
    }

    selected = select_option_from_chain(chain, "CALL", 750.0)

    assert selected["symbol"] == "SPY_LIQUID"
    assert selected["expiration"] == _expiration_key(later)