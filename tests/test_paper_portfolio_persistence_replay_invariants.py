from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path
import shutil
import sqlite3

import pytest

from engine.phase3.paper_portfolio_engine import PaperPortfolioEngine
from engine.phase3.paper_portfolio_governance import (
    PaperPortfolioState,
    PaperRecommendationModel,
    PaperRecommendationPolicy,
    PaperRecommendationStatus,
)
from engine.phase3.paper_portfolio_persistence import (
    CorporateActionRecord,
    CorporateActionType,
    HumanApprovalDecision,
    HumanApprovalRecord,
    HumanApprovalStatus,
    InvalidLifecycleTransitionError,
    PaperEventType,
    PaperLedgerValidationError,
    PaperPortfolioLedger,
    PaperPortfolioPersistenceModel,
    PaperPortfolioPersistenceValidationError,
    PaperPortfolioReplayError,
    PaperPortfolioReplayModel,
    PaperPortfolioRepository,
)
from engine.phase3.paper_portfolio_persistence.types import TaxLotStatus
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
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _build_pipeline():
    validation = SystemValidationModel(REPO_ROOT).evaluate()
    governance_model = PaperRecommendationModel()
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
        as_of_timestamp="2026-07-18T23:50:00+00:00",
        paper_cash=1000.0,
        paper_holdings={validation.decision.ticker: 1000.0},
        paper_weights={validation.decision.ticker: 0.5},
        total_paper_value=2000.0,
        provenance={"source": "paper_persistence_test"},
        version="1.0",
    )
    governance = governance_model.evaluate(
        decision_results=(validation.decision,),
        expected_return_results={validation.expected_return.ticker: validation.expected_return},
        calibration_results={validation.calibration.ticker: validation.calibration},
        simulation_result=validation.simulation,
        shadow_allocation_result=validation.shadow_allocation,
        policy=policy,
        paper_portfolio_state=state,
        human_approvals={validation.decision.ticker: policy.required_approvals},
        as_of_timestamp="2026-07-18T23:50:00+00:00",
    )
    ticker = governance.recommendation_records[0].ticker
    engine_result = PaperPortfolioEngine().evaluate(
        recommendation_records=governance.recommendation_records,
        paper_portfolio_state=state,
        policy=policy,
        historical_market_prices={ticker: {"2026-07-18T23:50:00+00:00": 100.0}},
        benchmark_prices={"start": 100.0, "end": 101.0},
        as_of_timestamp="2026-07-18T23:50:00+00:00",
    )
    return policy, governance.recommendation_records, engine_result


def _approval_for(recommendation_id: str) -> HumanApprovalRecord:
    return HumanApprovalRecord(
        approval_id=sha256(f"approval|{recommendation_id}".encode("utf-8")).hexdigest(),
        recommendation_id=recommendation_id,
        approver_identity="risk",
        approval_decision=HumanApprovalDecision.APPROVE_FOR_PAPER,
        approval_timestamp="2026-07-18T23:50:00+00:00",
        approval_scope="single_recommendation",
        policy_version="paper-governance-v1",
        source_audit_reference="governance-audit",
        reason="manual approval",
        expiration_timestamp="2026-07-21T23:50:00+00:00",
        superseded_by_reference=None,
        status=HumanApprovalStatus.ACTIVE,
    )


def test_persistence_package_boundary_integrity() -> None:
    forbidden_import_prefixes = (
        "engine.research_phase1",
        "engine.phase2_research",
        "engine.phase2_downstream",
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
        "requests",
        "urllib",
        "httpx",
        "psycopg2",
        "pymongo",
        "mysql",
        "postgres",
    )
    forbidden_raw_tokens = (
        "http://",
        "https://",
        "broker",
        "real_account",
        "live_order",
        "execute_order",
        "market_order",
        "cloudsql",
    )

    for path in (REPO_ROOT / "engine" / "phase3" / "paper_portfolio_persistence").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(alias.name.startswith(prefix) for prefix in forbidden_import_prefixes)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(node.module.startswith(prefix) for prefix in forbidden_import_prefixes)
        for token in forbidden_raw_tokens:
            assert token not in source.lower()


