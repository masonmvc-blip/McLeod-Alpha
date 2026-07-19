from __future__ import annotations

import json
from pathlib import Path

import engine.research_phase1 as phase1


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self._payload, dict):
            return self._payload
        return json.loads(self._payload)


class _FakeSession:
    def get(self, url, timeout=30):
        if "submissions" in url:
            return _FakeResponse(_dummy_submissions_payload())
        if "companyfacts" in url:
            return _FakeResponse(_dummy_companyfacts_payload())
        return _FakeResponse(_dummy_document_text())


class _FakeRequestsResponse:
    def __init__(self, url: str):
        self.status_code = 200
        self.url = url
        self.text = _dummy_document_text()
        self._json = {
            "0": {"cik_str": 1535527, "ticker": "CRWD", "title": "CrowdStrike Holdings, Inc."},
            "1": {"cik_str": 1181412, "ticker": "SPCX", "title": "SPACE EXPLORATION TECHNOLOGIES CORP"},
        }

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


class _FakeSEC:
    def __init__(self):
        self.session = _FakeSession()

    def get_cik_for_ticker(self, ticker):
        return "0000320193"

    def _select_unit_data(self, units, preferred_units=None):
        rows = []
        if not isinstance(units, dict):
            return rows
        if preferred_units:
            for pref in preferred_units:
                if pref in units:
                    rows.extend(units[pref])
                else:
                    for key, data in units.items():
                        if key.startswith(pref.rstrip("*")):
                            rows.extend(data)
        if not rows:
            for data in units.values():
                rows.extend(data)
        return rows


def _prepare_tmp_layout(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    research = data / "research"
    raw = research / "raw"
    cache = research / "cache"
    facts = research / "facts"
    logs = research / "logs"
    review = research / "review"

    monkeypatch.setattr(phase1, "WORKSPACE", tmp_path)
    monkeypatch.setattr(phase1, "DATA_DIR", data)
    monkeypatch.setattr(phase1, "RESEARCH_DIR", research)
    monkeypatch.setattr(phase1, "RAW_DIR", raw)
    monkeypatch.setattr(phase1, "CACHE_DIR", cache)
    monkeypatch.setattr(phase1, "FACTS_DIR", facts)
    monkeypatch.setattr(phase1, "LOGS_DIR", logs)
    monkeypatch.setattr(phase1, "REVIEW_DIR", review)
    monkeypatch.setattr(phase1, "COLLECTION_INDEX_PATH", cache / "phase1_collection_index.json")
    monkeypatch.setattr(phase1, "RUN_SUMMARY_PATH", logs / "phase1_run_summary_latest.json")
    monkeypatch.setattr(phase1, "FACT_STORE_PATH", facts / "phase1_fact_store.jsonl")

    phase1._ensure_dirs()


def _dummy_submissions_payload():
    return {
        "filings": {
            "recent": {
                "form": ["20-F", "6-K", "8-K", "10-Q", "10-K"],
                "filingDate": ["2026-03-01", "2026-05-15", "2026-06-01", "2026-06-10", "2026-02-01"],
                "accessionNumber": [
                    "0000000000-26-000001",
                    "0000000000-26-000002",
                    "0000000000-26-000003",
                    "0000000000-26-000004",
                    "0000000000-26-000005",
                ],
                "primaryDocument": [
                    "annual20f.htm",
                    "quarterly6k.htm",
                    "earnings_release.htm",
                    "quarterly10q.htm",
                    "annual10k.htm",
                ],
            }
        }
    }


def _dummy_companyfacts_payload():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 1000.0}]}},
                "GrossProfit": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 780.0}]}},
                "OperatingIncomeLoss": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 220.0}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 300.0}]}},
                "PaymentsForCapitalExpenditures": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 50.0}]}},
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 500.0}]}},
                "LongTermDebt": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 200.0}]}},
                "StockholdersEquity": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 700.0}]}},
                "WeightedAverageNumberOfDilutedSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"form": "10-K", "end": "2024-12-31", "filed": "2025-03-01", "val": 45.0},
                            {"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 50.0},
                        ]
                    }
                },
                "ShareBasedCompensation": {"units": {"USD": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 80.0}]}},
            },
            "ifrs-full": {
                "Revenue": {"units": {"USD": [{"form": "20-F", "end": "2025-12-31", "filed": "2026-04-01", "val": 900.0}]}},
                "ProfitLossFromOperatingActivities": {"units": {"USD": [{"form": "20-F", "end": "2025-12-31", "filed": "2026-04-01", "val": 120.0}]}},
                "CashFlowsFromUsedInOperatingActivities": {"units": {"USD": [{"form": "20-F", "end": "2025-12-31", "filed": "2026-04-01", "val": 250.0}]}},
                "CashAndCashEquivalents": {"units": {"USD": [{"form": "20-F", "end": "2025-12-31", "filed": "2026-04-01", "val": 350.0}]}},
                "Borrowings": {"units": {"USD": [{"form": "20-F", "end": "2025-12-31", "filed": "2026-04-01", "val": 150.0}]}},
                "Equity": {"units": {"USD": [{"form": "20-F", "end": "2025-12-31", "filed": "2026-04-01", "val": 610.0}]}},
                "AdjustedWeightedAverageShares": {"units": {"shares": [{"form": "20-F", "end": "2025-12-31", "filed": "2026-04-01", "val": 40.0}]}},
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [{"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 52.0}]}
                }
            },
        }
    }


def _dummy_document_text() -> str:
    return """
    Annual recurring revenue was $1.2 billion. Subscription revenue was $800 million.
    Net retention was 118%. We served 32000 customers.
    Guidance for next quarter remains strong.
    Tangible book value per share was $12.45 and book value per share was $15.25.
    CET1 ratio was 13.2% and tier 1 capital ratio was 14.1% and total capital ratio was 16.8%.
    Provision for credit losses was $12 million and allowance for credit losses was $80 million.
    Loan growth was 9.1% while deposit growth was 7.4%.
    Fund seeks to track an index. The exchange-traded fund benchmark is the Defiance SPCX Index.
    Top 10 concentration was 42.3% with 58 holdings.
    """


def _patch_sources(monkeypatch):
    monkeypatch.setattr(phase1, "SECDataSource", _FakeSEC)
    monkeypatch.setattr(phase1.TranscriptDataSource, "fetch_symbol", lambda self, ticker: {"source_urls": []})
    monkeypatch.setattr(phase1.requests, "get", lambda url, timeout=45, allow_redirects=True, headers=None: _FakeRequestsResponse(url))
    monkeypatch.setattr(
        phase1.FinvizDataSource,
        "_fetch_snapshot",
        lambda self, ticker: {"Price": "123.45", "Avg Volume": "1.2M", "Dividend %": "0.3", "Expense": "0.45", "AUM": "2.5B"},
    )


