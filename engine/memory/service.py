"""Canonical persistence service for live state and append-only events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "mcleod_alpha.db"
DEFAULT_POSITION_PATH = PROJECT_ROOT / "data" / "open_position.json"
DEFAULT_SIGNAL_PATH = PROJECT_ROOT / "logs" / "signals.csv"


@dataclass(frozen=True)
class MemoryEvent:
    category: str
    event_type: str
    source: str
    payload: dict[str, Any]
    correlation_id: str | None = None
    event_id: str = ""
    occurred_at: str = ""
    schema_version: int = 1

    def normalized(self) -> "MemoryEvent":
        return MemoryEvent(
            category=self.category,
            event_type=self.event_type,
            source=self.source,
            payload=self.payload,
            correlation_id=self.correlation_id,
            event_id=self.event_id or str(uuid4()),
            occurred_at=self.occurred_at or datetime.now(timezone.utc).isoformat(),
            schema_version=self.schema_version,
        )


class Memory:
    """The sole persistence boundary for Brain and execution code."""

    def __init__(self, db_path=None, position_path=None, signal_path=None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.position_path = Path(position_path or DEFAULT_POSITION_PATH)
        self.signal_path = Path(signal_path or DEFAULT_SIGNAL_PATH)

    def initialize_live_trade_store(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, entry_time TEXT, exit_time TEXT,
                    direction TEXT, entry_price REAL, exit_price REAL, pnl REAL,
                    exit_reason TEXT, feature_payload TEXT
                )
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(trade_log)")}
            for name, type_name in (
                ("option_symbol", "TEXT"), ("option_entry", "REAL"),
                ("option_exit", "REAL"), ("option_quantity", "INTEGER"),
                ("option_delta", "REAL"), ("option_return", "REAL"),
                ("option_pnl_dollars", "REAL"), ("option_pnl_pct", "REAL"),
                ("broker_entry_order_id", "TEXT"), ("broker_exit_order_id", "TEXT"),
                ("momentum_freshness_score", "REAL"), ("momentum_phase", "TEXT"),
                ("entry_diagnostic_snapshot", "TEXT"), ("exit_diagnostic_snapshot", "TEXT"),
                ("absorption_score", "REAL"),
                ("option_high_since_entry", "REAL"), ("option_low_since_entry", "REAL"),
                ("option_high_timestamp", "TEXT"), ("option_low_timestamp", "TEXT"),
                ("spy_price_at_option_high", "REAL"), ("spy_price_at_option_low", "REAL"),
                ("mfe_pct", "REAL"), ("mae_pct", "REAL"), ("exit_efficiency_pct", "REAL"),
                ("peak_capture_pct", "REAL"), ("profit_left_on_table_dollars", "REAL"),
                ("minutes_to_peak", "REAL"), ("minutes_after_peak_until_exit", "REAL"),
                ("entry_efficiency_pct", "REAL"), ("trade_quality_grade", "TEXT"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE trade_log ADD COLUMN {name} {type_name}")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS bot_order_audit (
                    order_id TEXT PRIMARY KEY, intent TEXT, created_at TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS trade_diagnostic_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_time TEXT, event_type TEXT,
                    direction TEXT, option_symbol TEXT, source TEXT, snapshot TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS canonical_completed_trades (
                    canonical_trade_id TEXT PRIMARY KEY,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    broker_entry_order_id TEXT,
                    broker_exit_order_id TEXT,
                    option_symbol TEXT,
                    source TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_completed_trades_date
                ON canonical_completed_trades (trade_date, entry_time)
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS canonical_completed_trade_versions (
                    canonical_trade_id TEXT NOT NULL,
                    canonical_version INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    source TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (canonical_trade_id, canonical_version),
                    UNIQUE (canonical_trade_id, payload_sha256)
                )
            """)
            legacy_canonical_rows = connection.execute(
                """
                SELECT canonical_trade_id, source, created_at, payload
                FROM canonical_completed_trades
                WHERE canonical_trade_id NOT IN (
                    SELECT canonical_trade_id FROM canonical_completed_trade_versions
                )
                """
            ).fetchall()
            for canonical_trade_id, source, created_at, raw_payload in legacy_canonical_rows:
                try:
                    payload = json.loads(raw_payload)
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                payload["canonical_trade_id"] = canonical_trade_id
                payload["canonical_version"] = 1
                payload["schema_version"] = "canonical-completed-trade.v2"
                serialized = json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)
                payload_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                connection.execute(
                    """
                    INSERT INTO canonical_completed_trade_versions (
                        canonical_trade_id, canonical_version, payload_sha256, source, recorded_at, payload
                    ) VALUES (?, 1, ?, ?, ?, ?)
                    """,
                    (canonical_trade_id, payload_sha256, source, created_at, serialized),
                )

    def record_order(self, order_id, intent):
        order_id = str(order_id or "").strip()
        if not order_id:
            return
        self.initialize_live_trade_store()
        created_at = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO bot_order_audit (order_id, intent, created_at) VALUES (?, ?, ?)",
                (order_id, str(intent or ""), created_at),
            )
        self.record_event(MemoryEvent(
            "execution", "broker_order_recorded", "execution",
            {"order_id": order_id, "intent": str(intent or ""), "created_at": created_at}, order_id,
        ))

    def record_diagnostic(self, event_type, direction, option_symbol=None, source=None, snapshot=None):
        self.initialize_live_trade_store()
        event_time = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("""
                INSERT INTO trade_diagnostic_events (
                    event_time, event_type, direction, option_symbol, source, snapshot
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (event_time, str(event_type or ""), str(direction or ""),
                  str(option_symbol or ""), str(source or ""), snapshot))
        self.record_event(MemoryEvent(
            "diagnostic", str(event_type or ""), str(source or "execution"),
            {"direction": str(direction or ""), "option_symbol": str(option_symbol or ""),
             "snapshot": snapshot, "event_time": event_time},
        ))

    def record_trade(self, **trade):
        self.initialize_live_trade_store()
        self.upsert_completed_trade(trade, source="live_execution")
        columns = (
            "entry_time", "exit_time", "direction", "entry_price", "exit_price", "pnl",
            "exit_reason", "feature_payload", "option_symbol", "option_entry", "option_exit",
            "option_quantity", "option_delta", "option_return", "option_pnl_dollars",
            "option_pnl_pct", "broker_entry_order_id", "broker_exit_order_id",
            "momentum_freshness_score", "momentum_phase", "absorption_score",
            "entry_diagnostic_snapshot", "exit_diagnostic_snapshot",
            "option_high_since_entry", "option_low_since_entry", "option_high_timestamp",
            "option_low_timestamp", "spy_price_at_option_high", "spy_price_at_option_low",
            "mfe_pct", "mae_pct", "exit_efficiency_pct", "peak_capture_pct",
            "profit_left_on_table_dollars", "minutes_to_peak", "minutes_after_peak_until_exit",
            "entry_efficiency_pct", "trade_quality_grade",
        )
        values = tuple(trade.get(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                f"INSERT INTO trade_log ({', '.join(columns)}) VALUES ({placeholders})", values
            )
        self.record_event(MemoryEvent(
            "trade", "trade_recorded", "execution", trade,
            str(trade.get("broker_exit_order_id") or trade.get("broker_entry_order_id") or "") or None,
        ))

    @staticmethod
    def _canonical_trade_id(trade: dict[str, Any]) -> str:
        entry_order_id = str(trade.get("broker_entry_order_id") or "")
        exit_order_id = str(trade.get("broker_exit_order_id") or "")
        if entry_order_id or exit_order_id:
            identity = "broker|{}|{}|{}".format(entry_order_id, exit_order_id, trade.get("option_symbol") or "")
        else:
            identity = "local|{}|{}|{}|{}".format(
                trade.get("entry_time") or "", trade.get("exit_time") or "",
                trade.get("option_symbol") or "", trade.get("direction") or "",
            )
        return "completed-trade:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _canonical_feature_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("feature_payload") or payload.get("entry_features") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {"raw_feature_payload": raw}
        features = dict(raw) if isinstance(raw, dict) else {}
        metadata = {
            "confidence_score": payload.get("confidence_score", payload.get("bot_confidence_score")),
            "checklist_score": payload.get("checklist_score"),
            "market_regime": payload.get("market_regime", features.get("market_regime")),
            "trend_maturity": payload.get("trend_maturity", features.get("trend_maturity", payload.get("momentum_phase"))),
            "signal_version": payload.get("signal_version", features.get("signal_version")),
            "model_version": payload.get("model_version", features.get("model_version")),
            "rule_version": payload.get("rule_version", features.get("rule_version")),
        }
        return {"all_features": features, "metadata": metadata}

    def upsert_completed_trade(self, trade: dict[str, Any], source="live_execution") -> dict[str, Any]:
        """Append an immutable version of the one canonical completed-trade object."""
        self.initialize_live_trade_store()
        payload = dict(trade or {})
        entry_time = str(payload.get("entry_time") or "")
        exit_time = str(payload.get("exit_time") or "")
        if not entry_time or not exit_time:
            raise ValueError("A completed trade requires entry_time and exit_time")
        canonical_trade_id = str(payload.get("canonical_trade_id") or self._canonical_trade_id(payload))
        now = datetime.now(timezone.utc).isoformat()
        payload["canonical_trade_id"] = canonical_trade_id
        payload["schema_version"] = "canonical-completed-trade.v2"
        payload["source"] = str(source)
        payload["feature_snapshot"] = self._canonical_feature_snapshot(payload)
        with sqlite3.connect(self.db_path) as connection:
            latest = connection.execute(
                "SELECT canonical_version, payload_sha256 FROM canonical_completed_trade_versions WHERE canonical_trade_id = ? ORDER BY canonical_version DESC LIMIT 1",
                (canonical_trade_id,),
            ).fetchone()
            fact_payload = dict(payload)
            fact_payload.pop("canonical_version", None)
            fact_sha256 = hashlib.sha256(
                json.dumps(fact_payload, default=str, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest()
            existing_version = connection.execute(
                "SELECT canonical_version FROM canonical_completed_trade_versions WHERE canonical_trade_id = ? AND payload_sha256 = ?",
                (canonical_trade_id, fact_sha256),
            ).fetchone()
            if existing_version is not None:
                payload["canonical_version"] = int(existing_version[0])
                return payload
            payload["canonical_version"] = int(latest[0] or 0) + 1 if latest else 1
            serialized = json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)
            payload_sha256 = fact_sha256
            if latest is not None and payload_sha256 == latest[1]:
                payload["canonical_version"] = int(latest[0])
                return payload
            connection.execute(
                """
                INSERT INTO canonical_completed_trades (
                    canonical_trade_id, entry_time, exit_time, trade_date,
                    broker_entry_order_id, broker_exit_order_id, option_symbol,
                    source, schema_version, payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_trade_id) DO NOTHING
                """,
                (
                    canonical_trade_id, entry_time, exit_time, entry_time[:10],
                    str(payload.get("broker_entry_order_id") or ""),
                    str(payload.get("broker_exit_order_id") or ""),
                    str(payload.get("option_symbol") or ""), str(source),
                    payload["schema_version"], serialized, now, now,
                ),
            )
            connection.execute(
                """
                INSERT INTO canonical_completed_trade_versions (
                    canonical_trade_id, canonical_version, payload_sha256, source, recorded_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (canonical_trade_id, payload["canonical_version"], payload_sha256, str(source), now, serialized),
            )
        self.record_event(MemoryEvent(
            "trade", "canonical_completed_trade_upserted", str(source), payload, canonical_trade_id,
        ))
        return payload

    def load_completed_trades(self, start_date: str, end_date: str | None = None) -> list[dict[str, Any]]:
        """Load canonical completed-trade objects; downstream consumers must use this API."""
        self.initialize_live_trade_store()
        end_date = str(end_date or start_date)
        self._backfill_legacy_completed_trades(str(start_date), end_date)
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT trade.canonical_trade_id, trade.entry_time, version.canonical_version, version.payload
                FROM canonical_completed_trades AS trade
                JOIN canonical_completed_trade_versions AS version
                    ON version.canonical_trade_id = trade.canonical_trade_id
                WHERE trade.trade_date BETWEEN ? AND ?
                ORDER BY trade.entry_time ASC, trade.canonical_trade_id ASC, version.canonical_version ASC
                """,
                (str(start_date), end_date),
            ).fetchall()
        selected = {}
        for canonical_trade_id, entry_time, canonical_version, raw_payload in rows:
            payload = json.loads(raw_payload)
            existing = selected.get(canonical_trade_id)
            is_broker_cash = str(payload.get("pnl_source") or "").lower() == "broker_cash"
            existing_is_broker_cash = bool(existing and str(existing.get("pnl_source") or "").lower() == "broker_cash")
            if existing is None or (is_broker_cash and not existing_is_broker_cash) or (
                is_broker_cash == existing_is_broker_cash
                and int(canonical_version) > int(existing.get("canonical_version") or 0)
            ):
                selected[canonical_trade_id] = payload
        return sorted(selected.values(), key=lambda trade: (str(trade.get("entry_time") or ""), str(trade.get("canonical_trade_id") or "")))

    def load_completed_trades_for_date(self, trade_date: str) -> list[dict[str, Any]]:
        return self.load_completed_trades(trade_date)

    def load_trade_reconciliation_metrics(self, trade_date: str, broker_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Return count parity for broker facts and every canonical trade projection."""
        canonical = self.load_completed_trades_for_date(trade_date)
        canonical_ids = {str(trade.get("canonical_trade_id") or "") for trade in canonical}
        broker_rows = list(broker_rows or [])
        broker_ids = {self._canonical_trade_id(dict(row)) for row in broker_rows}
        canonical_pnl = sum(float(trade.get("option_pnl_dollars", trade.get("pnl", 0.0)) or 0.0) for trade in canonical)
        broker_pnl = sum(float(row.get("option_pnl_dollars", row.get("pnl", 0.0)) or 0.0) for row in broker_rows)
        pnl_variance = canonical_pnl - broker_pnl
        root = self.db_path.parent.parent
        export_path = root / "data" / "reports" / "trade_logs" / f"daily_trade_review_data_{trade_date}.json"
        try:
            export_rows = list((json.loads(export_path.read_text(encoding="utf-8")) or {}).get("trades") or [])
        except (OSError, json.JSONDecodeError):
            export_rows = []
        review_ids = {str(row.get("trade_id") or "") for row in export_rows}
        replay_dir = root / "data" / "spy_bot_reviewer" / "replays"
        replay_ready_ids = {
            trade_id for trade_id in canonical_ids
            if (replay_dir / f"{''.join(char for char in trade_id if char.isalnum() or char in '-_')}.json").exists()
        }
        outbox_path = root / "data" / "reports" / "trade_ledger_outbox.jsonl"
        latest_outbox: dict[str, str] = {}
        try:
            for line in outbox_path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("key"):
                    latest_outbox[str(event["key"])] = str(event.get("event") or "")
        except (OSError, json.JSONDecodeError):
            pass
        pending_outbox = sum(1 for event_type in latest_outbox.values() if event_type == "pending")
        unreconciled = broker_ids - canonical_ids
        extra_canonical = canonical_ids - broker_ids
        count_reconciled = canonical_ids == broker_ids
        pnl_reconciled = abs(pnl_variance) <= 0.01
        return {
            "trading_date": trade_date,
            "broker_trades_today": len(broker_ids),
            "canonical_completed_trades": len(canonical_ids),
            "broker_pnl_dollars": round(broker_pnl, 2),
            "canonical_pnl_dollars": round(canonical_pnl, 2),
            "pnl_variance_dollars": round(pnl_variance, 2),
            "count_reconciled": count_reconciled,
            "pnl_reconciled": pnl_reconciled,
            "review_export_trades": len(review_ids),
            "replay_ready_trades": len(replay_ready_ids),
            "unreconciled_trades": len(unreconciled),
            "extra_canonical_trades": len(extra_canonical),
            "pending_outbox_entries": pending_outbox,
            "unreconciled_trade_ids": sorted(unreconciled),
            "extra_canonical_trade_ids": sorted(extra_canonical),
            "healthy": count_reconciled and pnl_reconciled and pending_outbox == 0,
        }

    def _backfill_legacy_completed_trades(self, start_date: str, end_date: str) -> None:
        """Compatibility migration for completed rows written before canonical-trade.v1."""
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(
                """
                SELECT * FROM trade_log
                WHERE exit_time IS NOT NULL AND TRIM(exit_time) <> ''
                  AND substr(entry_time, 1, 10) BETWEEN ? AND ?
                """,
                (start_date, end_date),
            ).fetchall()]
        for row in rows:
            canonical_trade_id = self._canonical_trade_id(row)
            with sqlite3.connect(self.db_path) as connection:
                existing = connection.execute(
                    """
                    SELECT payload
                    FROM canonical_completed_trade_versions
                    WHERE canonical_trade_id = ?
                    ORDER BY canonical_version DESC
                    LIMIT 1
                    """,
                    (canonical_trade_id,),
                ).fetchone()
            if existing is not None:
                try:
                    existing_payload = json.loads(existing[0])
                    if str(existing_payload.get("pnl_source") or "").lower() == "broker_cash":
                        continue
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            self.upsert_completed_trade(row, source="legacy_trade_log_backfill")

    def reconcile_broker_trades(self, broker_rows, source="broker_reconciliation"):
        """Idempotently persist broker-paired trades and emit one event per inserted row."""
        self.initialize_live_trade_store()
        inserted_trades = []
        columns = (
            "entry_time", "exit_time", "direction", "entry_price", "exit_price", "pnl",
            "exit_reason", "option_symbol", "option_entry", "option_exit", "option_quantity",
            "option_pnl_dollars", "option_return", "option_pnl_pct", "broker_entry_order_id",
            "broker_exit_order_id", "feature_payload", "entry_diagnostic_snapshot",
            "exit_diagnostic_snapshot",
        )
        for broker_row in broker_rows or ():
            trade = dict(broker_row or {})
            entry_order_id = str(trade.get("broker_entry_order_id") or "")
            exit_order_id = str(trade.get("broker_exit_order_id") or "")
            if not entry_order_id and not exit_order_id:
                continue
            canonical = self.upsert_completed_trade(trade, source=source)
            with sqlite3.connect(self.db_path) as connection:
                exists = connection.execute(
                    """
                    SELECT 1 FROM trade_log
                    WHERE COALESCE(broker_entry_order_id, '') = ?
                      AND COALESCE(broker_exit_order_id, '') = ?
                    LIMIT 1
                    """,
                    (entry_order_id, exit_order_id),
                ).fetchone()
            if exists is not None:
                continue
            with sqlite3.connect(self.db_path) as connection:
                payload = {
                    "entry_time": trade.get("entry_time"),
                    "exit_time": trade.get("exit_time"),
                    "direction": trade.get("direction"),
                    "entry_price": trade.get("entry_price"),
                    "exit_price": trade.get("exit_price"),
                    "pnl": trade.get("pnl"),
                    "exit_reason": trade.get("exit_reason"),
                    "option_symbol": trade.get("option_symbol"),
                    "option_entry": trade.get("option_entry"),
                    "option_exit": trade.get("option_exit"),
                    "option_quantity": trade.get("option_quantity"),
                    "option_pnl_dollars": trade.get("pnl"),
                    "option_return": None,
                    "option_pnl_pct": None,
                    "broker_entry_order_id": entry_order_id,
                    "broker_exit_order_id": exit_order_id,
                    "feature_payload": None,
                    "entry_diagnostic_snapshot": None,
                    "exit_diagnostic_snapshot": None,
                }
                connection.execute(
                    f"INSERT INTO trade_log ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(payload[column] for column in columns),
                )
            inserted_trades.append(canonical)
        for trade in inserted_trades:
            correlation_id = "broker-trade:{}:{}".format(
                trade["broker_entry_order_id"] or "-", trade["broker_exit_order_id"] or "-",
            )
            self.record_event(MemoryEvent(
                "trade",
                "broker_trade_reconciled",
                source,
                {"schema_version": "broker-trade-reconciliation.v1", "trade": trade},
                correlation_id,
            ))
        return len(inserted_trades)

    def record_event(self, event: MemoryEvent, *, timeout_seconds: float = 5.0) -> MemoryEvent:
        event = event.normalized()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path, timeout=max(0.0, float(timeout_seconds))) as connection:
            connection.execute(f"PRAGMA busy_timeout={max(0, int(float(timeout_seconds) * 1000))}")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    correlation_id TEXT,
                    schema_version INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO memory_events (
                    event_id, occurred_at, category, event_type, source,
                    correlation_id, schema_version, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.occurred_at,
                    event.category,
                    event.event_type,
                    event.source,
                    event.correlation_id,
                    event.schema_version,
                    json.dumps(event.payload, default=str, separators=(",", ":")),
                ),
            )
        return event

    def record_feature_vector(self, payload, source="brain", correlation_id=None):
        """Persist one versioned feature vector and its append-only Memory event."""
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError("Feature vector payload must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Feature vector payload must be a JSON object")

        vector = dict(payload)
        schema_version = str(vector.pop("schema_version", "entry-feature-vector.v1"))
        correlation = str(correlation_id or vector.get("correlation_id") or uuid4())
        vector_id = f"feature-vector:{correlation}"
        recorded_at = datetime.now(timezone.utc).isoformat()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_vectors (
                    feature_vector_id TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    correlation_id TEXT UNIQUE NOT NULL,
                    schema_version TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO feature_vectors (
                    feature_vector_id, recorded_at, source, correlation_id, schema_version, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    vector_id,
                    recorded_at,
                    str(source or "brain"),
                    correlation,
                    schema_version,
                    json.dumps(vector, default=str, separators=(",", ":")),
                ),
            ).rowcount
        if not inserted:
            return MemoryEvent(
                "feature_vector", "feature_vector_recorded", str(source or "brain"), vector,
                correlation, vector_id, recorded_at, 1,
            )
        return self.record_event(MemoryEvent(
            "feature_vector", "feature_vector_recorded", str(source or "brain"),
            {"schema_version": schema_version, "vector": vector}, correlation, vector_id,
        ))

    def record_latency(self, payload, projection_path=None, source="monitor"):
        if projection_path is not None:
            self._append_jsonl_projection(projection_path, payload)
        event = MemoryEvent("latency", "latency_recorded", source, payload).normalized()
        try:
            return self.record_event(event, timeout_seconds=0.05)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            return event

    def record_decision(self, payload, projection_path=None, source="brain", correlation_id=None):
        event = self.record_event(MemoryEvent("decision", "decision_recorded", source, payload, correlation_id))
        if projection_path is not None:
            self._append_jsonl_projection(projection_path, payload)
        return event

    def record_experiment(self, payload, source="research", correlation_id=None):
        return self.record_event(MemoryEvent("experiment", "experiment_recorded", source, payload, correlation_id))

    def write_experiment_text(self, projection_path, content, artifact_type, source="research", correlation_id=None):
        path = Path(projection_path)
        self._write_text_projection(path, str(content))
        return self._record_experiment_projection(path, artifact_type, "text", source, correlation_id)

    def append_experiment_line(self, projection_path, line, artifact_type, source="research", correlation_id=None):
        path = Path(projection_path)
        content = self.read_experiment_text(path, encoding="utf-8") + str(line).rstrip("\n") + "\n"
        self._write_text_projection(path, content)
        return self._record_experiment_projection(path, artifact_type, "append", source, correlation_id)

    def read_experiment_text(self, projection_path, default="", **kwargs):
        path = Path(projection_path)
        if not path.exists():
            return default
        try:
            return path.read_text(**kwargs)
        except Exception:
            return default

    def read_experiment_bytes(self, projection_path, default=b""):
        path = Path(projection_path)
        if not path.exists():
            return default
        try:
            return path.read_bytes()
        except Exception:
            return default

    def experiment_projection_exists(self, projection_path):
        return Path(projection_path).exists()

    def record_report(self, payload, source="reporting", correlation_id=None):
        return self.record_event(MemoryEvent("report", "report_recorded", source, payload, correlation_id))

    def write_report_text(self, projection_path, content, report_type, source="reporting", correlation_id=None):
        path = Path(projection_path)
        self._write_text_projection(path, str(content))
        return self._record_report_projection(path, report_type, "text", source, correlation_id)

    def write_report_json(self, projection_path, payload, report_type, source="reporting", correlation_id=None):
        path = Path(projection_path)
        self._write_json_projection(path, payload)
        return self._record_report_projection(path, report_type, "json", source, correlation_id)

    def write_report_csv(self, projection_path, fieldnames, rows, report_type, source="reporting", correlation_id=None):
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(path)
        return self._record_report_projection(path, report_type, "csv", source, correlation_id)

    def append_report_line(self, projection_path, line, report_type, source="reporting", correlation_id=None):
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(str(line).rstrip("\n") + "\n")
        return self._record_report_projection(path, report_type, "append", source, correlation_id)

    def open_runtime_log(self, projection_path, mode="a", encoding="utf-8", buffering=1):
        """Open a compatibility runtime log while keeping its projection owned by Memory."""
        if mode not in {"a", "w"}:
            raise ValueError("Runtime logs support append or truncate mode only")
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open(mode, encoding=encoding, buffering=buffering)

    def write_runtime_artifact(self, projection_path, content, artifact_type, source="cockpit"):
        """Atomically write a runtime compatibility projection and record its ownership event."""
        path = Path(projection_path)
        self._write_text_projection(path, str(content))
        return self.record_event(MemoryEvent(
            "runtime", "runtime_artifact_written", source,
            {"artifact_type": str(artifact_type), "projection_path": str(path)},
        ))

    def clear_runtime_artifact(self, projection_path, artifact_type, source="cockpit"):
        """Remove a stale runtime compatibility projection and record its ownership event."""
        path = Path(projection_path)
        path.unlink(missing_ok=True)
        return self.record_event(MemoryEvent(
            "runtime", "runtime_artifact_cleared", source,
            {"artifact_type": str(artifact_type), "projection_path": str(path)},
        ))

    def load_decision_audit_event(self, projection_path, candle_time):
        """Read the latest decision-audit event matching a closed candle minute."""
        path = Path(projection_path)
        target_time = self._parse_projection_timestamp(candle_time)
        if target_time is None or not path.exists():
            return None
        try:
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError):
            return None
        target_minute = target_time.astimezone(timezone.utc).replace(second=0, microsecond=0)
        for event in reversed(events):
            event_time = self._parse_projection_timestamp(event.get("candle_time"))
            if event_time is not None and event_time.astimezone(timezone.utc).replace(second=0, microsecond=0) == target_minute:
                return event
        return None

    @staticmethod
    def _parse_projection_timestamp(value):
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def read_report_bytes(self, projection_path):
        return Path(projection_path).read_bytes()

    def read_report_text(self, projection_path, default="", **kwargs):
        path = Path(projection_path)
        if not path.exists():
            return default
        try:
            return path.read_text(**kwargs)
        except Exception:
            return default

    def load_broker_daily_pnl_rows(self):
        self.initialize_live_trade_store()
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute("SELECT payload FROM canonical_completed_trades ORDER BY entry_time, canonical_trade_id").fetchall()
        return [{
            "trade_date": str(trade.get("entry_time") or "")[:10],
            "pnl_dollars": trade.get("option_pnl_dollars", trade.get("pnl", 0.0)),
            "option_symbol": trade.get("option_symbol"),
            "broker_entry_order_id": trade.get("broker_entry_order_id"),
            "broker_exit_order_id": trade.get("broker_exit_order_id"),
        } for (payload,) in rows for trade in [json.loads(payload)]]

    def load_trade_log_status_summary(self, db_path=None):
        """Return the small read-only trade-log summary needed by runtime status."""
        target_db_path = Path(db_path or self.db_path)
        if not target_db_path.exists():
            return None
        try:
            with sqlite3.connect(target_db_path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(trade_log)")}
                row = connection.execute(
                    """
                    SELECT COUNT(1) AS closed_count, MAX(exit_time) AS max_exit_time
                    FROM trade_log
                    WHERE exit_time IS NOT NULL AND TRIM(exit_time) <> ''
                    """
                ).fetchone()
        except sqlite3.Error:
            return None

        closed_count = int(row[0] or 0) if row else 0
        max_exit_time = str(row[1] or "none") if row else "none"
        return {
            "closed_trade_signature": f"{closed_count}:{max_exit_time}",
            "has_absorption_score": "absorption_score" in columns,
        }

    def load_trade_log_export_inputs(self, trade_date):
        self.initialize_live_trade_store()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            order_ids = {
                str(row["order_id"] or "").strip()
                for row in connection.execute("SELECT order_id FROM bot_order_audit").fetchall()
                if str(row["order_id"] or "").strip()
            }
            payload_rows = connection.execute(
                "SELECT payload FROM canonical_completed_trades WHERE trade_date = ? ORDER BY entry_time, canonical_trade_id",
                (str(trade_date),),
            ).fetchall()
            trades = []
            for (payload,) in payload_rows:
                trade = json.loads(payload)
                trade["id"] = trade.get("canonical_trade_id")
                trade["dollar_pnl"] = trade.get("option_pnl_dollars", trade.get("pnl", 0))
                trades.append(trade)
        return order_ids, trades

    def load_exit_quality_export_inputs(self, start_date, end_date):
        """Read completed trade quality fields for a reporting period."""
        trades = self.load_completed_trades(str(start_date), str(end_date))
        return [dict(trade, id=trade.get("canonical_trade_id"), dollar_pnl=trade.get("option_pnl_dollars", trade.get("pnl", 0))) for trade in trades]

    def _record_report_projection(self, path, report_type, format_name, source, correlation_id):
        return self.record_report(
            {
                "schema_version": "report-artifact.v1",
                "report_type": str(report_type),
                "format": str(format_name),
                "projection_path": str(path),
            },
            source=source,
            correlation_id=correlation_id,
        )

    def _record_experiment_projection(self, path, artifact_type, format_name, source, correlation_id):
        return self.record_experiment(
            {
                "schema_version": "experiment-artifact.v1",
                "artifact_type": str(artifact_type),
                "format": str(format_name),
                "projection_path": str(path),
            },
            source=source,
            correlation_id=correlation_id,
        )

    def record_performance(self, payload, source="performance", correlation_id=None):
        return self.record_event(MemoryEvent("performance", "performance_recorded", source, payload, correlation_id))

    def load_daily_trade_performance(self, date_str):
        """Return the Memory-owned trade performance snapshot for one trading date."""
        self.initialize_live_trade_store()
        rows = [
            {
                "id": trade.get("canonical_trade_id"), "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"), "direction": trade.get("direction"),
                "exit_reason": trade.get("exit_reason"), "option_symbol": trade.get("option_symbol"),
                "pnl_value": trade.get("option_pnl_dollars", trade.get("pnl", 0)),
            }
            for trade in self.load_completed_trades_for_date(str(date_str))
        ]
        pnl_values = [float(row.get("pnl_value") or 0.0) for row in rows]
        return {
            "date": str(date_str),
            "trades": len(rows),
            "wins": sum(1 for value in pnl_values if value > 0),
            "losses": sum(1 for value in pnl_values if value < 0),
            "net_pnl": float(sum(pnl_values)),
            "rows": rows,
        }

    def record_daily_performance(self, snapshot, source="daily_pnl_email"):
        if not isinstance(snapshot, dict):
            raise ValueError("Daily performance snapshot must be a JSON object")
        date_str = str(snapshot.get("date") or "").strip()
        if not date_str:
            raise ValueError("Daily performance snapshot requires a date")
        payload = {
            "schema_version": "daily-performance.v1",
            "snapshot": dict(snapshot),
        }
        return self.record_performance(payload, source=source, correlation_id=f"daily-performance:{date_str}")

    def record_optimization(self, payload, source="optimizer", correlation_id=None):
        return self.record_event(MemoryEvent("optimization", "optimization_recorded", source, payload, correlation_id))

    def read_optimization_csv(self, projection_path):
        text = self.read_optimization_text(projection_path, encoding="utf-8")
        return list(csv.DictReader(text.splitlines())) if text else []

    def write_optimization_csv(self, projection_path, fieldnames, rows, artifact_type, source="optimizer", correlation_id=None):
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(path)
        return self._record_optimization_projection(path, artifact_type, "csv", source, correlation_id)

    def write_optimization_text(self, projection_path, content, artifact_type, source="optimizer", correlation_id=None):
        path = Path(projection_path)
        self._write_text_projection(path, str(content))
        return self._record_optimization_projection(path, artifact_type, "text", source, correlation_id)

    def read_optimization_text(self, projection_path, default="", **kwargs):
        path = Path(projection_path)
        if not path.exists():
            return default
        try:
            return path.read_text(**kwargs)
        except Exception:
            return default

    def record_version(self, payload, source="system", correlation_id=None):
        return self.record_event(MemoryEvent("version", "version_recorded", source, payload, correlation_id))

    def save_setting(self, name, value, projection_path=None, source="cockpit"):
        payload = {"name": str(name), "value": value}
        event = self.record_event(MemoryEvent("setting", "setting_saved", source, payload, str(name)))
        if projection_path is not None:
            self._write_json_projection(projection_path, value)
        return event

    def load_setting(self, projection_path, default=None):
        return self._read_json_projection(projection_path, default)

    def setting_projection_revision(self, projection_path):
        path = Path(projection_path)
        if not path.exists():
            return None
        return path.stat().st_mtime_ns

    def clear_setting(self, name, projection_path=None, source="cockpit"):
        event = self.record_event(MemoryEvent(
            "setting", "setting_cleared", source, {"name": str(name)}, str(name),
        ))
        if projection_path is not None:
            Path(projection_path).unlink(missing_ok=True)
        return event

    def save_csv_projection(self, projection_path, frame):
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)

    def load_csv_projection(self, projection_path):
        import pandas as pd

        return pd.read_csv(Path(projection_path))

    def _append_jsonl_projection(self, projection_path, payload):
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")

    def _write_json_projection(self, projection_path, value):
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
        temp_path.replace(path)

    def _write_text_projection(self, projection_path, content):
        path = Path(projection_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(str(content), encoding="utf-8")
        temp_path.replace(path)

    def _read_json_projection(self, projection_path, default=None):
        path = Path(projection_path)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def save_position(self, position):
        payload = self._position_payload(position)
        self.position_path.parent.mkdir(parents=True, exist_ok=True)
        self.position_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.record_event(MemoryEvent("position", "position_saved", "execution", payload))

    def load_position(self, position_type):
        if not self.position_path.exists():
            return None
        payload = json.loads(self.position_path.read_text(encoding="utf-8"))
        option_symbol = str(payload.get("option_symbol") or "").upper()
        if "TEST" in option_symbol:
            self.clear_position()
            return None
        payload["opened"] = datetime.fromisoformat(payload["opened"])
        position = position_type(**{key: payload[key] for key in self._position_constructor_fields()})
        for key, default in self._position_extra_fields().items():
            setattr(position, key, payload.get(key, default))
        return position

    def clear_position(self):
        if self.position_path.exists():
            self.position_path.unlink()
        self.record_event(MemoryEvent("position", "position_cleared", "execution", {}))

    def record_signal(self, price, regime, call_score, put_score, feature_payload=None):
        self.signal_path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.signal_path.exists()
        with self.signal_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if not exists:
                writer.writerow(["timestamp", "price", "regime", "call_score", "put_score", "feature_payload"])
            writer.writerow([
                datetime.now().isoformat(), price, regime, call_score, put_score,
                json.dumps(feature_payload) if feature_payload is not None else "",
            ])
        self.record_event(MemoryEvent(
            "signal", "signal_recorded", "brain",
            {"price": price, "regime": regime, "call_score": call_score,
             "put_score": put_score, "feature_payload": feature_payload},
        ))

    @staticmethod
    def _position_constructor_fields():
        return (
            "direction", "entry_price", "stop_price", "target_price", "quantity",
            "opened", "reason", "option_symbol", "option_entry", "option_delta",
        )

    def _record_optimization_projection(self, path, artifact_type, format_name, source, correlation_id):
        return self.record_optimization(
            {
                "schema_version": "optimization-artifact.v1",
                "artifact_type": str(artifact_type),
                "format": str(format_name),
                "projection_path": str(path),
            },
            source=source,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _position_extra_fields():
        return {
            "feature_payload": "", "option_stop": 0, "option_initial_stop": 0,
            "active_stop_reason": "STOP", "schwab_order_id": "",
            "schwab_fill_price": 0.0, "schwab_fill_timestamp": "",
            "submitted_limit_price": 0.0, "protective_stop_order_id": "",
            "protective_stop_price": 0.0, "protective_stop_status": "",
        }

    @classmethod
    def _position_payload(cls, position):
        payload = {key: getattr(position, key) for key in cls._position_constructor_fields()}
        payload["opened"] = payload["opened"].isoformat()
        payload.update({key: getattr(position, key, default) for key, default in cls._position_extra_fields().items()})
        return payload


_MEMORY = Memory()


def get_memory() -> Memory:
    return _MEMORY
