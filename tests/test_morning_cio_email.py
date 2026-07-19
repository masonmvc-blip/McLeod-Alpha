from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import cio_email.morning_report as morning_report


class _NoOpParser(HTMLParser):
    pass


class FakeEngine:
    def __init__(self):
        self.portfolio_data = {"sync_timestamp": "2026-07-17T06:00:00-05:00"}
        self.summary_data = {"sync_timestamp": "2026-07-17T06:00:00-05:00"}
        self.equities = [
            {"symbol": "AAA", "asset_type": "EQUITY"},
            {"symbol": "BBB", "asset_type": "EQUITY"},
        ]
        self.options = [
            {"symbol": "AAA 2026C100", "quantity": 1, "average_price": 1.23, "market_value": 123.0, "day_pl": 4.5, "day_pl_pct": 3.7},
        ]
        self._research = {
            ("AAA", "business_quality"): 90,
            ("AAA", "valuation"): 80,
            ("AAA", "expected_alpha"): 12,
            ("AAA", "expected_2yr_cagr"): 18,
            ("AAA", "expected_10yr_cagr"): 15,
            ("AAA", "thesis_health"): "HEALTHY",
            ("BBB", "business_quality"): 75,
            ("BBB", "valuation"): 72,
            ("BBB", "expected_alpha"): 9,
            ("BBB", "expected_2yr_cagr"): 14,
            ("BBB", "expected_10yr_cagr"): 11,
            ("BBB", "thesis_health"): "AT_RISK",
        }

    def get_portfolio_metrics(self):
        return {
            "account_number": "12345678",
            "account_type": "MARGIN",
            "total_portfolio_value": 100000.0,
            "equity_value": 87500.0,
            "cash_balance": 12500.0,
            "buying_power": 30000.0,
            "maintenance_requirement": 15000.0,
            "margin_efficiency_score": 30.0,
            "num_equities": 2,
            "num_options": 1,
        }

    def rank_core_holdings(self):
        return [
            {
                "rank": 1,
                "symbol": "AAA",
                "composite_score": 92.1,
                "weight_pct": 12.5,
                "thesis_health": "HEALTHY",
                "data_quality": 98,
                "business_quality": 90,
                "expected_alpha": 12,
                "valuation": 80,
                "expected_2yr_cagr": 18,
                "expected_10yr_cagr": 15,
                "missing_core_inputs": 0,
            },
            {
                "rank": 2,
                "symbol": "BBB",
                "composite_score": 81.7,
                "weight_pct": 8.0,
                "thesis_health": "AT_RISK",
                "data_quality": 95,
                "business_quality": 75,
                "expected_alpha": 9,
                "valuation": 72,
                "expected_2yr_cagr": 14,
                "expected_10yr_cagr": 11,
                "missing_core_inputs": 0,
            },
        ]

    def estimate_target_weights(self, method="mcleod_optimized"):
        return [
            {
                "symbol": "AAA",
                "current_weight_pct": 12.5,
                "target_weight_pct": 11.0,
                "diff_pct": -1.5,
                "current_value": 12500.0,
                "target_value": 11000.0,
                "diff_value": -1500.0,
                "action": "SELL",
                "priority": 1.5,
            },
            {
                "symbol": "BBB",
                "current_weight_pct": 8.0,
                "target_weight_pct": 10.0,
                "diff_pct": 2.0,
                "current_value": 8000.0,
                "target_value": 10000.0,
                "diff_value": 2000.0,
                "action": "BUY",
                "priority": 2.0,
            },
        ]

    def identify_replacement_candidates(self):
        return [
            {
                "symbol": "BBB",
                "rank": 2,
                "market_value": 8000.0,
                "weight_pct": 8.0,
                "day_pl_pct": -1.1,
                "liquidity_score": 61,
                "composite_score": 81.7,
                "reason": "Lower-ranked holding",
            }
        ]

    def calculate_eipv_rankings(self, allocation_amount):
        return [
            {
                "symbol": "AAA",
                "eipv_score": 3.4,
                "current_weight_pct": 12.5,
                "target_weight_pct": 11.0,
                "new_weight_pct": 13.4,
                "potential_value_add": 1034.0,
            }
        ]

    def get_research_value(self, symbol, field):
        return self._research.get((symbol, field), morning_report.RESEARCH_NEEDED)


def _fake_news(symbols):
    findings = [
        morning_report.NewsFinding(
            symbol="AAA",
            status="ok",
            docs=[{"form": "8-K", "filing_date": "2026-07-16", "excerpt": "AAA filed an 8-K with an operating update."}],
            source_timestamp="2026-07-17T06:05:00-05:00",
            source_urls=["https://example.com/aaa"],
        )
    ]
    return "complete", findings, ""


