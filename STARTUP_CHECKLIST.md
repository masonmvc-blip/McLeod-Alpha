# McLeod Alpha Trading Bot - Startup Checklist

## Canonical Runtime Flow
- Start stack: `ops/stack_start.sh`
- Check status: `ops/stack_status.sh`
- Stop stack: `ops/stack_stop.sh`
- Control Center direct launch: `ops/run_control_center_waitress.sh`

### Standard Go-Live Command (Desktop)

Use this single command before/after edits to deploy and verify live runtime:

```bash
cd ~/Documents/GitHub/McLeod-Alpha-New
./scripts/maintenance/go_live.sh
```

This command enforces:
- Desktop-only live runtime execution.
- Parity state `MATCH` and `parity_block_start=False`.
- Bot effective running state after restart/start.

Do not use direct `python3 control_center.py` for live operations.

Desktop-only runtime rule:
- Canonical bot host is `Masons-iMac.local` unless `MCLEOD_CANONICAL_RUNTIME_HOST` is explicitly changed.
- Do not run the trading bot from the laptop; non-canonical hosts should be treated as read-only dashboards.
- Canonical Control Center URL: `https://masons-imac.tailb88bd7.ts.net/`
- Legacy laptop URL `https://masons-macbook-pro.tailb88bd7.ts.net/` is not authoritative and should not be used.

Use these scripts as the blessed operational path to avoid stale process/file confusion.

**Deployment Date:** 2026-07-14  
**Account:** 33310903 (Live Schwab)  
**Mode:** LIVE TRADING  

---

## 🔴 PRE-START VERIFICATION (Before Running Bot)

### Configuration Files
- [ ] `.env` exists and contains:
  - [ ] `SCHWAB_APP_KEY` set
  - [ ] `SCHWAB_APP_SECRET` set
  - [ ] `SCHWAB_CALLBACK_URL=https://127.0.0.1:8182`
  - [ ] `ACCOUNT_MODE=live`
  - [ ] `SCHWAB_ACCOUNT_NUMBER=33310903`
  - [ ] `SCHWAB_ACCOUNT_HASH=96636430645ADE50C3BB2834109A7246D6CD53C8FE53D513711FCCD8F53162C4`

### Python Environment
- [ ] Virtual environment activated: `source ./venv/bin/activate`
- [ ] Python 3.9+ available: `python3 --version`
- [ ] All dependencies installed: `pip list | grep schwab`
- [ ] Token file exists: `ls token.json`

### Core Files Present
- [ ] `phase3_monitor.py` exists and is executable
- [ ] `execution/live_engine.py` exists
- [ ] `EMERGENCY_KILL_SWITCH.md` available

### Data Directories
- [ ] `data/` directory exists
- [ ] `logs/` directory exists
- [ ] `data/open_position.json` cleared (or absent): `rm -f data/open_position.json`

---

## 🟢 STARTUP VERIFICATION (When Running Bot)

### Phase 1: Initialization (First 5 seconds)
Watch for these messages in order:

**Console Output Expected:**
```
✓ Account Verified: 33310903 (Live Trading Account)
✓ Live Engine Configured with Account 33310903
✓ Emergency kill switch activated (Ctrl+C to exit cleanly)
Mode: LIVE TRADING
```

**Checklist:**
- [ ] Account verification message appears
- [ ] Live engine configuration message appears
- [ ] Kill switch activation message appears
- [ ] Mode shows "LIVE TRADING" (not "PAPER")
- [ ] No error messages in first 10 seconds

### Phase 2: Signal Data Acquisition (10-30 seconds)
**Console Output Expected:**
```
Candles received: [number > 10]
Regime detected: [BULL or BEAR]
```

**Checklist:**
- [ ] Candles being fetched from Schwab
- [ ] More than 10 candles received
- [ ] Regime detection working (BULL or BEAR shown)
- [ ] No "Waiting for enough candle data" repeating loops

### Phase 3: Trading Loop Active (After 30 seconds)
**Console Output Expected:**
```
[Continuous loop of candle updates every 60 seconds]
Ready for entry...
```

**Checklist:**
- [ ] Trading loop running continuously
- [ ] Candle updates appearing every ~60 seconds
- [ ] Regime showing as BULL or BEAR
- [ ] No exception stack traces
- [ ] CPU usage stable (not spinning)

---

## 📊 LIVE TRADING STATUS CHECK

Once bot is running, verify these conditions are met:

### Configuration Verification
```bash
# Run in another terminal while bot is running:
grep "ACCOUNT_MODE" .env          # Should show: ACCOUNT_MODE=live
grep "ACCOUNT_NUMBER" .env        # Should show: ACCOUNT_NUMBER=33310903
python3 auth_test.py              # Should show: READY FOR LIVE TRADING
```

**Checklist:**
- [ ] `ACCOUNT_MODE` shows `live`
- [ ] Account number is `33310903`
- [ ] `auth_test.py` shows "READY FOR LIVE TRADING"
- [ ] No "test" or "paper" keywords in configuration

### Signal Generation Test
Look for these in bot output within first 2 minutes:

**Expected Signals:**
```
CALL signal: score=X, entry=price, stop=price, target=price
PUT signal: score=X, entry=price, stop=price, target=price
```

**Checklist:**
- [ ] Signal generation active (CALL or PUT signals appearing)
- [ ] Entry prices reasonable (within 1% of current SPY)
- [ ] Stop levels below entry price (reasonable distance)
- [ ] Target levels above entry price
- [ ] Signal scores > 5 (threshold met)

### Live Engine Verification
Look for these indicators in logs:

**Checklist:**
- [ ] Orders marked with 🔴 LIVE prefix (if trade enters)
- [ ] No "PAPER" mode indicators in logs
- [ ] No alternate execution-engine messages
- [ ] Position tracking shows Schwab order IDs (if live order placed)

---

## ⚠️ CRITICAL CHECKPOINTS (Red Flags to Watch)

### STOP BOT Immediately If You See:
- [ ] ❌ "Mode: PAPER ONLY" - Wrong mode! Stop and fix.
- [ ] ❌ "Failed to verify account" - Account mismatch! Stop and check.
- [ ] ❌ "Hash mismatch" - Wrong account configured! Stop.
- [ ] ❌ Exception stack trace with database error - Stop and check logs.
- [ ] ❌ "Candle fetch error" persisting for >3 minutes - Stop and restart.
- [ ] ❌ Position file corrupted message - Stop and check data/open_position.json.

### CAUTION (Monitor Closely):
- ⚠️ No signals generated after 5 minutes - Check regime detection
- ⚠️ Entry score showing as very low (<2) - May indicate data issue
- ⚠️ Same signal repeating multiple times - Check entry logic
- ⚠️ Very frequent trades (>1 per minute) - Check thresholds

---

## 🎯 OPERATIONAL READINESS

Once all above items verified, confirm:

### Safety Features Active
- [ ] Emergency kill switch registered (Ctrl+C works)
- [ ] Position preservation enabled
- [ ] Log flushing active
- [ ] Database integrity checks running

### Trading Parameters Confirmed
- [ ] Max trades per day: 20
- [ ] Entry window: 09:30 - 15:45 ET
- [ ] Forced exit: 15:59 ET
- [ ] Contracts per trade: 1
- [ ] Call threshold: 5
- [ ] Put threshold: 5

### Risk Management Active
- [ ] Position sizing: 1 contract
- [ ] Stop level: ~2.25% below entry
- [ ] Trailing stops: Active at profit milestones
- [ ] Max hold: 15 minutes per position

---

## 📋 LIVE TRADING SESSION CHECKLIST

### Before Market Open (09:25 ET)
- [ ] Verify .env configuration is correct
- [ ] Clear old position file: `rm -f data/open_position.json`
- [ ] Check disk space: `df -h`
- [ ] Verify logs directory writable: `touch logs/test.log && rm logs/test.log`
- [ ] Schwab website accessible and logged in
- [ ] Keep Schwab interface visible (check positions)

### At Market Open (09:30 ET)
- [ ] Start bot: `./phase3_monitor.py`
- [ ] Watch for initialization messages (should take ~10 seconds)
- [ ] Verify "LIVE TRADING" mode confirmed
- [ ] Account verification passes
- [ ] Kill switch message appears
- [ ] First candles fetched successfully

### During Market Hours (09:30 - 15:45 ET)
- [ ] Monitor bot output every 15-30 minutes
- [ ] Check for any error messages or exceptions
- [ ] Verify positions appear in Schwab (if trade enters)
- [ ] Monitor position management updates
- [ ] Check that trades respect time windows
- [ ] Verify stop/target logic working

### Before Market Close (15:45 ET)
- [ ] No new entries after 15:45 ET (forced exit window)
- [ ] Any open positions being managed to exit
- [ ] Trades closing by forced exit time (15:59 ET)
- [ ] Position file updated with final status