def test_ir_retrieval_and_source_attempt_logging(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("CRWD", "operating_company")
    assert package["documents"]

    attempts_path = phase1.LOGS_DIR / "CRWD_source_attempts.json"
    assert attempts_path.exists()
    attempts = json.loads(attempts_path.read_text())["attempts"]
    assert any(a["source_type"] == "official_ir_page" for a in attempts)


def test_foreign_issuer_form_handling(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("OPRA", "operating_company")
    annual = [d for d in package["documents"] if d["source_type"] == "latest_annual_filing"]
    assert annual
    assert "20-F" in (annual[0].get("document_id") or "")


def test_20f_and_6k_parsing(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("OPRA", "operating_company")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)
    fields = {f["normalized_field"]: f for f in parsed["facts"]}
    assert fields["revenue"]["fact_status"] in {"verified", "conflicting"}
    assert fields["free_cash_flow"]["fact_status"] in {"verified", "conflicting"}


def test_rklb_identity_terms_and_field_config():
    terms = phase1._expected_identity_terms("RKLB")
    required = phase1.required_fields_for_ticker("RKLB", "operating_company")
    optional = phase1.optional_fields_for_ticker("RKLB")

    assert "rocket lab" in terms
    assert "backlog" in required
    assert "guidance" in required
    assert "adjusted_ebitda" in optional
    assert "electron" in optional


def test_rklb_table_and_text_extraction(tmp_path):
    html = """
    <table>
      <tr><th>Metric</th><th>Q1 2026</th></tr>
      <tr><td>Backlog</td><td>1200000000</td></tr>
      <tr><td>Launch Services Revenue</td><td>250000000</td></tr>
      <tr><td>Space Systems Revenue</td><td>315000000</td></tr>
      <tr><td>Adjusted EBITDA</td><td>42000000</td></tr>
    </table>
    <p>Rocket Lab Corporation is expanding spacecraft production and Electron launch operations.</p>
    <p>Neutron development continues and guidance for the next quarter remains constructive.</p>
    """
    p = tmp_path / "rklb_release.html"
    p.write_text(html, encoding="utf-8")

    table = phase1.pd.DataFrame(
        [
            ["Backlog", 1200000000],
            ["Launch Services Revenue", 250000000],
            ["Space Systems Revenue", 315000000],
            ["Adjusted EBITDA", 42000000],
        ],
        columns=["Metric", "Q1 2026"],
    )

    row = {
        "local_cache_path": str(p),
        "document_id": "doc-rklb-1",
        "source_url": "https://example.com/rklb",
        "document_date": "2026-05-15",
        "document_title": "RKLB Results",
        "source_type": "latest_earnings_release",
    }

    extracted = phase1._extract_rklb_table_frame(table, row, 0)
    fields = {f["normalized_field"] for f in extracted}

    assert {"backlog", "launch_services_revenue", "space_systems_revenue", "adjusted_ebitda"}.issubset(fields)
    assert all(f["fact_status"] == "verified" for f in extracted)

    parser = phase1.ResearchParser()
    spacecraft_matches = parser._extract_text_matches([row], [r"\bspacecraft\b[^.]{0,160}\."], string_only=True)
    electron_matches = parser._extract_text_matches([row], [r"\bElectron\b[^.]{0,160}\."], string_only=True)
    neutron_matches = parser._extract_text_matches([row], [r"\bNeutron\b[^.]{0,160}\."], string_only=True)

    assert spacecraft_matches
    assert electron_matches
    assert neutron_matches


def test_bank_specific_alias_and_regex_fields(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("VBNK", "bank")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)
    by = {f["normalized_field"]: f for f in parsed["facts"]}
    assert by["cet1"]["fact_status"] in {"missing", "uncertain", "conflicting", "verified"}
    assert by["tbv_per_share"]["fact_status"] in {"missing", "uncertain", "conflicting", "verified"}


def test_biotech_pipeline_extraction(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("ARTV", "biotechnology")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)
    rows = [f for f in parsed["facts"] if f["normalized_field"] == "pipeline_programs"]
    assert rows


def test_artv_table_row_extraction_biotech_required_fields(tmp_path):
    html = """
    <table>
      <tr><th>Program update</th></tr>
      <tr><td>AlloNK is currently evaluating an ongoing open-label Phase [2a] study recruiting approximately 90 adult participants.</td></tr>
      <tr><td>The FDA has granted Fast Track designation in lupus nephritis and our Option and License Agreement with GC Cell remains in effect.</td></tr>
      <tr><td>Recent financing activities and dilution disclosures are discussed in management commentary.</td></tr>
    </table>
    """
    p = tmp_path / "artv_table.html"
    p.write_text(html, encoding="utf-8")
    row = {
        "local_cache_path": str(p),
        "document_id": "doc-artv-1",
        "source_url": "https://example.com/artv",
        "document_date": "2026-05-19",
        "document_title": "ARTV Clinical Update",
        "source_type": "latest_annual_filing",
    }

    extracted = phase1._extract_artv_table_rows(row)
    fields = {r["normalized_field"] for r in extracted}
    assert "pipeline_programs" in fields
    assert "development_stage" in fields
    assert "trial_phase" in fields
    assert "enrollment_status" in fields
    assert "regulatory_designations" in fields
    assert "licensing_agreements" in fields
    assert "recent_financing" in fields
    assert "management_stated_dilution_disclosures" in fields
    assert all(r["fact_status"] == "verified" for r in extracted)


def test_artv_estimated_cash_runway_derived_from_verified_burn(tmp_path):
    companyfacts = {
        "facts": {
            "us-gaap": {
                "CashAndCashEquivalentsAtCarryingValue": {
                    "units": {
                        "USD": [
                            {"form": "10-Q", "end": "2026-03-31", "filed": "2026-05-19", "val": 90000000.0}
                        ]
                    }
                },
                "ShortTermInvestments": {
                    "units": {
                        "USD": [
                            {"form": "10-Q", "end": "2026-03-31", "filed": "2026-05-19", "val": 30000000.0}
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            {"form": "10-Q", "end": "2026-03-31", "filed": "2026-05-19", "val": -15000000.0}
                        ]
                    }
                },
            }
        }
    }
    cf = tmp_path / "artv_companyfacts.json"
    cf.write_text(json.dumps(companyfacts), encoding="utf-8")

    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(
        {
            "ticker": "ARTV",
            "security_type": "biotechnology",
            "documents": [
                {
                    "source_type": "sec_companyfacts",
                    "document_id": "CIK:test:companyfacts",
                    "source_url": "https://example.com/companyfacts",
                    "document_date": "",
                    "local_cache_path": str(cf),
                }
            ],
        }
    )

    runway_rows = [
        f for f in parsed["facts"]
        if f.get("normalized_field") == "estimated_cash_runway" and f.get("fact_status") == "verified"
    ]
    assert runway_rows
    assert round(float(runway_rows[0]["value"]), 4) == 24.0


def test_etf_prospectus_and_holdings_extraction(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("SPCX", "etf_fund")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)
    rows = {f["normalized_field"]: f for f in parsed["facts"]}
    assert rows["fund_strategy"]["fact_status"] in {"uncertain", "missing", "conflicting"}
    assert rows["number_of_holdings"]["fact_status"] in {"uncertain", "missing", "conflicting"}


def test_per_document_text_lineage_preserved(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("CRWD", "operating_company")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)

    arr_rows = [f for f in parsed["facts"] if f["normalized_field"] == "arr" and f["fact_status"] != "missing"]
    assert arr_rows
    assert all(r.get("source_document_id") for r in arr_rows)
    assert all(r.get("local_cache_path") for r in arr_rows)
    assert all(r.get("matched_text") for r in arr_rows)
    assert all(r.get("context_before") is not None for r in arr_rows)
    assert all(r.get("context_after") is not None for r in arr_rows)


def test_narrative_regex_defaults_to_uncertain(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("CRWD", "operating_company")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)

    guidance_rows = [f for f in parsed["facts"] if f["normalized_field"] == "guidance" and f["value"]]
    assert guidance_rows
    assert all(r["fact_status"] == "uncertain" for r in guidance_rows)


def test_currency_preservation(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("VBNK", "bank")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)

    equity_rows = [f for f in parsed["facts"] if f["normalized_field"] == "common_equity" and f["fact_status"] == "verified"]
    assert equity_rows
    assert all(r["currency"] in {"CAD", "USD", ""} for r in equity_rows)


def test_no_text_rows_zero_fallback(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("CRWD", "operating_company")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)

    rows = [f for f in parsed["facts"] if f.get("extraction_method") == "official_document_regex" and f.get("value") is not None]
    assert rows
    assert all(f.get("source_document_id") for f in rows)


def test_reclassification_audit_logging(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    old_payload = {
        "facts": [
            {
                "normalized_field": "guidance",
                "fact_status": "verified",
                "extraction_method": "official_document_regex",
                "source_document_id": "old-doc",
            }
        ]
    }
    (phase1.FACTS_DIR / "CRWD_phase1_facts.json").write_text(json.dumps(old_payload), encoding="utf-8")

    result = phase1.run_phase1(["CRWD"])
    assert result
    audit = json.loads(phase1.FACT_STATUS_AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["rows"]


def test_spcx_identity_gate_blocks_extraction(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    def fake_identity_registry(tickers):
        return {
            "SPCX": {
                "ticker": "SPCX",
                "legal_name": "SPACE EXPLORATION TECHNOLOGIES CORP",
                "security_type": "operating_company",
                "exchange": "Nasdaq",
                "reporting_jurisdiction": "United States",
                "reporting_currency": "USD",
                "sec_cik": "0001181412",
                "foreign_issuer_status": False,
                "primary_filing_system": "SEC filings",
                "official_ir_url": "",
                "official_product_url": "",
                "identity_sources": [],
                "identity_confidence": 0.99,
                "identity_status": "ticker_reassigned",
                "verified_at": phase1._utc_now_iso(),
                "identity_notes": "Current ticker maps to operating company, not ETF.",
            }
        }

    monkeypatch.setattr(phase1, "_build_security_identity_registry", fake_identity_registry)

    def should_not_collect(self, ticker, security_type):
        raise AssertionError("SPCX collection should be identity-gated")

    monkeypatch.setattr(phase1.ResearchCollector, "collect_ticker", should_not_collect)
    result = phase1.run_phase1(["SPCX"])
    assert result["per_ticker"]["SPCX"]["summary"]["phase2_readiness"] is False
    assert result["per_ticker"]["SPCX"]["identity"]["identity_status"] == "ticker_reassigned"


def test_official_source_registry_fields(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)

    monkeypatch.setattr(
        phase1,
        "_validate_official_url",
        lambda url, expected_terms: {
            "official_url": url,
            "verified_at": phase1._utc_now_iso(),
            "http_status": 200,
            "redirected_url": url + "final",
            "issuer_or_sponsor_match": True,
            "active": True,
            "notes": "validated",
        },
    )
    registry = phase1._write_official_source_registry(["CRWD"])
    row = registry["CRWD"][0]
    assert "original_url" in row
    assert "final_url" in row
    assert "redirect_chain" in row
    assert "document_type_match" in row


def test_security_identity_registry_written(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    monkeypatch.setattr(
        phase1,
        "_resolve_security_identity",
        lambda ticker: {
            "ticker": ticker,
            "legal_name": ticker,
            "security_type": "operating_company",
            "exchange": "Nasdaq",
            "reporting_jurisdiction": "United States",
            "reporting_currency": "USD",
            "sec_cik": "0000000001",
            "foreign_issuer_status": False,
            "primary_filing_system": "SEC domestic issuer (10-K/10-Q)",
            "official_ir_url": "https://example.com/ir",
            "official_product_url": "",
            "identity_sources": [],
            "identity_confidence": 0.9,
            "identity_status": "verified",
            "verified_at": phase1._utc_now_iso(),
            "identity_notes": "ok",
        },
    )
    registry = phase1._build_security_identity_registry(["CRWD", "SPCX"])
    assert phase1.SECURITY_IDENTITY_REGISTRY_PATH.exists()
    assert phase1.SPCX_IDENTITY_PATH.exists()
    assert registry["CRWD"]["identity_status"] == "verified"


def test_spcx_identity_gated_coverage_zero(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    monkeypatch.setattr(
        phase1,
        "_build_security_identity_registry",
        lambda tickers: {
            "SPCX": {
                "ticker": "SPCX",
                "legal_name": "SPACE EXPLORATION TECHNOLOGIES CORP",
                "security_type": "operating_company",
                "exchange": "Nasdaq",
                "reporting_jurisdiction": "United States",
                "reporting_currency": "USD",
                "sec_cik": "0001181412",
                "foreign_issuer_status": False,
                "primary_filing_system": "SEC filings",
                "official_ir_url": "",
                "official_product_url": "",
                "identity_sources": [],
                "identity_confidence": 0.99,
                "identity_status": "ticker_reassigned",
                "verified_at": phase1._utc_now_iso(),
                "identity_notes": "blocked",
            }
        },
    )
    result = phase1.run_phase1(["SPCX"])
    summary = result["per_ticker"]["SPCX"]["summary"]
    assert summary["required_field_coverage_pct"] == 0.0
    assert summary["optional_field_coverage_pct"] == 0.0
    assert summary["phase2_readiness"] is False
    facts = json.loads((phase1.FACTS_DIR / "SPCX_phase1_facts.json").read_text())["facts"]
    assert all(f["blocker_reason"] == "identity_blocked" for f in facts)


def test_spcx_identity_gate_audit_rows(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    old_payload = {
        "facts": [
            {"normalized_field": "fund_strategy", "fact_status": "verified", "source_document_id": "old-source"}
        ]
    }
    (phase1.FACTS_DIR / "SPCX_phase1_facts.json").write_text(json.dumps(old_payload), encoding="utf-8")
    rows = phase1._build_fact_status_audit(
        {"SPCX": old_payload["facts"]},
        {"SPCX": [{"normalized_field": "fund_strategy", "fact_status": "missing", "extraction_method": "identity_gate"}]},
    )
    assert rows
    assert rows[0]["ticker"] == "SPCX"


def test_vbnk_exhibit_discovery_helper(tmp_path):
    html = '<a href="ex_969212.htm">Interim Consolidated Financial Statements for the three months ended April 30, 2026 and 2025.</a>'
    p = tmp_path / "parent.html"
    p.write_text(html, encoding="utf-8")
    row = {"local_cache_path": str(p), "source_url": "https://www.sec.gov/Archives/edgar/data/1690639/000143774926019259/versb20260430_6k.htm"}
    links = phase1._discover_vbnk_exhibit_links(row)
    assert links
    assert links[0]["document_type"] == "financial_statements"


def test_vbnk_table_row_extraction(tmp_path):
    html = """
    <table>
      <tr><th>Metric</th><th>Q2 2026</th><th>Q2 2025</th></tr>
      <tr><td>Common Equity Tier 1 (CET1) ratio</td><td>13.18</td><td>12.32</td></tr>
      <tr><td>Tier 1 capital ratio</td><td>14.51</td><td>13.65</td></tr>
      <tr><td>Total capital ratio</td><td>16.13</td><td>14.79</td></tr>
    </table>
    """
    p = tmp_path / "table.html"
    p.write_text(html, encoding="utf-8")
    row = {
        "local_cache_path": str(p),
        "document_id": "doc1",
        "source_url": "https://example.com/doc1",
        "document_date": "2026-04-30",
        "document_title": "Quarterly Supplement",
        "source_type": "vbnk_financial_statements",
    }
    extracted = phase1._extract_vbnk_table_rows(row)
    fields = {r["normalized_field"] for r in extracted}
    assert "cet1" in fields
    assert "tier1_capital_ratio" in fields
    assert "total_capital_ratio" in fields


def test_crwd_table_row_extraction_required_metrics(tmp_path):
        html = """
        <table>
            <tr><th>Metric</th><th>Q1 FY2027</th><th>Q1 FY2026</th></tr>
            <tr><td>Annual recurring revenue</td><td>5508596</td><td>4435596</td></tr>
            <tr><td>Subscription revenue</td><td>1234567</td><td>1000000</td></tr>
            <tr><td>Dollar-based net retention rate</td><td>115</td><td>112</td></tr>
        </table>
        """
        p = tmp_path / "crwd_table.html"
        p.write_text(html, encoding="utf-8")
        row = {
                "local_cache_path": str(p),
                "document_id": "doc-crwd-1",
                "source_url": "https://example.com/crwd",
                "document_date": "2026-04-30",
                "document_title": "CRWD Supplemental Metrics",
                "source_type": "latest_quarterly_filing",
        }

        extracted = phase1._extract_crwd_table_rows(row)
        fields = {r["normalized_field"] for r in extracted}
        assert "arr" in fields
        assert "subscription_revenue" in fields
        assert "retention" in fields
        assert all(r["fact_status"] == "verified" for r in extracted)


def test_crwd_table_row_extraction_dedupes_repeat_rows(tmp_path):
        html = """
        <table>
            <tr><th>Metric</th><th>Q1 FY2027</th></tr>
            <tr><td>Annual recurring revenue</td><td>5508596</td></tr>
            <tr><td>Annual recurring revenue*</td><td>5508596</td></tr>
        </table>
        """
        p = tmp_path / "crwd_table_dedupe.html"
        p.write_text(html, encoding="utf-8")
        row = {
                "local_cache_path": str(p),
                "document_id": "doc-crwd-2",
                "source_url": "https://example.com/crwd2",
                "document_date": "2026-04-30",
                "document_title": "CRWD Supplemental Metrics",
                "source_type": "latest_quarterly_filing",
        }

        extracted = phase1._extract_crwd_table_rows(row)
        arr_rows = [r for r in extracted if r["normalized_field"] == "arr"]
        assert len(arr_rows) == 1


def test_opra_table_row_extraction_required_metrics(tmp_path):
        html = """
        <table>
          <tr><th>Segment</th><th>FY2025</th><th>FY2024</th></tr>
          <tr><td>Advertising</td><td>230908</td><td>187434</td></tr>
          <tr><td>Search</td><td>162168</td><td>140162</td></tr>
        </table>
        """
        p = tmp_path / "opra_table.html"
        p.write_text(html, encoding="utf-8")
        row = {
            "local_cache_path": str(p),
            "document_id": "doc-opra-1",
            "source_url": "https://example.com/opra",
            "document_date": "2026-06-10",
            "document_title": "OPRA Revenue Mix",
            "source_type": "latest_annual_filing",
        }

        extracted = phase1._extract_opra_table_rows(row)
        fields = {r["normalized_field"] for r in extracted}
        assert "advertising_revenue" in fields
        assert "search_revenue" in fields
        assert all(r["fact_status"] == "verified" for r in extracted)


def test_opra_transcript_fallback_uses_sec_documents(monkeypatch, tmp_path):
        _prepare_tmp_layout(monkeypatch, tmp_path)
        _patch_sources(monkeypatch)

        # Force transcript provider empty so OPRA fallback path is exercised.
        monkeypatch.setattr(phase1.TranscriptDataSource, "fetch_symbol", lambda self, ticker: {"source_urls": []})

        collector = phase1.ResearchCollector(workspace=tmp_path)
        package = collector.collect_ticker("OPRA", "operating_company")
        transcript_docs = [
            d for d in (package.get("documents") or []) if d.get("source_type") == "earnings_call_transcript"
        ]
        assert transcript_docs
        assert all(d.get("collection_status") in {"retrieved", "cached"} for d in transcript_docs)


def test_nbis_table_row_extraction_ai_infrastructure_revenue(tmp_path):
        html = """
        <table>
          <tr><th>Section</th><th>Narrative</th></tr>
          <tr><td>Nebius AI cloud business</td><td>Revenue grew by 462% year-over-year to $412.0 million in 2025.</td></tr>
        </table>
        """
        p = tmp_path / "nbis_table.html"
        p.write_text(html, encoding="utf-8")
        row = {
            "local_cache_path": str(p),
            "document_id": "doc-nbis-1",
            "source_url": "https://example.com/nbis",
            "document_date": "2026-05-20",
            "document_title": "NBIS Annual Report",
            "source_type": "latest_annual_filing",
        }

        extracted = phase1._extract_nbis_table_rows(row)
        fields = {r["normalized_field"] for r in extracted}
        assert "ai_infrastructure_revenue" in fields
        ai_rows = [r for r in extracted if r["normalized_field"] == "ai_infrastructure_revenue"]
        assert ai_rows
        assert ai_rows[0]["value"] == 412_000_000.0
        assert all(r["fact_status"] == "verified" for r in extracted)


def test_nbis_table_row_extraction_customer_concentration(tmp_path):
                html = """
                <table>
                    <tr><th>Customer</th><th>2025</th></tr>
                    <tr><td>Customer A</td><td>25</td></tr>
                </table>
                """
                p = tmp_path / "nbis_customer_table.html"
                p.write_text(html, encoding="utf-8")
                row = {
                        "local_cache_path": str(p),
                        "document_id": "doc-nbis-cc-1",
                        "source_url": "https://example.com/nbis-cc",
                        "document_date": "2026-05-20",
                        "document_title": "NBIS Concentration Table",
                        "source_type": "latest_annual_filing",
                }

                extracted = phase1._extract_nbis_table_rows(row)
                cc_rows = [r for r in extracted if r["normalized_field"] == "customer_concentration"]
                assert cc_rows
                assert float(cc_rows[0]["value"]) == 25.0
                assert cc_rows[0]["fact_status"] == "verified"


def test_nbis_transcript_fallback_uses_sec_documents(monkeypatch, tmp_path):
        _prepare_tmp_layout(monkeypatch, tmp_path)
        _patch_sources(monkeypatch)

        monkeypatch.setattr(phase1.TranscriptDataSource, "fetch_symbol", lambda self, ticker: {"source_urls": []})

        collector = phase1.ResearchCollector(workspace=tmp_path)
        package = collector.collect_ticker("NBIS", "operating_company")
        transcript_docs = [
            d for d in (package.get("documents") or []) if d.get("source_type") == "earnings_call_transcript"
        ]
        assert transcript_docs
        assert all(d.get("collection_status") in {"retrieved", "cached"} for d in transcript_docs)


def test_nbis_gross_margin_derived_from_cost_of_revenue_when_gross_profit_missing(tmp_path):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 1000.0}
                            ]
                        }
                    },
                    "CostOfRevenue": {
                        "units": {
                            "USD": [
                                {"form": "10-K", "end": "2025-12-31", "filed": "2026-03-01", "val": 620.0}
                            ]
                        }
                    },
                }
            }
        }
        cf = tmp_path / "companyfacts.json"
        cf.write_text(json.dumps(companyfacts), encoding="utf-8")

        parser = phase1.ResearchParser()
        parsed = parser.parse_ticker(
            {
                "ticker": "NBIS",
                "security_type": "operating_company",
                "documents": [
                    {
                        "source_type": "sec_companyfacts",
                        "document_id": "CIK:test:companyfacts",
                        "source_url": "https://example.com/companyfacts",
                        "document_date": "",
                        "local_cache_path": str(cf),
                    }
                ],
            }
        )

        gross_margin_rows = [
            f for f in parsed["facts"]
            if f.get("normalized_field") == "gross_margin" and f.get("fact_status") == "verified"
        ]
        assert gross_margin_rows
        assert round(float(gross_margin_rows[0]["value"]), 4) == 38.0


def test_nbis_customer_concentration_extracted_from_companyfacts_pure_units(tmp_path):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "ConcentrationRiskPercentage1": {
                        "units": {
                            "pure": [
                                {"form": "20-F", "end": "2025-12-31", "filed": "2026-04-30", "val": 25.0}
                            ]
                        }
                    }
                }
            }
        }
        cf = tmp_path / "companyfacts_concentration.json"
        cf.write_text(json.dumps(companyfacts), encoding="utf-8")

        parser = phase1.ResearchParser()
        parsed = parser.parse_ticker(
            {
                "ticker": "NBIS",
                "security_type": "operating_company",
                "documents": [
                    {
                        "source_type": "sec_companyfacts",
                        "document_id": "CIK:test:companyfacts",
                        "source_url": "https://example.com/companyfacts",
                        "document_date": "",
                        "local_cache_path": str(cf),
                    }
                ],
            }
        )

        concentration_rows = [
            f for f in parsed["facts"]
            if f.get("normalized_field") == "customer_concentration" and f.get("fact_status") == "verified"
        ]
        assert concentration_rows
        assert float(concentration_rows[0]["value"]) == 25.0


