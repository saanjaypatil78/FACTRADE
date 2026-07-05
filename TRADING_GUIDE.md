# FACTRADE Trading Guide

## Free-Only Live Monitoring & Historical Backtesting for XAUUSD and USOIL/WTI

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Free Data Sources – What Works and What Doesn't](#2-free-data-sources)
3. [Broker CSV Import Workflow](#3-broker-csv-import-workflow)
4. [Setup & Installation](#4-setup--installation)
5. [Running Live Monitor Mode](#5-running-live-monitor-mode)
6. [Running Backtest Mode](#6-running-backtest-mode)
7. [Strategy Logic Summary](#7-strategy-logic-summary)
8. [Risk Management Rules](#8-risk-management-rules)
9. [Signal Schema](#9-signal-schema)
10. [Extending the System](#10-extending-the-system)

---

## 1. Architecture Overview

```
src/trading/
├── candle.py                  # Common OHLCV schema (Candle, Signal, TradeResult)
├── adapters/
│   ├── base.py                # Abstract BaseAdapter
│   ├── csv_adapter.py         # Broker-exported CSV import  ← best accuracy
│   └── yfinance_adapter.py    # Free yfinance proxy (GC=F / CL=F)
├── liquidity_detector.py      # Swing-high/low, PDH/PDL, sweep detection
├── signal_generator.py        # Four setups: OTE+CHoCH, SMMA, BB, VWAP
├── risk_manager.py            # ATR-based SL/TP, lot sizing
├── trade_executor.py          # Paper-trade / signal-only executor
├── backtester.py              # Walk-forward backtest engine
└── monitor.py                 # Continuous live-monitoring loop

main_trading.py                # CLI entry point
```

All adapters normalise their data into the same `Candle` dataclass, so
strategy logic is fully source-agnostic.

---

## 2. Free Data Sources

### A. yfinance (Free, No API Key)

| FACTRADE symbol | yfinance ticker | Description |
|---|---|---|
| `XAUUSD` | `GC=F` | CME Gold Futures (continuous front-month) |
| `USOIL` / `WTI` | `CL=F` | CME WTI Crude Oil Futures (continuous front-month) |

**What you get:**
- Daily bars: up to ~27 years of history, completely free.
- 1H bars: up to ~2 years of history.
- 15m / 5m bars: last 60 days only (Yahoo Finance free-tier limit).
- 1m bars: last 7 days only.

**Known limitations (use with awareness):**

| Limitation | Detail |
|---|---|
| **Price offset** | `GC=F` is the CME futures price, not the spot XAUUSD CFD price from your broker. Expect a small premium (cost-of-carry, contract roll) that varies over time. |
| **15m/5m history cap** | Only 60 days of sub-hourly history available. |
| **Intraday delay** | Yahoo Finance imposes a ~15-minute delay on intraday bars. |
| **Volume mismatch** | Volume is CME exchange volume, not retail CFD tick-volume. |
| **No tick data** | Sub-minute data is unavailable. |
| **Roll gaps** | Continuous futures contracts have occasional roll-day gaps. |

**Verdict:**  
Good for daily/4H/1H multi-timeframe context and pattern research.  
Use broker CSV for 15m/5m entry-timing accuracy.

---

### B. Broker-Exported CSV (Recommended for Best Accuracy)

Export directly from your broker (MT4/MT5, cTrader, etc.) for **exact**
symbol pricing (true XAUUSD spot or exact USOIL CFD).

**Zero paid credits. Perfect accuracy. Unlimited history.**

See [Section 3](#3-broker-csv-import-workflow) for the step-by-step workflow.

---

## 3. Broker CSV Import Workflow

### Step 1 – Export from MT4/MT5

1. Open MetaTrader 4/5.
2. Open the History Center: **Tools → History Center**.
3. Select symbol (e.g. **XAUUSD**) and timeframe (e.g. **H1**).
4. Click **Export** → save as `.csv`.
5. Repeat for each required timeframe (Daily, 4H, 1H, 15m, 5m).

MT4 CSV format (auto-detected by `CSVAdapter`):
```
DATE,TIME,OPEN,HIGH,LOW,CLOSE,TICKVOL,VOL,SPREAD
2024.01.01,00:00,2063.17,2063.44,2062.39,2062.76,253,0,200
```

### Step 2 – Export from cTrader / TradingView

**cTrader**: right-click chart → **Export Data** → CSV.

**TradingView**: open the chart → **Export chart data** button (bottom-right).

TradingView format (auto-detected):
```
time,open,high,low,close,Volume
2024-01-01 00:00:00,2063.17,2063.44,2062.39,2062.76,1234
```

### Step 3 – Run Backtest with CSV Files

```bash
python main_trading.py backtest \
    --symbols XAUUSD \
    --csv-1h  data/XAUUSD_H1.csv \
    --csv-15m data/XAUUSD_M15.csv \
    --csv-5m  data/XAUUSD_M5.csv
```

For USOIL:
```bash
python main_trading.py backtest \
    --symbols USOIL \
    --csv-1h  data/USOIL_H1.csv \
    --csv-15m data/USOIL_M15.csv
```

---

## 4. Setup & Installation

```bash
# Install all dependencies (includes yfinance)
pip install -r requirements.txt

# Verify the trading module loads correctly
python -c "from src.trading import Backtester, LiveMonitor; print('OK')"
```

No API keys, no paid subscriptions required.

---

## 5. Running Live Monitor Mode

Live monitoring uses yfinance (free, ~15-min delayed) and runs in
**paper-trade / signal-only mode by default**.  No real orders are ever
placed unless you subclass `TradeExecutor`.

### Basic usage

```bash
# Monitor XAUUSD and USOIL on default timeframes (1H, 15m, 5m)
python main_trading.py monitor

# Monitor only XAUUSD, poll every 5 minutes
python main_trading.py monitor --symbols XAUUSD --interval 300

# Custom timeframes
python main_trading.py monitor --symbols XAUUSD USOIL --timeframes 4H 1H 15m
```

### Custom risk settings

```bash
python main_trading.py monitor \
    --symbols XAUUSD \
    --atr-mult 1.5 \
    --max-sl-pips 40 \
    --risk-pct 0.5
```

### Output

Each signal is logged with:
```
signal  symbol=XAUUSD  direction=long  setup=ote_choch
        entry=2088.3400  sl=2076.2100  tp1=2112.5700  rr=1.85
```

Press **Ctrl-C** to stop. A session summary is printed on exit.

### Programmatic usage

```python
from src.trading.adapters.yfinance_adapter import YFinanceAdapter
from src.trading.monitor import LiveMonitor

def on_signal(sig):
    print(f"SIGNAL: {sig.symbol} {sig.direction} @ {sig.entry_price:.2f}")
    print(f"  SL={sig.stop_loss:.2f}  TP1={sig.take_profit_1:.2f}  R:R={sig.risk_reward:.2f}")

monitor = LiveMonitor(
    adapter=YFinanceAdapter(),
    poll_interval=60,
    signal_callback=on_signal,
)
monitor.run(symbols=["XAUUSD", "USOIL"], timeframes=["1H", "15m", "5m"])
```

---

## 6. Running Backtest Mode

### Using free yfinance data (quick start)

```bash
# Backtest both symbols using free yfinance proxy data
python main_trading.py backtest --symbols XAUUSD USOIL

# Save JSON reports
python main_trading.py backtest \
    --symbols XAUUSD USOIL \
    --json-out ./backtest_reports
```

### Using broker CSV files (exact accuracy)

```bash
python main_trading.py backtest \
    --symbols XAUUSD \
    --csv-1d  data/XAUUSD_D1.csv \
    --csv-4h  data/XAUUSD_H4.csv \
    --csv-1h  data/XAUUSD_H1.csv \
    --csv-15m data/XAUUSD_M15.csv \
    --csv-5m  data/XAUUSD_M5.csv
```

### Sample report output

```
====================================================
  FACTRADE Backtest Report – XAUUSD
  Period: 2023-01-03T00:00:00+00:00 → 2024-12-31T23:00:00+00:00
====================================================
  Total trades      : 47
  Wins / Losses     : 28 / 19
  Win rate          : 59.6 %
  Total pips        : 1240.5
  Avg win pips      : 82.3
  Avg loss pips     : -45.1
  Profit factor     : 2.73
  Max drawdown pips : 186.0
----------------------------------------------------
  By setup:
    ote_choch            n=  21  wr= 66.7%  pips=  743.0
    smma_ribbon          n=  12  wr= 58.3%  pips=  312.5
    bb_reversion         n=   8  wr= 50.0%  pips=   85.0
    vwap_breakout        n=   6  wr= 50.0%  pips=  100.0
====================================================
```

### Programmatic usage

```python
from src.trading.adapters.csv_adapter import CSVAdapter
from src.trading.backtester import Backtester

candles_by_tf = {
    "1H": CSVAdapter("data/XAUUSD_H1.csv", "XAUUSD", "1H").fetch(),
    "15m": CSVAdapter("data/XAUUSD_M15.csv", "XAUUSD", "15m").fetch(),
    "5m": CSVAdapter("data/XAUUSD_M5.csv", "XAUUSD", "5m").fetch(),
}

bt = Backtester()
report = bt.run(candles_by_tf, symbol="XAUUSD")
bt.print_report(report)

# Access individual trades
for trade in report.trades:
    print(trade.signal.setup_type, trade.pnl_pips, trade.exit_reason)
```

---

## 7. Strategy Logic Summary

The system implements all four setups from the FACTRADE Masterplan v7.0.

### Setup 1 – OTE + CHoCH (Universal – works in any regime)

```
HTF (1H/4H) candle sweeps a liquidity level (swing high/low, PDH/PDL)
    ↓
15m shows a Major CHoCH (strong displacement break)
    ↓
Price retraces into OTE zone: Fibonacci 0.618 – 0.786
    ↓
Entry at midpoint of OTE zone on 5m/15m confirmation
```

**Best for:** XAUUSD (Gold behaves very reliably with this setup).

### Setup 2 – SMMA Ribbon (Regime 1: Trending)

```
SMMA(31) clearly above/below SMMA(59) → trend confirmed
    ↓
Price pulls back to touch fast SMMA ribbon
    ↓
Hammer / long-wick rejection candle at ribbon
    ↓
Entry on candle close
```

**Best for:** USOIL / WTI (structural runner, follows SMMA well).

### Setup 3 – Bollinger Bands 199/1.9 (Regime 2: Consolidation)

```
5m Bollinger Bands (period=199, std=1.9) are FLAT (consolidation)
    ↓
Price touches outer band with a wick (sell-side / buy-side sweep)
    ↓
Close confirms return inside the band
    ↓
Entry; TP1 = midline, TP2 = opposite band
```

**Best for:** XAUUSD during Asian/quiet sessions.

### Setup 4 – VWAP Breakout (Regime 3: High Volatility)

```
Price returns from VWAP deviation band
    ↓
Two consecutive candles close on the same side of VWAP
    ↓
Third candle breaks the 2-bar high/low
    ↓
Entry on third candle close
```

**Best for:** London/NY session opens for both XAUUSD and USOIL.

---

## 8. Risk Management Rules

All rules from the Masterplan are enforced in `RiskManager`:

| Rule | Value |
|---|---|
| SL formula | `Wick extreme ± (1.5 × ATR) ± spread` |
| ATR period | 14 bars |
| Spread buffer | 2 pips |
| Max SL distance | 50 pips (trade skipped if exceeded) |
| Default risk per trade | 0.5 % of account balance |
| A+ setup risk | 1.0 % of account balance |
| TP1 (80 % close) | 2 × R (first internal liquidity) |
| TP2 (20 % runner) | 5 × R (HTF opposing liquidity) |

**Additional hard rules (not automated – enforce manually):**
- Daily stop: –2 R or –2 % (whichever hits first).
- Weekly stop: –5 R hard lock.
- No trades within 15 minutes of: FOMC, CPI, NFP, EIA Crude Inventories.
- Maximum correlated exposure: 1.5 % total.

---

## 9. Signal Schema

Every generated signal has these guaranteed fields:

```python
Signal(
    symbol      = "XAUUSD",          # str
    direction   = "long",             # "long" | "short"
    entry_price = 2088.34,            # float
    stop_loss   = 2076.21,            # float – always deterministic
    take_profit_1 = 2112.57,          # float – 80 % close target
    take_profit_2 = 2149.14,          # float – 20 % runner target
    timestamp   = datetime(..., utc), # UTC datetime
    setup_type  = "ote_choch",        # one of four setup types
    timeframe   = "15m",              # timeframe where entry was detected
    risk_reward = 1.85,               # R:R at TP1
    atr_at_entry = 5.3,               # ATR value at signal time
    metadata    = {...},              # setup-specific debug info
)
```

`stop_loss` and `take_profit_1/2` are always set before the signal is
emitted. No signal with `stop_loss == 0` will ever be returned.

---

## 10. Extending the System

### Adding a new data source

```python
from src.trading.adapters.base import BaseAdapter
from src.trading.candle import Candle

class MyBrokerAdapter(BaseAdapter):
    name = "my_broker"
    supports_live = True

    def fetch(self, symbol, timeframe, start=None, end=None, limit=None):
        raw = my_broker_api.get_ohlcv(symbol, timeframe)
        candles = [Candle(...) for row in raw]
        return self._filter_valid(candles)
```

### Adding a new setup

Add a method to `SignalGenerator` and call it from `scan()`:

```python
def my_custom_signal(self, candles):
    # ... detect setup ...
    sl_price, sl_pips, skip = self.risk.calculate_sl(...)
    if skip:
        return None
    tp1, tp2 = self.risk.calculate_tp(...)
    return Signal(
        ...,
        setup_type="ote_choch",  # use an existing type or extend the Literal
    )
```

### Enabling real-order execution

Subclass `TradeExecutor` and override `_place_order`:

```python
from src.trading.trade_executor import TradeExecutor

class LiveExecutor(TradeExecutor):
    def _place_order(self, pos_id, signal):
        my_broker.place_order(
            symbol=signal.symbol,
            direction=signal.direction,
            price=signal.entry_price,
            sl=signal.stop_loss,
            tp=signal.take_profit_1,
        )
```

Pass `paper_trade=False` to enable live execution.

> ⚠️ **Safety default:** `paper_trade=True` is always the default.
> Live execution is **opt-in only** and requires explicit subclassing.
