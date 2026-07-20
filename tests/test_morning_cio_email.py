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


def _redirect_runtime_paths(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(morning_report, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(morning_report, "REPORT_DIR", report_dir)
    monkeypatch.setattr(morning_report, "ARCHIVE_DIR", report_dir / "archive")
    monkeypatch.setattr(morning_report, "LATEST_HTML", report_dir / "latest_morning_cio_report.html")
    monkeypatch.setattr(morning_report, "LATEST_TEXT", report_dir / "latest_morning_cio_report.txt")
    monkeypatch.setattr(morning_report, "LATEST_JSON", report_dir / "latest_morning_cio_report.json")
    monkeypatch.setattr(morning_report, "DELIVERY_REGISTRY_PATH", report_dir / "delivery_registry.jsonl")
    monkeypatch.setattr(morning_report, "LEGACY_MARKDOWN_PATH", tmp_path / "morning_cio_report_latest.md")
    monkeypatch.setattr(morning_report, "STATE_PATH", report_dir / "latest_morning_cio_state.json")
    monkeypatch.setattr(morning_report, "RUN_LOG_PATH", tmp_path / "morning_cio_email.jsonl")
    monkeypatch.setattr(morning_report, "LOCK_PATH", tmp_path / "morning_cio_email.lock")


def test_dry_run_generates_html_and_text(monkeypatch, tmp_path):
    _redirect_runtime_paths(monkeypatch, tmp_path)
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

    morning_report._write_artifacts(bundle, text_body, html_body, payload)
    archive_dir = morning_report.ARCHIVE_DIR / bundle.report_date
    assert (archive_dir / "morning_cio_report.md").exists()
    assert (archive_dir / "morning_cio_report.html").exists()
    assert (archive_dir / "morning_cio_report.json").exists()


def test_report_rendering_is_deterministic_for_same_bundle(monkeypatch):
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": False, "returncode": 1, "stdout": "", "stderr": "offline"})
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)
    bundle = morning_report._build_bundle(
        force=True,
        logger=morning_report._configure_logger("determinism"),
        previous_state={"thesis_health": {"AAA": "HEALTHY", "BBB": "HEALTHY"}},
        report_date="2026-07-17",
    )
    first = morning_report.build_report(bundle)
    second = morning_report.build_report(bundle)
    assert first[:3] == second[:3]


def test_cli_dry_run_writes_artifacts_without_delivery(monkeypatch, tmp_path):
    _redirect_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)
    monkeypatch.setattr(morning_report, "_smtp_send", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry run sent email")))

    assert morning_report.main(["--dry-run", "--date", "2026-07-17"]) == 0
    assert morning_report.LATEST_HTML.exists()
    assert morning_report.LATEST_JSON.exists()
    assert (morning_report.ARCHIVE_DIR / "2026-07-17" / "morning_cio_report.md").exists()
    assert not morning_report.DELIVERY_REGISTRY_PATH.exists()


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

    _redirect_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)

    def fail_smtp(*args, **kwargs):
        raise RuntimeError("smtp fail")

    monkeypatch.setattr(morning_report, "_smtp_send", fail_smtp)
    outlook_called = {"used": False}

    def outlook_stub(*args, **kwargs):
        outlook_called["used"] = True
        return {"accepted": True}

    monkeypatch.setattr(morning_report, "_outlook_send", outlook_stub)

    rc = morning_report.main(["--send", "--force"])
    assert rc == 4
    assert outlook_called["used"] is False


def test_outlook_fallback_never_targets_mail_app(monkeypatch):
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(morning_report.subprocess, "run", fake_run)

    result = morning_report._outlook_send(
        "dest@example.com",
        "Morning CIO",
        "Report body",
        morning_report._configure_logger("outlook-test"),
    )

    assert result["transport"] == "outlook"
    assert "Microsoft Outlook" in calls["command"][-1]
    assert "Mail\"" not in calls["command"][-1]


def test_missing_credentials_fail_closed(monkeypatch, tmp_path):
    _redirect_runtime_paths(monkeypatch, tmp_path)
    for name in ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD", "EMAIL_TO", "EXPECTED_EMAIL_ADDRESS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)

    assert morning_report.main(["--send", "--date", "2026-07-17", "--force"]) == 3
    rows = [json.loads(line) for line in morning_report.DELIVERY_REGISTRY_PATH.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["event"] == "send_failed"
    assert set(rows[-1]) <= {
        "run_id", "report_date", "event", "status", "transport", "recipient",
        "subject", "content_sha256", "error", "logged_at",
    }


def test_same_report_date_is_not_sent_twice(monkeypatch, tmp_path):
    _redirect_runtime_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("EMAIL_ADDRESS", "cio@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("EMAIL_TO", "dest@example.com")
    monkeypatch.setenv("MORNING_CIO_REQUIRE_SMTP_ONLY", "true")
    monkeypatch.setattr(morning_report, "_run_portfolio_refresh", lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    monkeypatch.setattr(morning_report, "_check_news", _fake_news)

    sends = []

    def smtp_stub(*args, **kwargs):
        sends.append(kwargs.get("subject") or args[3])
        return {"accepted": True, "attempt": 1, "refused": {}}

    monkeypatch.setattr(morning_report, "_smtp_send", smtp_stub)
    assert morning_report.main(["--send", "--date", "2026-07-17"]) == 0
    assert morning_report.main(["--send", "--date", "2026-07-17"]) == 0
    assert len(sends) == 1

    rows = [json.loads(line) for line in morning_report.DELIVERY_REGISTRY_PATH.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["send_succeeded", "send_skipped_duplicate"]


def test_reporting_module_does_not_import_production_execution_engine():
    source = Path(morning_report.__file__).read_text(encoding="utf-8")
    assert "execution.live_engine" not in source
    assert "phase3_monitor" not in source
    assert "place_order" not in source


def test_portfolio_refresh_output_is_not_logged(monkeypatch):
    class CaptureLogger:
        def __init__(self):
            self.calls = []

        def info(self, message, *args):
            self.calls.append((message, args))

    secret_marker = "account-secret-marker"
    monkeypatch.setattr(
        morning_report,
        "_run_portfolio_refresh",
        lambda: {"attempted": True, "succeeded": True, "returncode": 0, "stdout": secret_marker, "stderr": secret_marker},
    )
    monkeypatch.setattr(morning_report, "_load_engine", FakeEngine)
    logger = CaptureLogger()
    morning_report.get_current_portfolio(logger=logger)
    assert secret_marker not in repr(logger.calls)


def test_contract_script_passes_current_files():
    root = Path(__file__).resolve().parent.parent
    py = root / "venv" / "bin" / "python"
    if not py.exists():
        py = root / ".venv" / "bin" / "python"
    exec_py = str(py) if py.exists() else "python3"
    result = subprocess.run([exec_py, str(root / "scripts" / "verify_morning_cio_contract.py")], cwd=str(root), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
