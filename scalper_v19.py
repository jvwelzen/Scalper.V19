import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import threading
import json
import os
import atexit
from datetime import datetime
from typing import Optional
from flask import Flask, render_template_string, jsonify, request

# ═══════════════════════════════════════════════════════════════
#  SYMBOLS
# ═══════════════════════════════════════════════════════════════
SYMBOLS = [
    "EURUSD", "EURGBP", "EURCHF", "EURAUD", "EURCAD", "EURNZD", "EURJPY",
    "GBPUSD", "GBPJPY", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
    "USDJPY", "USDCAD", "USDCHF", "AUDUSD", "NZDUSD",
    "XAUUSD", "XAGUSD",
    "BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "DOGUSD", "XRPUSD", "ADAUSD", "LTCUSD", "DOTUSD",
]

MAX_SPREAD = {
    "EURUSD": 15.0, "EURGBP": 15.0, "EURCHF": 18.0, "EURAUD": 20.0,
    "EURCAD": 19.0, "EURNZD": 18.0, "EURJPY": 20.0,
    "GBPUSD": 18.0, "GBPJPY": 30.0, "GBPAUD": 22.0, "GBPCAD": 23.0,
    "GBPCHF": 13.0, "GBPNZD": 33.0,
    "USDJPY": 30.0, "USDCAD": 15.0, "USDCHF": 19.0,
    "AUDUSD": 18.0, "NZDUSD": 20.0,
    "XAUUSD": 31.0, "XAGUSD": 65.0,
    "BTCUSD": 1750.0, "ETHUSD": 260.0, "SOLUSD": 60.0, "BNBUSD": 285.0,
    "DOGUSD": 16.5,  "XRPUSD": 85.5,  "ADAUSD": 65.5, "LTCUSD": 107.0, "DOTUSD": 87.0,
}

CRYPTO_SYMBOLS  = {"BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "DOGUSD", "XRPUSD", "ADAUSD", "LTCUSD", "DOTUSD"}
METALS_SYMBOLS  = {"XAUUSD", "XAGUSD"}
_spread_warn_ts: dict = {}   # symbol → last warned datetime
_port_risk_warn_ts: Optional[datetime] = None   # last portfolio-risk warning

SYMBOL_CATEGORIES = {
    "EUR":    ["EURUSD", "EURGBP", "EURCHF", "EURAUD", "EURCAD", "EURNZD", "EURJPY"],
    "GBP":    ["GBPUSD", "GBPJPY", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "USD":    ["USDJPY", "USDCAD", "USDCHF", "AUDUSD", "NZDUSD"],
    "Metals": ["XAUUSD", "XAGUSD"],
    "Crypto": ["BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "DOGUSD", "XRPUSD", "ADAUSD", "LTCUSD", "DOTUSD"],
}
SYMBOL_CATEGORY = {s: cat for cat, syms in SYMBOL_CATEGORIES.items() for s in syms}

CATEGORY_SCORE_SCALE = {
    "EUR": 100, "GBP": 100, "USD": 100, "Metals": 10, "Crypto": 0.01,
}

# ═══════════════════════════════════════════════════════════════
#  GLOBAL CONFIG  (v14 params, unchanged)
# ═══════════════════════════════════════════════════════════════
MAGIC              = 171717
BASE_RISK_PCT      = 0.5
MAX_PORTFOLIO_RISK = 6.0
RR                 = 2.5
MAX_POS_PER_SYMBOL = 3
MIN_ENTRY_DISTANCE = 0.35
MIN_SCORE          = 0.55
TRAIL_TRIGGER_RR   = 0.6
TRAIL_STEP_POINTS  = 4
DEVIATION          = 20
UTC_TRADE_START    = 6
UTC_TRADE_END      = 17
METALS_TIME_FILTER = True   # False = metals trade 24h like crypto
ATR_SL_MULTIPLIER  = 1.5
ATR_PERIOD         = 14

# Crypto overrides
CRYPTO_RR               = 1.8
CRYPTO_ATR_SL_MULT      = 2.2
CRYPTO_TRAIL_TRIGGER_RR = 0.4
CRYPTO_MIN_SCORE        = 0.45
CRYPTO_MAX_POS          = 2

# Cooldown: seconds to block new entries after a close (TP/SL/cascade)
COOLDOWN_SECONDS = 300   # 5 minutes default

# ═══════════════════════════════════════════════════════════════
#  DEFAULTS  (source of truth for reset button)
# ═══════════════════════════════════════════════════════════════
DEFAULTS = {
    "base_risk_pct":      0.5,
    "max_portfolio_risk": 6.0,
    "rr":                 2.5,
    "max_pos":            3,
    "min_entry_dist":     0.35,
    "min_score":          0.55,
    "trail_trigger":      0.6,
    "trail_step":         4,
    "deviation":          20,
    "utc_start":          6,
    "utc_end":            17,
    "metals_time_filter": 1,
    "atr_sl_mult":        1.5,
    "crypto_rr":              1.8,
    "crypto_atr_sl_mult":     2.2,
    "crypto_trail_trigger":   0.4,
    "crypto_min_score":       0.45,
    "crypto_max_pos":         2,
    "sniper_breakout_rr":     1.2,  "sniper_breakout_atr":  0.6,  "sniper_breakout_trail":  0.40, "sniper_breakout_maxpos":  2, "sniper_breakout_score":  0.35,
    "sniper_impulse_rr":      1.3,  "sniper_impulse_atr":   0.7,  "sniper_impulse_trail":   0.35, "sniper_impulse_maxpos":   2, "sniper_impulse_score":   0.35,
    "sniper_reversion_rr":    1.1,  "sniper_reversion_atr": 0.5,  "sniper_reversion_trail": 0.30, "sniper_reversion_maxpos": 2, "sniper_reversion_score": 0.35,
    # strategy enabled flags
    "en_normal":           1,
    "en_sniper_breakout":  1,
    "en_sniper_impulse":   1,
    "en_sniper_reversion": 1,
    # cooldown
    "cooldown_seconds":    300,
}

# ═══════════════════════════════════════════════════════════════
#  SETTINGS PERSISTENCE
# ═══════════════════════════════════════════════════════════════
SETTINGS_FILE = "scalper_settings.json"

def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_settings(cfg: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[WARN] save_settings: {e}")

def apply_settings(cfg: dict) -> None:
    """Apply a settings dict to all globals. Call at startup and after reset."""
    global BASE_RISK_PCT, MAX_PORTFOLIO_RISK, RR, MAX_POS_PER_SYMBOL
    global MIN_ENTRY_DISTANCE, MIN_SCORE, TRAIL_TRIGGER_RR, TRAIL_STEP_POINTS
    global UTC_TRADE_START, UTC_TRADE_END, METALS_TIME_FILTER, DEVIATION, ATR_SL_MULTIPLIER
    global CRYPTO_RR, CRYPTO_ATR_SL_MULT, CRYPTO_TRAIL_TRIGGER_RR, CRYPTO_MIN_SCORE, CRYPTO_MAX_POS
    global COOLDOWN_SECONDS
    g = {**DEFAULTS, **cfg}
    BASE_RISK_PCT      = float(g["base_risk_pct"])
    MAX_PORTFOLIO_RISK = float(g["max_portfolio_risk"])
    RR                 = float(g["rr"])
    MAX_POS_PER_SYMBOL = int(g["max_pos"])
    MIN_ENTRY_DISTANCE = float(g["min_entry_dist"])
    MIN_SCORE          = float(g["min_score"])
    TRAIL_TRIGGER_RR   = float(g["trail_trigger"])
    TRAIL_STEP_POINTS  = int(g["trail_step"])
    DEVIATION          = int(g["deviation"])
    UTC_TRADE_START    = int(g["utc_start"])
    UTC_TRADE_END      = int(g["utc_end"])
    METALS_TIME_FILTER = bool(int(g["metals_time_filter"]))
    ATR_SL_MULTIPLIER  = float(g["atr_sl_mult"])
    CRYPTO_RR               = float(g["crypto_rr"])
    CRYPTO_ATR_SL_MULT      = float(g["crypto_atr_sl_mult"])
    CRYPTO_TRAIL_TRIGGER_RR = float(g["crypto_trail_trigger"])
    CRYPTO_MIN_SCORE        = float(g["crypto_min_score"])
    CRYPTO_MAX_POS          = int(g["crypto_max_pos"])
    COOLDOWN_SECONDS        = int(g["cooldown_seconds"])
    for sname, prefix in [("sniper_breakout","sniper_breakout"),("sniper_impulse","sniper_impulse"),("sniper_reversion","sniper_reversion")]:
        STRATEGIES[sname]["rr"]            = float(g[f"{prefix}_rr"])
        STRATEGIES[sname]["atr_sl_mult"]   = float(g[f"{prefix}_atr"])
        STRATEGIES[sname]["trail_trigger"]  = float(g[f"{prefix}_trail"])
        STRATEGIES[sname]["max_pos"]       = int(g[f"{prefix}_maxpos"])
        STRATEGIES[sname]["min_score"]     = float(g[f"{prefix}_score"])
    STRATEGIES["normal"]["rr"]            = RR
    STRATEGIES["normal"]["atr_sl_mult"]   = ATR_SL_MULTIPLIER
    STRATEGIES["normal"]["min_score"]     = MIN_SCORE
    STRATEGIES["normal"]["trail_trigger"] = TRAIL_TRIGGER_RR
    STRATEGIES["normal"]["max_pos"]       = MAX_POS_PER_SYMBOL
    for sname in ["normal","sniper_breakout","sniper_impulse","sniper_reversion"]:
        STRATEGIES[sname]["enabled"] = bool(int(g.get(f"en_{sname}", 1)))


STRATEGIES = {
    "normal": {
        "enabled":       True,
        "rr":            2.5,
        "atr_sl_mult":   1.5,
        "min_score":     0.55,
        "trail_trigger": 0.60,
        "max_pos":       3,
    },
    "sniper_breakout": {
        "enabled":       True,
        "rr":            1.2,
        "atr_sl_mult":   0.6,
        "min_score":     0.0,
        "trail_trigger": 0.40,
        "max_pos":       2,
    },
    "sniper_impulse": {
        "enabled":       True,
        "rr":            1.3,
        "atr_sl_mult":   0.7,
        "min_score":     0.0,
        "trail_trigger": 0.35,
        "max_pos":       2,
    },
    "sniper_reversion": {
        "enabled":       True,
        "rr":            1.1,
        "atr_sl_mult":   0.5,
        "min_score":     0.0,
        "trail_trigger": 0.30,
        "max_pos":       2,
    },
}

# ── Apply saved settings at startup (needs STRATEGIES to exist first) ──
apply_settings(load_settings())

# ═══════════════════════════════════════════════════════════════
#  PERSISTENT STATE
# ═══════════════════════════════════════════════════════════════
STATE_FILE      = "scalper_state.json"
LOG_FILE        = "scalper.log"
DISABLED_FILE   = "scalper_disabled.json"
SYMBOLS_FILE    = "scalper_symbols.json"
OVERRIDES_FILE  = "scalper_overrides.json"

# ── Per-symbol parameter overrides ──
# Keys: symbol string. Values: dict with any subset of:
#   atr_sl_mult, min_score, trail_trigger, rr, max_pos
# Missing keys fall through to category/global values.
SYMBOL_OVERRIDES: dict = {}

# ── Default symbol snapshot (used for reset) ──
DEFAULT_SYMBOLS = list(SYMBOLS)
DEFAULT_MAX_SPREAD = dict(MAX_SPREAD)
DEFAULT_SYMBOL_CATEGORY = dict(SYMBOL_CATEGORY)


def load_symbols() -> None:
    """Load persisted symbol list from disk and apply to globals."""
    global SYMBOLS, MAX_SPREAD, CRYPTO_SYMBOLS, METALS_SYMBOLS, SYMBOL_CATEGORY, SYMBOL_CATEGORIES
    if not os.path.exists(SYMBOLS_FILE):
        return
    try:
        with open(SYMBOLS_FILE) as f:
            data = json.load(f)
        new_syms  = data.get("symbols", [])
        new_spread = data.get("max_spread", {})
        new_cat   = data.get("symbol_category", {})
        if not new_syms:
            return
        SYMBOLS = new_syms
        for k, v in new_spread.items():
            MAX_SPREAD[k] = float(v)
        CRYPTO_SYMBOLS.clear()
        METALS_SYMBOLS.clear()
        SYMBOL_CATEGORIES.clear()
        for cat in ["EUR", "GBP", "USD", "Metals", "Crypto"]:
            SYMBOL_CATEGORIES[cat] = []
        for sym in SYMBOLS:
            cat = new_cat.get(sym, "EUR")
            SYMBOL_CATEGORY[sym] = cat
            SYMBOL_CATEGORIES.setdefault(cat, [])
            if sym not in SYMBOL_CATEGORIES[cat]:
                SYMBOL_CATEGORIES[cat].append(sym)
            if cat == "Crypto":
                CRYPTO_SYMBOLS.add(sym)
            elif cat == "Metals":
                METALS_SYMBOLS.add(sym)
    except Exception as e:
        print(f"[WARN] load_symbols: {e}")


def save_symbols() -> None:
    try:
        with open(SYMBOLS_FILE, "w") as f:
            json.dump({
                "symbols":         SYMBOLS,
                "max_spread":      MAX_SPREAD,
                "symbol_category": SYMBOL_CATEGORY,
            }, f, indent=2)
    except Exception as e:
        print(f"[WARN] save_symbols: {e}")


def reset_symbols() -> None:
    """Restore the built-in default symbol list."""
    global SYMBOLS, MAX_SPREAD, CRYPTO_SYMBOLS, METALS_SYMBOLS, SYMBOL_CATEGORY, SYMBOL_CATEGORIES
    SYMBOLS = list(DEFAULT_SYMBOLS)
    MAX_SPREAD.clear()
    MAX_SPREAD.update(DEFAULT_MAX_SPREAD)
    SYMBOL_CATEGORY.clear()
    SYMBOL_CATEGORY.update(DEFAULT_SYMBOL_CATEGORY)
    CRYPTO_SYMBOLS.clear()
    METALS_SYMBOLS.clear()
    SYMBOL_CATEGORIES.clear()
    for cat in ["EUR", "GBP", "USD", "Metals", "Crypto"]:
        SYMBOL_CATEGORIES[cat] = []
    for sym in SYMBOLS:
        cat = SYMBOL_CATEGORY.get(sym, "EUR")
        SYMBOL_CATEGORIES.setdefault(cat, [])
        if sym not in SYMBOL_CATEGORIES[cat]:
            SYMBOL_CATEGORIES[cat].append(sym)
        if cat == "Crypto":
            CRYPTO_SYMBOLS.add(sym)
        elif cat == "Metals":
            METALS_SYMBOLS.add(sym)
    try:
        os.remove(SYMBOLS_FILE)
    except Exception:
        pass


def load_overrides() -> None:
    """Load per-symbol overrides from disk into SYMBOL_OVERRIDES."""
    global SYMBOL_OVERRIDES
    if not os.path.exists(OVERRIDES_FILE):
        return
    try:
        with open(OVERRIDES_FILE) as f:
            data = json.load(f)
        SYMBOL_OVERRIDES.clear()
        SYMBOL_OVERRIDES.update(data)
    except Exception as e:
        print(f"[WARN] load_overrides: {e}")


def save_overrides() -> None:
    try:
        with open(OVERRIDES_FILE, "w") as f:
            json.dump(SYMBOL_OVERRIDES, f, indent=2)
    except Exception as e:
        print(f"[WARN] save_overrides: {e}")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                d = json.load(f)
            d.setdefault("daily", {})
            d.setdefault("session_start_balance", None)
            d.setdefault("session_start_date", None)
            d.setdefault("cumulative_pnl", 0.0)
            d.setdefault("trades_total", 0)
            return d
        except Exception:
            pass
    return {
        "daily": {}, "session_start_balance": None,
        "session_start_date": None, "cumulative_pnl": 0.0, "trades_total": 0,
    }


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[WARN] save_state: {e}")


_disabled_lock = threading.Lock()


def load_disabled() -> set:
    if os.path.exists(DISABLED_FILE):
        try:
            with open(DISABLED_FILE) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_disabled(d: set) -> None:
    try:
        with open(DISABLED_FILE, "w") as f:
            json.dump(sorted(d), f)
    except Exception as e:
        print(f"[WARN] save_disabled: {e}")


DISABLED_SYMBOLS: set = load_disabled()
load_symbols()    # apply persisted symbol list (if any) over the defaults
load_overrides()  # apply per-symbol parameter overrides

# ═══════════════════════════════════════════════════════════════
#  OVERRIDE-AWARE HELPERS
#  Priority: per-symbol override → crypto category → global
# ═══════════════════════════════════════════════════════════════
def _rr(symbol: str) -> float:
    ov = SYMBOL_OVERRIDES.get(symbol, {})
    if "rr" in ov: return float(ov["rr"])
    return CRYPTO_RR if symbol in CRYPTO_SYMBOLS else RR

def _atr_sl_mult(symbol: str) -> float:
    ov = SYMBOL_OVERRIDES.get(symbol, {})
    if "atr_sl_mult" in ov: return float(ov["atr_sl_mult"])
    return CRYPTO_ATR_SL_MULT if symbol in CRYPTO_SYMBOLS else ATR_SL_MULTIPLIER

def _trail_trigger(symbol: str) -> float:
    ov = SYMBOL_OVERRIDES.get(symbol, {})
    if "trail_trigger" in ov: return float(ov["trail_trigger"])
    return CRYPTO_TRAIL_TRIGGER_RR if symbol in CRYPTO_SYMBOLS else TRAIL_TRIGGER_RR

def _min_score(symbol: str) -> float:
    ov = SYMBOL_OVERRIDES.get(symbol, {})
    if "min_score" in ov: return float(ov["min_score"])
    return CRYPTO_MIN_SCORE if symbol in CRYPTO_SYMBOLS else MIN_SCORE

def _max_pos(symbol: str) -> int:
    ov = SYMBOL_OVERRIDES.get(symbol, {})
    if "max_pos" in ov: return int(ov["max_pos"])
    return CRYPTO_MAX_POS if symbol in CRYPTO_SYMBOLS else MAX_POS_PER_SYMBOL

# ═══════════════════════════════════════════════════════════════
#  MT5 INIT
# ═══════════════════════════════════════════════════════════════
if not mt5.initialize(
    path="C:/Program Files/MetaTrader 5/terminal64.exe",
    login=YOUR ACCOUNT NUMBER,            # ACCOUNT NUMBER
    server="VantageInternational-Demo",   # YOUR SERVER
    password="YOUR PASSWORD"              # YOUR PASSWORD
):
    raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")

for sym in SYMBOLS:
    mt5.symbol_select(sym, True)

start_balance = mt5.account_info().balance


def shutdown():
    mt5.shutdown()
    print("[SHUTDOWN] MT5 closed.")


atexit.register(shutdown)

# ═══════════════════════════════════════════════════════════════
#  THREAD LOCKS + DASHBOARD STATE
# ═══════════════════════════════════════════════════════════════
_lock         = threading.Lock()
_trades_lock  = threading.Lock()
_trades_total = 0
_cfg_lock     = threading.Lock()
BOT_PAUSED    = False

# ── Cooldown: symbol → datetime when cooldown expires ──
_cooldown_lock = threading.Lock()
_cooldown: dict = {}   # symbol → datetime


def set_cooldown(symbol: str, reason: str = "") -> None:
    """Start a cooldown for symbol. No new entries until it expires."""
    from datetime import timedelta
    until = datetime.utcnow() + timedelta(seconds=COOLDOWN_SECONDS)
    with _cooldown_lock:
        _cooldown[symbol] = until
    tag = f" [{reason}]" if reason else ""
    log(f"⏳ COOLDOWN{tag} {symbol} — no new entries for {COOLDOWN_SECONDS}s (until {until.strftime('%H:%M:%S')} UTC)")


def cooldown_remaining(symbol: str) -> float:
    """Seconds left on cooldown, or 0 if none."""
    with _cooldown_lock:
        until = _cooldown.get(symbol)
    if until is None:
        return 0.0
    secs = (until - datetime.utcnow()).total_seconds()
    return max(secs, 0.0)

app = Flask(__name__)

DASHBOARD = {
    "account":        {},
    "symbols":        [],
    "basket":         {"current": 0.0},
    "session_pnl":    0.0,
    "daily":          {},
    "log":            [],
    "started":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trades_total":   0,
    "portfolio_risk": 0.0,
    "strategies":     STRATEGIES,
    "config": {
        "rr":                 RR,
        "base_risk_pct":      BASE_RISK_PCT,
        "max_portfolio_risk": MAX_PORTFOLIO_RISK,
        "trail_trigger":      TRAIL_TRIGGER_RR,
        "trail_step":         TRAIL_STEP_POINTS,
        "max_pos":            MAX_POS_PER_SYMBOL,
        "min_entry_dist":     MIN_ENTRY_DISTANCE,
        "min_score":          MIN_SCORE,
        "magic":              MAGIC,
        "symbols_count":      len(SYMBOLS),
        "utc_start":          UTC_TRADE_START,
        "utc_end":            UTC_TRADE_END,
        "metals_time_filter": 1 if METALS_TIME_FILTER else 0,
        "deviation":          DEVIATION,
        "atr_sl_mult":        ATR_SL_MULTIPLIER,
        "crypto_rr":              CRYPTO_RR,
        "crypto_atr_sl_mult":     CRYPTO_ATR_SL_MULT,
        "crypto_trail_trigger":   CRYPTO_TRAIL_TRIGGER_RR,
        "crypto_min_score":       CRYPTO_MIN_SCORE,
        "crypto_max_pos":         CRYPTO_MAX_POS,
        # Sniper params — must be present so settings panel pre-populates correctly
        "sniper_breakout_rr":      STRATEGIES["sniper_breakout"]["rr"],
        "sniper_breakout_atr":     STRATEGIES["sniper_breakout"]["atr_sl_mult"],
        "sniper_breakout_trail":   STRATEGIES["sniper_breakout"]["trail_trigger"],
        "sniper_breakout_maxpos":  STRATEGIES["sniper_breakout"]["max_pos"],
        "sniper_breakout_score":   STRATEGIES["sniper_breakout"]["min_score"],
        "sniper_impulse_rr":       STRATEGIES["sniper_impulse"]["rr"],
        "sniper_impulse_atr":      STRATEGIES["sniper_impulse"]["atr_sl_mult"],
        "sniper_impulse_trail":    STRATEGIES["sniper_impulse"]["trail_trigger"],
        "sniper_impulse_maxpos":   STRATEGIES["sniper_impulse"]["max_pos"],
        "sniper_impulse_score":    STRATEGIES["sniper_impulse"]["min_score"],
        "sniper_reversion_rr":     STRATEGIES["sniper_reversion"]["rr"],
        "sniper_reversion_atr":    STRATEGIES["sniper_reversion"]["atr_sl_mult"],
        "sniper_reversion_trail":  STRATEGIES["sniper_reversion"]["trail_trigger"],
        "sniper_reversion_maxpos": STRATEGIES["sniper_reversion"]["max_pos"],
        "sniper_reversion_score":  STRATEGIES["sniper_reversion"]["min_score"],
    },
    "bot_paused": False,
}

# ═══════════════════════════════════════════════════════════════
#  LOGGER
# ═══════════════════════════════════════════════════════════════
def log(msg: str) -> None:
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"time": ts[11:19], "msg": msg, "full": f"[{ts}] {msg}"}
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry["full"] + "\n")
    except Exception:
        pass
    with _lock:
        DASHBOARD["log"].insert(0, entry)
        DASHBOARD["log"] = DASHBOARD["log"][:300]
    print(entry["full"])

# ═══════════════════════════════════════════════════════════════
#  DATA FETCHING  (v14: multi-timeframe)
# ═══════════════════════════════════════════════════════════════
def get_data(symbol):
    m1  = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1,  0, 200)
    m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 200)
    h1  = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1,  0, 100)
    if m1  is None or len(m1)  < 50: return None, None, None
    if m15 is None or len(m15) < 50: return None, None, None
    if h1  is None or len(h1)  < 60: return None, None, None
    return pd.DataFrame(m1), pd.DataFrame(m15), pd.DataFrame(h1)

