from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess

import pytest

from engine.phase3.paper_portfolio_engine import PaperPortfolioEngine
from engine.phase3.paper_portfolio_governance import (
    PaperPortfolioState,
    PaperRecommendationModel,
    PaperRecommendationPolicy,
    PaperRecommendationStatus,
)
from engine.phase3.paper_portfolio_operations import (
    HealthStatus,
    OperationType,
    OperationsMode,
    PaperBackupManager,
    PaperOperationsController,
    PaperOperationsPolicy,
    PaperOperationsPreflightModel,
    RequestStatus,
    SessionStatus,
    build_daily_operations_report,
    build_operations_audit,
    evaluate_health,
    reconcile_states,
)
from engine.phase3.paper_portfolio_persistence import (
    HumanApprovalDecision,
    HumanApprovalRecord,
    HumanApprovalStatus,
    PaperPortfolioLedger,
    PaperPortfolioPersistenceModel,
    PaperPortfolioReplayModel,
    PaperPortfolioRepository,
)
from engine.phase3.system_validation import SystemValidationModel


REPO_ROOT = Path(__file__).resolve().parent.parent

FROZEN_HASHES = {
    "config/research_os_manifest.json": "8133e50ecfad9dc31fc40d237c4409c4ca9573936603008b9f7ca30e3939a473",
    "engine/phase3/context.py": "2099134c8afee427adeb6b291b5f4e10c6b9f0fae9ca4313feb6018297e4c3f1",
    "engine/phase3/expected_return/model.py": "8e0d2b399872c6910bb242ccd204c3687cd7e817cc5138462d82981e1b73ceeb",
    "engine/phase3/decision_engine/model.py": "15f7a92d288314afbfcd1a2d19d1c1484bcd88beece2f8ce7aff4c3ead479beb",
    "engine/phase3/calibration/model.py": "e5977219a3abf15b34e69de0ceef05d6dfccae566934cafb77dd88156c1be367",
    "engine/phase3/portfolio_simulation/model.py": "a4565433daf6f3aa8a2673bd493f7265462109f93890b9f0c48b9965d213d385",
    "engine/phase3/shadow_portfolio_construction/model.py": "43d39d2fec949b6a6060741890e703f19341b2bce63ddce8bd6b481c37c9f53d",
    "engine/phase3/system_validation/model.py": "66b02a55a1cacf154035d9f9454eb4dc5a4c88836c525a49a68cd4de424da3ab",
    "engine/research_os_release.py": "bebb46337f73450af766b325eb6052a5a5db2276926e5166271b0be774f20a35",
    "engine/phase2_downstream.py": "7d25d7aa24be4177118ac41e209fc173e5e5c20607052a0ce4522352ad41804b",
    "engine/portfolio_engine.py": "4d39683c3a0fee762bf028f748216388aef5b68ed3b5ac149478f6e2f8afb63b",
}

