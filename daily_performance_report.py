#!/usr/bin/env python3
"""
McLeod Alpha Daily Performance Report

Reads trade_log from data/mcleod_alpha.db and generates a comprehensive
daily trading report for the specified date (defaults to today).

Usage:
  python daily_performance_report.py --date 2026-07-13
  python daily_performance_report.py  # uses today
"""

import sqlite3
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import statistics


def safe_parse_feature_payload(payload_str):
    """Safely parse feature_payload JSON, return dict or empty dict on failure."""
    if not payload_str:
        return {}
    try:
        return json.loads(payload_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def safe_get(d, key, default="N/A"):
    """Safely get value from dict, return default if missing or None."""
    if d is None:
        return default
    val = d.get(key, default)
    return val if val is not None else default


def format_dollar(val):
    """Format dollar value, return N/A for None."""
    if val is None or val == "N/A":
        return "N/A"
    return f"${val:,.2f}"


def format_pct(val):
    """Format percentage value, return N/A for None."""
    if val is None or val == "N/A":
        return "N/A"
    return f"{val:.2f}%"


def format_time_duration(td):
    """Format timedelta to human-readable format."""
    if td is None:
        return "N/A"
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_trades_for_date(db_path, target_date):
    """
    Query trade_log for all trades with entry_time on target_date.
    target_date should be a datetime.date object.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Format date range for SQL
    date_str = target_date.strftime("%Y-%m-%d")
    next_date = target_date + timedelta(days=1)
    next_date_str = next_date.strftime("%Y-%m-%d")

    query = """
    SELECT * FROM trade_log 
    WHERE DATE(entry_time) = ?
    ORDER BY entry_time ASC
    """

    cursor.execute(query, (date_str,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def calculate_hold_time(entry_time_str, exit_time_str):
    """Calculate hold time as timedelta."""
    if not entry_time_str or not exit_time_str:
        return None
    try:
        entry = datetime.fromisoformat(entry_time_str)
        exit_t = datetime.fromisoformat(exit_time_str)
        return exit_t - entry
    except (ValueError, TypeError):
        return None


def generate_report(db_path, target_date):
    """Generate the complete daily performance report."""
    trades = get_trades_for_date(db_path, target_date)

    if not trades:
        print(f"\nNo trades found for {target_date.strftime('%Y-%m-%d')}\n")
        return

    # Parse all feature payloads
    for trade in trades:
        trade["_feature_payload"] = safe_parse_feature_payload(
            trade.get("feature_payload")
        )
        trade["_hold_time"] = calculate_hold_time(
            trade.get("entry_time"), trade.get("exit_time")
        )

    print("\n" + "=" * 50)
    print("MCLEOD ALPHA DAILY REPORT")
    print("=" * 50)
    print(f"Date: {target_date.strftime('%Y-%m-%d')}\n")

    # ===== OVERALL PERFORMANCE =====
    print("OVERALL PERFORMANCE")
    print("-" * 50)

    total_trades = len(trades)
    winners = sum(1 for t in trades if safe_get(t, "option_pnl_dollars") != "N/A" and t.get("option_pnl_dollars", 0) > 0)
    losers = sum(1 for t in trades if safe_get(t, "option_pnl_dollars") != "N/A" and t.get("option_pnl_dollars", 0) < 0)
    breakeven = sum(1 for t in trades if safe_get(t, "option_pnl_dollars") != "N/A" and t.get("option_pnl_dollars", 0) == 0)

    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
    net_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in trades)
    
    option_pnl_values = [t.get("option_pnl_dollars", 0) or 0 for t in trades if t.get("option_pnl_dollars") is not None]
    option_pnl_pcts = [t.get("option_pnl_pct", 0) or 0 for t in trades if t.get("option_pnl_pct") is not None]
    
    avg_return_pct = statistics.mean(option_pnl_pcts) if option_pnl_pcts else 0

    winner_dollars = [t.get("option_pnl_dollars", 0) for t in trades if t.get("option_pnl_dollars", 0) > 0]
    loser_dollars = [t.get("option_pnl_dollars", 0) for t in trades if t.get("option_pnl_dollars", 0) < 0]

    avg_winner_dollars = statistics.mean(winner_dollars) if winner_dollars else 0
    avg_loser_dollars = statistics.mean(loser_dollars) if loser_dollars else 0

    winner_pcts = [t.get("option_pnl_pct", 0) for t in trades if t.get("option_pnl_pct", 0) > 0]
    loser_pcts = [t.get("option_pnl_pct", 0) for t in trades if t.get("option_pnl_pct", 0) < 0]

    avg_winner_pct = statistics.mean(winner_pcts) if winner_pcts else 0
    avg_loser_pct = statistics.mean(loser_pcts) if loser_pcts else 0

    profit_factor = abs(sum(winner_dollars) / sum(loser_dollars)) if loser_dollars and sum(loser_dollars) != 0 else (1.0 if not loser_dollars and winner_dollars else 0)
    expectancy = net_pnl / total_trades if total_trades > 0 else 0

    largest_winner = max(winner_dollars) if winner_dollars else 0
    largest_loser = min(loser_dollars) if loser_dollars else 0

    hold_times = [t["_hold_time"] for t in trades if t["_hold_time"] is not None]
    hold_times_seconds = [td.total_seconds() for td in hold_times]
    avg_hold_time_seconds = statistics.mean(hold_times_seconds) if hold_times_seconds else None
    median_hold_time_seconds = statistics.median(hold_times_seconds) if hold_times_seconds else None
    avg_hold_time = timedelta(seconds=avg_hold_time_seconds) if avg_hold_time_seconds is not None else None
    median_hold_time = timedelta(seconds=median_hold_time_seconds) if median_hold_time_seconds is not None else None

    print(f"Total trades:           {total_trades}")
    print(f"Winners:                {winners}")
    print(f"Losers:                 {losers}")
    print(f"Breakeven:              {breakeven}")
    print(f"Win rate:               {win_rate:.2f}%")
    print(f"Net option P/L:         {format_dollar(net_pnl)}")
    print(f"Average option return:  {format_pct(avg_return_pct)}")
    print(f"Average winner:         {format_dollar(avg_winner_dollars)}")
    print(f"Average loser:          {format_dollar(avg_loser_dollars)}")
    print(f"Average winner %:       {format_pct(avg_winner_pct)}")
    print(f"Average loser %:        {format_pct(avg_loser_pct)}")
    print(f"Profit factor:          {profit_factor:.2f}" if profit_factor != 0 else "Profit factor:          N/A")
    print(f"Expectancy per trade:   {format_dollar(expectancy)}")
    print(f"Largest winner:         {format_dollar(largest_winner)}")
    print(f"Largest loser:          {format_dollar(largest_loser)}")
    print(f"Average hold time:      {format_time_duration(avg_hold_time)}")
    print(f"Median hold time:       {format_time_duration(median_hold_time)}")

    # ===== CALL VS PUT =====
    print("\n" + "=" * 50)
    print("CALL VS PUT")
    print("-" * 50)

    for direction in ["CALL", "PUT"]:
        dir_trades = [t for t in trades if t.get("direction") == direction]
        if not dir_trades:
            continue

        dir_winners = sum(1 for t in dir_trades if t.get("option_pnl_dollars", 0) > 0)
        dir_win_rate = (dir_winners / len(dir_trades) * 100) if dir_trades else 0
        dir_net_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in dir_trades)
        dir_avg_pnl = dir_net_pnl / len(dir_trades) if dir_trades else 0
        dir_pnl_pcts = [t.get("option_pnl_pct", 0) or 0 for t in dir_trades if t.get("option_pnl_pct") is not None]
        dir_avg_pct = statistics.mean(dir_pnl_pcts) if dir_pnl_pcts else 0

        print(f"\n{direction}:")
        print(f"  Trade count:     {len(dir_trades)}")
        print(f"  Winners:         {dir_winners}")
        print(f"  Win rate:        {dir_win_rate:.2f}%")
        print(f"  Net P/L:         {format_dollar(dir_net_pnl)}")
        print(f"  Avg P/L:         {format_dollar(dir_avg_pnl)}")
        print(f"  Avg return %:    {format_pct(dir_avg_pct)}")

    # ===== EXIT ANALYSIS =====
    print("\n" + "=" * 50)
    print("EXIT ANALYSIS")
    print("-" * 50)

    exit_reasons = defaultdict(list)
    for trade in trades:
        reason = trade.get("exit_reason", "Unknown")
        exit_reasons[reason].append(trade)

    for reason in sorted(exit_reasons.keys()):
        reason_trades = exit_reasons[reason]
        reason_winners = sum(1 for t in reason_trades if t.get("option_pnl_dollars", 0) > 0)
        reason_win_rate = (reason_winners / len(reason_trades) * 100) if reason_trades else 0
        reason_net_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in reason_trades)
        reason_avg_pnl = reason_net_pnl / len(reason_trades) if reason_trades else 0
        reason_pnl_pcts = [t.get("option_pnl_pct", 0) or 0 for t in reason_trades if t.get("option_pnl_pct") is not None]
        reason_avg_pct = statistics.mean(reason_pnl_pcts) if reason_pnl_pcts else 0

        print(f"\n{reason}:")
        print(f"  Count:           {len(reason_trades)}")
        print(f"  Win rate:        {reason_win_rate:.2f}%")
        print(f"  Net P/L:         {format_dollar(reason_net_pnl)}")
        print(f"  Avg P/L:         {format_dollar(reason_avg_pnl)}")
        print(f"  Avg return %:    {format_pct(reason_avg_pct)}")

    # ===== TRADE BREAKDOWN =====
    print("\n" + "=" * 50)
    print("TRADE BREAKDOWN")
    print("-" * 50)

    for idx, trade in enumerate(trades, 1):
        fp = trade["_feature_payload"]
        entry_score = safe_get(fp, "entry_score", "N/A")
        entry_reasons = safe_get(fp, "entry_reasons", [])
        if isinstance(entry_reasons, list):
            entry_reasons_str = ", ".join(entry_reasons)
        else:
            entry_reasons_str = str(entry_reasons)

        print(f"\nTrade #{idx}:")
        print(f"  Entry time:      {trade.get('entry_time', 'N/A')}")
        print(f"  Exit time:       {trade.get('exit_time', 'N/A')}")
        print(f"  Hold duration:   {format_time_duration(trade['_hold_time'])}")
        print(f"  Direction:       {trade.get('direction', 'N/A')}")
        print(f"  Option symbol:   {trade.get('option_symbol', 'N/A')}")
        print(f"  Entry score:     {entry_score}")
        print(f"  Entry reasons:   {entry_reasons_str if entry_reasons_str else 'N/A'}")
        print(f"  Option entry:    {format_dollar(trade.get('option_entry'))}")
        print(f"  Option exit:     {format_dollar(trade.get('option_exit'))}")
        print(f"  Quantity:        {trade.get('option_quantity', 'N/A')}")
        print(f"  Dollar P/L:      {format_dollar(trade.get('option_pnl_dollars'))}")
        print(f"  Percent return:  {format_pct(trade.get('option_pnl_pct'))}")
        print(f"  Exit reason:     {trade.get('exit_reason', 'N/A')}")

    # ===== SIGNAL STATISTICS =====
    print("\n" + "=" * 50)
    print("SIGNAL STATISTICS")
    print("-" * 50)

    all_signals = defaultdict(list)
    for trade in trades:
        fp = trade["_feature_payload"]
        reasons = safe_get(fp, "entry_reasons", [])
        if isinstance(reasons, list):
            for reason in reasons:
                all_signals[reason].append(trade)

    if not all_signals:
        print("No entry reasons found in feature_payload")
    else:
        for signal in sorted(all_signals.keys()):
            signal_trades = all_signals[signal]
            signal_winners = sum(1 for t in signal_trades if t.get("option_pnl_dollars", 0) > 0)
            signal_win_rate = (signal_winners / len(signal_trades) * 100) if signal_trades else 0
            signal_net_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in signal_trades)
            signal_pnl_pcts = [t.get("option_pnl_pct", 0) or 0 for t in signal_trades if t.get("option_pnl_pct") is not None]
            signal_avg_pct = statistics.mean(signal_pnl_pcts) if signal_pnl_pcts else 0

            print(f"\n{signal}:")
            print(f"  Times used:      {len(signal_trades)}")
            print(f"  Wins:            {signal_winners}")
            print(f"  Win rate:        {signal_win_rate:.2f}%")
            print(f"  Net P/L:         {format_dollar(signal_net_pnl)}")
            print(f"  Avg return %:    {format_pct(signal_avg_pct)}")

    # ===== ENTRY SCORE STATISTICS =====
    print("\n" + "=" * 50)
    print("ENTRY SCORE STATISTICS")
    print("-" * 50)

    entry_scores = defaultdict(list)
    for trade in trades:
        fp = trade["_feature_payload"]
        score = safe_get(fp, "entry_score", "N/A")
        if score != "N/A":
            entry_scores[score].append(trade)

    if not entry_scores:
        print("No entry scores found in feature_payload")
    else:
        for score in sorted(entry_scores.keys()):
            score_trades = entry_scores[score]
            score_winners = sum(1 for t in score_trades if t.get("option_pnl_dollars", 0) > 0)
            score_win_rate = (score_winners / len(score_trades) * 100) if score_trades else 0
            score_net_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in score_trades)
            score_pnl_pcts = [t.get("option_pnl_pct", 0) or 0 for t in score_trades if t.get("option_pnl_pct") is not None]
            score_avg_pct = statistics.mean(score_pnl_pcts) if score_pnl_pcts else 0

            print(f"\nEntry score {score}:")
            print(f"  Trade count:     {len(score_trades)}")
            print(f"  Winners:         {score_winners}")
            print(f"  Win rate:        {score_win_rate:.2f}%")
            print(f"  Net P/L:         {format_dollar(score_net_pnl)}")
            print(f"  Avg return %:    {format_pct(score_avg_pct)}")

    # ===== SUPPORT / RESISTANCE SUMMARY =====
    print("\n" + "=" * 50)
    print("SUPPORT / RESISTANCE SUMMARY")
    print("-" * 50)

    sr_distances_res = []
    sr_distances_sup = []
    close_above_res_trades = []
    close_below_sup_trades = []
    near_res_trades = []
    near_sup_trades = []

    for trade in trades:
        fp = trade["_feature_payload"]
        sr = safe_get(fp, "support_resistance", {})
        
        dist_res_pct = safe_get(sr, "distance_to_resistance_pct")
        dist_sup_pct = safe_get(sr, "distance_to_support_pct")
        
        if dist_res_pct != "N/A":
            sr_distances_res.append(dist_res_pct)
        if dist_sup_pct != "N/A":
            sr_distances_sup.append(dist_sup_pct)
        
        if safe_get(sr, "closed_above_resistance") == True:
            close_above_res_trades.append(trade)
        if safe_get(sr, "closed_below_support") == True:
            close_below_sup_trades.append(trade)
        
        nearest_res = safe_get(sr, "nearest_resistance")
        nearest_sup = safe_get(sr, "nearest_support")
        if nearest_res != "N/A":
            near_res_trades.append(trade)
        if nearest_sup != "N/A":
            near_sup_trades.append(trade)

    avg_dist_res = statistics.mean(sr_distances_res) if sr_distances_res else 0
    avg_dist_sup = statistics.mean(sr_distances_sup) if sr_distances_sup else 0

    print(f"Avg distance to resistance %: {format_pct(avg_dist_res)}")
    print(f"Avg distance to support %:   {format_pct(avg_dist_sup)}")

    if close_above_res_trades:
        res_winners = sum(1 for t in close_above_res_trades if t.get("option_pnl_dollars", 0) > 0)
        res_wr = (res_winners / len(close_above_res_trades) * 100)
        res_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in close_above_res_trades)
        print(f"\nClosed above resistance ({len(close_above_res_trades)} trades):")
        print(f"  Win rate:        {res_wr:.2f}%")
        print(f"  Net P/L:         {format_dollar(res_pnl)}")

    if close_below_sup_trades:
        sup_winners = sum(1 for t in close_below_sup_trades if t.get("option_pnl_dollars", 0) > 0)
        sup_wr = (sup_winners / len(close_below_sup_trades) * 100)
        sup_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in close_below_sup_trades)
        print(f"\nClosed below support ({len(close_below_sup_trades)} trades):")
        print(f"  Win rate:        {sup_wr:.2f}%")
        print(f"  Net P/L:         {format_dollar(sup_pnl)}")

    # ===== MACD SUMMARY =====
    print("\n" + "=" * 50)
    print("MACD SUMMARY")
    print("-" * 50)

    bull_cross_trades = []
    bear_cross_trades = []
    hist_strengthen_trades = []
    hist_weaken_trades = []

    for trade in trades:
        fp = trade["_feature_payload"]
        macd = safe_get(fp, "macd", {})
        
        if safe_get(macd, "bullish_crossover_last_3_candles") == True:
            bull_cross_trades.append(trade)
        if safe_get(macd, "bearish_crossover_last_3_candles") == True:
            bear_cross_trades.append(trade)
        
        hist_dir = safe_get(macd, "histogram_direction")
        if hist_dir == "STRENGTHENING":
            hist_strengthen_trades.append(trade)
        elif hist_dir == "WEAKENING":
            hist_weaken_trades.append(trade)

    for label, tlist in [
        ("Bullish crossover", bull_cross_trades),
        ("Bearish crossover", bear_cross_trades),
        ("Histogram strengthening", hist_strengthen_trades),
        ("Histogram weakening", hist_weaken_trades),
    ]:
        if tlist:
            winners = sum(1 for t in tlist if t.get("option_pnl_dollars", 0) > 0)
            wr = (winners / len(tlist) * 100)
            pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in tlist)
            print(f"\n{label} ({len(tlist)} trades):")
            print(f"  Win rate:        {wr:.2f}%")
            print(f"  Net P/L:         {format_dollar(pnl)}")

    # ===== TIME-OF-DAY ANALYSIS =====
    print("\n" + "=" * 50)
    print("TIME-OF-DAY ANALYSIS")
    print("-" * 50)

    hour_trades = defaultdict(list)
    for trade in trades:
        entry_time_str = trade.get("entry_time")
        if entry_time_str:
            try:
                entry_dt = datetime.fromisoformat(entry_time_str)
                hour = entry_dt.hour
                hour_trades[hour].append(trade)
            except (ValueError, TypeError):
                pass

    if hour_trades:
        for hour in sorted(hour_trades.keys()):
            hour_list = hour_trades[hour]
            hour_winners = sum(1 for t in hour_list if t.get("option_pnl_dollars", 0) > 0)
            hour_wr = (hour_winners / len(hour_list) * 100) if hour_list else 0
            hour_pnl = sum(t.get("option_pnl_dollars", 0) or 0 for t in hour_list)
            hour_pnl_pcts = [t.get("option_pnl_pct", 0) or 0 for t in hour_list if t.get("option_pnl_pct") is not None]
            hour_avg_pct = statistics.mean(hour_pnl_pcts) if hour_pnl_pcts else 0

            print(f"\n{hour:02d}:00 ({len(hour_list)} trades):")
            print(f"  Win rate:        {hour_wr:.2f}%")
            print(f"  Net P/L:         {format_dollar(hour_pnl)}")
            print(f"  Avg return %:    {format_pct(hour_avg_pct)}")
    else:
        print("No trades with valid entry times")

    print("\n" + "=" * 50 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="McLeod Alpha Daily Performance Report"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Date in YYYY-MM-DD format (defaults to today)",
    )

    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD")
            return
    else:
        target_date = datetime.now().date()

    db_path = Path("data/mcleod_alpha.db")
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return

    generate_report(db_path, target_date)


if __name__ == "__main__":
    main()
