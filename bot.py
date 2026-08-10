import requests
import time
from datetime import datetime
import csv
import io
import socket
from logger import log_trade, log_signal, log_debug, log_summary, log_error

# ================= CONFIG =================

ACCESS_TOKEN = "eyJhbGciOiJIUzUxMiIsInR5cCI6IkpXVCJ9.eyJjbGllbnRJRCI6IjAzQUg0IiwiZXhwIjoxNzg2NDExODAwLCJpYXQiOjE3ODYzMzE5NzYsImlzcyI6ImluZG1vbmV5IiwicGFydG5lcklEIjoxNzY1NSwidG9rZW5JRCI6NTkxNTh9.U8bojRFaaLseQFLXBXFVldWUv2dHZxAee6nU5C_18Hkp39pSaLe8P8hN9CTdXJyhNnrRXZ2icZy-xKmzZRAJbQ"

NIFTY_CODE = "NIDX_40000001"
NIFTY_STRIKE_GAP = 50 

BASE_URL = "https://api.indstocks.com"

TRADING_MODE = "LIVE"   # PAPER or LIVE

NO_OF_LOTS = 19

LOT_SIZE = 65 * NO_OF_LOTS

DAILY_STOP_RS = -1000 * NO_OF_LOTS

today = datetime.now().date()

START_TRADING_TIME = "09:30"

FORCE_EXIT_TIME = "15:15"

MAX_ENTRY_DELAY_SEC = 90

POSITION_MONITOR_INTERVAL = 1

ENTRY_SCAN_INTERVAL = 30

MIN_EMA_SEPARATION = 5.5

STOP_LOSS_RS = -600 * NO_OF_LOTS

TRAIL_TRIGGER_RS = 130 * NO_OF_LOTS

TRAIL_GAP_RS = 130 * NO_OF_LOTS

max_profit_seen = 0

# ==========================
# Weekly Expiry Settings
# ==========================
ENABLE_WEEKLY_EXPIRY_FILTER = True
EXPIRY_ENTRY_CUTOFF = "12:00"

# =========================================

position_open = False

trade_side = None

entry_price = 0

daily_points = 0

ce_entry_taken = False
pe_entry_taken = False

wins = 0
losses = 0
total_trades = 0

or_high = None
or_low = None

last_signal_candle_ts = None
last_processed_candle_ts = None

last_exit_candle_ts = None

last_ema_check_minute = None

max_profit_seen = 0
trail_active = False

option_security_id = None
option_symbol = None
option_strike = None

entry_order_id = None
exit_order_id = None

_instruments_cache   = None
_instruments_date    = None

# =========================================


def log_trade(msg):

    with open(
        "trades.log",
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"\n[{datetime.now()}] {msg}\n"
        )

def is_weekly_expiry():
    """
    Returns True if today is the weekly NIFTY expiry day.
    Currently, weekly expiry is Tuesday.
    """
    return datetime.now().weekday() == 1

def log_debug(msg):

    with open(
        "debug.log",
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"\n[{datetime.now()}] {msg}\n"
        )

def log_research(msg):

    with open(
        "research.log",
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"\n[{datetime.now()}] {msg}\n"
        )

def load_instruments_fno() -> list:
    global _instruments_cache, _instruments_date

    today = datetime.now().date()

    if _instruments_cache and _instruments_date == today:
        return _instruments_cache

    log_debug("Downloading FNO instruments CSV...")

    headers = {"Authorization": ACCESS_TOKEN}
    url     = f"{BASE_URL}/market/instruments?source=fno"

    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        with open("fno_instruments.csv", "w", encoding="utf-8") as f:
            f.write(r.text)

        reader = csv.DictReader(io.StringIO(r.text))
        rows   = list(reader)

        _instruments_cache = rows
        _instruments_date  = today

        log_debug(f"Instruments loaded — {len(rows)} rows")
        return rows

    except Exception as e:
        
        raise


