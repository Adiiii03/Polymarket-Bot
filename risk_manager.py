"""
risk_manager.py — Position sizing and daily drawdown protection.

Keeps us safe when markets move against us and prevents the bot from
blowing up the account in a single bad session.
"""

from dataclasses import dataclass, field
from typing import Optional

from config import (
    INITIAL_CAPITAL,
    MAX_POSITION_FRACTION,
    MIN_ORDER_SHARES,
    MAX_ORDER_SHARES,
    DAILY_LOSS_LIMIT,
    MAX_OPEN_POSITIONS,
)
from logger_setup import get_logger

log = get_logger("RiskManager")


@dataclass
class OpenPosition:
    order_id: str
    direction: str       # "UP" or "DOWN"
    shares: float
    entry_price: float
    cost: float          # shares * entry_price (USDC spent)
    market_slug: str
    end_timestamp: int


class RiskManager:
    """
    Tracks account equity and open positions; decides whether and how
    much to bet on each signal.
    """

    def __init__(self, starting_balance: float = INITIAL_CAPITAL):
        self._balance = starting_balance        # Current available USDC
        self._peak_balance = starting_balance   # For drawdown tracking
        self._session_start_balance = starting_balance
        self._open_positions: dict[str, OpenPosition] = {}  # order_id → position
        self._total_trades = 0
        self._winning_trades = 0
        self._total_pnl = 0.0

    # ─── Gating ──────────────────────────────────────────────────────────────

    def can_trade(self) -> bool:
        """Return False if we should stop trading (daily loss limit hit etc.)."""
        if self._balance <= 0:
            log.warning("⛔ Balance exhausted — trading halted")
            return False

        daily_loss = (self._session_start_balance - self._balance) / self._session_start_balance
        if daily_loss >= DAILY_LOSS_LIMIT:
            log.warning(
                f"⛔ Daily loss limit reached ({daily_loss*100:.1f}% ≥ "
                f"{DAILY_LOSS_LIMIT*100:.1f}%) — trading halted for today"
            )
            return False

        if len(self._open_positions) >= MAX_OPEN_POSITIONS:
            log.debug(
                f"Max open positions ({MAX_OPEN_POSITIONS}) reached — skipping signal"
            )
            return False

        return True

    # ─── Position Sizing ─────────────────────────────────────────────────────

    def size_order(self, edge: float, entry_price: float) -> float:
        """
        Return the number of shares to buy using a simplified Kelly criterion.

        Full Kelly: f* = (p * b - q) / b
          where p = win probability, b = net odds (1/price - 1), q = 1 - p

        We use a half-Kelly fraction and then cap it at MAX_POSITION_FRACTION
        of current balance.

        Returns shares (float), guaranteed ≥ MIN_ORDER_SHARES.
        """
        if entry_price <= 0 or entry_price >= 1:
            return MIN_ORDER_SHARES

        p = entry_price + edge   # Our estimated win probability
        q = 1.0 - p
        b = (1.0 / entry_price) - 1.0  # Net odds per dollar risked

        kelly = (p * b - q) / b if b > 0 else 0
        half_kelly = max(0.0, kelly / 2.0)

        # Fraction of balance → USDC → shares
        usdc_to_risk = self._balance * min(half_kelly, MAX_POSITION_FRACTION)
        shares = usdc_to_risk / entry_price

        shares = round(max(MIN_ORDER_SHARES, min(MAX_ORDER_SHARES, shares)), 1)
        usdc_cost = shares * entry_price

        if usdc_cost > self._balance:
            # Fall back to minimum if we can't afford the calculated size
            shares = max(MIN_ORDER_SHARES, round(self._balance * 0.05 / entry_price, 1))

        log.debug(
            f"Sizing: edge={edge:.3f}  kelly={kelly:.3f}  "
            f"half_kelly={half_kelly:.3f}  shares={shares}  "
            f"cost=${shares * entry_price:.2f}"
        )
        return shares

    # ─── Position Tracking ───────────────────────────────────────────────────

    def record_order_placed(
        self,
        order_id: str,
        direction: str,
        shares: float,
        entry_price: float,
        market_slug: str,
        end_timestamp: int,
    ):
        cost = shares * entry_price
        self._balance -= cost
        self._total_trades += 1

        pos = OpenPosition(
            order_id=order_id,
            direction=direction,
            shares=shares,
            entry_price=entry_price,
            cost=cost,
            market_slug=market_slug,
            end_timestamp=end_timestamp,
        )
        self._open_positions[order_id] = pos

        log.info(
            f"💰 Balance after order: ${self._balance:.2f} USDC  "
            f"(reserved ${cost:.2f} for this trade)"
        )

    def record_market_settled(
        self,
        market_slug: str,
        won: bool,
    ):
        """
        Called when a 5-minute market resolves.  Finds all open positions
        for this market slug and marks them as won or lost.
        """
        closed = [
            pos for pos in self._open_positions.values()
            if pos.market_slug == market_slug
        ]

        for pos in closed:
            if won:
                # Each share pays $1 on win
                payout = pos.shares * 1.0
                pnl = payout - pos.cost
                self._balance += payout
                self._winning_trades += 1
            else:
                pnl = -pos.cost  # We lose the cost; already deducted

            self._total_pnl += pnl
            self._peak_balance = max(self._peak_balance, self._balance)

            result_emoji = "✅" if won else "❌"
            log.info(
                f"{result_emoji} Market settled [{pos.direction}]  "
                f"PnL: {'+'if pnl >= 0 else ''}{pnl:.2f} USDC  "
                f"Balance: ${self._balance:.2f}"
            )
            del self._open_positions[pos.order_id]

        self._log_session_stats()

    def expire_positions_for_market(self, market_slug: str, won: bool):
        """Alias used by main loop after market expiry."""
        self.record_market_settled(market_slug, won)

    # ─── Stats ───────────────────────────────────────────────────────────────

    def _log_session_stats(self):
        win_rate = (
            self._winning_trades / self._total_trades
            if self._total_trades > 0 else 0
        )
        drawdown = (
            (self._peak_balance - self._balance) / self._peak_balance
            if self._peak_balance > 0 else 0
        )
        log.info(
            f"📊 Session stats — Trades: {self._total_trades}  "
            f"Win rate: {win_rate*100:.1f}%  "
            f"Total PnL: ${self._total_pnl:+.2f}  "
            f"Balance: ${self._balance:.2f}  "
            f"Max drawdown: {drawdown*100:.1f}%"
        )

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def open_position_count(self) -> int:
        return len(self._open_positions)

    @property
    def open_positions(self) -> dict[str, OpenPosition]:
        return dict(self._open_positions)
