# Professional Trading Dashboard V2.0 — Architecture & User Guide

## Institutional Quant Dark Mode Telemetry Terminal

The RV32IM High-Frequency Trading (HFT) Dashboard has been overhauled and upgraded to **Version 2.0**. Inspired by institutional trading systems (Bloomberg Terminal, Jane Street telemetry desks, Grafana), the new dashboard provides real-time multi-stock monitoring, hardware accelerator profiling, risk analytics, and live inspection of the RV32IM SoC.

---

## 1. Design Philosophy & Visual Aesthetic

- **Theme Palette:** Deep slate/obsidian canvas (`#0B0E14`), elevated card surfaces (`#151921`), secondary hover surfaces (`#1C2331`), and subtle structural borders (`#262C36`).
- **Typography:** High-contrast monospace fonts (`Consolas`, `JetBrains Mono`) for all financial and hardware numeric telemetry to eliminate jitter during rapid tick updates.
- **Semantic Color Coding:**
  - **Emerald Green (`#00E676`):** BUY signals, positive PnL (+USD), and hardware compute speedups.
  - **Coral Red (`#FF5252`):** SELL signals, negative PnL, drawdowns, and dropped packets.
  - **Electric Cyan (`#00E5FF`):** FPGA Hardware Accelerator metrics and live telemetry.
  - **Amber / Gold (`#FFD740`):** RV32IM CPU Software Baseline metrics, pipeline stalls, and warnings.
  - **Sky Blue (`#38BDF8`):** Shared-cash portfolio allocator metrics and active company selection.

---

## 2. Architecture & Modular Package Structure

The dashboard code is organized into a modular Python package located in `extras/dashboard/`:

```
extras/
├── hft_dashboard.py              # Main CLI entry point & backward-compatible batch runner
└── dashboard/                    # Modular Dashboard V2.0 Package
    ├── __init__.py               # Package exports
    ├── theme.py                  # Quant dark theme constants, fonts, and matplotlib styles
    ├── mmio_map.py               # Complete 44-register MMIO map definitions & decoders
    ├── engine.py                 # Multi-company quantitative engine, audit log & accounting
    ├── serial_if.py              # UART 115200 serial packet exchange & resync framing
    ├── ui.py                     # Tkinter + Matplotlib interactive desktop GUI
    └── snapshot.py               # Headless high-res dark terminal snapshot generator
```

---

## 3. Core Modules & Layout

### A. Top Control & System Status Bar (Header)
- **Data Source Selector:** Switch between `Live UART / Nexys A7 FPGA (COM6)`, `RTL Simulation (Python Bit-Exact Model)`, `Real Market Data Feed (Yahoo 1-min)`, and `Synthetic Data (SYN1-SYN8)`.
- **Execution Actions:** `Pause/Run`, `Step Tick`, `Reset`, and `Export Snapshot`.
- **Physical Strategy Switcher (SW0):** Toggle between **Original 2-of-3 Voting** (MA + VWAP + Breakout) and **MA-Only Mode** (Moving Average consensus).
- **System Health Status Pills:** Live status for Clock Frequency (`100.0 MHz Artix-7`), Core Fmax (`103.9 MHz`), Active Strategy (`SW0`), Portfolio Allocator Mode, UART Link Status (`115200 8N1 [ONLINE]`), and System Health (`HEALTHY / DEGRADED`).

### B. KPI Hero Ribbon (Top-Level Summary Cards)
Six high-impact summary metric cards with live delta badges:
1. **Total Portfolio Equity & Net PnL:** Real-time valuation (`$100,021,573.73`), live dollar delta (`+$21,573.73 (+0.022%)`), and available shared cash balance.
2. **Tick-to-Trade Latency:** Hardware decision latency (`50.0 ns / 5 cycles`) with deterministic P50/P99 guarantees.
3. **Portfolio Allocation Latency:** Multi-stock rebalance execution time (`320.0 ns / 32 cycles`, min 13c, max 64c).
4. **Hardware Speedup Factor:** Speedup multiplier (`164.2x Faster`) comparing FPGA 50 ns decision vs RV32IM CPU software baseline (8.21 µs / ~82 cycles).
5. **Throughput & Link Rate:** Hardware throughput capability (`20.0 M Ticks/s`) vs UART line rate (`2.88 kTPS`), with dropped packet and overrun tracking.
6. **Risk & Execution Summary:** Maximum drawdown (`0.01%`), Sharpe ratio (`20.73`), win rate (`68.4%`), and total executed trades (`1,478`).