# ═══════════════════════════════════════════════════════════════
#  FEATURE ENGINE  (v14)
# ═══════════════════════════════════════════════════════════════
def compute_features(df, category="EUR"):
    scale = CATEGORY_SCORE_SCALE.get(category, 100)
    ema9  = df['close'].ewm(span=9,  adjust=False).mean()
    ema21 = df['close'].ewm(span=21, adjust=False).mean()
    ema50 = df['close'].ewm(span=50, adjust=False).mean()
    atr   = (df['high'] - df['low']).rolling(ATR_PERIOD).mean()
    return {
        "ema9":     ema9.iloc[-1],
        "ema21":    ema21.iloc[-1],
        "ema50":    ema50.iloc[-1],
        "momentum": ema9.iloc[-1]  - ema21.iloc[-1],
        "trend":    ema21.iloc[-1] - ema50.iloc[-1],
        "pullback": abs(df['close'].iloc[-1] - ema9.iloc[-1]),
        "candle":   abs(df['close'].iloc[-1] - df['open'].iloc[-1]),
        "range":    df['high'].iloc[-1] - df['low'].iloc[-1],
        "atr":      atr.iloc[-1],
        "atr_mean": atr.mean(),
        "scale":    scale,
    }


def detect_regime(f):
    if   f["atr"] > f["atr_mean"] * 1.3: return "HIGH"
    elif f["atr"] < f["atr_mean"] * 0.7: return "LOW"
    return "NORMAL"


def composite_score(f, regime) -> float:
    scale      = f.get("scale", 100)
    s_momentum = (np.tanh(f["momentum"] * scale) + 1) / 2
    s_trend    = (np.tanh(f["trend"]    * scale) + 1) / 2
    s_pullback = 1.0 - min(f["pullback"] / (f["atr"] + 1e-9), 1.0)
    s_candle   = min(f["candle"] / (f["range"] + 1e-9), 1.0)
    raw = (s_momentum * 0.35 + s_trend * 0.25 + s_pullback * 0.20 + s_candle * 0.20)
    if   regime == "HIGH": raw = min(raw * 1.15, 1.0)
    elif regime == "LOW":  raw = raw * 0.75
    return float(np.clip(raw, 0.0, 1.0))

# ═══════════════════════════════════════════════════════════════
#  TREND + MOMENTUM  (v14)
# ═══════════════════════════════════════════════════════════════
def get_h1_trend(df_h1) -> str:
    ema50 = df_h1['close'].ewm(span=50, adjust=False).mean()
    close = df_h1['close'].iloc[-1]
    slope = ema50.iloc[-1] - ema50.iloc[-5]
    min_slope = close * 0.00005
    if close > ema50.iloc[-1] and slope >  min_slope: return "UP"
    if close < ema50.iloc[-1] and slope < -min_slope: return "DN"
    return "FLAT"


def get_momentum_dir(df) -> str:
    fast  = df['close'].ewm(span=9,  adjust=False).mean()
    slow  = df['close'].ewm(span=21, adjust=False).mean()
    f, fp, s = fast.iloc[-1], fast.iloc[-3], slow.iloc[-1]
    slope = f - fp
    thr   = df['close'].iloc[-1] * 0.0001
    dist  = abs(f - s)
    if f > s and slope >  thr and dist > thr: return "UP"
    if f < s and slope < -thr and dist > thr: return "DN"
    return "FLAT"

# ═══════════════════════════════════════════════════════════════
#  SIGNALS
#  v14 "normal" signal (multi-TF, body-filter, H1 gate) +
#  v18 sniper signals (breakout / impulse / reversion)
# ═══════════════════════════════════════════════════════════════
def normal_signal(df1, df15, df_h1, score, symbol: str) -> Optional[str]:
    """v14 high-quality multi-TF signal."""
    is_crypto = symbol in CRYPTO_SYMBOLS
    min_sc    = _min_score(symbol)
    if score < min_sc:
        return None

    mom1     = get_momentum_dir(df1)
    mom15    = get_momentum_dir(df15)
    h1_trend = get_h1_trend(df_h1)

    if is_crypto:
        if mom1 == "FLAT":
            return None
        if mom1 == "UP" and mom15 == "DN" and h1_trend != "UP":
            return None
        if mom1 == "DN" and mom15 == "UP" and h1_trend != "DN":
            return None
    else:
        if mom1 == "UP" and mom15 == "DN": return None
        if mom1 == "DN" and mom15 == "UP": return None
        if mom1 == "FLAT": return None

    if mom1 == "UP":
        if h1_trend == "DN": return None
        if h1_trend == "FLAT" and score < 0.65: return None
    if mom1 == "DN":
        if h1_trend == "UP": return None
        if h1_trend == "FLAT" and score < 0.65: return None

    prev_high  = df1['high'].iloc[-2]
    prev_low   = df1['low'].iloc[-2]
    o, c       = df1['open'].iloc[-1], df1['close'].iloc[-1]
    candle_rng = df1['high'].iloc[-1] - df1['low'].iloc[-1]
    body_pct   = abs(c - o) / (candle_rng + 1e-10)
    if body_pct < 0.55:
        return None

    if mom1 == "UP" and c > prev_high: return "BUY"
    if mom1 == "DN" and c < prev_low:  return "SELL"
    return None


def sniper_breakout_signal(df1, symbol: str = "") -> Optional[str]:
    """v18 sniper: price breaks N-bar high/low.
    Crypto uses a wider 6-bar window — volatile M1 candles make a 4-bar
    break trivial noise; requiring 6 bars filters out most false signals.
    """
    is_crypto = symbol in CRYPTO_SYMBOLS
    lookback  = 7 if is_crypto else 5   # bars to look back (iloc[-n:-1])
    high  = df1['high'].iloc[-lookback:-1].max()
    low   = df1['low'].iloc[-lookback:-1].min()
    close = df1['close'].iloc[-1]
    if close > high: return "BUY"
    if close < low:  return "SELL"
    return None


def sniper_impulse_signal(df1, symbol: str = "") -> Optional[str]:
    """v18 sniper: strong single-candle impulse (large body, direction confirmed).
    Crypto lowers the body-ratio threshold from 70% to 60%: on high-volatility
    coins, wicks are inherently larger, so a strict 70% gate would filter out
    almost every valid impulse candle.
    """
    is_crypto   = symbol in CRYPTO_SYMBOLS
    body_thresh = 0.60 if is_crypto else 0.70
    o = df1['open'].iloc[-1]
    c = df1['close'].iloc[-1]
    h = df1['high'].iloc[-1]
    l = df1['low'].iloc[-1]
    rng  = h - l
    body = abs(c - o)
    if rng < 1e-10: return None
    if body / rng < body_thresh: return None          # weak candle
    ema9  = df1['close'].ewm(span=9,  adjust=False).mean()
    ema21 = df1['close'].ewm(span=21, adjust=False).mean()
    if c > o and ema9.iloc[-1] > ema21.iloc[-1]: return "BUY"
    if c < o and ema9.iloc[-1] < ema21.iloc[-1]: return "SELL"
    return None


def sniper_reversion_signal(df1, df_h1, symbol: str = "") -> Optional[str]:
    """v18 sniper: M1 exhaustion reverting to H1 trend.
    Crypto uses a wider stretch threshold (2.0× ATR vs 1.5× for forex):
    crypto routinely oscillates 1.5× ATR intrabar without being truly
    overextended, so the tighter gate produces too many low-quality fades.
    """
    is_crypto    = symbol in CRYPTO_SYMBOLS
    atr_stretch  = 2.0 if is_crypto else 1.5
    h1 = get_h1_trend(df_h1)
    if h1 == "FLAT": return None
    ema9 = df1['close'].ewm(span=9, adjust=False).mean()
    c    = df1['close'].iloc[-1]
    atr  = (df1['high'] - df1['low']).rolling(ATR_PERIOD).mean().iloc[-1]
    dist = c - ema9.iloc[-1]
    if dist >  atr_stretch * atr and h1 == "DN": return "SELL"
    if dist < -atr_stretch * atr and h1 == "UP": return "BUY"
    return None


def _is_atr_flat(df1, symbol: str) -> bool:
    """Filter 3: ATR-based flatness guard.
    Returns True (i.e. market is too flat to trade) when the current ATR
    is below 0.03 % of price for forex/metals, or 0.05 % for crypto.
    These thresholds catch genuine sideways compression that EMA slope
    alone can miss, especially during Asian quiet hours.
    """
    atr   = (df1["high"] - df1["low"]).rolling(ATR_PERIOD).mean().iloc[-1]
    price = df1["close"].iloc[-1]
    if price < 1e-9:
        return False
    threshold = 0.0005 if symbol in CRYPTO_SYMBOLS else 0.0003
    return (atr / price) < threshold


def collect_signals(symbol, df1, df15, df_h1, score, regime="NORMAL") -> list:
    """Return signals in priority order. Execution loop fires only the first qualifying one.

    Three sideways-market guards applied to every sniper strategy:
      1. Regime filter  — snipers are suppressed when volatility is LOW.
                          A LOW regime means current ATR < 70 % of its rolling
                          mean, which is a reliable sign of a ranging, compressed
                          market where breakout / impulse signals are mostly noise.
      2. Score gate     — each sniper strategy has its own min_score (default 0.35).
                          The composite score already penalises flat momentum and
                          weak candles; requiring a non-zero floor ensures snipers
                          only fire when price structure supports the trade.
      3. ATR-flat guard — absolute safety net: if the raw ATR is below 0.03 % of
                          price (forex) or 0.05 % (crypto) the market is in tight
                          consolidation and no sniper trades are opened at all.
    """
    out = []

    # ── Normal (handles both forex and crypto via _rr/_atr_sl_mult helpers) ──
    if STRATEGIES["normal"]["enabled"]:
        sig = normal_signal(df1, df15, df_h1, score, symbol)
        if sig:
            out.append({"strategy": "normal", "direction": sig})

    # Shared sniper pre-checks (filters 1, 2, 3)
    sniper_blocked = False
    if regime == "LOW":
        sniper_blocked = True   # filter 1: LOW volatility regime
    elif _is_atr_flat(df1, symbol):
        sniper_blocked = True   # filter 3: absolute ATR flatness

    if not sniper_blocked:
        # ── Sniper Breakout ──
        if STRATEGIES["sniper_breakout"]["enabled"]:
            if score >= STRATEGIES["sniper_breakout"]["min_score"]:  # filter 2
                sig = sniper_breakout_signal(df1, symbol)
                if sig:
                    out.append({"strategy": "sniper_breakout", "direction": sig})

        # ── Sniper Impulse ──
        if STRATEGIES["sniper_impulse"]["enabled"]:
            if score >= STRATEGIES["sniper_impulse"]["min_score"]:   # filter 2
                sig = sniper_impulse_signal(df1, symbol)
                if sig:
                    out.append({"strategy": "sniper_impulse", "direction": sig})

        # ── Sniper Reversion ──
        if STRATEGIES["sniper_reversion"]["enabled"]:
            if score >= STRATEGIES["sniper_reversion"]["min_score"]: # filter 2
                sig = sniper_reversion_signal(df1, df_h1, symbol)
                if sig:
                    out.append({"strategy": "sniper_reversion", "direction": sig})

    return out

# ═══════════════════════════════════════════════════════════════
#  RISK MANAGEMENT  (v14)
# ═══════════════════════════════════════════════════════════════
def dynamic_risk_pct(balance) -> float:
    pnl = (balance - start_balance) / start_balance * 100
    if   pnl >  3: return BASE_RISK_PCT * 1.5
    elif pnl < -2: return BASE_RISK_PCT * 0.5
    return BASE_RISK_PCT


def portfolio_open_risk(positions, balance) -> float:
    total = 0.0
    for p in positions:
        info = mt5.symbol_info(p.symbol)
        if info is None:
            continue
        tick_val  = info.trade_tick_value
        tick_size = info.trade_tick_size
        if tick_size <= 0 or tick_val <= 0:
            continue
        if p.sl == 0:
            # fallback: assume 1% of notional
            total += p.price_open * p.volume * tick_val / tick_size * 0.01
            continue
        risk_dist = abs(p.price_open - p.sl)
        total += risk_dist / tick_size * tick_val * p.volume
    return (total / balance * 100) if balance > 0 else 0.0


def calc_lot(symbol, entry, sl, balance) -> float:
    info = mt5.symbol_info(symbol)
    if info is None: return 0.01
    risk_dist = abs(entry - sl)
    if risk_dist < 1e-9: return 0.01
    tick_val  = info.trade_tick_value
    tick_size = info.trade_tick_size
    if tick_size <= 0 or tick_val <= 0: return 0.01
    risk_money = balance * dynamic_risk_pct(balance) / 100
    lot  = risk_money / (risk_dist / tick_size * tick_val)
    step = info.volume_step if info.volume_step > 0 else 0.01
    lot  = round(round(lot / step) * step, 8)
    return max(info.volume_min, min(info.volume_max, lot))


def too_close(sym_pos, entry, signal, info) -> bool:
    for p in sym_pos:
        same_dir = (signal == "BUY"  and p.type == mt5.POSITION_TYPE_BUY) or \
                   (signal == "SELL" and p.type == mt5.POSITION_TYPE_SELL)
        if not same_dir: continue
        initial_risk = abs(p.price_open - p.sl)
        if initial_risk == 0: continue
        if abs(entry - p.price_open) < initial_risk * MIN_ENTRY_DISTANCE:
            return True
    return False

