# FACTRADE Trading System

A free-first, paper-safe XAUUSD / USOIL (WTI Crude Oil) trading system built on top of the FACTRADE platform. Implements Arjo's Liquidity Framework with HTF liquidity detection, LTF precision entries, ATR-based risk management, and an advanced exit manager.

---

## Quick-start (paper / signal mode — safe default)

```bash
pip install -r requirements.txt   # includes yfinance and pyarrow

python - <<'EOF'
from src.trading.data.broker_adapter import MockBrokerAdapter
from src.trading.monitor import LiveMonitor

adapter = MockBrokerAdapter(symbol="XAUUSD", timeframe="1H", seed=42)
monitor = LiveMonitor(feed_adapter=adapter, mode="paper", poll_interval_seconds=0)
monitor.start(max_iterations=5)
print(monitor.get_summary())
EOF
```

No broker credentials needed. No real orders are placed.

---

## Architecture

```
src/trading/
├── data/
│   ├── store.py           # Universal historical data store (SQLite + Parquet)
│   ├── fetcher.py         # Free public data (yfinance)
│   ├── resampler.py       # Exact 3H / 4H resampling from 1H source data
│   └── broker_adapter.py  # Pluggable live-feed adapters
├── analysis/
│   ├── liquidity_detector.py  # HTF liquidity pools (swing H/L, PDH/PDL, equal H/L)
│   └── signal_generator.py   # LTF entry signals (OTE 0.618–0.786, CHoCH, FVG)
├── execution/
│   ├── risk_manager.py           # ATR-based SL, 0.5–1% risk, daily/weekly stops
│   ├── exit_manager.py           # Advanced exit (partial TP, BE, trailing, time stop)
│   ├── trade_executor.py         # Paper / signal executor with JSON-Lines log
│   └── auto_execution_bridge.py  # Optional broker execution bridge (opt-in)
├── backtest/
│   └── backtester.py      # Walk-forward backtesting engine
└── monitor.py             # Live monitoring loop
```

---

## Feature overview

### 1 · Universal historical data store

All fetched / imported candles are stored in a portable local store so future backtests and reference queries never need to re-download data.

**Format:**
- **SQLite** (`data/trading_store/catalogue.db`) — metadata: symbol, timeframe, source, date range, fetch timestamp, resampling provenance.
- **Parquet** (`data/trading_store/*.parquet`) — normalised OHLCV data (columnar, efficient).

**API:**

```python
from src.trading.data.store import DataStore
from src.trading.data.fetcher import FreeFetcher

store = DataStore()                        # default: data/trading_store/
fetcher = FreeFetcher(store=store)

# Fetch and auto-save 3H XAUUSD (fetches 1H from yfinance, resamples exactly)
df = fetcher.fetch("XAUUSD", "3H", start="2023-01-01", end="2024-01-01")

# Subsequent calls load from local store — no download
df = store.load("XAUUSD", "3H")

# Incremental refresh (only new candles downloaded)
df = store.refresh("XAUUSD", "3H", fetcher)

# Inspect catalogue
print(store.list_entries())
```

**Fallback manager (store → yfinance → optional file import):**

```python
from src.trading.data.source_manager import DataSourceManager, ImportFileSpec

manager = DataSourceManager(
    store=store,
    file_sources={
        ("XAUUSD", "15m"): ImportFileSpec(path="data/imports/xauusd_15m.parquet"),
        ("WTIUSD", "15m"): ImportFileSpec(path="data/imports/wtiusd_15m.csv", source="broker_csv"),
    },
)

result = manager.get("XAUUSD", "15m", start="2024-01-01", end="2024-06-01")
if result.df.empty:
    print("No data available:", result.detail)
else:
    print("Loaded via", result.source, "rows:", len(result.df))
```

`DataSourceManager` checks Yahoo DNS/HTTPS before trying `yfinance`; if offline, it skips Yahoo and continues to optional imported files.

**GitHub Actions proxy/egress example:**

