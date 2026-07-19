from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Mapping, Sequence

from engine.phase3.paper_portfolio_persistence.types import PersistedBundle, ReplayValidationResult

from .types import (
    PaperOperationRequest,
    PaperOperationsPreflightResult,
    PaperOperationsSession,
    PaperReconciliationResult,
)


def build_daily_operations_report(
    *,
    operating_mode: str,
    session: PaperOperationsSession,
    preflight: PaperOperationsPreflightResult,
    reconciliation: PaperReconciliationResult,
    replay_validation: ReplayValidationResult,
    bundle: PersistedBundle,
    requests: Sequence[PaperOperationRequest],
    benchmark_comparison: Mapping[str, float],
    drawdown: float,
    audit_references: Mapping[str, str],
) -> Mapping[str, object]:
    approved_recommendations = sorted(
        [row.recommendation_id for row in bundle.recommendations if row.status.value == "APPROVED_FOR_PAPER"]
    )
    completed_fills = sorted([row.transaction_id for row in bundle.transactions])
    rejected_requests = sorted([row.request_id for row in requests if row.request_status.value in {"BLOCKED", "REJECTED", "FAILED"}])

    latest_performance = bundle.performance_history[-1] if bundle.performance_history else None
    holdings = {row.ticker: row.quantity for row in bundle.positions}

    report = {
        "operating_mode": operating_mode,
        "session_status": session.session_status.value,
        "preflight_result": preflight.passed,
        "active_blockers": list(preflight.blockers),
        "warnings": list(preflight.warnings),
        "ledger_status": preflight.checks.get("ledger_integrity", False),
        "reconciliation_status": reconciliation.passed,
        "replay_status": replay_validation.canonical_match,
        "checkpoint_status": preflight.checks.get("checkpoint_match", False),
        "backup_status": preflight.checks.get("backups", False),
        "restore_test_status": preflight.checks.get("restore_test", False),
        "latest_paper_nav": bundle.portfolio_state.total_paper_value,
        "paper_cash": bundle.portfolio_state.paper_cash,
        "paper_holdings": dict(sorted(holdings.items())),
        "approved_paper_recommendations": approved_recommendations,
        "completed_paper_fills": completed_fills,
        "rejected_operation_requests": rejected_requests,
        "performance_summary": {
            "daily_return": latest_performance.daily_return if latest_performance else 0.0,
            "cumulative_return": latest_performance.cumulative_return if latest_performance else 0.0,
            "active_return": latest_performance.active_return if latest_performance else 0.0,
        },
        "benchmark_comparison": dict(sorted(benchmark_comparison.items())),
        "drawdown": drawdown,
        "audit_references": dict(sorted(audit_references.items())),
    }
    report["report_hash"] = sha256(json.dumps(report, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    return report
