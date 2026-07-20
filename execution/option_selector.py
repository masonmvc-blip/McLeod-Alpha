from engine.brain import Brain


MIN_OPTION_DAILY_VOLUME = 500
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
            "REJECTED: no option passed bid-ask and daily-volume liquidity filters "
            f"(minimum volume: {MIN_OPTION_DAILY_VOLUME})"
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