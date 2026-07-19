"""
Backtesting package for Phase 2 historical data replay, signal generation, and trade simulation.

Provides data loading, replay, signal generation, and trade simulation infrastructure
without modifying live or paper trading behavior.
"""

from backtesting.data_loader import load_csv_data, validate_dataframe
from backtesting.replay_engine import ReplayEngine
from backtesting.signal_replay import SignalReplayEngine
from backtesting.option_pricer import EstimatedOptionPricer
from backtesting.trade_simulator import TradeSimulator, SimulatedTrade
from backtesting.strategy_optimizer import StrategyOptimizer, StrategyParameters, StrategyResult
from backtesting.regime_filter_ab import ExperimentConfig, run_regime_filter_ab
from backtesting.trade_replay_inspector import PaperTradeSpec, inspect_trade

__all__ = [
    "load_csv_data",
    "validate_dataframe",
    "ReplayEngine",
    "SignalReplayEngine",
    "EstimatedOptionPricer",
    "TradeSimulator",
    "SimulatedTrade",
    "StrategyOptimizer",
    "StrategyParameters",
    "StrategyResult",
    "ExperimentConfig",
    "run_regime_filter_ab",
    "PaperTradeSpec",
    "inspect_trade",
]
