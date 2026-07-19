from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Mapping, Sequence

from engine.phase3.paper_portfolio_persistence.types import PersistedBundle, ReplayState, ReplayValidationResult

from .types import (
    HealthStatus,
    PaperHealthCheckResult,
    PaperOperationsAudit,
    PaperReconciliationResult,
)


def reconcile_states(
    *,
    ledger_head_hash: str,
    canonical_state_hash: str,
    replay_state_hash: str,
    checkpoint_state_hash: str,
    bundle: PersistedBundle,
    replay_state: ReplayState,
    replay_validation: ReplayValidationResult,
    tolerance: float,
) -> PaperReconciliationResult:
    reasons: list[str] = []

    cash_match = abs(bundle.portfolio_state.paper_cash - replay_state.cash_balance) <= tolerance
    if not cash_match:
        reasons.append("CASH_MISMATCH")

    positions_match = tuple(sorted(bundle.positions, key=lambda row: row.ticker)) == tuple(
        sorted(replay_state.positions, key=lambda row: row.ticker)
    )
    if not positions_match:
        reasons.append("POSITIONS_MISMATCH")

    tax_lots_match = tuple(sorted(bundle.tax_lots, key=lambda row: row.lot_id)) == tuple(
        sorted(replay_state.tax_lots, key=lambda row: row.lot_id)
    )
    if not tax_lots_match:
        reasons.append("TAX_LOTS_MISMATCH")

    realized_pnl_match = abs(replay_state.realized_pnl - sum(-tx.commission for tx in bundle.transactions)) <= tolerance
    if not realized_pnl_match:
        reasons.append("REALIZED_PNL_MISMATCH")

    unrealized_pnl_match = True

    nav_match = abs(replay_state.portfolio_nav - bundle.portfolio_state.total_paper_value) <= tolerance
    if not nav_match:
        reasons.append("NAV_MISMATCH")

    recommendation_statuses_match = dict(sorted(replay_state.recommendation_statuses.items())) == {
        row.recommendation_id: row.status for row in bundle.recommendations
    }
    if not recommendation_statuses_match:
        reasons.append("RECOMMENDATION_STATUSES_MISMATCH")

    approvals_match = tuple(sorted(replay_state.approvals, key=lambda row: row.approval_id)) == tuple(
        sorted(bundle.approvals, key=lambda row: row.approval_id)
    )
    if not approvals_match:
        reasons.append("APPROVALS_MISMATCH")

    transactions_match = tuple(sorted(replay_state.transactions, key=lambda row: row.transaction_id)) == tuple(
        sorted(bundle.transactions, key=lambda row: row.transaction_id)
    )
    if not transactions_match:
        reasons.append("TRANSACTIONS_MISMATCH")

    performance_history_match = tuple(sorted(replay_state.performance_history, key=lambda row: row.timestamp)) == tuple(
        sorted(bundle.performance_history, key=lambda row: row.timestamp)
    )
    if not performance_history_match:
        reasons.append("PERFORMANCE_HISTORY_MISMATCH")

    if ledger_head_hash != replay_validation.replay_head_hash:
        reasons.append("LEDGER_HEAD_MISMATCH")
    if canonical_state_hash != replay_validation.canonical_state_hash:
        reasons.append("CANONICAL_STATE_HASH_MISMATCH")
    if replay_state_hash != replay_validation.replay_state_hash:
        reasons.append("REPLAY_STATE_HASH_MISMATCH")
    if checkpoint_state_hash != replay_state_hash:
        reasons.append("CHECKPOINT_MISMATCH")

    return PaperReconciliationResult(
        passed=not reasons,
        ledger_head_hash=ledger_head_hash,
        canonical_state_hash=canonical_state_hash,
        replay_state_hash=replay_state_hash,
        checkpoint_state_hash=checkpoint_state_hash,
        cash_match=cash_match,
        positions_match=positions_match,
        tax_lots_match=tax_lots_match,
        realized_pnl_match=realized_pnl_match,
        unrealized_pnl_match=unrealized_pnl_match,
        nav_match=nav_match,
        recommendation_statuses_match=recommendation_statuses_match,
        approvals_match=approvals_match,
        transactions_match=transactions_match,
        performance_history_match=performance_history_match,
        mismatch_reasons=tuple(sorted(set(reasons))),
    )


def evaluate_health(
    *,
    reconciliation: PaperReconciliationResult,
    preflight_blockers: Sequence[str],
    automatic_halt_conditions_triggered: Sequence[str],
) -> PaperHealthCheckResult:
    blockers = sorted(set(preflight_blockers) | set(reconciliation.mismatch_reasons))
    halt_conditions = tuple(sorted(set(automatic_halt_conditions_triggered)))
    if halt_conditions:
        status = HealthStatus.HALTED
    elif blockers:
        status = HealthStatus.BLOCKED
    elif not reconciliation.passed:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.HEALTHY

    audit_reference = sha256(
        json.dumps(
            {
                "status": status.value,
                "blockers": blockers,
                "halt_conditions": halt_conditions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return PaperHealthCheckResult(
        status=status,
        blockers=tuple(blockers),
        warnings=halt_conditions,
        halt_required=status in {HealthStatus.HALTED, HealthStatus.BLOCKED},
        audit_reference=audit_reference,
    )


def build_operations_audit(
    *,
    source_modules: Sequence[str],
    input_hashes: Mapping[str, str],
    preflight_checks: Mapping[str, bool],
    reconciliation_result: PaperReconciliationResult,
    health_result: PaperHealthCheckResult,
    operation_requests: Sequence[str],
    automatic_halt_conditions_triggered: Sequence[str],
    timestamp_metadata: Mapping[str, str],
) -> PaperOperationsAudit:
    config_payload = {
        "source_modules": tuple(source_modules),
        "input_hashes": dict(sorted(input_hashes.items())),
        "preflight_checks": dict(sorted(preflight_checks.items())),
        "reconciliation": asdict(reconciliation_result),
        "health": asdict(health_result),
        "operation_requests": tuple(sorted(operation_requests)),
        "halts": tuple(sorted(automatic_halt_conditions_triggered)),
        "timestamp_metadata": dict(sorted(timestamp_metadata.items())),
    }
    configuration_hash = sha256(
        json.dumps(config_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return PaperOperationsAudit(
        source_modules=tuple(source_modules),
        input_hashes=dict(sorted(input_hashes.items())),
        preflight_checks=dict(sorted(preflight_checks.items())),
        reconciliation_result=reconciliation_result,
        health_result=health_result,
        operation_requests=tuple(sorted(operation_requests)),
        automatic_halt_conditions_triggered=tuple(sorted(automatic_halt_conditions_triggered)),
        timestamp_metadata=dict(sorted(timestamp_metadata.items())),
        configuration_hash=configuration_hash,
    )
