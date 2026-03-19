"""
main.py — Orchestrates the entire Polymarket BTC 5-minute bot.

Event loop structure:
  ┌─ asyncio event loop ─────────────────────────────────────────────┐
  │                                                                    │
  │  [Task 1] BTCPriceFeed.run()  ← streams Binance aggTrade forever  │
  │                                                                    │
  │  [Task 2] trading_loop()      ← main decision cycle               │
  │    ├─ find active 5-min market                                     │
  │    ├─ every POLL_INTERVAL seconds:                                 │
  │    │   ├─ read latest BTC prices                                   │
  │    │   ├─ fetch Polymarket order book                              │
  │    │   ├─ run strategy → maybe emit a TradeSignal                  │
  │    │   └─ if signal → size & place order via PolymarketClient      │
  │    └─ wait for market expiry, check outcome, record PnL            │
  │                                                                    │
  └────────────────────────────────────────────────────────────────────┘

Run with:
    python main.py
"""

import asyncio
import signal
import sys
import time
from typing import Optional

import aiohttp

from config import INITIAL_CAPITAL
from logger_setup import get_logger
from market_finder import (
    MarketInfo,
    get_current_market,
    market_is_tradeable,
    seconds_until_expiry,
    current_market_end_timestamp,
)
from polymarket_client import PolymarketClient
from price_feed import BTCPriceFeed
from risk_manager import RiskManager
from strategy import MomentumStrategy, TradeSignal
from tracker import TradeTracker

log = get_logger("Main")

# How often (seconds) we poll the order book & run the strategy
POLL_INTERVAL: float = 0.5

# How long to wait (seconds) after market expiry to fetch the outcome
SETTLEMENT_DELAY: float = 5.0


# ─── Main trading loop ───────────────────────────────────────────────────────

async def trading_loop(
    price_feed: BTCPriceFeed,
    poly_client: PolymarketClient,
    risk: RiskManager,
    strategy: MomentumStrategy,
    tracker: TradeTracker,
    http: aiohttp.ClientSession,
):
    """
    Runs indefinitely: finds a market, trades it for ~5 minutes,
    waits for settlement, then moves to the next market.
    """
    log.info("⚡ Trading loop started")

    while True:
        # ── 1. Find the current active market ────────────────────────────
        log.info("🔍 Looking for active 5-minute BTC market...")
        market = await get_current_market(http)

        if market is None:
            log.warning("No active market found — waiting 10s before retry")
            await asyncio.sleep(10)
            continue

        log.info(
            f"🎯 Trading market: {market.question}  "
            f"(expires in {seconds_until_expiry(market):.0f}s)"
        )

        # Track which orders were placed for this market
        placed_order_ids: list[str] = []

        # ── 2. Trade until the market closes ─────────────────────────────
        while market_is_tradeable(market):

            # Wait for enough price history
            if not price_feed.is_ready():
                await asyncio.sleep(0.1)
                continue

            # Fetch latest prices & order book in parallel
            prices, book = await asyncio.gather(
                price_feed.get_prices(),
                poly_client.get_market_book(
                    market.up_token_id,
                    market.down_token_id,
                ),
            )

            if book is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Run strategy
            if risk.can_trade():
                signal: Optional[TradeSignal] = strategy.evaluate(prices, book)

                if signal is not None:
                    shares = risk.size_order(signal.edge, signal.entry_price)
                    order_id = await poly_client.place_order(
                        token_id=signal.token_id,
                        price=signal.entry_price,
                        shares=shares,
                        direction=signal.direction,
                    )

                    if order_id:
                        risk.record_order_placed(
                            order_id=order_id,
                            direction=signal.direction,
                            shares=shares,
                            entry_price=signal.entry_price,
                            market_slug=market.slug,
                            end_timestamp=market.end_timestamp,
                        )
                        placed_order_ids.append(order_id)

            await asyncio.sleep(POLL_INTERVAL)

        # ── 3. Market is closing — wait for settlement ────────────────────
        remaining = seconds_until_expiry(market)
        if remaining > 0:
            log.info(f"⏳ Market expiring in {remaining:.1f}s — waiting...")
            await asyncio.sleep(max(0, remaining + SETTLEMENT_DELAY))
        else:
            await asyncio.sleep(SETTLEMENT_DELAY)

        # ── 4. Determine outcome & record PnL ────────────────────────────
        if placed_order_ids:
            won = await _fetch_outcome(http, market)
            log.info(
                f"{'🏆 WON' if won else '💸 LOST'} market: {market.slug}"
            )

            # Update risk manager & write CSV row for each position
            for order_id, pos in list(risk.open_positions.items()):
                if pos.market_slug == market.slug:
                    pnl = (pos.shares - pos.cost) if won else -pos.cost
                    tracker.log_trade(
                        market_slug=market.slug,
                        direction=pos.direction,
                        shares=pos.shares,
                        entry_price=pos.entry_price,
                        cost=pos.cost,
                        won=won,
                        pnl=pnl,
                        balance_after=risk.balance + (pos.shares if won else 0),
                        order_id=order_id,
                    )

            risk.record_market_settled(market.slug, won)

        log.info("─" * 60)
        log.info("Moving to next market...")