def test_nbis_customer_concentration_extracted_from_inline_xbrl_markup(tmp_path):
        annual_text = '''
        <html><body>
        <ix:nonFraction name="us-gaap:ConcentrationRiskPercentage1" id="x1">27</ix:nonFraction>%
        </body></html>
        '''
        annual_doc = tmp_path / "nbis_annual_inline.txt"
        annual_doc.write_text(annual_text, encoding="utf-8")

        parser = phase1.ResearchParser()
        parsed = parser.parse_ticker(
            {
                "ticker": "NBIS",
                "security_type": "operating_company",
                "documents": [
                    {
                        "source_type": "latest_annual_filing",
                        "document_id": "20-F:test",
                        "source_url": "https://example.com/annual",
                        "document_date": "2026-04-30",
                        "local_cache_path": str(annual_doc),
                    }
                ],
            }
        )

        concentration_rows = [
            f for f in parsed["facts"]
            if f.get("normalized_field") == "customer_concentration" and f.get("fact_status") == "verified"
        ]
        assert concentration_rows
        assert float(concentration_rows[0]["value"]) == 27.0


def test_not_applicable_field_handling_and_coverage(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collection = {"documents": [], "ticker": "SPCX", "security_type": "etf_fund"}
    parsed = {"facts": [{"normalized_field": "arr", "fact_status": "not_applicable"}]}

    summary = phase1.build_phase1_report("SPCX", "etf_fund", collection, parsed)
    assert "not_applicable_fields" in summary


def test_coverage_calculation_accuracy():
    facts = [
        {"normalized_field": "a", "fact_status": "verified"},
        {"normalized_field": "b", "fact_status": "missing"},
        {"normalized_field": "c", "fact_status": "not_applicable"},
    ]
    cov = phase1._coverage_from_fields(facts, ["a", "b", "c"])
    assert cov["applicable_total"] == 2
    assert cov["verified_coverage_pct"] == 50.0


def test_blockers_use_resolved_required_status_not_raw_conflicts(monkeypatch, tmp_path):
    collection = {
        "documents": [
            {
                "source_type": "sec_submissions",
                "collection_status": "retrieved",
                "source_url": "https://example.com",
                "document_date": "2026-06-01",
            }
        ],
        "ticker": "VBNK",
        "security_type": "bank",
    }
    parsed = {
        "facts": [
            {
                "normalized_field": "net_interest_margin",
                "fact_status": "conflicting",
                "value": 2.18,
            },
            {
                "normalized_field": "net_interest_margin",
                "fact_status": "verified",
                "value": 2.33,
            },
        ]
    }

    # Write report into an isolated workspace path.
    monkeypatch.setattr(phase1, "REVIEW_DIR", tmp_path)
    summary = phase1.build_phase1_report("VBNK", "bank", collection, parsed)

    blockers = summary["blockers_for_phase2"]
    assert all("Conflicting required facts" not in b for b in blockers)
    assert summary["required_conflicting_coverage_pct"] == 0.0


def _extract_md_scalar(md_text: str, label: str) -> str:
    prefix = f"- {label}: "
    for line in md_text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _extract_md_conflicting_required_fields(md_text: str) -> list[str]:
    lines = md_text.splitlines()
    in_blockers = False
    for line in lines:
        if line.strip() == "## Exact Remaining Blockers":
            in_blockers = True
            continue
        if in_blockers and line.startswith("## "):
            break
        if in_blockers and line.startswith("- Conflicting required facts: "):
            payload = line.split(":", 1)[1].strip()
            if not payload:
                return []
            return [p.strip() for p in payload.split(",") if p.strip()]
    return []


def _extract_md_missing_required_fields(md_text: str) -> list[str]:
    lines = md_text.splitlines()
    in_block = False
    out: list[str] = []
    for line in lines:
        if line.strip() == "## Missing Required Facts":
            in_block = True
            continue
        if in_block and line.startswith("## "):
            break
        if in_block and line.startswith("- "):
            value = line[2:].strip()
            if value and value != "none":
                out.append(value)
    return out


def _extract_md_blockers(md_text: str) -> list[str]:
    lines = md_text.splitlines()
    in_block = False
    out: list[str] = []
    for line in lines:
        if line.strip() == "## Exact Remaining Blockers":
            in_block = True
            continue
        if in_block and line.startswith("## "):
            break
        if in_block and line.startswith("- "):
            value = line[2:].strip()
            if value and value != "none":
                out.append(value)
    return out


def test_phase2_readiness_false_when_missing_required_fields(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    monkeypatch.setattr(phase1, "required_fields_for_ticker", lambda t, s: ["a"])
    monkeypatch.setattr(phase1, "optional_fields_for_ticker", lambda t: [])
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "TEST", 0.0)

    collection = {"documents": [], "ticker": "TEST", "security_type": "operating_company"}
    parsed = {"facts": []}

    summary = phase1.build_phase1_report("TEST", "operating_company", collection, parsed)
    assert summary["missing_required_facts"] > 0
    assert summary["phase2_readiness"] is False


def test_phase2_readiness_false_when_conflicting_required_fields(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    monkeypatch.setattr(phase1, "required_fields_for_ticker", lambda t, s: ["a"])
    monkeypatch.setattr(phase1, "optional_fields_for_ticker", lambda t: [])
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "TEST", 0.0)

    collection = {"documents": [], "ticker": "TEST", "security_type": "operating_company"}
    parsed = {"facts": [{"normalized_field": "a", "fact_status": "conflicting"}]}

    summary = phase1.build_phase1_report("TEST", "operating_company", collection, parsed)
    assert summary["required_conflicting_coverage_pct"] > 0.0
    assert summary["phase2_readiness"] is False


def test_phase2_readiness_false_when_required_coverage_below_target(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    monkeypatch.setattr(phase1, "required_fields_for_ticker", lambda t, s: ["a", "b"])
    monkeypatch.setattr(phase1, "optional_fields_for_ticker", lambda t: [])
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "TEST", 80.0)

    collection = {"documents": [], "ticker": "TEST", "security_type": "operating_company"}
    parsed = {
        "facts": [
            {"normalized_field": "a", "fact_status": "verified"},
            {"normalized_field": "b", "fact_status": "uncertain"},
        ]
    }

    summary = phase1.build_phase1_report("TEST", "operating_company", collection, parsed)
    assert summary["required_field_coverage_pct"] < summary["phase2_target_coverage_pct"]
    assert summary["missing_required_facts"] == 0
    assert summary["phase2_readiness"] is False


def test_phase2_readiness_false_when_required_source_failures_present(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    monkeypatch.setattr(phase1, "required_fields_for_ticker", lambda t, s: ["a"])
    monkeypatch.setattr(phase1, "optional_fields_for_ticker", lambda t: [])
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "TEST", 0.0)

    collection = {
        "documents": [
            {
                "source_type": "official_ir_page",
                "collection_status": "error",
                "source_url": "https://example.com",
                "collection_error": "403 Client Error",
                "document_date": "",
            }
        ],
        "ticker": "TEST",
        "security_type": "operating_company",
    }
    parsed = {"facts": [{"normalized_field": "a", "fact_status": "verified"}]}

    summary = phase1.build_phase1_report("TEST", "operating_company", collection, parsed)
    assert summary["source_failures"]
    assert summary["phase2_readiness"] is False


def test_run_phase1_summary_and_review_match_resolved_fact_store(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)

    identity = {
        "ticker": "VBNK",
        "legal_name": "VersaBank",
        "security_type": "bank",
        "exchange": "Nasdaq",
        "reporting_jurisdiction": "Canada",
        "reporting_currency": "CAD",
        "sec_cik": "0001690639",
        "foreign_issuer_status": True,
        "primary_filing_system": "SEC foreign issuer (40-F/6-K)",
        "official_ir_url": "",
        "official_product_url": "",
        "identity_sources": [],
        "identity_confidence": 0.99,
        "identity_status": "verified",
        "verified_at": phase1._utc_now_iso(),
        "identity_notes": "",
    }
    monkeypatch.setattr(phase1, "_build_security_identity_registry", lambda tickers: {"VBNK": identity})
    monkeypatch.setattr(phase1, "_write_official_source_registry", lambda tickers: {t: [] for t in tickers})
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "VBNK", 0.0)

    sample_facts = [
        {"normalized_field": "net_interest_margin", "fact_status": "conflicting", "extraction_method": "html_table_row_match"},
        {"normalized_field": "net_interest_margin", "fact_status": "verified", "extraction_method": "html_table_row_match"},
        {"normalized_field": "allowance_for_credit_losses", "fact_status": "verified", "extraction_method": "html_table_row_match"},
        {"normalized_field": "deposit_growth", "fact_status": "verified", "extraction_method": "xbrl_concept_latest"},
        {"normalized_field": "loan_growth", "fact_status": "verified", "extraction_method": "xbrl_concept_latest"},
    ]

    def _fake_collect(self, ticker, security_type):
        return {
            "ticker": ticker,
            "security_type": security_type,
            "documents": [
                {
                    "source_type": "sec_submissions",
                    "collection_status": "retrieved",
                    "source_url": "https://example.com/submissions",
                    "document_date": "2026-06-01",
                }
            ],
        }

    monkeypatch.setattr(phase1.ResearchCollector, "collect_ticker", _fake_collect)

    def _fake_parse(self, collection):
        payload = {"facts": list(sample_facts)}
        (phase1.FACTS_DIR / "VBNK_phase1_facts.json").write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(phase1.ResearchParser, "parse_ticker", _fake_parse)

    result = phase1.run_phase1(["VBNK"])
    facts_payload = json.loads((phase1.FACTS_DIR / "VBNK_phase1_facts.json").read_text(encoding="utf-8"))
    fact_rows = facts_payload["facts"]
    summary = result["per_ticker"]["VBNK"]["summary"]
    md_text = (phase1.REVIEW_DIR / "VBNK_phase1_facts.md").read_text(encoding="utf-8")

    required_cov = phase1._coverage_from_fields(fact_rows, phase1.required_fields_for_ticker("VBNK", "bank"))
    optional_cov = phase1._coverage_from_fields(fact_rows, phase1.optional_fields_for_ticker("VBNK"))
    expected_conflicting = sorted(required_cov["conflicting"])

    assert summary["required_field_coverage_pct"] == required_cov["verified_coverage_pct"]
    assert summary["optional_field_coverage_pct"] == optional_cov["verified_coverage_pct"]
    assert summary["required_conflicting_coverage_pct"] == required_cov["conflicting_coverage_pct"]

    md_required_cov = _extract_md_scalar(md_text, "Required coverage (verified only)").rstrip("%")
    md_optional_cov = _extract_md_scalar(md_text, "Optional coverage (verified only)").rstrip("%")
    md_conflicting_cov = _extract_md_scalar(md_text, "Required conflicting coverage").rstrip("%")
    assert float(md_required_cov) == required_cov["verified_coverage_pct"]
    assert float(md_optional_cov) == optional_cov["verified_coverage_pct"]
    assert float(md_conflicting_cov) == required_cov["conflicting_coverage_pct"]

    summary_conflicting = []
    for blocker in summary["blockers_for_phase2"]:
        if blocker.startswith("Conflicting required facts: "):
            payload = blocker.split(":", 1)[1].strip()
            summary_conflicting = [p.strip() for p in payload.split(",") if p.strip()]
    assert sorted(summary_conflicting) == expected_conflicting
    assert sorted(_extract_md_conflicting_required_fields(md_text)) == expected_conflicting

    # Readiness should be false when resolved required fields remain missing.
    assert summary["phase2_readiness"] is False
    assert _extract_md_scalar(md_text, "Phase 2 readiness") == "False"


