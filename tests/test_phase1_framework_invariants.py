from __future__ import annotations

import ast
import json
from pathlib import Path

import engine.research_phase1 as phase1


COMPLETED_TICKERS = ["VBNK", "CRWD", "OPRA", "NBIS", "ARTV"]


def _prepare_tmp_layout(monkeypatch, tmp_path: Path) -> None:
    data = tmp_path / "data"
    research = data / "research"
    monkeypatch.setattr(phase1, "WORKSPACE", tmp_path)
    monkeypatch.setattr(phase1, "DATA_DIR", data)
    monkeypatch.setattr(phase1, "RESEARCH_DIR", research)
    monkeypatch.setattr(phase1, "RAW_DIR", research / "raw")
    monkeypatch.setattr(phase1, "CACHE_DIR", research / "cache")
    monkeypatch.setattr(phase1, "FACTS_DIR", research / "facts")
    monkeypatch.setattr(phase1, "LOGS_DIR", research / "logs")
    monkeypatch.setattr(phase1, "REVIEW_DIR", research / "review")
    monkeypatch.setattr(phase1, "COLLECTION_INDEX_PATH", research / "cache" / "phase1_collection_index.json")
    monkeypatch.setattr(phase1, "RUN_SUMMARY_PATH", research / "logs" / "phase1_run_summary_latest.json")
    monkeypatch.setattr(phase1, "FACT_STORE_PATH", research / "facts" / "phase1_fact_store.jsonl")
    phase1._ensure_dirs()


def _extract_md_scalar(md_text: str, label: str) -> str:
    prefix = f"- {label}: "
    for line in md_text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _extract_md_list(md_text: str, section: str) -> list[str]:
    lines = md_text.splitlines()
    in_section = False
    out: list[str] = []
    for line in lines:
        if line.strip() == section:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- "):
            value = line[2:].strip()
            if value and value != "none":
                out.append(value)
    return out


def _artifact_consistency_is_stale(summary_payload: dict[str, object]) -> bool:
    per_ticker = summary_payload.get("per_ticker", {}) if isinstance(summary_payload, dict) else {}
    if not isinstance(per_ticker, dict):
        return True

    for ticker in COMPLETED_TICKERS:
        ticker_payload = per_ticker.get(ticker)
        if not isinstance(ticker_payload, dict):
            return True

        facts_path = Path(f"data/research/facts/{ticker}_phase1_facts.json")
        md_path = Path(f"data/research/review/{ticker}_phase1_facts.md")
        if not facts_path.exists() or not md_path.exists():
            return True

        summary = ticker_payload.get("summary", {})
        if not isinstance(summary, dict):
            return True

        facts = json.loads(facts_path.read_text(encoding="utf-8")).get("facts", [])
        if not isinstance(facts, list):
            return True

        security_type = str(ticker_payload.get("security_type") or "operating_company")
        required_fields = phase1.required_fields_for_ticker(ticker, security_type)
        optional_fields = phase1.optional_fields_for_ticker(ticker)
        required_cov = phase1._coverage_from_fields(facts, required_fields)
        optional_cov = phase1._coverage_from_fields(facts, optional_fields)

        if summary.get("required_field_coverage_pct") != required_cov.get("verified_coverage_pct"):
            return True
        if summary.get("optional_field_coverage_pct") != optional_cov.get("verified_coverage_pct"):
            return True
        if summary.get("missing_required_fields") != required_cov.get("missing"):
            return True
        if summary.get("conflicting_required_fields") != required_cov.get("conflicting"):
            return True

    return False


def _load_fresh_completed_artifacts() -> dict[str, object]:
    summary_path = Path("data/research/logs/phase1_run_summary_latest.json")
    if not summary_path.exists() or _artifact_consistency_is_stale(json.loads(summary_path.read_text(encoding="utf-8"))):
        phase1.run_phase1(COMPLETED_TICKERS)
    return json.loads(summary_path.read_text(encoding="utf-8"))