def get_nifty_candles():

    headers = {
        "Authorization": ACCESS_TOKEN
    }

    end_time = int(time.time() * 1000)

    start_time = (
        end_time
        - (3 * 24 * 60 * 60 * 1000)
    )

    url = (
        BASE_URL
        + "/market/historical/5minute"
        + f"?scrip-codes={NIFTY_CODE}"
        + f"&start_time={start_time}"
        + f"&end_time={end_time}"
    )

    r = requests.get(
        url,
        headers=headers
    )

    data = r.json()

    print("=" * 50)
    #print(data)
    print("=" * 50)

    return (
        data["data"]
        [NIFTY_CODE]
        ["candles"]
    )


def ema(values, period):

    multiplier = 2 / (period + 1)

    ema_value = values[0]

    for price in values[1:]:

        ema_value = (
            (price - ema_value)
            * multiplier
        ) + ema_value

    return ema_value


def get_latest_data():

    candles = get_nifty_candles()

    closes = [
        c["c"]
        for c in candles[:-1]
    ]

    latest = candles[-2]
    previous = candles[-3]

    # DEBUG
    print("\nLATEST CANDLE:")
    print(latest)

    print("\nPREVIOUS CANDLE:")
    print(previous)

    ema3 = ema(closes, 3)
    ema30 = ema(closes, 30)

    return (
        latest,
        previous,
        ema3,
        ema30,
        candles
    )
    
    
# =========================================
# OPENING RANGE
# =========================================

def build_opening_range(candles):

    global or_high
    global or_low

    highs = []
    lows = []
    
    today = datetime.now().date()

    for c in candles:

        ts = datetime.fromtimestamp(c["ts"])
        
        #print(ts)

        if ts.date() != today:
            continue

        hhmm = ts.strftime("%H:%M")

        if hhmm in ["09:15", "09:20", "09:25", "09:30"]:

            highs.append(c["h"])
            lows.append(c["l"])

    if highs and lows:

        or_high = max(highs)
        or_low = min(lows)
        
        print(
            f"Opening Range Built | High={or_high} Low={or_low}"
        )

        return True

    return False
    
# =========================================
# ENTRY
# =========================================

def enter_trade(
    side,
    price,
    ema3,
    ema30,
    setup
):

    global position_open
    global trade_side
    global entry_price

    global option_security_id
    global option_symbol
    global option_strike

    global entry_order_id

    print(f"MODE : {TRADING_MODE}")

    # --------------------------------------------------
    # Find ATM Option
    # --------------------------------------------------
    opt = find_atm_option(price, side)

    if opt is None:
        print("No ATM option found.")
        return

    option_security_id = opt["security_id"]
    option_symbol = opt["trading_symbol"]
    option_strike = opt["strike"]

    # --------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------
    if TRADING_MODE == "PAPER":

        try:
            premium = get_option_ltp(option_security_id)
        except Exception:
            print("Unable to fetch option premium.")
            return

        entry_order_id = None

    # --------------------------------------------------
    # LIVE MODE
    # --------------------------------------------------
    else:

        order_id = place_order(
            side="BUY",
            security_id=option_security_id,
            qty=LOT_SIZE
        )

        if not order_id:
            print("BUY order failed.")
            return

        entry_order_id = order_id

        time.sleep(2)

        fill_price = get_order_fill_price(order_id)

        if fill_price:

            premium = fill_price

        else:

            try:
                premium = get_option_ltp(option_security_id)
            except Exception:
                print("Unable to fetch option premium.")
                return

    # --------------------------------------------------
    # Store Position
    # --------------------------------------------------
    position_open = True
    trade_side = side
    entry_price = premium
    global max_profit_seen
    global trail_active

    max_profit_seen = 0
    trail_active = False

    # --------------------------------------------------
    # Console Log
    # --------------------------------------------------
    print("\n")
    print("=" * 60)
    print(f"ENTRY {side}")
    print(f"MODE      : {TRADING_MODE}")
    print(f"NIFTY     : {price}")
    print(f"OPTION    : {option_symbol}")
    print(f"STRIKE    : {option_strike}")
    print(f"PREMIUM   : {round(premium,2)}")
    print(f"ORDER ID  : {entry_order_id}")
    print(f"TIME      : {datetime.now()}")
    print(f"EMA3      : {round(ema3,2)}")
    print(f"EMA30     : {round(ema30,2)}")
    print("=" * 60)

    # --------------------------------------------------
    # File Log
    # --------------------------------------------------
    log_trade(
        f"""
============================================================

ENTRY {side}

MODE: {TRADING_MODE}

TIME: {datetime.now()}

NIFTY: {price}

OPTION: {option_symbol}

STRIKE: {option_strike}

PREMIUM: {round(premium,2)}

ORDER_ID: {entry_order_id}

EMA3: {round(ema3,2)}

EMA30: {round(ema30,2)}

SETUP: {setup}

============================================================
"""
    )

    print(f"SETUP : {setup}") 
    
    
