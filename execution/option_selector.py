from datetime import date, datetime



def get_nearest_expiration(chain):
    today = date.today()
    eligible = []

    for expiration_key in chain.keys():
        date_text = expiration_key.split(":")[0]

        try:
            expiration_date = datetime.strptime(
                date_text,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            continue

        days_to_expiration = (expiration_date - today).days

        if (
            expiration_date.weekday() == 4
            and days_to_expiration >= 7
        ):
            eligible.append((expiration_date, expiration_key))

    if not eligible:
        raise ValueError(
            "No Friday expiration at least 7 days away was found"
        )

    eligible.sort(key=lambda item: item[0])
    selected_date, selected_key = eligible[0]

    print(
        f"SELECTED FRIDAY EXPIRATION: "
        f"{selected_date} | "
        f"DTE={(selected_date - today).days}"
    )

    return selected_key

def get_strikes_for_expiration(chain, expiration):
    return chain[expiration]


def get_closest_strike(strikes, spy_price):
    return min(strikes.keys(), key=lambda strike: abs(float(strike) - spy_price))


def select_option_from_chain(data, direction, spy_price):
    if direction == "CALL":
        chain = data["callExpDateMap"]
    else:
        chain = data["putExpDateMap"]

    expiration = get_nearest_expiration(chain)
    strikes = get_strikes_for_expiration(chain, expiration)

    candidates = []

    for strike, contracts in strikes.items():
        for contract in contracts:
            bid = float(contract.get("bid") or 0)
            ask = float(contract.get("ask") or 0)
            mark = float(contract.get("mark") or 0)
            volume = int(contract.get("totalVolume") or 0)
            open_interest = int(contract.get("openInterest") or 0)

            if bid <= 0 or ask <= 0 or mark <= 0:
                continue

            spread = ask - bid
            spread_pct = (spread / mark) * 100

            # Preserve our bid-ask liquidity requirements.
            if spread > 0.05 or spread_pct > 8:
                continue

            candidates.append({
                "symbol": contract.get("symbol"),
                "description": contract.get("description"),
                "direction": direction,
                "expiration": expiration,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "last": contract.get("last"),
                "mark": mark,
                "delta": contract.get("delta"),
                "volume": volume,
                "open_interest": open_interest,
                "spread": spread,
                "spread_pct": spread_pct,
            })

    if not candidates:
        print("REJECTED: no option passed bid-ask and liquidity filters")
        return None

    # Highest volume first. Ties favor open interest, then closest strike.
    selected = max(
        candidates,
        key=lambda option: (
            option["volume"],
            option["open_interest"],
            -abs(float(option["strike"]) - spy_price),
        ),
    )

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