# ═══════════════════════════════════════════════════════════════
#  TRAILING STOP  (v14, crypto-aware trigger)
# ═══════════════════════════════════════════════════════════════
def trail_stops(positions):
    for p in positions:
        info = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        if info is None or tick is None: continue
        initial_risk = abs(p.price_open - p.sl)
        if initial_risk == 0: continue
        min_stop = max(info.trade_stops_level, info.spread) * info.point
        trig     = _trail_trigger(p.symbol)

        if p.type == mt5.POSITION_TYPE_BUY:
            if tick.bid < p.price_open + initial_risk * trig: continue
            new_sl = round(tick.bid - initial_risk, info.digits)
            new_sl = round(min(new_sl, tick.bid - min_stop), info.digits)
            if new_sl <= p.sl + TRAIL_STEP_POINTS * info.point: continue
            if new_sl <= p.sl: continue
        else:
            if tick.ask > p.price_open - initial_risk * trig: continue
            new_sl = round(tick.ask + initial_risk, info.digits)
            new_sl = round(max(new_sl, tick.ask + min_stop), info.digits)
            if new_sl >= p.sl - TRAIL_STEP_POINTS * info.point: continue
            if new_sl >= p.sl: continue

        res = mt5.order_send({
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": p.ticket,
            "symbol":   p.symbol,
            "sl":       new_sl,
            "tp":       p.tp,
            "magic":    MAGIC,
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
            log(f"📈 TRAIL {direction} {p.symbol} SL {p.sl:.5f} → {new_sl:.5f}")
        else:
            log(f"⚠ TRAIL failed {p.symbol} retcode={res.retcode if res else '?'}")

# ═══════════════════════════════════════════════════════════════
#  SL/TP BUILDER  (v14, strategy-aware RR + ATR mult)
# ═══════════════════════════════════════════════════════════════
def build_sl_tp(symbol: str, direction: str, df1, tick, info, strategy: str = "normal"):
    cfg      = STRATEGIES.get(strategy, STRATEGIES["normal"])
    atr      = (df1['high'] - df1['low']).rolling(ATR_PERIOD).mean().iloc[-1]
    min_stop = max(info.trade_stops_level, info.spread) * info.point * 1.1
    # For the normal strategy, per-symbol overrides take precedence over strategy defaults
    if strategy == "normal":
        rr       = _rr(symbol)
        atr_mult = _atr_sl_mult(symbol)
    else:
        rr       = cfg["rr"]
        atr_mult = cfg["atr_sl_mult"]

    if direction == "BUY":
        entry  = tick.ask
        sl_atr = round(entry - atr * atr_mult, info.digits)
        sl_bar = df1['low'].rolling(5).min().iloc[-2]
        sl = min(sl_atr, sl_bar) if sl_bar < entry else sl_atr
        if (entry - sl) < min_stop:
            sl = round(entry - min_stop * 1.1, info.digits)
        tp    = round(entry + (entry - sl) * rr, info.digits)
        otype = mt5.ORDER_TYPE_BUY
    else:
        entry  = tick.bid
        sl_atr = round(entry + atr * atr_mult, info.digits)
        sl_bar = df1['high'].rolling(5).max().iloc[-2]
        sl = max(sl_atr, sl_bar) if sl_bar > entry else sl_atr
        if (sl - entry) < min_stop:
            sl = round(entry + min_stop * 1.1, info.digits)
        tp    = round(entry - (sl - entry) * rr, info.digits)
        otype = mt5.ORDER_TYPE_SELL

    # validation
    if direction == "BUY":
        if sl >= entry:         return {"error": f"SL {sl:.5f} >= entry {entry:.5f}"}
        if (entry - sl) < min_stop: return {"error": f"SL dist {entry-sl:.5f} < min_stop {min_stop:.5f}"}
        if (tp - entry) < min_stop: return {"error": f"TP dist {tp-entry:.5f} < min_stop {min_stop:.5f}"}
    else:
        if sl <= entry:         return {"error": f"SL {sl:.5f} <= entry {entry:.5f}"}
        if (sl - entry) < min_stop: return {"error": f"SL dist {sl-entry:.5f} < min_stop {min_stop:.5f}"}
        if (entry - tp) < min_stop: return {"error": f"TP dist {entry-tp:.5f} < min_stop {min_stop:.5f}"}

    return {
        "error":    None,
        "entry":    entry,
        "sl":       sl,
        "tp":       tp,
        "otype":    otype,
        "atr":      round(atr, info.digits),
        "rr":       rr,
        "atr_mult": atr_mult,
    }

# ═══════════════════════════════════════════════════════════════
#  MARKET HOURS
# ═══════════════════════════════════════════════════════════════
def market_is_open(symbol) -> bool:
    if symbol in CRYPTO_SYMBOLS: return True
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or tick.bid == 0 or tick.ask == 0: return False
    if time.time() - tick.time > 300: return False
    return True

# ═══════════════════════════════════════════════════════════════
#  TRADES COUNTER
# ═══════════════════════════════════════════════════════════════
def increment_trades(state: dict) -> int:
    global _trades_total
    with _trades_lock:
        _trades_total += 1
        val = _trades_total
    state["trades_total"] = val
    save_state(state)
    with _lock:
        DASHBOARD["trades_total"] = val
    return val

# ═══════════════════════════════════════════════════════════════
#  CONFIG BUILDER  (single source for all API responses)
# ═══════════════════════════════════════════════════════════════
def _build_cfg() -> dict:
    return {
        "rr": RR, "base_risk_pct": BASE_RISK_PCT, "max_portfolio_risk": MAX_PORTFOLIO_RISK,
        "trail_trigger": TRAIL_TRIGGER_RR, "trail_step": TRAIL_STEP_POINTS,
        "max_pos": MAX_POS_PER_SYMBOL, "min_entry_dist": MIN_ENTRY_DISTANCE,
        "min_score": MIN_SCORE, "magic": MAGIC, "symbols_count": len(SYMBOLS),
        "utc_start": UTC_TRADE_START, "utc_end": UTC_TRADE_END,
        "metals_time_filter": 1 if METALS_TIME_FILTER else 0,
        "deviation": DEVIATION, "atr_sl_mult": ATR_SL_MULTIPLIER,
        "crypto_rr": CRYPTO_RR, "crypto_atr_sl_mult": CRYPTO_ATR_SL_MULT,
        "crypto_trail_trigger": CRYPTO_TRAIL_TRIGGER_RR,
        "crypto_min_score": CRYPTO_MIN_SCORE, "crypto_max_pos": CRYPTO_MAX_POS,
        "sniper_breakout_rr":      STRATEGIES["sniper_breakout"]["rr"],
        "sniper_breakout_atr":     STRATEGIES["sniper_breakout"]["atr_sl_mult"],
        "sniper_breakout_trail":   STRATEGIES["sniper_breakout"]["trail_trigger"],
        "sniper_breakout_maxpos":  STRATEGIES["sniper_breakout"]["max_pos"],
        "sniper_breakout_score":   STRATEGIES["sniper_breakout"]["min_score"],
        "sniper_impulse_rr":       STRATEGIES["sniper_impulse"]["rr"],
        "sniper_impulse_atr":      STRATEGIES["sniper_impulse"]["atr_sl_mult"],
        "sniper_impulse_trail":    STRATEGIES["sniper_impulse"]["trail_trigger"],
        "sniper_impulse_maxpos":   STRATEGIES["sniper_impulse"]["max_pos"],
        "sniper_impulse_score":    STRATEGIES["sniper_impulse"]["min_score"],
        "sniper_reversion_rr":     STRATEGIES["sniper_reversion"]["rr"],
        "sniper_reversion_atr":    STRATEGIES["sniper_reversion"]["atr_sl_mult"],
        "sniper_reversion_trail":  STRATEGIES["sniper_reversion"]["trail_trigger"],
        "sniper_reversion_maxpos": STRATEGIES["sniper_reversion"]["max_pos"],
        "sniper_reversion_score":  STRATEGIES["sniper_reversion"]["min_score"],
    }

# ═══════════════════════════════════════════════════════════════
#  HTML DASHBOARD  (v14 full dashboard + strategy panel)
# ═══════════════════════════════════════════════════════════════
HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SCALPER MERGED</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:     #080c10; --bg2: #0d1219; --bg3: #121820;
    --border: rgba(255,255,255,0.07); --border2: rgba(255,255,255,0.13);
    --text:   #e8edf2; --muted: #5a6a7a; --muted2: #3d5068;
    --accent: #00e5a0; --accent2: #0090ff;
    --red: #ff4d6a; --amber: #ffb830; --green: #00e5a0; --cyan: #00d4ff;
    --gold: #f7c75a;
    --mono: 'JetBrains Mono', monospace; --sans: 'Syne', sans-serif;
  }
  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { background: var(--bg); color: var(--text); font-family: var(--mono); font-size: 12px; height: 100%; overflow: hidden; }
  body::before { content:''; position:fixed; inset:0; background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.03) 2px,rgba(0,0,0,0.03) 4px); pointer-events:none; z-index:9999; }
  .layout { display:flex; flex-direction:column; height:100vh; overflow:hidden; }
  header { height:54px; display:flex; align-items:center; justify-content:space-between; padding:0 28px; background:var(--bg2); border-bottom:1px solid var(--border2); flex-shrink:0; }
  .logo { font-family:var(--sans); font-weight:800; font-size:18px; letter-spacing:-0.5px; display:flex; align-items:center; gap:10px; }
  .logo-dot { width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 10px var(--accent); animation:pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{opacity:1;box-shadow:0 0 10px var(--accent)} 50%{opacity:.5;box-shadow:0 0 4px var(--accent)} }
  .logo-sub { color:var(--muted); font-weight:100; margin-left:4px; }
  .logo-sub2 { color:var(--muted); font-weight:400; margin-left:4px; }
  .header-right { display:flex; gap:20px; align-items:center; font-size:11px; color:var(--muted); flex-wrap:wrap; }
  .header-right strong { color:var(--text); font-weight:500; }
  .session-chip { display:flex; align-items:center; gap:6px; padding:4px 14px; border-radius:20px; font-size:12px; font-weight:600; }
  .session-chip.pos  { background:rgba(0,229,160,0.10);  border:1px solid rgba(0,229,160,0.25);  color:var(--green); }
  .session-chip.neg  { background:rgba(255,77,106,0.10); border:1px solid rgba(255,77,106,0.25); color:var(--red); }
  .session-chip.zero { background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);color:var(--muted); }
  .chip-label { font-size:9px; letter-spacing:1.5px; text-transform:uppercase; opacity:0.7; }
  .live-pill { display:flex; align-items:center; gap:6px; background:rgba(0,229,160,0.08); border:1px solid rgba(0,229,160,0.2); border-radius:20px; padding:4px 12px; color:var(--accent); font-size:11px; font-weight:500; }
  .live-dot { width:6px; height:6px; border-radius:50%; background:var(--accent); animation:pulse 1.5s ease-in-out infinite; }
  .settings-btn { width:32px; height:32px; border-radius:4px; background:rgba(255,255,255,0.05); border:1px solid var(--border2); color:var(--muted); cursor:pointer; display:flex; align-items:center; justify-content:center; font-size:16px; transition:all .2s; flex-shrink:0; }
  .settings-btn:hover { background:rgba(255,255,255,0.10); color:var(--text); transform:rotate(45deg); }
  .paused-banner { display:none; position:fixed; top:54px; left:0; right:0; z-index:200; background:rgba(255,184,48,0.12); border-bottom:1px solid rgba(255,184,48,0.3); text-align:center; padding:6px; font-size:11px; font-weight:600; letter-spacing:2px; color:var(--amber); }
  .paused-banner.visible { display:block; }
  /* KPIs */
  .kpi-row { display:grid; grid-template-columns:repeat(6,1fr); gap:1px; background:var(--border); flex-shrink:0; }
  .kpi { background:var(--bg2); padding:14px 20px; position:relative; overflow:hidden; }
  .kpi::after { content:''; position:absolute; top:0; left:0; width:3px; height:100%; background:var(--kpi-color,var(--accent)); }
  .kpi-label { font-size:9px; font-weight:500; letter-spacing:2px; text-transform:uppercase; color:var(--muted); margin-bottom:5px; }
  .kpi-value { font-family:var(--sans); font-size:18px; font-weight:700; color:var(--text); line-height:1; }
  .kpi-value.pos{color:var(--green)} .kpi-value.neg{color:var(--red)} .kpi-value.cyan{color:var(--cyan)} .kpi-value.amber{color:var(--amber)}
  .kpi-sub { font-size:9px; color:var(--muted); margin-top:4px; }
  /* Layout */
  .main { display:grid; grid-template-columns:1fr 310px; gap:1px; background:var(--border); flex:1; min-height:0; overflow:hidden; }
  /* Table */
  .table-panel { background:var(--bg2); display:flex; flex-direction:column; min-height:0; overflow:hidden; }
  .panel-header { padding:10px 20px; background:var(--bg3); border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; flex-shrink:0; }
  .panel-title { font-family:var(--sans); font-size:10px; font-weight:600; letter-spacing:2px; text-transform:uppercase; color:var(--muted); }
  .panel-count { color:var(--cyan); font-family:var(--sans); font-size:14px; font-weight:700; }
  .table-scroll { flex:1; overflow-y:auto; overflow-x:auto; min-height:0; }
  .table-scroll::-webkit-scrollbar{width:5px;height:5px} .table-scroll::-webkit-scrollbar-track{background:var(--bg3)} .table-scroll::-webkit-scrollbar-thumb{background:rgba(0,229,160,0.35);border-radius:3px} .table-scroll::-webkit-scrollbar-thumb:hover{background:rgba(0,229,160,0.65)}
  table { width:100%; border-collapse:collapse; min-width:760px; }
  thead th { padding:8px 10px; font-size:9px; letter-spacing:1.5px; text-transform:uppercase; color:var(--muted); font-weight:500; border-bottom:1px solid var(--border2); background:var(--bg2); position:sticky; top:0; z-index:5; text-align:left; white-space:nowrap; }
  thead th:not(:first-child){text-align:right} thead th.center{text-align:center}
  tbody tr { border-bottom:1px solid rgba(255,255,255,0.03); transition:background .12s; }
  tbody tr:hover{background:rgba(255,255,255,0.025)}
  tbody tr.row-active{background:rgba(0,229,160,0.03)} tbody tr.row-disabled{opacity:.28} tbody tr.row-closed{opacity:.38}
  tbody td { padding:7px 10px; vertical-align:middle; white-space:nowrap; }
  tbody td:not(:first-child){text-align:right} tbody td.center{text-align:center}
  .sym-name{font-weight:600;font-size:12px;letter-spacing:0.5px;cursor:pointer}
  .sym-name.is-crypto{color:var(--gold)}
  .crypto-badge{display:inline-block;font-size:7px;letter-spacing:1px;padding:1px 4px;border-radius:2px;background:rgba(247,199,90,0.10);border:1px solid rgba(247,199,90,0.22);color:var(--gold);margin-left:4px;vertical-align:middle;font-weight:700}
  .score-pill{display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600}
  .sp-high{background:rgba(0,229,160,0.12);color:var(--green);border:1px solid rgba(0,229,160,0.25)}
  .sp-mid{background:rgba(255,184,48,0.10);color:var(--amber);border:1px solid rgba(255,184,48,0.25)}
  .sp-low{background:rgba(255,255,255,0.04);color:var(--muted);border:1px solid var(--border)}
  .trend-up{color:var(--green)} .trend-dn{color:var(--red)} .trend-flat{color:var(--muted)}
  .h1-badge{display:inline-flex;align-items:center;padding:1px 5px;border-radius:2px;font-size:9px;font-weight:700;letter-spacing:1px}
  .h1-up{background:rgba(0,229,160,0.10);color:var(--green);border:1px solid rgba(0,229,160,0.20)}
  .h1-dn{background:rgba(255,77,106,0.10);color:var(--red);border:1px solid rgba(255,77,106,0.20)}
  .h1-flat{background:rgba(255,255,255,0.04);color:var(--muted);border:1px solid var(--border)}
  .signal-badge{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600;letter-spacing:1px}
  .sig-buy{background:rgba(0,229,160,0.12);color:var(--green);border:1px solid rgba(0,229,160,0.25)}
  .sig-sell{background:rgba(255,77,106,0.12);color:var(--red);border:1px solid rgba(255,77,106,0.25)}
  .sig-none{color:var(--muted)}
  .strat-tags{display:flex;gap:3px;justify-content:flex-end;flex-wrap:wrap}
  .strat-tag{font-size:7px;letter-spacing:0.8px;padding:1px 5px;border-radius:2px;font-weight:700;text-transform:uppercase}
  .st-normal{background:rgba(0,144,255,0.12);color:var(--accent2);border:1px solid rgba(0,144,255,0.25)}
  .st-sniper{background:rgba(255,184,48,0.10);color:var(--amber);border:1px solid rgba(255,184,48,0.25)}
  .st-crypto{background:rgba(247,199,90,0.10);color:var(--gold);border:1px solid rgba(247,199,90,0.22)}
  .regime-tag{font-size:8px;letter-spacing:1.5px;padding:1px 5px;border-radius:2px}
  .rg-high{background:rgba(255,184,48,0.1);color:var(--amber)} .rg-low{background:rgba(0,144,255,0.1);color:var(--accent2)} .rg-norm{background:rgba(255,255,255,0.04);color:var(--muted)}
  .bar-wrap{display:flex;align-items:center;gap:5px;justify-content:flex-end}
  .bar-track{width:40px;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden}
  .bar-fill{height:100%;border-radius:2px;transition:width .4s}
  .spread-ok{color:var(--muted)} .spread-warn{color:var(--amber)}
  .pnl-pos{color:var(--green)} .pnl-neg{color:var(--red)} .pnl-zero{color:var(--muted)}
  .trade-btn{display:inline-flex;align-items:center;justify-content:center;height:20px;padding:0 8px;border-radius:3px;font-size:8px;font-weight:700;letter-spacing:1.5px;cursor:pointer;border:1px solid;transition:all .18s;user-select:none;font-family:var(--mono)}
  .trade-btn.buy{background:rgba(0,229,160,0.08);border-color:rgba(0,229,160,0.30);color:var(--green)}
  .trade-btn.buy:hover{background:rgba(0,229,160,0.22);border-color:rgba(0,229,160,0.5)}
  .trade-btn.sell{background:rgba(255,77,106,0.08);border-color:rgba(255,77,106,0.30);color:var(--red)}
  .trade-btn.sell:hover{background:rgba(255,77,106,0.22);border-color:rgba(255,77,106,0.5)}
  .trade-btn:disabled{opacity:.28;pointer-events:none}
  .close-btn{display:inline-flex;align-items:center;justify-content:center;height:20px;padding:0 8px;border-radius:3px;font-size:8px;font-weight:700;letter-spacing:1.5px;cursor:pointer;border:1px solid rgba(255,184,48,0.30);background:rgba(255,184,48,0.07);color:var(--amber);transition:all .18s;user-select:none;font-family:var(--mono);white-space:nowrap}
  .close-btn:hover{background:rgba(255,184,48,0.20);border-color:rgba(255,184,48,0.55);color:#ffd060}
  .close-btn:disabled,.close-btn.no-pos{opacity:.18;pointer-events:none;border-color:rgba(255,255,255,0.08);background:transparent;color:var(--muted2)}
  .toggle-btn{display:inline-flex;align-items:center;justify-content:center;width:46px;height:20px;border-radius:3px;font-size:8px;font-weight:600;letter-spacing:1.5px;cursor:pointer;border:1px solid;transition:all .18s;user-select:none}
  .toggle-btn.enabled{background:rgba(0,229,160,0.08);border-color:rgba(0,229,160,0.25);color:var(--green)}
  .toggle-btn.disabled{background:rgba(255,77,106,0.08);border-color:rgba(255,77,106,0.22);color:var(--red)}
  .toggle-btn.pending{opacity:.4;pointer-events:none}
  /* Category tabs */
  .cat-tabs{display:flex;gap:2px;padding:6px 14px;background:var(--bg3);border-bottom:1px solid var(--border);flex-shrink:0;flex-wrap:wrap}
  .cat-tab{height:22px;padding:0 10px;border-radius:3px;font-size:9px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;border:1px solid var(--border2);background:rgba(255,255,255,0.03);color:var(--muted);font-family:var(--mono);transition:all .15s}
  .cat-tab:hover{background:rgba(255,255,255,0.07);color:var(--text)}
  .cat-tab.active{background:rgba(0,229,160,0.12);border-color:rgba(0,229,160,0.35);color:var(--green)}
  .cat-tab.crypto-tab.active{background:rgba(247,199,90,0.12);border-color:rgba(247,199,90,0.35);color:var(--gold)}
  .cat-tab .ct-count{margin-left:5px;opacity:.55;font-size:8px}
  .cat-row td{padding:4px 10px 3px;font-size:8px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--muted2);background:var(--bg3);border-bottom:1px solid var(--border);text-align:left!important}
  .cat-row.crypto-cat td{color:rgba(247,199,90,0.45)}
  /* Right panel */
  .right-panel{background:var(--bg2);display:flex;flex-direction:column;overflow:hidden;min-height:0}
  .risk-section{padding:14px 16px;border-bottom:1px solid var(--border);flex-shrink:0}
  .risk-header{display:flex;justify-content:space-between;font-size:9px;letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;margin-bottom:8px}
  .risk-header span:last-child{font-family:var(--sans);font-size:14px;font-weight:700;color:var(--text);letter-spacing:0}
  .risk-track{height:5px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;margin-bottom:4px}
  .risk-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--green),var(--amber) 60%,var(--red));transition:width .5s}
  .risk-marks{display:flex;justify-content:space-between;font-size:8px;color:var(--muted)}
  .daily-section{padding:12px 16px;border-bottom:1px solid var(--border);flex-shrink:0}
  .section-title{font-family:var(--sans);font-size:9px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:10px}
  .daily-row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:11px}
  .daily-row:last-child{border:none}
  .daily-date{color:var(--muted);font-size:10px}
  .log-section{flex:1;overflow:hidden;display:flex;flex-direction:column;min-height:0}
  .log-header{padding:9px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
  .log-entries{flex:1;overflow-y:auto;min-height:0}
  .log-entries::-webkit-scrollbar{width:4px} .log-entries::-webkit-scrollbar-track{background:var(--bg3)} .log-entries::-webkit-scrollbar-thumb{background:rgba(0,212,255,0.35);border-radius:2px} .log-entries::-webkit-scrollbar-thumb:hover{background:rgba(0,212,255,0.65)}
  .log-entry{display:grid;grid-template-columns:52px 1fr;gap:6px;padding:5px 16px;border-bottom:1px solid rgba(255,255,255,0.025);font-size:10px;animation:slideIn .2s ease}
  @keyframes slideIn{from{opacity:0;transform:translateX(6px)}to{opacity:1}}
  .log-t{color:var(--muted);font-size:9px;padding-top:1px}
  .log-m{color:var(--muted);line-height:1.4;word-break:break-word}
  .log-m.ok{color:var(--green)} .log-m.err{color:var(--red)} .log-m.warn{color:var(--amber)}
  .log-m.trail{color:var(--accent2)} .log-m.info{color:var(--cyan)} .log-m.manual{color:var(--cyan);font-weight:600} .log-m.close{color:var(--amber);font-weight:600}
  /* Settings / Chart / Modals */
  .settings-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:800;align-items:flex-start;justify-content:center;backdrop-filter:blur(3px);padding:40px 16px 16px;overflow-y:auto}
  .settings-overlay.open{display:flex}
  .settings-modal{background:var(--bg2);border:1px solid var(--border2);border-radius:4px;width:760px;max-width:calc(100vw - 32px);max-height:calc(100vh - 56px);display:flex;flex-direction:column;box-shadow:0 24px 80px rgba(0,0,0,0.8);overflow:hidden;flex-shrink:0}
  .settings-cols{display:grid;grid-template-columns:1fr 1fr;gap:0;flex:1;overflow:hidden;min-height:0}
  .settings-col{overflow-y:auto;padding:10px 12px}
  .settings-col::-webkit-scrollbar{width:4px} .settings-col::-webkit-scrollbar-track{background:var(--bg3)} .settings-col::-webkit-scrollbar-thumb{background:rgba(0,229,160,0.30);border-radius:2px} .settings-col::-webkit-scrollbar-thumb:hover{background:rgba(0,229,160,0.60)}
  .sm-table-scroll::-webkit-scrollbar{width:4px} .sm-table-scroll::-webkit-scrollbar-track{background:var(--bg3)} .sm-table-scroll::-webkit-scrollbar-thumb{background:rgba(255,184,48,0.35);border-radius:2px} .sm-table-scroll::-webkit-scrollbar-thumb:hover{background:rgba(255,184,48,0.65)}
  .settings-col+.settings-col{border-left:1px solid var(--border);background:var(--bg2);display:flex;flex-direction:column;overflow:hidden;padding:0;min-width:0}
  .sm-col-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
  .sm-col-title{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--cyan)}
  .sm-add-grid{display:grid;grid-template-columns:1fr 88px 64px 52px;gap:5px;align-items:end;margin-bottom:5px}
  @media(max-width:860px){
    .settings-overlay{padding:8px;align-items:flex-start;justify-content:center}
    .settings-modal{width:100%;max-width:100%;max-height:calc(100vh - 16px);border-radius:4px}
    .settings-cols{grid-template-columns:1fr;grid-template-rows:auto auto;overflow-y:auto;overflow-x:hidden}
    .settings-col{overflow-y:visible;max-height:none}
    .settings-col+.settings-col{border-left:none;border-top:1px solid var(--border);min-height:340px;overflow:hidden}
    .sm-add-grid{grid-template-columns:1fr 90px 68px 52px;gap:4px}
    .sm-table-scroll{overflow-x:auto!important;overflow-y:auto!important}
  }
  .sm-field-label{font-size:9px;color:var(--muted);margin-bottom:3px;letter-spacing:1px;text-transform:uppercase}
  .settings-head{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--border);flex-shrink:0}
  .settings-head h2{font-family:var(--sans);font-size:13px;font-weight:700}
  .settings-body{flex:1;overflow-y:auto;padding:12px 14px}
  .settings-body::-webkit-scrollbar{width:4px} .settings-body::-webkit-scrollbar-track{background:var(--bg3)} .settings-body::-webkit-scrollbar-thumb{background:rgba(0,229,160,0.30);border-radius:2px} .settings-body::-webkit-scrollbar-thumb:hover{background:rgba(0,229,160,0.60)}
  .settings-section{margin-bottom:14px}
  .settings-section-title{font-size:8px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:7px;padding-bottom:4px;border-bottom:1px solid var(--border)}
  .settings-section-title.crypto-title{color:var(--gold);border-bottom-color:rgba(247,199,90,0.3)}
  .settings-section-title.sniper-title{color:var(--amber);border-bottom-color:rgba(255,184,48,0.3)}
  .settings-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;gap:8px}
  .settings-label{font-size:10px;color:var(--muted);flex:1;white-space:nowrap}
  .settings-label small{display:block;font-size:8px;color:var(--muted2);margin-top:1px}
  .settings-input{width:76px;height:22px;background:var(--bg3);border:1px solid var(--border2);border-radius:3px;color:var(--text);font-family:var(--mono);font-size:11px;font-weight:500;text-align:right;padding:0 6px;transition:border-color .15s}
  .settings-input:focus{outline:none;border-color:var(--accent)}
  .settings-input.changed{border-color:var(--amber);color:var(--amber)}
  .settings-input.crypto-input{border-color:rgba(247,199,90,0.28)}
  .settings-input.crypto-input:focus{border-color:var(--gold)}
  .settings-input.sniper-input{border-color:rgba(255,184,48,0.28)}
  .settings-input.sniper-input:focus{border-color:var(--amber)}
  .server-toggle-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);margin-bottom:12px}
  .server-toggle-label{font-family:var(--sans);font-size:11px;font-weight:600}
  .server-toggle-btn{height:26px;padding:0 12px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:1.5px;cursor:pointer;border:1px solid;font-family:var(--mono);transition:all .18s;min-width:80px}
  .server-toggle-btn.running{background:rgba(0,229,160,0.08);border-color:rgba(0,229,160,0.3);color:var(--green)}
  .server-toggle-btn.paused{background:rgba(255,184,48,0.10);border-color:rgba(255,184,48,0.35);color:var(--amber)}
  .settings-footer{padding:8px 14px;border-top:1px solid var(--border);display:flex;gap:8px;flex-shrink:0}
  .settings-save-btn{flex:1;height:28px;border-radius:3px;font-size:10px;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid;font-family:var(--mono);background:rgba(0,229,160,0.10);border-color:rgba(0,229,160,0.30);color:var(--green)}
  .settings-save-btn:hover{background:rgba(0,229,160,0.22)} .settings-save-btn:disabled{opacity:.4;pointer-events:none}
  .settings-cancel-btn{height:28px;padding:0 14px;border-radius:3px;font-size:10px;font-weight:600;letter-spacing:1px;cursor:pointer;border:1px solid var(--border);font-family:var(--mono);color:var(--muted);background:rgba(255,255,255,0.03);transition:all .18s}
  .settings-cancel-btn:hover{background:rgba(255,255,255,0.07);color:var(--text)}
  .info-ic{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);color:var(--muted2);font-size:8px;font-style:normal;cursor:default;margin-left:5px;flex-shrink:0;transition:all .15s;user-select:none;font-family:serif;line-height:1}
  .info-ic:hover{background:rgba(0,212,255,0.12);border-color:rgba(0,212,255,0.35);color:var(--cyan)}
  #s-tooltip{position:fixed;z-index:2000;max-width:230px;background:#1a2332;border:1px solid rgba(0,212,255,0.25);border-radius:4px;padding:8px 11px;font-size:10px;color:var(--text);line-height:1.5;pointer-events:none;opacity:0;transition:opacity .15s;box-shadow:0 8px 32px rgba(0,0,0,0.6);font-family:var(--mono)}
  .strat-toggle{font-size:9px;font-weight:700;letter-spacing:1px;padding:3px 12px;border-radius:2px;cursor:pointer;border:1px solid;font-family:var(--mono);transition:all .15s;min-width:46px}
  .strat-toggle.on{background:rgba(0,229,160,0.08);border-color:rgba(0,229,160,0.25);color:var(--green)}
  .strat-toggle.off{background:rgba(255,77,106,0.08);border-color:rgba(255,77,106,0.22);color:var(--red)}
  .chart-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.72);z-index:500;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
  .chart-overlay.open{display:flex}
  .chart-modal{background:var(--bg2);border:1px solid var(--border2);border-radius:4px;width:820px;max-width:95vw;box-shadow:0 24px 80px rgba(0,0,0,0.7);animation:modalIn .18s ease}
  @keyframes modalIn{from{opacity:0;transform:scale(0.96) translateY(8px)}to{opacity:1;transform:scale(1) translateY(0)}}
  .chart-modal-header{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--border)}
  .chart-modal-title{font-family:var(--sans);font-size:16px;font-weight:700;display:flex;align-items:center;gap:10px}
  .chart-modal-sub{font-size:10px;letter-spacing:2px;color:var(--muted);font-family:var(--mono);font-weight:400}
  .chart-close{width:28px;height:28px;border-radius:3px;background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--muted);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:16px;transition:all .15s}
  .chart-close:hover{background:rgba(255,61,90,0.15);color:var(--red);border-color:rgba(255,61,90,0.3)}
  .chart-body{padding:16px 20px 20px}
  .chart-loading{display:flex;align-items:center;justify-content:center;height:320px;color:var(--muted);font-size:11px;letter-spacing:2px;border:1px solid var(--border);border-radius:3px;background:var(--bg)}
  .chart-loading-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);margin-right:10px;animation:pulse 1s ease-in-out infinite}
  .close-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.72);z-index:700;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
  .close-overlay.open{display:flex}
  .close-modal{background:var(--bg2);border:1px solid rgba(255,184,48,0.25);border-radius:4px;width:360px;padding:26px;box-shadow:0 24px 80px rgba(0,0,0,0.7);animation:modalIn .18s ease}
  .close-modal h3{font-family:var(--sans);font-size:16px;font-weight:700;margin-bottom:12px;color:var(--amber);display:flex;align-items:center;gap:8px}
  .close-modal p{font-size:11px;color:var(--muted);line-height:1.6;margin-bottom:6px}
  .close-modal-actions{display:flex;gap:10px;margin-top:20px}
  .trade-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.72);z-index:600;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
  .trade-overlay.open{display:flex}
  .trade-modal{background:var(--bg2);border:1px solid var(--border2);border-radius:4px;width:390px;padding:26px;box-shadow:0 24px 80px rgba(0,0,0,0.7);animation:modalIn .18s ease}
  .trade-modal h3{font-family:var(--sans);font-size:17px;font-weight:700;margin-bottom:18px;display:flex;align-items:center;gap:8px}
  .trade-detail-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;font-size:11px;border-bottom:1px solid rgba(255,255,255,0.04)}
  .trade-detail-row:last-of-type{border:none}
  .trade-detail-row .lbl{color:var(--muted);letter-spacing:1.5px;font-size:9px;text-transform:uppercase}
  .trade-detail-row .val{font-weight:600;font-family:var(--mono)}
  .trade-note{font-size:9px;color:var(--muted);margin-top:14px;line-height:1.6;padding:10px 12px;background:rgba(255,255,255,0.025);border-radius:3px;border-left:2px solid var(--border2)}
  .trade-note.crypto-note{border-left-color:rgba(247,199,90,0.4);background:rgba(247,199,90,0.04)}
  .trade-actions{display:flex;gap:10px;margin-top:18px}
  .trade-confirm-btn{flex:1;height:38px;border-radius:3px;font-size:11px;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid;font-family:var(--mono);transition:all .18s}
  .trade-confirm-btn.go-buy{background:rgba(0,229,160,0.12);border-color:rgba(0,229,160,0.35);color:var(--green)}
  .trade-confirm-btn.go-buy:hover{background:rgba(0,229,160,0.25)}
  .trade-confirm-btn.go-sell{background:rgba(255,77,106,0.12);border-color:rgba(255,77,106,0.35);color:var(--red)}
  .trade-confirm-btn.go-sell:hover{background:rgba(255,77,106,0.25)}
  .trade-confirm-btn.go-close{background:rgba(255,184,48,0.10);border-color:rgba(255,184,48,0.35);color:var(--amber)}
  .trade-confirm-btn.cancel{background:rgba(255,255,255,0.04);border-color:var(--border);color:var(--muted)}
  .trade-confirm-btn.cancel:hover{background:rgba(255,255,255,0.08);color:var(--text)}
  .trade-confirm-btn:disabled{opacity:.4;pointer-events:none}
  .tf-btn{height:22px;padding:0 8px;border-radius:3px;font-size:9px;font-weight:600;letter-spacing:1px;cursor:pointer;border:1px solid var(--border2);background:rgba(255,255,255,0.03);color:var(--muted);font-family:var(--mono);transition:all .15s}
  .tf-btn:hover{background:rgba(255,255,255,0.08);color:var(--text)}
  .tf-btn.active{background:rgba(0,229,160,0.12);border-color:rgba(0,229,160,0.35);color:var(--green)}
  /* Trades popup */
  .trades-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.78);z-index:900;align-items:flex-start;justify-content:center;backdrop-filter:blur(3px);padding:40px 16px 16px;overflow-y:auto}
  .trades-overlay.open{display:flex}
  .trades-modal{background:var(--bg2);border:1px solid var(--border2);border-radius:4px;width:980px;max-width:calc(100vw - 32px);max-height:calc(100vh - 56px);display:flex;flex-direction:column;box-shadow:0 24px 80px rgba(0,0,0,0.85);overflow:hidden;flex-shrink:0;animation:modalIn .18s ease}
  .trades-modal-head{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--border2);flex-shrink:0}
  .trades-modal-title{font-family:var(--sans);font-size:15px;font-weight:700;display:flex;align-items:center;gap:12px}
  .trades-tabs{display:flex;gap:6px}
  .trades-tab{height:26px;padding:0 14px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;border:1px solid var(--border2);background:rgba(255,255,255,0.03);color:var(--muted);font-family:var(--mono);transition:all .15s}
  .trades-tab:hover{background:rgba(255,255,255,0.07);color:var(--text)}
  .trades-tab.active{background:rgba(0,229,160,0.12);border-color:rgba(0,229,160,0.35);color:var(--green)}
  .trades-tab.hist-tab.active{background:rgba(0,144,255,0.12);border-color:rgba(0,144,255,0.35);color:var(--accent2)}
  .trades-body{flex:1;overflow:hidden;display:flex;flex-direction:column;min-height:0}
  .trades-pane{display:none;flex:1;overflow:auto;min-height:0}
  .trades-pane.active{display:flex;flex-direction:column}
  .trades-pane::-webkit-scrollbar,.trades-pane>div::-webkit-scrollbar{width:6px;height:6px}
  .trades-pane::-webkit-scrollbar-track,.trades-pane>div::-webkit-scrollbar-track{background:var(--bg3)}
  .trades-pane::-webkit-scrollbar-thumb,.trades-pane>div::-webkit-scrollbar-thumb{background:rgba(0,144,255,0.65);border-radius:3px}
  .trades-pane::-webkit-scrollbar-thumb:hover,.trades-pane>div::-webkit-scrollbar-thumb:hover{background:rgba(0,144,255,0.90)}
  .trades-table{width:100%;border-collapse:collapse;min-width:860px}
  .trades-table thead th{padding:8px 12px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border2);background:var(--bg3);position:sticky;top:0;z-index:5;text-align:left;white-space:nowrap}
  .trades-table thead th:not(:first-child){text-align:right}
  .trades-table tbody tr{border-bottom:1px solid rgba(255,255,255,0.03);transition:background .12s}
  .trades-table tbody tr:hover{background:rgba(255,255,255,0.025)}
  .trades-table tbody td{padding:7px 12px;vertical-align:middle;white-space:nowrap;font-size:11px}
  .trades-table tbody td:not(:first-child){text-align:right}
  .trades-empty{display:flex;align-items:center;justify-content:center;flex:1;color:var(--muted);font-size:11px;letter-spacing:2px;padding:60px}
  .trades-summary{display:flex;gap:20px;padding:10px 20px;background:var(--bg3);border-top:1px solid var(--border);font-size:10px;flex-shrink:0}
  .trades-summary-item{display:flex;flex-direction:column;gap:2px}
  .trades-summary-label{font-size:8px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted)}
  .trades-summary-value{font-family:var(--sans);font-size:13px;font-weight:700}
  .t-buy{color:var(--green)}.t-sell{color:var(--red)}.t-pos{color:var(--green)}.t-neg{color:var(--red)}.t-zero{color:var(--muted)}
  .trades-refresh{height:22px;padding:0 10px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid rgba(0,229,160,0.3);background:rgba(0,229,160,0.07);color:var(--green);font-family:var(--mono);transition:all .15s}
  .trades-refresh:hover{background:rgba(0,229,160,0.18)}
  .hist-filter{display:flex;gap:8px;padding:8px 16px;background:var(--bg3);border-bottom:1px solid var(--border);align-items:center;flex-shrink:0}
  .hist-filter-btn{height:22px;padding:0 10px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid var(--border2);background:rgba(255,255,255,0.03);color:var(--muted);font-family:var(--mono);transition:all .15s}
  .hist-filter-btn.active{background:rgba(0,144,255,0.12);border-color:rgba(0,144,255,0.35);color:var(--accent2)}
  .hist-filter-btn:hover{background:rgba(255,255,255,0.08);color:var(--text)}
