from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Mapping, Sequence

from engine.phase3.paper_portfolio_engine.types import PaperPortfolioAudit, PaperTransaction, PerformanceSnapshot, PositionRecord
from engine.phase3.paper_portfolio_governance.types import (
    PaperPortfolioState,
    PaperRecommendationRecord,
    PaperRecommendationStatus,
)

from .types import (
    CorporateActionRecord,
    HumanApprovalDecision,
    HumanApprovalRecord,
    HumanApprovalStatus,
    PaperTaxLot,
    PersistedBundle,
    ReplayCheckpoint,
    TaxLotStatus,
)


class PaperPortfolioRepositoryError(ValueError):
    pass


class InvalidLifecycleTransitionError(PaperPortfolioRepositoryError):
    pass


class PaperPortfolioRepository:
    SCHEMA_VERSION = "1.0"
    RECOMMENDATION_TRANSITIONS: Mapping[PaperRecommendationStatus, tuple[PaperRecommendationStatus, ...]] = {
        PaperRecommendationStatus.DRAFT: (
            PaperRecommendationStatus.BLOCKED,
            PaperRecommendationStatus.PENDING_APPROVAL,
        ),
        PaperRecommendationStatus.PENDING_APPROVAL: (
            PaperRecommendationStatus.APPROVED_FOR_PAPER,
            PaperRecommendationStatus.REJECTED,
        ),
        PaperRecommendationStatus.APPROVED_FOR_PAPER: (
            PaperRecommendationStatus.SUPERSEDED,
            PaperRecommendationStatus.EXPIRED,
            PaperRecommendationStatus.REJECTED,
        ),
        PaperRecommendationStatus.BLOCKED: (),
        PaperRecommendationStatus.REJECTED: (),
        PaperRecommendationStatus.EXPIRED: (),
        PaperRecommendationStatus.SUPERSEDED: (),
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = FULL")
        self._create_schema()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterable[sqlite3.Connection]:
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                sequence_number INTEGER PRIMARY KEY,
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                effective_timestamp TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                recommendation_id TEXT,
                transaction_id TEXT,
                payload_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                duplicate_fingerprint TEXT UNIQUE NOT NULL,
                previous_event_hash TEXT NOT NULL,
                event_hash TEXT UNIQUE NOT NULL,
                source_audit_references_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recommendation_records (
                recommendation_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                recommendation_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_timestamp TEXT NOT NULL,
                FOREIGN KEY (recommendation_id) REFERENCES recommendation_records(recommendation_id)
            );

            CREATE TABLE IF NOT EXISTS paper_transactions (
                transaction_id TEXT PRIMARY KEY,
                recommendation_id TEXT,
                payload_json TEXT NOT NULL,
                created_timestamp TEXT NOT NULL,
                FOREIGN KEY (recommendation_id) REFERENCES recommendation_records(recommendation_id)
            );

            CREATE TABLE IF NOT EXISTS paper_positions (
                ticker TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS performance_snapshots (
                timestamp TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolio_states (
                as_of_timestamp TEXT PRIMARY KEY,
                state_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolio_audits (
                audit_hash TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS replay_checkpoints (
                sequence_number INTEGER PRIMARY KEY,
                state_hash TEXT NOT NULL,
                ledger_head_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                created_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tax_lots (
                lot_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS corporate_actions (
                action_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                action_type TEXT NOT NULL,
                validated INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_timestamp TEXT NOT NULL
            );
            """
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", self.SCHEMA_VERSION),
        )
        self.conn.commit()

    def _to_jsonable(self, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {str(k): self._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._to_jsonable(v) for v in value]
        return value

    def _json_dumps(self, payload: Any) -> str:
        return json.dumps(self._to_jsonable(payload), sort_keys=True, separators=(",", ":"))

    def schema_version(self) -> str:
        row = self.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row is None:
            raise PaperPortfolioRepositoryError("Missing schema version metadata.")
        return str(row["value"])

    def validate_schema_version(self, expected: str) -> None:
        actual = self.schema_version()
        if actual != expected:
            raise PaperPortfolioRepositoryError(f"Schema mismatch: expected={expected} actual={actual}")

    def persist_event_row(self, row: Mapping[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO events(
                    sequence_number,
                    event_id,
                    event_type,
                    event_timestamp,
                    effective_timestamp,
                    aggregate_id,
                    recommendation_id,
                    transaction_id,
                    payload_version,
                    payload_json,
                    payload_hash,
                    duplicate_fingerprint,
                    previous_event_hash,
                    event_hash,
                    source_audit_references_json,
                    provenance_json,
                    created_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["sequence_number"]),
                    str(row["event_id"]),
                    str(row["event_type"]),
                    str(row["event_timestamp"]),
                    str(row["effective_timestamp"]),
                    str(row["aggregate_id"]),
                    row.get("recommendation_id"),
                    row.get("transaction_id"),
                    str(row["payload_version"]),
                    str(row["payload_json"]),
                    str(row["payload_hash"]),
                    str(row["duplicate_fingerprint"]),
                    str(row["previous_event_hash"]),
                    str(row["event_hash"]),
                    str(row["source_audit_references_json"]),
                    str(row["provenance_json"]),
                    str(row["created_timestamp"]),
                ),
            )

    def next_event_sequence_and_previous_hash(self) -> tuple[int, str]:
        row = self.conn.execute(
            "SELECT sequence_number, event_hash FROM events ORDER BY sequence_number DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 1, "GENESIS"
        return int(row["sequence_number"]) + 1, str(row["event_hash"])

    def list_event_rows(self) -> tuple[Mapping[str, Any], ...]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY sequence_number ASC").fetchall()
        return tuple(dict(row) for row in rows)

    def upsert_recommendation(self, record: PaperRecommendationRecord, updated_timestamp: str) -> None:
        payload = self._json_dumps(asdict(record))
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT status FROM recommendation_records WHERE recommendation_id = ?",
                (record.recommendation_id,),
            ).fetchone()
            if existing is not None:
                from_status = PaperRecommendationStatus(str(existing["status"]))
                to_status = record.status
                self._validate_transition(from_status=from_status, to_status=to_status)
                if (
                    from_status is PaperRecommendationStatus.APPROVED_FOR_PAPER
                    and to_status is PaperRecommendationStatus.REJECTED
                ):
                    revoke = conn.execute(
                        """
                        SELECT 1 FROM approvals
                        WHERE recommendation_id = ?
                          AND decision = ?
                          AND status = ?
                        ORDER BY created_timestamp DESC
                        LIMIT 1
                        """,
                        (
                            record.recommendation_id,
                            HumanApprovalDecision.REVOKE_PAPER_APPROVAL.value,
                            HumanApprovalStatus.REVOKED.value,
                        ),
                    ).fetchone()
                    if revoke is None:
                        raise InvalidLifecycleTransitionError(
                            "APPROVED_FOR_PAPER -> REJECTED requires explicit approval revocation."
                        )
            conn.execute(
                """
                INSERT INTO recommendation_records(recommendation_id, ticker, status, payload_json, updated_timestamp)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(recommendation_id)
                DO UPDATE SET status=excluded.status, payload_json=excluded.payload_json, updated_timestamp=excluded.updated_timestamp
                """,
                (record.recommendation_id, record.ticker, record.status.value, payload, updated_timestamp),
            )

    def get_recommendations(self) -> tuple[PaperRecommendationRecord, ...]:
        rows = self.conn.execute(
            "SELECT payload_json FROM recommendation_records ORDER BY recommendation_id"
        ).fetchall()
        records: list[PaperRecommendationRecord] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            payload["status"] = PaperRecommendationStatus(payload["status"])
            records.append(PaperRecommendationRecord(**payload))
        return tuple(records)

    def save_approval(self, approval: HumanApprovalRecord) -> None:
        if approval.approval_decision is HumanApprovalDecision.APPROVE_FOR_PAPER and approval.status is not HumanApprovalStatus.ACTIVE:
            raise PaperPortfolioRepositoryError("Paper approval must be ACTIVE.")
        if approval.approval_decision is HumanApprovalDecision.REJECT_FOR_PAPER and approval.status is not HumanApprovalStatus.REJECTED:
            raise PaperPortfolioRepositoryError("Paper rejection must be REJECTED.")
        if approval.approval_decision is HumanApprovalDecision.REVOKE_PAPER_APPROVAL and approval.status is not HumanApprovalStatus.REVOKED:
            raise PaperPortfolioRepositoryError("Approval revocation must be REVOKED.")

        payload = self._json_dumps(asdict(approval))
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO approvals(approval_id, recommendation_id, decision, status, payload_json, created_timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.approval_id,
                    approval.recommendation_id,
                    approval.approval_decision.value,
                    approval.status.value,
                    payload,
                    approval.approval_timestamp,
                ),
            )

    def get_approvals(self) -> tuple[HumanApprovalRecord, ...]:
        rows = self.conn.execute("SELECT payload_json FROM approvals ORDER BY created_timestamp, approval_id").fetchall()
        values: list[HumanApprovalRecord] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            payload["approval_decision"] = HumanApprovalDecision(payload["approval_decision"])
            payload["status"] = HumanApprovalStatus(payload["status"])
            values.append(HumanApprovalRecord(**payload))
        return tuple(values)

    def save_transactions(self, transactions: Sequence[PaperTransaction], created_timestamp: str) -> None:
        with self.transaction() as conn:
            for tx in transactions:
                payload = self._json_dumps(asdict(tx))
                conn.execute(
                    """
                    INSERT INTO paper_transactions(transaction_id, recommendation_id, payload_json, created_timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (tx.transaction_id, tx.recommendation_id, payload, created_timestamp),
                )

    def get_transactions(self) -> tuple[PaperTransaction, ...]:
        rows = self.conn.execute("SELECT payload_json FROM paper_transactions ORDER BY created_timestamp, transaction_id").fetchall()
        return tuple(PaperTransaction(**json.loads(str(row["payload_json"]))) for row in rows)

    def save_positions(self, positions: Sequence[PositionRecord], updated_timestamp: str) -> None:
        with self.transaction() as conn:
            for position in positions:
                payload = self._json_dumps(asdict(position))
                conn.execute(
                    """
                    INSERT INTO paper_positions(ticker, payload_json, updated_timestamp)
                    VALUES (?, ?, ?)
                    ON CONFLICT(ticker)
                    DO UPDATE SET payload_json=excluded.payload_json, updated_timestamp=excluded.updated_timestamp
                    """,
                    (position.ticker, payload, updated_timestamp),
                )

    def get_positions(self) -> tuple[PositionRecord, ...]:
        rows = self.conn.execute("SELECT payload_json FROM paper_positions ORDER BY ticker").fetchall()
        return tuple(PositionRecord(**json.loads(str(row["payload_json"]))) for row in rows)

    def save_performance_snapshot(self, snapshot: PerformanceSnapshot, created_timestamp: str) -> None:
        payload = self._json_dumps(asdict(snapshot))
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO performance_snapshots(timestamp, payload_json, created_timestamp)
                VALUES (?, ?, ?)
                ON CONFLICT(timestamp)
                DO UPDATE SET payload_json=excluded.payload_json, created_timestamp=excluded.created_timestamp
                """,
                (snapshot.timestamp, payload, created_timestamp),
            )

    def get_performance_snapshots(self) -> tuple[PerformanceSnapshot, ...]:
        rows = self.conn.execute("SELECT payload_json FROM performance_snapshots ORDER BY timestamp").fetchall()
        return tuple(PerformanceSnapshot(**json.loads(str(row["payload_json"]))) for row in rows)

    def save_portfolio_state(self, state: PaperPortfolioState, created_timestamp: str) -> str:
        payload = self._json_dumps(asdict(state))
        state_hash = sha256(payload.encode("utf-8")).hexdigest()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_states(as_of_timestamp, state_hash, payload_json, created_timestamp)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(as_of_timestamp)
                DO UPDATE SET state_hash=excluded.state_hash, payload_json=excluded.payload_json, created_timestamp=excluded.created_timestamp
                """,
                (state.as_of_timestamp, state_hash, payload, created_timestamp),
            )
        return state_hash

    def get_latest_portfolio_state(self) -> PaperPortfolioState:
        row = self.conn.execute(
            "SELECT payload_json FROM portfolio_states ORDER BY as_of_timestamp DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise PaperPortfolioRepositoryError("No portfolio state persisted.")
        return PaperPortfolioState(**json.loads(str(row["payload_json"])))

    def get_latest_state_hash(self) -> str:
        row = self.conn.execute(
            "SELECT state_hash FROM portfolio_states ORDER BY as_of_timestamp DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise PaperPortfolioRepositoryError("No portfolio state hash persisted.")
        return str(row["state_hash"])

    def save_portfolio_audit(self, audit: PaperPortfolioAudit, created_timestamp: str) -> str:
        payload = self._json_dumps(asdict(audit))
        digest = sha256(payload.encode("utf-8")).hexdigest()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO portfolio_audits(audit_hash, payload_json, created_timestamp)
                VALUES (?, ?, ?)
                """,
                (digest, payload, created_timestamp),
            )
        return digest

    def get_audits(self) -> tuple[PaperPortfolioAudit, ...]:
        rows = self.conn.execute("SELECT payload_json FROM portfolio_audits ORDER BY created_timestamp, audit_hash").fetchall()
        return tuple(PaperPortfolioAudit(**json.loads(str(row["payload_json"]))) for row in rows)

    def save_checkpoint(self, checkpoint: ReplayCheckpoint) -> None:
        payload = self._json_dumps(asdict(checkpoint))
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO replay_checkpoints(sequence_number, state_hash, ledger_head_hash, payload_json, schema_version, created_timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sequence_number)
                DO UPDATE SET state_hash=excluded.state_hash, ledger_head_hash=excluded.ledger_head_hash, payload_json=excluded.payload_json, schema_version=excluded.schema_version, created_timestamp=excluded.created_timestamp
                """,
                (
                    checkpoint.sequence_number,
                    checkpoint.state_hash,
                    checkpoint.ledger_head_hash,
                    payload,
                    checkpoint.schema_version,
                    checkpoint.created_timestamp,
                ),
            )

    def get_checkpoints(self) -> tuple[ReplayCheckpoint, ...]:
        rows = self.conn.execute(
            "SELECT sequence_number, state_hash, ledger_head_hash, schema_version, created_timestamp, payload_json "
            "FROM replay_checkpoints ORDER BY sequence_number"
        ).fetchall()
        values: list[ReplayCheckpoint] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            payload["portfolio_state"] = PaperPortfolioState(**payload["portfolio_state"])
            payload["position_state"] = tuple(PositionRecord(**item) for item in payload["position_state"])
            payload["performance_state"] = PerformanceSnapshot(**payload["performance_state"])
            payload["sequence_number"] = int(row["sequence_number"])
            payload["state_hash"] = str(row["state_hash"])
            payload["ledger_head_hash"] = str(row["ledger_head_hash"])
            payload["schema_version"] = str(row["schema_version"])
            payload["created_timestamp"] = str(row["created_timestamp"])
            values.append(ReplayCheckpoint(**payload))
        return tuple(values)

    def save_tax_lots(self, tax_lots: Sequence[PaperTaxLot], updated_timestamp: str) -> None:
        with self.transaction() as conn:
            for lot in tax_lots:
                payload = self._json_dumps(asdict(lot))
                conn.execute(
                    """
                    INSERT INTO tax_lots(lot_id, ticker, payload_json, updated_timestamp)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(lot_id)
                    DO UPDATE SET ticker=excluded.ticker, payload_json=excluded.payload_json, updated_timestamp=excluded.updated_timestamp
                    """,
                    (lot.lot_id, lot.ticker, payload, updated_timestamp),
                )

    def get_tax_lots(self) -> tuple[PaperTaxLot, ...]:
        rows = self.conn.execute("SELECT payload_json FROM tax_lots ORDER BY ticker, lot_id").fetchall()
        values: list[PaperTaxLot] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            payload["status"] = TaxLotStatus(payload["status"])
            values.append(PaperTaxLot(**payload))
        return tuple(values)

    def save_corporate_action(self, action: CorporateActionRecord) -> None:
        payload = self._json_dumps(asdict(action))
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO corporate_actions(action_id, ticker, action_type, validated, payload_json, created_timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    action.action_id,
                    action.ticker,
                    action.action_type.value,
                    1 if action.validated else 0,
                    payload,
                    action.created_timestamp,
                ),
            )

    def ticker_has_unvalidated_corporate_action(self, ticker: str) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(1) AS cnt FROM corporate_actions WHERE ticker = ? AND validated = 0",
            (ticker,),
        ).fetchone()
        return bool(row and int(row["cnt"]) > 0)

    def load_bundle(self) -> PersistedBundle:
        return PersistedBundle(
            portfolio_state=self.get_latest_portfolio_state(),
            positions=self.get_positions(),
            transactions=self.get_transactions(),
            performance_history=self.get_performance_snapshots(),
            recommendations=self.get_recommendations(),
            approvals=self.get_approvals(),
            audits=self.get_audits(),
            checkpoints=self.get_checkpoints(),
            tax_lots=self.get_tax_lots(),
        )

    def run_atomic(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.transaction() as conn:
            return operation(conn)

    def _validate_transition(self, from_status: PaperRecommendationStatus, to_status: PaperRecommendationStatus) -> None:
        if to_status == from_status:
            return
        allowed = self.RECOMMENDATION_TRANSITIONS.get(from_status, ())
        if to_status not in allowed:
            raise InvalidLifecycleTransitionError(
                f"Invalid lifecycle transition: {from_status.value} -> {to_status.value}"
            )