### After Market Close (16:00 ET)
- [ ] Review daily trading log
- [ ] Verify all trades closed
- [ ] Check final P&L for day
- [ ] Review any warning messages
- [ ] Can press Ctrl+C for clean shutdown if desired

---

## 🛑 EMERGENCY PROCEDURES

### If Bot Needs Immediate Stop
1. Press **Ctrl+C** (graceful shutdown)
2. Wait for shutdown message
3. Verify position preserved message
4. Check position file: `cat data/open_position.json`

### If Bot Hangs or Crashes
1. Press **Ctrl+C** first (gives graceful shutdown chance)
2. If no response, press **Ctrl+C** again
3. If still no response, check logs: `tail -f logs/trades.log`
4. Last resort: `kill -9 <PID>` (not recommended)

### If Position Stuck After Stop
1. Check Schwab interface for open orders
2. Manually cancel orders on Schwab if needed
3. On restart, bot will resume management

---

## 📊 DAILY STATUS REPORT (End of Day)

After market close, note:
- **Total Trades:** ___________
- **Winners:** ___________ (W%)
- **Losers:** ___________ (L%)
- **Net P&L:** ___________
- **Largest Win:** ___________
- **Largest Loss:** ___________
- **Any Issues:** ___________
- **Corrective Actions:** ___________

---

## ✅ FINAL GO/NO-GO DECISION

### GO for Live Trading if:
- ✓ All pre-start verification items checked
- ✓ All startup verification messages appeared
- ✓ No red flag warnings seen
- ✓ Configuration matches intended setup
- ✓ Account verified as 33310903 (production)
- ✓ Mode shows LIVE TRADING
- ✓ Safety features confirmed active
- ✓ You have Schwab interface available

### NO-GO for Live Trading if:
- ✗ Any configuration items missing
- ✗ Account verification failed
- ✗ Mode shows PAPER or other than LIVE
- ✗ Hash mismatch detected
- ✗ Any exception or error messages
- ✗ Kill switch not registering
- ✗ Signals not generating
- ✗ Candle data not fetching

---

## 🎬 STARTUP COMMAND (2026-07-14 Market Open)

```bash
# Activate environment and start bot
cd /Users/mason/Library/CloudStorage/Dropbox/McLeod\ Capital/McLeod\ Alpha
source ./venv/bin/activate
rm -f data/open_position.json
./phase3_monitor.py
```

**Expected First Output (within 10 seconds):**
```
✓ Account Verified: 33310903 (Live Trading Account)
✓ Live Engine Configured with Account 33310903
✓ Emergency kill switch activated (Ctrl+C to exit cleanly)
Mode: LIVE TRADING
Candles received: [number]
Regime detected: [BULL/BEAR]
Ready for entry...
```

If you see this output, bot is ready for live trading.

---

## 📞 TROUBLESHOOTING REFERENCE

| Issue | Solution |
|-------|----------|
| "Account not found" | Check SCHWAB_ACCOUNT_NUMBER in .env (should be 33310903) |
| "Hash mismatch" | Run `python3 auth_test.py` to get correct hash, update .env |
| "Mode: PAPER ONLY" | Change ACCOUNT_MODE=live in .env |
| "No candles received" | Check Schwab API credentials, verify market hours |
| "Stuck in startup loop" | Check logs, may need to restart or check network |
| "Position file corrupt" | Delete it: `rm data/open_position.json`, restart |
| Ctrl+C not working | Press Ctrl+C again (signal may take a moment) |
| Bot won't start | Check Python version, verify venv activated, check .env |

---

## ✨ SUCCESS CRITERIA

Bot is ready for live trading when:

1. ✅ Starts without errors
2. ✅ Account verified as 33310903
3. ✅ Mode shows LIVE TRADING
4. ✅ Kill switch registered
5. ✅ Candles fetching successfully
6. ✅ Regime detection working
7. ✅ Signal generation active
8. ✅ No exceptions or errors
9. ✅ Ready to enter trades on real Schwab account

---

**Created:** 2026-07-13  
**Status:** Ready for 2026-07-14 Deployment  
**Account:** 33310903 (Live Production)  
**Mode:** LIVE TRADING

---

## 📝 Session Notes

Use this space to note any observations during startup or trading:

```
[Session 1]
Date: 2026-07-14
Time Started: ________
Time Ended: ________
Status: ✓ OK / ✗ ISSUE
Notes: 


[Session 2]
Date: 
Time Started: ________
Time Ended: ________
Status: ✓ OK / ✗ ISSUE
Notes: 
```

---

**Next Step:** Print this checklist and keep it handy during 2026-07-14 market open.
