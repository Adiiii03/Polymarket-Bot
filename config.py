"""
config.py — Centralised configuration for the Polymarket BTC Bot.
All tuneable parameters live here so you never have to hunt through code.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Wallet / Chain ──────────────────────────────────────────────────────────
PRIVATE_KEY: str = os.getenv("PRIVATE_KEY", "")
WALLET_ADDRESS: str = os.getenv("WALLET_ADDRESS", "")
CHAIN_ID: int = 137           # Polygon mainnet
POLYGON_RPC: str = "https://polygon-rpc.com"

# ─── Polymarket API ──────────────────────────────────────────────────────────
CLOB_HOST: str = "https://clob.polymarket.com"
GAMMA_HOST: str = "https://gamma-api.polymarket.com"

# Slug prefix for 5-minute BTC up/down markets
# Full slug example: btc-updown-5m-1771168800
MARKET_SLUG_PREFIX: str = "btc-updown-5m-"

# How many seconds before market expiry to stop placing new orders
MARKET_CLOSE_BUFFER_SECS: int = 30

# ─── Price Feed ──────────────────────────────────────────────────────────────
BINANCE_WS_URL: str = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"

# Number of price ticks to keep in the rolling history (at ~10 ticks/sec
# from Binance aggTrade, 600 ticks ≈ last 60 seconds)
PRICE_HISTORY_LEN: int = 600

# ─── Strategy ────────────────────────────────────────────────────────────────
# Minimum edge (in probability points) before we place a trade.
# e.g. 0.04 means we only trade when our model says fair value is
# at least 4 cents better than the market price.
MIN_EDGE: float = 0.04

# How sensitive the momentum model is to BTC price moves.
# Higher = more aggressive; lower = more conservative.
# tanh(price_change_pct * MOMENTUM_SENSITIVITY) drives the probability adjustment.
MOMENTUM_SENSITIVITY: float = 400

# Maximum probability the model will ever assign to UP (caps overconfidence)
MAX_FAIR_PROB: float = 0.72
MIN_FAIR_PROB: float = 0.28

# Number of recent price ticks used for short-term momentum
SHORT_WINDOW: int = 60    # ~6 seconds at 10 ticks/sec
MEDIUM_WINDOW: int = 200  # ~20 seconds
LONG_WINDOW: int = 400    # ~40 seconds

# ─── Risk Management ─────────────────────────────────────────────────────────
INITIAL_CAPITAL: float = float(os.getenv("INITIAL_CAPITAL", "5"))

# Max fraction of current balance risked per trade (Kelly-inspired)
MAX_POSITION_FRACTION: float = 0.15   # 15% per trade (higher for small balance)

# Absolute min/max order size in shares
MIN_ORDER_SHARES: float = 1.0
MAX_ORDER_SHARES: float = 200.0

# Stop all trading for the day if total loss exceeds this fraction
DAILY_LOSS_LIMIT: float = 0.15        # 15%

# Maximum number of open positions at once
MAX_OPEN_POSITIONS: int = 3

# Minimum price to ever pay for a contract (avoid buying near-dead contracts)
MIN_CONTRACT_PRICE: float = 0.05
MAX_CONTRACT_PRICE: float = 0.95

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL: str = "INFO"
TRADE_LOG_FILE: str = "trades.csv"
