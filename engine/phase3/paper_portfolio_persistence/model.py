from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from engine.phase3.paper_portfolio_engine.types import PaperPortfolioEngineResult
from engine.phase3.paper_portfolio_governance.types import (
    PaperRecommendationRecord,
    PaperRecommendationStatus,
)

from .ledger import PaperPortfolioLedger
from .repository import PaperPortfolioRepository, PaperPortfolioRepositoryError
from .types import (
    CorporateActionRecord,
    HumanApprovalDecision,
    HumanApprovalStatus,
    HumanApprovalRecord,
    PaperEventType,
    PaperTaxLot,
    TaxLotStatus,
)


class PaperPortfolioPersistenceValidationError(ValueError):
    pass


class PaperPortfolioPersistenceModel:
    def __init__(self, repository: PaperPortfolioRepository, ledger: PaperPortfolioLedger) -> None:
        self.repository = repository
        self.ledger = ledger

    def persist_recommendation_lifecycle(
        self,
        *,
        recommendation: PaperRecommendationRecord,
        source_audit_references: Mapping[str, str],
        provenance: Mapping[str, Any],
        created_timestamp: str,
    ) -> None:
        if recommendation.status is PaperRecommendationStatus.APPROVED_FOR_PAPER:
            event_type = PaperEventType.RECOMMENDATION_RECORDED
        elif recommendation.status is PaperRecommendationStatus.REJECTED:
            event_type = PaperEventType.RECOMMENDATION_REJECTED
        elif recommendation.status is PaperRecommendationStatus.EXPIRED:
            event_type = PaperEventType.RECOMMENDATION_EXPIRED
        elif recommendation.status is PaperRecommendationStatus.SUPERSEDED:
            event_type = PaperEventType.RECOMMENDATION_SUPERSEDED
        elif recommendation.status in {PaperRecommendationStatus.DRAFT, PaperRecommendationStatus.PENDING_APPROVAL, PaperRecommendationStatus.BLOCKED}:
            event_type = PaperEventType.RECOMMENDATION_RECORDED
        else:
            raise PaperPortfolioPersistenceValidationError("Unsupported recommendation status.")

        self.repository.upsert_recommendation(recommendation, updated_timestamp=created_timestamp)
        self.ledger.append_event(
            event_type=event_type,
            event_timestamp=created_timestamp,
            effective_timestamp=recommendation.created_timestamp,
            aggregate_id="paper-portfolio",
            recommendation_id=recommendation.recommendation_id,
            transaction_id=None,
            payload_version="1.0",
            payload={
                "recommendation_id": recommendation.recommendation_id,
                "ticker": recommendation.ticker,
                "status": recommendation.status.value,
            },
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=created_timestamp,
        )

    def persist_approval(
        self,
        *,
        approval: HumanApprovalRecord,
        source_audit_references: Mapping[str, str],
        provenance: Mapping[str, Any],
        created_timestamp: str,
    ) -> None:
        self.repository.save_approval(approval)
        self.ledger.append_event(
            event_type=PaperEventType.APPROVAL_RECORDED,
            event_timestamp=created_timestamp,
            effective_timestamp=approval.approval_timestamp,
            aggregate_id="paper-portfolio",
            recommendation_id=approval.recommendation_id,
            transaction_id=None,
            payload_version="1.0",
            payload={"approval": asdict(approval)},
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=created_timestamp,
        )

    def persist_engine_result(
        self,
        *,
        recommendations: Sequence[PaperRecommendationRecord],
        engine_result: PaperPortfolioEngineResult,
        source_audit_references: Mapping[str, str],
        provenance: Mapping[str, Any],
        created_timestamp: str,
    ) -> tuple[PaperTaxLot, ...]:
        disallowed = {
            PaperRecommendationStatus.REJECTED,
            PaperRecommendationStatus.EXPIRED,
            PaperRecommendationStatus.SUPERSEDED,
        }
        approvals = self.repository.get_approvals()
        for tx in engine_result.simulated_fills:
            rec = [row for row in recommendations if row.recommendation_id == tx.recommendation_id]
            if not rec:
                raise PaperPortfolioPersistenceValidationError("Transaction has unknown recommendation.")
            status = rec[0].status
            if status in disallowed:
                raise PaperPortfolioPersistenceValidationError("Rejected/expired/superseded recommendation executed.")
            if status is not PaperRecommendationStatus.APPROVED_FOR_PAPER:
                raise PaperPortfolioPersistenceValidationError("Only approved recommendations can execute.")
            if not self._has_active_human_approval(
                recommendation_id=tx.recommendation_id,
                approvals=approvals,
            ):
                raise PaperPortfolioPersistenceValidationError("Approved recommendation has no active human approval record.")

        self.repository.save_transactions(engine_result.simulated_fills, created_timestamp)
        self.repository.save_positions(engine_result.positions, created_timestamp)
        self.repository.save_performance_snapshot(engine_result.performance_snapshot, created_timestamp)
        self.repository.save_portfolio_audit(engine_result.portfolio_audit, created_timestamp)
        self.repository.save_portfolio_state(engine_result.updated_state, created_timestamp)

        for tx in engine_result.simulated_fills:
            self.ledger.append_event(
                event_type=PaperEventType.PAPER_FILL_RECORDED,
                event_timestamp=created_timestamp,
                effective_timestamp=tx.timestamp,
                aggregate_id="paper-portfolio",
                recommendation_id=tx.recommendation_id,
                transaction_id=tx.transaction_id,
                payload_version="1.0",
                payload={"transaction": asdict(tx)},
                source_audit_references=source_audit_references,
                provenance=provenance,
                created_timestamp=created_timestamp,
            )

        for position in sorted(engine_result.positions, key=lambda row: row.ticker):
            if self.repository.ticker_has_unvalidated_corporate_action(position.ticker):
                raise PaperPortfolioPersistenceValidationError(
                    f"Unvalidated corporate action blocks position updates for {position.ticker}."
                )
            self.ledger.append_event(
                event_type=PaperEventType.POSITION_UPDATED,
                event_timestamp=created_timestamp,
                effective_timestamp=position.last_update,
                aggregate_id="paper-portfolio",
                recommendation_id=None,
                transaction_id=None,
                payload_version="1.0",
                payload={"position": asdict(position)},
                source_audit_references=source_audit_references,
                provenance=provenance,
                created_timestamp=created_timestamp,
            )

        self.ledger.append_event(
            event_type=PaperEventType.CASH_UPDATED,
            event_timestamp=created_timestamp,
            effective_timestamp=engine_result.performance_snapshot.timestamp,
            aggregate_id="paper-portfolio",
            recommendation_id=None,
            transaction_id=None,
            payload_version="1.0",
            payload={"cash_balance": engine_result.cash_balance},
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=created_timestamp,
        )

        self.ledger.append_event(
            event_type=PaperEventType.PERFORMANCE_SNAPSHOT_RECORDED,
            event_timestamp=created_timestamp,
            effective_timestamp=engine_result.performance_snapshot.timestamp,
            aggregate_id="paper-portfolio",
            recommendation_id=None,
            transaction_id=None,
            payload_version="1.0",
            payload={
                "performance_snapshot": asdict(engine_result.performance_snapshot),
                "unrealized_pnl": engine_result.unrealized_pnl,
            },
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=created_timestamp,
        )

        self.ledger.append_event(
            event_type=PaperEventType.PORTFOLIO_RECONCILED,
            event_timestamp=created_timestamp,
            effective_timestamp=engine_result.updated_state.as_of_timestamp,
            aggregate_id="paper-portfolio",
            recommendation_id=None,
            transaction_id=None,
            payload_version="1.0",
            payload={"portfolio_state": asdict(engine_result.updated_state)},
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=created_timestamp,
        )

        self.ledger.append_event(
            event_type=PaperEventType.REPLAY_COMPLETED,
            event_timestamp=created_timestamp,
            effective_timestamp=engine_result.updated_state.as_of_timestamp,
            aggregate_id="paper-portfolio",
            recommendation_id=None,
            transaction_id=None,
            payload_version="1.0",
            payload={"portfolio_audit": asdict(engine_result.portfolio_audit)},
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=created_timestamp,
        )

        recommendation_ticker_map = {
            row.recommendation_id: row.ticker.upper() for row in recommendations
        }
        tax_lots = self._deterministic_fifo_lots(
            engine_result.simulated_fills,
            recommendation_ticker_map=recommendation_ticker_map,
        )
        self.repository.save_tax_lots(tax_lots, updated_timestamp=created_timestamp)
        return tax_lots

    def _has_active_human_approval(
        self,
        *,
        recommendation_id: str,
        approvals: Sequence[HumanApprovalRecord],
    ) -> bool:
        approved = False
        for approval in approvals:
            if approval.recommendation_id != recommendation_id:
                continue
            if (
                approval.approval_decision is HumanApprovalDecision.APPROVE_FOR_PAPER
                and approval.status is HumanApprovalStatus.ACTIVE
            ):
                approved = True
            if approval.approval_decision is HumanApprovalDecision.REJECT_FOR_PAPER:
                return False
            if approval.approval_decision is HumanApprovalDecision.REVOKE_PAPER_APPROVAL:
                return False
        return approved

    def persist_corporate_action_pending(
        self,
        *,
        record: CorporateActionRecord,
        source_audit_references: Mapping[str, str],
        provenance: Mapping[str, Any],
    ) -> None:
        self.repository.save_corporate_action(record)
        self.ledger.append_event(
            event_type=PaperEventType.CORPORATE_ACTION_PENDING,
            event_timestamp=record.created_timestamp,
            effective_timestamp=record.effective_timestamp,
            aggregate_id="paper-portfolio",
            recommendation_id=None,
            transaction_id=None,
            payload_version="1.0",
            payload={
                "action_id": record.action_id,
                "ticker": record.ticker,
                "action_type": record.action_type.value,
                "validated": record.validated,
                "payload": dict(record.payload),
            },
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=record.created_timestamp,
        )

    def restore_state(self):
        return self.repository.load_bundle()

    def _deterministic_fifo_lots(
        self,
        transactions,
        recommendation_ticker_map: Mapping[str, str],
    ) -> tuple[PaperTaxLot, ...]:
        lot_index = 0
        inventory: dict[str, list[dict[str, Any]]] = {}
        for tx in sorted(transactions, key=lambda row: (row.timestamp, row.transaction_id)):
            ticker = recommendation_ticker_map.get(tx.recommendation_id, "UNKNOWN")
            lots = inventory.setdefault(ticker, [])
            if tx.transaction_type == "BUY":
                lot_index += 1
                lots.append(
                    {
                        "lot_id": sha256(f"{ticker}|{tx.transaction_id}|{lot_index}".encode("utf-8")).hexdigest(),
                        "ticker": ticker,
                        "opening_transaction_id": tx.transaction_id,
                        "opening_timestamp": tx.timestamp,
                        "original_quantity": tx.shares,
                        "remaining_quantity": tx.shares,
                        "cost_per_share": tx.simulated_execution_price,
                        "total_cost_basis": tx.shares * tx.simulated_execution_price,
                        "realized_pnl": 0.0,
                    }
                )
                continue

            remaining = tx.shares
            while remaining > 1e-12 and lots:
                lot = lots[0]
                consume = min(float(lot["remaining_quantity"]), remaining)
                lot["remaining_quantity"] = float(lot["remaining_quantity"]) - consume
                proceeds = consume * tx.simulated_execution_price
                basis = consume * float(lot["cost_per_share"])
                lot["realized_pnl"] = float(lot["realized_pnl"]) + (proceeds - basis)
                remaining -= consume
                if float(lot["remaining_quantity"]) <= 1e-12:
                    lots.pop(0)
            if remaining > 1e-12:
                raise PaperPortfolioPersistenceValidationError("FIFO sale exceeds available inventory.")

        output: list[PaperTaxLot] = []
        for ticker, lots in sorted(inventory.items()):
            for lot in lots:
                output.append(
                    PaperTaxLot(
                        lot_id=str(lot["lot_id"]),
                        ticker=ticker,
                        opening_transaction_id=str(lot["opening_transaction_id"]),
                        opening_timestamp=str(lot["opening_timestamp"]),
                        original_quantity=float(lot["original_quantity"]),
                        remaining_quantity=float(lot["remaining_quantity"]),
                        cost_per_share=float(lot["cost_per_share"]),
                        total_cost_basis=float(lot["total_cost_basis"]),
                        realized_pnl=float(lot["realized_pnl"]),
                        status=TaxLotStatus.OPEN if float(lot["remaining_quantity"]) > 1e-12 else TaxLotStatus.CLOSED,
                        provenance={"method": "fifo"},
                    )
                )
        return tuple(output)
