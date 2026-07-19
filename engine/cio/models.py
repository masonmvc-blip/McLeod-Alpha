from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


@dataclass(frozen=True)
class PortfolioHolding:
    symbol: str
    quantity: float
    market_value: float
    sector: str = "Unknown"
    thesis_health_score: float = 50.0
    valuation_score: float = 50.0
    conviction_score: float = 50.0
    risk_score: float = 50.0
    liquidity_score: float = 50.0
    notes: str = ""


@dataclass(frozen=True)
class WatchlistItem:
    symbol: str
    thesis: str
    valuation_score: float
    conviction_score: float
    risk_score: float
    sector: str = "Unknown"
    notes: str = ""


@dataclass(frozen=True)
class MaterialNewsItem:
    symbol: str
    headline: str
    summary: str
    impact: str
    materiality_score: float
    source: str
    published_at: str = ""


@dataclass(frozen=True)
class PortfolioConstraint:
    min_cash_weight: float = 0.10
    target_cash_weight: float = 0.15
    max_single_name_weight: float = 0.25
    max_sector_weight: float = 0.35
    max_portfolio_risk: float = 60.0
    min_diversification_score: float = 55.0
    min_liquidity_score: float = 40.0


@dataclass(frozen=True)
class ActionRecommendation:
    priority: int
    title: str
    reason: str
    expected_benefit: str
    confidence: float
    supporting_evidence: tuple[str, ...] = field(default_factory=tuple)
    symbol: str = ""
    action_type: str = ""


@dataclass(frozen=True)
class WatchlistChange:
    symbol: str
    change: str
    reason: str
    confidence: float
    supporting_evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ThesisChange:
    symbol: str
    previous_score: float
    current_score: float
    adjusted_score: float
    delta: float
    reason: str
    confidence: float
    supporting_evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PortfolioHealthResult:
    overall_score: float
    component_scores: tuple[tuple[str, float], ...]
    overall_risk: str
    cash_weight: float
    total_portfolio_value: float
    concentration_weight: float
    diversification_weight: float


@dataclass(frozen=True)
class ThesisHealthResult:
    overall_score: float
    symbol_scores: tuple[tuple[str, float], ...]
    changes: tuple[ThesisChange, ...]
    material_news: tuple[MaterialNewsItem, ...]


@dataclass(frozen=True)
class DecisionEngineInputs:
    date: str
    holdings: tuple[PortfolioHolding, ...] = field(default_factory=tuple)
    cash_balance: float = 0.0
    watchlist: tuple[WatchlistItem, ...] = field(default_factory=tuple)
    thesis_health_scores: Mapping[str, float] = field(default_factory=dict)
    valuation_scores: Mapping[str, float] = field(default_factory=dict)
    conviction_scores: Mapping[str, float] = field(default_factory=dict)
    risk_scores: Mapping[str, float] = field(default_factory=dict)
    recent_material_news: tuple[MaterialNewsItem, ...] = field(default_factory=tuple)
    constraints: PortfolioConstraint = field(default_factory=PortfolioConstraint)


@dataclass(frozen=True)
class DailyCIOBrief:
    date: str
    portfolio_health_score: float
    portfolio_health_components: tuple[tuple[str, float], ...]
    overall_risk: str
    cash_recommendation: str
    top_actions: tuple[ActionRecommendation, ...]
    recommended_buys: tuple[ActionRecommendation, ...]
    recommended_trims: tuple[ActionRecommendation, ...]
    holds: tuple[ActionRecommendation, ...]
    watchlist_changes: tuple[WatchlistChange, ...]
    thesis_changes: tuple[ThesisChange, ...]
    material_news: tuple[MaterialNewsItem, ...]
    confidence_score: float
    executive_summary: str