</style>
</head>
<body>
<div class="layout">

  <header>
    <div class="logo"><div class="logo-dot"></div>SCALPER .v20<span class="logo-sub">MERGED <span class="logo-sub2">.build 11</span></span></div>
    <div class="header-right">
      <span>MAGIC <strong>171717</strong></span>
      <span>STARTED <strong id="h-started">—</strong></span>
      <span>TRADES <strong id="h-trades">0</strong></span>
      <span>START <strong id="g-balance">—</strong></span>
      <div class="live-pill" id="live-pill"><div class="live-dot" id="live-dot"></div><span id="live-label">LIVE</span></div>
      <button class="settings-btn" onclick="openTrades()" title="Trades" style="font-size:11px;font-weight:700;letter-spacing:1px;font-family:var(--mono);width:auto;padding:0 10px">TRADES</button>
      <button class="settings-btn" onclick="openSettings()" title="Settings">&#9881;</button>
    </div>
  </header>

  <div class="kpi-row">
    <div class="kpi" style="--kpi-color:var(--accent2)"><div class="kpi-label">Balance</div><div class="kpi-value cyan" id="k-balance">—</div><div class="kpi-sub">account</div></div>
    <div class="kpi" style="--kpi-color:var(--accent)"><div class="kpi-label">Equity</div><div class="kpi-value" id="k-equity">—</div><div class="kpi-sub" id="k-equity-sub">—</div></div>
    <div class="kpi" style="--kpi-color:var(--green);position:relative"><div class="kpi-label">Open P&amp;L</div><div class="kpi-value" id="k-openpl">—</div><button id="close-all-btn" onclick="closeAll()" title="Close all open positions" style="position:absolute;bottom:10px;right:12px;padding:2px 9px;font-size:8px;font-weight:700;letter-spacing:1px;background:rgba(255,184,48,0.07);color:var(--amber);border:1px solid rgba(255,184,48,0.30);border-radius:3px;cursor:pointer;font-family:var(--mono);transition:all .18s" onmouseover="this.style.background='rgba(255,184,48,0.20)';this.style.borderColor='rgba(255,184,48,0.55)'" onmouseout="this.style.background='rgba(255,184,48,0.07)';this.style.borderColor='rgba(255,184,48,0.30)'">EMPTY BASKET</button></div>
    <div class="kpi" style="--kpi-color:var(--cyan)"><div class="kpi-label">Session P&amp;L</div><div class="kpi-value" id="k-session">—</div><div class="kpi-sub">today</div></div>
    <div class="kpi"><div class="kpi-label">Positions</div><div class="kpi-value" id="k-pos">0</div><div class="kpi-sub" id="k-syms">0 symbols</div></div>
    <div class="kpi" style="--kpi-color:var(--amber)"><div class="kpi-label">Port. Risk</div><div class="kpi-value" id="k-risk">0%</div><div class="kpi-sub">of balance</div></div>
  </div>

  <div class="main">
    <div class="table-panel">
      <div class="panel-header">
        <span class="panel-title">Market Scanner</span>
        <span id="cfg-strip" style="font-size:9px;color:var(--muted);letter-spacing:1px">—</span>
        <span class="panel-count" id="sym-count">0</span>
      </div>
      <div class="cat-tabs">
        <button class="cat-tab active" data-cat="ALL"    onclick="filterCat('ALL')">ALL <span class="ct-count" id="ct-ALL">0</span></button>
        <button class="cat-tab" data-cat="EUR"           onclick="filterCat('EUR')">EUR <span class="ct-count" id="ct-EUR">7</span></button>
        <button class="cat-tab" data-cat="GBP"           onclick="filterCat('GBP')">GBP <span class="ct-count" id="ct-GBP">6</span></button>
        <button class="cat-tab" data-cat="USD"           onclick="filterCat('USD')">USD <span class="ct-count" id="ct-USD">5</span></button>
        <button class="cat-tab" data-cat="Metals"        onclick="filterCat('Metals')">Metals <span class="ct-count" id="ct-Metals">2</span></button>
        <button class="cat-tab crypto-tab" data-cat="Crypto" onclick="filterCat('Crypto')">₿ Crypto <span class="ct-count" id="ct-Crypto">9</span></button>
      </div>
      <div class="table-scroll">
        <table>
          <thead><tr>
            <th>Symbol</th><th>Score / Strength</th><th class="center">M1/M15/H1</th>
            <th>Regime</th><th>Spread</th>
            <th>P&amp;L · Pos</th><th class="center">Active</th>
            <th class="center">Trade</th><th class="center">Close</th>
          </tr></thead>
          <tbody id="sym-tbody"><tr><td colspan="9" style="text-align:center;padding:40px;color:var(--muted)">Connecting…</td></tr></tbody>
        </table>
      </div>
    </div>

    <div class="right-panel">
      <div class="risk-section">
        <div class="risk-header"><span>Portfolio Risk</span><span id="r-risk-val">0.00%</span></div>
        <div class="risk-track"><div class="risk-fill" id="r-risk-bar" style="width:0%"></div></div>
        <div class="risk-marks"><span>0%</span><span id="r-risk-mid">3%</span><span id="r-risk-max">6%</span></div>
      </div>

      <div class="daily-section">
        <div class="section-title">Daily P&amp;L History</div>
        <div id="daily-rows"><span style="color:var(--muted);font-size:10px">No history yet</span></div>
      </div>

      <div class="log-section">
        <div class="log-header">
          <span class="section-title" style="margin:0">Activity Log</span>
          <span id="log-count" style="font-size:10px;color:var(--muted)">0</span>
        </div>
        <div class="log-entries" id="log-entries"></div>
      </div>
    </div>
  </div>
</div>

<div class="paused-banner" id="paused-banner">⏸ BOT PAUSED — no new trades will be placed</div>

<!-- ═══ TRADES POPUP ═══ -->
<div class="trades-overlay" id="trades-overlay" onclick="if(event.target===this)closeTrades()">
  <div class="trades-modal">
    <div class="trades-modal-head">
      <div class="trades-modal-title">
        📊 Trades
        <div class="trades-tabs">
          <button class="trades-tab active" id="tab-open" onclick="switchTradesTab('open')">Open Positions</button>
          <button class="trades-tab hist-tab" id="tab-hist" onclick="switchTradesTab('hist')">Trade History</button>
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <button class="trades-refresh" onclick="loadTradesData()">↻ REFRESH</button>
        <button class="chart-close" onclick="closeTrades()">✕</button>
      </div>
    </div>

    <div class="trades-body">
      <!-- Open Positions Pane -->
      <div class="trades-pane active" id="pane-open">
        <div style="display:flex;flex-direction:column;flex:1;overflow:auto;min-height:0">
          <table class="trades-table" id="open-table">
            <thead><tr>
              <th>Ticket</th><th>Symbol</th><th>Dir</th><th>Lot</th>
              <th>Open Price</th><th>Current Price</th><th>SL</th><th>TP</th>
              <th>Open Time</th><th>Comment</th><th>P&amp;L</th>
            </tr></thead>
            <tbody id="open-tbody"><tr><td colspan="11" class="trades-empty" style="border:none">Loading…</td></tr></tbody>
          </table>
        </div>
        <div class="trades-summary" id="open-summary" style="display:none">
          <div class="trades-summary-item"><div class="trades-summary-label">Open Positions</div><div class="trades-summary-value" id="sum-open-count">0</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Total Lots</div><div class="trades-summary-value" id="sum-open-lots">0.00</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Floating P&amp;L</div><div class="trades-summary-value" id="sum-open-pnl">$0.00</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Buy / Sell</div><div class="trades-summary-value" id="sum-open-sides">0 / 0</div></div>
        </div>
      </div>

      <!-- History Pane -->
      <div class="trades-pane" id="pane-hist">
        <div class="hist-filter">
          <span style="font-size:9px;color:var(--muted);letter-spacing:1px;text-transform:uppercase">Filter:</span>
          <button class="hist-filter-btn active" onclick="filterHist('all',this)">ALL</button>
          <button class="hist-filter-btn" onclick="filterHist('win',this)">WIN</button>
          <button class="hist-filter-btn" onclick="filterHist('loss',this)">LOSS</button>
          <button class="hist-filter-btn" onclick="filterHist('today',this)">TODAY</button>
          <span style="margin-left:auto;font-size:9px;color:var(--muted)" id="hist-count-label">— trades</span>
        </div>
        <div class="trades-pane active" style="flex:1;overflow:auto;min-height:0;display:block">
          <table class="trades-table" id="hist-table">
            <thead><tr>
              <th>Ticket</th><th>Symbol</th><th>Dir</th><th>Lot</th>
              <th>Open Price</th><th>Close Price</th><th>Open Time</th><th>Close Time</th>
              <th>Duration</th><th>Comment</th><th>P&amp;L</th>
            </tr></thead>
            <tbody id="hist-tbody"><tr><td colspan="11" class="trades-empty" style="border:none">Loading…</td></tr></tbody>
          </table>
        </div>
        <div class="trades-summary" id="hist-summary" style="display:none">
          <div class="trades-summary-item"><div class="trades-summary-label">Total Trades</div><div class="trades-summary-value" id="sum-hist-count">0</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Win Rate</div><div class="trades-summary-value" id="sum-hist-wr">0%</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Total P&amp;L</div><div class="trades-summary-value" id="sum-hist-pnl">$0.00</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Wins / Losses</div><div class="trades-summary-value" id="sum-hist-wl">0 / 0</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Avg Win</div><div class="trades-summary-value t-pos" id="sum-hist-avgwin">$0.00</div></div>
          <div class="trades-summary-item"><div class="trades-summary-label">Avg Loss</div><div class="trades-summary-value t-neg" id="sum-hist-avgloss">$0.00</div></div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- SETTINGS MODAL (with embedded Symbol Manager) -->
<div class="settings-overlay" id="settings-overlay" onclick="settingsOverlayClick(event)">
  <div class="settings-modal">
    <div class="settings-head">
      <h2>⚙ Settings &amp; <span style="color:var(--cyan)">⊞ Symbols</span></h2>
      <button class="chart-close" onclick="closeSettings()">✕</button>
    </div>
    <!-- Two-column body -->
    <div class="settings-cols">

      <!-- LEFT: Strategy & Risk parameters -->
      <div class="settings-col">
        <div class="server-toggle-row">
          <div>
            <div class="server-toggle-label" id="srv-label">Bot running</div>
            <div style="font-size:9px;color:var(--muted);margin-top:2px">Pause stops new entries; existing positions unaffected</div>
          </div>
          <button class="server-toggle-btn running" id="srv-btn" onclick="toggleServer()">⏸ PAUSE</button>
        </div>
        <div class="settings-section">
          <div class="settings-section-title sniper-title">Strategies — Enable / Disable</div>
          <div class="settings-row"><div class="settings-label">Normal<i class="info-ic" onmouseenter="showTip(this,'Multi-timeframe trend strategy for all symbols. Forex & metals need M1+M15+H1 aligned. Crypto uses the same logic but with its own RR, ATR and score from the Crypto Overrides section below.')" onmouseleave="hideTip()">i</i></div><button class="strat-toggle" id="st-btn-normal" onclick="toggleStrategy('normal',this)">—</button></div>
          <div class="settings-row"><div class="settings-label">Sniper Breakout<i class="info-ic" onmouseenter="showTip(this,'Enters when price closes beyond the 4-bar high or low. Pure price action, no score filter. Fast entries on momentum breaks.')" onmouseleave="hideTip()">i</i></div><button class="strat-toggle" id="st-btn-sniper_breakout" onclick="toggleStrategy('sniper_breakout',this)">—</button></div>
          <div class="settings-row"><div class="settings-label">Sniper Impulse<i class="info-ic" onmouseenter="showTip(this,'Fires on a single strong candle whose body is more than 70% of its range, confirmed by EMA9 > EMA21 direction.')" onmouseleave="hideTip()">i</i></div><button class="strat-toggle" id="st-btn-sniper_impulse" onclick="toggleStrategy('sniper_impulse',this)">—</button></div>
          <div class="settings-row"><div class="settings-label">Sniper Reversion<i class="info-ic" onmouseenter="showTip(this,'Counter-trend entry. When price stretches more than 1.5× ATR away from EMA9, the bot fades the move back toward the H1 trend direction.')" onmouseleave="hideTip()">i</i></div><button class="strat-toggle" id="st-btn-sniper_reversion" onclick="toggleStrategy('sniper_reversion',this)">—</button></div>
        </div>
        <div class="settings-section">
          <div class="settings-section-title sniper-title">Risk — Forex &amp; Metals</div>
          <div class="settings-row"><div class="settings-label">Risk per trade<small>% of balance</small><i class="info-ic" onmouseenter="showTip(this,'Percentage of your account balance risked on each trade. 0.5 = half a percent. Scales automatically: +50% when up 3%, −50% when down 2%.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-base_risk_pct" type="number" step="0.05" min="0.05" max="5"></div>
          <div class="settings-row"><div class="settings-label">Max portfolio risk<i class="info-ic" onmouseenter="showTip(this,'Bot stops opening new trades when total open risk across all positions reaches this % of balance. Protects against overexposure.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-max_portfolio_risk" type="number" step="0.5" min="0.5" max="20"></div>
          <div class="settings-row"><div class="settings-label">RR ratio (normal)<i class="info-ic" onmouseenter="showTip(this,'Reward-to-risk ratio for the Forex Normal strategy. 2.5 means the TP is placed 2.5× further from entry than the SL.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-rr" type="number" step="0.1" min="0.5" max="20"></div>
          <div class="settings-row"><div class="settings-label">Max pos per symbol<i class="info-ic" onmouseenter="showTip(this,'Maximum simultaneous open positions per symbol for the normal strategy. Sniper strategies have their own separate limit.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-max_pos" type="number" step="1" min="1" max="10"></div>
          <div class="settings-row"><div class="settings-label">Min entry distance<small>× initial risk</small><i class="info-ic" onmouseenter="showTip(this,'Prevents stacking trades too close together. A new entry in the same direction must be at least this multiple of initial risk away from existing positions.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-min_entry_dist" type="number" step="0.05" min="0" max="2"></div>
          <div class="settings-row"><div class="settings-label">Min score (normal)<i class="info-ic" onmouseenter="showTip(this,'Minimum composite momentum/trend score (0–1) required before the normal strategy enters. Higher = more selective, fewer but cleaner trades.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-min_score" type="number" step="0.01" min="0" max="1"></div>
          <div class="settings-row"><div class="settings-label">ATR multiplier<i class="info-ic" onmouseenter="showTip(this,'Stop loss distance = ATR × this value. Higher = wider SL, less noise-stopped. Lower = tighter SL, smaller loss if wrong but stops out more often.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-atr_sl_mult" type="number" step="0.1" min="0.5" max="5"></div>
          <div class="settings-row"><div class="settings-label">Trail trigger<small>× R</small><i class="info-ic" onmouseenter="showTip(this,'Trailing stop activates once profit reaches this multiple of initial risk. 0.6 = trailing starts when 60% of 1R is in profit.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-trail_trigger" type="number" step="0.05" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Trail step<small>min points</small><i class="info-ic" onmouseenter="showTip(this,'Minimum improvement in points before a trailing SL update is sent to the broker. Prevents constant micro-adjustments and rejected orders.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-trail_step" type="number" step="1" min="1" max="50"></div>
          <div class="settings-row"><div class="settings-label">UTC trade start<i class="info-ic" onmouseenter="showTip(this,'Hour (UTC) from which the bot may open new forex & metals trades. Default 6 = London open. Crypto is always 24h regardless.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-utc_start" type="number" step="1" min="0" max="23"></div>
          <div class="settings-row"><div class="settings-label">UTC trade end<i class="info-ic" onmouseenter="showTip(this,'Hour (UTC) after which no new forex & metals trades are opened. Default 17 = New York close. Open positions continue to run.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-utc_end" type="number" step="1" min="0" max="23"></div>
          <div class="settings-row"><div class="settings-label">Time filter — Metals<small>off = 24h like crypto</small><i class="info-ic" onmouseenter="showTip(this,'When ON, gold (XAUUSD) and silver (XAGUSD) follow the same UTC trading window as forex. When OFF they trade 24h like crypto.')" onmouseleave="hideTip()">i</i></div><select class="settings-input" id="s-metals_time_filter"><option value="1">ON (06–17 UTC)</option><option value="0">OFF (24h)</option></select></div>
          <div class="settings-row"><div class="settings-label">Slippage deviation<i class="info-ic" onmouseenter="showTip(this,'Maximum allowed price deviation in points when sending orders. Higher = more likely to fill in fast markets. Lower = stricter fill price but more rejections.')" onmouseleave="hideTip()">i</i></div><input class="settings-input" id="s-deviation" type="number" step="1" min="1" max="200"></div>
        </div>
        <div class="settings-section">
          <div class="settings-section-title crypto-title">₿ Crypto Overrides</div>
          <div class="settings-row"><div class="settings-label">RR<small>lower = TP hit more often</small><i class="info-ic" onmouseenter="showTip(this,'Reward/risk ratio for crypto. Lower than forex (1.8 vs 2.5) because crypto moves fast and a closer TP gets hit more reliably.')" onmouseleave="hideTip()">i</i></div><input class="settings-input crypto-input" id="s-crypto_rr" type="number" step="0.1" min="0.5" max="10"></div>
          <div class="settings-row"><div class="settings-label">ATR-SL mult<small>higher = wider SL</small><i class="info-ic" onmouseenter="showTip(this,'Wider stop for crypto (2.2×) to survive volatile swings that would stop out a tighter forex stop.')" onmouseleave="hideTip()">i</i></div><input class="settings-input crypto-input" id="s-crypto_atr_sl_mult" type="number" step="0.1" min="0.5" max="6"></div>
          <div class="settings-row"><div class="settings-label">Trail trigger<small>× R</small><i class="info-ic" onmouseenter="showTip(this,'Trail activates earlier for crypto (0.4R) to lock in profits faster given the higher volatility and sudden reversals.')" onmouseleave="hideTip()">i</i></div><input class="settings-input crypto-input" id="s-crypto_trail_trigger" type="number" step="0.05" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Min score<i class="info-ic" onmouseenter="showTip(this,'Minimum score for crypto normal. Lower than forex (0.45 vs 0.55) because crypto momentum scores work on a different scale.')" onmouseleave="hideTip()">i</i></div><input class="settings-input crypto-input" id="s-crypto_min_score" type="number" step="0.01" min="0" max="1"></div>
          <div class="settings-row"><div class="settings-label">Max positions<i class="info-ic" onmouseenter="showTip(this,'Maximum simultaneous open crypto positions per symbol. Lower than forex (2 vs 3) to limit exposure on volatile assets.')" onmouseleave="hideTip()">i</i></div><input class="settings-input crypto-input" id="s-crypto_max_pos" type="number" step="1" min="1" max="10"></div>
        </div>
        <div class="settings-section">
          <div class="settings-section-title sniper-title">⚡ Sniper — Breakout</div>
          <div class="settings-row"><div class="settings-label">RR<i class="info-ic" onmouseenter="showTip(this,'Reward/risk ratio for Sniper Breakout. Lower (1.2) because breakout entries are close to the move — TP is hit quickly or the break fails fast.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_breakout_rr" type="number" step="0.1" min="0.5" max="10"></div>
          <div class="settings-row"><div class="settings-label">ATR-SL mult<i class="info-ic" onmouseenter="showTip(this,'Tight SL (0.6× ATR) placed just inside the broken range. If price re-enters the range the idea is invalid.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_breakout_atr" type="number" step="0.1" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Trail trigger<small>× R</small><i class="info-ic" onmouseenter="showTip(this,'Trail starts when 40% of 1R is in profit. Early trail to protect breakout gains that can evaporate quickly.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_breakout_trail" type="number" step="0.05" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Max positions<i class="info-ic" onmouseenter="showTip(this,'Max simultaneous Sniper Breakout positions per symbol.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_breakout_maxpos" type="number" step="1" min="1" max="10"></div>
          <div class="settings-row"><div class="settings-label">Min score<small>0 = no gate</small><i class="info-ic" onmouseenter="showTip(this,'Score gate for this sniper. Default 0 = disabled. Sniper strategies use pure price action and do not need a score filter.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_breakout_score" type="number" step="0.01" min="0" max="1"></div>
          <div class="settings-section-title sniper-title" style="margin-top:10px">⚡ Sniper — Impulse</div>
          <div class="settings-row"><div class="settings-label">RR<i class="info-ic" onmouseenter="showTip(this,'Reward/risk for Sniper Impulse. Slightly higher than Breakout (1.3) because impulse candles have clearer direction.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_impulse_rr" type="number" step="0.1" min="0.5" max="10"></div>
          <div class="settings-row"><div class="settings-label">ATR-SL mult<i class="info-ic" onmouseenter="showTip(this,'SL placed at 0.7× ATR. Slightly wider than Breakout to give the impulse room to continue without a false stop.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_impulse_atr" type="number" step="0.1" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Trail trigger<small>× R</small><i class="info-ic" onmouseenter="showTip(this,'Trail activates at 0.35R. Slightly earlier than Breakout to capture impulse profits before the move fades.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_impulse_trail" type="number" step="0.05" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Max positions<i class="info-ic" onmouseenter="showTip(this,'Max simultaneous Sniper Impulse positions per symbol.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_impulse_maxpos" type="number" step="1" min="1" max="10"></div>
          <div class="settings-row"><div class="settings-label">Min score<small>0 = no gate</small><i class="info-ic" onmouseenter="showTip(this,'Score gate for Sniper Impulse. Default 0 = disabled. The candle body filter already acts as a quality gate.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_impulse_score" type="number" step="0.01" min="0" max="1"></div>
          <div class="settings-section-title sniper-title" style="margin-top:10px">⚡ Sniper — Reversion</div>
          <div class="settings-row"><div class="settings-label">RR<i class="info-ic" onmouseenter="showTip(this,'Reward/risk for Sniper Reversion. Lowest (1.1) because counter-trend trades are riskier — quick profit target keeps win rate healthy.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_reversion_rr" type="number" step="0.1" min="0.5" max="10"></div>
          <div class="settings-row"><div class="settings-label">ATR-SL mult<i class="info-ic" onmouseenter="showTip(this,'Tight SL (0.5× ATR) for the reversion. If price keeps going against the H1 trend beyond this the setup is invalid.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_reversion_atr" type="number" step="0.1" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Trail trigger<small>× R</small><i class="info-ic" onmouseenter="showTip(this,'Earliest trail trigger (0.3R). Reversion moves snap back fast — trail immediately to not give back the profit.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_reversion_trail" type="number" step="0.05" min="0.1" max="5"></div>
          <div class="settings-row"><div class="settings-label">Max positions<i class="info-ic" onmouseenter="showTip(this,'Max simultaneous Sniper Reversion positions per symbol.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_reversion_maxpos" type="number" step="1" min="1" max="10"></div>
          <div class="settings-row"><div class="settings-label">Min score<small>0 = no gate</small><i class="info-ic" onmouseenter="showTip(this,'Score gate for Sniper Reversion. Default 0 = disabled. The 1.5× ATR stretch condition is the quality filter.')" onmouseleave="hideTip()">i</i></div><input class="settings-input sniper-input" id="s-sniper_reversion_score" type="number" step="0.01" min="0" max="1"></div>
        </div>
      </div><!-- /settings-col left -->

      <!-- RIGHT: Symbol Manager -->
      <div class="settings-col">
        <!-- Header row -->
        <div style="padding:8px 10px 8px;border-bottom:1px solid var(--border);flex-shrink:0">
          <div class="sm-col-head">
            <span class="sm-col-title">⊞ Symbol Manager</span>
            <span style="font-size:9px;color:var(--muted);letter-spacing:1px">ACTIVE: <strong id="sm-count" style="color:var(--text)">0</strong></span>
          </div>
          <!-- Add/Edit form -->
          <div class="sm-add-grid">
            <div>
              <div class="sm-field-label">Symbol</div>
              <input id="sm-symbol" class="settings-input" style="width:80%;text-align:left;text-transform:uppercase" placeholder="e.g. GBPJPY" maxlength="12">
            </div>
            <div>
              <div class="sm-field-label">Category</div>
              <select id="sm-category" class="settings-input" style="width:100%">
                <option value="EUR">EUR</option>
                <option value="GBP">GBP</option>
                <option value="USD">USD</option>
                <option value="Metals">Metals</option>
                <option value="Crypto">Crypto</option>
              </select>
            </div>
            <div>
              <div class="sm-field-label">Max Spread</div>
              <input id="sm-spread" class="settings-input" style="width:100%" type="number" step="0.5" min="0.5" value="20" placeholder="20">
            </div>
            <div style="display:flex;flex-direction:column;gap:4px">
              <div class="sm-field-label">&nbsp;</div>
              <button id="sm-add-btn" onclick="smAddSymbol()" style="height:26px;border-radius:3px;font-size:10px;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid rgba(0,212,255,0.35);background:rgba(0,212,255,0.10);color:var(--cyan);font-family:var(--mono)">+ ADD</button>
            </div>
          </div>
          <div id="sm-msg" style="font-size:10px;min-height:14px;color:var(--muted)"></div>
        </div>
        <!-- Filter bar -->
        <div style="padding:6px 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);flex-shrink:0">
          <input id="sm-filter" oninput="smFilterTable()" placeholder="filter symbols…" style="height:22px;width:140px;background:var(--bg3);border:1px solid var(--border2);border-radius:3px;color:var(--text);font-family:var(--mono);font-size:11px;padding:0 8px">
          <button onclick="smResetSymbols()" style="height:22px;padding:0 10px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid rgba(255,184,48,0.3);background:rgba(255,184,48,0.07);color:var(--amber);font-family:var(--mono)">↺ DEFAULT</button>
        </div>
        <!-- Symbol table -->
        <div class="sm-table-scroll" style="overflow-y:auto;overflow-x:auto;flex:1;min-height:0">
          <table style="width:100%;min-width:280px;border-collapse:collapse;table-layout:fixed">
            <thead>
              <tr>
                <th style="padding:4px 6px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border2);background:var(--bg2);position:sticky;top:0;width:72px;max-width:72px;text-align:left;font-size:8px;letter-spacing:1px">SYM</th>
                <th style="padding:4px 6px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border2);background:var(--bg2);position:sticky;top:0;width:52px;max-width:52px;text-align:center;font-size:8px;letter-spacing:1px">CAT</th>
                <th style="padding:4px 6px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border2);background:var(--bg2);position:sticky;top:0;width:46px;max-width:46px;text-align:right;font-size:8px;letter-spacing:1px">SPR</th>
                <th style="padding:4px 6px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border2);background:var(--bg2);position:sticky;top:0;text-align:center;font-size:8px;letter-spacing:1px">ACT</th>
              </tr>
            </thead>
            <tbody id="sm-tbody"></tbody>
          </table>
        </div>
      </div><!-- /settings-col right -->

    </div><!-- /settings-cols -->

    <div class="settings-footer">
      <button class="settings-cancel-btn" onclick="closeSettings()">CANCEL</button>
      <button class="settings-cancel-btn" id="settings-default-btn" onclick="resetSettings()" style="color:var(--amber);border-color:rgba(255,184,48,0.3)">↺ SETTINGS DEFAULT</button>
      <button class="settings-save-btn" id="settings-save-btn" onclick="saveSettings()">✓ APPLY SETTINGS</button>
    </div>
  </div>
