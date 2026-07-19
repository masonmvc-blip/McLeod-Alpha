from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from engine.data_quality import ArtifactConflictError, audit_historical_sources
from tools.audit_historical_sources import main as cli_main


REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY = REPO_ROOT / "tests/fixtures/historical_coverage_policy.json"


def _record(symbol: str, field: str, value: str, **extra: object) -> dict[str, object]:
    return {"symbol": symbol, field: value, "source_metadata": {"provider": "fixture"}, **extra}


def _raw(root: Path, *, missing_price: bool = False, missing_fundamentals: bool = False) -> Path:
    payloads = {
        "sec": [_record("AAPL", "filing_date", "2024-01-02")],
        "prices": [_record("AAPL", "price_date", day, close=1) for day in ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")],
        "fundamentals": [_record("AAPL", "available_date", "2024-01-02", revenue=1)],
        "macro": [{"release_date": "2024-01-02", "series": "CPI", "source_metadata": {"provider": "fixture"}}],
        "analysts": [_record("AAPL", "revision_date", "2024-01-02")],
        "news": [_record("AAPL", "published_at", "2024-01-02")],
        "universes": [_record("AAPL", "membership_date", "2024-01-02", effective_from="2024-01-02", effective_to="2024-01-05")],
    }
    if missing_price:
        payloads["prices"] = payloads["prices"][:2]
    if missing_fundamentals:
        payloads["fundamentals"] = []
    for source, records in payloads.items():
        path = root / source
        path.mkdir(parents=True)
        (path / "records.json").write_text(json.dumps(records), encoding="utf-8")
    return root


def _audit(tmp_path: Path, root: Path, **kwargs: object):
    return audit_historical_sources(source_root=root, policy_path=POLICY, symbols=("AAPL",), start_date="2024-01-02", end_date="2024-01-05", frequency="daily", output_root=tmp_path / "artifacts", **kwargs)


def test_complete_coverage_is_ready_and_deterministic(tmp_path: Path) -> None:
    root = _raw(tmp_path / "raw")
    first = _audit(tmp_path, root)
    second = _audit(tmp_path, root)
    assert first.status == "READY" and first.audit_id == second.audit_id
    assert (Path(first.output_path) / "audit_manifest.json").is_file()


def test_partial_price_missing_fundamentals_and_policy_thresholds(tmp_path: Path) -> None:
    assert _audit(tmp_path, _raw(tmp_path / "partial", missing_price=True)).status == "PARTIAL"
    assert _audit(tmp_path, _raw(tmp_path / "missing", missing_fundamentals=True)).status == "NOT_READY"


def test_event_driven_stale_and_universe_inactive_gap_classification(tmp_path: Path) -> None:
    root = _raw(tmp_path / "raw", missing_price=True)
    universes = json.loads((root / "universes" / "records.json").read_text())
    universes[0]["effective_to"] = "2024-01-03"
    (root / "universes" / "records.json").write_text(json.dumps(universes), encoding="utf-8")
    result = _audit(tmp_path, root)
    gaps = json.loads((Path(result.output_path) / "gap_report.json").read_text()) ["gaps"]
    assert any(gap["classification"] == "EXPECTED_EVENT_DRIVEN" for gap in gaps) is False
    assert any(gap["classification"] == "STALE" for gap in gaps)
    assert any(gap["classification"] == "UNIVERSE_NOT_ACTIVE" for gap in gaps)


def test_invalid_nested_future_conflicts_and_hash_consistency(tmp_path: Path) -> None:
    root = _raw(tmp_path / "raw")
    prices = root / "prices" / "records.json"
    rows = json.loads(prices.read_text())
    rows[0]["nested"] = {"reported_at": "2024-01-03"}
    rows.append(dict(rows[1], close=99))
    prices.write_text(json.dumps(rows), encoding="utf-8")
    result = _audit(tmp_path, root)
    assert result.status == "LOOKAHEAD_FAILURE"
    assert result.lookahead_failures

    malformed = _raw(tmp_path / "malformed")
    values = json.loads((malformed / "prices" / "records.json").read_text())
    values[0]["price_date"] = "bad"
    (malformed / "prices" / "records.json").write_text(json.dumps(values), encoding="utf-8")
    assert _audit(tmp_path, malformed).status == "PARTIAL"


def test_universe_file_artifact_conflict_and_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _raw(tmp_path / "raw")
    output = tmp_path / "artifacts"
    args = ["--source-root", str(root), "--policy", str(POLICY), "--symbols", "AAPL", "--start-date", "2024-01-02", "--end-date", "2024-01-05", "--frequency", "daily", "--output-root", str(output)]
    assert cli_main(args) == 0
    assert [line.split("=", 1)[0] for line in capsys.readouterr().out.splitlines()] == ["audit_id", "status", "symbols_ready", "symbols_partial", "symbols_not_ready", "lookahead_failures", "output_path"]
    audit = _audit(tmp_path, root)
    (Path(audit.output_path) / "coverage_report.md").write_text("conflict", encoding="utf-8")
    with pytest.raises(ArtifactConflictError):
        _audit(tmp_path, root)
    assert cli_main(args) == 5
    invalid_args = [*args]
    invalid_args[invalid_args.index("--policy") + 1] = str(tmp_path / "missing-policy.json")
    assert cli_main(invalid_args) == 4


def test_source_hash_consistency_and_nonready_cli_codes(tmp_path: Path) -> None:
    root = _raw(tmp_path / "raw")
    (root / "import_manifest.json").write_text(json.dumps({"source_hashes": {"prices": "incorrect"}}), encoding="utf-8")
    assert _audit(tmp_path, root).status == "NOT_READY"

    partial_root = _raw(tmp_path / "partial", missing_price=True)
    partial_args = ["--source-root", str(partial_root), "--policy", str(POLICY), "--symbols", "AAPL", "--start-date", "2024-01-02", "--end-date", "2024-01-05", "--frequency", "daily", "--output-root", str(tmp_path / "partial_artifacts")]
    assert cli_main(partial_args) == 1
    missing_root = _raw(tmp_path / "missing", missing_fundamentals=True)
    missing_args = ["--source-root", str(missing_root), "--policy", str(POLICY), "--symbols", "AAPL", "--start-date", "2024-01-02", "--end-date", "2024-01-05", "--frequency", "daily", "--output-root", str(tmp_path / "missing_artifacts")]
    assert cli_main(missing_args) == 2
    lookahead_root = _raw(tmp_path / "lookahead")
    values = json.loads((lookahead_root / "prices" / "records.json").read_text())
    values[0]["nested"] = {"reported_at": "2024-01-03"}
    (lookahead_root / "prices" / "records.json").write_text(json.dumps(values), encoding="utf-8")
    lookahead_args = ["--source-root", str(lookahead_root), "--policy", str(POLICY), "--symbols", "AAPL", "--start-date", "2024-01-02", "--end-date", "2024-01-05", "--frequency", "daily", "--output-root", str(tmp_path / "lookahead_artifacts")]
    assert cli_main(lookahead_args) == 3


def test_auditor_does_not_import_protected_engines() -> None:
    forbidden = ("engine.replay", "engine.research", "decision", "thesis", "portfolio", "performance", "validation", "certification")
    for path in (REPO_ROOT / "engine/data_quality").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden)
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith(forbidden) for alias in node.names)