from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import ast
import json
from typing import Mapping, Sequence

from engine.phase3.paper_portfolio_governance import PaperRecommendationPolicy
from engine.phase3.paper_portfolio_persistence import PaperPortfolioLedger, PaperPortfolioReplayModel, PaperPortfolioRepository

from .types import PaperOperationsPolicy, PaperOperationsPreflightResult


class PaperOperationsPreflightError(ValueError):
    pass


class PaperOperationsPreflightModel:
    FORBIDDEN_IMPORT_PREFIXES = (
        "alpaca",
        "schwab",
        "ib_insync",
        "ccxt",
    )

    def __init__(
        self,
        *,
        policy: PaperOperationsPolicy,
        repository: PaperPortfolioRepository,
        ledger: PaperPortfolioLedger,
        replay: PaperPortfolioReplayModel,
        repo_root: Path,
    ) -> None:
        self.policy = policy
        self.repository = repository
        self.ledger = ledger
        self.replay = replay
        self.repo_root = repo_root

    def evaluate(
        self,
        *,
        current_timestamp: str,
        latest_price_data_timestamp: str,
        recommendation_timestamps: Mapping[str, str],
        frozen_hashes: Mapping[str, str],
        backup_count: int,
        latest_restore_test_passed: bool,
        hygiene_passed: bool,
        operator_approval_present: bool,
    ) -> PaperOperationsPreflightResult:
        self.policy.validate()

        checks: dict[str, bool] = {}
        blockers: list[str] = []
        warnings: list[str] = []

        checks["milestones"] = self._check_milestones()
        checks["frozen_hashes"] = self._check_frozen_hashes(frozen_hashes)
        checks["hygiene"] = bool(hygiene_passed)

        try:
            PaperRecommendationPolicy.default().validate()
            checks["governance_policy"] = True
        except Exception:
            checks["governance_policy"] = False

        checks["paper_engine"] = True

        try:
            head_hash = self.ledger.verify_integrity()
            checks["ledger_integrity"] = True
        except Exception:
            head_hash = "INVALID"
            checks["ledger_integrity"] = False

        try:
            replay_validation = self.replay.validate_canonical_state()
            checks["replay_vs_canonical"] = replay_validation.canonical_match
            checks["checkpoint_match"] = all(
                reason not in replay_validation.mismatch_reasons
                for reason in ("CHECKPOINT_STATE_HASH_MISMATCH", "CHECKPOINT_LEDGER_HEAD_MISMATCH")
            )
        except Exception:
            replay_validation = None
            checks["replay_vs_canonical"] = False
            checks["checkpoint_match"] = False

        checks["reconciliation"] = self._reconcile_cash_positions(tolerance=self.policy.reconciliation_tolerance)
        checks["corporate_actions"] = self._check_corporate_actions_clear()
        checks["recommendation_executability"] = self._check_non_executable_statuses()
        checks["approvals"] = self._check_required_approvals(operator_approval_present=operator_approval_present)
        checks["price_freshness"] = self._check_age_minutes(
            current_timestamp=current_timestamp,
            data_timestamp=latest_price_data_timestamp,
            max_age_minutes=self.policy.maximum_price_data_age_minutes,
        )
        checks["recommendation_freshness"] = all(
            self._check_age_minutes(
                current_timestamp=current_timestamp,
                data_timestamp=ts,
                max_age_minutes=self.policy.maximum_recommendation_age_minutes,
            )
            for ts in recommendation_timestamps.values()
        ) if recommendation_timestamps else True

        checkpoints = self.repository.get_checkpoints()
        checks["checkpoint_freshness"] = True
        if checkpoints:
            checks["checkpoint_freshness"] = self._check_age_minutes(
                current_timestamp=current_timestamp,
                data_timestamp=checkpoints[-1].created_timestamp,
                max_age_minutes=self.policy.maximum_checkpoint_age_minutes,
            )

        checks["backups"] = backup_count >= self.policy.minimum_backup_count
        checks["restore_test"] = bool(latest_restore_test_passed)
        checks["schema_version"] = self.repository.schema_version() == "1.0"
        checks["operating_window"] = self._check_operating_window(current_timestamp)
        checks["access_path_scan"] = self._scan_forbidden_access_paths()

        for key, passed in checks.items():
            if not passed:
                blockers.append(f"PREFLIGHT_{key.upper()}_FAILED")

        if checks["checkpoint_freshness"] is False:
            warnings.append("CHECKPOINT_STALE")

        latest_state_hash = "UNKNOWN"
        latest_checkpoint_sequence = 0
        try:
            latest_state_hash = self.repository.get_latest_state_hash()
        except Exception:
            blockers.append("LATEST_STATE_HASH_UNAVAILABLE")

        if checkpoints:
            latest_checkpoint_sequence = checkpoints[-1].sequence_number

        audit_reference = sha256(
            json.dumps(
                {
                    "checks": checks,
                    "blockers": blockers,
                    "warnings": warnings,
                    "head_hash": head_hash,
                    "state_hash": latest_state_hash,
                    "latest_checkpoint_sequence": latest_checkpoint_sequence,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        return PaperOperationsPreflightResult(
            passed=not blockers,
            checks=dict(sorted(checks.items())),
            blockers=tuple(sorted(set(blockers))),
            warnings=tuple(sorted(set(warnings))),
            latest_ledger_hash=head_hash,
            latest_state_hash=latest_state_hash,
            latest_checkpoint_sequence=latest_checkpoint_sequence,
            audit_reference=audit_reference,
        )

    def _check_milestones(self) -> bool:
        for marker in self.policy.required_milestone_markers:
            path = self.repo_root / marker
            if not path.exists():
                return False
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return False
            if not isinstance(payload, dict) or "milestone" not in payload:
                return False
        return True

    def _check_frozen_hashes(self, frozen_hashes: Mapping[str, str]) -> bool:
        for relative_path, expected_hash in frozen_hashes.items():
            path = self.repo_root / relative_path
            if not path.exists():
                return False
            actual_hash = sha256(path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                return False
        return True

    def _reconcile_cash_positions(self, tolerance: float) -> bool:
        bundle = self.repository.load_bundle()
        nav = bundle.portfolio_state.total_paper_value
        if nav <= 0:
            return False
        position_sum = sum(row.market_value for row in bundle.positions)
        total = position_sum + bundle.portfolio_state.paper_cash
        return abs(total - nav) <= tolerance

    def _check_corporate_actions_clear(self) -> bool:
        for position in self.repository.get_positions():
            if self.repository.ticker_has_unvalidated_corporate_action(position.ticker):
                return False
        return True

    def _check_non_executable_statuses(self) -> bool:
        status_by_recommendation = {row.recommendation_id: row.status.value for row in self.repository.get_recommendations()}
        forbidden = {"REJECTED", "EXPIRED", "SUPERSEDED", "BLOCKED"}
        for tx in self.repository.get_transactions():
            if status_by_recommendation.get(tx.recommendation_id) in forbidden:
                return False
        return True

    def _check_required_approvals(self, operator_approval_present: bool) -> bool:
        if not operator_approval_present:
            return False
        approvals = self.repository.get_approvals()
        active_approvers = {row.approver_identity.lower() for row in approvals if row.status.value == "ACTIVE"}
        required = {name.lower() for name in self.policy.required_operator_approvals}
        return required.issubset(active_approvers)

    def _check_age_minutes(self, *, current_timestamp: str, data_timestamp: str, max_age_minutes: int) -> bool:
        now = datetime.fromisoformat(current_timestamp)
        then = datetime.fromisoformat(data_timestamp)
        age_minutes = (now - then).total_seconds() / 60.0
        return age_minutes <= float(max_age_minutes)

    def _check_operating_window(self, timestamp: str) -> bool:
        dt = datetime.fromisoformat(timestamp)
        minute_of_day = dt.hour * 60 + dt.minute
        for window in self.policy.allowed_operating_windows:
            start, end = window.split("-")
            sh, sm = [int(v) for v in start.split(":")]
            eh, em = [int(v) for v in end.split(":")]
            start_minute = sh * 60 + sm
            end_minute = eh * 60 + em
            if start_minute <= minute_of_day <= end_minute:
                return True
        return False

    def _scan_forbidden_access_paths(self) -> bool:
        for path in (self.repo_root / "engine" / "phase3" / "paper_portfolio_operations").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                            return False
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(self.FORBIDDEN_IMPORT_PREFIXES):
                        return False
        return True