</div>

<!-- CHART POPUP -->
<div class="chart-overlay" id="chart-overlay" onclick="closeChart(event)">
  <div class="chart-modal">
    <div class="chart-modal-header">
      <div class="chart-modal-title"><span id="chart-title">—</span><span class="chart-modal-sub" id="chart-tf-label">M1 · 100 CANDLES</span></div>
      <div style="display:flex;align-items:center;gap:6px">
        <div style="display:flex;gap:3px">
          <button class="tf-btn active" onclick="setTf('M1')">M1</button>
          <button class="tf-btn" onclick="setTf('M5')">M5</button>
          <button class="tf-btn" onclick="setTf('M15')">M15</button>
          <button class="tf-btn" onclick="setTf('M30')">M30</button>
          <button class="tf-btn" onclick="setTf('H1')">H1</button>
          <button class="tf-btn" onclick="setTf('H4')">H4</button>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
          <div style="display:flex;gap:10px;font-size:10px;color:var(--muted)">
            <span>O <strong id="ci-o">—</strong></span><span>H <strong id="ci-h" style="color:var(--green)">—</strong></span>
            <span>L <strong id="ci-l" style="color:var(--red)">—</strong></span><span>C <strong id="ci-c">—</strong></span>
          </div>
          <button class="chart-close" onclick="closeChart()">✕</button>
        </div>
      </div>
    </div>
    <div class="chart-body"><div id="chart-container"><div class="chart-loading"><span class="chart-loading-dot"></span>LOADING</div></div></div>
  </div>
</div>

<!-- MANUAL TRADE MODAL -->
<div class="trade-overlay" id="trade-overlay">
  <div class="trade-modal">
    <h3 id="tm-title">—</h3>
    <div class="trade-detail-row"><span class="lbl">Score</span><span class="val" id="tm-score">—</span></div>
    <div class="trade-detail-row"><span class="lbl">H1 Trend</span><span class="val" id="tm-h1">—</span></div>
    <div class="trade-detail-row"><span class="lbl">Regime</span><span class="val" id="tm-regime">—</span></div>
    <div class="trade-detail-row"><span class="lbl">Spread</span><span class="val" id="tm-spread">—</span></div>
    <div class="trade-detail-row"><span class="lbl">M1 Mom</span><span class="val" id="tm-mom1">—</span></div>
    <div class="trade-detail-row"><span class="lbl">M15 Mom</span><span class="val" id="tm-mom15">—</span></div>
    <div class="trade-note" id="tm-note">Loading…</div>
    <div class="trade-actions">
      <button class="trade-confirm-btn cancel" onclick="closeTradeModal()">CANCEL</button>
      <button class="trade-confirm-btn go-buy" id="tm-exec-btn" onclick="executeManualTrade()">EXECUTE</button>
    </div>
  </div>
</div>

<!-- CLOSE ALL MODAL -->
<div class="close-overlay" id="close-overlay">
  <div class="close-modal">
    <h3>⚠ Close All Positions</h3>
    <p>Close <strong id="cm-count">0</strong> position(s) on <strong id="cm-symbol">—</strong> at market price?</p>
    <p style="margin-top:6px;font-size:10px;color:var(--red)">This action cannot be undone.</p>
    <div class="close-modal-actions">
      <button class="trade-confirm-btn cancel" style="flex:1" onclick="closeCloseModal()">CANCEL</button>
      <button class="trade-confirm-btn go-close" style="flex:1" id="cm-exec-btn" onclick="executeClose()">CLOSE ALL</button>
    </div>
  </div>
</div>

<div id="s-tooltip"></div>