# =========================================
# EXIT
# =========================================

def exit_trade(
    price,
    reason
):

    global position_open
    global trade_side
    global entry_price

    global option_security_id
    global option_symbol
    global option_strike

    global entry_order_id
    global exit_order_id

    global daily_points
    global wins
    global losses
    global total_trades
    
    global max_profit_seen
    global trail_active

    # --------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------
    if TRADING_MODE == "PAPER":

        try:
            exit_price = get_option_ltp(option_security_id)
        except Exception:
            print("Unable to fetch exit premium.")
            return

        exit_order_id = None

    # --------------------------------------------------
    # LIVE MODE
    # --------------------------------------------------
    else:

        order_id = square_off(
            option_security_id,
            LOT_SIZE
        )

        if not order_id:
            print("SELL order failed.")
            return

        exit_order_id = order_id

        time.sleep(2)

        fill_price = get_order_fill_price(order_id)

        if fill_price:

            exit_price = fill_price

        else:

            try:
                exit_price = get_option_ltp(option_security_id)
            except Exception:
                print("Unable to fetch exit premium.")
                return

    # --------------------------------------------------
    # Calculate PnL
    # --------------------------------------------------
    points = exit_price - entry_price
    pnl_rs = points * LOT_SIZE

    daily_points += pnl_rs
    total_trades += 1

    if pnl_rs > 0:
        wins += 1
    else:
        losses += 1

    # --------------------------------------------------
    # Console Log
    # --------------------------------------------------
    print("\n")
    print("=" * 60)
    print(f"EXIT {trade_side}")
    print(f"MODE      : {TRADING_MODE}")
    print(f"REASON    : {reason}")
    print(f"OPTION    : {option_symbol}")
    print(f"STRIKE    : {option_strike}")
    print(f"ENTRY     : {round(entry_price,2)}")
    print(f"EXIT      : {round(exit_price,2)}")
    print(f"POINTS    : {round(points,2)}")
    print(f"PNL       : ₹{round(pnl_rs,2)}")
    print(f"BUY ID    : {entry_order_id}")
    print(f"SELL ID   : {exit_order_id}")
    print(f"TIME      : {datetime.now()}")
    print("=" * 60)

    # --------------------------------------------------
    # File Log
    # --------------------------------------------------
    log_trade(
        f"""
============================================================

EXIT {trade_side}

MODE: {TRADING_MODE}

REASON: {reason}

TIME: {datetime.now()}

OPTION: {option_symbol}

STRIKE: {option_strike}

ENTRY PREMIUM: {round(entry_price,2)}

EXIT PREMIUM: {round(exit_price,2)}

POINTS: {round(points,2)}

PNL: {round(pnl_rs,2)}

BUY_ORDER_ID: {entry_order_id}

SELL_ORDER_ID: {exit_order_id}

============================================================
"""
    )

    # --------------------------------------------------
    # Reset Position
    # --------------------------------------------------
    position_open = False
    trade_side = None
    entry_price = 0

    max_profit_seen = 0
    trail_active = False

    option_security_id = None
    option_symbol = None
    option_strike = None

    entry_order_id = None
    exit_order_id = None 
    

