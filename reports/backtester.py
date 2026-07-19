import pandas as pd
from pathlib import Path

SIGNALS = Path("logs/signals.csv")

OPTION_ENTRY = 1.25
OPTION_DELTA = 0.55
CONTRACTS = 10

TARGET_PCT = 5
STOP_PCT = -5

if not SIGNALS.exists():
    print("No signals file found.")
    raise SystemExit

df = pd.read_csv(SIGNALS)
df["timestamp"] = pd.to_datetime(df["timestamp"])
df = df.sort_values("timestamp").reset_index(drop=True)

trades = []
in_trade = False
trade = None

for _, row in df.iterrows():
    spy_price = float(row["price"])

    if not in_trade:
        if row["regime"] == "BULL_TREND" and row["call_score"] >= 5:
            in_trade = True
            trade = {
                "entry_time": row["timestamp"],
                "direction": "CALL",
                "entry_spy": spy_price,
                "entry_option": OPTION_ENTRY,
                "entry_score": row["call_score"],
                "regime": row["regime"],
                "best_return": 0,
                "worst_return": 0,
            }

        elif row["regime"] == "BEAR_TREND" and row["put_score"] >= 5:
            in_trade = True
            trade = {
                "entry_time": row["timestamp"],
                "direction": "PUT",
                "entry_spy": spy_price,
                "entry_option": OPTION_ENTRY,
                "entry_score": row["put_score"],
                "regime": row["regime"],
                "best_return": 0,
                "worst_return": 0,
            }

        continue

    if trade["direction"] == "CALL":
        spy_move = spy_price - trade["entry_spy"]
    else:
        spy_move = trade["entry_spy"] - spy_price

    option_price = trade["entry_option"] + (spy_move * OPTION_DELTA)
    option_return_pct = ((option_price - trade["entry_option"]) / trade["entry_option"]) * 100

    trade["best_return"] = max(trade["best_return"], option_return_pct)
    trade["worst_return"] = min(trade["worst_return"], option_return_pct)

    if option_return_pct >= TARGET_PCT or option_return_pct <= STOP_PCT:
        trade["exit_time"] = row["timestamp"]
        trade["exit_spy"] = spy_price
        trade["exit_option"] = option_price
        trade["option_return_pct"] = option_return_pct
        trade["option_pnl"] = (option_price - trade["entry_option"]) * 100 * CONTRACTS
        trade["exit_reason"] = "OPTION_TARGET" if option_return_pct >= TARGET_PCT else "OPTION_STOP"
        trades.append(trade)

        in_trade = False
        trade = None

results = pd.DataFrame(trades)

print("\nMcLeod Alpha Options Backtest")
print("-----------------------------")

if results.empty:
    print("No option trades generated.")
    raise SystemExit

wins = results[results["option_pnl"] > 0]
losses = results[results["option_pnl"] <= 0]

print(f"Trades: {len(results)}")
print(f"Wins: {len(wins)}")
print(f"Losses: {len(losses)}")
print(f"Win rate: {len(wins) / len(results) * 100:.1f}%")
print(f"Total option PnL: ${results['option_pnl'].sum():.2f}")
print(f"Average option PnL: ${results['option_pnl'].mean():.2f}")
print(f"Best option return: {results['option_return_pct'].max():.2f}%")
print(f"Worst option return: {results['option_return_pct'].min():.2f}%")
print(f"Average best unrealized return: {results['best_return'].mean():.2f}%")
print(f"Average worst unrealized return: {results['worst_return'].mean():.2f}%")

print("\nBy direction:")
print(results.groupby("direction")["option_pnl"].agg(["count", "sum", "mean"]))

print("\nBy entry score:")
print(results.groupby("entry_score")["option_pnl"].agg(["count", "sum", "mean"]))

print("\nBy exit reason:")
print(results.groupby("exit_reason")["option_pnl"].agg(["count", "sum", "mean"]))

print("\nRecent trades:")
print(results.tail(20).to_string(index=False))