class _InvariantFakeResponse:
    def __init__(self, url: str):
        self.status_code = 200
        self.url = url
        self.text = "<html><body>validated</body></html>"

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "0": {"cik_str": 1535527, "ticker": "CRWD", "title": "CrowdStrike Holdings, Inc."},
            "1": {"cik_str": 1181412, "ticker": "SPCX", "title": "SPACE EXPLORATION TECHNOLOGIES CORP"},
        }


def _patch_sources(monkeypatch) -> None:
    class _FakeSEC:
        def __init__(self):
            self.session = self

        def get(self, url, timeout=30):
            if "submissions" in url:
                return _InvariantFakeResponse(url)
            if "companyfacts" in url:
                return _InvariantFakeResponse(url)
            return _InvariantFakeResponse(url)

        def _select_unit_data(self, units, preferred_units=None):
            return []

        def get_cik_for_ticker(self, ticker):
            return "0001535527"

    monkeypatch.setattr(phase1, "SECDataSource", _FakeSEC)
    monkeypatch.setattr(phase1.TranscriptDataSource, "fetch_symbol", lambda self, ticker: {"source_urls": []})
    monkeypatch.setattr(phase1.requests, "get", lambda url, timeout=45, allow_redirects=True, headers=None: _InvariantFakeResponse(url))
    monkeypatch.setattr(
        phase1.FinvizDataSource,
        "_fetch_snapshot",
        lambda self, ticker: {"Price": "123.45", "Avg Volume": "1.2M", "Dividend %": "0.3", "Expense": "0.45", "AUM": "2.5B"},
    )


def test_invariant_single_canonical_readiness_computation_exists() -> None:
    source_path = Path(phase1.__file__)
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    readiness_defs = [n for n in ast.walk(module) if isinstance(n, ast.FunctionDef) and n.name == "_compute_phase2_readiness"]
    assert len(readiness_defs) == 1

    readiness_calls = [
        n
        for n in ast.walk(module)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_compute_phase2_readiness"
    ]
    assert len(readiness_calls) == 1


def test_invariant_summary_and_markdown_use_resolved_fact_store(monkeypatch, tmp_path) -> None:
    _prepare_tmp_layout(monkeypatch, tmp_path)
    monkeypatch.setattr(phase1, "required_fields_for_ticker", lambda ticker, security_type: ["a", "b"])
    monkeypatch.setattr(phase1, "optional_fields_for_ticker", lambda ticker: ["c", "d"])
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "ZZZF", 0.0)

    collection = {
        "documents": [
            {
                "source_type": "sec_submissions",
                "collection_status": "retrieved",
                "source_url": "https://example.com/submissions",
                "document_date": "2026-06-01",
            }
        ],
        "ticker": "ZZZF",
        "security_type": "operating_company",
    }
    parsed = {
        "facts": [
            {"normalized_field": "a", "fact_status": "verified", "extraction_method": "html_table_row_match"},
            {"normalized_field": "b", "fact_status": "missing", "extraction_method": "html_table_row_match"},
            {"normalized_field": "c", "fact_status": "verified", "extraction_method": "html_table_row_match"},
            {"normalized_field": "d", "fact_status": "missing", "extraction_method": "html_table_row_match"},
        ]
    }

    summary = phase1.build_phase1_report("ZZZF", "operating_company", collection, parsed)
    md_text = (phase1.REVIEW_DIR / "ZZZF_phase1_facts.md").read_text(encoding="utf-8")

    required_cov = phase1._coverage_from_fields(parsed["facts"], ["a", "b"])
    optional_cov = phase1._coverage_from_fields(parsed["facts"], ["c", "d"])

    assert summary["required_field_coverage_pct"] == required_cov["verified_coverage_pct"]
    assert summary["optional_field_coverage_pct"] == optional_cov["verified_coverage_pct"]
    assert summary["missing_required_fields"] == required_cov["missing"]
    assert summary["conflicting_required_fields"] == required_cov["conflicting"]

    assert float(_extract_md_scalar(md_text, "Required coverage (verified only)").rstrip("%")) == summary["required_field_coverage_pct"]
    assert float(_extract_md_scalar(md_text, "Optional coverage (verified only)").rstrip("%")) == summary["optional_field_coverage_pct"]
    assert _extract_md_list(md_text, "## Missing Required Facts") == summary["missing_required_fields"]
    assert _extract_md_list(md_text, "## Exact Remaining Blockers") == summary["blockers_for_phase2"]
    assert _extract_md_scalar(md_text, "Phase 2 readiness") == str(summary["phase2_readiness"])