```yaml
env:
  HTTP_PROXY: ${{ secrets.HTTP_PROXY }}
  HTTPS_PROXY: ${{ secrets.HTTPS_PROXY }}
  NO_PROXY: ${{ secrets.NO_PROXY }}
```

Allow DNS + HTTPS egress to:
- `finance.yahoo.com`
- `query1.finance.yahoo.com`
- `query2.finance.yahoo.com`
- `guce.yahoo.com`

**Provenance:** when data is resampled from a finer source, `resample_from` is recorded in the catalogue (e.g. `"1H"` for 3H data built from 1H bars).

---

### 2 · Exact 3H / 4H resampling

yfinance does not provide native 3H or 4H bars. The `resampler` fetches 1H data and builds exact multi-hour candles:

| Aggregation rule | Formula |
|---|---|
| open | first constituent 1H open |
| high | max of constituent 1H highs |
| low  | min of constituent 1H lows |
| close | last constituent 1H close |
| volume | sum of constituent 1H volumes |

**Alignment** uses `origin="epoch"` so bars always fall on clean UTC boundaries:
- 3H: 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 UTC
- 4H: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC

**Validation helper** (`validate_resampling`) checks every bar's OHLCV values against the source data and reports mismatches. The test suite (`tests/test_trading_resampler.py`) proves correctness bar-by-bar.

> **Important distinction:** 3H/4H data computed via exact resampling from 1H is labelled `resample_from="1H"` in the catalogue. If a broker exports native 3H/4H bars (e.g. MT4 CSV), import them via `FileBridgeAdapter` and save with `resample_from=None` — those are true broker-native bars.

---

### 3 · Broker-feed live mode

#### Free mode (default)
`FreeFetcher` uses yfinance:
- `XAUUSD` → `GC=F` (Gold Futures, spot proxy)
- `USOIL` → `CL=F` (WTI Crude Futures)

#### Broker file bridge (low-manual-steps)
Export 1H history from MT4/MT5/cTrader and point `FileBridgeAdapter` at the file:

```python
from src.trading.data.broker_adapter import FileBridgeAdapter

adapter = FileBridgeAdapter(
    path="xauusd_1h.csv",   # broker-exported CSV
    symbol="XAUUSD",
    timeframe="1H",
    date_col="time",        # column name of the timestamp
)
adapter.connect()
df = adapter.get_candles()
```

Call `adapter.reload()` after each broker export for rolling updates.

#### Webhook bridge (TradingView / cTrader alerts)
`WebhookBridgeAdapter` starts a local HTTP server that accepts POST candle data:

```python
from src.trading.data.broker_adapter import WebhookBridgeAdapter
import os; os.environ["FACTRADE_WEBHOOK_ENABLED"] = "1"

adapter = WebhookBridgeAdapter(symbol="XAUUSD", timeframe="1H", enabled=True)
adapter.connect()    # starts Flask server on localhost:8765
```

Send candles via POST to `http://localhost:8765/candle`:
```json
{
  "symbol": "XAUUSD", "timeframe": "1H",
  "time": "2024-01-15T09:00:00Z",
  "open": 2050.10, "high": 2055.40, "low": 2049.80, "close": 2053.20,
  "volume": 1234
}
```

#### Custom broker adapter
Implement `LiveFeedAdapter` for any proprietary API:

```python
from src.trading.data.broker_adapter import LiveFeedAdapter
import pandas as pd

class MyBrokerAdapter(LiveFeedAdapter):
    def connect(self):    ...   # login, subscribe
    def disconnect(self): ...   # logout
    def get_candles(self, limit=500) -> pd.DataFrame:
        ...  # fetch from broker API, return normalised OHLCV
```

---

### 4 · HTF liquidity detection (Daily / 4H / 3H / 1H)

`LiquidityDetector` identifies institutional liquidity pools:

