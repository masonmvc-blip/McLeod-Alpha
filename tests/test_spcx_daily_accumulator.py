from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from engine import research_phase1
from engine.data_sources import sec_source
from scripts import spcx_daily_accumulator as accumulator


def test_direct_script_execution_can_import_operational_helpers(tmp_path):
    probe = (
        "import importlib, runpy, sys; "
        "runpy.run_path(sys.argv[1], run_name='spcx_import_probe'); "
        "importlib.import_module('ops.runtime_alerts')"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", probe, str(Path(accumulator.__file__).resolve())],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_capped_limit_price_never_exceeds_live_ask():
    assert accumulator.capped_limit_price(Decimal("100.00")) == Decimal("100.00")
    assert accumulator.capped_limit_price(Decimal("123.45")) == Decimal("123.45")
    assert accumulator.capped_limit_price(Decimal("123.456")) == Decimal("123.45")


def test_margin_buying_power_is_used_only_when_explicitly_enabled():
    account = {
        "securitiesAccount": {
            "currentBalances": {
                "cashAvailableForTrading": 0,
                "availableFundsNonMarginableTrade": 135.65,
                "buyingPowerNonMarginableTrade": 135.65,
                "availableFunds": 135.65,
                "buyingPower": 542.60,
            }
        }
    }
    assert accumulator._available_buying_power(account, allow_margin=False) == (
        Decimal("135.65"),
        "non_margin",
    )
    assert accumulator._available_buying_power(account, allow_margin=True) == (
        Decimal("542.6"),
        "margin",
    )


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


def test_ledger_guard_allows_retry_after_confirmed_nonfill(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        '\n'.join(
            [
                '{"event":"submission_started","session_date":"2026-07-28"}',
                '{"event":"submitted","session_date":"2026-07-28","order_id":"abc123"}',
                '{"event":"terminal","session_date":"2026-07-28","order_id":"abc123","status":"CANCELED"}',
            ]
        )
        + '\n',
        encoding="utf-8",
    )
    assert not accumulator._ledger_has_submission_started(date(2026, 7, 28), ledger)


def test_opening_window_is_narrow():
    assert accumulator.opening_window_is_valid(
        datetime(2026, 7, 28, 13, 30, tzinfo=timezone.utc)
    )
    assert accumulator.opening_window_is_valid(
        datetime(2026, 7, 28, 13, 33, tzinfo=timezone.utc)
    )
    assert accumulator.opening_window_is_valid(
        datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc)
    )
    assert not accumulator.opening_window_is_valid(
        datetime(2026, 7, 28, 13, 36, tzinfo=timezone.utc)
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


def test_quote_benchmarks_record_bid_midpoint_and_spread():
    quote = accumulator.QuoteSnapshot(
        "SPCX",
        accumulator.EXPECTED_CUSIP,
        "SpaceX",
        Decimal("134.90"),
        Decimal("134.70"),
        "2026-08-25T09:30:07-04:00",
    )
    assert accumulator._quote_benchmarks(quote) == {
        "bid": "134.70",
        "midpoint": "134.8000",
        "spread": "0.2000",
        "spread_bps": "14.84",
    }


def test_execution_quality_records_fill_benchmarks_and_broker_latency():
    plan = accumulator.OrderPlan(
        session_date="2026-08-25",
        symbol="SPCX",
        quantity=1,
        bid="134.70",
        ask="134.90",
        midpoint="134.8000",
        spread="0.2000",
        spread_bps="14.84",
        quote_time="2026-08-25T09:30:07-04:00",
        limit_price="134.90",
        cap_percent="0.00",
        cancel_after_seconds=120,
        account_suffix="0903",
        available_buying_power="1000.00",
        buying_power_source="non_margin",
        margin_buying_enabled=False,
    )
    order = {
        "enteredTime": "2026-08-25T13:30:07+0000",
        "orderActivityCollection": [
            {
                "executionLegs": [
                    {
                        "time": "2026-08-25T13:30:20+0000",
                        "price": 134.80,
                        "quantity": 1,
                    }
                ]
            }
        ],
    }
    assert accumulator._execution_quality(plan, order) == {
        "execution_price": "134.8000",
        "execution_time": "2026-08-25T13:30:20+0000",
        "broker_fill_seconds": "13.000",
        "price_improvement_vs_ask": "0.1000",
        "price_improvement_bps": "7.41",
        "execution_vs_midpoint": "0.0000",
        "spread_capture_percent": "50.00",
    }


def test_order_status_400_recovers_from_account_collection(monkeypatch):
    class Response:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class Client:
        def get_order(self, order_id, account_hash):
            return Response({}, 400)

        def get_orders_for_account(self, account_hash):
            return Response([{"orderId": "abc123", "status": "FILLED"}])

    monkeypatch.setattr(accumulator, "CANCEL_AFTER_SECONDS", 1)
    monkeypatch.setattr(accumulator.time, "sleep", lambda _: None)
    status, order = accumulator._wait_for_terminal_state(Client(), "acct", "abc123")
    assert status == "FILLED"
    assert order["orderId"] == "abc123"


def test_order_status_400_does_not_blindly_cancel_when_order_unknown(monkeypatch):
    class Response:
        status_code = 400

        def raise_for_status(self):
            raise RuntimeError("HTTP 400")

        def json(self):
            return []

    class Client:
        def get_order(self, order_id, account_hash):
            return Response()

        def get_orders_for_account(self, account_hash):
            return Response()

        def cancel_order(self, order_id, account_hash):
            raise AssertionError("must not blindly cancel an unidentified order")

    monkeypatch.setattr(accumulator, "CANCEL_AFTER_SECONDS", 0)
    status, order = accumulator._wait_for_terminal_state(Client(), "acct", "abc123")
    assert status == "STATUS_UNCERTAIN"
    assert order["orderId"] == "abc123"


def test_timeout_confirms_cancellation_for_safe_recovery(monkeypatch):
    class Response:
        status_code = 200

        def __init__(self, payload=None):
            self._payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def __init__(self):
            self.cancelled = False

        def get_orders_for_account(self, account_hash):
            status = "CANCELED" if self.cancelled else "WORKING"
            return Response([{"orderId": "abc123", "status": status}])

        def cancel_order(self, order_id, account_hash):
            self.cancelled = True
            return Response()

    monkeypatch.setattr(accumulator, "CANCEL_AFTER_SECONDS", 0)
    monkeypatch.setattr(accumulator, "CANCEL_CONFIRM_SECONDS", 1)
    status, order = accumulator._wait_for_terminal_state(Client(), "acct", "abc123")
    assert status == "CANCELED"
    assert order["orderId"] == "abc123"


def test_force_cannot_be_combined_with_execution(monkeypatch):
    monkeypatch.setattr(accumulator, "_load_env", lambda: None)
    with pytest.raises(RuntimeError, match="prohibited"):
        accumulator.main(["--execute", "--force"])


def test_auth_failure_is_recorded_and_returns_immediately(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    latest = tmp_path / "latest.json"
    alert = tmp_path / "runtime_alert.json"
    monkeypatch.setattr(accumulator, "_load_env", lambda: None)
    monkeypatch.setattr(accumulator, "is_trading_session", lambda _day: True)
    monkeypatch.setattr(accumulator, "opening_window_is_valid", lambda _now: True)
    monkeypatch.setattr(accumulator, "_create_client", lambda: (_ for _ in ()).throw(RuntimeError("expired")))
    monkeypatch.setattr(accumulator, "LEDGER_PATH", ledger)
    monkeypatch.setattr(accumulator, "LATEST_PATH", latest)
    from ops import runtime_alerts
    monkeypatch.setattr(runtime_alerts, "ALERT_PATH", alert)

    assert accumulator.main([]) == 1
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["event"] == "blocked"
    assert payload["reason"] == "schwab_reauthentication_required"
    assert json.loads(alert.read_text(encoding="utf-8"))["active"] is True


def test_confirmed_nonfill_returns_error_and_sets_alert(tmp_path, monkeypatch):
    class Response:
        headers = {"Location": "/orders/abc123"}

        def __init__(self, payload=None):
            self._payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def get_orders_for_account(self, account_hash):
            return Response([])

        def get_account(self, account_hash):
            return Response(
                {"securitiesAccount": {"currentBalances": {"cashAvailableForTrading": 1000}}}
            )

        def place_order(self, account_hash, order):
            return Response()

    ledger = tmp_path / "ledger.jsonl"
    latest = tmp_path / "latest.json"
    alert = tmp_path / "runtime_alert.json"
    monkeypatch.setattr(accumulator, "_load_env", lambda: None)
    monkeypatch.setattr(accumulator, "is_trading_session", lambda _day: True)
    monkeypatch.setattr(accumulator, "opening_window_is_valid", lambda _now: True)
    monkeypatch.setattr(accumulator, "_create_client", Client)
    monkeypatch.setattr(accumulator, "_get_account_hash", lambda: "acct")
    monkeypatch.setattr(
        accumulator,
        "_fetch_quote",
        lambda _client: accumulator.QuoteSnapshot(
            "SPCX", accumulator.EXPECTED_CUSIP, "SpaceX", Decimal("100"), Decimal("99"), "now"
        ),
    )
    monkeypatch.setattr(accumulator, "_build_limit_order", lambda _price: {})
    monkeypatch.setattr(
        accumulator,
        "_wait_for_terminal_state",
        lambda *_args: ("CANCELED", {"orderId": "abc123", "status": "CANCELED"}),
    )
    monkeypatch.setattr(accumulator, "LEDGER_PATH", ledger)
    monkeypatch.setattr(accumulator, "LATEST_PATH", latest)
    monkeypatch.setenv("SPCX_AUTOMATION_LIVE_ACK", accumulator.LIVE_ACK_VALUE)
    monkeypatch.setenv("SCHWAB_ACCOUNT_NUMBER", "00000903")
    from ops import runtime_alerts
    monkeypatch.setattr(runtime_alerts, "ALERT_PATH", alert)

    assert accumulator.main(["--execute"]) == 1
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["event"] == "terminal"
    assert payload["status"] == "CANCELED"
    alert_payload = json.loads(alert.read_text(encoding="utf-8"))
    assert alert_payload["active"] is True
    assert alert_payload["event_type"] == "spcx_daily_accumulator_nonfill"


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
    assert schedule.count("<key>Weekday</key>") == 10
    for weekday in range(1, 6):
        assert schedule.count(f"<key>Weekday</key><integer>{weekday}</integer>") == 2
    assert schedule.count("<key>Minute</key><integer>30</integer>") == 5
    assert schedule.count("<key>Minute</key><integer>34</integer>") == 5
    assert "<key>Weekday</key><integer>6</integer>" not in schedule
