"""
tracker.py — Persists every trade to a CSV so you can analyse performance
in Excel / Python later.
"""

import csv
import os
import time
from dataclasses import dataclass
from typing import Optional

from config import TRADE_LOG_FILE
from logger_setup import get_logger

log = get_logger("Tracker")

HEADERS = [
    "timestamp",
    "market_slug",
    "direction",
    "shares",
    "entry_price",
    "cost_usdc",
    "won",
    "pnl_usdc",
    "balance_after",
    "order_id",
]


class TradeTracker:
    """
    Appends a CSV row after each trade resolves.
    Creates the CSV with headers if it doesn't already exist.
    """

    def __init__(self, filepath: str = TRADE_LOG_FILE):
        self._filepath = filepath
        self._ensure_headers()

    def _ensure_headers(self):
        if not os.path.exists(self._filepath):
            with open(self._filepath, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                writer.writeheader()
            log.info(f"Created trade log: {self._filepath}")

    def log_trade(
        self,
        market_slug: str,
        direction: str,
        shares: float,
        entry_price: float,
        cost: float,
        won: bool,
        pnl: float,
        balance_after: float,
        order_id: str,
    ):
        row = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "market_slug": market_slug,
            "direction": direction,
            "shares": f"{shares:.1f}",
            "entry_price": f"{entry_price:.4f}",
            "cost_usdc": f"{cost:.4f}",
            "won": "1" if won else "0",
            "pnl_usdc": f"{pnl:.4f}",
            "balance_after": f"{balance_after:.4f}",
            "order_id": order_id,
        }
        with open(self._filepath, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=HEADERS).writerow(row)
