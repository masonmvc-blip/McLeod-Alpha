from execution.contract_limits import MAX_OPEN_CONTRACTS

ACCOUNT_SIZE = 1000
RISK_PER_TRADE = 10
MAX_CONTRACTS = MAX_OPEN_CONTRACTS

def calculate_quantity(entry_price, stop_price):
    risk_per_share = abs(entry_price - stop_price)

    if risk_per_share <= 0:
        return 0

    qty = int(RISK_PER_TRADE / risk_per_share)

    if qty < 1:
        qty = 1

    return min(qty, MAX_CONTRACTS)