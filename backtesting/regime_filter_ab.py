"""A/B market-regime filter analysis for backtesting only.

This module does not alter live or paper trading behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd

import backtesting.signal_replay as sr_module
from backtesting import load_csv_data, ReplayEngine
from backtesting.option_pricer import EstimatedOptionPricer
from backtesting.signal_replay import SignalReplayEngine
from backtesting.trade_simulator import TradeSimulator
from strategy.signals import is_regime_aligned


@dataclass
class ExperimentConfig:
    call_threshold: int = 5
    put_threshold: int = 5
    include_premarket: bool = True
    max_trades_per_day: int = 20


def _run_simulation(csv_path: Path, config: ExperimentConfig, force_alignment: Optional[bool]) -> pd.DataFrame:
    """Run a single deterministic simulation and return trades DataFrame."""
    df = load_csv_data(str(csv_path))
    replay_engine = ReplayEngine(df, include_premarket=config.include_premarket)

    orig_align = sr_module.is_regime_aligned
    if force_alignment is True:
        sr_module.is_regime_aligned = lambda direction, market_regime: True
    elif force_alignment is False:
        sr_module.is_regime_aligned = orig_align

    try:
        signal_engine = SignalReplayEngine(
            replay_engine=replay_engine,
            call_threshold=config.call_threshold,
            put_threshold=config.put_threshold,
        )
        simulator = TradeSimulator(
            replay_engine=replay_engine,
            signal_engine=signal_engine,
            option_pricer=EstimatedOptionPricer(),
            max_trades_per_day=config.max_trades_per_day,
        )
        simulator.run()
        trades_df = simulator.get_trades_dataframe().copy()
    finally:
        sr_module.is_regime_aligned = orig_align

    if trades_df.empty:
        return trades_df

    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True)
    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"], utc=True, errors="coerce")
    trades_df = trades_df.sort_values(["entry_time", "direction"]).reset_index(drop=True)
    trades_df["sequence_id"] = trades_df.index + 1
    return trades_df


def _metrics(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return {
            "total_trades": 0,
            "calls": 0,
            "puts": 0,
            "winners": 0,
            "losers": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "avg_winner": 0.0,
            "avg_loser": 0.0,
            "max_drawdown": 0.0,
            "avg_return": 0.0,
            "median_return": 0.0,
        }

    pnl = df["dollar_pnl"].astype(float)
    returns = df["percent_pnl"].astype(float)

    winners_mask = pnl > 0
    losers_mask = pnl < 0

    winners = int(winners_mask.sum())
    losers = int(losers_mask.sum())
    total = int(len(df))

    gross_profit = float(pnl[winners_mask].sum())
    gross_loss = float((-pnl[losers_mask]).sum())

    cumulative = pnl.cumsum()
    drawdown = cumulative.cummax() - cumulative

    return {
        "total_trades": total,
        "calls": int((df["direction"] == "CALL").sum()),
        "puts": int((df["direction"] == "PUT").sum()),
        "winners": winners,
        "losers": losers,
        "win_rate": float((winners / total) * 100.0) if total else 0.0,
        "net_pnl": float(pnl.sum()),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
        "expectancy": float(pnl.mean()),
        "avg_winner": float(pnl[winners_mask].mean()) if winners else 0.0,
        "avg_loser": float((-pnl[losers_mask]).mean()) if losers else 0.0,
        "max_drawdown": float(drawdown.max()) if len(drawdown) else 0.0,
        "avg_return": float(returns.mean()),
        "median_return": float(returns.median()),
    }


def _build_blocked_trades(baseline_df: pd.DataFrame) -> pd.DataFrame:
    if baseline_df.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "direction",
                "market_regime",
                "entry_score",
                "entry_reasons",
                "estimated_pnl_if_taken",
                "winner_or_loser",
                "exit_reason",
                "time_of_day",
                "sequence_id",
            ]
        )

    blocked_rows: List[Dict[str, object]] = []
    for _, row in baseline_df.iterrows():
        direction = str(row["direction"])
        regime = str(row["market_regime"])
        if is_regime_aligned(direction, regime):
            continue

        pnl = float(row["dollar_pnl"])
        if pnl > 0:
            outcome = "WINNER"
        elif pnl < 0:
            outcome = "LOSER"
        else:
            outcome = "BREAKEVEN"

        ts = pd.to_datetime(row["entry_time"], utc=True)
        blocked_rows.append(
            {
                "timestamp": ts.isoformat(),
                "direction": direction,
                "market_regime": regime,
                "entry_score": int(row["entry_score"]),
                "entry_reasons": row["entry_reasons"],
                "estimated_pnl_if_taken": round(pnl, 2),
                "winner_or_loser": outcome,
                "exit_reason": row["exit_reason"],
                "time_of_day": ts.tz_convert("America/New_York").strftime("%H:%M"),
                "sequence_id": int(row["sequence_id"]),
            }
        )

    return pd.DataFrame(blocked_rows)


def _build_skip_only(baseline_df: pd.DataFrame) -> pd.DataFrame:
    if baseline_df.empty:
        return baseline_df.copy()

    aligned_mask = baseline_df.apply(
        lambda r: is_regime_aligned(str(r["direction"]), str(r["market_regime"])),
        axis=1,
    )
    out = baseline_df[aligned_mask].copy().reset_index(drop=True)
    out["sequence_id"] = out.index + 1
    return out


def _build_constant_sample(
    baseline_df: pd.DataFrame,
    filtered_natural_df: pd.DataFrame,
    skip_only_df: pd.DataFrame,
    blocked_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build constant-sample accepted trades and explicit replacements."""
    target_n = len(baseline_df)
    skip_keys = set(
        zip(
            pd.to_datetime(skip_only_df.get("entry_time", pd.Series(dtype=str)), utc=True)
            .map(lambda x: x.isoformat())
            .tolist(),
            skip_only_df.get("direction", pd.Series(dtype=str)).astype(str).tolist(),
        )
    )

    needed_replacements = max(0, target_n - len(skip_only_df))

    filtered_pool = filtered_natural_df.copy().reset_index(drop=True)
    filtered_pool["_key_ts"] = pd.to_datetime(filtered_pool["entry_time"], utc=True).map(lambda x: x.isoformat())
    filtered_pool["_key_dir"] = filtered_pool["direction"].astype(str)
    replacement_pool = filtered_pool[
        ~filtered_pool.apply(lambda r: (r["_key_ts"], r["_key_dir"]) in skip_keys, axis=1)
    ].copy()

    selected_replacements = replacement_pool.head(needed_replacements).copy().reset_index(drop=True)

    replacement_rows: List[Dict[str, object]] = []
    blocked_positions = blocked_df["sequence_id"].tolist() if not blocked_df.empty else []
    for idx, row in selected_replacements.iterrows():
        replaced_position = blocked_positions[idx] if idx < len(blocked_positions) else None

        replacement_rows.append(
            {
                "timestamp": pd.to_datetime(row["entry_time"], utc=True).isoformat(),
                "direction": row["direction"],
                "market_regime": row["market_regime"],
                "entry_score": int(row["entry_score"]),
                "entry_reasons": row["entry_reasons"],
                "p_l": round(float(row["dollar_pnl"]), 2),
                "replaced_blocked_sequence": replaced_position,
            }
        )

    const_df = pd.concat([skip_only_df.copy(), selected_replacements.drop(columns=["_key_ts", "_key_dir"], errors="ignore")], ignore_index=True)
    if not const_df.empty:
        const_df = const_df.sort_values(["entry_time", "direction"]).reset_index(drop=True)
        const_df["sequence_id"] = const_df.index + 1

    replacements_df = pd.DataFrame(replacement_rows)
    return const_df, replacements_df