def test_ledger_append_only_deterministic_ids_and_hashes() -> None:
    repo = PaperPortfolioRepository(":memory:")
    ledger = PaperPortfolioLedger(repo)

    first = ledger.append_event(
        event_type=PaperEventType.RECOMMENDATION_RECORDED,
        event_timestamp="2026-07-18T23:50:00+00:00",
        effective_timestamp="2026-07-18T23:50:00+00:00",
        aggregate_id="paper-portfolio",
        recommendation_id="r1",
        transaction_id=None,
        payload_version="1.0",
        payload={"recommendation_id": "r1", "status": "DRAFT", "ticker": "RKLB"},
        source_audit_references={"governance": "a1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:00+00:00",
    )
    second = ledger.append_event(
        event_type=PaperEventType.APPROVAL_RECORDED,
        event_timestamp="2026-07-18T23:51:00+00:00",
        effective_timestamp="2026-07-18T23:51:00+00:00",
        aggregate_id="paper-portfolio",
        recommendation_id="r1",
        transaction_id=None,
        payload_version="1.0",
        payload={"approval": "risk"},
        source_audit_references={"governance": "a1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:51:00+00:00",
    )

    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert second.previous_event_hash == first.event_hash

    with pytest.raises(PaperLedgerValidationError):
        ledger.append_event(
            event_type=PaperEventType.APPROVAL_RECORDED,
            event_timestamp="2026-07-18T23:51:00+00:00",
            effective_timestamp="2026-07-18T23:51:00+00:00",
            aggregate_id="paper-portfolio",
            recommendation_id="r1",
            transaction_id=None,
            payload_version="1.0",
            payload={"approval": "risk"},
            source_audit_references={"governance": "a1"},
            provenance={"source": "test"},
            created_timestamp="2026-07-18T23:51:00+00:00",
        )

    events = ledger.read_events()
    assert tuple(event.event_id for event in events) == (first.event_id, second.event_id)
    assert ledger.verify_integrity() == second.event_hash

    export = ledger.export_ledger()
    repo_import = PaperPortfolioRepository(":memory:")
    ledger_import = PaperPortfolioLedger(repo_import)
    ledger_import.import_ledger(export)
    assert ledger_import.verify_integrity() == ledger.verify_integrity()


def test_recovery_fail_closed_conditions() -> None:
    repo = PaperPortfolioRepository(":memory:")
    ledger = PaperPortfolioLedger(repo)

    ledger.append_event(
        event_type=PaperEventType.RECOMMENDATION_RECORDED,
        event_timestamp="2026-07-18T23:50:00+00:00",
        effective_timestamp="2026-07-18T23:50:00+00:00",
        aggregate_id="paper-portfolio",
        recommendation_id="r1",
        transaction_id=None,
        payload_version="1.0",
        payload={"recommendation_id": "r1", "status": "DRAFT", "ticker": "RKLB"},
        source_audit_references={"governance": "a1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:00+00:00",
    )
    ledger.append_event(
        event_type=PaperEventType.APPROVAL_RECORDED,
        event_timestamp="2026-07-18T23:51:00+00:00",
        effective_timestamp="2026-07-18T23:51:00+00:00",
        aggregate_id="paper-portfolio",
        recommendation_id="r1",
        transaction_id=None,
        payload_version="1.0",
        payload={"approval": "risk"},
        source_audit_references={"governance": "a1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:51:00+00:00",
    )

    repo.run_atomic(lambda conn: conn.execute("DELETE FROM events WHERE sequence_number = 1"))
    with pytest.raises(PaperLedgerValidationError):
        ledger.validate_hash_chain()

    repo.run_atomic(lambda conn: conn.execute("UPDATE metadata SET value='2.0' WHERE key='schema_version'"))
    with pytest.raises(PaperPortfolioReplayError):
        PaperPortfolioReplayModel(repo, ledger).replay_from_event_zero()


def test_persistence_and_replay_determinism_checkpoint_equivalence(tmp_path: Path) -> None:
    _, recommendations, engine_result = _build_pipeline()
    db_path = tmp_path / "paper_validation.sqlite"

    repo = PaperPortfolioRepository(db_path)
    ledger = PaperPortfolioLedger(repo)
    persistence = PaperPortfolioPersistenceModel(repo, ledger)
    replay = PaperPortfolioReplayModel(repo, ledger)

    rec = recommendations[0]
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.DRAFT),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:00+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.PENDING_APPROVAL),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:10+00:00",
    )
    approval = _approval_for(rec.recommendation_id)
    persistence.persist_approval(
        approval=approval,
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:20+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:30+00:00",
    )

    lots_first = persistence.persist_engine_result(
        recommendations=(replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),),
        engine_result=engine_result,
        source_audit_references={"engine": "e1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:51:00+00:00",
    )
    checkpoint = replay.build_checkpoint(
        created_timestamp="2026-07-18T23:51:05+00:00",
        source_audit_references={"engine": "e1"},
    )

    replay_result_first = replay.validate_canonical_state()
    replay_result_second = replay.validate_canonical_state()
    assert replay_result_first == replay_result_second
    assert replay_result_first.canonical_match
    assert checkpoint.state_hash == replay_result_first.replay_state_hash

    restore_before_close = persistence.restore_state()
    repo.close()

    reopened = PaperPortfolioRepository(db_path)
    reopened_ledger = PaperPortfolioLedger(reopened)
    reopened_replay = PaperPortfolioReplayModel(reopened, reopened_ledger)

    restored = reopened.load_bundle()
    replay_state = reopened_replay.replay_from_event_zero()
    replay_validation = reopened_replay.validate_canonical_state()
    assert replay_validation.canonical_match
    assert restored.portfolio_state == restore_before_close.portfolio_state
    assert replay_state.latest_state == restored.portfolio_state
    assert replay_state.cash_balance == replay_state.latest_state.paper_cash

    lots_second = restored.tax_lots
    assert lots_first == lots_second
    assert all(lot.status in {TaxLotStatus.OPEN, TaxLotStatus.CLOSED} for lot in lots_second)

    reopened.run_atomic(lambda conn: conn.execute("UPDATE replay_checkpoints SET state_hash='bad'"))
    mismatch = reopened_replay.validate_canonical_state()
    assert not mismatch.canonical_match
    assert "CHECKPOINT_STATE_HASH_MISMATCH" in mismatch.mismatch_reasons


def test_approval_lifecycle_execution_and_invalid_transition_guards(tmp_path: Path) -> None:
    _, recommendations, engine_result = _build_pipeline()
    rec = recommendations[0]

    repo = PaperPortfolioRepository(tmp_path / "transition.sqlite")
    ledger = PaperPortfolioLedger(repo)
    persistence = PaperPortfolioPersistenceModel(repo, ledger)

    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.DRAFT),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:00+00:00",
    )

    with pytest.raises(InvalidLifecycleTransitionError):
        persistence.persist_recommendation_lifecycle(
            recommendation=replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),
            source_audit_references={"governance": "g1"},
            provenance={"source": "test"},
            created_timestamp="2026-07-18T23:50:05+00:00",
        )

    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.PENDING_APPROVAL),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:10+00:00",
    )

    with pytest.raises(PaperPortfolioPersistenceValidationError):
        persistence.persist_engine_result(
            recommendations=(replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),),
            engine_result=engine_result,
            source_audit_references={"engine": "e1"},
            provenance={"source": "test"},
            created_timestamp="2026-07-18T23:50:15+00:00",
        )

    persistence.persist_approval(
        approval=_approval_for(rec.recommendation_id),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:20+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:30+00:00",
    )

    revoke = HumanApprovalRecord(
        approval_id=sha256(f"revoke|{rec.recommendation_id}".encode("utf-8")).hexdigest(),
        recommendation_id=rec.recommendation_id,
        approver_identity="risk",
        approval_decision=HumanApprovalDecision.REVOKE_PAPER_APPROVAL,
        approval_timestamp="2026-07-18T23:50:40+00:00",
        approval_scope="single_recommendation",
        policy_version="paper-governance-v1",
        source_audit_reference="governance-audit",
        reason="revoked",
        expiration_timestamp="2026-07-21T23:50:00+00:00",
        superseded_by_reference=None,
        status=HumanApprovalStatus.REVOKED,
    )
    persistence.persist_approval(
        approval=revoke,
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:40+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.REJECTED),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:45+00:00",
    )

    with pytest.raises(PaperPortfolioPersistenceValidationError):
        persistence.persist_engine_result(
            recommendations=(replace(rec, status=PaperRecommendationStatus.REJECTED),),
            engine_result=engine_result,
            source_audit_references={"engine": "e1"},
            provenance={"source": "test"},
            created_timestamp="2026-07-18T23:51:00+00:00",
        )


