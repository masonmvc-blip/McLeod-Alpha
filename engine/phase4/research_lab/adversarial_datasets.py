from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from .types import DatasetContaminationResult, DatasetObservation


CONTAMINATION_CLASSES: tuple[str, ...] = (
    "future_fundamental_data",
    "future_prices",
    "revised_macro_data",
    "post_period_index_membership",
    "survivor_only_universe",
    "delisted_security_omission",
    "overlapping_train_test_observations",
    "target_leakage_derived_features",
    "timestamp_misalignment",
    "filing_date_vs_period_end_confusion",
    "publication_lag_violations",
    "corporate_action_hindsight",
    "benchmark_look_ahead",
    "universe_selection_look_ahead",
)


def _ts(value: str) -> datetime:
    if not value:
        return datetime(1900, 1, 1, tzinfo=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _base_observation(observation_id: str, *, feature_name: str = "roic", security_id: str = "ABC") -> DatasetObservation:
    period_end = datetime(2024, 3, 31, tzinfo=timezone.utc)
    filing = period_end + timedelta(days=30)
    publication = filing + timedelta(days=1)
    availability = publication + timedelta(days=1)
    effective = availability + timedelta(minutes=1)
    target_start = availability + timedelta(days=1)
    target_end = target_start + timedelta(days=30)
    membership = datetime(2023, 1, 1, tzinfo=timezone.utc)
    corp_action = publication - timedelta(days=1)
    return DatasetObservation(
        observation_id=observation_id,
        security_id=security_id,
        observation_date=availability.date().isoformat(),
        economic_period_end=period_end.date().isoformat(),
        filing_date=filing.date().isoformat(),
        publication_timestamp=publication.isoformat(),
        availability_timestamp=availability.isoformat(),
        effective_timestamp=effective.isoformat(),
        universe_membership_timestamp=membership.isoformat(),
        delisting_timestamp="",
        corporate_action_timestamp=corp_action.isoformat(),
        feature_name=feature_name,
        feature_value=1.234,
        target_start_timestamp=target_start.isoformat(),
        target_end_timestamp=target_end.isoformat(),
        source_version="v1",
        revision_identifier="initial",
        provenance={
            "fixture": "point_in_time",
            "expected_universe_ids": "ABC,DELISTED_X",
            "validator_contract": "dataset_observation_v1",
        },
    )


def _clone(obs: DatasetObservation, **updates: object) -> DatasetObservation:
    payload = {
        "observation_id": obs.observation_id,
        "security_id": obs.security_id,
        "observation_date": obs.observation_date,
        "economic_period_end": obs.economic_period_end,
        "filing_date": obs.filing_date,
        "publication_timestamp": obs.publication_timestamp,
        "availability_timestamp": obs.availability_timestamp,
        "effective_timestamp": obs.effective_timestamp,
        "universe_membership_timestamp": obs.universe_membership_timestamp,
        "delisting_timestamp": obs.delisting_timestamp,
        "corporate_action_timestamp": obs.corporate_action_timestamp,
        "feature_name": obs.feature_name,
        "feature_value": obs.feature_value,
        "target_start_timestamp": obs.target_start_timestamp,
        "target_end_timestamp": obs.target_end_timestamp,
        "source_version": obs.source_version,
        "revision_identifier": obs.revision_identifier,
        "provenance": deepcopy(dict(obs.provenance)),
    }
    payload.update(updates)
    return DatasetObservation(**payload)


def build_adversarial_dataset_fixtures() -> dict[str, tuple[tuple[DatasetObservation, ...], tuple[DatasetObservation, ...]]]:
    clean = _base_observation("obs-clean")
    delisted_clean = _clone(
        _base_observation("obs-delisted", security_id="DELISTED_X", feature_name="momentum"),
        delisting_timestamp="2024-07-15T00:00:00+00:00",
    )
    valid = (clean, delisted_clean)

    fixtures: dict[str, tuple[tuple[DatasetObservation, ...], tuple[DatasetObservation, ...]]] = {}
    fixtures["future_fundamental_data"] = (
        valid,
        (_clone(clean, availability_timestamp="2024-06-01T00:00:00+00:00", target_start_timestamp="2024-05-01T00:00:00+00:00", observation_id="bad-future-fund"), delisted_clean),
    )
    fixtures["future_prices"] = (
        valid,
        (_clone(clean, feature_name="future_price", observation_date="2024-06-01", target_start_timestamp="2024-05-15T00:00:00+00:00", observation_id="bad-future-price"), delisted_clean),
    )
    fixtures["revised_macro_data"] = (
        valid,
        (_clone(clean, feature_name="macro_cpi", revision_identifier="revised_2", publication_timestamp="2024-06-01T00:00:00+00:00", target_start_timestamp="2024-05-20T00:00:00+00:00", observation_id="bad-revision"), delisted_clean),
    )
    fixtures["post_period_index_membership"] = (
        valid,
        (_clone(clean, universe_membership_timestamp="2024-07-01T00:00:00+00:00", target_start_timestamp="2024-05-01T00:00:00+00:00", observation_id="bad-membership"), delisted_clean),
    )
    fixtures["survivor_only_universe"] = (
        valid,
        (_clone(clean, provenance={"expected_universe_ids": "ABC,DELISTED_X", "validator_contract": "dataset_observation_v1"}),),
    )
    fixtures["delisted_security_omission"] = (
        valid,
        (_clone(clean, security_id="DELISTED_X", delisting_timestamp="", observation_id="bad-delisted-missing"),),
    )
    fixtures["overlapping_train_test_observations"] = (
        valid,
        (_clone(clean, observation_date="2024-05-20", target_start_timestamp="2024-05-15T00:00:00+00:00", target_end_timestamp="2024-06-20T00:00:00+00:00", observation_id="bad-overlap"), delisted_clean),
    )
    fixtures["target_leakage_derived_features"] = (
        valid,
        (_clone(clean, feature_name="target_return_next_21d", observation_id="bad-target-leakage"), delisted_clean),
    )
    fixtures["timestamp_misalignment"] = (
        valid,
        (_clone(clean, publication_timestamp="2024-05-05T00:00:00+00:00", availability_timestamp="2024-05-01T00:00:00+00:00", observation_id="bad-ts-order"), delisted_clean),
    )
    fixtures["filing_date_vs_period_end_confusion"] = (
        valid,
        (_clone(clean, filing_date="2024-03-01", economic_period_end="2024-03-31", observation_id="bad-filing-period"), delisted_clean),
    )
    fixtures["publication_lag_violations"] = (
        valid,
        (_clone(clean, publication_timestamp="2024-03-31T00:00:00+00:00", economic_period_end="2024-03-31", observation_id="bad-pub-lag"), delisted_clean),
    )
    fixtures["corporate_action_hindsight"] = (
        valid,
        (_clone(clean, feature_name="adjusted_price", corporate_action_timestamp="2024-06-10T00:00:00+00:00", target_start_timestamp="2024-05-01T00:00:00+00:00", observation_id="bad-corp-action"), delisted_clean),
    )
    fixtures["benchmark_look_ahead"] = (
        valid,
        (_clone(clean, security_id="BENCHMARK", observation_date="2024-06-15", target_start_timestamp="2024-05-01T00:00:00+00:00", observation_id="bad-benchmark-lookahead"), delisted_clean),
    )
    fixtures["universe_selection_look_ahead"] = (
        valid,
        (_clone(clean, feature_name="universe_selector", effective_timestamp="2024-06-01T00:00:00+00:00", target_start_timestamp="2024-05-01T00:00:00+00:00", observation_id="bad-universe-lookahead"), delisted_clean),
    )
    return fixtures


def _validate_class(contamination_class: str, observations: Sequence[DatasetObservation]) -> tuple[bool, tuple[str, ...], str, str]:
    offenders: list[str] = []
    evidence: list[str] = []
    severity = "HIGH"

    universe_ids = sorted({obs.security_id for obs in observations})
    expected_ids = set()
    for obs in observations:
        raw = str(obs.provenance.get("expected_universe_ids", ""))
        expected_ids.update([x.strip() for x in raw.split(",") if x.strip()])

    for obs in observations:
        target_start = _ts(obs.target_start_timestamp)
        target_end = _ts(obs.target_end_timestamp)
        period_end = _ts(obs.economic_period_end)
        filing = _ts(obs.filing_date)
        publication = _ts(obs.publication_timestamp)
        availability = _ts(obs.availability_timestamp)
        effective = _ts(obs.effective_timestamp)
        membership = _ts(obs.universe_membership_timestamp)
        delisting = _ts(obs.delisting_timestamp)
        corp_action = _ts(obs.corporate_action_timestamp)
        observation_date = _ts(obs.observation_date)

        if contamination_class == "future_fundamental_data" and availability > target_start:
            offenders.append(obs.observation_id)
            evidence.append("availability_timestamp after target_start")
        elif contamination_class == "future_prices" and "price" in obs.feature_name.lower() and observation_date > target_start:
            offenders.append(obs.observation_id)
            evidence.append("price observation date after target_start")
        elif contamination_class == "revised_macro_data" and obs.feature_name.startswith("macro") and obs.revision_identifier.startswith("revised") and publication > target_start:
            offenders.append(obs.observation_id)
            evidence.append("revised macro release used before availability")
        elif contamination_class == "post_period_index_membership" and membership > target_start:
            offenders.append(obs.observation_id)
            evidence.append("index membership entered after target start")
        elif contamination_class == "delisted_security_omission" and obs.security_id.startswith("DELISTED") and not obs.delisting_timestamp:
            offenders.append(obs.observation_id)
            evidence.append("delisted security missing delisting timestamp")
        elif contamination_class == "overlapping_train_test_observations" and observation_date >= target_start and observation_date <= target_end:
            offenders.append(obs.observation_id)
            evidence.append("observation date overlaps target interval")
        elif contamination_class == "target_leakage_derived_features" and (
            "target" in obs.feature_name.lower() or "future" in obs.feature_name.lower() or "next" in obs.feature_name.lower()
        ):
            offenders.append(obs.observation_id)
            evidence.append("feature name encodes forward target")
        elif contamination_class == "timestamp_misalignment" and (publication > availability or availability > effective):
            offenders.append(obs.observation_id)
            evidence.append("publication/availability/effective order invalid")
        elif contamination_class == "filing_date_vs_period_end_confusion" and filing < period_end:
            offenders.append(obs.observation_id)
            evidence.append("filing date earlier than economic period end")
        elif contamination_class == "publication_lag_violations" and publication <= period_end:
            offenders.append(obs.observation_id)
            evidence.append("publication lag violated")
        elif contamination_class == "corporate_action_hindsight" and "adjusted" in obs.feature_name.lower() and corp_action > target_start:
            offenders.append(obs.observation_id)
            evidence.append("corporate action recorded after target start")
        elif contamination_class == "benchmark_look_ahead" and obs.security_id == "BENCHMARK" and observation_date > target_start:
            offenders.append(obs.observation_id)
            evidence.append("benchmark observation occurs after target start")
        elif contamination_class == "universe_selection_look_ahead" and obs.feature_name == "universe_selector" and effective > target_start:
            offenders.append(obs.observation_id)
            evidence.append("universe selector effective after target start")

    if contamination_class == "survivor_only_universe":
        missing = sorted(expected_ids.difference(universe_ids))
        if missing:
            offenders.extend(missing)
            evidence.append("expected universe ids missing from observations")

    if offenders:
        return False, tuple(sorted(set(offenders))), "; ".join(sorted(set(evidence))), severity
    return True, tuple(), "No contamination detected", "NONE"


def validate_dataset_fixture(
    *,
    fixture_id: str,
    contamination_class: str,
    observations: Sequence[DatasetObservation],
    validator_version: str = "dataset-validator-1.0",
) -> DatasetContaminationResult:
    passed, offenders, evidence, severity = _validate_class(contamination_class, observations)
    return DatasetContaminationResult(
        fixture_id=fixture_id,
        contamination_class=contamination_class,
        passed=passed,
        offending_observation_ids=offenders,
        evidence=evidence,
        severity=severity,
        validator_version=validator_version,
        provenance={
            "observation_count": str(len(observations)),
            "validator_contract": "dataset_observation_v1",
        },
    )


def run_dataset_adversarial_suite() -> tuple[DatasetContaminationResult, ...]:
    fixtures = build_adversarial_dataset_fixtures()
    results: list[DatasetContaminationResult] = []
    for contamination_class in CONTAMINATION_CLASSES:
        valid, contaminated = fixtures[contamination_class]
        valid_result = validate_dataset_fixture(
            fixture_id=f"{contamination_class}::valid",
            contamination_class=contamination_class,
            observations=valid,
        )
        contaminated_result = validate_dataset_fixture(
            fixture_id=f"{contamination_class}::contaminated",
            contamination_class=contamination_class,
            observations=contaminated,
        )
        results.append(valid_result)
        results.append(contaminated_result)
    return tuple(results)


def dataset_suite_passed(results: Iterable[DatasetContaminationResult]) -> bool:
    valid_checks = [r for r in results if r.fixture_id.endswith("::valid")]
    contaminated_checks = [r for r in results if r.fixture_id.endswith("::contaminated")]
    return all(r.passed for r in valid_checks) and all(not r.passed for r in contaminated_checks)
