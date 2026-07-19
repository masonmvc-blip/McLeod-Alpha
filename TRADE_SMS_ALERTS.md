# Trade SMS Alerts

This project can send you a text message on every option trade entry and exit.

## 1) Configure environment variables (free methods)

### Option A: macOS Mail.app relay (no SMTP password required)

```bash
ENABLE_TRADE_SMS_ALERTS=true
TRADE_ALERT_TRANSPORT=mailapp_sms
TRADE_ALERT_TO_GATEWAY=5551234567@vtext.com
```

This uses your already-configured Mail app account to send to the carrier gateway.

### Option B: SMTP relay

Add these to your `.env` file:

```bash
ENABLE_TRADE_SMS_ALERTS=true
TRADE_ALERT_TRANSPORT=email_sms
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@example.com
SMTP_PASSWORD=your_email_app_password
SMTP_FROM=you@example.com
TRADE_ALERT_TO_GATEWAY=5551234567@vtext.com
```

Carrier gateway examples (US):
- Verizon: `number@vtext.com`
- AT&T: `number@txt.att.net`
- T-Mobile: `number@tmomail.net`
- US Cellular: `number@email.uscc.net`

## 1.5) Optional Twilio fallback

If you prefer Twilio or want fallback mode:

```bash
TRADE_ALERT_TRANSPORT=auto   # tries email_sms first, then Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1YOUR_TWILIO_NUMBER
TRADE_ALERT_TO_NUMBER=+1YOUR_MOBILE_NUMBER
```

## 2) Where alerts fire

- Live options entry fill confirmed: `execution/live_engine.py`
- Live options exit: `execution/live_engine.py`
- Paper options entry: `execution/paper_engine.py`
- Paper options exit: `execution/paper_engine.py`
- Legacy paper path entry/exit: `paper_trader.py`

## 2.5) Send a one-time test text

Run:

```bash
venv/bin/python scripts/test_trade_sms.py
```

Expected output:
- `SMS test sent successfully` when config is valid
- A warning message if SMS is disabled or credentials are missing

## 3) Message contents

Entry alert includes:
- Mode (LIVE/PAPER)
- Direction (CALL/PUT)
- Quantity
- Option symbol
- Option entry price
- SPY entry price
- Entry reason

Exit alert includes:
- Mode (LIVE/PAPER)
- Direction
- Quantity
- Option symbol
- Option entry and exit prices
- Option PnL dollars and percent (if available)
- Exit reason

## Notes

- Alerts are disabled unless `ENABLE_TRADE_SMS_ALERTS=true`.
- If gateway/Twilio config is missing or invalid, trade execution continues and logs an SMS warning.
- Free mode uses SMTP email-to-SMS gateway delivery.
- Twilio mode uses Twilio REST API via `requests`.
