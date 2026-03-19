"""
market_finder.py — Deterministically locate the active Polymarket
5-minute BTC Up/Down market and return its token IDs.

Polymarket names these markets with the slug:
    btc-updown-5m-{unix_timestamp}
where unix_timestamp is the end time of the 5-minute window,
always a multiple of 300 seconds.

Finding the current market requires only the current clock time —
no scanning or guessing needed.
"""

import math
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import GAMMA_HOST, MARKET_SLUG_PREFIX, MARKET_CLOSE_BUFFER_SECS
from logger_setup import get_logger

log = get_logger("MarketFinder")


@dataclass
class MarketInfo:
    slug: str
    condition_id: str
    question: str
    end_timestamp: int          # Unix seconds — when this market settles
    up_token_id: str            # CLOB token ID for the "Up" outcome
    down_token_id: str          # CLOB token ID for the "Down" outcome
    up_outcome_index: int       # 0 or 1
    down_outcome_index: int     # 0 or 1


def current_market_end_timestamp() -> int:
    """
    Return the Unix timestamp (seconds) of the END of the current
    5-minute window — always a multiple of 300.

    e.g. if now = 14:07:30, this returns the timestamp for 14:10:00.
    """
    now = int(time.time())
    return ((now // 300) + 1) * 300


def seconds_until_expiry(market: MarketInfo) -> float:
    """How many seconds remain until this market settles."""
    return market.end_timestamp - time.time()


def market_is_tradeable(market: MarketInfo) -> bool:
    """
    Return True if the market is still open with enough time
    to safely place and settle an order.
    """
    remaining = seconds_until_expiry(market)
    return remaining > MARKET_CLOSE_BUFFER_SECS


async def fetch_market_info(
    session: aiohttp.ClientSession,
    end_timestamp: int,
) -> Optional[MarketInfo]:
    """
    Query the Polymarket Gamma API for the 5-minute BTC market
    that ends at `end_timestamp` and return a MarketInfo object.

    Returns None if the market doesn't exist yet or an error occurs.
    """
    slug = f"{MARKET_SLUG_PREFIX}{end_timestamp}"
    url = f"{GAMMA_HOST}/markets?slug={slug}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                log.debug(f"Gamma API returned {resp.status} for slug {slug}")
                return None

            data = await resp.json()

            # Gamma API returns a list; we want the first (and only) match
            if not data:
                log.debug(f"No market found for slug: {slug}")
                return None

            market_data = data[0] if isinstance(data, list) else data

            # Parse token IDs and outcomes
            clob_token_ids: list[str] = market_data.get("clobTokenIds", [])
            outcomes: list[str] = market_data.get("outcomes", [])

            if len(clob_token_ids) < 2 or len(outcomes) < 2:
                log.warning(f"Unexpected market structure for {slug}: {market_data}")
                return None

            # Identify which index corresponds to Up vs Down
            up_idx, down_idx = _find_up_down_indices(outcomes)

            info = MarketInfo(
                slug=slug,
                condition_id=market_data.get("conditionId", ""),
                question=market_data.get("question", slug),
                end_timestamp=end_timestamp,
                up_token_id=clob_token_ids[up_idx],
                down_token_id=clob_token_ids[down_idx],
                up_outcome_index=up_idx,
                down_outcome_index=down_idx,
            )

            log.info(
                f"📋 Market: {info.question} | "
                f"Expires in {seconds_until_expiry(info):.0f}s | "
                f"Up token: ...{info.up_token_id[-6:]}"
            )
            return info

    except aiohttp.ClientError as e:
        log.warning(f"Network error fetching market {slug}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching market {slug}: {e}")
        return None


async def get_current_market(
    session: aiohttp.ClientSession,
    retries: int = 10,
    retry_delay: float = 1.0,
) -> Optional[MarketInfo]:
    """
    Find the currently active 5-minute BTC market, waiting up to
    `retries * retry_delay` seconds for it to appear on the API.

    Polymarket usually creates the next market a few seconds
    before the current one expires.
    """
    import asyncio

    end_ts = current_market_end_timestamp()

    for attempt in range(retries):
        market = await fetch_market_info(session, end_ts)
        if market is not None:
            return market

        if attempt < retries - 1:
            log.debug(f"Market not found yet, retrying in {retry_delay}s... ({attempt+1}/{retries})")
            await asyncio.sleep(retry_delay)

    log.error(f"Could not find market ending at {end_ts} after {retries} attempts")
    return None


async def wait_for_next_market(
    session: aiohttp.ClientSession,
) -> Optional[MarketInfo]:
    """
    Wait until the current 5-minute window expires, then find and
    return the next market.  Called at the end of each trading cycle.
    """
    import asyncio

    next_end_ts = current_market_end_timestamp()
    secs_remaining = next_end_ts - time.time()

    if secs_remaining > 0:
        log.info(f"⏳ Waiting {secs_remaining:.1f}s for current market to expire...")
        await asyncio.sleep(max(0, secs_remaining + 1))  # +1s buffer

    # Now look for the new market
    return await get_current_market(session)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _find_up_down_indices(outcomes: list[str]) -> tuple[int, int]:
    """
    Return (up_index, down_index) by scanning outcome names.
    Falls back to (0, 1) if labels are ambiguous.
    """
    up_keywords = {"up", "higher", "yes", "above"}
    down_keywords = {"down", "lower", "no", "below"}

    up_idx, down_idx = 0, 1  # Default

    for i, outcome in enumerate(outcomes):
        o = outcome.lower().strip()
        if o in up_keywords:
            up_idx = i
        elif o in down_keywords:
            down_idx = i

    return up_idx, down_idx