def test_summary_review_and_fact_store_are_identical_for_resolved_status(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)

    identity = {
        "ticker": "ZZZZ",
        "legal_name": "Zeta Labs",
        "security_type": "operating_company",
        "exchange": "Nasdaq",
        "reporting_jurisdiction": "United States",
        "reporting_currency": "USD",
        "sec_cik": "0000000000",
        "foreign_issuer_status": False,
        "primary_filing_system": "SEC domestic issuer (10-K/10-Q)",
        "official_ir_url": "",
        "official_product_url": "",
        "identity_sources": [],
        "identity_confidence": 0.99,
        "identity_status": "verified",
        "verified_at": phase1._utc_now_iso(),
        "identity_notes": "",
    }
    monkeypatch.setattr(phase1, "required_fields_for_ticker", lambda t, s: ["a", "b"])
    monkeypatch.setattr(phase1, "optional_fields_for_ticker", lambda t: ["c"])
    monkeypatch.setitem(phase1.COVERAGE_TARGETS, "ZZZZ", 80.0)

    collection = {
        "documents": [
            {
                "source_type": "sec_submissions",
                "collection_status": "retrieved",
                "source_url": "https://example.com/submissions",
                "document_date": "2026-06-01",
            }
        ],
        "ticker": "ZZZZ",
        "security_type": "operating_company",
    }
    parsed = {
        "facts": [
            {"normalized_field": "a", "fact_status": "verified"},
            {"normalized_field": "b", "fact_status": "uncertain"},
            {"normalized_field": "c", "fact_status": "verified"},
        ]
    }

    summary = phase1.build_phase1_report("ZZZZ", "operating_company", collection, parsed, identity=identity)
    md_text = (phase1.REVIEW_DIR / "ZZZZ_phase1_facts.md").read_text(encoding="utf-8")
    fact_rows = parsed["facts"]
    required_cov = phase1._coverage_from_fields(fact_rows, ["a", "b"])
    optional_cov = phase1._coverage_from_fields(fact_rows, ["c"])

    assert summary["required_field_coverage_pct"] == required_cov["verified_coverage_pct"]
    assert summary["optional_field_coverage_pct"] == optional_cov["verified_coverage_pct"]
    assert summary["missing_required_fields"] == required_cov["missing"]
    assert summary["conflicting_required_fields"] == required_cov["conflicting"]
    assert summary["phase2_readiness"] is False

    assert float(_extract_md_scalar(md_text, "Required coverage (verified only)").rstrip("%")) == summary["required_field_coverage_pct"]
    assert float(_extract_md_scalar(md_text, "Optional coverage (verified only)").rstrip("%")) == summary["optional_field_coverage_pct"]
    assert _extract_md_missing_required_fields(md_text) == summary["missing_required_fields"]
    assert _extract_md_conflicting_required_fields(md_text) == summary["conflicting_required_fields"]
    assert _extract_md_blockers(md_text) == summary["blockers_for_phase2"]
    assert _extract_md_scalar(md_text, "Phase 2 readiness") == str(summary["phase2_readiness"])


