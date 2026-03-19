# Polymarket BTC 5-Minute Bot — Complete Setup Guide

## Cost Breakdown

| Item | Cost |
|------|------|
| Python + dependencies | **Free** |
| Binance price feed (WebSocket) | **Free** |
| Polymarket API access | **Free** |
| Running on your PC | **Free** |
| MATIC for gas (one-time) | **~$2–3** (buy once, lasts months) |
| USDC approval gas fee | **~$0.01** |
| Gas per trade (Polygon) | **~$0.001–0.005** |
| 1,000 trades worth of gas | **~$1–5** |
| **Total infrastructure cost** | **~$3–8 one-time, then ~$0/month** |

Your only real cost is the **$300 starting capital** you're trading with.

---

## Step 1 — Install Python

Download Python 3.11+ from https://python.org/downloads
Make sure to check **"Add Python to PATH"** during installation.

---

## Step 2 — Install the bot

Open a terminal (Command Prompt / Terminal) and run:

```bash
# Navigate into the bot folder
cd path/to/polymarket-bot

# Install dependencies
pip install -r requirements.txt
```

---

## Step 3 — Get a Polygon wallet

You need a **self-custody wallet** (not an exchange account).

**Option A — MetaMask (easiest)**
1. Install MetaMask: https://metamask.io
2. Create a new wallet and save your seed phrase offline
3. Add the **Polygon network** (MetaMask → Settings → Networks → Add Polygon)
4. Export your private key: MetaMask → Account → Export Private Key

**Option B — Generate a new wallet with Python (advanced)**
```python
from web3 import Web3
acct = Web3().eth.account.create()
print("Address:", acct.address)
print("Private key:", acct.key.hex())
```
Save both values securely.

---

## Step 4 — Fund your wallet with USDC on Polygon

Your wallet needs two things:
- **USDC** (your trading capital — start with $300)
- **MATIC** (~$3 worth, for gas fees)

**How to get them:**

1. Buy **USDC** and **MATIC** on Coinbase, Binance, or Kraken
2. When withdrawing, choose the **Polygon (MATIC) network** — NOT Ethereum
   - Ethereum fees are $5–20 per tx; Polygon fees are <$0.01
3. Send to your wallet address

> ⚠️ Double-check you're withdrawing on **Polygon**, not Ethereum or BNB Chain.

---

## Step 5 — Configure the bot

```bash
# Copy the example config
cp .env.example .env

# Open .env in a text editor and fill in:
#   PRIVATE_KEY=your_wallet_private_key_here
#   WALLET_ADDRESS=0xYourWalletAddress
#   INITIAL_CAPITAL=300
```

> 🔒 Never share your `.env` file or private key with anyone.

---

## Step 6 — One-time setup (approve USDC spending)

Before the bot can trade, Polymarket's smart contract needs permission
to move your USDC. This is a standard ERC-20 approval — no funds move.

```bash
python setup_wallet.py
```

You should see:
```
✅ Connected to Polygon mainnet
   MATIC balance:  X.XXXX MATIC
   USDC balance:   300.00 USDC
✅ USDC approval confirmed!
✅ L2 credentials derived successfully
✅ Setup complete! You're ready to trade.
```

---

## Step 7 — Start the bot

```bash
python main.py
```

The bot will:
1. Connect to Binance's free price feed
2. Find the current active 5-minute BTC market on Polymarket
3. Monitor for momentum gaps in real-time (~2 checks/second)
4. Place orders automatically when it finds an edge
5. Record every trade to `trades.csv` for your review
6. Move to the next market after each 5-minute window

To stop, press **Ctrl+C** — the bot shuts down gracefully.

---

## Tuning the strategy (config.py)

| Parameter | Default | Effect |
|-----------|---------|--------|
| `MIN_EDGE` | `0.04` | Minimum gap before trading (higher = fewer but higher-quality trades) |
| `MOMENTUM_SENSITIVITY` | `400` | How strongly BTC momentum affects our fair-value estimate |
| `MAX_POSITION_FRACTION` | `0.08` | Max 8% of balance per trade |
| `DAILY_LOSS_LIMIT` | `0.15` | Stop trading if down 15% today |
| `MAX_OPEN_POSITIONS` | `3` | Max simultaneous bets |

**Start conservative.** Run for a few days at default settings and review
`trades.csv` before increasing position sizes.

---

## Understanding your trades.csv

Every settled trade is logged here:

| Column | Meaning |
|--------|---------|
| `timestamp` | When the order was placed |
| `direction` | UP or DOWN |
| `entry_price` | Price paid per share (e.g. 0.47 = 47¢) |
| `shares` | Number of shares bought |
| `cost_usdc` | Total USDC spent |
| `won` | 1 = won, 0 = lost |
| `pnl_usdc` | Profit/loss in USDC |
| `balance_after` | Running balance |

---

## Important risk warnings

- **This is speculative trading.** You can lose your entire $300.
- Past results from others do not guarantee your results.
- Start with a smaller amount (e.g. $50) to test the system first.
- Never trade money you can't afford to lose.
- The bot places real orders with real money automatically.
- Keep an eye on `trades.csv` daily to monitor performance.

---

## Troubleshooting

**"PRIVATE_KEY not set"** → Make sure `.env` exists and has your key.

**"Low MATIC balance"** → Buy MATIC on an exchange and withdraw to Polygon.

**"No active market found"** → Polymarket creates new markets shortly before
each 5-minute window starts. The bot retries automatically.

**"Order placement failed"** → Possible causes: insufficient USDC balance,
USDC approval not done, or Polymarket API temporarily down. Run
`setup_wallet.py` again to diagnose.

**Orders are placed but not filling** → Increase `MIN_CONTRACT_PRICE`
or widen `MIN_EDGE` — your limit price may be away from the market.