MILESTONE_HASHES = {
    "data/research/logs/PaperPortfolioEngine_Validated.json": "cfe62390a42047553d1d01eccd3c38cf24fa8acbeafee4ee8deff726409a5d61",
    "data/research/logs/RepositoryHygiene_Validated.json": "b375ece8db0066cbcdaa0e2d984d43819f6b44dfb5c781cb60ca6e11a4ee7f88",
    "data/research/logs/PaperPortfolioPersistenceReplay_Validated.json": "79883d7262cf7063206b85be149165f57db6ce7a3dc7a926531f4455ed6078cc",
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _build_pipeline():
    validation = SystemValidationModel(REPO_ROOT).evaluate()
    base_policy = PaperRecommendationPolicy.default()
    policy = PaperRecommendationPolicy(
        **{
            **base_policy.__dict__,
            "maximum_position_weight": 1.0,
            "maximum_sector_weight": 1.0,
            "maximum_portfolio_turnover": 1.0,
            "minimum_cash_reserve": 0.0,
            "shadow_allocation_requirements": ("WEIGHTS_RECONCILE",),
            "required_approvals": ("risk",),
        }
    )
    state = PaperPortfolioState(
        as_of_timestamp="2026-07-18T23:58:00+00:00",
        paper_cash=1000.0,
        paper_holdings={validation.decision.ticker: 1000.0},
        paper_weights={validation.decision.ticker: 0.5},
        total_paper_value=2000.0,
        provenance={"source": "operations_test"},
        version="1.0",
    )
    governance = PaperRecommendationModel().evaluate(
        decision_results=(validation.decision,),
        expected_return_results={validation.expected_return.ticker: validation.expected_return},
        calibration_results={validation.calibration.ticker: validation.calibration},
        simulation_result=validation.simulation,
        shadow_allocation_result=validation.shadow_allocation,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals={validation.decision.ticker: policy.required_approvals},
        as_of_timestamp="2026-07-18T23:58:00+00:00",
    )
    ticker = governance.recommendation_records[0].ticker
    engine_result = PaperPortfolioEngine().evaluate(
        recommendation_records=governance.recommendation_records,
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices={ticker: {"2026-07-18T23:58:00+00:00": 100.0}},
        benchmark_prices={"start": 100.0, "end": 101.0},
        as_of_timestamp="2026-07-18T23:58:00+00:00",
    )
    return governance.recommendation_records, engine_result


def _approval(recommendation_id: str) -> HumanApprovalRecord:
    return HumanApprovalRecord(
        approval_id=sha256(f"ops-approval|{recommendation_id}".encode("utf-8")).hexdigest(),
        recommendation_id=recommendation_id,
        approver_identity="risk",
        approval_decision=HumanApprovalDecision.APPROVE_FOR_PAPER,
        approval_timestamp="2026-07-18T23:58:00+00:00",
        approval_scope="single_recommendation",
        policy_version="paper-governance-v1",
        source_audit_reference="ops-governance-audit",
        reason="manual",
        expiration_timestamp="2026-07-21T23:58:00+00:00",
        superseded_by_reference=None,
        status=HumanApprovalStatus.ACTIVE,
    )


def _seed_repository(db_path: Path):
    recs, engine_result = _build_pipeline()
    repo = PaperPortfolioRepository(db_path)
    ledger = PaperPortfolioLedger(repo)
    persistence = PaperPortfolioPersistenceModel(repo, ledger)
    replay = PaperPortfolioReplayModel(repo, ledger)

    rec = recs[0]
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.DRAFT),
        source_audit_references={"governance": "g1"},
        provenance={"source": "ops-test"},
        created_timestamp="2026-07-18T23:58:00+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.PENDING_APPROVAL),
        source_audit_references={"governance": "g1"},
        provenance={"source": "ops-test"},
        created_timestamp="2026-07-18T23:58:10+00:00",
    )
    persistence.persist_approval(
        approval=_approval(rec.recommendation_id),
        source_audit_references={"governance": "g1"},
        provenance={"source": "ops-test"},
        created_timestamp="2026-07-18T23:58:20+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),
        source_audit_references={"governance": "g1"},
        provenance={"source": "ops-test"},
        created_timestamp="2026-07-18T23:58:30+00:00",
    )
    persistence.persist_engine_result(
        recommendations=(replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),),
        engine_result=engine_result,
        source_audit_references={"engine": "e1"},
        provenance={"source": "ops-test"},
        created_timestamp="2026-07-18T23:59:00+00:00",
    )
    checkpoint = replay.build_checkpoint(
        created_timestamp="2026-07-18T23:59:10+00:00",
        source_audit_references={"engine": "e1"},
    )
    return repo, ledger, replay, rec, checkpoint


def test_operations_boundary_and_defaults() -> None:
    source_dir = REPO_ROOT / "engine" / "phase3" / "paper_portfolio_operations"
    forbidden_import_prefixes = ("alpaca", "schwab", "ib_insync", "ccxt", "requests", "httpx", "urllib")
    for path in source_dir.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_import_prefixes)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden_import_prefixes)

    policy = PaperOperationsPolicy.default()
    assert policy.operations_mode in {OperationsMode.DISABLED, OperationsMode.VALIDATION_ONLY}
    policy.validate()


