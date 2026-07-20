from datetime import datetime
from pathlib import Path
import pandas as pd
from engine.memory import get_memory

today = datetime.now().strftime("%Y-%m-%d")
day_dir = Path("data") / today
signals_file = day_dir / "signals.csv"
report_file = day_dir / "daily_report.txt"

if not signals_file.exists():
    print("No signals file found yet.")
    raise SystemExit

df = get_memory().load_csv_projection(signals_file)

total = len(df)
decisions = df["decision"].value_counts().to_dict()
avg_call = df["call_score"].mean()
avg_put = df["put_score"].mean()
max_call = df["call_score"].max()
max_put = df["put_score"].max()

report = f"""
McLeod Alpha Daily Report
Date: {today}

Signals recorded: {total}

Decision counts:
{decisions}

Average call score: {avg_call:.2f}
Average put score: {avg_put:.2f}

Max call score: {max_call}
Max put score: {max_put}

Strongest call signals:
{df.sort_values("call_score", ascending=False).head(5).to_string(index=False)}

Strongest put signals:
{df.sort_values("put_score", ascending=False).head(5).to_string(index=False)}
"""

get_memory().write_report_text(report_file, report, "daily_signal_report", source="daily_report", correlation_id=f"daily-signal-report:{today}")
print(report)
print(f"Saved report to {report_file}")
