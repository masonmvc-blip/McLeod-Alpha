from __future__ import annotations

from dataclasses import dataclass, field

from .decision_record import DecisionRecord
from .models import DailyCIOBrief, PortfolioHolding, WatchlistItem
from .portfolio_plan import ReplacementCandidate
from .outcome_reconciliation import RealizedOutcome


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


@dataclass(frozen=True)
class ReplacementProfile:
    symbol: str
    score: float
    expected_alpha: float
    confidence: float
    evidence: tuple[str, ...] = field(default_factory=tuple)
    sector: str = "Unknown"
    risk_score: float = 50.0


class ReplacementEngine:
    def build_candidates(
        self,
        *,
        brief: DailyCIOBrief,
        current_portfolio: tuple[PortfolioHolding, ...],
        watchlist: tuple[WatchlistItem, ...],
        decision_records: tuple[DecisionRecord, ...],
        realized_outcomes: tuple[RealizedOutcome, ...],
        profile_map: dict[str, ReplacementProfile],
    ) -> tuple[ReplacementCandidate, ...]:
        current_symbols = [_normalize_symbol(holding.symbol) for holding in current_portfolio]
        watchlist_symbols = {_normalize_symbol(item.symbol) for item in watchlist}
        outcome_history = self._build_history_index(decision_records, realized_outcomes)

        candidates: list[ReplacementCandidate] = []
        for holding in current_portfolio:
            holding_symbol = _normalize_symbol(holding.symbol)
            holding_profile = profile_map.get(holding_symbol)
            if holding_profile is None:
                continue

            best_match = None
            for candidate in watchlist:
                candidate_symbol = _normalize_symbol(candidate.symbol)
                if candidate_symbol in current_symbols:
                    continue
                candidate_profile = profile_map.get(candidate_symbol)
                if candidate_profile is None:
                    continue
                if best_match is None or self._is_better_candidate(candidate_profile, holding_profile, best_match[1]):
                    best_match = (candidate, candidate_profile)

            if best_match is None:
                continue

            candidate, candidate_profile = best_match
            score_gap = candidate_profile.score - holding_profile.score
            alpha_gap = candidate_profile.expected_alpha - holding_profile.expected_alpha
            if score_gap < 8.0 and alpha_gap < 1.5:
                continue

            evidence = tuple(
                dict.fromkeys(
                    tuple(candidate_profile.evidence)
                    + tuple(holding_profile.evidence)
                    + tuple(outcome_history.get(holding_symbol, ()))
                )
            )
            rationale = (
                f"{candidate.symbol} materially out-scores {holding.symbol} by {score_gap:.1f} points and improves expected alpha by {alpha_gap:.2f}."
            )
            candidates.append(
                ReplacementCandidate(
                    symbol_to_sell=holding.symbol,
                    symbol_to_buy=candidate.symbol,
                    expected_alpha_gain=round(alpha_gap, 2),
                    confidence=round(min(100.0, 50.0 + max(score_gap, 0.0) * 3.0), 1),
                    supporting_evidence=evidence or (f"{candidate.symbol} score {candidate_profile.score:.1f}",),
                    rationale=rationale,
                )
            )

        return tuple(sorted(candidates, key=lambda item: (-item.expected_alpha_gain, item.symbol_to_sell, item.symbol_to_buy)))

    @staticmethod
    def _build_history_index(
        decision_records: tuple[DecisionRecord, ...],
        realized_outcomes: tuple[RealizedOutcome, ...],
    ) -> dict[str, tuple[str, ...]]:
        by_symbol: dict[str, list[str]] = {}
        outcome_map = {outcome.decision_id: outcome for outcome in realized_outcomes}
        for record in decision_records:
            outcome = outcome_map.get(record.decision_id)
            if outcome is None:
                continue
            symbol = _normalize_symbol(record.symbol)
            by_symbol.setdefault(symbol, []).append(
                f"{record.action_type} {outcome.absolute_return:+.2%} / adj {outcome.benchmark_adjusted_return:+.2%}"
            )
        return {symbol: tuple(values) for symbol, values in by_symbol.items()}

    @staticmethod
    def _is_better_candidate(
        candidate: ReplacementProfile,
        holding: ReplacementProfile,
        current_best: ReplacementProfile,
    ) -> bool:
        if candidate.score != current_best.score:
            return candidate.score > current_best.score
        if candidate.expected_alpha != current_best.expected_alpha:
            return candidate.expected_alpha > current_best.expected_alpha
        return candidate.symbol < current_best.symbol