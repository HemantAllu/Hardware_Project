# Professional Quantitative Trading Terminal — Dashboard Guide

**System**: RV32IM FPGA Multi-Company High-Frequency Trading System  
**Module**: `extras/hft_dashboard.py`  

---

## 1. Interface Philosophy & Visual Architecture

The redesigned dashboard provides an institutional-grade dark quantitative trading interface modeled after modern high-frequency trading terminals (Bloomberg AIM, FlexTrade, TT).

### Color Palette
- **Background**: Deep charcoal/black (`#121212`) for high contrast and reduced eye fatigue during extended trading sessions.
- **Card Panels**: Elevated surface dark gray (`#1e1e1e`) with clean 1px borders (`#2e2e2e`).
- **Semantic Accents**:
  - Green (`#00e676`): BUY orders, positive unrealized/realized P&L, healthy subsystem status.
  - Red (`#ff5252`): SELL orders, negative P&L, system fault/warning states.
  - Blue (`#2979ff`): System telemetry, navigation accents, active selections.
  - Amber (`#ffd600`): Rotation events, margin boundary alerts.
  - Cyan (`#00e5ff`): Moving Average Only strategy indicator.

---

## 2. Navigation & Five Core Tabs

### 2.1 Tab 1: Overview
- **System Top Bar**: Real-time display of FPGA connection state (`LIVE HARDWARE` vs `SIMULATION / DEMO`), serial port, baud rate (115,200), CPU clock (100 MHz), and active trading mode.
- **Active Strategy Banner (P0-D)**: Real-time status of physical switch `SW0` and board `LED0`. Indicates whether the core is executing the **Baseline 2-of-3 Voting Strategy** or the **Moving-Average-Only Strategy**.
- **Portfolio Metrics Bar**: Real-time KPI cards:
  - Initial Capital ($)
  - Cash Balance ($)
  - Invested Capital ($)
  - Unrealized & Realized P&L ($ / %)
  - Accounting Invariant Badge: Confirms $\text{Equity} = \text{Cash} + \sum (\text{Position}_i \times P_i)$.
- **Multi-Company Price Grid**: Real-time quotes, spreads, and 1-minute price trends for all 8 supported assets (AAPL, NVDA, GOOGL, MSFT, AMZN, WMT, META, TSLA).

### 2.2 Tab 2: Trading Operations
- **Interactive Multi-Asset Chart**: High-resolution time-series plotting price bars, 4-price Moving Average, VWAP curve, and Breakout upper/lower bounds.
- **Execution Markers**: Visual BUY (green up-triangle) and SELL (red down-triangle) indicators positioned exactly at the execution tick.
- **Order Blotter**: Filterable real-time table logging recent execution events with timestamp, symbol, side, fill price, quantity, and execution source.

### 2.3 Tab 3: Portfolio & Risk Management
- **Holdings Table**: Current lot inventory, average entry price, market valuation, allocation percentage, and unrealized return per company.
- **Asset Allocation Donut**: Visual breakdown of portfolio capital distribution across active positions and reserve cash.
- **Rotation Audit Ledger**: Detailed historical log of portfolio rebalancing and momentum rotations (asset liquidated, asset purchased, momentum delta).

### 2.4 Tab 4: Hardware Diagnostics & Fault Injection
- **FPGA Diagnostic Register Table**: Direct live view of MMIO diagnostic registers:
  - `OVERRUN` (`0x2C`): Ingress buffer drop count.
  - `ENG_DROP` (`0x90`): Processing stall drops.
  - `FRAME_ERR` (`0x8C`): UART framing errors.
  - `PKT_ABORT` (`0x98`): Framing glitch packet aborts.
  - `PKT_TIMEOUT` (`0x9C`): Inter-byte watchdog timeouts.
  - `VWAP_OFF` (`0x94`): VWAP saturation counter.
- **Latency Distribution Plot**: Visual breakdown comparing FPGA hardware compute latency (50 ns) against RV32IM software latency (820 ns).
- **Interactive Fault Injection Controls (P0-B)**:
  - Inject Framing Error Glitch (forces missing stop bit).
  - Inject Truncated Packet (sends 7 bytes instead of 12).
  - Inject Buffer Overrun Burst (transmits 20 ticks at wire speed).
  - Inject Soft Reset (triggers `CMD_RESET`).
- **Transaction Audit Trail (P0-C)**: Monotonically incrementing transaction sequence IDs with a one-click button to export the complete ledger to CSV.

### 2.5 Tab 5: Quantitative Research & Backtesting
- **Strategy Backtesting View**: In-sample training and out-of-sample test results.
- **Ablation Comparison**: Performance delta when removing momentum ranking, rotation, or reweighting.
- **Risk Metrics**: Sharpe ratio, maximum drawdown duration, win rate, and profit factor.

---

## 3. Command-Line Invocation Modes

### 3.1 Interactive GUI
```bash
python extras/hft_dashboard.py --gui                     # Force dark GUI mode
python extras/hft_dashboard.py --port COM3               # Connect to physical Nexys A7 FPGA
python extras/hft_dashboard.py --port none               # Interactive demo using offline Python model
```

### 3.2 Automated Regression & Headless Mode
```bash
python extras/hft_dashboard.py --snapshot-dark --save-png results/dashboard_snapshot.png --no-plot
```

### 3.3 Historical Batch Replay Mode
```bash
python extras/hft_dashboard.py --company all --days 2 --port none --out-dir results_batch
python extras/hft_dashboard.py --company apple,nvidia --together --strategy hybrid
```

