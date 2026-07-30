from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from engine import research_phase1
from engine.data_sources import sec_source
from scripts import spcx_daily_accumulator as accumulator


def test_capped_limit_price_never_exceeds_live_ask():
    assert accumulator.capped_limit_price(Decimal("100.00")) == Decimal("100.00")
    assert accumulator.capped_limit_price(Decimal("123.45")) == Decimal("123.45")
    assert accumulator.capped_limit_price(Decimal("123.456")) == Decimal("123.45")


def test_parse_quote_requires_spacex_identity():
    payload = {
        "SPCX": {
            "symbol": "SPCX",
            "quote": {"askPrice": 402.12, "bidPrice": 401.90},
            "reference": {
                "cusip": accumulator.EXPECTED_CUSIP,
                "description": "Space Exploration Technologies Corp Class A",
            },
        }
    }
    snapshot = accumulator.parse_quote(payload)
    assert snapshot.symbol == "SPCX"
    assert snapshot.cusip == accumulator.EXPECTED_CUSIP
    assert snapshot.ask == Decimal("402.12")


def test_parse_quote_rejects_legacy_spcx_identity():
    payload = {
        "SPCX": {
            "symbol": "SPCX",
            "quote": {"askPrice": 42.00},
            "reference": {
                "cusip": "26923N108",
                "description": "The SPAC and New Issue ETF",
            },
        }
    }
    with pytest.raises(RuntimeError, match="identity guard failed"):
        accumulator.parse_quote(payload)


def test_research_identity_maps_spcx_to_spacex_operating_company():
    assert research_phase1.SECURITY_TYPE_BY_TICKER["SPCX"] == "operating_company"
    assert sec_source.TICKER_TO_CIK["SPCX"] == "0001181412"
    assert "spacex" in research_phase1._expected_identity_terms("SPCX")
    assert research_phase1.OFFICIAL_SOURCE_URLS["SPCX"] == {
        "official_ir_page": "https://ir.spacex.com/"
    }


def test_duplicate_guard_detects_todays_spcx_buy():
    orders = [
        {
            "status": "FILLED",
            "enteredTime": "2026-07-28T13:30:01Z",
            "orderLegCollection": [
                {"instruction": "BUY", "instrument": {"symbol": "SPCX"}}
            ],
        }
    ]
    assert accumulator.duplicate_order_exists(orders, date(2026, 7, 28))
    assert not accumulator.duplicate_order_exists(orders, date(2026, 7, 29))


def test_duplicate_guard_ignores_cancelled_order():
    orders = [
        {
            "status": "CANCELED",
            "enteredTime": "2026-07-28T13:30:01Z",
            "orderLegCollection": [
                {"instruction": "BUY", "instrument": {"symbol": "SPCX"}}
            ],
        }
    ]
    assert not accumulator.duplicate_order_exists(orders, date(2026, 7, 28))


def test_ledger_guard_blocks_repeat_after_submission_started(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        '{"event":"submission_started","session_date":"2026-07-28"}\n',
        encoding="utf-8",
    )
    assert accumulator._ledger_has_submission_started(date(2026, 7, 28), ledger)


def test_opening_window_is_narrow():
    assert accumulator.opening_window_is_valid(
        datetime(2026, 7, 28, 13, 30, tzinfo=timezone.utc)
    )
    assert not accumulator.opening_window_is_valid(
        datetime(2026, 7, 28, 13, 33, tzinfo=timezone.utc)
    )


def test_execution_price_uses_weighted_fill_price():
    order = {
        "orderActivityCollection": [
            {
                "executionLegs": [
                    {"price": 100.0, "quantity": 0.25},
                    {"price": 100.2, "quantity": 0.75},
                ]
            }
        ]
    }
    assert accumulator._execution_price(order) == "100.1500"


def test_force_cannot_be_combined_with_execution(monkeypatch):
    monkeypatch.setattr(accumulator, "_load_env", lambda: None)
    with pytest.raises(RuntimeError, match="prohibited"):
        accumulator.main(["--execute", "--force"])


def test_record_serializes_decimal_quote_fields(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    latest = tmp_path / "latest.json"
    monkeypatch.setattr(accumulator, "LATEST_PATH", latest)

    accumulator._record(
        {"event": "dry_run", "quote": {"ask": Decimal("115.57")}},
        ledger,
    )

    assert json.loads(ledger.read_text())["quote"]["ask"] == "115.57"
    assert json.loads(latest.read_text())["quote"]["ask"] == "115.57"


def test_installer_uses_live_weekday_open_schedule():
    installer = (
        accumulator.PROJECT_ROOT
        / "scripts"
        / "install_spcx_daily_accumulator_launchagent.sh"
    ).read_text(encoding="utf-8")

    schedule = installer.split("<key>StartCalendarInterval</key>", 1)[1].split(
        "</array>", 1
    )[0]
    assert "--execute" in installer
    assert schedule.count("<key>Weekday</key>") == 5
    for weekday in range(1, 6):
        assert f"<key>Weekday</key><integer>{weekday}</integer>" in schedule
    assert "<key>Weekday</key><integer>6</integer>" not in schedule
