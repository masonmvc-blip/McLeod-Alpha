"""Canonical persistence service for live state and append-only events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
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
        columns = (
            "entry_time", "exit_time", "direction", "entry_price", "exit_price", "pnl",
            "exit_reason", "feature_payload", "option_symbol", "option_entry", "option_exit",
            "option_quantity", "option_delta", "option_return", "option_pnl_dollars",
            "option_pnl_pct", "broker_entry_order_id", "broker_exit_order_id",
            "momentum_freshness_score", "momentum_phase", "absorption_score",
            "entry_diagnostic_snapshot", "exit_diagnostic_snapshot",
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
        with sqlite3.connect(self.db_path) as connection:
            for broker_row in broker_rows or ():
                trade = dict(broker_row or {})
                entry_order_id = str(trade.get("broker_entry_order_id") or "")
                exit_order_id = str(trade.get("broker_exit_order_id") or "")
                if not entry_order_id and not exit_order_id:
                    continue
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
                inserted_trades.append(payload)
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

    def record_event(self, event: MemoryEvent) -> MemoryEvent:
        event = event.normalized()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
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
        event = self.record_event(MemoryEvent("latency", "latency_recorded", source, payload))
        if projection_path is not None:
            self._append_jsonl_projection(projection_path, payload)
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
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                """
                SELECT
                    date(entry_time) AS trade_date,
                    COALESCE(option_pnl_dollars, pnl, 0.0) AS pnl_dollars,
                    option_symbol,
                    broker_entry_order_id,
                    broker_exit_order_id
                FROM trade_log
                WHERE entry_time IS NOT NULL AND date(entry_time) IS NOT NULL
                ORDER BY date(entry_time), id
                """
            ).fetchall()]

    def load_trade_log_export_inputs(self, trade_date):
        self.initialize_live_trade_store()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            order_ids = {
                str(row["order_id"] or "").strip()
                for row in connection.execute("SELECT order_id FROM bot_order_audit").fetchall()
                if str(row["order_id"] or "").strip()
            }
            trades = [dict(row) for row in connection.execute(
                """
                SELECT
                    id, entry_time, exit_time, direction, exit_reason, option_symbol,
                    option_entry, option_exit, option_quantity, option_pnl_pct,
                    COALESCE(option_pnl_dollars, pnl, 0) AS dollar_pnl,
                    broker_entry_order_id, broker_exit_order_id, feature_payload,
                    entry_diagnostic_snapshot, exit_diagnostic_snapshot
                FROM trade_log
                WHERE substr(entry_time, 1, 10) = ?
                ORDER BY entry_time ASC
                """,
                (str(trade_date),),
            ).fetchall()]
        return order_ids, trades

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
        with sqlite3.connect(self.db_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(trade_log)")}
            pnl_column = "option_pnl_dollars" if "option_pnl_dollars" in columns else "pnl"
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(
                f"""
                SELECT id, entry_time, exit_time, direction, exit_reason,
                       COALESCE({pnl_column}, 0) AS pnl_value, option_symbol
                FROM trade_log
                WHERE substr(entry_time, 1, 10) = ?
                ORDER BY entry_time ASC
                """,
                (str(date_str),),
            ).fetchall()]
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