def monitor_live_position():

    global entry_price
    global option_security_id
    global option_symbol
    global trade_side
    global max_profit_seen
    global trail_active

    if not position_open:
        return

    try:
        current_premium = get_option_ltp(option_security_id)
    except Exception:
        print("Unable to fetch live premium.")
        return

    current_pnl_rs = round(
        (current_premium - entry_price) * LOT_SIZE,
        2
    )
    
    # -----------------------------------------
    # Track Maximum Profit
    # -----------------------------------------

    if current_pnl_rs > max_profit_seen:
        max_profit_seen = current_pnl_rs
        
    
    # -----------------------------------------
    # Activate Trailing Stop
    # -----------------------------------------

    if (
        not trail_active
        and max_profit_seen >= TRAIL_TRIGGER_RS
    ):
        trail_active = True

        print(">>> TRAILING STOP ACTIVATED <<<")

    print("\n")
    print("=" * 60)
    print("LIVE POSITION")
    print("=" * 60)
    print(f"SIDE       : {trade_side}")
    print(f"OPTION     : {option_symbol}")
    print(f"ENTRY      : {round(entry_price,2)}")
    print(f"CURRENT    : {round(current_premium,2)}")
    print(f"PNL        : ₹{current_pnl_rs}")
    print(f"MAX PNL    : ₹{round(max_profit_seen,2)}")
    print(f"TRAIL      : {'ACTIVE' if trail_active else 'OFF'}")
    print(f"TIME       : {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60) 
    
    # -----------------------------------------
    # Trailing Stop Exit
    # -----------------------------------------

    if trail_active:

        if (max_profit_seen - current_pnl_rs) >= TRAIL_GAP_RS:

            print(
                f"Trailing Stop Hit | "
                f"Peak={round(max_profit_seen,2)} "
                f"Current={round(current_pnl_rs,2)}"
            )

            exit_trade(
                0,
                "TRAILING_STOP"
            )

            return current_pnl_rs

    return current_pnl_rs   


# =========================================
# SIGNALS
# =========================================

def check_entry_signal():

    global last_signal_candle_ts
    global last_processed_candle_ts
    global ce_entry_taken
    global pe_entry_taken
    

    latest, \
    previous, \
    ema3, \
    ema30, \
    candles = get_latest_data()

    if or_high is None:
        build_opening_range(candles)

    if not or_high:
        return

    latest_close = latest["c"]

    current_ts = latest["ts"]

    # Process each completed candle only once
    if current_ts == last_processed_candle_ts:
        return

    last_processed_candle_ts = current_ts

    completed_closes = [c["c"] for c in candles[:-1]]

    prev_ema3 = ema(completed_closes[:-1], 3)

    prev_ema30 = ema(completed_closes[:-1], 30)

    trend = "BULLISH" if ema3 > ema30 else "BEARISH"

    print(
        f"""
==================================================
TIME      : {datetime.now().strftime('%H:%M:%S')}
CANDLE    : {datetime.fromtimestamp(latest['ts'])}
PRICE     : {latest_close}
EMA3      : {round(ema3,2)}
EMA30     : {round(ema30,2)}
TREND     : {trend}
OR_HIGH   : {or_high}
OR_LOW    : {or_low}
POSITION  : {position_open}
==================================================
"""
    )

    print(
        f"prev_ema3={round(prev_ema3,2)} "
        f"prev_ema30={round(prev_ema30,2)} "
        f"ema3={round(ema3,2)} "
        f"ema30={round(ema30,2)}"
    )

    bull_cross = (
        prev_ema3 <= prev_ema30
        and ema3 > ema30
    )

    bear_cross = (
        prev_ema3 >= prev_ema30
        and ema3 < ema30
    )

    print(
        f"BULL_CROSS={bull_cross} "
        f"BEAR_CROSS={bear_cross}"
    )

    print(
        f"CHECK => "
        f"Price:{latest_close} "
        f"ORH:{or_high} "
        f"ORL:{or_low}"
    )

    print(
        f"Distance_ORH={round(latest_close-or_high,2)} "
        f"Distance_ORL={round(latest_close-or_low,2)}"
    )
    
    
    # -----------------------------------------
    # Age of latest completed candle
    # -----------------------------------------

    
    ema_gap = abs(ema3 - ema30)

    print(
        f"EMA Gap : {round(ema_gap,2)} "
        f"(Min Required: {MIN_EMA_SEPARATION})"
    )
    
    # ==========================================================
    # Research Logging
    # ==========================================================

    distance_from_ema30 = round(latest_close - ema30, 2)

    distance_from_or = (
        round(latest_close - or_high, 2)
        if trend == "BULLISH"
        else round(latest_close - or_low, 2)
    )

    log_research(
        f"""
    ============================================================
    SIGNAL ANALYSIS

    TIME              : {datetime.now()}
    CANDLE            : {datetime.fromtimestamp(latest['ts'])}

    TREND             : {trend}
    PRICE             : {latest_close}

    EMA3              : {round(ema3,2)}
    EMA30             : {round(ema30,2)}
    EMA GAP           : {round(ema_gap,2)}

    DIST EMA30        : {distance_from_ema30}
    DIST OR           : {distance_from_or}

    OR HIGH           : {or_high}
    OR LOW            : {or_low}

    CE TAKEN          : {ce_entry_taken}
    PE TAKEN          : {pe_entry_taken}

    ============================================================
    """
    )

    # ==========================================================
    # Weekly Expiry Entry Cutoff
    # ==========================================================

    current_time = datetime.now().strftime("%H:%M")

    if (
        ENABLE_WEEKLY_EXPIRY_FILTER
        and is_weekly_expiry()
        and current_time >= EXPIRY_ENTRY_CUTOFF
    ):
        log_research(
            f"""
        ============================================================
        ENTRY BLOCKED - WEEKLY EXPIRY

        TIME      : {current_time}
        CUT OFF   : {EXPIRY_ENTRY_CUTOFF}
        CE TAKEN  : {ce_entry_taken}
        PE TAKEN  : {pe_entry_taken}

        ============================================================
        """
        )
        return

    # ======================
    # EMA CROSS LONG
    # ======================

    if (
         ema3 > ema30
         and latest_close > ema30
         and latest_close > previous["h"]
         and ema_gap >= MIN_EMA_SEPARATION
         and not ce_entry_taken
    ):

  

        enter_trade(
            "CE",
            latest_close,
            ema3,
            ema30,
            "EMA_TREND"
        )
            
        ce_entry_taken = True
        
        return

    # ======================
    # EMA CROSS SHORT
    # ======================

    if (
        ema3 < ema30
        and latest_close < ema30
        and latest_close < previous["l"]
        and ema_gap >= MIN_EMA_SEPARATION
        and not pe_entry_taken
    ):

               
        enter_trade(
            "PE",
            latest_close,
            ema3,
            ema30,
            "EMA_TREND"
        )
        
        pe_entry_taken = True

        return   
        
# =========================================
# MANAGE EXIT
# =========================================

def manage_position():

    global last_ema_check_minute

    if not position_open:
        return

    # -----------------------------------------
    # Always monitor live position
    # -----------------------------------------

    current_pnl_rs = monitor_live_position()
    
    # Position may have been closed by Trailing Stop
    if not position_open:
        return

    # -----------------------------------------
    # Check EMA only once every 5 minutes
    # -----------------------------------------

    now = datetime.now()

    # Only around 5-minute boundaries
    if now.minute % 5 != 0:
        return

    # Give broker/API a few seconds to publish candle
    if now.second > 10:
        return

    current_slot = now.strftime("%H:%M")

    if current_slot == last_ema_check_minute:
        return

    last_ema_check_minute = current_slot

    print("\nChecking EMA exit...")

    check_ema_exit()  

def check_ema_exit():

    global ce_entry_taken
    global pe_entry_taken
    global last_exit_candle_ts

    latest,\
    previous,\
    ema3,\
    ema30,\
    candles = get_latest_data()

    price = latest["c"]
    
    # -----------------------------------------
    # Process each completed candle only once
    # -----------------------------------------

    if latest["ts"] == last_exit_candle_ts:
        return

    last_exit_candle_ts = latest["ts"]

    if trade_side == "CE":

        if ema3 < ema30:

            ce_entry_taken = False

            exit_trade(
                price,
                "EMA_CROSS"
            )

    else:

        if ema3 > ema30:

            pe_entry_taken = False

            exit_trade(
                price,
                "EMA_CROSS"
            )

            
def find_atm_option(index_price: float, side: str) -> dict | None:
    instruments = load_instruments_fno()
    today       = datetime.now().date()

    atm_strike = round(index_price / NIFTY_STRIKE_GAP) * NIFTY_STRIKE_GAP

    log_debug(f"Finding {side} option | Index={index_price} | ATM={atm_strike}")

    candidates = []
    for row in instruments:
        trading_symbol = (row.get("TRADING_SYMBOL") or "").strip().upper()
        otype          = (row.get("OPTION_TYPE") or "").strip().upper()
        exch           = (row.get("EXCH") or "").strip().upper()

        if not trading_symbol.startswith("NIFTY"):
            continue
        if ("BANKNIFTY" in trading_symbol or "MIDCPNIFTY" in trading_symbol
                or "FINNIFTY" in trading_symbol):
            continue
        if otype != side:
            continue
        if exch != "NSE":
            continue

        try:
            strike     = float(row.get("STRIKE_PRICE") or 0)
            expiry_str = (row.get("EXPIRY_DATE") or "").strip()
            expiry_date = datetime.strptime(expiry_str, "%m/%d/%Y %H:%M").date()
        except Exception:
            continue

        if expiry_date < today:
            continue

        candidates.append({
            "security_id":   (row.get("SECURITY_ID") or "").strip(),
            "strike":        strike,
            "expiry_date":   expiry_date,
            "expiry_str":    expiry_str,
            "trading_symbol": (row.get("TRADING_SYMBOL") or "").strip(),
            "custom_symbol": (row.get("CUSTOM_SYMBOL") or "").strip(),
            "lot_units":     row.get("LOT_UNITS", LOT_SIZE),
        })

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x["expiry_date"], abs(x["strike"] - atm_strike)))
    best = candidates[0]

    log_signal(
        f"OPTION SELECTED | {side} | Strike={best['strike']} | "
        f"Expiry={best['expiry_str']} | Symbol={best['trading_symbol']} | "
        f"SecurityID={best['security_id']}"
    )
    return best
  
