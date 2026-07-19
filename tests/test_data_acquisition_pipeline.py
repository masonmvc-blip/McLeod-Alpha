from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from engine.data_sources import AnalystConnector, FundamentalsConnector, MacroConnector, NewsConnector, PriceConnector, SECConnector, SourceValidationError
from engine.datasets.dataset_assembler import DatasetAssembler
from tools.build_historical_dataset import main as cli_main


CONNECTORS = (
    (SECConnector, "sec", "filing_date", "sec_filings"),
    (PriceConnector, "prices", "price_date", "prices"),
    (FundamentalsConnector, "fundamentals", "available_date", "company_fundamentals"),
    (MacroConnector, "macro", "release_date", "macro_data"),
    (AnalystConnector, "analysts", "revision_date", "analyst_estimates"),
    (NewsConnector, "news", "published_at", "evidence"),
)
REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_source(root: Path, directory: str, records: list[dict]) -> None:
    path = root / directory
    path.mkdir(parents=True, exist_ok=True)
    (path / "records.json").write_text(json.dumps({"records": list(reversed(records))}), encoding="utf-8")


def _raw_sources(root: Path) -> Path:
    payloads = {
        "sec": [{"symbol": "AAPL", "filing_date": "2024-01-02", "form": "8-K"}, {"symbol": "AAPL", "filing_date": "2024-01-03", "form": "10-Q"}],
        "prices": [{"symbol": "AAPL", "price_date": "2024-01-02", "close": 185.0}, {"symbol": "AAPL", "price_date": "2024-01-03", "close": 186.0}],
        "fundamentals": [{"symbol": "AAPL", "available_date": "2024-01-02", "revenue": 100.0}],
        "macro": [{"release_date": "2024-01-02", "series": "CPI", "value": 3.4}],
        "analysts": [{"symbol": "AAPL", "revision_date": "2024-01-02", "eps_estimate": 2.1}],
        "news": [{"symbol": "AAPL", "published_at": "2024-01-02", "evidence_id": "news-1", "headline": "Local fixture"}],
    }
    for directory, records in payloads.items():
        _write_source(root, directory, records)
    return root


@pytest.mark.parametrize("connector_cls,directory,date_field,source_name", CONNECTORS)
def test_each_connector_contract_filters_orders_hashes_and_freezes(tmp_path: Path, connector_cls, directory: str, date_field: str, source_name: str) -> None:
    root = tmp_path / "raw"
    _write_source(root, directory, [
        {"symbol": "MSFT", date_field: "2024-01-02", "value": 2},
        {"symbol": "AAPL", date_field: "2024-01-02", "value": 1},
        {"symbol": "AAPL", date_field: "2024-01-03", "value": 3},
    ])
    connector = connector_cls()
    first = connector.fetch("2024-01-02", ("MSFT", "AAPL"), root)
    second = connector.fetch("2024-01-02", ("AAPL", "MSFT"), root)
    assert first.source_name == source_name
    assert first.source_hash == second.source_hash
    assert [record["symbol"] for record in first.records] == ["AAPL", "MSFT"]
    with pytest.raises(TypeError):
        first.records[0]["value"] = 99  # type: ignore[index]


def test_connector_rejects_malformed_and_nested_future_dates(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    _write_source(root, "sec", [{"symbol": "AAPL", "filing_date": "not-a-date", "form": "8-K"}])
    with pytest.raises(SourceValidationError, match="malformed filing_date"):
        SECConnector().fetch("2024-01-02", ("AAPL",), root)

    _write_source(root, "sec", [{"symbol": "AAPL", "filing_date": "2024-01-02", "earnings": {"reported_at": "2024-01-03"}}])
    with pytest.raises(SourceValidationError, match="future date"):
        SECConnector().fetch("2024-01-02", ("AAPL",), root)


def test_assembler_preserves_lineage_and_builds_byte_identical_datasets(tmp_path: Path) -> None:
    source_root = _raw_sources(tmp_path / "raw")
    assembler = DatasetAssembler()
    snapshots = assembler.assemble_snapshots(dates=("2024-01-02", "2024-01-03"), symbols=("AAPL",), source_root=source_root)
    assert tuple(snapshots[0]) == (
        "snapshot_id", "snapshot_date", "company_fundamentals", "sec_filings", "macro_data", "prices", "analyst_estimates", "evidence", "source_lineage", "content_hash",
    )
    assert set(snapshots[0]["source_lineage"]) == {item[3] for item in CONNECTORS}
    assert all(len(value["source_hash"]) == 64 for value in snapshots[0]["source_lineage"].values())
    assert snapshots == assembler.assemble_snapshots(dates=("2024-01-03", "2024-01-02"), symbols=("AAPL",), source_root=source_root)

    first, second = tmp_path / "first", tmp_path / "second"
    assembler.build(output_dir=first, dataset_id="hist-aapl", dataset_name="AAPL", market="US", dates=("2024-01-02", "2024-01-03"), symbols=("AAPL",), source_root=source_root)
    assembler.build(output_dir=second, dataset_id="hist-aapl", dataset_name="AAPL", market="US", dates=("2024-01-02", "2024-01-03"), symbols=("AAPL",), source_root=source_root)
    assert {str(path.relative_to(first)): path.read_bytes() for path in first.rglob("*") if path.is_file()} == {str(path.relative_to(second)): path.read_bytes() for path in second.rglob("*") if path.is_file()}


def _cli_args(source_root: Path, output: Path) -> list[str]:
    return ["--source-root", str(source_root), "--output", str(output), "--dataset-id", "hist-aapl", "--dataset-name", "AAPL", "--market", "US", "--symbols", "AAPL", "--start-date", "2024-01-02", "--end-date", "2024-01-03"]


def test_cli_validate_only_output_conflict_and_hash_stability(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source_root = _raw_sources(tmp_path / "raw")
    output = tmp_path / "dataset"
    assert cli_main([*_cli_args(source_root, output), "--validate-only"]) == 0
    validate_output = capsys.readouterr().out.strip().splitlines()
    assert len(validate_output) == 4 and not output.exists()
    assert cli_main(_cli_args(source_root, output)) == 0
    build_output = capsys.readouterr().out.strip().splitlines()
    assert validate_output[2] == build_output[2]
    _write_source(source_root, "prices", [{"symbol": "AAPL", "price_date": "2024-01-02", "close": 1.0}])
    assert cli_main(_cli_args(source_root, output)) == 4
    assert cli_main(["--source-root", str(source_root), "--output", str(tmp_path / "bad"), "--dataset-id", "x", "--dataset-name", "x", "--market", "US", "--symbols", "AAPL", "--start-date", "bad", "--end-date", "2024-01-03"]) == 2


def test_acquisition_modules_do_not_import_replay_or_protected_engines() -> None:
    forbidden = ("engine.replay", "engine.research", "engine.cio", "portfolio", "validation", "certification", "decision", "thesis", "performance")
    paths = [*sorted((REPO_ROOT / "engine" / "data_sources").glob("*_connector.py")), REPO_ROOT / "engine" / "data_sources" / "source_contract.py", REPO_ROOT / "engine" / "datasets" / "dataset_assembler.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden)
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith(forbidden) for alias in node.names)