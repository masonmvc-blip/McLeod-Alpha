"""
McLeod Alpha trading strategy signal calculations.

Pure, reusable functions for technical analysis and scoring.
Used by both live trading and backtesting.
"""

from .signals import (
    add_indicators,
    build_feature_snapshot,
    classify_market_regime,
    is_regime_aligned,
    market_regime,
    volume_momentum,
    candle_quality,
    score_call,
    score_put,
)

__all__ = [
    "add_indicators",
    "build_feature_snapshot",
    "classify_market_regime",
    "is_regime_aligned",
    "market_regime",
    "volume_momentum",
    "candle_quality",
    "score_call",
    "score_put",
]