def test_invariant_phase2_readiness_contract_false_for_each_failure_condition() -> None:
    base = {
        "required_cov": {"verified_coverage_pct": 100.0, "missing": []},
        "target": 100.0,
        "conflicting_required_fields": [],
        "source_failures": [],
        "verified_text_facts": [],
        "currency_ambiguity": False,
        "material_period_mismatch": False,
        "identity_status": "verified",
    }

    assert phase1._compute_phase2_readiness(**base) is True

    failed = dict(base)
    failed["required_cov"] = {"verified_coverage_pct": 90.0, "missing": ["x"]}
    assert phase1._compute_phase2_readiness(**failed) is False

    failed = dict(base)
    failed["conflicting_required_fields"] = ["x"]
    assert phase1._compute_phase2_readiness(**failed) is False

    failed = dict(base)
    failed["required_cov"] = {"verified_coverage_pct": 99.0, "missing": []}
    assert phase1._compute_phase2_readiness(**failed) is False

    failed = dict(base)
    failed["source_failures"] = [{"source_type": "official_ir_page"}]
    assert phase1._compute_phase2_readiness(**failed) is False

    failed = dict(base)
    failed["identity_status"] = "unverified"
    assert phase1._compute_phase2_readiness(**failed) is False

    failed = dict(base)
    failed["material_period_mismatch"] = True
    assert phase1._compute_phase2_readiness(**failed) is False

    failed = dict(base)
    failed["currency_ambiguity"] = True
    assert phase1._compute_phase2_readiness(**failed) is False


def test_invariant_blockers_are_deterministic_and_ordered(monkeypatch, tmp_path) -> None:
    _prepare_tmp_layout(monkeypatch, tmp_path)
    monkeypatch.setattr(phase1, "required_fields_for_ticker", lambda ticker, security_type: ["a", "b", "c"])
    monkeypatch.setattr(phase1, "optional_fields_for_ticker", lambda ticker: [])
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "VBNK", 100.0)

    collection = {
        "documents": [
            {
                "source_type": "z_source",
                "collection_status": "error",
                "source_url": "https://z.example.com",
                "collection_error": "403 Client Error",
                "document_date": "",
            },
            {
                "source_type": "a_source",
                "collection_status": "error",
                "source_url": "https://a.example.com",
                "collection_error": "timeout",
                "document_date": "",
            },
        ],
        "ticker": "VBNK",
        "security_type": "bank",
    }
    parsed = {
        "facts": [
            {"normalized_field": "b", "fact_status": "conflicting", "extraction_method": "html_table_row_match"},
            {"normalized_field": "x", "fact_status": "verified", "extraction_method": "official_document_regex", "currency": "USD"},
            {
                "normalized_field": "y",
                "fact_status": "verified",
                "extraction_method": "html_table_row_match",
                "currency": "CAD",
                "calculation_metadata": {"requires_same_period": True, "input_periods": ["2026Q1", "2026Q2"]},
            },
        ]
    }
    identity = {"identity_status": "unverified"}

    summary1 = phase1.build_phase1_report("VBNK", "bank", collection, parsed, identity=identity)
    summary2 = phase1.build_phase1_report("VBNK", "bank", collection, parsed, identity=identity)

    expected = [
        "Missing required fields: a, c",
        "Conflicting required facts: b",
        "Source failures present: a_source, z_source",
        "Verified narrative facts remain without structured or exact table lineage",
        "Currency ambiguity remains across verified facts",
        "Material period mismatch remains in calculated verified facts",
        "Identity status is unverified",
        "Required verified coverage below target: 0.0% < 100.0%",
    ]

    assert summary1["blockers_for_phase2"] == expected
    assert summary2["blockers_for_phase2"] == expected


