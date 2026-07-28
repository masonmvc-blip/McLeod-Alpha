from datetime import date, datetime

from engine.brain import Brain
from engine.brain.engine import (
    OPTION_MAX_ABSOLUTE_SPREAD,
    OPTION_MAX_SPREAD_PCT,
    OPTION_MIN_DAYS_TO_EXPIRY,
    OPTION_MIN_OPEN_INTEREST,
)


MIN_OPTION_DAILY_VOLUME = 400
OPTION_SELECTION_BRAIN = Brain()



def get_nearest_expiration(chain):
    return OPTION_SELECTION_BRAIN.select_option_expiration(chain)

def get_strikes_for_expiration(chain, expiration):
    return chain[expiration]


def get_closest_strike(strikes, spy_price):
    return min(strikes.keys(), key=lambda strike: abs(float(strike) - spy_price))


def select_option_from_chain(data, direction, spy_price):
    selected = OPTION_SELECTION_BRAIN.select_option_contract(data, direction, spy_price)
    if selected is None:
        print(
            "REJECTED: no option passed executable bid-ask/spread liquidity filters "
            f"(minimum volume: {MIN_OPTION_DAILY_VOLUME}; "
            f"open-interest fallback: {OPTION_MIN_OPEN_INTEREST})"
        )
        return None

    print(
        f"SELECTED HIGHEST-VOLUME OPTION: "
        f"{selected['symbol']} | "
        f"Volume={selected['volume']} | "
        f"Open interest={selected['open_interest']} | "
        f"Bid={selected['bid']:.2f} | "
        f"Ask={selected['ask']:.2f} | "
        f"Spread=${selected['spread']:.2f} "
        f"({selected['spread_pct']:.1f}%)"
    )

    return selected


def option_selection_block_reason(data, direction, *, as_of=None):
    """Identify an insufficient-contract rejection without masking quote failures."""
    chain_key = "callExpDateMap" if str(direction or "").upper() == "CALL" else "putExpDateMap"
    today = as_of or date.today()

    for expiration_key, strikes in (data.get(chain_key, {}) or {}).items():
        try:
            expiration = datetime.strptime(str(expiration_key).split(":", 1)[0], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if expiration.weekday() != 4 or (expiration - today).days < OPTION_MIN_DAYS_TO_EXPIRY:
            continue

        for contracts in (strikes or {}).values():
            for contract in contracts or []:
                try:
                    bid = float(contract.get("bid") or 0.0)
                    ask = float(contract.get("ask") or 0.0)
                    mark = float(contract.get("mark") or 0.0)
                    volume = int(contract.get("totalVolume") or 0)
                    open_interest = int(contract.get("openInterest") or 0)
                except (TypeError, ValueError):
                    continue
                if bid <= 0 or ask <= 0 or mark <= 0:
                    continue
                spread = ask - bid
                if spread > OPTION_MAX_ABSOLUTE_SPREAD or (spread / mark) * 100.0 > OPTION_MAX_SPREAD_PCT:
                    continue
                if volume < MIN_OPTION_DAILY_VOLUME and open_interest < OPTION_MIN_OPEN_INTEREST:
                    return "Too Few Contracts"
    return None


def find_option_bid(data, option_symbol):
    for chain_name in ["callExpDateMap", "putExpDateMap"]:
        chain = data.get(chain_name, {})

        for expiration in chain.values():
            for contracts in expiration.values():
                for contract in contracts:
                    if contract.get("symbol") == option_symbol:
                        return float(contract.get("bid") or 0)

    return None


def find_option_mark(data, option_symbol):
    for chain_name in ["callExpDateMap", "putExpDateMap"]:
        chain = data.get(chain_name, {})

        for expiration in chain.values():
            for contracts in expiration.values():
                for contract in contracts:
                    if contract.get("symbol") == option_symbol:
                        return float(contract.get("mark") or contract.get("last") or 0)

    return None