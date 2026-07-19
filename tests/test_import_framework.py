from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from engine.importers import AnalystImporter, FundamentalsImporter, MacroImporter, NewsImporter, PriceImporter, SECImporter, UniverseImporter
from engine.importers.import_contract import ImportValidationError, import_all
from tools.import_historical_sources import main as cli_main


IMPORTERS = (SECImporter(), PriceImporter(), FundamentalsImporter(), MacroImporter(), AnalystImporter(), NewsImporter(), UniverseImporter())


def _record(*, symbol: str | None = "AAPL", date_field: str, date_value: str = "2024-01-02", **extra: object) -> dict[str, object]:
    record: dict[str, object] = {date_field: date_value, "source_metadata": {"provider": "verified-archive", "document_id": f"{date_field}-1"}, **extra}
    if symbol is not None:
        record["symbol"] = symbol
    return record


def _input_root(root: Path) -> Path:
    (root / "sec").mkdir(parents=True)
    (root / "prices").mkdir()
    (root / "fundamentals").mkdir()
    (root / "macro").mkdir()
    (root / "analysts").mkdir()
    (root / "news").mkdir()
    (root / "universes").mkdir()
    (root / "sec" / "records.json").write_text(json.dumps([_record(date_field="filing_date", form="8-K")]), encoding="utf-8")
    with (root / "prices" / "records.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "price_date", "close", "source_metadata"))
        writer.writeheader()
        writer.writerow({"symbol": "aapl", "price_date": "2024-01-02", "close": "185.0", "source_metadata": json.dumps({"provider": "verified-archive", "document_id": "price-1"})})
    (root / "fundamentals" / "records.jsonl").write_text(json.dumps(_record(date_field="available_date", revenue=100.0)) + "\n", encoding="utf-8")
    (root / "macro" / "records.json").write_text(json.dumps({"records": [_record(symbol=None, date_field="release_date", series="CPI", value=3.4)]}), encoding="utf-8")
    (root / "analysts" / "records.json").write_text(json.dumps([_record(date_field="revision_date", eps=2.0)]), encoding="utf-8")
    (root / "news" / "records.json").write_text(json.dumps([_record(date_field="published_at", headline="Archived release")]), encoding="utf-8")
    (root / "universes" / "records.json").write_text(json.dumps([_record(date_field="membership_date", index="S&P 500")]), encoding="utf-8")
    return root


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_csv_json_and_jsonl_import_into_raw_source_layout(tmp_path: Path) -> None:
    report = import_all(input_root=_input_root(tmp_path / "input"), output_root=tmp_path / "raw_sources", importers=IMPORTERS)
    assert report.imported_records == 7
    assert report.rejected_records == 0
    assert (tmp_path / "raw_sources" / "prices" / "records.jsonl").is_file()
    price = json.loads((tmp_path / "raw_sources" / "prices" / "records.jsonl").read_text(encoding="utf-8"))
    assert price["symbol"] == "AAPL"
    assert price["price_date"] == "2024-01-02"
    assert len(price["record_hash"]) == 64
    manifest = json.loads((tmp_path / "raw_sources" / "import_manifest.json").read_text(encoding="utf-8"))
    assert sorted(manifest["source_hashes"]) == ["analysts", "fundamentals", "macro", "news", "prices", "sec", "universes"]


def test_duplicate_and_malformed_records_fail_closed_with_strict_report(tmp_path: Path) -> None:
    input_root = _input_root(tmp_path / "input")
    duplicate = _record(date_field="filing_date", form="8-K")
    (input_root / "sec" / "records.json").write_text(json.dumps([duplicate, duplicate]), encoding="utf-8")
    with pytest.raises(ImportValidationError) as captured:
        import_all(input_root=input_root, output_root=tmp_path / "raw_sources", importers=IMPORTERS)
    assert captured.value.report.rejected_records == 1
    assert captured.value.report.duplicate_records
    assert not (tmp_path / "raw_sources").exists()

    malformed_root = _input_root(tmp_path / "malformed")
    (malformed_root / "news" / "records.json").write_text(
        json.dumps([
            {"symbol": "AAPL", "published_at": "not-a-date", "source_metadata": {"provider": "verified"}},
            {"symbol": "AAPL", "published_at": "2024-01-02"},
        ]),
        encoding="utf-8",
    )
    with pytest.raises(ImportValidationError) as malformed:
        import_all(input_root=malformed_root, output_root=tmp_path / "bad", importers=IMPORTERS)
    assert malformed.value.report.malformed_records
    assert malformed.value.report.missing_required_fields


def test_imports_are_deterministic_and_byte_identical_on_rerun(tmp_path: Path) -> None:
    input_root = _input_root(tmp_path / "input")
    first, second = tmp_path / "first", tmp_path / "second"
    import_all(input_root=input_root, output_root=first, importers=IMPORTERS)
    rerun = import_all(input_root=input_root, output_root=first, importers=IMPORTERS)
    import_all(input_root=input_root, output_root=second, importers=IMPORTERS)
    assert rerun.imported_records == 7
    assert _files(first) == _files(second)


def test_cli_import_and_output_conflict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_root = _input_root(tmp_path / "input")
    output = tmp_path / "raw_sources"
    assert cli_main(["--input", str(input_root), "--output", str(output)]) == 0
    assert "imported_records=7" in capsys.readouterr().out
    assert cli_main(["--input", str(input_root), "--output", str(output)]) == 0
    _write = (input_root / "prices" / "records.csv")
    _write.write_text("symbol,price_date,close,source_metadata\nAAPL,2024-01-02,1.0,\"{\"\"provider\"\":\"\"verified\"\"}\"\n", encoding="utf-8")
    assert cli_main(["--input", str(input_root), "--output", str(output)]) == 3