def test_dry_run_generates_html_and_text(monkeypatch, tmp_path):
    monkeypatch.setattr(morning_report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(morning_report, "LATEST_HTML", tmp_path / "latest_morning_cio_report.html")
    monkeypatch.setattr(morning_report, "LATEST_TEXT", tmp_path / "latest_morning_cio_report.txt")
    monkeypatch.setattr(morning_report, "LATEST_JSON", tmp_path / "latest_morning_cio_report.json")
    monkeypatch.setattr(morning_report, "STATE_PATH", tmp_path / "latest_morning_cio_state.json")
    monkeypatch.setattr(morning_report, "RUN_LOG_PATH", tmp_path / "morning_cio_email.jsonl")
    monkeypatch.setattr(morning_report, "LOCK_PATH", tmp_path / "morning_cio_email.lock")
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": False, "returncode": 1, "stdout": "", "stderr": "offline"})
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)

    previous_state = {"thesis_health": {"AAA": "HEALTHY", "BBB": "HEALTHY"}}
    logger = morning_report._configure_logger("test-run")
    bundle = morning_report._build_bundle(force=True, logger=logger, previous_state=previous_state)
    text_body, html_body, payload, sections = morning_report.build_report(bundle)

    assert [section.title for section in sections] == [
        "Executive Summary",
        "High-Conviction Actions",
        "McLeod Core Rankings",
        "Phase 2 Research",
        "Best Next Investment Dollar by EIPV",
        "Current Weight vs. Target Weight",
        "Replacement Candidates, excluding SPCX",
        "Thesis Health Changes",
        "Material Overnight News Affecting Current Holdings",
        "Options Position Review",
        "Data Quality Score",
        "Missing Data",
    ]
    assert "Executive Summary" in text_body
    assert "Thesis Health Changes" in text_body
    assert "BBB: HEALTHY -> AT_RISK" in text_body
    assert "Data Quality Score" in text_body
    assert payload["account_display"]

    parser = _NoOpParser()
    parser.feed(html_body)
    assert html_body.startswith("<!DOCTYPE html>")
    assert "McLeod Morning CIO Report" in html_body
    assert "Executive Summary" in html_body


def test_smtp_password_is_stripped_before_login(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "cio@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "  a b c d  ")
    monkeypatch.setenv("EMAIL_TO", "dest@example.com")
    monkeypatch.setenv("EMAIL_FROM_NAME", "McLeod Alpha")

    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls["host"] = host
            calls["port"] = port
            calls["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, username, password):
            calls["username"] = username
            calls["password"] = password

        def send_message(self, message):
            calls["to"] = message["To"]
            calls["subject"] = message["Subject"]
            return {}

    monkeypatch.setattr(morning_report.smtplib, "SMTP_SSL", FakeSMTP)

    result = morning_report._smtp_send(
        report=object(),
        html_body="<html></html>",
        text_body="plain text",
        subject="McLeod Morning CIO Report | 2026-07-17 | Daily Review",
        logger=morning_report._configure_logger("smtp-test"),
    )

    assert result["accepted"] is True
    assert calls["host"] == "smtp.gmail.com"
    assert calls["port"] == 465
    assert calls["username"] == "cio@example.com"
    assert calls["password"] == "abcd"
    assert calls["to"] == "dest@example.com"


def test_lock_file_blocks_duplicate_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(morning_report, "LOCK_PATH", tmp_path / "morning_cio_email.lock")
    morning_report._acquire_lock()
    try:
        try:
            morning_report._acquire_lock()
            raise AssertionError("expected lock acquisition to fail")
        except RuntimeError:
            pass
    finally:
        morning_report._release_lock()


def test_strict_recommendation_gate_restricts_actions(monkeypatch):
    class GapEngine(FakeEngine):
        def rank_core_holdings(self):
            rows = super().rank_core_holdings()
            for row in rows:
                row["business_quality"] = morning_report.RESEARCH_NEEDED
            return rows

    monkeypatch.setenv("MORNING_CIO_STRICT_RECOMMENDATIONS", "true")
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", GapEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)

    bundle = morning_report._build_bundle(force=True, logger=morning_report._configure_logger("strict-gate"), previous_state={"thesis_health": {"AAA": "HEALTHY"}})
    assert bundle.high_conviction_actions
    assert len(bundle.high_conviction_actions) == 1
    assert bundle.high_conviction_actions[0]["type"] == "Fix data"
    assert "restricted" in bundle.high_conviction_actions[0]["summary"].lower()


def test_smtp_only_mode_fails_without_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("MORNING_CIO_REQUIRE_SMTP_ONLY", "true")
    monkeypatch.setenv("EMAIL_ADDRESS", "cio@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("EMAIL_TO", "dest@example.com")

    monkeypatch.setattr(morning_report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(morning_report, "LATEST_HTML", tmp_path / "latest_morning_cio_report.html")
    monkeypatch.setattr(morning_report, "LATEST_TEXT", tmp_path / "latest_morning_cio_report.txt")
    monkeypatch.setattr(morning_report, "LATEST_JSON", tmp_path / "latest_morning_cio_report.json")
    monkeypatch.setattr(morning_report, "LEGACY_MARKDOWN_PATH", tmp_path / "morning_cio_report_latest.md")
    monkeypatch.setattr(morning_report, "STATE_PATH", tmp_path / "latest_morning_cio_state.json")
    monkeypatch.setattr(morning_report, "RUN_LOG_PATH", tmp_path / "morning_cio_email.jsonl")
    monkeypatch.setattr(morning_report, "LOCK_PATH", tmp_path / "morning_cio_email.lock")
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)

    def fail_smtp(*args, **kwargs):
        raise RuntimeError("smtp fail")

    monkeypatch.setattr(morning_report, "_smtp_send", fail_smtp)
    mail_called = {"used": False}

    def mail_stub(*args, **kwargs):
        mail_called["used"] = True
        return {"accepted": True}

    monkeypatch.setattr(morning_report, "_mailapp_send", mail_stub)

    rc = morning_report.main(["--send", "--force"])
    assert rc == 4
    assert mail_called["used"] is False


def test_contract_script_passes_current_files():
    root = Path(__file__).resolve().parent.parent
    py = root / "venv" / "bin" / "python"
    if not py.exists():
        py = root / ".venv" / "bin" / "python"
    exec_py = str(py) if py.exists() else "python3"
    result = subprocess.run([exec_py, str(root / "scripts" / "verify_morning_cio_contract.py")], cwd=str(root), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
