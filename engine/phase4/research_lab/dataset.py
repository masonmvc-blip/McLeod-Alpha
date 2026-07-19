from __future__ import annotations

from hashlib import sha256
import json

from .types import DatasetSpec, SurvivorshipPolicy


def deterministic_dataset_id(
    *,
    universe: str,
    start_date: str,
    end_date: str,
    required_fields: tuple[str, ...],
    required_sample_size: int,
    survivorship_policy: SurvivorshipPolicy,
) -> str:
    payload = {
        "end_date": end_date,
        "required_fields": list(sorted(required_fields)),
        "required_sample_size": required_sample_size,
        "start_date": start_date,
        "survivorship_policy": survivorship_policy.value,
        "universe": universe,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def create_dataset_spec(
    *,
    universe: str,
    start_date: str,
    end_date: str,
    required_fields: tuple[str, ...],
    survivorship_policy: SurvivorshipPolicy,
    look_ahead_prevention: bool,
    data_quality_score: float,
    provenance: dict[str, str],
    required_sample_size: int = 120,
) -> DatasetSpec:
    if not (0.0 <= data_quality_score <= 1.0):
        raise ValueError("data_quality_score must be in [0, 1]")
    if required_sample_size <= 0:
        raise ValueError("required_sample_size must be > 0")
    dataset_id = deterministic_dataset_id(
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        required_fields=required_fields,
        required_sample_size=required_sample_size,
        survivorship_policy=survivorship_policy,
    )
    return DatasetSpec(
        dataset_id=dataset_id,
        universe=universe,
        start_date=start_date,
        end_date=end_date,
        required_fields=tuple(sorted(required_fields)),
        required_sample_size=required_sample_size,
        survivorship_policy=survivorship_policy,
        look_ahead_prevention=look_ahead_prevention,
        data_quality_score=data_quality_score,
        provenance=dict(sorted(provenance.items())),
    )
