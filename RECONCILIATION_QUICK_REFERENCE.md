# Schwab Order Reconciliation - Quick Reference

## The Fix in 30 Seconds

**Problem:** Bot blocks trades when Schwab has REPLACED/FILLED/CANCELED orders  
**Fix:** Only ACTIVE orders (WORKING, PENDING_ACTIVATION, etc.) block trades  
**Result:** False trade blocks eliminated  

---

## Order Statuses Reference

### 🟢 ACTIVE Statuses (BLOCK Trading)
These orders can still get filled in the future:

| Status | Meaning | Blocks? |
|--------|---------|---------|
| WORKING | Order is working in market | ✅ YES |
| PENDING_ACTIVATION | Awaiting activation condition | ✅ YES |
| QUEUED | In queue for submission | ✅ YES |
| ACCEPTED | Accepted by broker, awaiting fill | ✅ YES |
| AWAITING_PARENT_ORDER | Conditional, waiting on parent order | ✅ YES |
| AWAITING_CONDITION | Waiting for condition to be met | ✅ YES |
| PARTIALLY_FILLED | Partial fill, can fill more | ✅ YES |

### 🔴 TERMINAL Statuses (DO NOT Block)
These orders are completed/closed, cannot be filled:

| Status | Meaning | Blocks? |
|--------|---------|---------|
| FILLED | Order completely filled | ❌ NO |
| CANCELED | User or system canceled | ❌ NO |
| CANCELLED | Alternative spelling | ❌ NO |
| REPLACED | Order was replaced with a new order | ❌ NO |
| EXPIRED | Order expired without filling | ❌ NO |
| REJECTED | Broker rejected the order | ❌ NO |

---

## Reconciliation Logs

When you see logs like this:
```
[RECONCILIATION] Order 12345: status=REPLACED (TERMINAL) → does NOT block
[RECONCILIATION] Order 12346: BUY 3 SPY 260724C00754000 | status=WORKING (ACTIVE) → blocks=True
```

**Read as:**
- Order 12345 has REPLACED status → Old order, won't block
- Order 12346 has WORKING status → Active order, will block entry

---

## Test Results

**All Tests Passing:**
- ✅ 16 new reconciliation tests (test_schwab_reconciliation.py)
- ✅ 5 live engine tests (test_live_engine_comprehensive.py)
- ✅ 10 protective stop tests (test_protective_stop_orders.py)
- ✅ 10+ other existing tests

**Total: 40+ tests all passing**

---

## Troubleshooting

### Still getting "Trade blocked" message?

1. **Check reconciliation logs** for active orders
2. **Verify in Schwab:** Is the order actually WORKING/PENDING/QUEUED?
3. **If REPLACED/FILLED/CANCELED:** Should not block (bug fixed)
4. **If truly active:** It should block (intended behavior)

### Expected behavior:

```
✅ NO active SPY orders + NO open SPY positions = Trading allowed
❌ ANY active SPY order OR open SPY position = Trading blocked
```

---

## Files Modified

- `execution/live_engine.py` - check_spy_option_exposure() function
- `test_schwab_reconciliation.py` - NEW, 16 comprehensive tests

## No Changes To

- Entry logic
- Exit logic  
- Sizing logic
- Stop logic
- Any other strategy parameters
