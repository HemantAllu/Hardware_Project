# Project Architecture — RV32IM FPGA Trading Engine & Portfolio Allocator

## 1. System Overview

The system implements a hardware-accelerated high-frequency algorithmic trading coprocessor tightly integrated with a 32-bit RISC-V pipelined processor (RV32IM) on a Xilinx Artix-7 FPGA (Digilent Nexys A7-100T).

```
                      +---------------------------------------+
                      |       Nexys A7-100T FPGA Board       |
                      |                                       |
  [PC Dashboard] <==> | UART RX/TX <==> MMIO Interconnect     |
                      |                     ||                |
                      |       +-------------++------------+   |
                      |       |                           |   |
                      |  RV32IM CPU Core           Multi-Engine   |
                      |  (5-Stage Pipelined)       Accelerator |
                      |  - IF, ID, EX, MEM, WB    - N Engines |
                      |  - Multicycle M-Ext       - Allocator |
                      |       |                           |   |
                      |       +-------------+-------------+   |
                      |                     |                 |
  [SW0: Strategy] ==> | Synchronizer & Safe Boundary Latch    |
  [LED0: Active]  <== | Active Strategy Mode Indicator       |
                      +---------------------------------------+
```

---

## 2. Pipelined RV32IM Core (`src/rtl/rv32im_core.v`)

1. **Instruction Fetch (IF)**:
   - Program Counter (PC) increment and branch/jump redirection.
   - Dual-port synchronous ROM/RAM interfacing.
2. **Instruction Decode (ID)**:
   - RV32I base integer decoding and immediate generator.
   - Dual-read, single-write 32-entry register file (`x0` hardwired to zero).
3. **Execute (EX)**:
   - 32-bit arithmetic and logic unit (ALU).
   - Multicycle M-Extension coprocessor (`src/rtl/muldiv_unit.v`) implementing non-restoring division, remainder, and Wallace/Booth multiplication (32 clock cycles).
   - Hazard unit data forwarding from MEM and WB stages.
4. **Memory (MEM)**:
   - Load/store byte-addressable alignment logic.
   - Memory-mapped I/O (MMIO) decoder targeting address aperture `0x3000_0000 - 0x3000_00FF`.
5. **Writeback (WB)**:
   - Selects ALU result, memory load data, or multiplier/divider output to commit to register file.

---

## 3. Autonomous Multi-Company Accelerator (`src/rtl/hft_multi.v`)

The hardware accelerator instantiates $N$ identical parallel trading pipelines (`hft_accelerator.v`):
- **Cycle 1 (S1)**: Ingress price and volume latched; tick counter incremented; volume accumulator updated.
- **Cycle 2 (S2)**: 4-price sliding window shift; moving average computed via shift arithmetic; VWAP product ($P \times V$) calculated.
- **Cycle 3 (S3)**: Cumulative sum $\sum (P \times V)$ and cumulative volume $\sum V$ updated; fixed-point ratio evaluated.
- **Cycle 4 (S4)**: Technical signal generation:
  - Moving Average signal: $P > \text{MA} \implies \text{BUY}$, $P < \text{MA} \implies \text{SELL}$.
  - VWAP signal: $P > \text{VWAP} \implies \text{BUY}$, $P < \text{VWAP} \implies \text{SELL}$.
  - Breakout signal: $P > \text{BRK\_HIGH} \implies \text{BUY}$, $P < \text{BRK\_LOW} \implies \text{SELL}$.
  - Strategy Selection:
    - **Mode 0 (Baseline)**: 2-of-3 majority voting across MA, VWAP, Breakout.
    - **Mode 1 (MA-Only)**: Direct MA signal propagation.
- **Cycle 5 (S5)**: Risk validation:
  - Position limit check: $\text{Current Position} + \text{Volume} \le \text{POS\_LIMIT}$.
  - Cash limit check: $\text{Required Cash} \le \text{Company Cash Cap}$.
  - Prohibition of short-selling: SELL only allowed if $\text{Position} \ge \text{Volume}$.

---

## 4. Hardware Portfolio Allocator (`src/rtl/hft_alloc.v`)

Evaluates portfolio-wide decisions across all $N$ active assets:
1. **Momentum Scoring**: Evaluates short-term rate-of-change and distance above moving average.
2. **Priority Ranking**: Identifies strongest BUY candidate among non-capped assets.
3. **Rotation Mechanics**:
   - Compares buyer's momentum against weakest holding's momentum.
   - If $\Delta \text{Momentum} > \text{MARGIN}$ and holding duration $\ge \text{MIN\_HOLD}$, triggers rotation (liquidates weak holding, executes strong buy).
4. **Non-Borrowing Invariant**: Shared cash account strictly forbids negative balances:
   $$\text{Cash}_{\text{remaining}} \ge 0 \quad \text{and} \quad \text{Total Invested} \le \text{Initial Capital}$$

---

## 5. Physical Strategy Selector (P0-D Architecture)

To ensure glitch-free runtime switching between algorithmic strategies:
1. **Asynchronous Switch Input**: Digilent Nexys A7-100T onboard switch `SW0` (Package pin `J15`).
2. **Metastability Guard**: Two-stage flip-flop synchronizer (`sw_strat_q1`, `sw_strat_q2`) in `src/rtl/hft_mmio.v`.
3. **Safe Boundary Latching**: `active_strategy` updates strictly on `tick_accept` pulses (at the start of a transaction, never mid-flight).
4. **Visual Indicator**: Nexys A7 onboard LED `LED0` (Package pin `H17`) reflects active strategy:
   - `LED0 = OFF`: Baseline 2-of-3 voting mode.
   - `LED0 = ON`: Moving-Average-Only strategy mode.

