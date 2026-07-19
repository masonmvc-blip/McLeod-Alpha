from execution.equity_stream import build_equity_quote_payload


def test_build_equity_quote_payload_maps_stream_fields():
    payload = build_equity_quote_payload(
        "SPY",
        {
            "key": "SPY",
            "BID_PRICE": 750.81,
            "ASK_PRICE": 750.84,
            "LAST_PRICE": 750.82,
            "MARK": 750.82,
            "CLOSE_PRICE": 751.83,
            "TOTAL_VOLUME": 17127040,
            "QUOTE_TIME_MILLIS": 1784133104282,
            "TRADE_TIME_MILLIS": 1784133103575,
            "REGULAR_MARKET_LAST_PRICE": 750.82,
            "REGULAR_MARKET_TRADE_MILLIS": 1784133103575,
        },
    )

    quote = payload["SPY"]["quote"]
    regular = payload["SPY"]["regular"]

    assert quote["bidPrice"] == 750.81
    assert quote["askPrice"] == 750.84
    assert quote["lastPrice"] == 750.82
    assert quote["mark"] == 750.82
    assert quote["totalVolume"] == 17127040
    assert regular["regularMarketLastPrice"] == 750.82
    assert regular["regularMarketTradeTime"] == 1784133103575


def test_build_equity_quote_payload_defaults_symbol_when_missing_key():
    payload = build_equity_quote_payload(
        "SPY",
        {
            "LAST_PRICE": 750.82,
            "MARK": 750.82,
        },
    )

    assert "SPY" in payload