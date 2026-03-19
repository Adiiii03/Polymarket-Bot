"""
price_feed.py — Real-time Bitcoin spot price via Binance aggTrade WebSocket.

Maintains a thread-safe rolling price history that other modules read from.
No API key required — Binance public WebSocket is completely free.
"""

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import websockets

from config import BINANCE_WS_URL, PRICE_HISTORY_LEN
from logger_setup import get_logger

log = get_logger("PriceFeed")


@dataclass
class PriceTick:
    price: float
    timestamp: float  # Unix epoch seconds


class BTCPriceFeed:
    """
    Connects to Binance's aggTrade stream for BTCUSDT and maintains
    a rolling deque of recent price ticks.
    """

    def __init__(self):
        self._history: deque[PriceTick] = deque(maxlen=PRICE_HISTORY_LEN)
        self._lock = asyncio.Lock()
        self._running = False
        self._last_price: Optional[float] = None

    # ─── Public API ──────────────────────────────────────────────────────────

    @property
    def last_price(self) -> Optional[float]:
        return self._last_price

    async def get_prices(self) -> list[float]:
        """Return a copy of the price history (oldest → newest)."""
        async with self._lock:
            return [t.price for t in self._history]

    async def get_ticks(self) -> list[PriceTick]:
        """Return full tick history including timestamps."""
        async with self._lock:
            return list(self._history)

    def is_ready(self) -> bool:
        """True once we have enough ticks to run the strategy."""
        return len(self._history) >= 60

    # ─── WebSocket Loop ──────────────────────────────────────────────────────

    async def run(self):
        """Connect and stream price data indefinitely, reconnecting on errors."""
        self._running = True
        log.info(f"Connecting to Binance WebSocket: {BINANCE_WS_URL}")

        while self._running:
            try:
                async with websockets.connect(
                    BINANCE_WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    log.info("✅ Binance WebSocket connected")
                    async for raw in ws:
                        msg = json.loads(raw)
                        await self._handle_message(msg)

            except (websockets.ConnectionClosed, OSError) as e:
                log.warning(f"Binance WS disconnected: {e} — reconnecting in 2s")
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Unexpected error in price feed: {e} — reconnecting in 5s")
                await asyncio.sleep(5)

        log.info("Price feed stopped.")

    def stop(self):
        self._running = False

    # ─── Internal ────────────────────────────────────────────────────────────

    async def _handle_message(self, msg: dict):
        """Parse an aggTrade message and store the price."""
        try:
            price = float(msg["p"])   # "p" = price in aggTrade stream
            ts = msg["T"] / 1000.0   # "T" = trade time (ms → s)

            tick = PriceTick(price=price, timestamp=ts)

            async with self._lock:
                self._history.append(tick)
                self._last_price = price

        except (KeyError, ValueError) as e:
            log.debug(f"Skipping malformed message: {e}")