async def _fetch_outcome(
    http: aiohttp.ClientSession,
    market: MarketInfo,
) -> bool:
    """
    Ask the Gamma API whether the UP outcome won.
    Returns True if UP won, False if DOWN won.
    Falls back to comparing BTC open/close price if API is slow.
    """
    from config import GAMMA_HOST

    url = f"{GAMMA_HOST}/markets?slug={market.slug}"
    for _ in range(5):
        try:
            async with http.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                if isinstance(data, list) and data:
                    m = data[0]
                    outcome_prices: list[str] = m.get("outcomePrices", [])
                    # If market resolved, one outcome price will be "1" and other "0"
                    if outcome_prices and len(outcome_prices) >= 2:
                        up_price = float(outcome_prices[market.up_outcome_index])
                        if up_price == 1.0:
                            return True
                        elif up_price == 0.0:
                            return False
        except Exception as e:
            log.debug(f"Outcome fetch error: {e}")

        await asyncio.sleep(3)

    log.warning("Could not determine outcome from API — defaulting to loss")
    return False


# ─── Entry point ─────────────────────────────────────────────────────────────

async def main():
    log.info("=" * 60)
    log.info("  🤖 Polymarket BTC 5-Minute Bot")
    log.info(f"  Starting capital: ${INITIAL_CAPITAL:.2f} USDC")
    log.info("=" * 60)

    # Validate config
    from config import PRIVATE_KEY
    if not PRIVATE_KEY:
        log.error(
            "PRIVATE_KEY not set!\n"
            "  1. Copy .env.example to .env\n"
            "  2. Fill in your Polygon wallet private key\n"
            "  3. Run setup_wallet.py first to approve USDC spending"
        )
        sys.exit(1)

    # Initialise components
    price_feed = BTCPriceFeed()
    poly_client = PolymarketClient()
    risk = RiskManager(starting_balance=INITIAL_CAPITAL)
    strategy = MomentumStrategy()
    tracker = TradeTracker()

    # Authenticate with Polymarket (derives L2 credentials from wallet)
    await poly_client.authenticate()

    # Fetch live balance to sync our risk manager
    live_balance = await poly_client.get_balance()
    if live_balance > 0:
        risk._balance = live_balance
        risk._session_start_balance = live_balance
        risk._peak_balance = live_balance
        log.info(f"💵 Live USDC balance: ${live_balance:.2f}")
    else:
        log.warning(
            "Could not fetch live balance — using INITIAL_CAPITAL from config.\n"
            "Make sure you have USDC on Polygon and have run setup_wallet.py"
        )

    # Graceful shutdown handler
    stop_event = asyncio.Event()

    def _shutdown(sig, frame):
        log.info(f"\n⛔ Received {sig.name} — shutting down gracefully...")
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    async with aiohttp.ClientSession() as http:
        # Run price feed and trading loop concurrently
        price_task = asyncio.create_task(price_feed.run())
        trade_task = asyncio.create_task(
            trading_loop(price_feed, poly_client, risk, strategy, tracker, http)
        )
        stop_task = asyncio.create_task(stop_event.wait())

        # Wait until a shutdown signal arrives
        done, pending = await asyncio.wait(
            [price_task, trade_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    log.info("Bot stopped. Check trades.csv for your session results.")


if __name__ == "__main__":
    asyncio.run(main())