<script>
  const _tip=document.getElementById('s-tooltip');
  function showTip(el,txt){
    _tip.textContent=txt; _tip.style.opacity='1';
    const r=el.getBoundingClientRect();
    let x=r.right+8, y=r.top-4;
    if(x+240>window.innerWidth) x=r.left-248;
    if(y+100>window.innerHeight) y=window.innerHeight-110;
    _tip.style.left=x+'px'; _tip.style.top=y+'px';
  }
  function hideTip(){ _tip.style.opacity='0'; }
  const CRYPTO_SYMS = new Set(["BTCUSD","ETHUSD","SOLUSD","BNBUSD","DOGUSD","XRPUSD","ADAUSD","LTCUSD","DOTUSD"]);
  const STRAT_NAMES = ["normal","sniper_breakout","sniper_impulse","sniper_reversion"];

  function fmt2(v)    { return v == null ? '—' : v.toFixed(2); }
  function fmtM(v)    { return '$'+Math.abs(v).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}); }
  function fmtSgn(v)  { return (v>=0?'+$':'-$')+Math.abs(v).toFixed(2); }
  function colCls(v)  { return v>0?'pos':v<0?'neg':''; }
  function pnlCls(v)  { return v>0?'pnl-pos':v<0?'pnl-neg':'pnl-zero'; }
  function scoreCls(s){ return s>=0.65?'sp-high':s>=0.50?'sp-mid':'sp-low'; }
  function barColor(s){ const r=Math.round(255*(1-s)),g=Math.round(229*s); return `rgb(${r},${g},60)`; }
  function setEl(id,txt,cls){ const el=document.getElementById(id); if(!el)return; el.textContent=txt; if(cls!==undefined){el.className=el.className.replace(/\b(pos|neg|cyan|amber)\b/g,'').trim(); if(cls)el.className+=' '+cls;} }
  function h1Badge(t){ if(t==='UP')return'<span class="h1-badge h1-up">H1↑</span>'; if(t==='DN')return'<span class="h1-badge h1-dn">H1↓</span>'; return'<span class="h1-badge h1-flat">H1—</span>'; }
  function momDir(m){ if(m==='UP')return'<span class="trend-up">↑</span>'; if(m==='DN')return'<span class="trend-dn">↓</span>'; return'<span class="trend-flat">—</span>'; }
  function regimeBadge(r){ const cls=r==='HIGH'?'rg-high':r==='LOW'?'rg-low':'rg-norm'; return`<span class="regime-tag ${cls}">${r||'NORMAL'}</span>`; }
  function stratTagHtml(name){ const isCrypto=name.startsWith('crypto'); const isSniper=name.startsWith('sniper'); const cls=isCrypto?'st-crypto':isSniper?'st-sniper':'st-normal'; const lbl=name.replace('sniper_','').replace('crypto_','₿ ').replace('normal','nrm').toUpperCase(); return`<span class="strat-tag ${cls}">${lbl}</span>`; }
  function logCls(msg){ if(/✅/.test(msg))return'ok'; if(/❌|⛔/.test(msg))return'err'; if(/⚠/.test(msg))return'warn'; if(/📈|TRAIL/.test(msg))return'trail'; if(/🚀/.test(msg))return'info'; if(/🖐|MANUAL/.test(msg))return'manual'; if(/🔴|CLOSE/.test(msg))return'close'; return''; }

  let lastLogSig='', _cfgRendered=false;

  function updateConfig(cfg){
    if(_cfgRendered||!cfg)return;
    const el=document.getElementById('cfg-strip'); if(!el)return;
    el.innerHTML=['RR <strong style="color:var(--text)">1:'+cfg.rr+'</strong>','ATR-SL <strong style="color:var(--text)">'+(cfg.atr_sl_mult||1.5)+'×</strong>','<span style="color:var(--gold)">₿RR <strong>1:'+(cfg.crypto_rr||1.8)+'</strong></span>'].join(' · ');
    _cfgRendered=true;
  }

  function updateStrategies(strategies){
    if(!strategies)return;
    STRAT_NAMES.forEach(name=>{
      const btn=document.getElementById('st-btn-'+name); if(!btn)return;
      const on=(strategies[name]||{}).enabled;
      btn.className='strat-toggle '+(on?'on':'off');
      btn.textContent=on?'ON':'OFF';
    });
  }

  async function toggleStrategy(name,btn){
    btn.disabled=true;
    try{
      const r=await fetch('/api/strategy/'+name,{method:'POST'}); const d=await r.json();
      btn.className='strat-toggle '+(d.enabled?'on':'off');
      btn.textContent=d.enabled?'ON':'OFF';
    }catch(e){}
    btn.disabled=false;
  }

  async function refresh(){
    try{
      const d=await fetch('/api/data').then(r=>r.json());
      updateHeader(d); updateConfig(d.config); updateKPIs(d);
      updateRisk(d.portfolio_risk||0, (d.config||{}).max_portfolio_risk||6); updateTable(d.symbols||[]);
      updateDaily(d.daily||{}); updateLog(d.log||[]);
      updateStrategies(d.strategies);
    }catch(e){console.error('refresh',e);}
  }

  function updateHeader(d){
    setEl('h-started',d.started||'—'); setEl('h-trades',d.trades_total||0);
    const sp=d.session_pnl||0;
    const chip=document.getElementById('session-chip'); const valEl=document.getElementById('session-val');
    if(chip)chip.className='session-chip '+(sp>0?'pos':sp<0?'neg':'zero');
    if(valEl)valEl.textContent=fmtSgn(sp);
    setEl('g-balance',d.session_start?'$'+fmt2(d.session_start):'—');
    if(!_settingsOpen)updateServerBtn(d.bot_paused||false);
  }

  function updateKPIs(d){
    const a=d.account||{},b=d.basket||{};
    setEl('k-balance',fmtM(a.balance||0),'cyan');
    setEl('k-equity',fmtM(a.equity||0),colCls((a.equity||0)-(a.balance||0)));
    setEl('k-equity-sub',(a.equity||0)>=(a.balance||0)?'▲ above balance':'▼ below balance');
    const cur=b.current||0; setEl('k-openpl',fmtSgn(cur),colCls(cur));
    const sp=d.session_pnl||0; setEl('k-session',fmtSgn(sp),colCls(sp));
    setEl('k-pos',a.open_positions||0);
    setEl('k-syms',(a.active_symbols||0)+' symbol'+((a.active_symbols!==1)?'s':''));
    const risk=d.portfolio_risk||0; const maxRisk=(d.config||{}).max_portfolio_risk||6; setEl('k-risk',risk.toFixed(2)+'%',risk>(maxRisk*2/3)?'amber':'');
    setEl('sym-count',(d.symbols||[]).length);
  }

  function updateRisk(risk, max){
    max=max||6;
    document.getElementById('r-risk-val').textContent=risk.toFixed(2)+'%';
    document.getElementById('r-risk-bar').style.width=Math.min(risk/max*100,100)+'%';
    const mid=document.getElementById('r-risk-mid'); if(mid)mid.textContent=(max/2).toFixed(1).replace('.0','')+'%';
    const mx=document.getElementById('r-risk-max');  if(mx)mx.textContent=max+'%';
  }

  const rowCache=new Map(); let _activeCat='ALL';
  const CAT_ORDER=['EUR','GBP','USD','Metals','Crypto'];
  const CAT_LABELS={EUR:'EUR Pairs',GBP:'GBP Pairs',USD:'USD Pairs',Metals:'Metals',Crypto:'Crypto'};

  function filterCat(cat){ _activeCat=cat; document.querySelectorAll('.cat-tab').forEach(t=>t.classList.toggle('active',t.dataset.cat===cat)); applyFilter(); }

  function applyFilter(){
    const tbody=document.getElementById('sym-tbody'); let visible=0;
    tbody.querySelectorAll('tr').forEach(tr=>{ if(tr.classList.contains('cat-row'))return; const sym=tr.dataset.sym; if(!sym)return; const c=rowCache.get(sym); if(!c)return; const show=_activeCat==='ALL'||c.category===_activeCat; tr.style.display=show?'':'none'; if(show)visible++; });
    tbody.querySelectorAll('tr.cat-row').forEach(tr=>{ tr.style.display=_activeCat!=='ALL'?'none':''; });
    document.getElementById('sym-count').textContent=visible;
  }

  function buildTable(syms){
    const tbody=document.getElementById('sym-tbody'); tbody.innerHTML=''; rowCache.clear();
    const groups={}; CAT_ORDER.forEach(cat=>groups[cat]=[]);
    syms.forEach(s=>{ const cat=s.category||'Other'; if(!groups[cat])groups[cat]=[]; groups[cat].push(s); });
    let total=0;
    CAT_ORDER.forEach(cat=>{ const n=(groups[cat]||[]).length; const el=document.getElementById('ct-'+cat); if(el)el.textContent=n; total+=n; });
    document.getElementById('ct-ALL').textContent=total;
    CAT_ORDER.forEach(cat=>{
      const catSyms=groups[cat]||[]; if(!catSyms.length)return;
      const hdr=document.createElement('tr'); hdr.className='cat-row'; hdr.dataset.cat=cat;
      hdr.innerHTML=`<td colspan="9">${CAT_LABELS[cat]||cat}<span style="color:var(--muted);font-size:8px;font-weight:400;margin-left:8px;letter-spacing:1px">${catSyms.length} symbols</span></td>`;
      tbody.appendChild(hdr);
      catSyms.forEach(s=>{
        const isCrypto=CRYPTO_SYMS.has(s.symbol);
        const tr=document.createElement('tr'); tr.dataset.sym=s.symbol;
        tr.innerHTML=`
          <td><span class="sym-name" onclick="openChart('${s.symbol}')">${s.symbol}</span></td>
          <td class="c-score"></td><td class="c-mom center"></td>
          <td class="c-regime"></td>
          <td class="c-spread"></td><td class="c-profitpos"></td>
          <td style="text-align:center"><button class="toggle-btn enabled" onclick="toggleSym('${s.symbol}',this)"><span>ON</span></button></td>
          <td style="text-align:center;white-space:nowrap">
            <button class="trade-btn buy"  onclick="openTradeModal('${s.symbol}','BUY')">&#9650; BUY</button>
            <button class="trade-btn sell" onclick="openTradeModal('${s.symbol}','SELL')">&#9660; SELL</button>
          </td>
          <td style="text-align:center"><button class="close-btn no-pos" onclick="openCloseModal('${s.symbol}')">✕ CLOSE</button></td>`;
        tbody.appendChild(tr);
        rowCache.set(s.symbol,{ tr, category:s.category,
          score:tr.querySelector('.c-score'), mom:tr.querySelector('.c-mom'),
          regime:tr.querySelector('.c-regime'),
          spread:tr.querySelector('.c-spread'), profitpos:tr.querySelector('.c-profitpos'),
          btn:tr.querySelector('.toggle-btn'), closeBtn:tr.querySelector('.close-btn') });
      });
    });
    applyFilter();
  }

  function updateTable(syms){
    if(!syms.length)return;
    if(rowCache.size===0){buildTable(syms);return;}
    syms.forEach(s=>{
      const c=rowCache.get(s.symbol); if(!c)return;
      c.tr.className=s.disabled?'row-disabled':!s.market_open?'row-closed':s.positions>0?'row-active':'';
      c.score.innerHTML=`<div class="bar-wrap"><span class="score-pill ${scoreCls(s.score)}">${s.score.toFixed(2)}</span><div class="bar-track"><div class="bar-fill" style="width:${(s.score*100).toFixed(1)}%;background:${barColor(s.score)}"></div></div></div>`;
      c.mom.innerHTML=`${momDir(s.mom1)}<span style="color:var(--muted2)">/</span>${momDir(s.mom15)}<span style="color:var(--muted2)">/</span>${momDir(s.h1_trend)}`;
      c.regime.innerHTML=regimeBadge(s.regime);
      c.spread.innerHTML=`<span class="${s.spread_warn&&s.market_open?'spread-warn':'spread-ok'}">${s.spread}</span>`;
      const posColor=s.pos_side==='buy'?'var(--green)':s.pos_side==='sell'?'var(--red)':s.pos_side==='mixed'?'var(--amber)':'var(--muted)';
      const posIcon=s.pos_side==='buy'?'▲':s.pos_side==='sell'?'▼':'';
      c.profitpos.innerHTML=`<span class="${s.profit!==0?pnlCls(s.profit):'pnl-zero'}">${s.profit!==0?fmtSgn(s.profit):'—'}</span><span style="color:${posColor};font-size:10px;margin-left:4px;font-weight:600">${posIcon}${s.positions}/${s.max_pos}</span>`;
      if(!c.btn.classList.contains('pending')){ c.btn.className='toggle-btn '+(s.disabled?'disabled':'enabled'); c.btn.querySelector('span').textContent=s.disabled?'OFF':'ON'; }
      if(c.closeBtn&&!c.closeBtn.classList.contains('closing')){ if(s.positions>0){c.closeBtn.className='close-btn';c.closeBtn.textContent=`✕ ${s.positions>1?s.positions+' POS':'CLOSE'}`;} else{c.closeBtn.className='close-btn no-pos';c.closeBtn.textContent='✕ CLOSE';} }
    });
    applyFilter();
  }

  function updateDaily(daily){
    const dates=Object.keys(daily).sort().reverse(); const el=document.getElementById('daily-rows');
    el.innerHTML=dates.length?dates.slice(0,7).map(dt=>`<div class="daily-row"><span class="daily-date">${dt}</span><span class="${pnlCls(daily[dt])}">${fmtSgn(daily[dt])}</span></div>`).join(''):'<span style="color:var(--muted);font-size:10px">No history yet</span>';
  }

  function updateLog(entries){
    const sig=entries.length?(entries[0].time+entries[0].msg):'';
    if(sig===lastLogSig)return; lastLogSig=sig;
    setEl('log-count',entries.length);
    document.getElementById('log-entries').innerHTML=entries.map(e=>`<div class="log-entry"><span class="log-t">${e.time}</span><span class="log-m ${logCls(e.msg)}">${e.msg}</span></div>`).join('');
  }

  // ── Manual trade ──
  let _pendingTrade=null;
  async function openTradeModal(symbol,direction){
    _pendingTrade={symbol,direction};
    let info={};
    try{ const rows=await fetch('/api/data').then(r=>r.json()).then(d=>d.symbols||[]); info=rows.find(r=>r.symbol===symbol)||{}; }catch(e){}
    const isCrypto=CRYPTO_SYMS.has(symbol); const isB=direction==='BUY'; const color=isB?'var(--green)':'var(--red)';
    document.getElementById('tm-title').innerHTML=`${isB?'&#9650;':'&#9660;'}&nbsp;<span style="color:${color}">${direction}</span>&nbsp;&nbsp;${symbol}${isCrypto?'&nbsp;<span class="crypto-badge">₿</span>':''}`;
    setEl('tm-score',info.score!=null?info.score.toFixed(2):'—'); setEl('tm-h1',info.h1_trend||'—');
    setEl('tm-regime',info.regime||'—'); setEl('tm-spread',info.spread!=null?String(info.spread):'—');
    setEl('tm-mom1',info.mom1||'—'); setEl('tm-mom15',info.mom15||'—');
    const noteEl=document.getElementById('tm-note');
    if(noteEl){ noteEl.className=isCrypto?'trade-note crypto-note':'trade-note'; noteEl.innerHTML=isCrypto?'<span style="color:var(--gold);font-weight:600">₿ CRYPTO MODE</span> — ATR-SL <strong>2.2×</strong> · RR <strong>1:1.8</strong> · Trail <strong>0.4R</strong>':'Forex/Metals — ATR-SL <strong>1.5×</strong> · RR <strong>1:2.5</strong> · Trail <strong>0.6R</strong> · Magic <strong>171717</strong>'; }
    const btn=document.getElementById('tm-exec-btn'); btn.className='trade-confirm-btn '+(isB?'go-buy':'go-sell'); btn.disabled=false; btn.style.color=''; btn.textContent=isB?'▲ EXECUTE BUY':'▼ EXECUTE SELL';
    document.getElementById('trade-overlay').classList.add('open');
  }
  function closeTradeModal(){ document.getElementById('trade-overlay').classList.remove('open'); _pendingTrade=null; }
  async function executeManualTrade(){
    if(!_pendingTrade)return; const{symbol,direction}=_pendingTrade; const btn=document.getElementById('tm-exec-btn'); btn.disabled=true; btn.textContent='SENDING…';
    try{ const res=await fetch('/api/trade/'+symbol,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({direction})}); const d=await res.json();
      if(d.ok){closeTradeModal();}else{btn.textContent='ERR: '+(d.error||'unknown');btn.style.color='var(--red)';setTimeout(()=>{btn.disabled=false;btn.style.color='';btn.textContent=(direction==='BUY'?'▲ EXECUTE BUY':'▼ EXECUTE SELL');},2800);}
    }catch(e){btn.textContent='NETWORK ERROR';setTimeout(()=>{btn.disabled=false;btn.textContent=(direction==='BUY'?'▲ EXECUTE BUY':'▼ EXECUTE SELL');},2800);}
  }

  // ── Close modal ──
  let _pendingClose=null;
  async function openCloseModal(symbol){ let posCount=0; try{const rows=await fetch('/api/data').then(r=>r.json()).then(d=>d.symbols||[]); posCount=(rows.find(r=>r.symbol===symbol)||{}).positions||0;}catch(e){}
    if(posCount===0)return; _pendingClose={symbol}; document.getElementById('cm-symbol').textContent=symbol; document.getElementById('cm-count').textContent=posCount;
    const execBtn=document.getElementById('cm-exec-btn'); execBtn.disabled=false; execBtn.textContent='CLOSE ALL'; document.getElementById('close-overlay').classList.add('open'); }
  function closeCloseModal(){ document.getElementById('close-overlay').classList.remove('open'); _pendingClose=null; }
  async function executeClose(){
    if(!_pendingClose)return;
    const{symbol}=_pendingClose;
    const execBtn=document.getElementById('cm-exec-btn');
    execBtn.disabled=true; execBtn.textContent='CLOSING…';
    // ── Close ALL (from Empty Basket button) ──
    if(symbol==='__ALL__'){
      try{
        const d=await fetch('/api/close_all',{method:'POST'}).then(r=>r.json());
        if(d.ok){
          closeCloseModal();
          const allBtn=document.getElementById('close-all-btn');
          if(allBtn){allBtn.textContent='✓ DONE';setTimeout(()=>{allBtn.textContent='EMPTY BASKET';allBtn.disabled=false;},2000);}
        }else{execBtn.textContent='ERR: '+(d.error||'unknown');setTimeout(()=>{execBtn.disabled=false;execBtn.textContent='CLOSE ALL';},2800);}
      }catch(e){execBtn.textContent='NETWORK ERROR';setTimeout(()=>{execBtn.disabled=false;execBtn.textContent='CLOSE ALL';},2800);}
      return;
    }
    // ── Close single symbol ──
    const c=rowCache.get(symbol);
    if(c&&c.closeBtn){c.closeBtn.classList.add('closing');c.closeBtn.disabled=true;c.closeBtn.textContent='⏳ CLOSING';}
    try{
      const res=await fetch('/api/close/'+symbol,{method:'POST'}); const d=await res.json();
      if(d.ok){closeCloseModal();if(c&&c.closeBtn){c.closeBtn.classList.remove('closing');c.closeBtn.disabled=false;}}
      else{execBtn.textContent='ERR: '+(d.error||'unknown');setTimeout(()=>{execBtn.disabled=false;execBtn.textContent='CLOSE ALL';},2800);if(c&&c.closeBtn){c.closeBtn.classList.remove('closing');c.closeBtn.disabled=false;}}
    }catch(e){execBtn.textContent='NETWORK ERROR';setTimeout(()=>{execBtn.disabled=false;execBtn.textContent='CLOSE ALL';},2800);if(c&&c.closeBtn){c.closeBtn.classList.remove('closing');c.closeBtn.disabled=false;}}
  }

  async function closeAll(){
    let totalPos = 0;
    try{ const d = await fetch('/api/data').then(r=>r.json()); totalPos = (d.account||{}).open_positions || 0; }catch(e){}
    if(totalPos === 0) return;
    document.getElementById('cm-symbol').textContent = 'ALL SYMBOLS';
    document.getElementById('cm-count').textContent = totalPos;
    const execBtn = document.getElementById('cm-exec-btn');
    execBtn.disabled = false; execBtn.textContent = 'CLOSE ALL';
    _pendingClose = { symbol: '__ALL__' };
    document.getElementById('close-overlay').classList.add('open');
  }

  // ── Chart ──
  let chartSymbol=null,chartTf='M1',chartRefreshTimer=null;
  function setTf(tf){ chartTf=tf; document.querySelectorAll('.tf-btn').forEach(b=>b.classList.toggle('active',b.textContent===tf)); document.getElementById('chart-tf-label').textContent=tf+' · 100 CANDLES'; if(chartSymbol){document.getElementById('chart-container').innerHTML='<div class="chart-loading"><span class="chart-loading-dot"></span>LOADING</div>'; ['ci-o','ci-h','ci-l','ci-c'].forEach(id=>document.getElementById(id).textContent='—'); loadChart(chartSymbol);} }
  async function openChart(symbol){ chartSymbol=symbol;chartTf='M1'; document.querySelectorAll('.tf-btn').forEach(b=>b.classList.toggle('active',b.textContent==='M1')); document.getElementById('chart-tf-label').textContent='M1 · 100 CANDLES'; document.getElementById('chart-title').textContent=symbol; document.getElementById('chart-overlay').classList.add('open'); document.getElementById('chart-container').innerHTML='<div class="chart-loading"><span class="chart-loading-dot"></span>LOADING</div>'; ['ci-o','ci-h','ci-l','ci-c'].forEach(id=>document.getElementById(id).textContent='—'); await loadChart(symbol); clearInterval(chartRefreshTimer); chartRefreshTimer=setInterval(()=>{if(chartSymbol)loadChart(chartSymbol);},5000); }
  function closeChart(e){ if(e&&e.target!==document.getElementById('chart-overlay'))return; chartSymbol=null; clearInterval(chartRefreshTimer); document.getElementById('chart-overlay').classList.remove('open'); }
  document.addEventListener('keydown',e=>{ if(e.key==='Escape'){closeTradeModal();closeCloseModal();closeChart();} });
  async function loadChart(symbol){ try{ const candles=await fetch(`/api/candles/${symbol}?tf=${chartTf}`).then(r=>r.json()); if(!candles.length)return; renderChart(candles); }catch(e){document.getElementById('chart-container').innerHTML='<div class="chart-loading" style="color:var(--red)">ERROR LOADING DATA</div>';} }
  function renderChart(candles){
    const W=780,H=300,PAD={top:16,right:12,bottom:28,left:58};
    const cw=(W-PAD.left-PAD.right)/candles.length; const candleW=Math.max(Math.floor(cw*0.7),1);
    const minP=Math.min(...candles.map(c=>c.l)); const maxP=Math.max(...candles.map(c=>c.h)); const range=maxP-minP||1;
    const chartH=H-PAD.top-PAD.bottom;
    const py=v=>PAD.top+chartH-((v-minP)/range)*chartH; const px=i=>PAD.left+i*cw+cw/2;
    const last=candles[candles.length-1]; const digits=last.c<10?5:last.c<1000?3:1;
    document.getElementById('ci-o').textContent=last.o.toFixed(digits); document.getElementById('ci-h').textContent=last.h.toFixed(digits);
    document.getElementById('ci-l').textContent=last.l.toFixed(digits); document.getElementById('ci-c').textContent=last.c.toFixed(digits);
    const gridLines=[]; for(let i=0;i<=4;i++){const v=minP+(range/4)*i,y=py(v); gridLines.push(`<line x1="${PAD.left}" y1="${y}" x2="${W-PAD.right}" y2="${y}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/><text x="${PAD.left-6}" y="${y+4}" text-anchor="end" fill="#3d5068" font-size="9" font-family="'JetBrains Mono',monospace">${v.toFixed(digits)}</text>`);}
    const timeLabels=[]; const step=Math.max(1,Math.floor(candles.length/5)); for(let i=0;i<candles.length;i+=step){const d=new Date(candles[i].t*1000); const lbl=d.getUTCHours().toString().padStart(2,'0')+':'+d.getUTCMinutes().toString().padStart(2,'0'); timeLabels.push(`<text x="${px(i)}" y="${H-6}" text-anchor="middle" fill="#3d5068" font-size="9" font-family="'JetBrains Mono',monospace">${lbl}</text>`);}
    const candleBodies=candles.map((c,i)=>{ const bull=c.c>=c.o,color=bull?'#00e5a0':'#ff4d6a'; const bodyTop=py(Math.max(c.o,c.c)),bodyBot=py(Math.min(c.o,c.c)); const bodyH=Math.max(bodyBot-bodyTop,1),cx=px(i),half=candleW/2; return`<line x1="${cx}" y1="${py(c.h)}" x2="${cx}" y2="${py(c.l)}" stroke="rgba(255,255,255,0.35)" stroke-width="1"/><rect x="${cx-half}" y="${bodyTop}" width="${candleW}" height="${bodyH}" fill="${color}" rx="0.5"/>`;}).join('');
    const curY=py(last.c),curColor=last.c>=last.o?'#00e5a0':'#ff4d6a';
    const priceLine=`<line x1="${PAD.left}" y1="${curY}" x2="${W-PAD.right}" y2="${curY}" stroke="${curColor}" stroke-width="1" stroke-dasharray="3,3" opacity="0.6"/><rect x="${W-PAD.right}" y="${curY-9}" width="52" height="16" fill="${curColor}" rx="2"/><text x="${W-PAD.right+26}" y="${curY+4}" text-anchor="middle" fill="#080c10" font-size="9" font-weight="700" font-family="'JetBrains Mono',monospace">${last.c.toFixed(digits)}</text>`;
    document.getElementById('chart-container').innerHTML=`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:320px;display:block;background:var(--bg);border:1px solid var(--border);border-radius:3px">${gridLines.join('')}${timeLabels.join('')}${candleBodies}${priceLine}</svg>`;
  }

  async function toggleSym(symbol,btn){ btn.classList.add('pending'); try{const r=await fetch('/api/toggle/'+symbol,{method:'POST'}); const d=await r.json(); btn.className='toggle-btn '+(d.enabled?'enabled':'disabled'); btn.querySelector('span').textContent=d.enabled?'ON':'OFF';}catch(e){} btn.classList.remove('pending'); }

  // ── Settings ──
  const SETTINGS_KEYS=['base_risk_pct','max_portfolio_risk','rr','max_pos','min_entry_dist','min_score','atr_sl_mult','trail_trigger','trail_step','utc_start','utc_end','metals_time_filter','deviation','crypto_rr','crypto_atr_sl_mult','crypto_trail_trigger','crypto_min_score','crypto_max_pos','sniper_breakout_rr','sniper_breakout_atr','sniper_breakout_trail','sniper_breakout_maxpos','sniper_breakout_score','sniper_impulse_rr','sniper_impulse_atr','sniper_impulse_trail','sniper_impulse_maxpos','sniper_impulse_score','sniper_reversion_rr','sniper_reversion_atr','sniper_reversion_trail','sniper_reversion_maxpos','sniper_reversion_score'];
  let _origValues={},_settingsOpen=false;

  function openSettings(){
    _settingsOpen=true;
    fetch('/api/data').then(r=>r.json()).then(d=>{
      const cfg=d.config||{}; _origValues={...cfg};
      SETTINGS_KEYS.forEach(k=>{ const el=document.getElementById('s-'+k); if(el&&cfg[k]!==undefined){el.value=cfg[k];el.classList.remove('changed');el.dataset.orig=cfg[k];el.oninput=()=>el.classList.toggle('changed',String(el.value)!==String(el.dataset.orig));} });
      updateStrategies(d.strategies);
      updateServerBtn(d.bot_paused||false);
    });
    document.getElementById('settings-save-btn').textContent='✓ APPLY SETTINGS';
    document.getElementById('settings-save-btn').disabled=false;
    document.getElementById('sm-msg').textContent='';
    document.getElementById('sm-symbol').value='';
    document.getElementById('sm-spread').value='20';
    document.getElementById('sm-filter').value='';
    document.getElementById('sm-add-btn').textContent='+ ADD';
    smLoadSymbols();
    document.getElementById('settings-overlay').classList.add('open');
  }
  function closeSettings(){ _settingsOpen=false; document.getElementById('settings-overlay').classList.remove('open'); SETTINGS_KEYS.forEach(k=>{const el=document.getElementById('s-'+k);if(el)el.classList.remove('changed');}); }
  function settingsOverlayClick(e){ if(e.target===document.getElementById('settings-overlay')&&e.offsetY<8)closeSettings(); }

  async function saveSettings(){
    const btn=document.getElementById('settings-save-btn'); btn.disabled=true; btn.textContent='SAVING…';
    const payload={}; SETTINGS_KEYS.forEach(k=>{const el=document.getElementById('s-'+k);if(el){const v=parseFloat(el.value);if(!isNaN(v))payload[k]=v;}});
    try{ const res=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const d=await res.json();
      if(d.ok){ _cfgRendered=false; btn.textContent='✓ SAVED'; SETTINGS_KEYS.forEach(k=>{const el=document.getElementById('s-'+k);if(el&&d.config[k]!==undefined){el.dataset.orig=d.config[k];el.classList.remove('changed');}}); setTimeout(()=>{btn.disabled=false;btn.textContent='✓ APPLY SETTINGS';},1500); }
      else{btn.textContent='ERROR';setTimeout(()=>{btn.disabled=false;btn.textContent='✓ APPLY SETTINGS';},2500);}
    }catch(e){btn.textContent='NETWORK ERROR';setTimeout(()=>{btn.disabled=false;btn.textContent='✓ APPLY SETTINGS';},2500);}
  }

  async function resetSettings(){
    const btn=document.getElementById('settings-default-btn'); btn.disabled=true; btn.textContent='RESETTING…';
    try{ const res=await fetch('/api/settings/reset',{method:'POST'}); const d=await res.json();
      if(d.ok){
        _cfgRendered=false;
        SETTINGS_KEYS.forEach(k=>{const el=document.getElementById('s-'+k);if(el&&d.config[k]!==undefined){el.value=d.config[k];el.dataset.orig=d.config[k];el.classList.remove('changed');}});
        updateStrategies(d.strategies);
        btn.textContent='✓ RESET';
      } else { btn.textContent='ERROR'; }
    }catch(e){ btn.textContent='ERROR'; }
    setTimeout(()=>{btn.disabled=false;btn.textContent='↺ DEFAULT';},1800);
  }

  function updateServerBtn(paused){
    const btn=document.getElementById('srv-btn'),lbl=document.getElementById('srv-label');
    const banner=document.getElementById('paused-banner'),pill=document.getElementById('live-pill');
    const dot=document.getElementById('live-dot'),label=document.getElementById('live-label');
    if(paused){ btn.className='server-toggle-btn paused';btn.textContent='▶ RESUME'; if(lbl)lbl.textContent='Bot paused'; if(banner)banner.classList.add('visible'); if(pill){pill.style.background='rgba(255,184,48,0.08)';pill.style.borderColor='rgba(255,184,48,0.25)';pill.style.color='var(--amber)';} if(dot)dot.style.background='var(--amber)'; if(label)label.textContent='PAUSED';
    }else{ btn.className='server-toggle-btn running';btn.textContent='⏸ PAUSE'; if(lbl)lbl.textContent='Bot running'; if(banner)banner.classList.remove('visible'); if(pill){pill.style.background='';pill.style.borderColor='';pill.style.color='';} if(dot)dot.style.background=''; if(label)label.textContent='LIVE';}
  }
  async function toggleServer(){ const btn=document.getElementById('srv-btn'); btn.disabled=true; const currentlyPaused=btn.classList.contains('paused'); try{const res=await fetch('/api/server',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paused:!currentlyPaused})}); const d=await res.json(); if(d.ok)updateServerBtn(d.paused);}catch(e){} btn.disabled=false; }

  // ── Symbol Manager (embedded in Settings) ──
  let _smSymbols = [];
  let _smOverrides = {};   // symbol → {rr, atr_sl_mult, trail_trigger, min_score, max_pos}

  async function smLoadOverrides() {
    try {
      const d = await fetch('/api/overrides').then(r => r.json());
      _smOverrides = d.overrides || {};
    } catch(e) { console.error('smLoadOverrides', e); }
  }

  function smToggleOverride(sym, btn) {
    const row = document.getElementById('ovr-row-' + sym);
    if (!row) return;
    const visible = row.style.display !== 'none';
    document.querySelectorAll('[id^="ovr-row-"]').forEach(r => { r.style.display = 'none'; });
    row.style.display = visible ? 'none' : 'table-row';
  }

  async function smSaveOverride(sym) {
    const keys = ['rr', 'atr_sl_mult', 'trail_trigger', 'min_score', 'max_pos'];
    const payload = {};
    keys.forEach(k => {
      const el = document.getElementById('ovr-' + sym + '-' + k);
      if (el && el.value.trim() !== '') {
        const v = parseFloat(el.value);
        if (!isNaN(v)) payload[k] = (k === 'max_pos') ? Math.round(v) : v;
      }
    });
    if (Object.keys(payload).length === 0) return smClearOverride(sym);
    try {
      const res = await fetch('/api/overrides/' + sym, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const d = await res.json();
      if (d.ok) {
        _smOverrides[sym] = d.overrides;
        await smLoadSymbols();
        document.getElementById('sm-msg').style.color = 'var(--amber)';
        document.getElementById('sm-msg').textContent = '\u26a1 Override saved for ' + sym;
      } else {
        document.getElementById('sm-msg').style.color = 'var(--red)';
        document.getElementById('sm-msg').textContent = 'Error: ' + (d.error || 'unknown');
      }
    } catch(e) {
      document.getElementById('sm-msg').style.color = 'var(--red)';
      document.getElementById('sm-msg').textContent = 'Network error';
    }
  }

  async function smClearOverride(sym) {
    try {
      const res = await fetch('/api/overrides/' + sym, { method: 'DELETE' });
      const d = await res.json();
      if (d.ok) {
        delete _smOverrides[sym];
        await smLoadSymbols();
        document.getElementById('sm-msg').style.color = 'var(--muted)';
        document.getElementById('sm-msg').textContent = sym + ' overrides cleared';
      }
    } catch(e) {
      document.getElementById('sm-msg').style.color = 'var(--red)';
      document.getElementById('sm-msg').textContent = 'Network error';
    }
  }

  async function smLoadSymbols() {
    try {
      await smLoadOverrides();
      const d = await fetch('/api/symbols').then(r => r.json());
      _smSymbols = d.symbols || [];
      document.getElementById('sm-count').textContent = _smSymbols.length;
      smRenderTable(_smSymbols);
    } catch(e) { console.error('smLoad', e); }
  }

  function smRenderTable(syms) {
    const catColors = {EUR:'var(--accent2)',GBP:'#a78bfa',USD:'var(--cyan)',Metals:'var(--gold)',Crypto:'var(--gold)'};
    const tbody = document.getElementById('sm-tbody');
    tbody.innerHTML = syms.map(s => {
      const cc = catColors[s.category] || 'var(--muted)';
      const isCrypto = s.is_crypto, isMetal = s.is_metal;
      const badge = isCrypto ? '<span style="font-size:7px;padding:1px 4px;border-radius:2px;background:rgba(247,199,90,0.12);border:1px solid rgba(247,199,90,0.3);color:var(--gold);margin-left:4px">₿</span>'
                  : isMetal  ? '<span style="font-size:7px;padding:1px 4px;border-radius:2px;background:rgba(0,212,255,0.10);border:1px solid rgba(0,212,255,0.25);color:var(--cyan);margin-left:4px">⬡</span>' : '';
      const ov = _smOverrides[s.symbol] || {};
      const hasOverride = Object.keys(ov).length > 0;
      const ovDot = hasOverride ? '<span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--amber);margin-left:4px;vertical-align:middle" title="Has overrides"></span>' : '';
      return `<tr data-sym="${s.symbol}" style="border-bottom:1px solid rgba(255,255,255,0.03)">
        <td style="padding:4px 6px;font-weight:700;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:72px">${s.symbol}${badge}${ovDot}</td>
        <td style="padding:4px 6px;text-align:center;overflow:hidden;max-width:52px"><span style="font-size:9px;font-weight:600;color:${cc}">${s.category}</span></td>
        <td style="padding:4px 6px;text-align:right;font-size:10px;color:var(--muted);max-width:46px">${s.max_spread}</td>
        <td style="padding:4px 6px;text-align:center;white-space:nowrap">
          <button onclick="smToggleOverride('${s.symbol}',this)" style="height:18px;padding:0 5px;border-radius:3px;font-size:8px;font-weight:700;cursor:pointer;border:1px solid ${hasOverride?'rgba(255,184,48,0.4)':'rgba(255,255,255,0.1)'};background:${hasOverride?'rgba(255,184,48,0.10)':'rgba(255,255,255,0.03)'};color:${hasOverride?'var(--amber)':'var(--muted)'};font-family:var(--mono);margin-right:2px" title="Per-symbol overrides">OVR</button>
          <button onclick="smEditSymbol('${s.symbol}','${s.category}',${s.max_spread})" style="height:18px;padding:0 5px;border-radius:3px;font-size:8px;font-weight:700;cursor:pointer;border:1px solid rgba(0,212,255,0.28);background:rgba(0,212,255,0.07);color:var(--cyan);font-family:var(--mono);margin-right:2px">EDT</button>
          <button onclick="smDeleteSymbol('${s.symbol}',this)" style="height:18px;padding:0 5px;border-radius:3px;font-size:8px;font-weight:700;cursor:pointer;border:1px solid rgba(255,77,106,0.28);background:rgba(255,77,106,0.07);color:var(--red);font-family:var(--mono)">DEL</button>
        </td>
      </tr>
      <tr id="ovr-row-${s.symbol}" style="display:none;background:rgba(255,184,48,0.03);border-bottom:1px solid rgba(255,184,48,0.12)">
        <td colspan="4" style="padding:6px 10px">
          <div style="font-size:8px;font-weight:700;letter-spacing:1.5px;color:var(--amber);text-transform:uppercase;margin-bottom:6px">⚡ Overrides for ${s.symbol} <span style="font-weight:400;color:var(--muted)">(blank = use global/category default)</span></div>
          <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-bottom:6px">
            ${['rr','atr_sl_mult','trail_trigger','min_score','max_pos'].map(k => {
              const labels = {rr:'RR',atr_sl_mult:'ATR-SL',trail_trigger:'Trail×R',min_score:'Min Score',max_pos:'Max Pos'};
              const steps  = {rr:'0.1',atr_sl_mult:'0.1',trail_trigger:'0.05',min_score:'0.01',max_pos:'1'};
              const val = ov[k] != null ? ov[k] : '';
              return `<div>
                <div style="font-size:8px;color:var(--muted);margin-bottom:2px;letter-spacing:1px">${labels[k]}</div>
                <input id="ovr-${s.symbol}-${k}" type="number" step="${steps[k]}" value="${val}" placeholder="default"
                  style="width:100%;height:20px;background:var(--bg3);border:1px solid rgba(255,184,48,0.25);border-radius:3px;color:var(--amber);font-family:var(--mono);font-size:10px;text-align:right;padding:0 4px">
              </div>`;
            }).join('')}
          </div>
          <div style="display:flex;gap:5px">
            <button onclick="smSaveOverride('${s.symbol}')" style="height:20px;padding:0 10px;border-radius:3px;font-size:8px;font-weight:700;cursor:pointer;border:1px solid rgba(255,184,48,0.35);background:rgba(255,184,48,0.10);color:var(--amber);font-family:var(--mono)">✓ APPLY</button>
            <button onclick="smClearOverride('${s.symbol}')" style="height:20px;padding:0 10px;border-radius:3px;font-size:8px;font-weight:700;cursor:pointer;border:1px solid rgba(255,77,106,0.28);background:rgba(255,77,106,0.05);color:var(--red);font-family:var(--mono)">✕ CLEAR ALL</button>
          </div>
        </td>
      </tr>`;
    }).join('') || '<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--muted)">No symbols</td></tr>';
  }

  function smFilterTable() {
    const q = document.getElementById('sm-filter').value.toUpperCase().trim();
    const filtered = q ? _smSymbols.filter(s => s.symbol.includes(q) || s.category.toUpperCase().includes(q)) : _smSymbols;
    smRenderTable(filtered);
  }

  function smEditSymbol(sym, cat, spread) {
    document.getElementById('sm-symbol').value = sym;
    document.getElementById('sm-category').value = cat;
    document.getElementById('sm-spread').value = spread;
    document.getElementById('sm-symbol').focus();
    document.getElementById('sm-add-btn').textContent = '✓ SAVE';
    document.getElementById('sm-msg').style.color = 'var(--cyan)';
    document.getElementById('sm-msg').textContent = `Editing ${sym} — change values and click SAVE`;
  }

  async function smAddSymbol() {
    const btn = document.getElementById('sm-add-btn');
    const sym = document.getElementById('sm-symbol').value.toUpperCase().trim();
    const cat = document.getElementById('sm-category').value;
    const spread = parseFloat(document.getElementById('sm-spread').value);
    const msgEl = document.getElementById('sm-msg');
    if (!sym) { msgEl.style.color='var(--red)'; msgEl.textContent='Enter a symbol name'; return; }
    if (isNaN(spread) || spread <= 0) { msgEl.style.color='var(--red)'; msgEl.textContent='Enter a valid max spread'; return; }
    btn.disabled = true; btn.textContent = '…';
    try {
      const res = await fetch('/api/symbols', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({symbol: sym, category: cat, max_spread: spread})
      });
      const d = await res.json();
      if (d.ok) {
        msgEl.style.color = 'var(--green)';
        msgEl.textContent = `✓ ${sym} saved (${cat}, spread ${spread})`;
        document.getElementById('sm-symbol').value = '';
        document.getElementById('sm-spread').value = '20';
        btn.textContent = '+ ADD';
        await smLoadSymbols();
      } else {
        msgEl.style.color = 'var(--red)'; msgEl.textContent = 'Error: ' + (d.error || 'unknown');
        btn.textContent = '+ ADD';
      }
    } catch(e) { msgEl.style.color='var(--red)'; msgEl.textContent='Network error'; btn.textContent='+ ADD'; }
    btn.disabled = false;
  }

  async function smDeleteSymbol(sym, btn) {
    if (!confirm(`Remove ${sym} from active symbols?`)) return;
    btn.disabled = true; btn.textContent = '…';
    try {
      const res = await fetch('/api/symbols/'+sym, {method: 'DELETE'});
      const d = await res.json();
      if (d.ok) {
        document.getElementById('sm-msg').style.color = 'var(--amber)';
        document.getElementById('sm-msg').textContent = `${sym} removed`;
        await smLoadSymbols();
      } else {
        btn.textContent = 'ERR'; setTimeout(()=>{btn.disabled=false;btn.textContent='DEL';},2000);
      }
    } catch(e) { btn.disabled=false; btn.textContent='DEL'; }
  }

  async function smResetSymbols() {
    if (!confirm('Reset symbol list to factory defaults? All custom changes will be lost.')) return;
    const msgEl = document.getElementById('sm-msg');
    try {
      const res = await fetch('/api/symbols/reset', {method: 'POST'});
      const d = await res.json();
      if (d.ok) {
        msgEl.style.color = 'var(--green)';
        msgEl.textContent = `✓ Reset to ${d.count} default symbols`;
        document.getElementById('sm-filter').value = '';
        document.getElementById('sm-symbol').value = '';
        document.getElementById('sm-spread').value = '20';
        document.getElementById('sm-add-btn').textContent = '+ ADD';
        await smLoadSymbols();
      } else {
        msgEl.style.color = 'var(--red)'; msgEl.textContent = 'Reset failed';
      }
    } catch(e) { msgEl.style.color='var(--red)'; msgEl.textContent='Network error'; }
  }

  refresh();
  setInterval(refresh, 2000);

  // ═══════════════════════════════════════════════════════════════
  //  TRADES POPUP
  // ═══════════════════════════════════════════════════════════════
  let _tradesTab = 'open';
  let _histData = [];
  let _histFilter = 'all';

  function openTrades() {
    document.getElementById('trades-overlay').classList.add('open');
    loadTradesData();
  }
  function closeTrades() {
    document.getElementById('trades-overlay').classList.remove('open');
  }
  function switchTradesTab(tab) {
    _tradesTab = tab;
    document.getElementById('tab-open').classList.toggle('active', tab === 'open');
    document.getElementById('tab-hist').classList.toggle('active', tab === 'hist');
    document.getElementById('pane-open').style.display = tab === 'open' ? 'flex' : 'none';
    document.getElementById('pane-hist').style.display = tab === 'hist' ? 'flex' : 'none';
    // Ensure pane-open uses flex-direction:column when visible
    if (tab === 'open') { document.getElementById('pane-open').style.flexDirection = 'column'; }
    if (tab === 'hist') { document.getElementById('pane-hist').style.flexDirection = 'column'; }
  }

  async function loadTradesData() {
    try {
      const [openResp, histResp] = await Promise.all([
        fetch('/api/trades/open').then(r => r.json()),
        fetch('/api/trades/history').then(r => r.json()),
      ]);
      renderOpenTrades(openResp.trades || []);
      _histData = histResp.trades || [];
      renderHistoryTrades(_histData, _histFilter);
    } catch(e) {
      document.getElementById('open-tbody').innerHTML = '<tr><td colspan="11" style="text-align:center;padding:40px;color:var(--red);letter-spacing:1px">Error loading data</td></tr>';
    }
  }

  function fmtTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toISOString().slice(0,16).replace('T',' ');
  }
  function fmtDuration(secs) {
    if (secs < 60) return secs + 's';
    if (secs < 3600) return Math.floor(secs/60) + 'm ' + (secs%60) + 's';
    const h = Math.floor(secs/3600), m = Math.floor((secs%3600)/60);
    return h + 'h ' + m + 'm';
  }
  function pnlClass(v) { return v > 0 ? 't-pos' : v < 0 ? 't-neg' : 't-zero'; }
  function pnlFmt(v) { return (v >= 0 ? '+$' : '-$') + Math.abs(v).toFixed(2); }

  function renderOpenTrades(trades) {
    const tbody = document.getElementById('open-tbody');
    if (!trades.length) {
      tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:60px;color:var(--muted);letter-spacing:2px;font-size:11px">NO OPEN POSITIONS</td></tr>';
      document.getElementById('open-summary').style.display = 'none';
      return;
    }
    let totalPnl = 0, totalLots = 0, buys = 0, sells = 0;
    tbody.innerHTML = trades.map(t => {
      const dir = t.type === 0 ? 'BUY' : 'SELL';
      const dirCls = t.type === 0 ? 't-buy' : 't-sell';
      const pnl = parseFloat(t.profit);
      totalPnl += pnl; totalLots += t.volume;
      if (t.type === 0) buys++; else sells++;
      const digits = t.price_open < 10 ? 5 : t.price_open < 1000 ? 3 : 1;
      return `<tr>
        <td style="color:var(--muted);font-size:10px">#${t.ticket}</td>
        <td style="font-weight:700">${t.symbol}</td>
        <td class="${dirCls}" style="font-weight:700;letter-spacing:1px">${dir}</td>
        <td>${t.volume.toFixed(2)}</td>
        <td>${t.price_open.toFixed(digits)}</td>
        <td>${t.price_current.toFixed(digits)}</td>
        <td style="color:var(--red)">${t.sl ? t.sl.toFixed(digits) : '—'}</td>
        <td style="color:var(--green)">${t.tp ? t.tp.toFixed(digits) : '—'}</td>
        <td style="color:var(--muted);font-size:10px">${fmtTime(t.time)}</td>
        <td style="color:var(--muted);font-size:10px;max-width:140px;overflow:hidden;text-overflow:ellipsis">${t.comment || '—'}</td>
        <td class="${pnlClass(pnl)}" style="font-weight:700">${pnlFmt(pnl)}</td>
      </tr>`;
    }).join('');
    document.getElementById('open-summary').style.display = 'flex';
    document.getElementById('sum-open-count').textContent = trades.length;
    document.getElementById('sum-open-lots').textContent = totalLots.toFixed(2);
    const pnlEl = document.getElementById('sum-open-pnl');
    pnlEl.textContent = pnlFmt(totalPnl);
    pnlEl.className = 'trades-summary-value ' + pnlClass(totalPnl);
    document.getElementById('sum-open-sides').innerHTML = `<span class="t-buy">${buys}</span> / <span class="t-sell">${sells}</span>`;
  }

  function filterHist(f, btn) {
    _histFilter = f;
    document.querySelectorAll('.hist-filter-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderHistoryTrades(_histData, f);
  }

  function renderHistoryTrades(all, filter) {
    const today = new Date().toISOString().slice(0,10);
    let trades = all;
    if (filter === 'win')   trades = all.filter(t => t.profit > 0);
    if (filter === 'loss')  trades = all.filter(t => t.profit <= 0);
    if (filter === 'today') trades = all.filter(t => fmtTime(t.time_close).startsWith(today));
    document.getElementById('hist-count-label').textContent = trades.length + ' trades';
    const tbody = document.getElementById('hist-tbody');
    if (!trades.length) {
      tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:60px;color:var(--muted);letter-spacing:2px;font-size:11px">NO HISTORY</td></tr>';
      document.getElementById('hist-summary').style.display = 'none';
      return;
    }
    let totalPnl = 0, wins = 0, losses = 0, winSum = 0, lossSum = 0;
    tbody.innerHTML = trades.map(t => {
      const dir = t.type === 0 ? 'BUY' : 'SELL';
      const dirCls = t.type === 0 ? 't-buy' : 't-sell';
      const pnl = parseFloat(t.profit);
      totalPnl += pnl;
      if (pnl > 0) { wins++; winSum += pnl; } else { losses++; lossSum += pnl; }
      const duration = t.time_close && t.time ? fmtDuration(t.time_close - t.time) : '—';
      const digits = t.price_open < 10 ? 5 : t.price_open < 1000 ? 3 : 1;
      return `<tr>
        <td style="color:var(--muted);font-size:10px">#${t.ticket}</td>
        <td style="font-weight:700">${t.symbol}</td>
        <td class="${dirCls}" style="font-weight:700;letter-spacing:1px">${dir}</td>
        <td>${t.volume.toFixed(2)}</td>
        <td>${t.price_open.toFixed(digits)}</td>
        <td>${t.price_close.toFixed(digits)}</td>
        <td style="color:var(--muted);font-size:10px">${fmtTime(t.time)}</td>
        <td style="color:var(--muted);font-size:10px">${fmtTime(t.time_close)}</td>
        <td style="color:var(--muted);font-size:10px">${duration}</td>
        <td style="color:var(--muted);font-size:10px;max-width:140px;overflow:hidden;text-overflow:ellipsis">${t.comment || '—'}</td>
        <td class="${pnlClass(pnl)}" style="font-weight:700">${pnlFmt(pnl)}</td>
      </tr>`;
    }).join('');
    document.getElementById('hist-summary').style.display = 'flex';
    document.getElementById('sum-hist-count').textContent = trades.length;
    const wr = trades.length ? Math.round(wins/trades.length*100) : 0;
    const wrEl = document.getElementById('sum-hist-wr');
    wrEl.textContent = wr + '%';
    wrEl.className = 'trades-summary-value ' + (wr >= 50 ? 't-pos' : 't-neg');
    const pnlEl = document.getElementById('sum-hist-pnl');
    pnlEl.textContent = pnlFmt(totalPnl);
    pnlEl.className = 'trades-summary-value ' + pnlClass(totalPnl);
    document.getElementById('sum-hist-wl').innerHTML = `<span class="t-pos">${wins}</span> / <span class="t-neg">${losses}</span>`;
    document.getElementById('sum-hist-avgwin').textContent = wins ? '+$' + (winSum/wins).toFixed(2) : '$0.00';
    document.getElementById('sum-hist-avgloss').textContent = losses ? '-$' + Math.abs(lossSum/losses).toFixed(2) : '$0.00';
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeTrades();
  });
