from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtesting.alpaca_full_backtest import (
    AlpacaClient,
    _choose_historical_contract_from_contracts,
    _contract_type_for_selection,
)


def _contract(symbol: str, ctype: str | None, strike: str, expiration: str, status: str = "inactive", oi: str = "10"):
    out = {
        "symbol": symbol,
        "strike_price": strike,
        "expiration_date": expiration,
        "status": status,
        "open_interest": oi,
    }
    if ctype is not None:
        out["type"] = ctype
    return out


def test_expired_historical_contracts_can_be_selected_for_past_dates():
    contracts = [
        _contract("SPY260724C00630000", "call", "630", "2026-07-24", status="inactive", oi="100"),
        _contract("SPY260724C00635000", "call", "635", "2026-07-24", status="inactive", oi="90"),
    ]
    selected, diag = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="CALL",
        spy_entry=631.2,
        target_expiration=date(2026, 7, 24),
    )
    assert selected is not None
    assert selected["symbol"] == "SPY260724C00630000"
    assert diag["contract_status"] == "inactive"


def test_inactive_status_does_not_invalidate_historical_contract():
    contracts = [
        _contract("SPY260724P00610000", "put", "610", "2026-07-24", status="inactive", oi="250"),
    ]
    selected, _ = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="PUT",
        spy_entry=611.0,
        target_expiration=date(2026, 7, 24),
    )
    assert selected is not None
    assert selected["status"] == "inactive"


def test_occ_symbol_mapping_when_type_missing():
    assert _contract_type_for_selection({"symbol": "SPY260724C00630000"}) == "call"
    assert _contract_type_for_selection({"symbol": "SPY260724P00630000"}) == "put"


def test_call_put_mapping_is_correct():
    contracts = [
        _contract("SPY260724C00630000", "call", "630", "2026-07-24", oi="1"),
        _contract("SPY260724P00630000", "put", "630", "2026-07-24", oi="999"),
    ]
    selected_call, _ = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="CALL",
        spy_entry=630,
        target_expiration=date(2026, 7, 24),
    )
    selected_put, _ = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="PUT",
        spy_entry=630,
        target_expiration=date(2026, 7, 24),
    )
    assert selected_call is not None and selected_call["symbol"].endswith("C00630000")
    assert selected_put is not None and selected_put["symbol"].endswith("P00630000")


def test_missing_delta_does_not_reject_all_candidates():
    contracts = [
        _contract("SPY260724C00625000", "call", "625", "2026-07-24", oi="3"),
        _contract("SPY260724C00630000", "call", "630", "2026-07-24", oi="5"),
    ]
    selected, diag = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="CALL",
        spy_entry=629.5,
        target_expiration=date(2026, 7, 24),
    )
    assert selected is not None
    assert diag["rejection_reason"] == ""


def test_no_future_contract_window_regression_selects_target_or_later_only():
    contracts = [
        _contract("SPY260717C00630000", "call", "630", "2026-07-17", oi="200"),
        _contract("SPY260724C00630000", "call", "630", "2026-07-24", oi="100"),
    ]
    selected, _ = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="CALL",
        spy_entry=630,
        target_expiration=date(2026, 7, 24),
    )
    assert selected is not None
    assert selected["expiration_date"] >= "2026-07-24"


def test_selection_is_deterministic():
    contracts = [
        _contract("SPY260724P00630000", "put", "630", "2026-07-24", oi="100"),
        _contract("SPY260724P00635000", "put", "635", "2026-07-24", oi="100"),
    ]
    first, _ = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="PUT",
        spy_entry=632,
        target_expiration=date(2026, 7, 24),
    )
    second, _ = _choose_historical_contract_from_contracts(
        contracts=contracts,
        direction="PUT",
        spy_entry=632,
        target_expiration=date(2026, 7, 24),
    )
    assert first is not None and second is not None
    assert first["symbol"] == second["symbol"]


def test_historical_trade_data_download_parses_rows(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {
                "trades": {
                    "SPY260724C00630000": [
                        {"t": "2026-07-13T13:30:00Z", "p": 1.23},
                        {"t": "2026-07-13T13:31:00Z", "p": 1.25},
                    ]
                }
            }

    def _fake_request(method, url, headers=None, params=None, timeout=None):
        return _Resp()

    monkeypatch.setattr("requests.request", _fake_request)
    client = AlpacaClient("k", "s")
    df = client.download_trades("SPY260724C00630000", date(2026, 7, 13))
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "timestamp" in df.columns and "price" in df.columns


def test_production_files_untouched_by_historical_selector_module():
    module_text = Path("backtesting/alpaca_full_backtest.py").read_text(encoding="utf-8")
    assert "execution.live_engine" not in module_text
    assert "execution.paper_engine" not in module_text