def get_option_ltp(security_id: str) -> float:
    scrip_code = f"NFO_{security_id}"
    headers    = {"Authorization": ACCESS_TOKEN}
    url        = f"{BASE_URL}/market/quotes/ltp?scrip-codes={scrip_code}"

    try:
        r    = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        return float(data["data"][scrip_code]["live_price"])
    except Exception as e:
        raise
  
def place_order(side, security_id, qty):
    if TRADING_MODE == "PAPER":
        print(f"[PAPER ORDER] {side} Security={security_id} Qty={qty}")
        return f"PAPER-{int(time.time())}"   # consistent string ID in both modes

    headers = {"Authorization": ACCESS_TOKEN, "Content-Type": "application/json"}
    payload = {
        "txn_type": side,
        "exchange": "NSE",
        "segment": "DERIVATIVE",
        "product": "INTRADAY",
        "order_type": "MARKET",
        "validity": "DAY",
        "security_id": str(security_id),
        "qty": qty,
        "is_amo": False,
        "algo_id": "99999"
    }

    try:
        r = requests.post(f"{BASE_URL}/order", headers=headers, json=payload, timeout=15)
        response = r.json()
        order_status = response.get("data", {}).get("order_status")

        if order_status in ("FAILED", "REJECTED"):
            return None

        order_id = response.get("data", {}).get("order_id")
        return order_id

    except Exception as e:
        return None
 
 
