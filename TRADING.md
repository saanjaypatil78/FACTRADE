# FACTRADE — Multi-Timeframe Liquidity Monitor

## Overview

This module adds an automated, multi-timeframe liquidity monitoring and trade execution system to FACTRADE. It follows Arjo's Liquidity Framework: detect where Smart Money has swept retail stop-losses on higher timeframes (HTF), then enter precision trades on lower timeframes (LTF) when price retraces into the OTE (Optimal Trade Entry) zone.

```
HTF Analysis          LTF Execution
─────────────         ──────────────
Daily  ┐              30m ─┐
4H     ├── Sweep?  →  15m ─┴── CHoCH + OTE → Signal → Risk Check → Order
3H     │
1H     ┘
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Edit `trading_config.yaml` to set your symbols, risk parameters, and SL/TP templates (see [Configuration](#configuration) below).

### 3. Run (paper-trading mode — no broker required)

```bash
python run_trading.py
```

### 4. Single evaluation pass (useful for cron / testing)

```bash
python run_trading.py --once
```

### 5. Use a custom config file

```bash
python run_trading.py --config my_config.yaml
```

### 6. Live execution mode

```bash
python run_trading.py --live
```

> ⚠️ **Live mode requires a broker adapter.** See [Broker Integration](#broker-integration).

---

## Configuration (`trading_config.yaml`)

| Parameter | Default | Description |
|---|---|---|
| `paper_mode` | `true` | `true` = simulate orders in memory; `false` = live execution |
| `poll_interval_seconds` | `60` | How often to run one evaluation cycle |
| `symbols[].symbol` | `XAUUSD` | Instrument identifier |
| `symbols[].htf_timeframes` | `[1D,4H,3H,1H]` | Timeframes used for liquidity context |
| `symbols[].ltf_timeframes` | `[30m,15m]` | Timeframes used for entry signals |
| `symbols[].pip_value` | `1.0` | Account-currency value per pip per 0.01 lot |
| `symbols[].max_sl_pips` | `50.0` | Skip trade if SL wider than this (per symbol) |
| `risk.equity` | `700.0` | Session capital in USD |
| `risk.risk_pct` | `1.0` | Default % of equity to risk per trade |
| `risk.max_risk_pct` | `2.0` | Hard cap for A+ setups |
| `risk.max_daily_loss_pct` | `2.0` | Halt new trades after this % daily drawdown |
| `risk.max_concurrent_trades` | `2` | Maximum simultaneously open positions |
| `risk.min_rr_ratio` | `1.5` | Minimum risk/reward ratio to approve a trade |
| `swing_lookback` | `3` | Candles each side required to confirm a swing pivot |
| `equal_tolerance_pct` | `0.05` | Tolerance (%) for equal-high/low detection |
| `ote_low` | `0.618` | Fibonacci OTE zone lower bound |
| `ote_high` | `0.786` | Fibonacci OTE zone upper bound |
| `max_sl_pips` | `50.0` | Global SL distance cap (per-symbol setting overrides) |

---

## Architecture

```
src/trading/
├── __init__.py           — public API exports
├── liquidity_detector.py — HTF swing H/L, equal H/L, PDH/PDL detection + sweep/run classification
├── signal_generator.py   — CHoCH detection, OTE zone, regime detection (trend/range/volatile)
├── risk_manager.py       — position sizing, daily loss cap, RR gate, concurrent-trade gate
├── trade_executor.py     — paper/live order lifecycle, 80/20 partial booking, runner management
└── monitor.py            — continuous multi-symbol multi-timeframe loop + config loader
```

### Liquidity Detection Parameters

**Swing pivots** (`swing_lookback=3`): A candle is a swing high/low when its high/low is strictly higher/lower than the `N` candles on each side. Increase `N` to find only major pivots; decrease for more sensitive detection.

**Equal levels** (`equal_tolerance_pct=0.05`): Two swing highs within 0.05% of each other are treated as an "equal high" (EQH) — a strong liquidity magnet.

**PDH / PDL**: Previous Day High and Low are derived automatically from daily grouping of the OHLCV index.

### Signal Generation

Entry signals are produced when **all** of the following align:

1. An HTF level (swing H/L, EQH/EQL, PDH/PDL) has been **swept** — price wicked above/below it and closed back on the opposite side.
2. On the LTF (15m or 30m), a **CHoCH** (Change of Character) displacement candle is detected after the sweep.
3. Price retraces into the **OTE zone** (Fibonacci 0.618–0.786 of the CHoCH move).
4. The computed SL distance (HTF swept level ± 1.5 × ATR) does not exceed `max_sl_pips`.

### Stop-Loss Formula

```
Final SL = HTF_swept_level ± (1.5 × ATR(14))
```

The ATR buffer gives the market "breathing room" and avoids micro-sweeps taking out your position.

### Take-Profit Levels (80/20 Marco Rule)

| Level | Fraction | Target |
|---|---|---|
| TP1 | 80% of position | 1st internal liquidity (≈1.5× SL distance) |
| TP2 | 20% runner | Opposite HTF liquidity (≈3.0× SL distance) |

After TP1 is hit, the runner's SL moves to **break-even** (entry price + tiny buffer). This ensures zero risk on the runner.

### Position Sizing

```
risk_amount = equity × risk_pct / 100
lot_size    = risk_amount / (sl_distance × pip_value_per_lot)
```

Lot size is always rounded down to the nearest 0.01 lot (minimum 0.01).

---

## Risk Management Gates

Every signal passes through five gates before an order is placed:

| Gate | Rule |
|---|---|
| **Daily loss cap** | Halt if `realized_daily_pnl < -(equity × max_daily_loss_pct / 100)` |
| **Concurrent trades** | Skip if `open_trades >= max_concurrent_trades` |
| **SL distance** | Skip if `sl_distance > max_sl_pips` |
| **RR ratio** | Skip if `TP1_distance / SL_distance < min_rr_ratio` |
| **Lot size** | Always at least 0.01 lot; never over-risk due to rounding |

---

## Regime Detection

The signal generator classifies market conditions before entering:

| Regime | Detection |
|---|---|
| **TREND** | SMMA 31/59 ribbon clearly separated; price on correct side |
| **RANGE** | Bollinger Bands (199, 1.9) flat; BB width < 0.5% |
| **VOLATILE** | Last close outside BB outer band |
| **UNDEFINED** | Insufficient data |

---

## Data Provider

The default `run_trading.py` uses a **synthetic data provider** so the system can be exercised without a live feed. Replace the `_simulated_provider` function with your real market-data source:

```python
# MetaTrader 5
import MetaTrader5 as mt5
TF_MAP = {"15m": mt5.TIMEFRAME_M15, "1H": mt5.TIMEFRAME_H1, ...}
def provider(symbol, tf):
    rates = mt5.copy_rates_from_pos(symbol, TF_MAP[tf], 0, 500)
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"], unit="s")
    return df[["open", "high", "low", "close", "tick_volume"]].rename(
        columns={"tick_volume": "volume"})