| Level type | Description |
|---|---|
| `swing_high` / `swing_low` | Pivot H/L confirmed by N bars each side |
| `pdh` / `pdl` | Previous Day High / Low |
| `pwh` / `pwl` | Previous Week High / Low |
| `equal_high` / `equal_low` | Clustered H/L within configurable tolerance |

Each level tracks status: `active` → `swept` (wick reversal) or `broken` (close continuation).

---

### 5 · LTF signal generation (15m / 30m entries)

`SignalGenerator` implements:
1. **CHoCH detection** — 15m/30m Change of Character after HTF sweep.
2. **Fibonacci OTE zone** — 0.618 – 0.786 retracement of the CHoCH range.
3. **FVG detection** — Fair Value Gap for confluence scoring.
4. **Regime tagging** — trend / range / volatile via SMMA 31/59 ribbon.

Output: `TradeSignal` with direction, entry, SL, TP1, TP2, confidence 0–1.

---

### 6 · ATR-based risk manager

| Parameter | Default | Description |
|---|---|---|
| `risk_pct` | 0.5% | Risk per trade (% of balance) |
| `aplus_risk_pct` | 1.0% | For A+ setups (confidence ≥ 0.8) |
| `max_sl_pips` | 50 | Skip trade if SL exceeds this |
| `atr_multiplier` | 1.5 | SL = wick ± 1.5 × ATR |
| `spread_pips` | 3 | Added to SL buffer |
| `max_lot` | 0.10 | Safety cap |
| `daily_stop_r` | -2R | Daily drawdown hard lock |
| `weekly_stop_r` | -5R | Weekly drawdown hard lock |

---

### 7 · Advanced exit manager (Marco 80/20 Rule + extensions)

Configure via `ExitConfig`:

```python
from src.trading.execution.exit_manager import ExitConfig

config = ExitConfig(
    partial_pct=0.80,            # close 80% at TP1
    breakeven_buffer_pips=10.0,  # runner SL = entry + 10 pips after TP1
    brokerage_pips=3.0,          # included in BE buffer
    trailing_stop=True,          # ATR trailing stop on runner (TP1→TP2)
    trail_atr_mult=1.5,          # trail distance = 1.5 × ATR
    max_hold_bars=0,             # 0 = no time stop
    pip_size=0.01,               # XAUUSD / USOIL pip size
)
```

**Exit sequence:**
1. **SL hit** → full close.
2. **TP1 reached** → close `partial_pct` of position, move SL to break-even.
3. **Trailing stop** (if enabled) → advance SL as price moves in favour.
4. **TP2 reached** → close remaining runner.
5. **Time stop** (if `max_hold_bars > 0`) → exit after N bars.
6. **Force close** → news filter or manual override.

The same `ExitConfig` is used by both the backtester and the live monitor, ensuring **deterministic, reproducible** behaviour.

---

### 8 · Backtesting

```python
from src.trading.data.store import DataStore
from src.trading.backtest.backtester import Backtester, BacktestConfig
from src.trading.execution.exit_manager import ExitConfig

store = DataStore()
config = BacktestConfig(
    symbol="XAUUSD",
    htf="4H",
    ltf="15m",
    account_balance=1400.0,
    risk_pct=0.5,
    exit=ExitConfig(partial_pct=0.80, trailing_stop=True),
)
bt = Backtester(store=store, config=config)
results = bt.run(start="2023-01-01", end="2024-01-01")
print(results["summary"])
```

**Long-run input contract (10-year style windows):**

```python
from src.trading.backtest.input_contract import ensure_long_run_inputs

inputs = ensure_long_run_inputs(
    store=store,
    source_manager=manager,
    start="2016-01-01",
    end="2026-01-01",
    symbols=["XAUUSD", "WTIUSD"],
    timeframes=["4H", "15m"],
)
if not inputs["ok"]:
    raise RuntimeError(f"Missing candles for long-run backtest: {inputs['items']}")
```

