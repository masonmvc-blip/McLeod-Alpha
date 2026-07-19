from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Mapping

from engine.phase3.paper_portfolio_engine.types import PaperPortfolioAudit, PaperTransaction, PerformanceSnapshot, PositionRecord
from engine.phase3.paper_portfolio_governance.types import PaperPortfolioState, PaperRecommendationStatus

from .ledger import PaperLedgerValidationError, PaperPortfolioLedger
from .repository import PaperPortfolioRepository
from .types import (
    HumanApprovalDecision,
    HumanApprovalRecord,
    HumanApprovalStatus,
    PaperEventType,
    PaperTaxLot,
    ReplayCheckpoint,
    ReplayState,
    ReplayValidationResult,
    TaxLotStatus,
)


class PaperPortfolioReplayError(ValueError):
    pass


class PaperPortfolioReplayModel:
    def __init__(self, repository: PaperPortfolioRepository, ledger: PaperPortfolioLedger) -> None:
        self.repository = repository
        self.ledger = ledger

    def replay_from_event_zero(self) -> ReplayState:
        try:
            self.repository.validate_schema_version("1.0")
        except Exception as exc:
            raise PaperPortfolioReplayError(f"Schema validation failed: {exc}") from exc
        self.ledger.validate_hash_chain()
        events = self.ledger.read_events()

        recommendation_statuses: dict[str, PaperRecommendationStatus] = {}
        recommendation_tickers: dict[str, str] = {}
        approvals: list[HumanApprovalRecord] = []
        transactions: list[PaperTransaction] = []
        positions: dict[str, PositionRecord] = {}
        tax_lots: list[PaperTaxLot] = []
        performance_history: list[PerformanceSnapshot] = []
        audit_chain: list[PaperPortfolioAudit] = []
        blocked: set[str] = set()
        cash_balance = 0.0
        realized_pnl = 0.0
        unrealized_pnl = 0.0
        portfolio_nav = 0.0
        latest_state: PaperPortfolioState | None = None

        for event in events:
            payload = dict(event.payload)
            if event.event_type is PaperEventType.RECOMMENDATION_RECORDED:
                recommendation_id = str(payload["recommendation_id"])
                recommendation_statuses[recommendation_id] = PaperRecommendationStatus(payload["status"])
                recommendation_tickers[recommendation_id] = str(payload.get("ticker", "UNKNOWN")).upper()
            elif event.event_type is PaperEventType.APPROVAL_RECORDED:
                raw = dict(payload["approval"])
                raw["approval_decision"] = HumanApprovalDecision(raw["approval_decision"])
                raw["status"] = HumanApprovalStatus(raw["status"])
                approvals.append(HumanApprovalRecord(**raw))
            elif event.event_type in {
                PaperEventType.RECOMMENDATION_REJECTED,
                PaperEventType.RECOMMENDATION_EXPIRED,
                PaperEventType.RECOMMENDATION_SUPERSEDED,
            }:
                recommendation_id = str(payload["recommendation_id"])
                recommendation_statuses[recommendation_id] = PaperRecommendationStatus(payload["status"])
                blocked.add(recommendation_id)
            elif event.event_type is PaperEventType.PAPER_FILL_RECORDED:
                raw = dict(payload["transaction"])
                tx = PaperTransaction(**raw)
                recommendation_id = tx.recommendation_id
                status = recommendation_statuses.get(recommendation_id)
                if status in {
                    PaperRecommendationStatus.REJECTED,
                    PaperRecommendationStatus.EXPIRED,
                    PaperRecommendationStatus.SUPERSEDED,
                }:
                    raise PaperPortfolioReplayError("Rejected/expired/revoked/superseded recommendation was executed.")
                transactions.append(tx)
                realized_pnl += -float(tx.commission)
            elif event.event_type is PaperEventType.POSITION_UPDATED:
                raw = dict(payload["position"])
                position = PositionRecord(**raw)
                positions[position.ticker] = position
            elif event.event_type is PaperEventType.CASH_UPDATED:
                cash_balance = float(payload["cash_balance"])
            elif event.event_type is PaperEventType.PERFORMANCE_SNAPSHOT_RECORDED:
                raw = dict(payload["performance_snapshot"])
                snapshot = PerformanceSnapshot(**raw)
                performance_history.append(snapshot)
                portfolio_nav = float(snapshot.nav)
                unrealized_pnl = float(payload.get("unrealized_pnl", unrealized_pnl))
            elif event.event_type is PaperEventType.PORTFOLIO_RECONCILED:
                raw = dict(payload["portfolio_state"])
                latest_state = PaperPortfolioState(**raw)
                portfolio_nav = latest_state.total_paper_value
            elif event.event_type is PaperEventType.REPLAY_COMPLETED:
                raw = dict(payload["portfolio_audit"])
                audit_chain.append(PaperPortfolioAudit(**raw))
            elif event.event_type is PaperEventType.CORPORATE_ACTION_PENDING:
                ticker = str(payload["ticker"]).upper()
                if not bool(payload.get("validated", False)):
                    for pos in positions.values():
                        if pos.ticker.upper() == ticker:
                            raise PaperPortfolioReplayError("Unvalidated corporate action blocks affected position updates.")

            if "tax_lots" in payload:
                tax_lots = [
                    PaperTaxLot(
                        **{
                            **lot,
                            "status": TaxLotStatus(lot["status"]),
                        }
                    )
                    for lot in payload["tax_lots"]
                ]

        if latest_state is None:
            raise PaperPortfolioReplayError("No reconciled state found during replay.")

        recomputed_realized, recomputed_lots = self._fifo_realized_pnl(
            transactions,
            recommendation_tickers=recommendation_tickers,
        )
        if abs(recomputed_realized - realized_pnl) > 1e-8:
            raise PaperPortfolioReplayError("FIFO realized P&L mismatch in replay.")

        return ReplayState(
            recommendation_statuses=dict(sorted(recommendation_statuses.items())),
            approvals=tuple(sorted(approvals, key=lambda row: (row.approval_timestamp, row.approval_id))),
            transactions=tuple(sorted(transactions, key=lambda row: (row.timestamp, row.transaction_id))),
            positions=tuple(sorted(positions.values(), key=lambda row: row.ticker)),
            cash_balance=cash_balance,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            portfolio_nav=portfolio_nav,
            performance_history=tuple(sorted(performance_history, key=lambda row: row.timestamp)),
            latest_state=latest_state,
            latest_audit_chain=tuple(audit_chain),
            tax_lots=tuple(recomputed_lots) if recomputed_lots else tuple(tax_lots),
            rejected_or_blocked_recommendations=tuple(sorted(blocked)),
        )

    def build_checkpoint(self, created_timestamp: str, source_audit_references: Mapping[str, str]) -> ReplayCheckpoint:
        replay_state = self.replay_from_event_zero()
        head_hash = self.ledger.verify_integrity()
        events = self.ledger.read_events()
        sequence_number = events[-1].sequence_number if events else 0
        state_hash = self._state_hash(replay_state.latest_state)
        checkpoint = ReplayCheckpoint(
            sequence_number=sequence_number,
            state_hash=state_hash,
            ledger_head_hash=head_hash,
            portfolio_state=replay_state.latest_state,
            position_state=replay_state.positions,
            cash_state=replay_state.cash_balance,
            performance_state=replay_state.performance_history[-1],
            schema_version=self.repository.schema_version(),
            created_timestamp=created_timestamp,
            source_audit_references=dict(source_audit_references),
        )
        self.repository.save_checkpoint(checkpoint)
        return checkpoint

    def validate_canonical_state(self) -> ReplayValidationResult:
        replay_first = self.replay_from_event_zero()
        replay_second = self.replay_from_event_zero()
        if replay_first != replay_second:
            raise PaperPortfolioReplayError("Replay is non-deterministic.")

        bundle = self.repository.load_bundle()
        reasons: list[str] = []
        if replay_first.latest_state != bundle.portfolio_state:
            reasons.append("LATEST_STATE_MISMATCH")
        if tuple(sorted(replay_first.positions, key=lambda row: row.ticker)) != tuple(sorted(bundle.positions, key=lambda row: row.ticker)):
            reasons.append("POSITIONS_MISMATCH")
        if tuple(sorted(replay_first.transactions, key=lambda row: row.transaction_id)) != tuple(sorted(bundle.transactions, key=lambda row: row.transaction_id)):
            reasons.append("TRANSACTIONS_MISMATCH")
        if tuple(sorted(replay_first.performance_history, key=lambda row: row.timestamp)) != tuple(sorted(bundle.performance_history, key=lambda row: row.timestamp)):
            reasons.append("PERFORMANCE_MISMATCH")

        canonical_hash = self.repository.get_latest_state_hash()
        replay_state_hash = self._state_hash(replay_first.latest_state)
        if replay_state_hash != canonical_hash:
            reasons.append("STATE_HASH_MISMATCH")

        checkpoints = self.repository.get_checkpoints()
        if checkpoints:
            last_checkpoint = checkpoints[-1]
            if last_checkpoint.state_hash != replay_state_hash:
                reasons.append("CHECKPOINT_STATE_HASH_MISMATCH")
            if last_checkpoint.ledger_head_hash != self.ledger.verify_integrity():
                reasons.append("CHECKPOINT_LEDGER_HEAD_MISMATCH")

        return ReplayValidationResult(
            deterministic=True,
            canonical_match=not reasons,
            replay_head_hash=self.ledger.verify_integrity(),
            canonical_state_hash=canonical_hash,
            replay_state_hash=replay_state_hash,
            mismatch_reasons=tuple(reasons),
        )

    def _state_hash(self, state: PaperPortfolioState) -> str:
        payload = json.dumps(asdict(state), sort_keys=True, separators=(",", ":"), default=str)
        return sha256(payload.encode("utf-8")).hexdigest()

    def _fifo_realized_pnl(
        self,
        transactions: list[PaperTransaction],
        recommendation_tickers: Mapping[str, str],
    ) -> tuple[float, tuple[PaperTaxLot, ...]]:
        lots_by_ticker: dict[str, list[dict[str, float | str]]] = {}
        realized = 0.0
        for tx in sorted(transactions, key=lambda row: (row.timestamp, row.transaction_id)):
            ticker = recommendation_tickers.get(tx.recommendation_id, "UNKNOWN")
            lots = lots_by_ticker.setdefault(ticker, [])
            if tx.transaction_type == "BUY":
                qty = tx.shares
                cost_per_share = tx.simulated_execution_price + (tx.commission / max(tx.shares, 1e-12))
                lots.append(
                    {
                        "remaining_quantity": qty,
                        "cost_per_share": cost_per_share,
                        "opening_timestamp": tx.timestamp,
                        "opening_transaction_id": tx.transaction_id,
                    }
                )
                continue

            sell_qty = tx.shares
            while sell_qty > 1e-12 and lots:
                lot = lots[0]
                available = float(lot["remaining_quantity"])
                consumed = min(available, sell_qty)
                proceeds = consumed * tx.simulated_execution_price
                cost = consumed * float(lot["cost_per_share"])
                realized += proceeds - cost
                lot["remaining_quantity"] = available - consumed
                if float(lot["remaining_quantity"]) <= 1e-12:
                    lots.pop(0)
                sell_qty -= consumed
            if sell_qty > 1e-12:
                raise PaperPortfolioReplayError("Sell exceeds available FIFO lots.")

        tax_lots: list[PaperTaxLot] = []
        for ticker, lots in sorted(lots_by_ticker.items()):
            for idx, lot in enumerate(lots, start=1):
                remaining = float(lot["remaining_quantity"])
                if remaining <= 1e-12:
                    continue
                cost_per_share = float(lot["cost_per_share"])
                tax_lots.append(
                    PaperTaxLot(
                        lot_id=sha256(f"{ticker}|{lot['opening_transaction_id']}|{idx}".encode("utf-8")).hexdigest(),
                        ticker=ticker,
                        opening_transaction_id=str(lot["opening_transaction_id"]),
                        opening_timestamp=str(lot["opening_timestamp"]),
                        original_quantity=remaining,
                        remaining_quantity=remaining,
                        cost_per_share=cost_per_share,
                        total_cost_basis=remaining * cost_per_share,
                        realized_pnl=0.0,
                        status=TaxLotStatus.OPEN,
                        provenance={"method": "fifo"},
                    )
                )
        return realized, tuple(tax_lots)