# yfinance
import yfinance as yf
def provider(symbol, tf):
    return yf.download(symbol, period="60d", interval=tf, auto_adjust=True)

# CCXT (crypto / some CFD brokers)
import ccxt, pandas as pd
exchange = ccxt.binance()
def provider(symbol, tf):
    data = exchange.fetch_ohlcv(symbol, tf, limit=500)
    df = pd.DataFrame(data, columns=["timestamp","open","high","low","close","volume"])
    df.index = pd.to_datetime(df["timestamp"], unit="ms")
    return df
```

---

## Broker Integration

For **live execution** implement the `BrokerAdapter` protocol in `trade_executor.py`:

```python
class MyBroker:
    def place_order(self, symbol, direction, lot_size, entry, sl, tp) -> str: ...
    def close_order(self, broker_order_id, lot_size) -> float: ...
    def get_current_price(self, symbol) -> float: ...
```

Then pass it to `TradeExecutor`:

```python
from src.trading import TradingMonitor
from src.trading.monitor import MonitorConfig
from src.trading.trade_executor import TradeExecutor

cfg = MonitorConfig.from_yaml("trading_config.yaml")
cfg.paper_mode = False
monitor = TradingMonitor(config=cfg, data_provider=my_provider)
# The executor inside monitor will call MyBroker for live orders
```

---

## Alert Callbacks

Add your own notification logic (Telegram, email, Discord) via the `alert_callbacks` parameter:

```python
def telegram_alert(signal, order):
    import requests
    msg = f"📊 {signal.symbol} {signal.direction.value.upper()} @ {signal.entry_price}"
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": msg})

monitor = TradingMonitor(
    config=cfg,
    data_provider=provider,
    alert_callbacks=[telegram_alert],
)
```

---

## Running Tests

```bash
# New trading system tests only
python -m pytest tests/test_trading_liquidity_detector.py \
                 tests/test_trading_signal_generator.py \
                 tests/test_trading_risk_manager.py \
                 tests/test_trading_executor_monitor.py -v

# All tests
python -m pytest
```

---

## Limitations and Safe Usage

1. **Paper mode is the default.** Never switch to live mode until you have verified the data provider and broker adapter produce correct values for your specific broker/account.

2. **The 50-pip skip rule.** Valid setups on high-volatility sessions (e.g., NFP, FOMC) may have wider ATR-based SLs. Adjust `max_sl_pips` per symbol rather than disabling the check entirely.

3. **News filter is your responsibility.** The system does not connect to an economic calendar. Check Forex Factory manually and ensure you are not holding positions into Tier-1 news events (NFP, CPI, FOMC, EIA). Close positions at least 10 minutes before.

4. **Prop-firm compliance.** If trading a funded account (e.g., TradeDay, FXIFY), re-read the latest rulebook before each session. News windows, IP restrictions, and drawdown rules change.

5. **Leverage awareness.** Leverage reduces margin, not pip value. A 0.05-lot XAUUSD position loses $5 per $1 move regardless of leverage.

6. **Simulated data ≠ real data.** The built-in synthetic provider is for testing only. Replace it with real OHLCV data before drawing any conclusions about strategy performance.

7. **Backtest before live.** Run the monitor with a historical data provider and `paper_mode=true` for at least 30 sessions before enabling live execution.