def get_order_fill_price(order_id):
    if TRADING_MODE == "PAPER":
        return None  # paper mode has no real fill — caller keeps quoted premium

    headers = {"Authorization": ACCESS_TOKEN}
    try:
        r = requests.get(f"{BASE_URL}/order-book", headers=headers, timeout=15)
        data   = r.json()
        orders = data.get("data", [])

        for order in orders:
            if order.get("id") == order_id and order.get("status") == "SUCCESS":
                return float(order.get("traded_price", 0))
        return None
    except Exception as e:
        return None


def square_off(security_id, qty):
    if TRADING_MODE == "PAPER":
        print(f"[PAPER EXIT] Security={security_id} Qty={qty}")
        return f"PAPER-EXIT-{int(time.time())}"

    headers = {"Authorization": ACCESS_TOKEN, "Content-Type": "application/json"}
    payload = {
        "txn_type": "SELL",
        "exchange": "NSE",
        "segment": "DERIVATIVE",
        "product": "INTRADAY",
        "order_type": "MARKET",
        "validity": "DAY",
        "security_id": str(security_id),
        "qty": qty,
        "is_amo": False,
        "algo_id": "99999"
    }

    try:
        r = requests.post(f"{BASE_URL}/order", headers=headers, json=payload, timeout=15)
        if r.status_code != 200:
            return None

        response = r.json()
        order_status = response.get("data", {}).get("order_status")
        if order_status in ("FAILED", "REJECTED"):
            return None

        return response.get("data", {}).get("order_id")

    except Exception as e:
        return None
 
 
  
