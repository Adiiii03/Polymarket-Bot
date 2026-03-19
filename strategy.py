"""
strategy.py — The core trading logic: momentum-based gap detection.

HOW THE STRATEGY WORKS
──────────────────────
Polymarket's 5-minute BTC Up/Down contract is a binary option:
  • You pay X cents per share.
  • If BTC is higher at expiry you collect $1 per share (profit: 1 - X).
  • If BTC is lower you lose X.

The "fair" price for the Up contract is the TRUE probability that BTC will
be higher in the next ~5 minutes.  In a perfectly efficient market that
would always be exactly 50¢ — but markets lag.

When Bitcoin moves quickly, the Polymarket order book doesn't reprice
instantly.  For a few seconds the Up contract might still sit at 48¢ even
though strong upward momentum makes ~55¢ the fair value.  That 7¢ gap is
our edge.  We buy before the market corrects, then sell (or let it expire)
once it does.

MOMENTUM MODEL
──────────────
  1. Pull the last N price ticks (Binance aggTrade, ~10/second).
  2. Compute weighted multi-timeframe momentum.
  3. Apply tanh() to bound the output in (-1, +1).
  4. Convert to a fair probability in [MIN_FAIR_PROB, MAX_FAIR_PROB].
  5. Compare fair probability to the actual market ask price.
  6. If edge > MIN_EDGE → signal a trade.
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np

from config import (
    MIN_EDGE,
    MOMENTUM_SENSITIVITY,
    MAX_FAIR_PROB,
    MIN_FAIR_PROB,
    SHORT_WINDOW,
    MEDIUM_WINDOW,
    LONG_WINDOW,
    MIN_CONTRACT_PRICE,
    MAX_CONTRACT_PRICE,
)
from logger_setup import get_logger
from polymarket_client import MarketBook

log = get_logger("Strategy")


@dataclass
class TradeSignal:
    direction: str       # "UP" or "DOWN"
    edge: float          # Our estimated edge (0 → 1)
    fair_prob: float     # Our fair probability for UP
    entry_price: float   # The ask price we intend to hit
    token_id: str        # Which token to buy


class MomentumStrategy:
    """
    Detects gaps between Polymarket contract prices and short-term
    BTC price momentum, and emits trade signals.
    """

    def __init__(self):
        self._signal_count = 0

    def evaluate(
        self,
        prices: list[float],
        book: MarketBook,
    ) -> Optional[TradeSignal]:
        """
        Given recent BTC prices and the current order book, return a
        TradeSignal if an edge exists, otherwise return None.
        """
        if len(prices) < SHORT_WINDOW:
            log.debug(f"Not enough price history yet ({len(prices)}/{SHORT_WINDOW} ticks)")
            return None

        arr = np.array(prices, dtype=float)

        # ── 1. Compute momentum at three timeframes ───────────────────────
        short_return  = _pct_change(arr, SHORT_WINDOW)
        medium_return = _pct_change(arr, min(MEDIUM_WINDOW, len(arr)))
        long_return   = _pct_change(arr, min(LONG_WINDOW,  len(arr)))

        # Weighted combination (most recent is most informative)
        weighted_momentum = (
            0.60 * short_return
            + 0.30 * medium_return
            + 0.10 * long_return
        )

        # ── 2. Convert momentum to a fair probability ─────────────────────
        # tanh maps any real to (-1, 1); scale by 0.5 so adjustment ≤ ±0.50
        adjustment = np.tanh(weighted_momentum * MOMENTUM_SENSITIVITY) * 0.50
        fair_prob_up = float(np.clip(0.50 + adjustment, MIN_FAIR_PROB, MAX_FAIR_PROB))
        fair_prob_down = 1.0 - fair_prob_up

        # ── 3. Get best ask prices (what we'd actually pay) ───────────────
        ask_up   = book.up.best_ask
        ask_down = book.down.best_ask

        # Skip if the market is illiquid or at extreme prices
        if not _price_ok(ask_up) or not _price_ok(ask_down):
            return None

        # ── 4. Calculate edge for each direction ─────────────────────────
        edge_up   = fair_prob_up   - ask_up
        edge_down = fair_prob_down - ask_down

        log.debug(
            f"BTC momentum={weighted_momentum*100:.4f}%  "
            f"fair_up={fair_prob_up:.3f}  "
            f"ask_up={ask_up:.3f}  edge_up={edge_up:.3f}  "
            f"ask_down={ask_down:.3f}  edge_down={edge_down:.3f}"
        )

        # ── 5. Emit signal if edge exceeds threshold ──────────────────────
        best_edge = max(edge_up, edge_down)

        if best_edge < MIN_EDGE:
            return None  # No exploitable gap right now

        if edge_up >= edge_down:
            self._signal_count += 1
            log.info(
                f"📈 UP signal #{self._signal_count}  "
                f"edge={edge_up:.3f}  fair={fair_prob_up:.3f}  ask={ask_up:.3f}"
            )
            return TradeSignal(
                direction="UP",
                edge=edge_up,
                fair_prob=fair_prob_up,
                entry_price=ask_up,
                token_id=book.up.token_id,
            )
        else:
            self._signal_count += 1
            log.info(
                f"📉 DOWN signal #{self._signal_count}  "
                f"edge={edge_down:.3f}  fair={fair_prob_down:.3f}  ask={ask_down:.3f}"
            )
            return TradeSignal(
                direction="DOWN",
                edge=edge_down,
                fair_prob=fair_prob_down,
                entry_price=ask_down,
                token_id=book.down.token_id,
            )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _pct_change(arr: np.ndarray, window: int) -> float:
    """
    Percentage change over the last `window` ticks.
    Returns 0 if there aren't enough samples.
    """
    if len(arr) < window + 1:
        return 0.0
    start = arr[-window - 1]
    end = arr[-1]
    if start == 0:
        return 0.0
    return float((end - start) / start)


def _price_ok(price: float) -> bool:
    """Return True if a contract price is within a tradeable range."""
    return MIN_CONTRACT_PRICE < price < MAX_CONTRACT_PRICE
