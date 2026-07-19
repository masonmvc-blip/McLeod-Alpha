from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .repository import PaperPortfolioRepository, PaperPortfolioRepositoryError
from .types import PaperEventType, PaperPortfolioEvent


class PaperLedgerValidationError(ValueError):
    pass


class PaperPortfolioLedger:
    ALLOWED_PAYLOAD_VERSIONS = {"1.0"}

    def __init__(self, repository: PaperPortfolioRepository) -> None:
        self.repository = repository

    def append_event(
        self,
        *,
        event_type: PaperEventType,
        event_timestamp: str,
        effective_timestamp: str,
        aggregate_id: str,
        payload_version: str,
        payload: Mapping[str, Any],
        source_audit_references: Mapping[str, str],
        provenance: Mapping[str, Any],
        created_timestamp: str,
        recommendation_id: str | None = None,
        transaction_id: str | None = None,
    ) -> PaperPortfolioEvent:
        self._validate_append_contract(
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload_version=payload_version,
            payload=payload,
        )
        sequence_number, previous_event_hash = self.repository.next_event_sequence_and_previous_hash()
        payload_json = self._canonical_json(payload)
        payload_hash = self._hash(payload_json)
        event_id = self._event_id(
            event_type=event_type,
            sequence_number=sequence_number,
            aggregate_id=aggregate_id,
            recommendation_id=recommendation_id,
            transaction_id=transaction_id,
            effective_timestamp=effective_timestamp,
            payload_hash=payload_hash,
        )
        event_hash = self._event_hash(
            event_id=event_id,
            event_type=event_type,
            sequence_number=sequence_number,
            event_timestamp=event_timestamp,
            effective_timestamp=effective_timestamp,
            aggregate_id=aggregate_id,
            recommendation_id=recommendation_id,
            transaction_id=transaction_id,
            payload_version=payload_version,
            payload_hash=payload_hash,
            previous_event_hash=previous_event_hash,
            source_audit_references=source_audit_references,
            provenance=provenance,
            created_timestamp=created_timestamp,
        )
        event = PaperPortfolioEvent(
            event_id=event_id,
            event_type=event_type,
            sequence_number=sequence_number,
            event_timestamp=event_timestamp,
            effective_timestamp=effective_timestamp,
            aggregate_id=aggregate_id,
            recommendation_id=recommendation_id,
            transaction_id=transaction_id,
            payload_version=payload_version,
            payload=dict(payload),
            previous_event_hash=previous_event_hash,
            event_hash=event_hash,
            source_audit_references=dict(source_audit_references),
            provenance=dict(provenance),
            created_timestamp=created_timestamp,
        )
        row = {
            "sequence_number": event.sequence_number,
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "event_timestamp": event.event_timestamp,
            "effective_timestamp": event.effective_timestamp,
            "aggregate_id": event.aggregate_id,
            "recommendation_id": event.recommendation_id,
            "transaction_id": event.transaction_id,
            "payload_version": event.payload_version,
            "payload_json": payload_json,
            "payload_hash": payload_hash,
            "duplicate_fingerprint": self._duplicate_fingerprint(
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                recommendation_id=event.recommendation_id,
                transaction_id=event.transaction_id,
                effective_timestamp=event.effective_timestamp,
                payload_hash=payload_hash,
            ),
            "previous_event_hash": event.previous_event_hash,
            "event_hash": event.event_hash,
            "source_audit_references_json": self._canonical_json(event.source_audit_references),
            "provenance_json": self._canonical_json(event.provenance),
            "created_timestamp": event.created_timestamp,
        }
        try:
            self.repository.persist_event_row(row)
        except Exception as exc:
            raise PaperLedgerValidationError(f"Event append rejected: {exc}") from exc
        return event

    def read_events(self) -> tuple[PaperPortfolioEvent, ...]:
        rows = self.repository.list_event_rows()
        events: list[PaperPortfolioEvent] = []
        for row in rows:
            events.append(
                PaperPortfolioEvent(
                    event_id=str(row["event_id"]),
                    event_type=PaperEventType(str(row["event_type"])),
                    sequence_number=int(row["sequence_number"]),
                    event_timestamp=str(row["event_timestamp"]),
                    effective_timestamp=str(row["effective_timestamp"]),
                    aggregate_id=str(row["aggregate_id"]),
                    recommendation_id=row.get("recommendation_id"),
                    transaction_id=row.get("transaction_id"),
                    payload_version=str(row["payload_version"]),
                    payload=json.loads(str(row["payload_json"])),
                    previous_event_hash=str(row["previous_event_hash"]),
                    event_hash=str(row["event_hash"]),
                    source_audit_references=json.loads(str(row["source_audit_references_json"])),
                    provenance=json.loads(str(row["provenance_json"])),
                    created_timestamp=str(row["created_timestamp"]),
                )
            )
        return tuple(events)

    def validate_hash_chain(self) -> None:
        events = self.read_events()
        expected_sequence = 1
        previous_hash = "GENESIS"
        seen_ids: set[str] = set()
        seen_hashes: set[str] = set()
        for event in events:
            if event.sequence_number != expected_sequence:
                raise PaperLedgerValidationError("Missing sequence detected in ledger.")
            if event.event_id in seen_ids:
                raise PaperLedgerValidationError("Duplicate event id detected in ledger.")
            if event.event_hash in seen_hashes:
                raise PaperLedgerValidationError("Duplicate event hash detected in ledger.")
            if event.previous_event_hash != previous_hash:
                raise PaperLedgerValidationError("Ledger hash chain break detected.")
            recomputed = self._event_hash(
                event_id=event.event_id,
                event_type=event.event_type,
                sequence_number=event.sequence_number,
                event_timestamp=event.event_timestamp,
                effective_timestamp=event.effective_timestamp,
                aggregate_id=event.aggregate_id,
                recommendation_id=event.recommendation_id,
                transaction_id=event.transaction_id,
                payload_version=event.payload_version,
                payload_hash=self._hash(self._canonical_json(event.payload)),
                previous_event_hash=event.previous_event_hash,
                source_audit_references=event.source_audit_references,
                provenance=event.provenance,
                created_timestamp=event.created_timestamp,
            )
            if recomputed != event.event_hash:
                raise PaperLedgerValidationError("Corrupted event hash detected.")
            self._validate_append_contract(
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                payload_version=event.payload_version,
                payload=event.payload,
            )
            expected_sequence += 1
            previous_hash = event.event_hash
            seen_ids.add(event.event_id)
            seen_hashes.add(event.event_hash)

    def verify_integrity(self) -> str:
        self.repository.validate_schema_version("1.0")
        self.validate_hash_chain()
        events = self.read_events()
        if not events:
            return "GENESIS"
        return events[-1].event_hash

    def export_ledger(self) -> Mapping[str, Any]:
        events = [asdict(event) for event in self.read_events()]
        for event in events:
            event["event_type"] = event["event_type"].value
        return {
            "schema_version": "1.0",
            "head_hash": self.verify_integrity(),
            "events": events,
        }

    def import_ledger(self, exported: Mapping[str, Any]) -> None:
        if str(exported.get("schema_version")) != "1.0":
            raise PaperLedgerValidationError("Schema mismatch during ledger import.")
        events = exported.get("events")
        if not isinstance(events, list):
            raise PaperLedgerValidationError("Invalid export format: events must be a list.")

        for raw in events:
            if not isinstance(raw, Mapping):
                raise PaperLedgerValidationError("Invalid event export record.")
            current_seq, _ = self.repository.next_event_sequence_and_previous_hash()
            if int(raw.get("sequence_number")) != current_seq:
                raise PaperLedgerValidationError("Sequence mismatch during ledger import.")
            row = {
                "sequence_number": int(raw["sequence_number"]),
                "event_id": str(raw["event_id"]),
                "event_type": str(raw["event_type"]),
                "event_timestamp": str(raw["event_timestamp"]),
                "effective_timestamp": str(raw["effective_timestamp"]),
                "aggregate_id": str(raw["aggregate_id"]),
                "recommendation_id": raw.get("recommendation_id"),
                "transaction_id": raw.get("transaction_id"),
                "payload_version": str(raw["payload_version"]),
                "payload_json": self._canonical_json(dict(raw["payload"])),
                "payload_hash": self._hash(self._canonical_json(dict(raw["payload"]))),
                "duplicate_fingerprint": self._duplicate_fingerprint(
                    event_type=PaperEventType(str(raw["event_type"])),
                    aggregate_id=str(raw["aggregate_id"]),
                    recommendation_id=raw.get("recommendation_id"),
                    transaction_id=raw.get("transaction_id"),
                    effective_timestamp=str(raw["effective_timestamp"]),
                    payload_hash=self._hash(self._canonical_json(dict(raw["payload"]))),
                ),
                "previous_event_hash": str(raw["previous_event_hash"]),
                "event_hash": str(raw["event_hash"]),
                "source_audit_references_json": self._canonical_json(dict(raw.get("source_audit_references", {}))),
                "provenance_json": self._canonical_json(dict(raw.get("provenance", {}))),
                "created_timestamp": str(raw["created_timestamp"]),
            }
            try:
                self.repository.persist_event_row(row)
            except Exception as exc:
                raise PaperLedgerValidationError(f"Import append rejected: {exc}") from exc

        head_hash = self.verify_integrity()
        if str(exported.get("head_hash")) != head_hash:
            raise PaperLedgerValidationError("Imported ledger head hash mismatch.")

    def _validate_append_contract(
        self,
        *,
        event_type: PaperEventType,
        aggregate_id: str,
        payload_version: str,
        payload: Mapping[str, Any],
    ) -> None:
        if event_type not in set(PaperEventType):
            raise PaperLedgerValidationError("Unsupported event type.")
        if not aggregate_id.strip():
            raise PaperLedgerValidationError("aggregate_id is required.")
        if payload_version not in self.ALLOWED_PAYLOAD_VERSIONS:
            raise PaperLedgerValidationError("Unsupported payload version.")
        if not isinstance(payload, Mapping):
            raise PaperLedgerValidationError("Event payload must be a mapping.")

    @staticmethod
    def _hash(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def _event_id(
        self,
        *,
        event_type: PaperEventType,
        sequence_number: int,
        aggregate_id: str,
        recommendation_id: str | None,
        transaction_id: str | None,
        effective_timestamp: str,
        payload_hash: str,
    ) -> str:
        raw = "|".join(
            [
                "paper-event-id-v1",
                event_type.value,
                str(sequence_number),
                aggregate_id,
                recommendation_id or "",
                transaction_id or "",
                effective_timestamp,
                payload_hash,
            ]
        )
        return self._hash(raw)

    def _event_hash(
        self,
        *,
        event_id: str,
        event_type: PaperEventType,
        sequence_number: int,
        event_timestamp: str,
        effective_timestamp: str,
        aggregate_id: str,
        recommendation_id: str | None,
        transaction_id: str | None,
        payload_version: str,
        payload_hash: str,
        previous_event_hash: str,
        source_audit_references: Mapping[str, str],
        provenance: Mapping[str, Any],
        created_timestamp: str,
    ) -> str:
        raw = self._canonical_json(
            {
                "event_id": event_id,
                "event_type": event_type.value,
                "sequence_number": sequence_number,
                "event_timestamp": event_timestamp,
                "effective_timestamp": effective_timestamp,
                "aggregate_id": aggregate_id,
                "recommendation_id": recommendation_id,
                "transaction_id": transaction_id,
                "payload_version": payload_version,
                "payload_hash": payload_hash,
                "previous_event_hash": previous_event_hash,
                "source_audit_references": dict(source_audit_references),
                "provenance": dict(provenance),
                "created_timestamp": created_timestamp,
            }
        )
        return self._hash(raw)

    def _duplicate_fingerprint(
        self,
        *,
        event_type: PaperEventType,
        aggregate_id: str,
        recommendation_id: str | None,
        transaction_id: str | None,
        effective_timestamp: str,
        payload_hash: str,
    ) -> str:
        raw = "|".join(
            [
                "paper-event-dup-v1",
                event_type.value,
                aggregate_id,
                recommendation_id or "",
                transaction_id or "",
                effective_timestamp,
                payload_hash,
            ]
        )
        return self._hash(raw)
