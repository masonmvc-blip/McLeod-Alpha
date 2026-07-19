from datetime import datetime, timedelta

from execution.option_quote_cache import ActiveOptionQuoteCache


def test_option_quote_cache_parses_quote_fields():
    def fetch(symbol):
        return {
            symbol: {
                "quote": {
                    "bidPrice": 1.23,
                    "askPrice": 1.27,
                    "mark": 1.25,
                    "lastPrice": 1.24,
                }
            }
        }

    cache = ActiveOptionQuoteCache(fetch_func=fetch, ttl_seconds=1.0)
    snap = cache.get("SPY   260724C00755000", now=datetime(2026, 7, 15, 10, 0, 0))

    assert snap.symbol == "SPY   260724C00755000"
    assert snap.bid == 1.23
    assert snap.ask == 1.27
    assert snap.mark == 1.25
    assert snap.last == 1.24


def test_option_quote_cache_reuses_snapshot_within_ttl():
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return {symbol: {"quote": {"bidPrice": 1.0, "mark": 1.1, "lastPrice": 1.05}}}

    cache = ActiveOptionQuoteCache(fetch_func=fetch, ttl_seconds=1.0)
    now = datetime(2026, 7, 15, 10, 0, 0)

    cache.get("SPY   260724C00755000", now=now)
    cache.get("SPY   260724C00755000", now=now + timedelta(milliseconds=500))

    assert calls == ["SPY   260724C00755000"]


def test_option_quote_cache_refreshes_after_ttl_or_symbol_change():
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return {symbol: {"quote": {"bidPrice": 2.0, "mark": 2.1, "lastPrice": 2.05}}}

    cache = ActiveOptionQuoteCache(fetch_func=fetch, ttl_seconds=1.0)
    now = datetime(2026, 7, 15, 10, 0, 0)

    cache.get("SPY   260724C00755000", now=now)
    cache.get("SPY   260724C00755000", now=now + timedelta(seconds=2))
    cache.get("SPY   260724P00752000", now=now + timedelta(seconds=2, milliseconds=1))

    assert calls == [
        "SPY   260724C00755000",
        "SPY   260724C00755000",
        "SPY   260724P00752000",
    ]