</script>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route("/")
def dashboard():
    return render_template_string(HTML)


@app.route("/api/data")
def api_data():
    with _lock:
        return jsonify(DASHBOARD)


@app.route("/api/toggle/<symbol>", methods=["POST"])
def api_toggle(symbol):
    if symbol not in SYMBOLS:
        return jsonify({"error": "unknown symbol"}), 400
    with _disabled_lock:
        if symbol in DISABLED_SYMBOLS:
            DISABLED_SYMBOLS.discard(symbol)
            enabled = True
            log(f"▶ {symbol} ENABLED")
        else:
            DISABLED_SYMBOLS.add(symbol)
            enabled = False
            log(f"⏸ {symbol} DISABLED")
        save_disabled(DISABLED_SYMBOLS)
    return jsonify({"symbol": symbol, "enabled": enabled})


@app.route("/api/strategy/<name>", methods=["POST"])
def api_toggle_strategy(name):
    if name not in STRATEGIES:
        return jsonify({"error": "unknown strategy"}), 400
    with _cfg_lock:
        STRATEGIES[name]["enabled"] = not STRATEGIES[name]["enabled"]
        enabled = STRATEGIES[name]["enabled"]
    with _lock:
        DASHBOARD["strategies"] = STRATEGIES
    log(f"⚙ STRATEGY {name} {'ENABLED' if enabled else 'DISABLED'}")
    cfg = _build_cfg()
    save_settings({k: cfg[k] for k in cfg if k not in ("magic","symbols_count")} |
                  {f"en_{n}": (1 if STRATEGIES[n]["enabled"] else 0) for n in STRATEGIES})
    return jsonify({"strategy": name, "enabled": enabled})


@app.route("/api/log")
def api_log_endpoint():
    with _lock:
        return jsonify(DASHBOARD["log"][:200])


@app.route("/api/trades/open")
def api_trades_open():
    """Return all currently open positions managed by this bot."""
    positions = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    trades = []
    for p in positions:
        tick = mt5.symbol_info_tick(p.symbol)
        current = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask if tick else p.price_open
        trades.append({
            "ticket":        p.ticket,
            "symbol":        p.symbol,
            "type":          p.type,   # 0=BUY, 1=SELL
            "volume":        p.volume,
            "price_open":    p.price_open,
            "price_current": round(current, 6),
            "sl":            p.sl,
            "tp":            p.tp,
            "profit":        round(p.profit, 2),
            "time":          p.time,
            "comment":       p.comment,
        })
    trades.sort(key=lambda x: x["time"], reverse=True)
    return jsonify({"ok": True, "trades": trades, "count": len(trades)})


@app.route("/api/trades/history")
def api_trades_history():
    """Return closed trade history for this bot's magic number (last 500)."""
    from datetime import timedelta
    date_from = datetime(2000, 1, 1)
    date_to   = datetime.now() + timedelta(days=1)
    deals = mt5.history_deals_get(date_from, date_to) or []
    # Filter: only entry/exit deals with our magic, exclude balance ops
    magic_deals = [d for d in deals if d.magic == MAGIC and d.entry in (0, 1)]
    # Group by position_id to pair open/close
    pos_map: dict = {}
    for d in magic_deals:
        pid = d.position_id
        if pid not in pos_map:
            pos_map[pid] = []
        pos_map[pid].append(d)
    trades = []
    for pid, ds in pos_map.items():
        ds_sorted = sorted(ds, key=lambda x: x.time)
        open_deal  = next((d for d in ds_sorted if d.entry == 0), None)
        close_deal = next((d for d in reversed(ds_sorted) if d.entry == 1), None)
        if open_deal is None:
            continue
        pnl = sum(d.profit for d in ds_sorted)
        trades.append({
            "ticket":      pid,
            "symbol":      open_deal.symbol,
            "type":        open_deal.type,  # 0=BUY, 1=SELL — already correct for entry deals
            "volume":      open_deal.volume,
            "price_open":  open_deal.price,
            "price_close": close_deal.price if close_deal else 0.0,
            "time":        open_deal.time,
            "time_close":  close_deal.time if close_deal else None,
            "profit":      round(pnl, 2),
            "comment":     open_deal.comment,
        })
    trades.sort(key=lambda x: x["time"], reverse=True)
    return jsonify({"ok": True, "trades": trades[:500], "count": len(trades)})


@app.route("/api/candles/<symbol>")
def api_candles(symbol):
    if symbol not in SYMBOLS:
        return jsonify({"error": "unknown symbol"}), 400
    TF_MAP = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    }
    tf = TF_MAP.get(request.args.get("tf", "M1").upper(), mt5.TIMEFRAME_M1)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 100)
    if rates is None or len(rates) == 0:
        return jsonify([])
    return jsonify([
        {"t": int(r["time"]), "o": float(r["open"]), "h": float(r["high"]),
         "l": float(r["low"]),  "c": float(r["close"])}
        for r in rates
    ])


@app.route("/api/close/<symbol>", methods=["POST"])
def api_close_positions(symbol):
    if symbol not in SYMBOLS:
        return jsonify({"ok": False, "error": "unknown symbol"}), 400
    positions = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == MAGIC]
    if not positions:
        return jsonify({"ok": False, "error": "no open positions for this symbol"})
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        return jsonify({"ok": False, "error": "symbol info unavailable"}), 400
    closed, errors = 0, []
    for p in positions:
        close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        close_price = tick.bid            if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
            "volume": p.volume, "type": close_type, "position": p.ticket,
            "price": close_price, "deviation": DEVIATION, "magic": MAGIC,
            "comment": "MERGED MANUAL CLOSE", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
            profit    = round(p.profit, 2)
            log(f"🔴 CLOSED {direction} {symbol} #{p.ticket} lot={p.volume:.2f} P&L={('+$' if profit>=0 else '-$')}{abs(profit):.2f}")
            closed += 1
        else:
            code = res.retcode if res else "N/A"
            errors.append(f"ticket {p.ticket} retcode={code}")
            log(f"❌ CLOSE failed {symbol} #{p.ticket} retcode={code}")
    if closed > 0:
        return jsonify({"ok": True, "closed": closed, "errors": errors})
    return jsonify({"ok": False, "error": "; ".join(errors) or "all closes failed"})


@app.route("/api/close_all", methods=["POST"])
def api_close_all():
    all_pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    if not all_pos:
        return jsonify({"ok": False, "error": "no open positions"})
    closed, errors = 0, []
    for p in all_pos:
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            errors.append(f"{p.symbol} tick unavailable")
            continue
        close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        close_price = tick.bid            if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
            "volume": p.volume, "type": close_type, "position": p.ticket,
            "price": close_price, "deviation": DEVIATION, "magic": MAGIC,
            "comment": "MERGED CLOSE ALL", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
            profit    = round(p.profit, 2)
            log(f"🔴 CLOSE ALL: {direction} {p.symbol} #{p.ticket} lot={p.volume:.2f} P&L={('+$' if profit>=0 else '-$')}{abs(profit):.2f}")
            closed += 1
        else:
            code = res.retcode if res else "N/A"
            errors.append(f"{p.symbol} #{p.ticket} retcode={code}")
            log(f"❌ CLOSE ALL failed {p.symbol} #{p.ticket} retcode={code}")
    log(f"🔴 CLOSE ALL complete — {closed}/{len(all_pos)} positions closed")
    return jsonify({"ok": closed > 0, "closed": closed, "total": len(all_pos), "errors": errors})


