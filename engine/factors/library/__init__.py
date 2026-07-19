from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Callable

from engine.factors import FactorContract, FactorMetadata


def number(snapshot: Mapping[str, Any], field: str) -> float:
    fundamentals = snapshot.get("company_fundamentals")
    if not isinstance(fundamentals, Mapping) or field not in fundamentals:
        raise ValueError(f"missing required input: company_fundamentals.{field}")
    value = fundamentals[field]
    if isinstance(value, Mapping):
        _assert_point_in_time(snapshot, value, field)
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"malformed numeric input: company_fundamentals.{field}")
    return float(value)


def series(snapshot: Mapping[str, Any], field: str) -> tuple[float, ...]:
    fundamentals = snapshot.get("company_fundamentals")
    values = fundamentals.get(field) if isinstance(fundamentals, Mapping) else None
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise ValueError(f"missing required input: company_fundamentals.{field}")
    result = []
    for item in values:
        if isinstance(item, Mapping):
            _assert_point_in_time(snapshot, item, field)
            item = item.get("value")
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"malformed numeric input: company_fundamentals.{field}")
        result.append(float(item))
    return tuple(result)


def ratio(numerator: float, denominator: float, label: str) -> float:
    if denominator == 0.0:
        raise ValueError(f"zero denominator: {label}")
    return numerator / denominator


def average(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _assert_point_in_time(snapshot: Mapping[str, Any], observation: Mapping[str, Any], field: str) -> None:
    snapshot_date = snapshot.get("snapshot_date")
    if not isinstance(snapshot_date, str):
        raise ValueError("missing required input: snapshot_date")
    try:
        as_of = date.fromisoformat(snapshot_date[:10])
    except ValueError as exc:
        raise ValueError("malformed snapshot_date") from exc
    for key in ("publication_date", "filing_date", "effective_date"):
        if key in observation:
            try:
                available = date.fromisoformat(str(observation[key])[:10])
            except ValueError as exc:
                raise ValueError(f"malformed availability date: {field}.{key}") from exc
            if available > as_of:
                raise ValueError(f"future-dated observation rejected: {field}.{key}")


def factor(*, factor_id: str, name: str, category: str, rationale: str, fields: tuple[str, ...], evaluator: Callable[[Mapping[str, Any]], float]) -> FactorContract:
    metadata = FactorMetadata(factor_id, name, "1.0.0", "McLeod Alpha Research", "2026-07-19T00:00:00Z", name, rationale, "POSITIVE", category, ("core", category.lower().replace("_", "-")), ("company_fundamentals", "snapshot_date"), True, True, "EXPERIMENTAL", True, False, required_snapshot_fields=("company_fundamentals", "snapshot_date"))
    return FactorContract(metadata, evaluator)


from .quality.roic_persistence import FACTOR as ROIC_PERSISTENCE
from .quality.gross_margin_stability import FACTOR as GROSS_MARGIN_STABILITY
from .quality.free_cash_flow_conversion import FACTOR as FREE_CASH_FLOW_CONVERSION
from .growth.revenue_acceleration import FACTOR as REVENUE_ACCELERATION
from .growth.earnings_acceleration import FACTOR as EARNINGS_ACCELERATION
from .value.free_cash_flow_yield import FACTOR as FREE_CASH_FLOW_YIELD
from .value.earnings_yield import FACTOR as EARNINGS_YIELD
from .capital_allocation.share_count_reduction import FACTOR as SHARE_COUNT_REDUCTION
from .capital_allocation.reinvestment_efficiency import FACTOR as REINVESTMENT_EFFICIENCY
from .balance_sheet.net_debt_to_fcf import FACTOR as NET_DEBT_TO_FCF


def core_factors() -> tuple[FactorContract, ...]:
    return (ROIC_PERSISTENCE, GROSS_MARGIN_STABILITY, FREE_CASH_FLOW_CONVERSION, REVENUE_ACCELERATION, EARNINGS_ACCELERATION, FREE_CASH_FLOW_YIELD, EARNINGS_YIELD, SHARE_COUNT_REDUCTION, REINVESTMENT_EFFICIENCY, NET_DEBT_TO_FCF)