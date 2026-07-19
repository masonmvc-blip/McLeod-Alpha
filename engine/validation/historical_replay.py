from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReplayPoint:
    as_of_date: str
    research_score: float
    thesis_score: float
    confidence_score: float
    recommendations: tuple[str, ...]
    portfolio_weights: tuple[tuple[str, float], ...]
    cio_return: float
    spy_return: float
    equal_weight_return: float
    benchmark_return: float
    turnover: float
    average_holding_period: float
    replacement_success: bool
    sector_returns: tuple[tuple[str, float], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReplayStageResult:
    as_of_date: str
    research_stage: str
    thesis_stage: str
    decision_stage: str
    portfolio_stage: str
    performance_stage: str


@dataclass(frozen=True)
class HistoricalReplayResult:
    points: tuple[ReplayPoint, ...]
    stage_results: tuple[ReplayStageResult, ...]


def _is_sorted_non_decreasing(values: tuple[str, ...]) -> bool:
    return all(values[index] <= values[index + 1] for index in range(len(values) - 1))


def run_historical_replay(points: tuple[ReplayPoint, ...]) -> HistoricalReplayResult:
    if not points:
        return HistoricalReplayResult(points=(), stage_results=())

    ordered_dates = tuple(point.as_of_date for point in points)
    if not _is_sorted_non_decreasing(ordered_dates):
        raise ValueError("Replay points must be sorted by as_of_date to avoid future information leakage.")

    stage_results = tuple(
        ReplayStageResult(
            as_of_date=point.as_of_date,
            research_stage="completed",
            thesis_stage="completed",
            decision_stage="completed",
            portfolio_stage="completed",
            performance_stage="completed",
        )
        for point in points
    )
    return HistoricalReplayResult(points=points, stage_results=stage_results)
