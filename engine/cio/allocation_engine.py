from __future__ import annotations

from dataclasses import dataclass, field

from .decision_record import DecisionRecord
from .models import DailyCIOBrief, PortfolioHolding, WatchlistItem
from .portfolio_plan import AllocationChange, PortfolioOSInputs, PortfolioTargetPosition
from .outcome_reconciliation import RealizedOutcome
from .replacement_engine import ReplacementProfile


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class AllocationSignal:
    symbol: str
    sector: str
    score: float
    expected_alpha: float
    expected_risk: float
    current_weight: float
    target_weight: float
    action: str
    reason: str
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AllocationResult:
    target_portfolio: tuple[PortfolioTargetPosition, ...]
    allocation_changes: tuple[AllocationChange, ...]
    cash_target: float
    expected_portfolio_alpha: float
    expected_portfolio_risk: float
    confidence: float
    profile_map: dict[str, ReplacementProfile]
    signals: tuple[AllocationSignal, ...]


class AllocationEngine:
    def build_allocation(
        self,
        inputs: PortfolioOSInputs,
    ) -> AllocationResult:
        total_current_value = sum(max(0.0, float(holding.market_value)) for holding in inputs.current_portfolio)
        portfolio_value = total_current_value + max(0.0, float(inputs.cash_balance))
        current_cash_weight = (float(inputs.cash_balance) / portfolio_value) if portfolio_value > 0 else 0.0
        cash_target = self._cash_target(inputs, current_cash_weight=current_cash_weight)
        equity_budget = max(0.0, 1.0 - cash_target)

        history_metrics = self._build_history_metrics(inputs.decision_records, inputs.realized_outcomes)
        profile_map = self._build_profile_map(inputs, history_metrics)
        signals = self._build_signals(inputs, profile_map, history_metrics)
        target_weights = self._normalize_target_weights(signals, equity_budget=equality_budget if False else equity_budget, inputs=inputs)

        target_portfolio: list[PortfolioTargetPosition] = []
        allocation_changes: list[AllocationChange] = []
        target_by_symbol = {signal.symbol: signal for signal in signals}
        current_weights = self._current_weights(inputs.current_portfolio, portfolio_value)

        for symbol in sorted(set(current_weights) | set(target_weights) | set(target_by_symbol)):
            current_weight = current_weights.get(symbol, 0.0)
            target_weight = target_weights.get(symbol, 0.0)
            current_value = current_weight * portfolio_value
            target_value = target_weight * portfolio_value
            signal = target_by_symbol.get(symbol)
            if target_weight <= 0 and current_weight <= 0:
                continue
            action = self._action_for_weights(current_weight, target_weight)
            reason = signal.reason if signal else "Maintain capital discipline and wait for a better setup."
            expected_alpha = signal.expected_alpha if signal else 0.0
            expected_risk = signal.expected_risk if signal else 50.0
            evidence = signal.evidence if signal else ()

            target_portfolio.append(
                PortfolioTargetPosition(
                    symbol=symbol,
                    current_weight=round(current_weight, 4),
                    target_weight=round(target_weight, 4),
                    current_value=round(current_value, 2),
                    target_value=round(target_value, 2),
                    action=action,
                    score=round(signal.score if signal else 0.0, 2),
                    expected_alpha=round(expected_alpha, 2),
                    expected_risk=round(expected_risk, 2),
                    reason=reason,
                    supporting_evidence=evidence,
                )
            )
            allocation_changes.append(
                AllocationChange(
                    symbol=symbol,
                    current_weight=round(current_weight, 4),
                    target_weight=round(target_weight, 4),
                    delta_weight=round(target_weight - current_weight, 4),
                    current_value=round(current_value, 2),
                    target_value=round(target_value, 2),
                    action=action,
                    reason=reason,
                )
            )

        expected_portfolio_alpha = self._weighted_metric(target_portfolio, attr="expected_alpha")
        expected_portfolio_risk = self._weighted_metric(target_portfolio, attr="expected_risk")
        confidence = self._confidence_score(inputs=inputs, target_portfolio=tuple(target_portfolio), history_metrics=history_metrics)

        return AllocationResult(
            target_portfolio=tuple(sorted(target_portfolio, key=lambda item: (-item.target_weight, item.symbol))),
            allocation_changes=tuple(sorted(allocation_changes, key=lambda item: (-abs(item.delta_weight), item.symbol))),
            cash_target=round(cash_target, 4),
            expected_portfolio_alpha=round(expected_portfolio_alpha, 2),
            expected_portfolio_risk=round(expected_portfolio_risk, 2),
            confidence=round(confidence, 1),
            profile_map=profile_map,
            signals=signals,
        )

    def _cash_target(self, inputs: PortfolioOSInputs, *, current_cash_weight: float) -> float:
        constraints = inputs.risk_limits
        health = float(inputs.decision_brief.portfolio_health_score)
        risk_bias = max(0.0, (70.0 - health) / 200.0)
        margin_bias = 0.0
        if inputs.margin_settings:
            buying_power = float(inputs.margin_settings.get("buying_power", 0.0) or 0.0)
            maintenance = float(inputs.margin_settings.get("maintenance_requirement", 0.0) or 0.0)
            if buying_power > 0:
                margin_bias = min(0.05, maintenance / buying_power * 0.02)

        desired = max(
            float(constraints.min_cash_weight),
            min(float(inputs.max_cash_allocation), float(constraints.target_cash_weight) + risk_bias + margin_bias),
        )
        if current_cash_weight < constraints.min_cash_weight:
            desired = max(desired, float(constraints.min_cash_weight))
        return round(min(float(inputs.max_cash_allocation), desired), 2)

    @staticmethod
    def _build_history_metrics(
        decision_records: tuple[DecisionRecord, ...],
        realized_outcomes: tuple[RealizedOutcome, ...],
    ) -> dict[str, dict[str, float]]:
        outcome_map = {outcome.decision_id: outcome for outcome in realized_outcomes}
        metrics: dict[str, dict[str, list[float]]] = {}
        for record in decision_records:
            outcome = outcome_map.get(record.decision_id)
            if outcome is None:
                continue
            symbol = _normalize_symbol(record.symbol)
            bucket = metrics.setdefault(symbol, {"bench": [], "conf": [], "dir": []})
            bucket["bench"].append(float(outcome.benchmark_adjusted_return))
            bucket["conf"].append(float(record.confidence))
            bucket["dir"].append(1.0 if outcome.directionally_correct else 0.0)
        condensed: dict[str, dict[str, float]] = {}
        for symbol, payload in metrics.items():
            condensed[symbol] = {
                "avg_benchmark_adjusted_return": sum(payload["bench"]) / len(payload["bench"]),
                "avg_confidence": sum(payload["conf"]) / len(payload["conf"]),
                "directional_accuracy": sum(payload["dir"]) / len(payload["dir"]),
            }
        return condensed

    def _build_profile_map(
        self,
        inputs: PortfolioOSInputs,
        history_metrics: dict[str, dict[str, float]],
    ) -> dict[str, ReplacementProfile]:
        profile_map: dict[str, ReplacementProfile] = {}
        brief = inputs.decision_brief
        hold_symbols = {_normalize_symbol(holding.symbol) for holding in inputs.current_portfolio}
        watch_symbols = {_normalize_symbol(item.symbol) for item in inputs.watchlist}

        for holding in inputs.current_portfolio:
            symbol = _normalize_symbol(holding.symbol)
            profile_map[symbol] = self._profile_for_symbol(
                symbol=symbol,
                sector=holding.sector,
                thesis_score=float(holding.thesis_health_score),
                valuation_score=float(holding.valuation_score),
                conviction_score=float(holding.conviction_score),
                liquidity_score=float(holding.liquidity_score),
                risk_score=float(holding.risk_score),
                decision_brief=brief,
                action_role="hold",
                history_metrics=history_metrics.get(symbol, {}),
                evidence=(holding.notes,) if holding.notes else (),
            )

        for item in inputs.watchlist:
            symbol = _normalize_symbol(item.symbol)
            if symbol in profile_map:
                continue
            profile_map[symbol] = self._profile_for_symbol(
                symbol=symbol,
                sector=item.sector,
                thesis_score=float(item.thesis_score) if hasattr(item, "thesis_score") else float(item.valuation_score),
                valuation_score=float(item.valuation_score),
                conviction_score=float(item.conviction_score),
                liquidity_score=float(item.valuation_score),
                risk_score=float(item.risk_score),
                decision_brief=brief,
                action_role="buy",
                history_metrics=history_metrics.get(symbol, {}),
                evidence=(item.thesis,) if item.thesis else (),
            )

        return profile_map

    def _profile_for_symbol(
        self,
        *,
        symbol: str,
        sector: str,
        thesis_score: float,
        valuation_score: float,
        conviction_score: float,
        liquidity_score: float,
        risk_score: float,
        decision_brief: DailyCIOBrief,
        action_role: str,
        history_metrics: dict[str, float],
        evidence: tuple[str, ...],
    ) -> ReplacementProfile:
        brief = decision_brief
        role_boost = 0.0
        if symbol in {_normalize_symbol(action.symbol) for action in brief.recommended_buys}:
            role_boost += 8.0
        if symbol in {_normalize_symbol(action.symbol) for action in brief.recommended_trims}:
            role_boost -= 8.0
        if symbol in {_normalize_symbol(action.symbol) for action in brief.holds}:
            role_boost += 2.0
        if symbol in {_normalize_symbol(action.symbol) for action in brief.watchlist_changes}:
            role_boost += 1.0

        history_edge = float(history_metrics.get("avg_benchmark_adjusted_return", 0.0)) * 100.0
        history_accuracy = float(history_metrics.get("directional_accuracy", 0.0))
        history_confidence = float(history_metrics.get("avg_confidence", brief.confidence_score))

        if action_role == "buy":
            raw_score = (
                (thesis_score * 0.28)
                + (valuation_score * 0.24)
                + (conviction_score * 0.20)
                + (liquidity_score * 0.10)
                + ((100.0 - risk_score) * 0.12)
                + role_boost
                + min(10.0, history_edge)
                + (history_accuracy * 4.0)
            )
            expected_alpha = (
                (valuation_score * 0.28)
                + (conviction_score * 0.22)
                + (thesis_score * 0.18)
                + (liquidity_score * 0.10)
                - (risk_score * 0.12)
                + min(8.0, history_edge)
            ) / 10.0
        else:
            raw_score = (
                (thesis_score * 0.24)
                + (valuation_score * 0.20)
                + (conviction_score * 0.18)
                + (liquidity_score * 0.12)
                + ((100.0 - risk_score) * 0.16)
                + role_boost
                + min(8.0, history_edge)
                + (history_accuracy * 3.0)
            )
            expected_alpha = (
                (valuation_score * 0.22)
                + (conviction_score * 0.18)
                + (thesis_score * 0.15)
                + (liquidity_score * 0.10)
                - (risk_score * 0.14)
                + min(6.0, history_edge)
            ) / 12.0

        score = _clamp(raw_score, 0.0, 100.0)
        if symbol in {_normalize_symbol(action.symbol) for action in brief.recommended_trims}:
            expected_alpha -= 0.5
        if symbol in {_normalize_symbol(action.symbol) for action in brief.recommended_buys}:
            expected_alpha += 0.75

        reason = (
            f"{symbol} score {score:.1f} combines thesis {thesis_score:.1f}, valuation {valuation_score:.1f}, conviction {conviction_score:.1f}, liquidity {liquidity_score:.1f}, and risk {risk_score:.1f}."
        )
        if history_metrics:
            reason += f" Journal edge {history_edge:+.2f} and directional accuracy {history_accuracy:.0%}."

        return ReplacementProfile(
            symbol=symbol,
            score=round(score, 2),
            expected_alpha=round(expected_alpha, 2),
            confidence=round(min(100.0, max(35.0, history_confidence)), 1),
            evidence=evidence,
            sector=sector or "Unknown",
            risk_score=risk_score,
        )

    def _build_signals(
        self,
        inputs: PortfolioOSInputs,
        profile_map: dict[str, ReplacementProfile],
        history_metrics: dict[str, dict[str, float]],
    ) -> tuple[AllocationSignal, ...]:
        brief = inputs.decision_brief
        current_symbols = {_normalize_symbol(holding.symbol) for holding in inputs.current_portfolio}
        signals: list[AllocationSignal] = []

        for symbol in sorted(profile_map):
            profile = profile_map[symbol]
            current_holding = next((holding for holding in inputs.current_portfolio if _normalize_symbol(holding.symbol) == symbol), None)
            current_weight = 0.0
            if current_holding is not None:
                current_weight = self._current_weight_for_holding(current_holding, inputs.current_portfolio, inputs.cash_balance)

            if current_holding is not None:
                action = "Hold"
                if symbol in {_normalize_symbol(action.symbol) for action in brief.recommended_trims}:
                    action = "Reduce"
                elif symbol in {_normalize_symbol(action.symbol) for action in brief.recommended_buys}:
                    action = "Increase"
                else:
                    action = "Hold"
                target_bias = 0.5 if action != "Reduce" else 0.35
                target_weight = current_weight * target_bias
            else:
                if symbol not in {_normalize_symbol(item.symbol) for item in inputs.watchlist}:
                    continue
                action = "Deploy"
                target_weight = 0.0
                if profile.score >= 60.0:
                    target_weight = max(inputs.min_position_size, (profile.score - 58.0) / 200.0)

            if current_holding is not None and profile.score < 45.0:
                target_weight = min(target_weight, max(0.0, current_weight * 0.25))

            score_adjustment = profile.score + profile.expected_alpha * 5.0
            if symbol in {_normalize_symbol(item.symbol) for item in inputs.watchlist} and profile.score >= 65.0:
                score_adjustment += 3.0

            signals.append(
                AllocationSignal(
                    symbol=symbol,
                    sector=profile.sector,
                    score=round(score_adjustment, 2),
                    expected_alpha=profile.expected_alpha,
                    expected_risk=profile.risk_score,
                    current_weight=round(current_weight, 4),
                    target_weight=round(target_weight, 4),
                    action=action,
                    reason=profile_map[symbol].evidence[0] if profile_map[symbol].evidence else profile_map[symbol].symbol,
                    evidence=profile.evidence,
                )
            )

        return tuple(sorted(signals, key=lambda item: (-item.score, item.symbol)))

    def _normalize_target_weights(
        self,
        signals: tuple[AllocationSignal, ...],
        *,
        equity_budget: float,
        inputs: PortfolioOSInputs,
    ) -> dict[str, float]:
        target_weights: dict[str, float] = {}
        raw_scores: dict[str, float] = {}

        for signal in signals:
            if signal.current_weight > 0:
                base = max(0.0, signal.score - 35.0)
                raw = (signal.current_weight * 0.45) + (base / 200.0)
            else:
                if signal.action != "Deploy" or signal.score < 60.0:
                    continue
                raw = max(0.0, (signal.score - 58.0) / 100.0)
            if raw > 0 and raw < inputs.min_position_size:
                raw = inputs.min_position_size
            raw_scores[signal.symbol] = raw

        total_raw = sum(raw_scores.values())
        if total_raw <= 0:
            return {}

        for symbol, raw in raw_scores.items():
            target = raw / total_raw * equity_budget
            target = min(target, float(inputs.max_position_size))
            if target < inputs.min_position_size and symbol in {signal.symbol for signal in signals if signal.current_weight > 0}:
                target = inputs.min_position_size
            target_weights[symbol] = target

        total_target = sum(target_weights.values())
        if total_target > equity_budget and total_target > 0:
            scale = equity_budget / total_target
            target_weights = {symbol: weight * scale for symbol, weight in target_weights.items()}

        return {symbol: round(weight, 4) for symbol, weight in target_weights.items()}

    @staticmethod
    def _action_for_weights(current_weight: float, target_weight: float) -> str:
        if target_weight <= 0 and current_weight > 0:
            return "Exit"
        if target_weight > current_weight + 0.01:
            return "Increase"
        if target_weight < current_weight - 0.01:
            return "Reduce"
        return "Hold"

    @staticmethod
    def _current_weights(
        current_portfolio: tuple[PortfolioHolding, ...],
        portfolio_value: float,
    ) -> dict[str, float]:
        if portfolio_value <= 0:
            return {}
        return {
            _normalize_symbol(holding.symbol): max(0.0, float(holding.market_value)) / portfolio_value
            for holding in current_portfolio
        }

    @staticmethod
    def _current_weight_for_holding(
        holding: PortfolioHolding,
        current_portfolio: tuple[PortfolioHolding, ...],
        cash_balance: float,
    ) -> float:
        total_value = sum(max(0.0, float(item.market_value)) for item in current_portfolio) + max(0.0, float(cash_balance))
        if total_value <= 0:
            return 0.0
        return max(0.0, float(holding.market_value)) / total_value

    @staticmethod
    def _weighted_metric(target_portfolio: tuple[PortfolioTargetPosition, ...], *, attr: str) -> float:
        total = sum(max(0.0, float(position.target_weight)) for position in target_portfolio)
        if total <= 0:
            return 0.0
        weighted = sum(max(0.0, float(position.target_weight)) * float(getattr(position, attr)) for position in target_portfolio)
        return weighted / total

    @staticmethod
    def _confidence_score(
        *,
        inputs: PortfolioOSInputs,
        target_portfolio: tuple[PortfolioTargetPosition, ...],
        history_metrics: dict[str, dict[str, float]],
    ) -> float:
        brief_confidence = float(inputs.decision_brief.confidence_score)
        history_sample_size = len(inputs.decision_records)
        realized_count = len(inputs.realized_outcomes)
        stable_names = sum(1 for position in target_portfolio if position.action == "Hold")
        coverage = min(1.0, history_sample_size / 10.0)
        realized_bias = min(1.0, realized_count / 5.0)
        stability = stable_names / max(1, len(target_portfolio))
        history_bonus = 0.0
        if history_metrics:
            history_bonus = sum(metric.get("directional_accuracy", 0.0) for metric in history_metrics.values()) / len(history_metrics)
        return _clamp(
            (brief_confidence * 0.38)
            + (coverage * 18.0)
            + (realized_bias * 10.0)
            + (stability * 12.0)
            + (history_bonus * 20.0),
            0.0,
            100.0,
        )