# =========================================
# MAIN LOOP
# =========================================

print("=" * 50)
print(f"NIFTY {TRADING_MODE} TRADING BOT STARTED")
print("=" * 50)

while True:

    try:

        now = datetime.now()

        hhmm = now.strftime("%H:%M")

        if hhmm < START_TRADING_TIME:

            print(
                f"{hhmm} Waiting for market setup..."
            )

            time.sleep(60)

            continue

        if daily_points <= DAILY_STOP_RS:

            print(
                "Daily stop loss reached"
            )

            time.sleep(300)

            continue

        if hhmm >= FORCE_EXIT_TIME:

            if position_open:

                latest,\
                _,\
                _,\
                _,\
                _ = get_latest_data()

                exit_trade(
                    latest["c"],
                    "EOD"
                )

            print(
                f"Trades:{total_trades} "
                f"Wins:{wins} "
                f"Losses:{losses} "
                f"PnL:{round(daily_points,2)}"
            )

            time.sleep(300)

            continue

        # ==========================================
        # ENTRY MODE
        # ==========================================

        if not position_open:

            if total_trades >= 2:

                print("Daily trade limit reached (2 trades).")

            else:

                check_entry_signal()
                
                if position_open:
                    continue

            time.sleep(ENTRY_SCAN_INTERVAL)

        # ==========================================
        # POSITION MODE
        # ==========================================

        else:

            manage_position()

            time.sleep(POSITION_MONITOR_INTERVAL)

    except Exception as e:

        print("ERROR:", e)

        log_debug(str(e))

        time.sleep(30)