def test_corporate_action_pending_blocks_position_updates(tmp_path: Path) -> None:
    _, recommendations, engine_result = _build_pipeline()
    rec = recommendations[0]

    repo = PaperPortfolioRepository(tmp_path / "corp.sqlite")
    ledger = PaperPortfolioLedger(repo)
    persistence = PaperPortfolioPersistenceModel(repo, ledger)

    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.DRAFT),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:00+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.PENDING_APPROVAL),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:10+00:00",
    )
    persistence.persist_approval(
        approval=_approval_for(rec.recommendation_id),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:20+00:00",
    )
    persistence.persist_recommendation_lifecycle(
        recommendation=replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:30+00:00",
    )

    action = CorporateActionRecord(
        action_id=sha256(b"ca-1").hexdigest(),
        ticker=rec.ticker,
        action_type=CorporateActionType.STOCK_SPLIT,
        effective_timestamp="2026-07-18T23:55:00+00:00",
        payload={"ratio": "2:1"},
        validated=False,
        source_audit_reference="corp-action-audit",
        created_timestamp="2026-07-18T23:54:00+00:00",
    )
    persistence.persist_corporate_action_pending(
        record=action,
        source_audit_references={"governance": "g1"},
        provenance={"source": "test"},
    )

    with pytest.raises(PaperPortfolioPersistenceValidationError):
        persistence.persist_engine_result(
            recommendations=(replace(rec, status=PaperRecommendationStatus.APPROVED_FOR_PAPER),),
            engine_result=engine_result,
            source_audit_references={"engine": "e1"},
            provenance={"source": "test"},
            created_timestamp="2026-07-18T23:56:00+00:00",
        )