def _blocked_summary_sections(blocked_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    if blocked_df.empty:
        empty = pd.DataFrame(columns=["count", "winners", "losers", "net_pnl", "avg_return", "median_return"])
        return {
            "by_direction": empty,
            "by_regime": empty,
            "by_hour": empty,
        }

    df = blocked_df.copy()
    pnl_col = "estimated_pnl_if_taken"

    def group_stats(group_field: str) -> pd.DataFrame:
        grouped = df.groupby(group_field, dropna=False)
        rows = []
        for key, g in grouped:
            pnl = g[pnl_col].astype(float)
            rows.append(
                {
                    group_field: key,
                    "count": len(g),
                    "winners": int((g["winner_or_loser"] == "WINNER").sum()),
                    "losers": int((g["winner_or_loser"] == "LOSER").sum()),
                    "net_pnl": round(float(pnl.sum()), 2),
                    "avg_return": round(float(pnl.mean()), 2),
                    "median_return": round(float(pnl.median()), 2),
                }
            )
        return pd.DataFrame(rows).sort_values(group_field).reset_index(drop=True)

    df["hour"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York").dt.strftime("%H")

    return {
        "by_direction": group_stats("direction"),
        "by_regime": group_stats("market_regime"),
        "by_hour": group_stats("hour"),
    }


def run_regime_filter_ab(csv_path: Path, output_dir: Path, config: ExperimentConfig) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_df = _run_simulation(csv_path, config, force_alignment=True)
    filtered_natural_df = _run_simulation(csv_path, config, force_alignment=False)

    blocked_df = _build_blocked_trades(baseline_df)
    skip_only_df = _build_skip_only(baseline_df)
    constant_df, replacements_df = _build_constant_sample(baseline_df, filtered_natural_df, skip_only_df, blocked_df)

    skip_path = output_dir / "regime_filter_skip_only.csv"
    constant_path = output_dir / "regime_filter_constant_sample.csv"
    blocked_path = output_dir / "regime_filter_blocked_trades.csv"
    replacement_path = output_dir / "regime_filter_replacement_trades.csv"
    report_path = output_dir / "regime_filter_ab_report.txt"

    skip_only_df.to_csv(skip_path, index=False)
    constant_df.to_csv(constant_path, index=False)
    blocked_df.to_csv(blocked_path, index=False)
    replacements_df.to_csv(replacement_path, index=False)

    baseline_metrics = _metrics(baseline_df)
    skip_metrics = _metrics(skip_only_df)
    constant_metrics = _metrics(constant_df)

    blocked_sections = _blocked_summary_sections(blocked_df)

    skip_validation_ok = len(skip_only_df) <= len(baseline_df)
    constant_has_target = len(constant_df) == len(baseline_df)

    blocked_keys = set(zip(blocked_df.get("timestamp", []), blocked_df.get("direction", [])))
    skip_keys = set(
        zip(
            pd.to_datetime(skip_only_df.get("entry_time", pd.Series(dtype=str)), utc=True)
            .map(lambda x: x.isoformat())
            .tolist(),
            skip_only_df.get("direction", pd.Series(dtype=str)).astype(str).tolist(),
        )
    )
    blocked_excluded_ok = len(blocked_keys.intersection(skip_keys)) == 0

    def fmt_metrics(title: str, m: Dict[str, float]) -> str:
        return "\n".join(
            [
                title,
                f"  Total trades: {m['total_trades']}",
                f"  Calls: {m['calls']}",
                f"  Puts: {m['puts']}",
                f"  Winners: {m['winners']}",
                f"  Losers: {m['losers']}",
                f"  Win rate: {m['win_rate']:.2f}%",
                f"  Net P/L: ${m['net_pnl']:.2f}",
                f"  Profit factor: {m['profit_factor']:.4f}" if m["profit_factor"] != float("inf") else "  Profit factor: inf",
                f"  Expectancy: ${m['expectancy']:.2f}",
                f"  Average winner: ${m['avg_winner']:.2f}",
                f"  Average loser: ${m['avg_loser']:.2f}",
                f"  Maximum drawdown: ${m['max_drawdown']:.2f}",
                f"  Average return: {m['avg_return']:.2f}%",
                f"  Median return: {m['median_return']:.2f}%",
            ]
        )

    net_effect_removed = skip_metrics["net_pnl"] - baseline_metrics["net_pnl"]
    net_effect_replacements = constant_metrics["net_pnl"] - skip_metrics["net_pnl"]
    quality_improved = skip_metrics["expectancy"] > baseline_metrics["expectancy"]
    total_improved = constant_metrics["net_pnl"] > baseline_metrics["net_pnl"]

    with report_path.open("w", encoding="utf-8") as f:
        f.write("Market Regime Filter A/B Report\n")
        f.write("=" * 80 + "\n")
        f.write(f"Data file: {csv_path}\n")
        f.write("Baseline: no market-regime alignment filter (thresholds 5/5)\n")
        f.write("Skip-only: apply filter and permanently skip blocked baseline entries\n")
        f.write("Constant-sample: apply filter and accept later replacements until baseline trade count, if available\n\n")

        f.write(fmt_metrics("Baseline Results", baseline_metrics) + "\n\n")
        f.write(fmt_metrics("Skip-Only Filtered Results", skip_metrics) + "\n\n")
        f.write(fmt_metrics("Constant-Sample Filtered Results", constant_metrics) + "\n\n")

        f.write("Validation\n")
        f.write("-" * 80 + "\n")
        f.write(f"Skip-only count <= baseline: {skip_validation_ok}\n")
        f.write(f"Constant-sample reached baseline count: {constant_has_target}\n")
        f.write(f"Blocked trades excluded from skip-only accepted set: {blocked_excluded_ok}\n")
        f.write(f"Replacement trades identified: {len(replacements_df)}\n\n")

        f.write("Blocked Trade Summary\n")
        f.write("-" * 80 + "\n")
        for label, section in [
            ("By Direction", blocked_sections["by_direction"]),
            ("By Regime", blocked_sections["by_regime"]),
            ("By Hour", blocked_sections["by_hour"]),
        ]:
            f.write(label + "\n")
            if section.empty:
                f.write("  (none)\n")
            else:
                f.write(section.to_string(index=False) + "\n")
            f.write("\n")

        f.write("Net Effects\n")
        f.write("-" * 80 + "\n")
        f.write(f"Net effect of removing blocked trades: ${net_effect_removed:.2f}\n")
        f.write(f"Net effect of replacement trades: ${net_effect_replacements:.2f}\n")
        f.write(f"Regime filter improved accepted-trade quality (expectancy): {quality_improved}\n")
        f.write(f"Regime filter improved total strategy performance (net P/L): {total_improved}\n")

    return {
        "baseline_df": baseline_df,
        "skip_only_df": skip_only_df,
        "constant_df": constant_df,
        "blocked_df": blocked_df,
        "replacements_df": replacements_df,
        "baseline_metrics": baseline_metrics,
        "skip_metrics": skip_metrics,
        "constant_metrics": constant_metrics,
        "net_effect_removed": net_effect_removed,
        "net_effect_replacements": net_effect_replacements,
        "quality_improved": quality_improved,
        "total_improved": total_improved,
        "paths": {
            "skip": skip_path,
            "constant": constant_path,
            "blocked": blocked_path,
            "replacement": replacement_path,
            "report": report_path,
        },
    }


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    csv_path = project_root / "data" / "historical" / "spy_1m.csv"
    output_dir = project_root / "backtesting" / "output"
    config = ExperimentConfig()

    result = run_regime_filter_ab(csv_path=csv_path, output_dir=output_dir, config=config)

    print("1. Baseline results")
    print(result["baseline_metrics"])
    print("2. Skip-only filtered results")
    print(result["skip_metrics"])
    print("3. Constant-sample filtered results")
    print(result["constant_metrics"])
    print(f"4. Net effect of removing blocked trades: ${result['net_effect_removed']:.2f}")
    print(f"5. Net effect of replacement trades: ${result['net_effect_replacements']:.2f}")
    print(f"6. Regime filter improved accepted-trade quality: {result['quality_improved']}")
    print(f"7. Regime filter improved total strategy performance: {result['total_improved']}")
    print("Outputs:")
    for key, path in result["paths"].items():
        print(f"- {key}: {path}")


if __name__ == "__main__":
    main()
