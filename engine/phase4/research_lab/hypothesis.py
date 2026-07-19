from __future__ import annotations

from hashlib import sha256
import json

from .types import (
    ExpectedDirection,
    ExperimentStatus,
    HypothesisType,
    ResearchHypothesis,
)


def deterministic_hypothesis_id(
    *,
    title: str,
    author: str,
    hypothesis_type: HypothesisType,
    factors_under_test: tuple[str, ...],
    creation_timestamp: str,
    version: str,
) -> str:
    payload = {
        "author": author,
        "creation_timestamp": creation_timestamp,
        "factors_under_test": list(sorted(factors_under_test)),
        "hypothesis_type": hypothesis_type.value,
        "title": title,
        "version": version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def create_hypothesis(
    *,
    title: str,
    description: str,
    author: str,
    creation_timestamp: str,
    hypothesis_type: HypothesisType,
    factors_under_test: tuple[str, ...],
    expected_direction: ExpectedDirection,
    null_hypothesis: str,
    alternative_hypothesis: str,
    required_dataset: str,
    required_sample_size: int,
    version: str,
    provenance: dict[str, str],
) -> ResearchHypothesis:
    if required_sample_size <= 0:
        raise ValueError("required_sample_size must be > 0")
    hypothesis_id = deterministic_hypothesis_id(
        title=title,
        author=author,
        hypothesis_type=hypothesis_type,
        factors_under_test=factors_under_test,
        creation_timestamp=creation_timestamp,
        version=version,
    )
    return ResearchHypothesis(
        hypothesis_id=hypothesis_id,
        title=title,
        description=description,
        author=author,
        creation_timestamp=creation_timestamp,
        hypothesis_type=hypothesis_type,
        factors_under_test=factors_under_test,
        expected_direction=expected_direction,
        null_hypothesis=null_hypothesis,
        alternative_hypothesis=alternative_hypothesis,
        required_dataset=required_dataset,
        required_sample_size=required_sample_size,
        experiment_status=ExperimentStatus.DRAFT,
        version=version,
        provenance=dict(sorted(provenance.items())),
    )