def test_interrupted_write_rollback_and_corruption_detection(tmp_path: Path) -> None:
    repo = PaperPortfolioRepository(tmp_path / "recovery.sqlite")
    ledger = PaperPortfolioLedger(repo)

    def broken(conn: sqlite3.Connection):
        conn.execute(
            "INSERT INTO recommendation_records(recommendation_id, ticker, status, payload_json, updated_timestamp) VALUES (?, ?, ?, ?, ?)",
            ("r1", "RKLB", "DRAFT", "{}", "2026-07-18T23:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO recommendation_records(recommendation_id, ticker, status, payload_json, updated_timestamp) VALUES (?, ?, ?, ?, ?)",
            ("r1", "RKLB", "DRAFT", "{}", "2026-07-18T23:00:00+00:00"),
        )

    with pytest.raises(sqlite3.IntegrityError):
        repo.run_atomic(broken)

    rows = repo.conn.execute("SELECT COUNT(1) AS cnt FROM recommendation_records").fetchone()
    assert rows is not None
    assert int(rows["cnt"]) == 0

    ledger.append_event(
        event_type=PaperEventType.RECOMMENDATION_RECORDED,
        event_timestamp="2026-07-18T23:50:00+00:00",
        effective_timestamp="2026-07-18T23:50:00+00:00",
        aggregate_id="paper-portfolio",
        recommendation_id="r1",
        transaction_id=None,
        payload_version="1.0",
        payload={"recommendation_id": "r1", "status": "DRAFT", "ticker": "RKLB"},
        source_audit_references={"governance": "a1"},
        provenance={"source": "test"},
        created_timestamp="2026-07-18T23:50:00+00:00",
    )

    repo.conn.execute("PRAGMA wal_checkpoint(FULL)")
    repo.close()

    copied = tmp_path / "corrupt.sqlite"
    shutil.copy2(tmp_path / "recovery.sqlite", copied)
    wal_src = tmp_path / "recovery.sqlite-wal"
    if wal_src.exists():
        shutil.copy2(wal_src, tmp_path / "corrupt.sqlite-wal")
    shm_src = tmp_path / "recovery.sqlite-shm"
    if shm_src.exists():
        shutil.copy2(shm_src, tmp_path / "corrupt.sqlite-shm")
    corrupt_repo = PaperPortfolioRepository(copied)
    corrupt_ledger = PaperPortfolioLedger(corrupt_repo)
    corrupt_repo.run_atomic(lambda conn: conn.execute("UPDATE events SET event_hash='CORRUPTED' WHERE sequence_number=1"))
    with pytest.raises(PaperLedgerValidationError):
        corrupt_ledger.validate_hash_chain()


def test_immutability_and_frozen_hashes_remain_unchanged() -> None:
    sample = _approval_for("r1")
    with pytest.raises(FrozenInstanceError):
        sample.reason = "mutate"  # type: ignore[misc]

    for relative_path, expected_hash in FROZEN_HASHES.items():
        actual = _sha(REPO_ROOT / relative_path)
        assert actual == expected_hash, f"Frozen hash mismatch: {relative_path}"

    for relative_path, expected_hash in MILESTONE_HASHES.items():
        actual = _sha(REPO_ROOT / relative_path)
        assert actual == expected_hash, f"Milestone hash mismatch: {relative_path}"