def test_preflight_fail_closed_on_invalid_markers_and_stale_prices(tmp_path: Path) -> None:
    repo, ledger, replay, _, _ = _seed_repository(tmp_path / "ops.sqlite")
    policy = PaperOperationsPolicy.default()
    preflight = PaperOperationsPreflightModel(
        policy=policy,
        repository=repo,
        ledger=ledger,
        replay=replay,
        repo_root=REPO_ROOT,
    )

    bad_hashes = dict(FROZEN_HASHES)
    bad_hashes["engine/phase3/context.py"] = "x"
    result = preflight.evaluate(
        current_timestamp="2026-07-19T03:00:00+00:00",
        latest_price_data_timestamp="2026-07-18T00:00:00+00:00",
        recommendation_timestamps={"r1": "2026-07-18T23:58:30+00:00"},
        frozen_hashes=bad_hashes,
        backup_count=0,
        latest_restore_test_passed=False,
        hygiene_passed=False,
        operator_approval_present=False,
    )
    assert not result.passed
    assert result.checks["frozen_hashes"] is False
    assert result.checks["price_freshness"] is False
    assert result.checks["backups"] is False


def test_controller_requires_manual_approval_and_no_autonomous_fill(tmp_path: Path) -> None:
    repo, ledger, replay, rec, _ = _seed_repository(tmp_path / "ops.sqlite")
    preflight = PaperOperationsPreflightModel(
        policy=PaperOperationsPolicy.default(),
        repository=repo,
        ledger=ledger,
        replay=replay,
        repo_root=REPO_ROOT,
    )
    controller = PaperOperationsController(policy=PaperOperationsPolicy.default(), preflight_model=preflight)

    session = controller.create_session(
        requested_mode=OperationsMode.PAPER_MANUAL,
        operator_identity="mason",
        operator_approval_reference="approval-ops-1",
        opened_timestamp="2026-07-18T23:59:30+00:00",
    )
    session = controller.run_preflight(
        session=session,
        current_timestamp="2026-07-18T23:59:30+00:00",
        latest_price_data_timestamp="2026-07-18T23:59:00+00:00",
        recommendation_timestamps={rec.recommendation_id: "2026-07-18T23:58:30+00:00"},
        frozen_hashes=FROZEN_HASHES,
        backup_count=1,
        latest_restore_test_passed=True,
        hygiene_passed=True,
    )
    session = controller.open_session(session=session)

    session, fill_request = controller.record_operation_request(
        session=session,
        operation_type=OperationType.RECORD_PAPER_FILL,
        recommendation_id=rec.recommendation_id,
        operator_identity="mason",
        operator_approval_reference="approval-ops-1",
        requested_timestamp="2026-07-19T00:00:00+00:00",
        effective_timestamp="2026-07-19T00:00:00+00:00",
        source_audit_references={"ops": "a1"},
        manual_approved=False,
    )
    assert fill_request.request_status is RequestStatus.BLOCKED

    session, approved_request = controller.record_operation_request(
        session=session,
        operation_type=OperationType.RECORD_PAPER_FILL,
        recommendation_id=rec.recommendation_id,
        operator_identity="mason",
        operator_approval_reference="approval-ops-1",
        requested_timestamp="2026-07-19T00:00:01+00:00",
        effective_timestamp="2026-07-19T00:00:01+00:00",
        source_audit_references={"ops": "a2"},
        manual_approved=True,
    )
    assert approved_request.request_status is RequestStatus.APPROVED_MANUALLY


