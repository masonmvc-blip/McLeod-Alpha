from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import shutil
import sqlite3
from typing import Mapping

from engine.phase3.paper_portfolio_persistence import PaperPortfolioLedger, PaperPortfolioReplayModel, PaperPortfolioRepository


class PaperBackupError(ValueError):
    pass


@dataclass(frozen=True)
class PaperBackupManifest:
    backup_name: str
    backup_path: str
    created_timestamp: str
    schema_version: str
    ledger_head_hash: str
    canonical_state_hash: str
    backup_file_hash: str
    row_counts: Mapping[str, int]


class PaperBackupManager:
    def __init__(self, repo_path: Path, backup_dir: Path) -> None:
        self.repo_path = Path(repo_path)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(
        self,
        *,
        created_timestamp: str,
        repository: PaperPortfolioRepository,
        ledger: PaperPortfolioLedger,
        replay: PaperPortfolioReplayModel,
    ) -> PaperBackupManifest:
        head_hash = ledger.verify_integrity()
        state_hash = repository.get_latest_state_hash()
        ts = created_timestamp.replace("-", "").replace(":", "")
        backup_name = f"paper_backup_{ts}_{head_hash[:12]}.sqlite"
        backup_path = self.backup_dir / backup_name

        src = sqlite3.connect(str(self.repo_path))
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        file_hash = self._canonical_backup_hash(backup_path)
        row_counts = self._row_counts(backup_path)
        manifest = PaperBackupManifest(
            backup_name=backup_name,
            backup_path=str(backup_path),
            created_timestamp=created_timestamp,
            schema_version=repository.schema_version(),
            ledger_head_hash=head_hash,
            canonical_state_hash=state_hash,
            backup_file_hash=file_hash,
            row_counts=row_counts,
        )
        self._write_manifest(manifest)
        return manifest

    def verify_backup(self, manifest: PaperBackupManifest) -> bool:
        backup_path = Path(manifest.backup_path)
        if not backup_path.exists():
            return False
        actual_hash = self._canonical_backup_hash(backup_path)
        if actual_hash != manifest.backup_file_hash:
            return False

        repo = PaperPortfolioRepository(backup_path)
        ledger = PaperPortfolioLedger(repo)
        replay = PaperPortfolioReplayModel(repo, ledger)
        try:
            if repo.schema_version() != manifest.schema_version:
                return False
            if ledger.verify_integrity() != manifest.ledger_head_hash:
                return False
            if repo.get_latest_state_hash() != manifest.canonical_state_hash:
                return False
            validation = replay.validate_canonical_state()
            return validation.canonical_match
        finally:
            repo.close()

    def test_restore(self, *, manifest: PaperBackupManifest, temp_root: Path) -> bool:
        temp_root = Path(temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        restored_path = temp_root / "restored_paper.sqlite"
        try:
            shutil.copy2(manifest.backup_path, restored_path)
            repo = PaperPortfolioRepository(restored_path)
            ledger = PaperPortfolioLedger(repo)
            replay = PaperPortfolioReplayModel(repo, ledger)
            try:
                if ledger.verify_integrity() != manifest.ledger_head_hash:
                    return False
                if repo.get_latest_state_hash() != manifest.canonical_state_hash:
                    return False
                validation = replay.validate_canonical_state()
                return validation.canonical_match
            finally:
                repo.close()
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def _write_manifest(self, manifest: PaperBackupManifest) -> None:
        path = self.backup_dir / f"{manifest.backup_name}.manifest.json"
        payload = {
            "backup_name": manifest.backup_name,
            "backup_path": manifest.backup_path,
            "created_timestamp": manifest.created_timestamp,
            "schema_version": manifest.schema_version,
            "ledger_head_hash": manifest.ledger_head_hash,
            "canonical_state_hash": manifest.canonical_state_hash,
            "backup_file_hash": manifest.backup_file_hash,
            "row_counts": dict(sorted(manifest.row_counts.items())),
        }
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, indent=2))

    def _row_counts(self, db_path: Path) -> Mapping[str, int]:
        conn = sqlite3.connect(str(db_path))
        try:
            tables = [
                "events",
                "recommendation_records",
                "approvals",
                "paper_transactions",
                "paper_positions",
                "performance_snapshots",
                "portfolio_states",
                "portfolio_audits",
                "replay_checkpoints",
                "tax_lots",
            ]
            counts = {}
            for name in tables:
                row = conn.execute(f"SELECT COUNT(1) FROM {name}").fetchone()
                counts[name] = int(row[0]) if row else 0
            return dict(sorted(counts.items()))
        finally:
            conn.close()

    def _canonical_backup_hash(self, db_path: Path) -> str:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            tables = [
                "metadata",
                "events",
                "recommendation_records",
                "approvals",
                "paper_transactions",
                "paper_positions",
                "performance_snapshots",
                "portfolio_states",
                "portfolio_audits",
                "replay_checkpoints",
                "tax_lots",
                "corporate_actions",
            ]
            dump = {}
            for table in tables:
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                dump[table] = [dict(row) for row in rows]
            canonical = json.dumps(dump, sort_keys=True, separators=(",", ":"), default=str)
            return sha256(canonical.encode("utf-8")).hexdigest()
        finally:
            conn.close()