def test_review_and_summary_conflicting_fields_match_fact_store(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)

    collection = {
        "documents": [
            {
                "source_type": "sec_submissions",
                "collection_status": "retrieved",
                "source_url": "https://example.com",
                "document_date": "2026-06-01",
            }
        ],
        "ticker": "VBNK",
        "security_type": "bank",
    }
    parsed = {
        "facts": [
            {"normalized_field": "roe", "fact_status": "conflicting", "extraction_method": "html_table_row_match"},
            {"normalized_field": "net_interest_margin", "fact_status": "verified", "extraction_method": "html_table_row_match"},
        ]
    }

    summary = phase1.build_phase1_report("VBNK", "bank", collection, parsed)
    md_text = (phase1.REVIEW_DIR / "VBNK_phase1_facts.md").read_text(encoding="utf-8")
    expected_conflicting = sorted(
        phase1._coverage_from_fields(parsed["facts"], phase1.required_fields_for_ticker("VBNK", "bank"))["conflicting"]
    )

    summary_conflicting = []
    for blocker in summary["blockers_for_phase2"]:
        if blocker.startswith("Conflicting required facts: "):
            summary_conflicting = [p.strip() for p in blocker.split(":", 1)[1].split(",") if p.strip()]

    assert sorted(summary_conflicting) == expected_conflicting
    assert sorted(_extract_md_conflicting_required_fields(md_text)) == expected_conflicting


