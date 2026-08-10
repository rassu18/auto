"""
logger.py — All logging for the Nifty Paper Trading Bot

Log files created:
  logs/trades.log   — Every entry and exit with full details
  logs/signals.log  — Every signal evaluation (EMA, OR, crossovers)
  logs/debug.log    — Internal state, skips, dedup, cooldowns
  logs/errors.log   — Exceptions and API failures
  logs/summary.log  — End-of-day P&L summary
"""

import os
from datetime import datetime

LOG_DIR = "logs"

# Create logs directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

TRADES_LOG  = os.path.join(LOG_DIR, "trades.log")
SIGNALS_LOG = os.path.join(LOG_DIR, "signals.log")
DEBUG_LOG   = os.path.join(LOG_DIR, "debug.log")
ERRORS_LOG  = os.path.join(LOG_DIR, "errors.log")
SUMMARY_LOG = os.path.join(LOG_DIR, "summary.log")


def _write(filepath: str, msg: str):
    """Base writer — thread-safe enough for single-process use."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


# ==========================================
# TRADE LOG — entry / exit events
# ==========================================

def log_trade(action: str, price: float, extra: dict = None):
    """
    Log an entry or exit event.

    Args:
        action : e.g. "ENTRY CE", "EXIT PE [WIN]", "BOT_START"
        price  : execution price
        extra  : dict of additional key=value pairs
    """
    lines = [
        "",
        "=" * 60,
        f"  {action}",
        f"  Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Price : {price}",
    ]

    if extra:
        for k, v in extra.items():
            lines.append(f"  {k:<12}: {v}")

    lines.append("=" * 60)
    lines.append("")

    with open(TRADES_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ==========================================
# SIGNAL LOG — every candle evaluation
# ==========================================

def log_signal(msg: str):
    """
    Log a signal evaluation line.
    One line per candle — shows price, EMAs, OR levels, crossovers.
    """
    _write(SIGNALS_LOG, msg)


# ==========================================
# DEBUG LOG — internal state tracking
# ==========================================

def log_debug(msg: str):
    """
    Log internal state info:
    - Dedup skips
    - Cooldown status
    - OR build progress
    - API retries
    """
    _write(DEBUG_LOG, msg)


# ==========================================
# ERROR LOG — exceptions
# ==========================================

def log_error(msg: str):
    """
    Log exceptions and API failures.
    Always written — never suppressed.
    """
    _write(ERRORS_LOG, f"ERROR: {msg}")


# ==========================================
# SUMMARY LOG — end of day P&L
# ==========================================

def log_summary(
    trades: int,
    wins: int,
    losses: int,
    daily_pnl: float,
    capital: float,
):
    """
    Write end-of-day summary block to summary.log.
    """
    date_str   = datetime.now().strftime("%Y-%m-%d")
    win_rate   = round((wins / trades * 100) if trades > 0 else 0, 1)
    return_pct = round((daily_pnl / capital * 100), 2)

    lines = [
        "",
        "=" * 60,
        f"  END OF DAY SUMMARY — {date_str}",
        "=" * 60,
        f"  Total Trades : {trades}",
        f"  Wins         : {wins}",
        f"  Losses       : {losses}",
        f"  Win Rate     : {win_rate}%",
        f"  Daily PnL    : ₹{daily_pnl}",
        f"  Capital      : ₹{capital}",
        f"  Return       : {return_pct}%",
        "=" * 60,
        "",
    ]

    with open(SUMMARY_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Also echo to trades.log for a single complete record
    with open(TRADES_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
