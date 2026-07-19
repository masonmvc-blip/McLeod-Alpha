from __future__ import annotations

import asyncio
import copy
import threading
from datetime import datetime
from typing import Optional

from schwab.streaming import StreamClient


def build_equity_quote_payload(symbol: str, entry: dict) -> dict:
    stream_symbol = entry.get("key") or entry.get("SYMBOL") or symbol
    quote = {
        "bidPrice": entry.get("BID_PRICE"),
        "askPrice": entry.get("ASK_PRICE"),
        "lastPrice": entry.get("LAST_PRICE"),
        "mark": entry.get("MARK"),
        "closePrice": entry.get("CLOSE_PRICE"),
        "totalVolume": entry.get("TOTAL_VOLUME"),
        "quoteTime": entry.get("QUOTE_TIME_MILLIS"),
        "tradeTime": entry.get("TRADE_TIME_MILLIS"),
    }
    regular = {
        "regularMarketLastPrice": entry.get("REGULAR_MARKET_LAST_PRICE"),
        "regularMarketTradeTime": entry.get("REGULAR_MARKET_TRADE_MILLIS"),
    }
    return {
        stream_symbol: {
            "quote": quote,
            "regular": regular,
        }
    }


class SchwabEquityQuoteStream:
    def __init__(self, client, symbol: str):
        self.client = client
        self.symbol = symbol
        self._stream: Optional[StreamClient] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._latest_payload = None
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._started = threading.Event()
        self._failed = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._failed = False
        self._thread = threading.Thread(target=self._run_thread, name="schwab-equity-stream", daemon=True)
        self._thread.start()
        self._started.wait(timeout=5)

    def stop(self):
        self._stop_requested.set()
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self._schedule_shutdown)

    def get_latest_quote_payload(self):
        with self._lock:
            return copy.deepcopy(self._latest_payload)

    def is_healthy(self) -> bool:
        return (not self._failed) and self._thread is not None and self._thread.is_alive()

    def _run_thread(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._stream_main())
        except Exception:
            self._failed = True
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
            except Exception:
                pass
            self._loop.close()

    async def _stream_main(self):
        self._stream = StreamClient(self.client, enforce_enums=False)
        self._stream.add_level_one_equity_handler(self._handle_equity_message)
        await self._stream.login()
        await self._stream.level_one_equity_subs(
            [self.symbol],
            fields=[
                StreamClient.LevelOneEquityFields.SYMBOL,
                StreamClient.LevelOneEquityFields.BID_PRICE,
                StreamClient.LevelOneEquityFields.ASK_PRICE,
                StreamClient.LevelOneEquityFields.LAST_PRICE,
                StreamClient.LevelOneEquityFields.MARK,
                StreamClient.LevelOneEquityFields.CLOSE_PRICE,
                StreamClient.LevelOneEquityFields.TOTAL_VOLUME,
                StreamClient.LevelOneEquityFields.QUOTE_TIME_MILLIS,
                StreamClient.LevelOneEquityFields.TRADE_TIME_MILLIS,
                StreamClient.LevelOneEquityFields.REGULAR_MARKET_LAST_PRICE,
                StreamClient.LevelOneEquityFields.REGULAR_MARKET_TRADE_MILLIS,
            ],
        )
        self._started.set()

        while not self._stop_requested.is_set():
            await self._stream.handle_message()

    def _handle_equity_message(self, msg):
        for entry in msg.get("content", []):
            payload = build_equity_quote_payload(self.symbol, entry)
            with self._lock:
                self._latest_payload = payload

    def _schedule_shutdown(self):
        if self._loop is None:
            return
        asyncio.create_task(self._shutdown_stream())

    async def _shutdown_stream(self):
        try:
            if self._stream is not None:
                await self._stream.logout()
        except Exception:
            pass