def test_identifier_mismatch_diagnostic_category():
    cat = phase1._classify_source_failure("CIK not found", "sec_cik_lookup", "NBIS")
    assert cat == "identifier mismatch"


def test_parser_unsupported_diagnostic_category():
    cat = phase1._classify_source_failure("parser unsupported for table", "official_etf_fact_sheet", "SPCX")
    assert cat == "parser unsupported"


def test_no_fabricated_values(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    package = collector.collect_ticker("CRWD", "operating_company")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(package)

    for fact in parsed["facts"]:
        if fact["fact_status"] == "missing":
            assert fact["value"] is None


def test_no_phase2_assumptions(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    result = phase1.run_phase1(["CRWD"])
    blob = json.dumps(result).lower()
    assert "expected alpha" not in blob
    assert "cagr" not in blob
    assert "eipv" not in blob


def test_report_contains_new_sections(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    collector = phase1.ResearchCollector(workspace=tmp_path)
    collection = collector.collect_ticker("CRWD", "operating_company")
    parser = phase1.ResearchParser()
    parsed = parser.parse_ticker(collection)
    phase1.build_phase1_report("CRWD", "operating_company", collection, parsed)

    report = (phase1.REVIEW_DIR / "CRWD_phase1_facts.md").read_text(encoding="utf-8")
    assert "Required coverage (verified only)" in report
    assert "Not Applicable Fields" in report
    assert "Phase 2 readiness" in report


def test_vbnk_exact_consolidated_nim_mapping():
    rows = phase1._classify_vbnk_table_row_label("Net interest margin*")
    assert any(r["normalized_field"] == "net_interest_margin" for r in rows)


def test_vbnk_credit_asset_nim_maps_separately():
    rows = phase1._classify_vbnk_table_row_label("Net interest margin on credit assets*")
    mapped = {r["normalized_field"] for r in rows}
    assert "net_interest_margin_credit_assets" in mapped
    assert "net_interest_margin" not in mapped


def test_vbnk_exact_total_allowance_mapping():
    rows = phase1._classify_vbnk_table_row_label("Allowance for expected credit losses")
    assert any(r["normalized_field"] == "allowance_for_credit_losses" for r in rows)


def test_vbnk_credit_assets_net_of_allowance_maps_separately():
    rows = phase1._classify_vbnk_table_row_label("Credit assets, net of allowance for credit losses")
    mapped = {r["normalized_field"] for r in rows}
    assert "credit_assets_net_of_allowance" in mapped
    assert "allowance_for_credit_losses" not in mapped


def test_vbnk_provision_not_allowance():
    rows = phase1._classify_vbnk_table_row_label("Provision for credit losses")
    mapped = {r["normalized_field"] for r in rows}
    assert "provision_for_credit_losses" in mapped
    assert "allowance_for_credit_losses" not in mapped


def test_vbnk_stage_specific_allowance_mapping():
    rows = phase1._classify_vbnk_table_row_label("Allowance for credit losses stage 2")
    assert any(r["normalized_field"] == "allowance_for_credit_losses_stage_2" for r in rows)


def test_definition_aware_conflict_key_prevents_false_conflict():
    f1 = phase1.Phase1Fact(
        ticker="VBNK",
        normalized_field="net_interest_margin",
        original_field="Net interest margin",
        taxonomy="table",
        value=2.18,
        unit="percent",
        period="2026-04-30",
        source_document_id="doc1",
        source_url="u1",
        source_date="2026-06-03",
        extracted_at=phase1._utc_now_iso(),
        confidence=90.0,
        extraction_method="html_table_row_match",
        raw_text_reference="x",
        fact_status="verified",
        definition="consolidated_bank_net_interest_margin",
        period_start="2026-02-01",
        period_end="2026-04-30",
        consolidation_scope="consolidated_bank",
    )
    f2 = phase1.Phase1Fact(
        ticker="VBNK",
        normalized_field="net_interest_margin",
        original_field="Net interest margin on credit assets",
        taxonomy="table",
        value=2.71,
        unit="percent",
        period="2026-04-30",
        source_document_id="doc2",
        source_url="u2",
        source_date="2026-06-03",
        extracted_at=phase1._utc_now_iso(),
        confidence=90.0,
        extraction_method="html_table_row_match",
        raw_text_reference="y",
        fact_status="verified",
        definition="net_interest_margin_on_credit_assets",
        period_start="2026-02-01",
        period_end="2026-04-30",
        consolidation_scope="credit_assets",
    )

    key1 = (f1.normalized_field, f1.definition, f1.period_start or f1.period, f1.period_end or f1.period, f1.currency, f1.consolidation_scope)
    key2 = (f2.normalized_field, f2.definition, f2.period_start or f2.period, f2.period_end or f2.period, f2.currency, f2.consolidation_scope)
    assert key1 != key2


def test_identity_lifecycle_type_mismatch_marks_reassigned():
    lifecycle = phase1._resolve_identity_lifecycle(
        ticker="ABCD",
        expected_security_type="etf_fund",
        legal_name="Example Operating Company",
        sec_cik="0001234567",
        forms=["8-K", "10-K"],
        history_registry={},
    )
    assert lifecycle["identity_status"] == "ticker_reassigned"
    assert lifecycle["identity_resolution"] == "reject_current_mapping"


def test_identity_lifecycle_redirects_when_canonical_cik_differs():
    history = {
        "SPCX": [
            {
                "name": "Defiance Next Gen ETF",
                "sec_cik": "0000001111",
                "security_type": "etf_fund",
                "current": True,
                "effective_from": "2020-01-01",
            }
        ]
    }
    lifecycle = phase1._resolve_identity_lifecycle(
        ticker="SPCX",
        expected_security_type="etf_fund",
        legal_name="Space Exploration Technologies Corp",
        sec_cik="0001181412",
        forms=["8-K", "S-1"],
        history_registry=history,
    )
    assert lifecycle["identity_status"] == "ticker_reassigned"
    assert lifecycle["identity_resolution"] == "redirect"
    assert lifecycle["canonical_identity"]["sec_cik"] == "0000001111"


def test_identity_lifecycle_uses_multi_identity_history_when_current_matches():
    history = {
        "ABCD": [
            {
                "name": "Legacy ABCD Trust",
                "sec_cik": "0000001000",
                "security_type": "operating_company",
                "current": False,
                "effective_from": "2010-01-01",
                "effective_to": "2019-12-31",
            },
            {
                "name": "ABCD Holdings Inc",
                "sec_cik": "0000002000",
                "security_type": "operating_company",
                "current": True,
                "effective_from": "2020-01-01",
            },
        ]
    }
    lifecycle = phase1._resolve_identity_lifecycle(
        ticker="ABCD",
        expected_security_type="operating_company",
        legal_name="ABCD Holdings Inc",
        sec_cik="0000002000",
        forms=["10-K"],
        history_registry=history,
    )
    assert lifecycle["identity_status"] == "verified"
    assert lifecycle["identity_resolution"] == "multi_identity_history"
    assert len(lifecycle["historical_identities"]) == 2


def test_fact_status_audit_identity_gate_generic_ticker():
    rows = phase1._build_fact_status_audit(
        previous_facts={"ABCD": []},
        current_facts={
            "ABCD": [
                {
                    "normalized_field": "fund_strategy",
                    "fact_status": "missing",
                    "extraction_method": "identity_gate",
                    "source_document_id": "",
                    "source_url": "",
                }
            ]
        },
    )
    assert rows
    assert rows[0]["ticker"] == "ABCD"
    assert "Identity-gated because ABCD is not identity-verified" in rows[0]["reason_for_change"]


def test_run_phase1_identity_gate_applies_to_any_non_verified_ticker(monkeypatch, tmp_path):
    _prepare_tmp_layout(monkeypatch, tmp_path)
    _patch_sources(monkeypatch)

    monkeypatch.setattr(
        phase1,
        "_build_security_identity_registry",
        lambda tickers: {
            "CRWD": {
                "ticker": "CRWD",
                "legal_name": "CrowdStrike Holdings, Inc.",
                "security_type": "operating_company",
                "exchange": "Nasdaq",
                "reporting_jurisdiction": "United States",
                "reporting_currency": "USD",
                "sec_cik": "0001535527",
                "foreign_issuer_status": False,
                "primary_filing_system": "SEC domestic issuer (10-K/10-Q)",
                "official_ir_url": "",
                "official_product_url": "",
                "identity_sources": [],
                "identity_confidence": 0.99,
                "identity_status": "ticker_reassigned",
                "verified_at": phase1._utc_now_iso(),
                "identity_notes": "test",
            }
        },
    )

    def should_not_collect(self, ticker, security_type):
        raise AssertionError("Collection should be identity-gated for any non-verified ticker")

    monkeypatch.setattr(phase1.ResearchCollector, "collect_ticker", should_not_collect)

    result = phase1.run_phase1(["CRWD"])
    assert result["per_ticker"]["CRWD"]["summary"]["phase2_readiness"] is False
    assert result["per_ticker"]["CRWD"]["identity"]["identity_status"] == "ticker_reassigned"
