"""Assemble deterministic historical source fragments into DatasetBuilder snapshots.

This module is data infrastructure only. It imports local file-backed connectors
and the DatasetBuilder; it never imports or invokes historical replay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from engine.data_sources import AnalystConnector, FundamentalsConnector, MacroConnector, NewsConnector, PriceConnector, SECConnector
from engine.data_sources.source_contract import HistoricalSourceConnector, thaw

from .dataset_builder import DatasetBuilder
from .dataset_manifest import dataset_content_hash
from .dataset_schema import SCHEMA_VERSION, canonical_json_bytes, hash_bytes, parse_date


class DatasetAssembler:
    def __init__(self, connectors: Sequence[HistoricalSourceConnector] | None = None) -> None:
        self.connectors = tuple(connectors or (SECConnector(), PriceConnector(), FundamentalsConnector(), MacroConnector(), AnalystConnector(), NewsConnector()))

    def assemble_snapshots(self, *, dates: Iterable[str], symbols: Sequence[str], source_root: Path | str) -> tuple[dict[str, Any], ...]:
        canonical_dates = tuple(sorted({parse_date(value, field_name="dates").isoformat() for value in dates}))
        canonical_symbols = tuple(sorted({str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()}))
        if not canonical_dates or not canonical_symbols:
            raise ValueError("dates and symbols must be non-empty")
        snapshots: list[dict[str, Any]] = []
        for snapshot_date in canonical_dates:
            fragments = [connector.fetch(snapshot_date, canonical_symbols, source_root) for connector in self.connectors]
            by_name = {fragment.source_name: fragment for fragment in fragments}
            if len(by_name) != len(fragments):
                raise ValueError("connector source_name values must be unique")
            lineage = {
                name: {
                    "source_name": fragment.source_name,
                    "source_hash": fragment.source_hash,
                    "schema_version": fragment.schema_version,
                    "record_count": len(fragment.records),
                }
                for name, fragment in sorted(by_name.items())
            }
            snapshot = {
                "snapshot_id": f"snapshot-{snapshot_date}-{'-'.join(symbol.lower() for symbol in canonical_symbols)}",
                "snapshot_date": snapshot_date,
                "company_fundamentals": [thaw(record) for record in by_name["company_fundamentals"].records],
                "sec_filings": [thaw(record) for record in by_name["sec_filings"].records],
                "macro_data": [thaw(record) for record in by_name["macro_data"].records],
                "prices": [thaw(record) for record in by_name["prices"].records],
                "analyst_estimates": [thaw(record) for record in by_name["analyst_estimates"].records],
                "evidence": [thaw(record) for record in by_name["evidence"].records],
                "source_lineage": lineage,
            }
            snapshot["content_hash"] = hash_bytes(canonical_json_bytes(snapshot))
            snapshots.append(snapshot)
        return tuple(snapshots)

    def preview_content_hash(self, *, dataset_id: str, dataset_name: str, market: str, snapshots: Sequence[dict[str, Any]], expected_dates: Sequence[str]) -> str:
        ordered = sorted(snapshots, key=lambda snapshot: (snapshot["snapshot_date"], snapshot["snapshot_id"]))
        snapshot_hashes = {snapshot["snapshot_id"]: hash_bytes(canonical_json_bytes(snapshot)) for snapshot in ordered}
        metadata = {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "market": market,
            "start_date": ordered[0]["snapshot_date"],
            "end_date": ordered[-1]["snapshot_date"],
            "snapshot_count": len(ordered),
            "schema_version": SCHEMA_VERSION,
            "expected_dates": list(sorted(expected_dates)),
        }
        return dataset_content_hash(metadata_without_hash=metadata, snapshot_hashes=snapshot_hashes)

    def build(self, *, output_dir: Path | str, dataset_id: str, dataset_name: str, market: str, dates: Iterable[str], symbols: Sequence[str], source_root: Path | str) -> Path:
        canonical_dates = tuple(sorted({parse_date(value, field_name="dates").isoformat() for value in dates}))
        snapshots = self.assemble_snapshots(dates=canonical_dates, symbols=symbols, source_root=source_root)
        return DatasetBuilder().build(output_dir=output_dir, dataset_id=dataset_id, dataset_name=dataset_name, market=market, snapshots=snapshots, expected_dates=canonical_dates)