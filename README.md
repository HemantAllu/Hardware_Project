# RV32IM FPGA High-Frequency Trading (HFT) System — Release V12 Complete

## Overview
This repository contains the complete FPGA-based low-latency multi-company trading engine on an RV32IM RISC-V SoC with a hardware portfolio allocator and institutional trading terminal.

- **Target Board:** Digilent Nexys A7-100T (Xilinx Artix-7 XC7A100T-1CSG324C)
- **Target Clock:** 100.0 MHz (10.0 ns period)
- **Verified Core $F_{max}$:** 103.9 MHz (Positive Worst Negative Slack +0.38 ns at $N=8$)
- **Core Compute Latency:** Deterministic 5 clock cycles (50.0 ns)
- **Speedup:** 164.2x faster than RV32IM CPU software baseline (8.21 µs)

---

## What's New in Dashboard V2.0

1. **Institutional Quant Dark Mode:**
   - Deep slate/obsidian canvas (`#0B0E14`), elevated cards (`#151921`), subtle borders (`#262C36`), and high-contrast monospace readouts (`Consolas`).
   - Semantic color system: Emerald Green for BUY and +PnL, Coral Red for SELL and drawdowns, Electric Cyan for FPGA hardware, and Amber for RV32IM CPU telemetry.
2. **Top Control & Status Bar:**
   - Live data source selector (FPGA UART, RTL simulation, Real market feed, Synthetic walk).
   - Execution controls: Run, Pause, Reset, Step Tick.
   - Physical Strategy Selector (SW0 toggle) between 2-of-3 voting and MA-only mode.
   - Live system health pills (Clock, Fmax, Strategy, Allocator, UART Link, System Health).
3. **KPI Hero Ribbon:**
   - 6 high-impact metric cards with delta badges: Portfolio Equity, Core Latency, Allocation Latency, Hardware Speedup, Throughput, and Risk Metrics.
4. **Interactive Multi-Tab Workspace:**
   - **Tab 1: Live Trading & 8-Company Monitor:** Sortable multi-company quote table, synchronized 2-panel equity & drawdown curves, and live auto-scrolling order tape.
   - **Tab 2: Hardware Telemetry & Pipeline Inspector:** Searchable 44-register live MMIO map, RV32IM 5-stage pipeline counters (CPI, stalls, forwarding), latency breakdown, and fault simulation injector.
   - **Tab 3: Scalability, Ablation & Benchmark Explorer:** Empirical FPGA resource scaling curves, Fmax curves, and side-by-side strategy backtest tables.
5. **Headless & CI Capture:**
   - High-resolution dark terminal snapshot generation (`--snapshot-dark --save-png results/dashboard_snapshot.png`).

---

## Quick Start

### 1. Launch Interactive Dashboard V2.0
```bash
python extras/hft_dashboard.py --gui
```

### 2. Capture Headless Dark Terminal Snapshot
```bash
python extras/hft_dashboard.py --snapshot-dark --save-png results/dashboard_snapshot.png --no-plot
```

### 3. Run Complete 10-Stage Automated Regression
```bash
python extras/tools/run_complete_regression.py
```

### 4. Run Multi-Company Verification Suite
```bash
python extras/tools/test_companies.py
```

---

## Documentation Index

- [Dashboard V2.0 User & Architecture Guide](docs/DASHBOARD_V2.md)
- [Dashboard Hardware Interface & MMIO Specification](docs/DASHBOARD_HARDWARE_INTERFACE.md)
- [Dashboard Verification & Test Report](docs/DASHBOARD_TEST_REPORT.md)
- [Complete MMIO Register Map](docs/MMIO_REGISTER_MAP.md)
- [UART Protocol Specification](docs/UART_PROTOCOL.md)
- [Full Project Architecture](docs/PROJECT_ARCHITECTURE.md)
- [Resource Scalability Report](docs/RESOURCE_SCALABILITY.md)
- [Quantitative Backtesting Report](docs/BACKTESTING_REPORT.md)
- [Bug Fixes & RTL Audit](docs/BUG_FIXES.md)

