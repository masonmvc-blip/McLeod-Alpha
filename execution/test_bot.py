from paper_engine import open_trade, close_trade, in_trade, trade_log
from risk_manager import can_open_trade, record_trade

print("McLeod Alpha system test running")

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"PASS {name}")
        passed += 1
    else:
        print(f"FAIL {name}")
        failed += 1

opened = open_trade(
    direction="CALL",
    price=100.0,
    stop=99.0,
    target=102.0,
    quantity=1,
    reason="TEST",
)

check("Trade opens", opened)
check("In trade", in_trade())

duplicate = open_trade(
    direction="CALL",
    price=101.0,
    stop=100.0,
    target=103.0,
    quantity=1,
    reason="DUPLICATE",
)

check("Duplicate blocked", duplicate is False)

closed = close_trade(price=102.0, reason="TARGET")

check("Trade closes", closed)
check("No longer in trade", not in_trade())
check("Trade logged", len(trade_log) == 1)

allowed, _ = can_open_trade()
check("Risk manager works", allowed)

record_trade(-60)

allowed, _ = can_open_trade()
check("Daily loss blocks", allowed is False)

print(f"Passed: {passed}")
print(f"Failed: {failed}")