def test_invariant_completed_tickers_have_consistent_artifacts() -> None:
    summary_payload = _load_fresh_completed_artifacts()
    per_ticker = summary_payload.get("per_ticker", {})

    for ticker in COMPLETED_TICKERS:
        assert ticker in per_ticker

        facts_path = Path(f"data/research/facts/{ticker}_phase1_facts.json")
        md_path = Path(f"data/research/review/{ticker}_phase1_facts.md")
        assert facts_path.exists()
        assert md_path.exists()

        summary = per_ticker[ticker]["summary"]
        facts = json.loads(facts_path.read_text(encoding="utf-8")).get("facts", [])
        md_text = md_path.read_text(encoding="utf-8")

        security_type = per_ticker[ticker].get("security_type", "operating_company")
        required_fields = phase1.required_fields_for_ticker(ticker, security_type)
        optional_fields = phase1.optional_fields_for_ticker(ticker)
        required_cov = phase1._coverage_from_fields(facts, required_fields)
        optional_cov = phase1._coverage_from_fields(facts, optional_fields)

        assert summary["required_field_coverage_pct"] == required_cov["verified_coverage_pct"]
        assert summary["optional_field_coverage_pct"] == optional_cov["verified_coverage_pct"]
        assert summary["missing_required_fields"] == required_cov["missing"]
        assert summary["conflicting_required_fields"] == required_cov["conflicting"]
        assert _extract_md_list(md_text, "## Missing Required Facts") == summary["missing_required_fields"]
        assert _extract_md_list(md_text, "## Exact Remaining Blockers") == summary["blockers_for_phase2"]
        assert _extract_md_scalar(md_text, "Phase 2 readiness") == str(summary["phase2_readiness"])


def test_stale_identity_registry_file_does_not_override_live_resolution(monkeypatch, tmp_path) -> None:
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    stale_registry = {
        "CRWD": {
            "ticker": "CRWD",
            "legal_name": "Stale Override Corp",
            "security_type": "etf_fund",
            "exchange": "NYSE",
            "reporting_jurisdiction": "United States",
            "reporting_currency": "USD",
            "sec_cik": "0000009999",
            "foreign_issuer_status": False,
            "primary_filing_system": "stale",
            "official_ir_url": "https://stale.example.com",
            "official_product_url": "",
            "identity_sources": [],
            "identity_confidence": 0.01,
            "identity_status": "verified",
            "verified_at": phase1._utc_now_iso(),
            "identity_notes": "stale registry entry",
        }
    }
    phase1.SECURITY_IDENTITY_REGISTRY_PATH.write_text(json.dumps(stale_registry), encoding="utf-8")

    result = phase1.run_phase1(["CRWD"])
    identity = result["per_ticker"]["CRWD"]["identity"]

    assert identity["legal_name"] == "CrowdStrike Holdings, Inc."
    assert identity["sec_cik"] == "0001535527"
    assert identity["identity_sources"][0]["type"] == "sec_company_tickers"
    assert identity["identity_sources"][1]["type"] == "sec_submissions"


def test_resolved_identity_preserves_source_provenance(monkeypatch, tmp_path) -> None:
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    result = phase1.run_phase1(["CRWD"])
    identity = result["per_ticker"]["CRWD"]["identity"]

    assert identity["identity_sources"]
    assert [source["type"] for source in identity["identity_sources"]] == [
        "sec_company_tickers",
        "sec_submissions",
        "sec_browse",
    ]
    assert identity["identity_resolution"] == "accept_current"
    assert identity["canonical_identity"] == {}
    assert identity["historical_identities"] == []
