<img width="1913" height="930" alt="image" src="https://github.com/user-attachments/assets/cccf7770-ae1a-46a3-9c87-6221950ce492" />
<img width="791" height="907" alt="image" src="https://github.com/user-attachments/assets/4cd70a45-f5f4-4e54-bc45-672d11f40931" />
<img width="909" height="497" alt="image" src="https://github.com/user-attachments/assets/bd31581a-e040-4e1d-ab91-64a3ac53d3b3" />


# Scalper V19

An automated MT5 scalping bot covering Forex, Metals, and Crypto — with a live web dashboard, per-symbol parameter overrides, and four trading strategies.

---

## Features

- **4 trading strategies** running simultaneously per symbol: Normal, Sniper Breakout, Sniper Impulse, and Sniper Reversion
- **Multi-timeframe confirmation** — M1 entry, M15 trend filter, H1 bias
- **ATR-based SL/TP** with dynamic trailing stop
- **Composite scoring engine** with regime detection (NORMAL / LOW / HIGH volatility)
- **Per-symbol parameter overrides** via `scalper_overrides.json` — RR, ATR multiplier, min score, trail trigger, max positions
- **Spread filter** — skips entries when live spread exceeds per-symbol max; logs spread at every trade entry
- **Portfolio risk cap** — halts new entries when total open risk exceeds configured threshold
- **Cooldown system** — blocks re-entry per symbol for 5 minutes after a close
- **Live web dashboard** on `http://localhost:5001` — shows scores, spreads, signals, positions, P&L, and regime per symbol
- **Hot-reload settings** — all parameters adjustable at runtime without restarting

---

## Strategies

| Strategy | Description |
|---|---|
| **Normal** | Multi-timeframe trend following. M1 + M15 + H1 must align. |
| **Sniper Breakout** | Fires when price breaks a recent swing high/low with momentum confirmation. |
| **Sniper Impulse** | Fires on a strong candle (body > 70% of range) in the EMA9 > EMA21 direction. |
| **Sniper Reversion** | Counter-trend fade when price stretches > 1.5× ATR from EMA9, back toward H1 bias. |

---

## Symbols

| Category | Symbols |
|---|---|
| EUR pairs | EURUSD, EURGBP, EURCHF, EURAUD, EURCAD, EURNZD, EURJPY |
| GBP pairs | GBPUSD, GBPJPY, GBPAUD, GBPCAD, GBPCHF, GBPNZD |
| USD pairs | USDJPY, USDCAD, USDCHF, AUDUSD, NZDUSD |
| Metals | XAUUSD, XAGUSD |
| Crypto | BTCUSD, ETHUSD, SOLUSD, BNBUSD, XRPUSD, ADAUSD, LTCUSD, DOTUSD, DOGUSD |

---

## Requirements

- Python 3.9+
- MetaTrader 5 desktop app (running and logged in)
- MT5 broker account with the symbols enabled

```bash
pip install MetaTrader5 pandas numpy flask
```

---

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/jvwelzen/Scalper-V19.git
   cd Scalper-V19
   ```

2. Place both files in the same directory:
   ```
   scalper_v19.py
   scalper_overrides.json
   ```

3. Change your MetaTrader 5 account on line 420 in scalper_v19.py.

if not mt5.initialize(
    path="C:/Program Files/MetaTrader 5/terminal64.exe",
    login=YOUR ACCOUNT NUMBER,            # ACCOUNT NUMBER
    server="VantageInternational-Demo",   # YOUR SERVER
    password="YOUR PASSWORD"              # YOUR PASSWORD
):

4. Run the bot:
   ```bash
   python scalper_v19.py
   ```

5. Open the dashboard: http://localhost:5001

---

## Configuration

### Global defaults (`scalper_v19.py`)

| Parameter | Default | Description |
|---|---|---|
| `BASE_RISK_PCT` | 0.5% | Risk per trade as % of account balance |
| `MAX_PORTFOLIO_RISK` | 6.0% | Max total open risk before new entries are blocked |
| `RR` | 2.5 | Default reward-to-risk ratio |
| `ATR_SL_MULTIPLIER` | 1.5 | SL distance = ATR × multiplier |
| `TRAIL_TRIGGER_RR` | 0.6 | Trail activates when trade reaches 60% of TP distance |
| `UTC_TRADE_START` | 6 | Trading window start (UTC hour) |
| `UTC_TRADE_END` | 17 | Trading window end (UTC hour) |
| `COOLDOWN_SECONDS` | 300 | Seconds to block re-entry after a close |

Crypto and Metals have their own parameter blocks and are adjusted separately.

### Per-symbol overrides (`scalper_overrides.json`)

Override any symbol's parameters without touching the main script:

```json
{
  "EURUSD": { "atr_sl_mult": 1.2, "rr": 2.8, "trail_trigger": 0.65, "min_score": 0.58, "max_pos": 3 },
  "XAUUSD": { "atr_sl_mult": 1.6, "rr": 2.5, "trail_trigger": 0.55, "min_score": 0.52, "max_pos": 2 },
  "BTCUSD": { "atr_sl_mult": 2.2, "rr": 1.8, "trail_trigger": 0.40, "min_score": 0.45, "max_pos": 2 }
}
```

All settings in the dashboard can also be changed live and will persist across restarts.

---

## Trade Log Format

```
✅ [sniper_impulse] BUY EURUSD score=0.71 lot=0.02 sl=1.08210 tp=1.08540 rr=2.8 spread=1.2 h1=bull
⚠ GBPJPY spread 34.1 > max 30.0
❌ [normal] XAUUSD retcode=10016
```

---

## Disclaimer

This software is for educational and personal use only. Trading involves significant risk of loss. Past performance of any strategy does not guarantee future results. Use at your own risk.