def test_reconciliation_health_halt_and_deterministic_report(tmp_path: Path) -> None:
    repo, ledger, replay, rec, checkpoint = _seed_repository(tmp_path / "ops.sqlite")
    policy = PaperOperationsPolicy.default()

    replay_validation = replay.validate_canonical_state()
    replay_state = replay.replay_from_event_zero()
    bundle = repo.load_bundle()
    reconciliation = reconcile_states(
        ledger_head_hash=ledger.verify_integrity(),
        canonical_state_hash=repo.get_latest_state_hash(),
        replay_state_hash=replay_validation.replay_state_hash,
        checkpoint_state_hash=checkpoint.state_hash,
        bundle=bundle,
        replay_state=replay_state,
        replay_validation=replay_validation,
        tolerance=policy.reconciliation_tolerance,
    )
    assert reconciliation.passed

    degraded = evaluate_health(
        reconciliation=reconciliation,
        preflight_blockers=(),
        automatic_halt_conditions_triggered=(),
    )
    assert degraded.status is HealthStatus.HEALTHY

    halted = evaluate_health(
        reconciliation=reconciliation,
        preflight_blockers=("REPLAY_MISMATCH",),
        automatic_halt_conditions_triggered=("replay_diverged",),
    )
    assert halted.status is HealthStatus.HALTED
    assert halted.halt_required

    session = PaperOperationsController(policy=policy, preflight_model=PaperOperationsPreflightModel(policy=policy, repository=repo, ledger=ledger, replay=replay, repo_root=REPO_ROOT)).create_session(
        requested_mode=OperationsMode.PAPER_OBSERVATION,
        operator_identity="mason",
        operator_approval_reference="approval-ops-2",
        opened_timestamp="2026-07-19T00:01:00+00:00",
    )

    preflight_result = PaperOperationsPreflightModel(
        policy=policy,
        repository=repo,
        ledger=ledger,
        replay=replay,
        repo_root=REPO_ROOT,
    ).evaluate(
        current_timestamp="2026-07-19T00:01:00+00:00",
        latest_price_data_timestamp="2026-07-18T23:59:00+00:00",
        recommendation_timestamps={rec.recommendation_id: "2026-07-18T23:58:30+00:00"},
        frozen_hashes=FROZEN_HASHES,
        backup_count=1,
        latest_restore_test_passed=True,
        hygiene_passed=True,
        operator_approval_present=True,
    )

    report_a = build_daily_operations_report(
        operating_mode=OperationsMode.PAPER_OBSERVATION.value,
        session=session,
        preflight=preflight_result,
        reconciliation=reconciliation,
        replay_validation=replay_validation,
        bundle=bundle,
        requests=(),
        benchmark_comparison={"benchmark_return": 0.01, "active_return": 0.0},
        drawdown=min(0.0, bundle.performance_history[-1].cumulative_return),
        audit_references={"ops": "audit-1"},
    )
    report_b = build_daily_operations_report(
        operating_mode=OperationsMode.PAPER_OBSERVATION.value,
        session=session,
        preflight=preflight_result,
        reconciliation=reconciliation,
        replay_validation=replay_validation,
        bundle=bundle,
        requests=(),
        benchmark_comparison={"benchmark_return": 0.01, "active_return": 0.0},
        drawdown=min(0.0, bundle.performance_history[-1].cumulative_return),
        audit_references={"ops": "audit-1"},
    )
    assert report_a == report_b