---

## 4. Main Multi-Tab Workspace

### Tab 1: Live Trading & 8-Company Portfolio Monitor
- **Multi-Company Grid (AAPL, NVDA, GOOGL, MSFT, AMZN, WMT, META, TSLA):**
  - Sortable live table displaying: Ticker, Last Price ($), Bid/Ask spread, Volume, 4-Point Moving Average, Volume-Weighted Average Price (VWAP), Momentum Score, Strategy Mode, Hardware Signal (BUY/SELL/HOLD), Position (Lots), Capital Allocated ($), Weight (%), and Individual PnL ($).
  - Double-clicking any company immediately locks the focus onto that company's technical chart.
- **Synchronized Charts:**
  - **Upper Panel:** Live Portfolio Valuation Curve ($) tracking total mark-to-market equity.
  - **Lower Panel:** Individual Company Price Action with 4-Point Moving Average overlay and technical markers.
- **Live Order & Signal Tape:**
  - Auto-scrolling execution tape capturing every tick decision: Timestamp, Transaction ID, Ticker, Hardware Signal, Execution Action (BUY / SELL / ROT / HOLD), Price, Traded Lots, Compute Latency (cyc/ns), and State Status (`OK / MISMATCH`).
  - Includes a dedicated "Export CSV" feature to archive raw execution audit logs.

### Tab 2: Hardware Telemetry, Latencies & RV32IM Pipeline Inspector
- **Searchable MMIO Register Map Inspector:**
  - Live inspection table of all **44 memory-mapped registers** (Offsets `0x00` through `0xAC`, Base `0x3000_0000`).
  - Search/filter by register name, hex offset, or functional description.
  - Real-time conversion of raw hex words into decoded physical engineering units (e.g., USD dollars, lots, nanoseconds, cycles, bitmask status flags).
- **RV32IM 5-Stage Pipeline Performance Counters:**
  - Real-time breakdown of CPU execution metrics: Total Clock Cycles, Instructions Executed, Average CPI (`1.15`), Hazard Stalls, Branch Penalty Cycles, and Forwarding Hits (MEM-to-EX and EX-to-EX).
- **Latency Breakdown & Percentile Distribution:**
  - Bar chart comparing sub-microsecond hardware latencies against software baselines (Log scale).
  - Allocator execution latency histogram verifying 13–64 cycle execution bounds.
- **Fault Simulation Injector:**
  - Interactive triggers for Hardware-in-the-Loop verification: UART Framing Error, Invalid Symbol ID, Burst Overrun, Parser Gap Timeout, and Engine Reset.

### Tab 3: Scalability, Ablation & Benchmark Explorer
- **Dynamic Dataset Integration:**
  - Automatically loads and parses empirical benchmark datasets directly from `results/` (`resource_scalability.csv`, `benchmark_results.csv`, `backtest_results.csv`, `ablation_results.csv`).
- **Interactive Scalability Plots:**
  - **Resource Utilization:** FPGA LUT and Flip-Flop scaling across $N = 1, 2, 4, 8$ companies.
  - **Maximum Operating Frequency ($F_{max}$):** Operating frequency curve across multi-company builds maintaining timing closure above the 100 MHz target clock ($103.9 \text{ MHz}$ at $N=8$).
- **Ablation & Strategy Performance Table:**
  - Side-by-side comparison of `Buy and Hold`, `Original 2-of-3 Voting`, `MA-Only Mode`, `No-Ranking`, `No-Rotation`, `No-Reweight`, and `Zero-Fee Baseline`.

---

## 5. How to Launch and Use

### Interactive Desktop GUI Mode
To launch the full graphical trading terminal:
```bash
python extras/hft_dashboard.py --gui
```
Or simply run without batch flags:
```bash
python extras/hft_dashboard.py
```

### Headless Snapshot Generation (Automated Regression / CI)
To capture a high-resolution 16:9 dark terminal snapshot without opening a window:
```bash
python extras/hft_dashboard.py --snapshot-dark --save-png results/dashboard_snapshot.png --no-plot
```

### Backward-Compatible CLI Batch Execution
All baseline CLI flags (`--company all`, `--together`, `--days 2`, `--speed`, `--log`, `--strategy independent`) continue to function with 100% fidelity:
```bash
python extras/hft_dashboard.py --company all --days 2 --port none --out-dir results_demo
python extras/hft_dashboard.py --company apple,nvidia --together --port none --no-plot --log results_together.csv
```

