from execution import live_engine


def test_stop_verification_returns_unknown_when_broker_query_fails(monkeypatch):
    class FailingClient:
        def get_orders_for_account(self, _account_hash):
            raise RuntimeError("Schwab rate-limit cooldown active")

    monkeypatch.setattr(live_engine, "_schwab_client", FailingClient())
    monkeypatch.setattr(live_engine, "_schwab_account_hash", "account-hash")

    assert live_engine._has_active_protective_stop_order("SPY   260807P00740000") is None