def test_backup_restore_determinism_and_integrity(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.sqlite"
    repo, ledger, replay, _, _ = _seed_repository(db_path)

    manager = PaperBackupManager(repo_path=db_path, backup_dir=tmp_path / "backups")
    manifest_a = manager.create_backup(
        created_timestamp="2026-07-19T00:02:00+00:00",
        repository=repo,
        ledger=ledger,
        replay=replay,
    )
    manifest_b = manager.create_backup(
        created_timestamp="2026-07-19T00:02:00+00:00",
        repository=repo,
        ledger=ledger,
        replay=replay,
    )
    assert manifest_a.backup_name == manifest_b.backup_name
    assert manifest_a.backup_file_hash == manifest_b.backup_file_hash
    assert manager.verify_backup(manifest_a)
    assert manager.test_restore(manifest=manifest_a, temp_root=tmp_path / "tmp_restore")


def test_interrupted_backup_does_not_damage_canonical_storage(tmp_path: Path) -> None:
    db_path = tmp_path / "ops.sqlite"
    repo, ledger, replay, _, _ = _seed_repository(db_path)
    canonical_hash_before = repo.get_latest_state_hash()

    manager = PaperBackupManager(repo_path=db_path, backup_dir=tmp_path / "backups")
    manifest = manager.create_backup(
        created_timestamp="2026-07-19T00:03:00+00:00",
        repository=repo,
        ledger=ledger,
        replay=replay,
    )
    Path(manifest.backup_path).unlink()
    assert not manager.verify_backup(manifest)
    assert repo.get_latest_state_hash() == canonical_hash_before


def test_cli_defaults_and_manual_guard() -> None:
    script = REPO_ROOT / "scripts" / "paper_operations_runbook.py"
    result = subprocess.run(
        ["python3", str(script)],
        check=True,
        text=True,
        capture_output=True,
    )
    assert '"mode": "VALIDATION_ONLY"' in result.stdout

    bad = subprocess.run(
        ["python3", str(script), "open-manual-session"],
        text=True,
        capture_output=True,
    )
    assert bad.returncode != 0


def test_isolated_operations_rehearsal_and_cleanup(tmp_path: Path) -> None:
    rehearsal_root = tmp_path / "rehearsal"
    rehearsal_root.mkdir(parents=True, exist_ok=True)
    db_path = rehearsal_root / "paper.sqlite"

    repo, ledger, replay, rec, checkpoint = _seed_repository(db_path)
    policy = PaperOperationsPolicy.default()
    preflight_model = PaperOperationsPreflightModel(
        policy=policy,
        repository=repo,
        ledger=ledger,
        replay=replay,
        repo_root=REPO_ROOT,
    )
    controller = PaperOperationsController(policy=policy, preflight_model=preflight_model)

    validation_session = controller.create_session(
        requested_mode=OperationsMode.VALIDATION_ONLY,
        operator_identity="mason",
        operator_approval_reference="",
        opened_timestamp="2026-07-19T00:04:00+00:00",
    )
    validation_preflight = controller.run_preflight(
        session=validation_session,
        current_timestamp="2026-07-19T00:04:00+00:00",
        latest_price_data_timestamp="2026-07-18T23:59:00+00:00",
        recommendation_timestamps={rec.recommendation_id: "2026-07-18T23:58:30+00:00"},
        frozen_hashes=FROZEN_HASHES,
        backup_count=1,
        latest_restore_test_passed=True,
        hygiene_passed=True,
    )
    assert validation_preflight.session_status is SessionStatus.PREFLIGHT_BLOCKED

    observation = controller.create_session(
        requested_mode=OperationsMode.PAPER_OBSERVATION,
        operator_identity="mason",
        operator_approval_reference="ops-approval-obs",
        opened_timestamp="2026-07-19T00:05:00+00:00",
    )
    observation = controller.run_preflight(
        session=observation,
        current_timestamp="2026-07-19T00:05:00+00:00",
        latest_price_data_timestamp="2026-07-18T23:59:00+00:00",
        recommendation_timestamps={rec.recommendation_id: "2026-07-18T23:58:30+00:00"},
        frozen_hashes=FROZEN_HASHES,
        backup_count=1,
        latest_restore_test_passed=True,
        hygiene_passed=True,
    )
    observation = controller.open_session(session=observation)
    observation, _ = controller.record_operation_request(
        session=observation,
        operation_type=OperationType.RECORD_RECOMMENDATION,
        recommendation_id=rec.recommendation_id,
        operator_identity="mason",
        operator_approval_reference="ops-approval-obs",
        requested_timestamp="2026-07-19T00:05:10+00:00",
        effective_timestamp="2026-07-19T00:05:10+00:00",
        source_audit_references={"ops": "obs-r1"},
        manual_approved=True,
    )

    observation, fill_request = controller.record_operation_request(
        session=observation,
        operation_type=OperationType.RECORD_PAPER_FILL,
        recommendation_id=rec.recommendation_id,
        operator_identity="mason",
        operator_approval_reference="ops-approval-obs",
        requested_timestamp="2026-07-19T00:05:15+00:00",
        effective_timestamp="2026-07-19T00:05:15+00:00",
        source_audit_references={"ops": "obs-fill"},
        manual_approved=True,
    )
    assert fill_request.request_status is RequestStatus.APPROVED_MANUALLY

    replay_validation = replay.validate_canonical_state()
    replay_state = replay.replay_from_event_zero()
    bundle = repo.load_bundle()
    reconciliation = reconcile_states(
        ledger_head_hash=ledger.verify_integrity(),
        canonical_state_hash=repo.get_latest_state_hash(),
        replay_state_hash=replay_validation.replay_state_hash,
        checkpoint_state_hash=checkpoint.state_hash,
        bundle=bundle,
        replay_state=replay_state,
        replay_validation=replay_validation,
        tolerance=policy.reconciliation_tolerance,
    )
    assert reconciliation.passed

    manager = PaperBackupManager(repo_path=db_path, backup_dir=rehearsal_root / "backups")
    manifest = manager.create_backup(
        created_timestamp="2026-07-19T00:06:00+00:00",
        repository=repo,
        ledger=ledger,
        replay=replay,
    )
    assert manager.verify_backup(manifest)
    repo.close()

    restored_ok = manager.test_restore(manifest=manifest, temp_root=rehearsal_root / "restore_temp")
    assert restored_ok

    reopened_repo = PaperPortfolioRepository(db_path)
    reopened_ledger = PaperPortfolioLedger(reopened_repo)
    reopened_replay = PaperPortfolioReplayModel(reopened_repo, reopened_ledger)
    reopened_preflight = PaperOperationsPreflightModel(
        policy=policy,
        repository=reopened_repo,
        ledger=reopened_ledger,
        replay=reopened_replay,
        repo_root=REPO_ROOT,
    ).evaluate(
        current_timestamp="2026-07-19T00:06:10+00:00",
        latest_price_data_timestamp="2026-07-18T23:59:00+00:00",
        recommendation_timestamps={rec.recommendation_id: "2026-07-18T23:58:30+00:00"},
        frozen_hashes=FROZEN_HASHES,
        backup_count=1,
        latest_restore_test_passed=True,
        hygiene_passed=True,
        operator_approval_present=True,
    )

    report = build_daily_operations_report(
        operating_mode=OperationsMode.PAPER_OBSERVATION.value,
        session=observation,
        preflight=reopened_preflight,
        reconciliation=reconciliation,
        replay_validation=replay_validation,
        bundle=bundle,
        requests=tuple(controller.requests),
        benchmark_comparison={"benchmark_return": 0.01, "active_return": 0.0},
        drawdown=min(0.0, bundle.performance_history[-1].cumulative_return),
        audit_references={"ops": "rehearsal"},
    )
    assert report["operating_mode"] == OperationsMode.PAPER_OBSERVATION.value

    # Deliberate replay mismatch trigger and automatic halt.
    temp_repo = PaperPortfolioRepository(db_path)
    temp_repo.run_atomic(lambda conn: conn.execute("UPDATE replay_checkpoints SET state_hash='BAD'"))
    temp_ledger = PaperPortfolioLedger(temp_repo)
    temp_replay = PaperPortfolioReplayModel(temp_repo, temp_ledger)
    mismatch_validation = temp_replay.validate_canonical_state()
    health = evaluate_health(
        reconciliation=reconciliation,
        preflight_blockers=tuple(mismatch_validation.mismatch_reasons),
        automatic_halt_conditions_triggered=("replay_diverged",),
    )
    assert health.status is HealthStatus.HALTED

    audit = build_operations_audit(
        source_modules=(
            "engine.phase3.paper_portfolio_operations.preflight",
            "engine.phase3.paper_portfolio_operations.controller",
            "engine.phase3.paper_portfolio_operations.monitor",
        ),
        input_hashes={"frozen": sha256(str(FROZEN_HASHES).encode("utf-8")).hexdigest()},
        preflight_checks={"ok": True},
        reconciliation_result=reconciliation,
        health_result=health,
        operation_requests=tuple(row.request_id for row in controller.requests),
        automatic_halt_conditions_triggered=("replay_diverged",),
        timestamp_metadata={"at": "2026-07-19T00:06:20+00:00"},
    )
    assert isinstance(audit.configuration_hash, str)

    reopened_repo.close()
    temp_repo.close()

    shutil.rmtree(rehearsal_root, ignore_errors=True)
    assert not rehearsal_root.exists()


def test_immutability_and_frozen_hashes_unchanged() -> None:
    record = _approval("r1")
    with pytest.raises(FrozenInstanceError):
        record.reason = "mutate"  # type: ignore[misc]

    for relative_path, expected_hash in FROZEN_HASHES.items():
        assert _sha(REPO_ROOT / relative_path) == expected_hash

    for relative_path, expected_hash in MILESTONE_HASHES.items():
        assert _sha(REPO_ROOT / relative_path) == expected_hash
