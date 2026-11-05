# Complete Project Audit — RV32IM Multi-Company FPGA HFT System

**Version**: v12-complete-upgrade  
**Target Hardware**: Digilent Nexys A7-100T (Xilinx Artix-7 XC7A100T, `xc7a100tcsg324-1`)  
**Clock Frequency**: 100 MHz (10.0 ns period)  
**Verification Date**: 2026-11-04  

---

## 1. Executive Summary

This audit establishes a complete verification baseline for the RV32IM High-Frequency Trading (HFT) processor and hardware accelerator system. The system combines:
1. A pipelined 5-stage RV32IM RISC-V CPU (`rv32im_core.v`, `hazard_unit.v`, `muldiv_unit.v`).
2. An autonomous parallel hardware accelerator (`hft_accelerator.v`, `hft_multi.v`) executing technical trading algorithms (4-price Moving Average, VWAP, Breakout detection, 2-of-3 voting, and strict risk checks).
3. A shared-cash portfolio allocator (`hft_alloc.v`) performing momentum ranking, rotation of weak holdings, dynamic reweighting, and strict non-borrowing cash management.
4. An MMIO integration layer (`hft_mmio.v`, `tick_parser.v`, `uart.v`) providing memory-mapped control, tick ingress, report egress, and physical hardware control via board switches and LEDs.
5. A professional dark quantitative trading terminal (`extras/hft_dashboard.py`), full backtesting suite, and performance benchmarking framework.

---

## 2. RTL Architecture Audit

### 2.1 Processing Core (`src/rtl/rv32im_core.v`)
- **Pipeline Architecture**: 5 stages (IF, ID, EX, MEM, WB).
- **Hazard Handling**: Load-use stall detection and dual-stage data forwarding (EX/MEM and MEM/WB stages) in `src/rtl/hazard_unit.v`.
- **M-Extension Multicycle Unit**: `src/rtl/muldiv_unit.v` implements multicycle signed/unsigned multiplication (32 cycles) and division/remainder (32 cycles). Handshake conforms strictly to RV32IM specifications with zero reported mismatches across 163,872 vectors.
- **Instruction Memory**: Dual-port BRAM / synchronous distributed ROM with C-firmware bootloader.

### 2.2 Autonomous Trading Engines (`src/rtl/hft_accelerator.v`, `src/rtl/hft_multi.v`)
- **Compute Latency**: 5 clock cycles (50 ns @ 100 MHz), fully deterministic.
- **Algorithm Implementations**:
  - **Moving Average**: 4-price sliding window sum with power-of-2 shift division.
  - **VWAP**: Cumulative $\sum (P \cdot V) / \sum V$ using fixed-point quotient registers with saturation guards (`vwap_overflow`).
  - **Breakout**: Upper (`brk_high`) and lower (`brk_low`) channel boundary comparison.
  - **Decision Voting**: 2-of-3 majority consensus between MA, VWAP, and Breakout signals.
  - **P0-D Strategy Selector**: Latched hardware runtime selection between original 2-of-3 voting (`strategy_mode=0`) and Moving-Average-Only voting (`strategy_mode=1`).
  - **Risk Constraints**: Strict volume limits, per-company position caps, and complete prohibition of short-selling or negative cash borrowing.

### 2.3 Shared-Cash Portfolio Allocator (`src/rtl/hft_alloc.v`)
- **Allocation Cadence**: Evaluates once every simulated bar / minute across all $N$ active companies.
- **Operations**:
  - Priority ranking of candidate BUY orders based on momentum scores.
  - Rotation logic: selectively liquidates weak holdings to fund stronger BUY candidates if momentum delta exceeds margin threshold.
  - Dynamic weight redistribution on position close with configurable weight floors.
  - Non-borrowing cash enforcement: total portfolio investment $\sum P_i \le \text{Starting Cash}$.
- **Latency Profile**: 13 to 64 clock cycles (130 ns to 640 ns) depending on $N$ and active rotation passes.

### 2.4 Communication & Interconnect (`src/rtl/tick_parser.v`, `src/rtl/hft_mmio.v`, `src/rtl/uart.v`)
- **Baud Rate**: 115,200 baud, 8-N-1.
- **Ingress Packet**: 12 bytes (`[31:0] tid`, `[31:0] price`, `[31:0] volume`).
- **Egress Packet**: 40 bytes with `0xAA55AA55` header and `0x55AA55AA` footer.
- **UART Framing Recovery**: Resilient framing error recovery logic with inter-byte timeout watchdog (`PKT_TIMEOUT`) and corrupted packet abort counter (`PKT_ABORT`).

---

## 3. Firmware & Software Interface Audit

### 3.1 C Firmware (`extras/hft_firmware.c`)
- Implements parallel software trading model on RV32IM core for live cross-verification against hardware accelerator.
- Polls MMIO status registers, computes software signals in 82 cycles (820 ns), writes back software decisions, and triggers UART report transmission.
- Updated to support `HFT_STRAT_CFG`, `HFT_STRAT_ORIG`, `HFT_STRAT_MA`, and `HFT_AUDIT_SEQ`.

### 3.2 Python Quantitative Stack (`extras/hft_model.py`, `extras/market_feed.py`, `extras/hft_dashboard.py`)
- **Reference Model**: Exact integer-level Python mirror of hardware pipeline (`HFTModel`, `MultiModel`, `PortfolioModel`).
- **Dashboard**: Professional 5-tab Bloomberg-inspired quantitative terminal (`Overview`, `Trading`, `Portfolio`, `Hardware`, `Research`).
- **Accounting Verification**: Continuous validation of the invariant $\text{Total Equity} = \text{Cash} + \sum (\text{Holdings}_i \times P_i)$.

---

## 4. Verification & Testing Audit Summary

| Component | Test Suite | Scope | Status |
|---|---|---|---|
| RV32IM CPU Core | `tb_rv32im_core.v` | Directed ALU, branch, jump, memory load/store | PASS |
| M-Extension | `tb_muldiv.v` | 163,872 randomized operand vectors | PASS |
| Strategy Selector | `test_strategy_selector.py`, `tb_strategy_selector.v` | SW0/LED0 transaction-boundary latching across $N=2, 4, 8$ | PASS |
| Non-Borrowing Invariant | `test_no_borrow.py` | Over-allocation, rotation, cash limits under stress | PASS |
| Multi-Company Replay | `test_companies.py` | 16 full-day market sessions across 8 companies | PASS |
| System RTL Elaboration | `xvlog` (Vivado 2025.2) | Full syntax and elaboration analysis | PASS |
| Mutation Testing | `run_complete_regression.py` | 4 injected behavioral faults (cash, limits, symbols) | PASS |

