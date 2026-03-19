"""
polymarket_client.py — Wrapper around py-clob-client for order book
reading and order placement on Polymarket.

Handles:
  • Authentication (L2 API credentials derived from wallet)
  • Order book polling (best bid/ask for Up and Down tokens)
  • Order creation and posting
  • Order cancellation
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from config import (
    CLOB_HOST,
    CHAIN_ID,
    PRIVATE_KEY,
    WALLET_ADDRESS,
    MIN_CONTRACT_PRICE,
    MAX_CONTRACT_PRICE,
)
from logger_setup import get_logger

log = get_logger("PolyClient")


@dataclass
class OrderBook:
    """Best bid/ask for a single outcome token."""
    token_id: str
    best_bid: float     # Highest price someone will BUY at
    best_ask: float     # Lowest price someone will SELL at
    mid: float          # Mid-market price


@dataclass
class MarketBook:
    """Combined order books for both Up and Down tokens."""
    up: OrderBook
    down: OrderBook


class PolymarketClient:
    """
    Thin async wrapper around the synchronous py-clob-client.

    All blocking calls are run in an executor so they don't block the
    asyncio event loop.
    """

    def __init__(self):
        if not PRIVATE_KEY:
            raise ValueError(
                "PRIVATE_KEY not set in .env — see .env.example for instructions"
            )

        self._client = ClobClient(
            CLOB_HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=1,   # EOA (regular wallet) signature
            funder=WALLET_ADDRESS if WALLET_ADDRESS else None,
        )
        self._creds_set = False
        self._loop = asyncio.get_event_loop()

    # ─── Setup ───────────────────────────────────────────────────────────────

    async def authenticate(self):
        """
        Derive L2 API credentials from your wallet key.
        Must be called once before placing any orders.
        This is a one-time derivation — no gas, no transaction.
        """
        log.info("Deriving L2 API credentials from wallet...")
        try:
            creds = await self._run(self._client.create_or_derive_api_creds)
            self._client.set_api_creds(creds)
            self._creds_set = True
            log.info("✅ Polymarket authenticated successfully")
        except Exception as e:
            log.error(f"Authentication failed: {e}")
            raise

    # ─── Order Book ──────────────────────────────────────────────────────────

    async def get_market_book(
        self,
        up_token_id: str,
        down_token_id: str,
    ) -> Optional[MarketBook]:
        """
        Fetch best bid/ask for both the Up and Down tokens.
        Returns None on error so callers can skip this cycle.
        """
        try:
            up_book, down_book = await asyncio.gather(
                self._get_order_book(up_token_id),
                self._get_order_book(down_token_id),
            )
            if up_book is None or down_book is None:
                return None
            return MarketBook(up=up_book, down=down_book)
        except Exception as e:
            log.warning(f"Failed to fetch market book: {e}")
            return None

    async def _get_order_book(self, token_id: str) -> Optional[OrderBook]:
        """Fetch the order book for a single token and extract best bid/ask."""
        try:
            book = await self._run(self._client.get_order_book, token_id)

            bids = sorted(
                [float(b["price"]) for b in (book.bids or [])],
                reverse=True,
            )
            asks = sorted(
                [float(a["price"]) for a in (book.asks or [])],
            )

            best_bid = bids[0] if bids else 0.0
            best_ask = asks[0] if asks else 1.0
            mid = (best_bid + best_ask) / 2

            return OrderBook(
                token_id=token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                mid=mid,
            )
        except Exception as e:
            log.debug(f"Order book error for {token_id[-8:]}: {e}")
            return None

    # ─── Order Placement ─────────────────────────────────────────────────────

    async def place_order(
        self,
        token_id: str,
        price: float,
        shares: float,
        direction: str,   # "UP" or "DOWN" — for logging only
    ) -> Optional[str]:
        """
        Place a GTC limit BUY order on the specified outcome token.

        Returns the order ID on success, None on failure.
        Price is the per-share cost (0.01–0.99 USDC).
        Shares is the number of outcome tokens to purchase.
        """
        if not self._creds_set:
            log.error("Cannot place order — not authenticated")
            return None

        # Final safety checks
        price = round(max(MIN_CONTRACT_PRICE, min(MAX_CONTRACT_PRICE, price)), 4)
        shares = round(max(1.0, shares), 1)

        log.info(
            f"🛒 Placing {direction} order | "
            f"{shares:.0f} shares @ ${price:.4f} = ${price * shares:.2f} USDC"
        )

        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=shares,
                side=BUY,
            )
            signed_order = await self._run(self._client.create_order, order_args)
            response = await self._run(
                self._client.post_order, signed_order, OrderType.GTC
            )

            order_id = response.get("orderID") or response.get("id", "unknown")
            log.info(f"✅ Order placed: {order_id}")
            return order_id

        except Exception as e:
            log.error(f"Order placement failed: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True on success."""
        try:
            await self._run(self._client.cancel, order_id)
            log.info(f"❌ Cancelled order {order_id}")
            return True
        except Exception as e:
            log.warning(f"Could not cancel order {order_id}: {e}")
            return False

    async def get_balance(self) -> float:
        """Return current USDC balance available for trading."""
        try:
            balance_data = await self._run(self._client.get_balance_allowance)
            # balance_allowance returns {"asset_type": ..., "balance": ..., "allowance": ...}
            return float(balance_data.get("balance", 0))
        except Exception as e:
            log.warning(f"Could not fetch balance: {e}")
            return 0.0

    # ─── Internals ───────────────────────────────────────────────────────────

    async def _run(self, fn, *args, **kwargs):
        """Run a synchronous py-clob-client call in the thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