@app.route("/api/trade/<symbol>", methods=["POST"])
def api_manual_trade(symbol):
    if symbol not in SYMBOLS:
        return jsonify({"ok": False, "error": "unknown symbol"}), 400
    body      = request.get_json(silent=True) or {}
    direction = (body.get("direction") or "").upper()
    if direction not in ("BUY", "SELL"):
        return jsonify({"ok": False, "error": "direction must be BUY or SELL"}), 400

    df1, df15, df_h1 = get_data(symbol)
    if df1 is None:
        return jsonify({"ok": False, "error": "no data for symbol"}), 400

    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    acc  = mt5.account_info()
    if tick is None or info is None or acc is None:
        return jsonify({"ok": False, "error": "symbol/account info unavailable"}), 400

    spread = (tick.ask - tick.bid) / info.point
    max_sp = MAX_SPREAD.get(symbol, 999)
    if spread > max_sp:
        msg = f"spread {spread:.1f} > max {max_sp}"
        log(f"⚠ MANUAL {direction} {symbol} blocked: {msg}")
        return jsonify({"ok": False, "error": msg})

    all_pos   = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    port_risk = portfolio_open_risk(all_pos, acc.balance)
    if port_risk >= MAX_PORTFOLIO_RISK:
        msg = f"portfolio risk {port_risk:.1f}% >= max {MAX_PORTFOLIO_RISK}%"
        log(f"⚠ MANUAL {direction} {symbol} blocked: {msg}")
        return jsonify({"ok": False, "error": msg})

    sym_pos = [p for p in all_pos if p.symbol == symbol]
    max_p   = _max_pos(symbol)
    if len(sym_pos) >= max_p:
        return jsonify({"ok": False, "error": f"already {len(sym_pos)} positions on {symbol} (max {max_p})"})

    strat = "normal"
    levels = build_sl_tp(symbol, direction, df1, tick, info, strat)
    if levels["error"]:
        log(f"⚠ MANUAL {direction} {symbol} SL/TP error: {levels['error']}")
        return jsonify({"ok": False, "error": levels["error"]})

    if too_close(sym_pos, levels["entry"], direction, info):
        return jsonify({"ok": False, "error": "entry too close to existing position"})

    lot = calc_lot(symbol, levels["entry"], levels["sl"], acc.balance)
    res = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
        "volume": lot, "type": levels["otype"], "price": levels["entry"],
        "sl": levels["sl"], "tp": levels["tp"], "deviation": DEVIATION, "magic": MAGIC,
        "comment": f"MERGED MANUAL {direction}", "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })

    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        state = load_state()
        increment_trades(state)
        log(f"🖐 MANUAL {direction} {symbol} lot={res.volume:.2f} sl={levels['sl']:.5f} tp={levels['tp']:.5f}")
        return jsonify({"ok": True, "ticket": res.order, "volume": res.volume})
    else:
        code = res.retcode if res else "N/A"
        log(f"❌ MANUAL {direction} {symbol} retcode={code}")
        return jsonify({"ok": False, "error": f"MT5 retcode {code}"})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    global BASE_RISK_PCT, MAX_PORTFOLIO_RISK, RR, MAX_POS_PER_SYMBOL
    global MIN_ENTRY_DISTANCE, MIN_SCORE, TRAIL_TRIGGER_RR, TRAIL_STEP_POINTS
    global UTC_TRADE_START, UTC_TRADE_END, METALS_TIME_FILTER, DEVIATION, ATR_SL_MULTIPLIER
    global CRYPTO_RR, CRYPTO_ATR_SL_MULT, CRYPTO_TRAIL_TRIGGER_RR, CRYPTO_MIN_SCORE, CRYPTO_MAX_POS

    if request.method == "GET":
        with _lock:
            return jsonify(DASHBOARD["config"])

    body = request.get_json(silent=True) or {}
    changed = []

    def _upd(key, current_val, cast, lo=None, hi=None):
        if key not in body: return current_val
        val = cast(body[key])
        if lo is not None: val = max(lo, val)
        if hi is not None: val = min(hi, val)
        if val != current_val: changed.append(f"{key}={val}")
        return val

    with _cfg_lock:
        RR                 = _upd("rr",                RR,                float, 0.5,  20.0)
        BASE_RISK_PCT      = _upd("base_risk_pct",     BASE_RISK_PCT,     float, 0.05, 5.0)
        MAX_PORTFOLIO_RISK = _upd("max_portfolio_risk",MAX_PORTFOLIO_RISK,float, 0.5,  20.0)
        TRAIL_TRIGGER_RR   = _upd("trail_trigger",     TRAIL_TRIGGER_RR,  float, 0.1,  5.0)
        TRAIL_STEP_POINTS  = _upd("trail_step",        TRAIL_STEP_POINTS, int,   1,    50)
        MAX_POS_PER_SYMBOL = _upd("max_pos",           MAX_POS_PER_SYMBOL,int,   1,    10)
        MIN_ENTRY_DISTANCE = _upd("min_entry_dist",    MIN_ENTRY_DISTANCE,float, 0.0,  2.0)
        MIN_SCORE          = _upd("min_score",         MIN_SCORE,         float, 0.0,  1.0)
        UTC_TRADE_START    = _upd("utc_start",         UTC_TRADE_START,   int,   0,    23)
        UTC_TRADE_END      = _upd("utc_end",           UTC_TRADE_END,     int,   0,    23)
        METALS_TIME_FILTER = bool(_upd("metals_time_filter", 1 if METALS_TIME_FILTER else 0, int, 0, 1))
        DEVIATION          = _upd("deviation",         DEVIATION,         int,   1,    200)
        ATR_SL_MULTIPLIER  = _upd("atr_sl_mult",       ATR_SL_MULTIPLIER, float, 0.5,  5.0)
        CRYPTO_RR               = _upd("crypto_rr",            CRYPTO_RR,              float, 0.5, 10.0)
        CRYPTO_ATR_SL_MULT      = _upd("crypto_atr_sl_mult",   CRYPTO_ATR_SL_MULT,     float, 0.5, 6.0)
        CRYPTO_TRAIL_TRIGGER_RR = _upd("crypto_trail_trigger", CRYPTO_TRAIL_TRIGGER_RR,float, 0.1, 5.0)
        CRYPTO_MIN_SCORE        = _upd("crypto_min_score",     CRYPTO_MIN_SCORE,       float, 0.0, 1.0)
        CRYPTO_MAX_POS          = _upd("crypto_max_pos",       CRYPTO_MAX_POS,         int,   1,   10)
        # Sniper strategy params — NO nested lock, we're already inside _cfg_lock
        for sname, prefix in [
            ("sniper_breakout",  "sniper_breakout"),
            ("sniper_impulse",   "sniper_impulse"),
            ("sniper_reversion", "sniper_reversion"),
        ]:
            for field, cfg_key, lo, hi, cast in [
                ("rr",       "rr",            0.5, 10.0, float),
                ("atr",      "atr_sl_mult",   0.1,  5.0, float),
                ("trail",    "trail_trigger",  0.1,  5.0, float),
                ("maxpos",   "max_pos",        1,   10,   int),
                ("score",    "min_score",      0.0,  1.0, float),
            ]:
                key = f"{prefix}_{field}"
                if key in body:
                    v = cast(max(lo, min(hi, cast(body[key]))))
                    if v != STRATEGIES[sname][cfg_key]: changed.append(f"{key}={v}")
                    STRATEGIES[sname][cfg_key] = v

    # Sync normal strategy params
    STRATEGIES["normal"]["rr"]            = RR
    STRATEGIES["normal"]["atr_sl_mult"]   = ATR_SL_MULTIPLIER
    STRATEGIES["normal"]["min_score"]     = MIN_SCORE
    STRATEGIES["normal"]["trail_trigger"] = TRAIL_TRIGGER_RR
    STRATEGIES["normal"]["max_pos"]       = MAX_POS_PER_SYMBOL

    new_cfg = _build_cfg()
    with _lock:
        DASHBOARD["config"]     = new_cfg
        DASHBOARD["strategies"] = STRATEGIES
    if changed:
        log(f"⚙ SETTINGS updated: {', '.join(changed)}")
    # Persist to disk
    save_settings({k: new_cfg[k] for k in new_cfg if k not in ("magic","symbols_count")} |
                  {f"en_{n}": (1 if STRATEGIES[n]["enabled"] else 0) for n in STRATEGIES})
    return jsonify({"ok": True, "config": new_cfg})


@app.route("/api/settings/reset", methods=["POST"])
def api_settings_reset():
    apply_settings(DEFAULTS)
    new_cfg = _build_cfg()
    with _lock:
        DASHBOARD["config"]     = new_cfg
        DASHBOARD["strategies"] = STRATEGIES
    save_settings({k: new_cfg[k] for k in new_cfg if k not in ("magic","symbols_count")} |
                  {f"en_{n}": (1 if STRATEGIES[n]["enabled"] else 0) for n in STRATEGIES})
    log("⚙ SETTINGS reset to defaults")
    return jsonify({"ok": True, "config": new_cfg, "strategies": STRATEGIES})


@app.route("/api/symbols", methods=["GET"])
def api_symbols_get():
    """Return current symbol list with spread and category info."""
    result = []
    for sym in SYMBOLS:
        result.append({
            "symbol":     sym,
            "max_spread": MAX_SPREAD.get(sym, 50.0),
            "category":   SYMBOL_CATEGORY.get(sym, "EUR"),
            "is_crypto":  sym in CRYPTO_SYMBOLS,
            "is_metal":   sym in METALS_SYMBOLS,
        })
    return jsonify({"ok": True, "symbols": result})


@app.route("/api/symbols", methods=["POST"])
def api_symbols_add():
    """Add a new symbol or update spread/category of existing one."""
    global SYMBOLS, CRYPTO_SYMBOLS, METALS_SYMBOLS, SYMBOL_CATEGORY, SYMBOL_CATEGORIES
    body = request.get_json(silent=True) or {}
    sym  = (body.get("symbol") or "").upper().strip()
    if not sym:
        return jsonify({"ok": False, "error": "symbol required"}), 400
    max_sp   = float(body.get("max_spread", 50.0))
    category = body.get("category", "EUR")
    if category not in SYMBOL_CATEGORIES:
        return jsonify({"ok": False, "error": f"unknown category: {category}"}), 400

    MAX_SPREAD[sym] = max_sp

    old_cat = SYMBOL_CATEGORY.get(sym)
    if old_cat and old_cat != category:
        if sym in SYMBOL_CATEGORIES.get(old_cat, []):
            SYMBOL_CATEGORIES[old_cat].remove(sym)
    SYMBOL_CATEGORY[sym] = category
    if sym not in SYMBOL_CATEGORIES.get(category, []):
        SYMBOL_CATEGORIES.setdefault(category, []).append(sym)

    CRYPTO_SYMBOLS.discard(sym)
    METALS_SYMBOLS.discard(sym)
    if category == "Crypto":
        CRYPTO_SYMBOLS.add(sym)
    elif category == "Metals":
        METALS_SYMBOLS.add(sym)

    if sym not in SYMBOLS:
        SYMBOLS.append(sym)
        mt5.symbol_select(sym, True)
        log(f"⚙ SYMBOL ADDED: {sym} cat={category} max_spread={max_sp}")
    else:
        log(f"⚙ SYMBOL UPDATED: {sym} cat={category} max_spread={max_sp}")

    with _lock:
        DASHBOARD["config"]["symbols_count"] = len(SYMBOLS)
    save_symbols()
    return jsonify({"ok": True, "symbol": sym, "category": category, "max_spread": max_sp})


@app.route("/api/symbols/<symbol>", methods=["DELETE"])
def api_symbols_delete(symbol):
    """Remove a symbol from the active list."""
    global SYMBOLS
    sym = symbol.upper().strip()
    if sym not in SYMBOLS:
        return jsonify({"ok": False, "error": "symbol not in list"}), 400
    SYMBOLS.remove(sym)
    cat = SYMBOL_CATEGORY.pop(sym, None)
    if cat and sym in SYMBOL_CATEGORIES.get(cat, []):
        SYMBOL_CATEGORIES[cat].remove(sym)
    CRYPTO_SYMBOLS.discard(sym)
    METALS_SYMBOLS.discard(sym)
    MAX_SPREAD.pop(sym, None)
    with _lock:
        DASHBOARD["config"]["symbols_count"] = len(SYMBOLS)
    save_symbols()
    log(f"⚙ SYMBOL REMOVED: {sym}")
    return jsonify({"ok": True, "removed": sym})


@app.route("/api/symbols/reset", methods=["POST"])
def api_symbols_reset():
    """Restore the built-in default symbol list."""
    reset_symbols()
    with _lock:
        DASHBOARD["config"]["symbols_count"] = len(SYMBOLS)
    log("⚙ SYMBOLS reset to factory defaults")
    return jsonify({"ok": True, "count": len(SYMBOLS)})


@app.route("/api/server", methods=["POST"])
def api_server_toggle():
    global BOT_PAUSED
    body = request.get_json(silent=True) or {}
    with _cfg_lock:
        BOT_PAUSED = bool(body["paused"]) if "paused" in body else not BOT_PAUSED
        paused = BOT_PAUSED
    with _lock:
        DASHBOARD["bot_paused"] = paused
    log(f"🔧 SERVER {'⏸ PAUSED' if paused else '▶ RESUMED'}")
    return jsonify({"ok": True, "paused": paused})


@app.route("/api/overrides", methods=["GET"])
def api_overrides_get():
    """Return all current per-symbol overrides."""
    return jsonify({"ok": True, "overrides": SYMBOL_OVERRIDES})


@app.route("/api/overrides/<symbol>", methods=["POST"])
def api_overrides_set(symbol):
    """Set or update per-symbol overrides. Pass only the keys you want to override."""
    sym = symbol.upper().strip()
    if sym not in SYMBOLS:
        return jsonify({"ok": False, "error": "unknown symbol"}), 400
    body = request.get_json(silent=True) or {}
    allowed = {"atr_sl_mult", "min_score", "trail_trigger", "rr", "max_pos"}
    updates = {}
    for k in allowed:
        if k in body:
            v = body[k]
            updates[k] = int(v) if k == "max_pos" else float(v)
    if not updates:
        return jsonify({"ok": False, "error": "no valid override keys supplied"}), 400
    SYMBOL_OVERRIDES.setdefault(sym, {}).update(updates)
    save_overrides()
    log(f"⚙ OVERRIDE {sym}: {updates}")
    return jsonify({"ok": True, "symbol": sym, "overrides": SYMBOL_OVERRIDES.get(sym, {})})


@app.route("/api/overrides/<symbol>", methods=["DELETE"])
def api_overrides_delete(symbol):
    """Remove all per-symbol overrides for a symbol (revert to global/category defaults)."""
    sym = symbol.upper().strip()
    removed = SYMBOL_OVERRIDES.pop(sym, None)
    save_overrides()
    if removed:
        log(f"⚙ OVERRIDE CLEARED {sym} — reverted to category/global defaults")
    return jsonify({"ok": True, "symbol": sym, "cleared": removed is not None})


def run_flask():
    app.run(host="0.0.0.0", port=5001, use_reloader=False, debug=False)

# ═══════════════════════════════════════════════════════════════
#  MAIN BOT LOOP
# ═══════════════════════════════════════════════════════════════
def fmtsgn(v):
    return ("+$" if v >= 0 else "-$") + f"{abs(v):.2f}"


def run_bot():
    global _trades_total
    log("🚀 SCALPER MERGED STARTED — Normal + Crypto + Sniper (Breakout/Impulse/Reversion)")

    state = load_state()
    with _trades_lock:
        _trades_total = state.get("trades_total", 0)

    session_start_balance = None
    # ticket → (symbol, type, price_open, sl) for SL-hit detection
    _prev_positions: dict = {}

    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            acc   = mt5.account_info()
            if acc is None:
                log("⚠ account_info() None — reconnecting…")
                time.sleep(5)
                continue

            all_pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]

            # ══ SL-hit cascade: close surviving siblings only when net P&L > 0 ══
            # Rationale: one position in a stacked set was just stopped out.
            # If the remaining siblings are collectively in profit we close them
            # to bank the gains before price reverses. If net P&L is zero or
            # negative we leave them alone — closing at a loss defeats the purpose.
            current_tickets = {p.ticket for p in all_pos}
            for ticket, (sym, ptype, price_open, sl) in list(_prev_positions.items()):
                if ticket in current_tickets:
                    continue   # still open — fine
                # Position disappeared since last tick — TP or SL hit.
                siblings = [
                    p for p in all_pos
                    if p.symbol == sym and p.type == ptype
                ]
                if not siblings:
                    # Last (or only) position on this symbol closed — always cooldown.
                    set_cooldown(sym, "TP/SL")
                    continue
                # Gate: only cascade when combined unrealised P&L is positive.
                net_pnl = sum(p.profit for p in siblings)
                if net_pnl <= 0:
                    # SL hit but siblings are in loss — no cascade, but still cooldown.
                    set_cooldown(sym, "SL")
                    continue
                tick = mt5.symbol_info_tick(sym)
                info = mt5.symbol_info(sym)
                if tick is None or info is None:
                    continue
                direction = "BUY" if ptype == mt5.POSITION_TYPE_BUY else "SELL"
                sign = "+$" if net_pnl >= 0 else "-$"
                log(f"🛑 SL CASCADE {sym} — ticket #{ticket} hit SL, net sibling P&L={sign}{abs(net_pnl):.2f}, closing {len(siblings)} sibling(s)")
                for p in siblings:
                    close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    close_price = tick.bid            if p.type == mt5.POSITION_TYPE_BUY else tick.ask
                    res = mt5.order_send({
                        "action":       mt5.TRADE_ACTION_DEAL,
                        "symbol":       sym,
                        "volume":       p.volume,
                        "type":         close_type,
                        "position":     p.ticket,
                        "price":        close_price,
                        "deviation":    DEVIATION,
                        "magic":        MAGIC,
                        "comment":      "SL CASCADE CLOSE",
                        "type_time":    mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    })
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        pnl = round(p.profit, 2)
                        log(f"🔴 CASCADE CLOSED {direction} {sym} #{p.ticket} lot={p.volume:.2f} P&L={chr(43) if pnl>=0 else chr(45)}${abs(pnl):.2f}")
                    else:
                        code = res.retcode if res else "N/A"
                        log(f"❌ CASCADE CLOSE failed {sym} #{p.ticket} retcode={code}")
                # Cooldown after cascade — always, regardless of individual order results
                set_cooldown(sym, "CASCADE")
                # Refresh positions after cascade
                all_pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]

            # Update position snapshot for next tick
            _prev_positions = {p.ticket: (p.symbol, p.type, p.price_open, p.sl) for p in all_pos}

            # Day rollover
            if state.get("session_start_date") and state["session_start_date"] != today:
                yesterday = state["session_start_date"]
                state["daily"][yesterday] = round(state.get("cumulative_pnl", 0.0), 2)
                log(f"📅 New day ({today}) | Yesterday P&L: {fmtsgn(state['daily'][yesterday])}")
                state.update(session_start_date=today, session_start_balance=acc.balance, cumulative_pnl=0.0)
                session_start_balance = acc.balance
                save_state(state)

            if session_start_balance is None:
                saved = state.get("session_start_balance")
                if saved and state.get("session_start_date") == today:
                    session_start_balance = saved
                else:
                    session_start_balance = acc.balance
                    state.update(session_start_balance=acc.balance, session_start_date=today)
                    save_state(state)
                log(f"📌 Session start: ${session_start_balance:.2f}")

            session_pnl = round(acc.balance - session_start_balance, 2)
            if session_pnl != state.get("cumulative_pnl"):
                state["cumulative_pnl"] = session_pnl
                state["daily"][today]   = session_pnl
                save_state(state)

            basket_cur = round(sum(p.profit for p in all_pos), 2)
            port_risk  = portfolio_open_risk(all_pos, acc.balance)

            with _trades_lock:
                current_trades = _trades_total

            with _lock:
                DASHBOARD.update(
                    session_pnl=session_pnl,
                    daily=dict(state["daily"]),
                    trades_total=current_trades,
                    portfolio_risk=round(port_risk, 2),
                    session_start=round(session_start_balance, 2),
                    strategies=STRATEGIES,
                    account={
                        "balance":        round(acc.balance, 2),
                        "equity":         round(acc.equity,  2),
                        "open_positions": len(all_pos),
                        "active_symbols": len(set(p.symbol for p in all_pos)),
                    },
                    basket={"current": basket_cur},
                )

            with _cfg_lock:
                is_paused = BOT_PAUSED
            with _lock:
                DASHBOARD["bot_paused"] = is_paused

            if is_paused:
                time.sleep(2)
                continue

            trail_stops(all_pos)

            rows = []
            for symbol in SYMBOLS:
                if not mt5.symbol_select(symbol, True):
                    continue

                df1, df15, df_h1 = get_data(symbol)
                if df1 is None:
                    continue

                tick = mt5.symbol_info_tick(symbol)
                info = mt5.symbol_info(symbol)
                if tick is None or info is None:
                    continue

                spread   = round((tick.ask - tick.bid) / info.point, 1)
                max_sp   = MAX_SPREAD.get(symbol, 999)
                sym_pos  = [p for p in all_pos if p.symbol == symbol]
                profit   = round(sum(p.profit for p in sym_pos), 2)
                is_open  = market_is_open(symbol)
                mom1     = get_momentum_dir(df1)
                mom15    = get_momentum_dir(df15)
                h1_trend = get_h1_trend(df_h1)

                category = SYMBOL_CATEGORY.get(symbol, "EUR")
                f        = compute_features(df1, category)
                regime   = detect_regime(f)
                score    = composite_score(f, regime)

                # Collect all active signals (for display)
                all_sigs = collect_signals(symbol, df1, df15, df_h1, score, regime)
                active_signal_strats = [s["strategy"] for s in all_sigs]
                primary_signal = all_sigs[0]["direction"] if all_sigs else None

                with _disabled_lock:
                    is_disabled = symbol in DISABLED_SYMBOLS

                buys     = sum(1 for p in sym_pos if p.type == mt5.POSITION_TYPE_BUY)
                sells    = sum(1 for p in sym_pos if p.type == mt5.POSITION_TYPE_SELL)
                pos_side = "buy" if buys > sells else "sell" if sells > buys else "mixed" if sym_pos else "none"

                rows.append({
                    "symbol":         symbol,
                    "category":       category,
                    "score":          round(score, 3),
                    "mom1":           mom1,
                    "mom15":          mom15,
                    "h1_trend":       h1_trend,
                    "signal":         primary_signal or "-",
                    "active_signals": active_signal_strats,
                    "regime":         regime,
                    "spread":         spread,
                    "spread_warn":    spread > max_sp,
                    "profit":         profit,
                    "positions":      len(sym_pos),
                    "pos_side":       pos_side,
                    "max_pos":        _max_pos(symbol),
                    "market_open":    is_open,
                    "is_crypto":      symbol in CRYPTO_SYMBOLS,
                    "disabled":       is_disabled,
                    "cooldown_secs":  round(cooldown_remaining(symbol)),
                })

                # ── Trade execution ──
                if is_disabled: continue
                if not is_open: continue
                if symbol not in CRYPTO_SYMBOLS:
                    is_metal = symbol in METALS_SYMBOLS
                    if not (is_metal and not METALS_TIME_FILTER):
                        if not (UTC_TRADE_START <= datetime.utcnow().hour < UTC_TRADE_END):
                            continue
                if spread > max_sp:
                    _now = datetime.utcnow()
                    _last = _spread_warn_ts.get(symbol)
                    if _last is None or (_now - _last).total_seconds() >= 60:
                        log(f"⚠ {symbol} spread {spread} > max {max_sp}")
                        _spread_warn_ts[symbol] = _now
                    continue
                if port_risk >= MAX_PORTFOLIO_RISK:
                    global _port_risk_warn_ts
                    _now = datetime.utcnow()
                    if _port_risk_warn_ts is None or (_now - _port_risk_warn_ts).total_seconds() >= 60:
                        log(f"⚠ Max portfolio risk {port_risk:.1f}% reached")
                        _port_risk_warn_ts = _now
                    continue

                # ── Cooldown: skip new entries while symbol is cooling down ──
                cd_secs = cooldown_remaining(symbol)
                if cd_secs > 0:
                    continue

                # ── Direction lock: never open both BUY and SELL on same symbol ──
                if sym_pos:
                    _n_buys  = sum(1 for p in sym_pos if p.type == mt5.POSITION_TYPE_BUY)
                    _n_sells = sum(1 for p in sym_pos if p.type == mt5.POSITION_TYPE_SELL)
                    allowed_dir = "BUY" if _n_buys >= _n_sells else "SELL"
                else:
                    _buy_votes  = sum(1 for s in all_sigs if s["direction"] == "BUY")
                    _sell_votes = sum(1 for s in all_sigs if s["direction"] == "SELL")
                    if _buy_votes > 0 and _sell_votes > 0:
                        allowed_dir = "BUY" if _buy_votes >= _sell_votes else "SELL"
                        log(f"⚡ {symbol} conflicting signals ({_buy_votes}× BUY vs {_sell_votes}× SELL) — locking to {allowed_dir}")
                    elif _buy_votes > 0:
                        allowed_dir = "BUY"
                    elif _sell_votes > 0:
                        allowed_dir = "SELL"
                    else:
                        allowed_dir = None

                # ── Priority execution: only the first qualifying strategy fires ──
                # all_sigs is already in priority order: normal → breakout → impulse → reversion
                chosen = next(
                    (s for s in all_sigs if s["direction"] == allowed_dir),
                    None
                )
                if chosen is None:
                    continue

                strategy  = chosen["strategy"]
                direction = chosen["direction"]
                cfg       = STRATEGIES.get(strategy, STRATEGIES["normal"])

                sym_max = cfg.get("max_pos", _max_pos(symbol))
                if len(sym_pos) >= sym_max:
                    continue

                levels = build_sl_tp(symbol, direction, df1, tick, info, strategy)
                if levels["error"]:
                    log(f"⚠ {symbol} {strategy} {direction}: {levels['error']}")
                    continue

                if too_close(sym_pos, levels["entry"], direction, info):
                    continue

                lot = calc_lot(symbol, levels["entry"], levels["sl"], acc.balance)
                res = mt5.order_send({
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                    "volume": lot, "type": levels["otype"], "price": levels["entry"],
                    "sl": levels["sl"], "tp": levels["tp"],
                    "deviation": DEVIATION, "magic": MAGIC,
                    "comment": f"MERGED {strategy} {direction}",
                    "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
                })

                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    increment_trades(state)
                    log(f"✅ [{strategy}] {direction} {symbol} score={score:.2f} lot={res.volume:.2f} sl={levels['sl']:.5f} tp={levels['tp']:.5f} rr={levels.get('rr','?')} spread={spread} h1={h1_trend}")
                    all_pos   = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
                    sym_pos   = [p for p in all_pos if p.symbol == symbol]
                    port_risk = portfolio_open_risk(all_pos, acc.balance)
                else:
                    code = res.retcode if res else "N/A"
                    log(f"❌ [{strategy}] {symbol} retcode={code}")

            with _lock:
                DASHBOARD["symbols"] = rows

        except Exception as e:
            import traceback
            log(f"⚡ LOOP ERROR: {e}")
            log(traceback.format_exc()[:300])

        time.sleep(2)

# ═══════════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════════
threading.Thread(target=run_flask, daemon=True).start()
run_bot()
