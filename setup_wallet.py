"""
setup_wallet.py — One-time wallet setup script.

Run this ONCE before starting the bot to:
  1. Verify your wallet is connected to Polygon
  2. Check your USDC balance
  3. Approve the Polymarket contract to spend your USDC

This script costs a tiny amount of MATIC in gas (~$0.01 at most).
You only need to run it once per wallet.

Usage:
    python setup_wallet.py
"""

import asyncio
import sys

from web3 import Web3
from py_clob_client.client import ClobClient

from config import PRIVATE_KEY, WALLET_ADDRESS, POLYGON_RPC, CHAIN_ID, CLOB_HOST
from logger_setup import get_logger

log = get_logger("Setup")

# Polygon USDC contract (native USDC, not bridged)
USDC_CONTRACT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
# Polymarket CTF Exchange address (the contract that needs USDC approval)
POLYMARKET_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

USDC_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
    {
        "name": "allowance",
        "type": "function",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
    {
        "name": "approve",
        "type": "function",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
    },
]

MAX_UINT256 = 2**256 - 1


def run_setup():
    if not PRIVATE_KEY:
        log.error("PRIVATE_KEY not set in .env — please fill in .env first")
        sys.exit(1)

    log.info("=" * 50)
    log.info("  Polymarket BTC Bot — Wallet Setup")
    log.info("=" * 50)

    # ── Connect to Polygon ────────────────────────────────────────────────
    w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
    if not w3.is_connected():
        log.error(f"Cannot connect to Polygon RPC: {POLYGON_RPC}")
        sys.exit(1)

    account = w3.eth.account.from_key(PRIVATE_KEY)
    address = account.address
    log.info(f"✅ Connected to Polygon mainnet")
    log.info(f"   Wallet address: {address}")

    # ── Check MATIC balance (for gas) ────────────────────────────────────
    matic_balance = w3.eth.get_balance(address)
    matic_human = w3.from_wei(matic_balance, "ether")
    log.info(f"   MATIC balance:  {matic_human:.4f} MATIC")
    if matic_human < 0.01:
        log.warning(
            "⚠️  Low MATIC balance — you need at least 0.01 MATIC for gas.\n"
            "   Buy MATIC on Coinbase/Binance and withdraw to Polygon network."
        )

    # ── Check USDC balance ───────────────────────────────────────────────
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT),
        abi=USDC_ABI,
    )
    usdc_balance = usdc.functions.balanceOf(address).call()
    usdc_human = usdc_balance / 1e6  # USDC has 6 decimals
    log.info(f"   USDC balance:   {usdc_human:.2f} USDC")

    if usdc_human < 10:
        log.warning(
            "⚠️  Low USDC balance — deposit at least $10 USDC to Polygon.\n"
            "   Use Coinbase/Binance to withdraw USDC to Polygon network directly."
        )

    # ── Check / set USDC allowance ───────────────────────────────────────
    allowance = usdc.functions.allowance(
        address,
        Web3.to_checksum_address(POLYMARKET_EXCHANGE),
    ).call()
    allowance_human = allowance / 1e6

    if allowance >= usdc_balance:
        log.info(f"✅ USDC allowance already set ({allowance_human:.2f} USDC approved)")
    else:
        log.info("📝 Approving Polymarket to spend your USDC...")
        log.info("   This is a standard ERC-20 approval — no funds are moved.")

        nonce = w3.eth.get_transaction_count(address)
        tx = usdc.functions.approve(
            Web3.to_checksum_address(POLYMARKET_EXCHANGE),
            MAX_UINT256,
        ).build_transaction({
            "from": address,
            "nonce": nonce,
            "gas": 60_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": CHAIN_ID,
        })

        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        log.info(f"   Tx sent: {tx_hash.hex()}")
        log.info("   Waiting for confirmation...")

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt.status == 1:
            log.info("✅ USDC approval confirmed!")
        else:
            log.error("❌ Approval transaction failed — check PolygonScan")
            sys.exit(1)

    # ── Derive Polymarket L2 API credentials ─────────────────────────────
    log.info("🔑 Deriving Polymarket L2 API credentials...")
    try:
        client = ClobClient(
            CLOB_HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=1,
            funder=address,
        )
        creds = client.create_or_derive_api_creds()
        log.info("✅ L2 credentials derived successfully")
        log.info(f"   API Key: {creds.api_key[:8]}...")
    except Exception as e:
        log.error(f"Failed to derive API credentials: {e}")
        log.error("Make sure PRIVATE_KEY is correct in your .env file")
        sys.exit(1)

    # ── Done ─────────────────────────────────────────────────────────────
    log.info("")
    log.info("=" * 50)
    log.info("  ✅ Setup complete!  You're ready to trade.")
    log.info("  Run:  python main.py")
    log.info("=" * 50)


if __name__ == "__main__":
    run_setup()
