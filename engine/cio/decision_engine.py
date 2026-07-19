from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from .daily_brief import write_daily_cio_brief
from .models import (
    ActionRecommendation,
    DailyCIOBrief,
    DecisionEngineInputs,
    MaterialNewsItem,
    PortfolioHolding,
    ThesisChange,
    WatchlistChange,
)
from .portfolio_health import compute_portfolio_health
from .thesis_health import compute_thesis_health


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _score_lookup(mapping, symbol: str, default: float = 50.0) -> float:
    return _clamp(float(mapping.get(symbol, default)))


def _weighted_average(scores: list[float], default: float = 50.0) -> float:
    if not scores:
        return default
    return sum(scores) / len(scores)


class DecisionEngine:
    def generate(
        self,
        inputs: DecisionEngineInputs,
        *,
        report_path: Path | None = None,
    ) -> DailyCIOBrief:
        portfolio_health = compute_portfolio_health(inputs)
        thesis_health = compute_thesis_health(inputs)
        thesis_scores = dict(thesis_health.symbol_scores)

        holdings_by_symbol = { _normalize_symbol(holding.symbol): holding for holding in inputs.holdings }
        watchlist_by_symbol = { _normalize_symbol(item.symbol): item for item in inputs.watchlist }
        all_symbols = sorted(
            set(holdings_by_symbol)
            | set(watchlist_by_symbol)
            | set(thesis_scores)
            | set(inputs.valuation_scores)
            | set(inputs.conviction_scores)
            | set(inputs.risk_scores)
        )

        buy_candidates: list[ActionRecommendation] = []
        trim_candidates: list[ActionRecommendation] = []
        hold_candidates: list[ActionRecommendation] = []
        watchlist_changes: list[WatchlistChange] = []
        thesis_changes = list(thesis_health.changes)

        max_single_name_weight = inputs.constraints.max_single_name_weight
        total_portfolio_value = portfolio_health.total_portfolio_value or 0.0
        sector_weights = defaultdict(float)
        for holding in inputs.holdings:
            sector_weights[holding.sector or "Unknown"] += (float(holding.market_value) / total_portfolio_value) if total_portfolio_value > 0 else 0.0

        for symbol in all_symbols:
            holding = holdings_by_symbol.get(symbol)
            watchlist_item = watchlist_by_symbol.get(symbol)
            thesis_score = thesis_scores.get(symbol, _score_lookup(inputs.thesis_health_scores, symbol))
            valuation_score = _score_lookup(inputs.valuation_scores, symbol)
            conviction_score = _score_lookup(inputs.conviction_scores, symbol)
            risk_score = _score_lookup(inputs.risk_scores, symbol)
            news_support = [news for news in inputs.recent_material_news if _normalize_symbol(news.symbol) == symbol]
            positive_news = sum(1 for item in news_support if item.impact.strip().lower() == "positive")
            negative_news = sum(1 for item in news_support if item.impact.strip().lower() == "negative")

            evidence = tuple(
                item.headline for item in sorted(news_support, key=lambda item: (-float(item.materiality_score), item.headline, item.published_at))
            )

            sector_weight = sector_weights.get((holding.sector if holding else watchlist_item.sector if watchlist_item else "Unknown") or "Unknown", 0.0)
            concentration_pressure = max(0.0, sector_weight * 100.0 - inputs.constraints.max_sector_weight * 100.0)

            if holding is not None:
                trim_score = (
                    (risk_score * 0.38)
                    + ((100.0 - thesis_score) * 0.22)
                    + ((100.0 - valuation_score) * 0.18)
                    + (concentration_pressure * 0.12)
                    + (max(0, negative_news - positive_news) * 3.0)
                )
                if trim_score >= 45.0 or risk_score >= 65.0 or sector_weight > max_single_name_weight:
                    trim_candidates.append(
                        ActionRecommendation(
                            priority=0,
                            title=f"Trim {symbol}",
                            reason=self._trim_reason(symbol, holding, thesis_score, valuation_score, risk_score, sector_weight),
                            expected_benefit=f"Reduce exposure and improve risk-adjusted health by {trim_score:.1f}/100.",
                            confidence=round(_clamp(55.0 + trim_score * 0.35), 1),
                            supporting_evidence=evidence or (f"Holding risk {risk_score:.1f}",),
                            symbol=symbol,
                            action_type="trim",
                        )
                    )
                else:
                    hold_candidates.append(
                        ActionRecommendation(
                            priority=0,
                            title=f"Hold {symbol}",
                            reason=f"Thesis {thesis_score:.1f}, valuation {valuation_score:.1f}, and risk {risk_score:.1f} remain balanced.",
                            expected_benefit="Preserve the existing position while waiting for a stronger catalyst.",
                            confidence=round(_clamp(50.0 + (thesis_score - risk_score) * 0.25), 1),
                            supporting_evidence=evidence or (f"Score profile stable for {symbol}",),
                            symbol=symbol,
                            action_type="hold",
                        )
                    )
            else:
                buy_score = (
                    (valuation_score * 0.34)
                    + (conviction_score * 0.32)
                    + (thesis_score * 0.18)
                    + ((100.0 - risk_score) * 0.12)
                    + (positive_news * 4.0)
                    - (negative_news * 5.0)
                )
                if buy_score >= 60.0:
                    buy_candidates.append(
                        ActionRecommendation(
                            priority=0,
                            title=f"Buy {symbol}",
                            reason=self._buy_reason(symbol, watchlist_item, thesis_score, valuation_score, conviction_score, risk_score, news_support),
                            expected_benefit=f"Capture a higher-conviction entry with an estimated edge score of {buy_score:.1f}/100.",
                            confidence=round(_clamp(52.0 + (buy_score - 60.0) * 0.6), 1),
                            supporting_evidence=evidence or ((watchlist_item.thesis if watchlist_item else f"Signal strength favors {symbol}"),),
                            symbol=symbol,
                            action_type="buy",
                        )
                    )
                else:
                    watchlist_change = WatchlistChange(
                        symbol=symbol,
                        change="watch" if buy_score >= 45.0 else "deprioritize",
                        reason=self._watchlist_reason(symbol, watchlist_item, thesis_score, valuation_score, conviction_score, risk_score),
                        confidence=round(_clamp(45.0 + abs(buy_score - 50.0) * 0.35), 1),
                        supporting_evidence=evidence or ((watchlist_item.thesis if watchlist_item else f"No strong catalyst for {symbol}"),),
                    )
                    watchlist_changes.append(watchlist_change)

        top_actions = self._select_top_actions(buy_candidates, trim_candidates, hold_candidates)
        recommended_buys = tuple(sorted(buy_candidates, key=self._action_sort_key))
        recommended_trims = tuple(sorted(trim_candidates, key=self._action_sort_key))
        holds = tuple(sorted(hold_candidates, key=self._action_sort_key))
        watchlist_changes = tuple(sorted(self._dedupe_watchlist_changes(watchlist_changes), key=lambda item: (-item.confidence, item.symbol, item.change)))
        thesis_changes = tuple(sorted(self._dedupe_thesis_changes(thesis_changes), key=lambda item: (-abs(item.delta), item.symbol)))

        material_news = tuple(
            sorted(
                inputs.recent_material_news,
                key=lambda item: (-float(item.materiality_score), item.symbol.upper(), item.headline, item.published_at),
            )
        )

        cash_weight = portfolio_health.cash_weight
        cash_buffer = max(0.0, cash_weight - inputs.constraints.min_cash_weight)
        best_buy = recommended_buys[0] if recommended_buys else None
        if cash_weight < inputs.constraints.min_cash_weight:
            cash_recommendation = (
                f"Raise cash toward at least {inputs.constraints.min_cash_weight:.1%}; "
                "trim low-quality or concentrated exposure before adding new risk."
            )
        elif best_buy is not None and cash_buffer > 0:
            cash_recommendation = (
                f"Deploy up to {min(cash_buffer, 0.10):.1%} of portfolio value into {best_buy.symbol} while preserving the cash floor."
            )
        else:
            cash_recommendation = (
                f"Maintain cash near {cash_weight:.1%} and redeploy only after a stronger buy signal appears."
            )

        confidence_score = self._confidence_score(portfolio_health_score=portfolio_health.overall_score, top_actions=top_actions, thesis_changes=thesis_changes, material_news=material_news)
        executive_summary = self._build_executive_summary(portfolio_health, top_actions, cash_recommendation, thesis_changes, material_news)

        brief = DailyCIOBrief(
            date=inputs.date,
            portfolio_health_score=portfolio_health.overall_score,
            portfolio_health_components=portfolio_health.component_scores,
            overall_risk=portfolio_health.overall_risk,
            cash_recommendation=cash_recommendation,
            top_actions=top_actions,
            recommended_buys=recommended_buys,
            recommended_trims=recommended_trims,
            holds=holds,
            watchlist_changes=watchlist_changes,
            thesis_changes=thesis_changes,
            material_news=material_news,
            confidence_score=confidence_score,
            executive_summary=executive_summary,
        )

        write_daily_cio_brief(brief, report_path=report_path)
        return brief

    @staticmethod
    def _action_sort_key(action: ActionRecommendation) -> tuple[int, float, str]:
        priority_rank = {"trim": 0, "buy": 1, "hold": 2}.get(action.action_type, 3)
        return (priority_rank, -float(action.confidence), action.symbol, action.title)

    @staticmethod
    def _dedupe_actions(actions: list[ActionRecommendation]) -> list[ActionRecommendation]:
        seen: set[tuple[str, str]] = set()
        deduped: list[ActionRecommendation] = []
        for action in actions:
            key = (action.symbol, action.action_type)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(action)
        return deduped

    def _select_top_actions(
        self,
        buy_candidates: list[ActionRecommendation],
        trim_candidates: list[ActionRecommendation],
        hold_candidates: list[ActionRecommendation],
    ) -> tuple[ActionRecommendation, ...]:
        ranked: list[ActionRecommendation] = []
        ranked.extend(sorted(trim_candidates, key=self._action_sort_key))
        ranked.extend(sorted(buy_candidates, key=self._action_sort_key))
        ranked.extend(sorted(hold_candidates, key=self._action_sort_key))

        if not ranked:
            ranked.append(
                ActionRecommendation(
                    priority=0,
                    title="Maintain current allocations",
                    reason="No action beat the selection threshold.",
                    expected_benefit="Preserve capital until a higher-conviction setup appears.",
                    confidence=50.0,
                    supporting_evidence=("No strong buy or trim signal detected",),
                    symbol="",
                    action_type="hold",
                )
            )

        ranked = self._dedupe_actions(ranked)
        selected = ranked[:3]
        selected = [replace(action, priority=index + 1) for index, action in enumerate(selected)]
        while len(selected) < 3:
            filler_index = len(selected) + 1
            selected.append(
                ActionRecommendation(
                    priority=filler_index,
                    title="Monitor thesis drift",
                    reason="No additional ranked action is available.",
                    expected_benefit="Keep the CIO review focused on the next catalyst.",
                    confidence=40.0,
                    supporting_evidence=("No additional ranked action available",),
                    symbol="",
                    action_type="hold",
                )
            )
        return tuple(selected)

    @staticmethod
    def _dedupe_watchlist_changes(changes: list[WatchlistChange]) -> list[WatchlistChange]:
        seen: set[str] = set()
        deduped: list[WatchlistChange] = []
        for change in changes:
            if change.symbol in seen:
                continue
            seen.add(change.symbol)
            deduped.append(change)
        return deduped

    @staticmethod
    def _dedupe_thesis_changes(changes: list[ThesisChange]) -> list[ThesisChange]:
        seen: set[str] = set()
        deduped: list[ThesisChange] = []
        for change in changes:
            if change.symbol in seen:
                continue
            seen.add(change.symbol)
            deduped.append(change)
        return deduped

    @staticmethod
    def _trim_reason(symbol: str, holding: PortfolioHolding, thesis_score: float, valuation_score: float, risk_score: float, sector_weight: float) -> str:
        return (
            f"{symbol} is carrying risk {risk_score:.1f} with thesis {thesis_score:.1f}, valuation {valuation_score:.1f}, "
            f"and {sector_weight:.1%} sector weight."
        )

    @staticmethod
    def _buy_reason(
        symbol: str,
        watchlist_item,
        thesis_score: float,
        valuation_score: float,
        conviction_score: float,
        risk_score: float,
        news_support: list[MaterialNewsItem],
    ) -> str:
        news_text = f" Recent material news supports the setup." if any(item.impact.strip().lower() == "positive" for item in news_support) else ""
        thesis_text = watchlist_item.thesis if watchlist_item is not None else "Signal quality is strong enough to justify a buy candidate."
        return (
            f"{symbol} combines thesis {thesis_score:.1f}, valuation {valuation_score:.1f}, conviction {conviction_score:.1f}, "
            f"and risk {risk_score:.1f}. {thesis_text}{news_text}"
        )

    @staticmethod
    def _watchlist_reason(symbol: str, watchlist_item, thesis_score: float, valuation_score: float, conviction_score: float, risk_score: float) -> str:
        thesis_text = watchlist_item.thesis if watchlist_item is not None else "Watchlist name remains under review."
        return (
            f"{symbol} sits at thesis {thesis_score:.1f}, valuation {valuation_score:.1f}, conviction {conviction_score:.1f}, "
            f"and risk {risk_score:.1f}; {thesis_text}"
        )

    @staticmethod
    def _confidence_score(
        *,
        portfolio_health_score: float,
        top_actions: tuple[ActionRecommendation, ...],
        thesis_changes: tuple[ThesisChange, ...],
        material_news: tuple[MaterialNewsItem, ...],
    ) -> float:
        action_confidence = _weighted_average([float(action.confidence) for action in top_actions], default=50.0)
        thesis_confidence = _weighted_average([float(change.confidence) for change in thesis_changes], default=60.0)
        news_signal = min(100.0, len(material_news) * 5.0)
        return round(_clamp((portfolio_health_score * 0.45) + (action_confidence * 0.35) + (thesis_confidence * 0.15) + news_signal * 0.05), 2)

    @staticmethod
    def _build_executive_summary(
        portfolio_health,
        top_actions: tuple[ActionRecommendation, ...],
        cash_recommendation: str,
        thesis_changes: tuple[ThesisChange, ...],
        material_news: tuple[MaterialNewsItem, ...],
    ) -> str:
        action_titles = "; ".join(action.title for action in top_actions)
        thesis_count = len(thesis_changes)
        news_count = len(material_news)
        return (
            f"Portfolio health is {portfolio_health.overall_score:.1f}/100 with {portfolio_health.overall_risk} risk. "
            f"Top actions: {action_titles}. Thesis changes tracked: {thesis_count}. Material news items reviewed: {news_count}. "
            f"Cash view: {cash_recommendation}"
        )