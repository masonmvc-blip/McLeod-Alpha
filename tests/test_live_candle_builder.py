from datetime import datetime
from zoneinfo import ZoneInfo

from strategy.live_candle_builder import LiveMinuteCandleBuilder


UTC = ZoneInfo("UTC")


def _payload(symbol, price, total_volume, when):
    ms = int(when.timestamp() * 1000)
    return {
        symbol: {
            "quote": {
                "mark": price,
                "lastPrice": price,
                "quoteTime": ms,
                "tradeTime": ms,
                "totalVolume": total_volume,
            },
            "regular": {
                "regularMarketLastPrice": price,
                "regularMarketTradeTime": ms,
            },
        }
    }


def test_live_candle_builder_updates_current_minute_ohlcv():
    builder = LiveMinuteCandleBuilder("SPY")
    builder.update_from_quote_payload(_payload("SPY", 100.0, 1000, datetime(2026, 7, 15, 14, 30, 1, tzinfo=UTC)))
    builder.update_from_quote_payload(_payload("SPY", 101.0, 1012, datetime(2026, 7, 15, 14, 30, 30, tzinfo=UTC)))
    builder.update_from_quote_payload(_payload("SPY", 99.5, 1018, datetime(2026, 7, 15, 14, 30, 45, tzinfo=UTC)))

    df = builder.as_dataframe()

    assert len(df) == 1
    row = df.iloc[0]
    assert float(row["open"]) == 100.0
    assert float(row["high"]) == 101.0
    assert float(row["low"]) == 99.5
    assert float(row["close"]) == 99.5
    assert float(row["volume"]) == 18.0


def test_live_candle_builder_preserves_recent_closed_minute_across_rollover():
    builder = LiveMinuteCandleBuilder("SPY", max_candles=3)
    builder.update_from_quote_payload(_payload("SPY", 100.0, 1000, datetime(2026, 7, 15, 14, 30, 58, tzinfo=UTC)))
    builder.update_from_quote_payload(_payload("SPY", 100.5, 1010, datetime(2026, 7, 15, 14, 31, 2, tzinfo=UTC)))

    df = builder.as_dataframe()

    assert len(df) == 2
    assert df.iloc[0]["datetime"] == datetime(2026, 7, 15, 14, 30, tzinfo=UTC)
    assert df.iloc[1]["datetime"] == datetime(2026, 7, 15, 14, 31, tzinfo=UTC)


def test_live_candle_builder_merge_overrides_history_duplicate():
    builder = LiveMinuteCandleBuilder("SPY")
    builder.update_from_quote_payload(_payload("SPY", 100.5, 1010, datetime(2026, 7, 15, 14, 31, 2, tzinfo=UTC)))

    import pandas as pd

    history = pd.DataFrame(
        [
            {"datetime": datetime(2026, 7, 15, 14, 30), "open": 99.0, "high": 100.0, "low": 98.5, "close": 99.5, "volume": 500},
            {"datetime": datetime(2026, 7, 15, 14, 31), "open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 100},
        ]
    )

    merged = builder.merge_with_history(history)

    assert len(merged) == 2
    assert float(merged.iloc[-1]["close"]) == 100.5


def test_live_candle_builder_prefers_freshest_timestamp_field():
    builder = LiveMinuteCandleBuilder("SPY")
    stale_quote_ms = int(datetime(2026, 7, 15, 14, 25, 0, tzinfo=UTC).timestamp() * 1000)
    fresh_trade_ms = int(datetime(2026, 7, 15, 14, 30, 20, tzinfo=UTC).timestamp() * 1000)

    payload = {
        "SPY": {
            "quote": {
                "mark": 100.0,
                "quoteTime": stale_quote_ms,
                "tradeTime": fresh_trade_ms,
                "totalVolume": 1000,
            },
            "regular": {
                "regularMarketLastPrice": 100.0,
                "regularMarketTradeTime": fresh_trade_ms,
            },
        }
    }

    snapshot = builder.update_from_quote_payload(payload)

    assert snapshot.quote_time_utc == datetime(2026, 7, 15, 14, 30, 20, tzinfo=UTC)
    df = builder.as_dataframe()
    assert len(df) == 1
    assert df.iloc[0]["datetime"] == datetime(2026, 7, 15, 14, 30, tzinfo=UTC)