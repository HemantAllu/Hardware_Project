# Bug Fixes and Reliability Hardening Log

**System**: RV32IM High-Frequency Trading FPGA System  
**Release**: v12-complete-upgrade  

---

## 1. Summary of Corrected Defects

| Issue ID | Subsystem | Description | Root Cause | Fix / Resolution | Status |
|---|---|---|---|---|---|
| **BUG-01** | `tick_parser.v` | Parser stall / deadlock on UART framing errors | Parser state machine hung waiting for bytes when a framing error occurred mid-packet | Added `frame_err` recovery state transition back to `IDLE`, incrementing `PKT_ABORT` | Verified |
| **BUG-02** | `tick_parser.v` | Inter-byte timeout hang on truncated packets | If transmitter truncated packet (< 12 bytes), parser stayed in receive state forever | Added 100,000-cycle (1 ms) watchdog timer resetting parser to `IDLE`, incrementing `PKT_TIMEOUT` | Verified |
| **BUG-03** | `hft_alloc.v` | Negative cash over-allocation invariant breach | Rotation step could debit cash before verifying credited liquidation proceeds | Re-ordered allocation stages to ensure liquidation credit commits before buy debit; added strict non-borrowing guard | Verified |
| **BUG-04** | `hft_mmio.v` | Physical switch metastability / race on strategy toggle | Asynchronous switch `SW0` changed `strategy_mode` mid-computation cycle | Added 2-stage flip-flop synchronizer (`sw_strat_q1`, `sw_strat_q2`) and latched update strictly on `tick_accept` boundary | Verified |
| **BUG-05** | `soc_top.v` | Kill switch pin collision | `sw[0]` was assigned to both emergency kill switch and new strategy selector | Moved emergency kill switch to `sw[15]` (pin `V10`); dedicated `sw[0]` (pin `J15`) to strategy selector; assigned `led[0]` (pin `H17`) to indicate active strategy | Verified |
| **BUG-06** | `hft_dashboard.py` | CLI backward compatibility breakage during UI redesign | Complete replacement of file broke `--company all`, `--days`, `--log` batch runners used by verification testbenches | Unified dark Bloomberg terminal GUI with full CLI batch runner, supporting both interactive mode and batch verification | Verified |
| **BUG-07** | `hft_firmware.c` | Software missing MMIO definitions for new registers | RISC-V firmware did not define strategy config and audit registers | Added `HFT_STRAT_CFG` (0xA0), `HFT_STRAT_ORIG` (0xA4), `HFT_STRAT_MA` (0xA8), and `HFT_AUDIT_SEQ` (0xAC) | Verified |

---

## 2. In-Depth Technical Details

### 2.1 UART Framing Error Recovery (`src/rtl/tick_parser.v`)
In high-frequency serial interfaces, physical signal glitches or cable disconnects cause UART stop-bit framing errors (`frame_err`). Previously, `tick_parser.v` waited indefinitely for the expected 12 bytes. If a framing error occurred on byte 3, bytes 4–12 were misaligned, leading to corrupted price/volume interpretation.
- **Fix**: When `frame_err` asserts, the parser immediately aborts the in-flight packet, purges byte alignment registers, increments `PKT_ABORT` (`0x98`), and transitions directly to `IDLE` after a 3-cycle gap to wait for the next clean transmission.

### 2.2 Watchdog Inter-Byte Timeout (`src/rtl/tick_parser.v`)
To guard against truncated packets where fewer than 12 bytes are delivered:
- **Fix**: A 100,000-cycle counter (`timeout_cnt`) starts upon receiving byte 0. If 1 ms elapses without packet completion, the parser asserts an internal timeout abort, resets all byte accumulators, increments `PKT_TIMEOUT` (`0x9C`), and clears the interface.

### 2.3 Non-Borrowing Invariant (`src/rtl/hft_alloc.v`)
Under fast market rotation, selling a held asset and buying a new asset within the same allocation cycle risked transient negative cash balances if the buyer's cost exceeded available cash prior to liquidation settlement.
- **Fix**: Formal two-phase commit:
  1. Phase 1: Compute and commit all liquidation sales. Credited cash is deposited into `shared_cash`.
  2. Phase 2: Compute BUY candidate affordability strictly against the newly settled `shared_cash`.
  3. Assertion: Any order with `cost > shared_cash` is unconditionally rejected (`dec = NONE`).

### 2.4 Physical Strategy Selector & Boundary Latching (`src/rtl/hft_mmio.v`, `soc_top.v`)
Dynamic switching of trading strategies (SW0) while an order calculation is in-flight (cycles 1–5) could cause undefined behavior if signals toggled between cycle 2 and cycle 4.
- **Fix**:
  1. `sw[0]` is sampled through two flip-flops:
     ```verilog
     always @(posedge clk) begin
         sw_strat_q1 <= sw_strategy;
         sw_strat_q2 <= sw_strat_q1;
     end
     ```
  2. The actual operating register `active_strategy` is updated *only* when `tick_accept` is asserted:
     ```verilog
     always @(posedge clk or posedge rst) begin
         if (rst)
             active_strategy <= 1'b0;
         else if (tick_accept)
             active_strategy <= sw_strat_override ? sw_strat_reg[0] : sw_strat_q2;
     end
     ```
  3. LED0 is connected directly to `active_strategy_led`, giving real-time confirmation of the hardware's active strategy.