For long-run intraday backtests, the recommended workflow is:
1. preload local candle files (CSV/Parquet) into the fallback manager,
2. run `ensure_long_run_inputs(...)` to auto-populate store gaps,
3. run `Backtester.run(...)` using locally cached data.

Results:
```python
{
    "total_trades": 47,
    "winners": 28,
    "losers": 19,
    "win_rate": 0.596,
    "total_pips": 312.5,
    "avg_pips": 6.6,
    "final_equity": 1587.20,
}
```

---

### 9 · Optional auto-execution bridge

⚠️ **DISABLED BY DEFAULT.** Two independent gates must be opened to enable live execution:

1. Constructor flag: `enable_live_execution=True`
2. Environment variable: `FACTRADE_LIVE_EXECUTION=1`

**Safe default (paper/signal):**
```python
from src.trading.execution.auto_execution_bridge import AutoExecutionBridge
bridge = AutoExecutionBridge()   # uses NullBrokerAdapter — logs only
```

**File bridge (EA pickup):**
```python
from src.trading.execution.auto_execution_bridge import AutoExecutionBridge, FileBrokerAdapter
import os; os.environ["FACTRADE_LIVE_EXECUTION"] = "1"

bridge = AutoExecutionBridge(
    broker_adapter=FileBrokerAdapter(order_file="data/live_orders.jsonl"),
    enable_live_execution=True,
)
```
MT4/MT5/cTrader EA reads `live_orders.jsonl` and executes the orders.

**Socket bridge (DWX Connect / custom):**
```python
from src.trading.execution.auto_execution_bridge import AutoExecutionBridge, SocketBrokerAdapter
import os; os.environ["FACTRADE_LIVE_EXECUTION"] = "1"

bridge = AutoExecutionBridge(
    broker_adapter=SocketBrokerAdapter(host="127.0.0.1", port=9090),
    enable_live_execution=True,
)
```

**Custom broker adapter:** subclass `BrokerExecutionAdapter` and implement `place_order`, `modify_sl`, `close_order`.

---

### 10 · Live monitoring

```python
from src.trading.data.broker_adapter import FileBridgeAdapter
from src.trading.monitor import LiveMonitor
from src.trading.execution.exit_manager import ExitConfig
from src.trading.execution.risk_manager import RiskManager

adapter = FileBridgeAdapter("xauusd_1h.csv", symbol="XAUUSD", timeframe="1H")
monitor = LiveMonitor(
    feed_adapter=adapter,
    mode="paper",                              # safe default
    poll_interval_seconds=60,
    risk_manager=RiskManager(account_balance=1400.0, risk_pct=0.5),
    exit_config=ExitConfig(partial_pct=0.80, trailing_stop=True),
    news_events=["2024-01-26T14:30:00Z"],     # NFP — suppress ±15 min
)
monitor.start()    # runs until Ctrl-C
```

---

## Supported instruments

| FACTRADE symbol | yfinance proxy | Notes |
|---|---|---|
| `XAUUSD` | `GC=F` | Gold Futures. Spot proxy; close to broker spot. |
| `USOIL` / `WTIUSD` | `CL=F` | WTI Crude Futures. Use 3m/5m LTF (less 1m noise). |

---

## Running tests

```bash
# All trading system tests
python -m pytest tests/test_trading_*.py -v

# Just the resampling correctness suite
python -m pytest tests/test_trading_resampler.py -v

# Exit manager determinism / partial-TP / trailing
python -m pytest tests/test_trading_exit_manager.py -v
```

---

## Safety checklist

- [x] Default mode is paper/signal — no real orders placed.
- [x] Auto-execution requires **two** explicit opt-ins (constructor + env var).
- [x] Max lot size capped at 0.10 by default.
- [x] Daily `-2R` and weekly `-5R` drawdown hard stops built in.
- [x] News filter suppresses signals within ±15 minutes of flagged events.
- [x] `max_sl_pips=50` skip rule — trades with large SL are rejected.
- [x] All exit behaviour is deterministic via `ExitConfig` (same in backtest and live).
