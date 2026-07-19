"""Manifest creation and content-addressing for immutable datasets."""

from __future__ import annotations

from typing import Any, Mapping

from .dataset_schema import CREATION_VERSION, SCHEMA_VERSION, DatasetManifest, hash_payload


def dataset_content_hash(*, metadata_without_hash: Mapping[str, Any], snapshot_hashes: Mapping[str, str]) -> str:
    return hash_payload(
        {
            "metadata": dict(metadata_without_hash),
            "snapshot_hashes": dict(sorted(snapshot_hashes.items())),
            "creation_version": CREATION_VERSION,
            "schema_version": SCHEMA_VERSION,
        }
    )


def create_manifest(*, dataset_id: str, content_hash: str, snapshot_hashes: Mapping[str, str]) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        content_hash=content_hash,
        snapshot_hashes=dict(sorted(snapshot_hashes.items())),
        creation_version=CREATION_VERSION,
        schema_version=SCHEMA_VERSION,
    )