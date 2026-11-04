> **v12 note:** parts of this file are superseded (shared-cash priority now serialises one engine per cycle, allocation latency, kill switch, STATUS bit 6, FRAME_ERR). See CHANGES_V12_BUGFIXES.md.

# Trading accelerator: bugs found and fixed

The base RV32IM core (`rv32im_core.v`, `alu.v`, `muldiv_unit.v`, ...) was not changed.
The trading files are `hft_accelerator.v`, `hft_mmio.v`, `tick_parser.v`, `uart.v`, `soc_top.v`,
plus `extras/hft_firmware.c` and `extras/hft_dashboard.py`.

## How to check

```
bash extras/tools/run_hft_tests.sh      # trading unit test + full-system test (~20 s)
python3 extras/tools/run_tests.py       # core regression (muldiv, directed, soc, C, random)
```

| Test | Original upload | Fixed |
|---|---|---|
| System test: reports received | none (each arrived as 16 of 32 bytes) | 80 of 80 |
| HW decision = reference model | 72 of 80 (after a UART fix) | 80 of 80 |
| SW decision = HW decision | 49 of 80 (after a UART fix) | 80 of 80 |
| Unit test, 3000 random ticks | 309 wrong decisions | 0 wrong |
| Core regression (`run_tests.py`) | did not build | all pass |

## Bugs

**Board would not run the trading system**
1. `src/mem/imem.mem` was still the old LED/7-segment demo, so the FPGA never ran the trading firmware.
   It now holds `hft_firmware.c` (the old demo image is kept as `extras/sw/demo_board_imem.mem`).
2. `create_project.tcl` and `rv32im.xpr` did not add `hft_mmio.v`, `hft_accelerator.v`, `tick_parser.v`, `uart.v`,
   so synthesis would fail with missing modules. Both now list all 16 RTL files.

**UART**
3. Every second byte sent to the PC was lost. After a write to `UART_TX`, the UART lowers `ready` one cycle
   late, so the firmware's next status poll still saw "ready" and its next write was dropped. Each 32-byte
   report arrived as 16 bytes and the dashboard could never decode one. Fixed: STATUS bit 2 = `tx_ready & ~tx_start`.
4. `tick_parser` had no way to recover framing: one lost byte, or resetting the board while the PC is
   sending, shifted every later packet by some bytes forever. It now drops a partial packet after ~5 ms of silence.
5. UART receive synchroniser started at X/0, which can look like a start bit after configuration; it now starts high.

**Accelerator**
6. `latency_cycles` was the constant 5, not a measurement. It is now counted from `tick_valid` (data_valid)
   to `decision_valid` with a cycle counter; it measures 5.
7. False BUY signals at start-up: the moving average included three zero prices, so the first ticks always
   looked "above average" (HW BUY on ticks 2 and 3 of the test). MA now votes only after 3 earlier ticks.
8. The VWAP compare did a 32 x 64-bit multiply and a 64-bit compare in one cycle (a timing risk at 100 MHz).
   The multiply and the compare are now in separate cycles; the volume sum is 32 bits. Latency is still 5 cycles.
9. `kill_switch` (SW0) went straight into the decision logic without a synchroniser; now 2 flip-flops.
10. A tick arriving while the engine was busy was silently lost; there is now a 1-entry buffer.

**MMIO**
11. If a new tick (or HW result) arrived in the same cycle the CPU cleared the flag, the clear won and the
    tick was lost. The hardware set now has priority. Also added `OVERRUN` (0x3000_002C): ticks that arrived
    before the CPU consumed the previous one.

**Firmware**
12. Software and hardware used different rules (software capped buys by capital and filled partially;
    hardware does all-or-nothing on the tick volume), so their positions drifted and decisions disagreed
    on 31 of 80 ticks. The software now uses exactly the hardware rules; capital is tracked only for the display.
13. Flags were cleared only after the 3 ms UART report, which could erase a tick that arrived meanwhile.
    TICK_READY is now cleared right after reading the tick, HW_DONE right after reading the result.
14. `crt0.S` did not zero `.bss`: after pressing CPU RESET the hardware state reset but the software's
    history did not. `.bss` is now zeroed at every start.
15. LED2 now lights when the hardware and software decisions differ (should never happen).

**Dashboard (`hft_dashboard.py`)**
16. No resync: after one lost or extra byte, every later report was misaligned. It now searches for the header and footer.
17. It overwrote the hardware decision with its own 1-share cash rule, so the plotted trades were not the
    FPGA's trades. It now follows the hardware decision and the full tick volume (same as the hardware position).
18. Simulation mode plotted random BUY/SELL decisions; it now uses the same strategy model.

**Test tooling**
19. `run_tests.py` could not build `soc_top` (missing trading files) and `tb_soc.v` lacked the UART ports. Fixed.

## Not changed, but check before the demo
* `download_apple_data.py` truncates prices to whole dollars and divides volume by 100. Apple trades around
  $200+, so with `BRK_HIGH = 150` the breakout engine votes BUY on every tick, and minute volumes / 100 are
  often above `POS_LIMIT = 1000`, which blocks most BUYs. Pick thresholds and scaling that fit the data
  (the thresholds are `CFG_*` in `hft_firmware.c`; the hardware gets them over MMIO at start-up).
* Kill switch: hardware and software sample SW0 a few hundred cycles apart, so toggling it exactly while a
  tick is processed can make the two disagree on that one tick (LED2 shows it).
* Timing was not checked in Vivado here. Check the timing report after implementation; the 32 x 32
  multipliers in `hft_accelerator.v` are the most likely critical path.

## Accelerator register map (0x3000_0000, word access)
| Offset | Name | Access |
|---|---|---|
| 0x00 | POS_LIMIT | RW |
| 0x04 | BRK_HIGH | RW |
| 0x08 | BRK_LOW | RW |
| 0x0C / 0x10 / 0x14 | TICK_ID / PRICE / VOL (last UART tick) | R |
| 0x18 / 0x1C / 0x20 | HW_DECISION (0 none, 1 BUY, 2 SELL) / HW_LATENCY / HW_POSITION | R |
| 0x24 | STATUS: bit0 tick ready, bit1 HW done, bit2 UART TX ready (write 1 to bit0/bit1 to clear) | RW |
| 0x28 | UART_TX (one byte) | W |
| 0x2C | OVERRUN count | R |

## Second review (after the first Vivado build)
(These timing/utilisation numbers are for the v4 RTL **before** the cash interlock and the v5
fixes below; re-run implementation for the current sources.)
Checked the uploaded project and its Vivado reports (synthesis, implementation, bitstream):
* Timing met at 100 MHz: WNS +0.397 ns, WHS +0.048 ns, 0 failing endpoints. The worst path is in the core
  (EX/MEM rd -> forwarding -> branch decision -> ID/EX flush), not in the trading accelerator.
* Utilization: 3,037 LUTs (4.8 %), 1,969 FFs (1.6 %), 12 DSP48 (4 core multiplier + 8 accelerator), 0 BRAM.
* imem.mem / dmem.mem read successfully; UART pins placed on C4 / D4; no critical warnings, no latches.
* Removed `prod_r` / `l_pv` registers in the synthesis log are Vivado moving them into the DSP blocks (expected).
* Fixed: TIMING-18 (missing I/O delay on uart_rx / uart_tx) -> false-path constraints added to the XDC.
* Still open (strategy settings, not RTL bugs): Apple prices (~$200+) are above BRK_HIGH = 150, so the breakout
  engine votes BUY on every tick, and minute volume / 100 is often above POS_LIMIT = 1000.
* Timing margin is only 0.4 ns: re-check the timing report after any change to the core's EX stage.

## Real-data version (v4)
* Real AAPL data: `extras/apple_feed.py`, new `hft_dashboard.py` (replay / live / CSV), `verify_run.py`,
  `download_apple_data.py` (keeps real prices; sent as cents). See `extras/README_REAL_DATA.md`.
* Fixed the "negative position" seen on the board: the board kept its state from the previous run while the
  dashboard restarted at 0. The PC now sends RESET and the configuration at the start of every run.
  RTL: CTRL register (0x3000_0030) clears the accelerator; packets with id bit 31 set are commands for the
  firmware and are not traded on. Firmware: runtime configuration, 40-byte report with the volume echo and
  the hardware position, 7-segment shows the position in decimal (using the RV32M divider).
* Shared reference model `extras/hft_model.py` (dashboard, verify_run.py and tools/check_hft.py).
* Tests: trading unit test PASS, system test PASS (126 lines incl. reset and AAPL-scale config),
  core regression ALL PASS. Re-run synthesis / implementation / bitstream for this version.

## v5 review fixes

| # | Problem | Fix | Test that now catches it |
|---|---|---|---|
| 1 | `src/mem/imem.mem` was a stale image (older than `hft_firmware.c`): the board ignored `CMD_CFG_CASH`, and its software decisions differed from the hardware whenever cash was short. | Rebuilt from the current firmware. New `extras/tools/make_board_image.sh` builds and installs the image in one step. | `run_hft_tests.sh` stage 5 runs the system and flow tests on the **shipped** `imem.mem`. It fails on the old image (136 problems). |
| 2 | Timing risk: S4 multiplied `price * vol` again (32x32 bit, not registered) and fed the result into a 64-bit compare and a 64-bit add/subtract, all in one cycle. | `trade_cost = l_pv`, the same product already registered in S1, so S4 starts from a register instead of an unregistered multiplier output. Bit-identical results. The DSP count is the same (synthesis merges the two identical multiplies, which is exactly why S4 used to depend on the unregistered product). | Stage 2 cash test (about 14,000 ticks, decision + position + **cash** per tick). |
| 3 | With the old default of $1,000,000 and whole-bar trades, real AAPL data never traded: one lot costs about $250,000 and a bar is typically about 100 lots. Every check "passed" with position 0 throughout. | The default `--starting-cash` for real data is now $1,000,000,000. The dashboard and `verify_run.py` print how many signals the risk interlock refused, and warn when cash blocks most BUYs or nothing traded. The returns graph says "no trades executed" when that happens. | Dashboard/verify summary lines (see README_REAL_DATA.md). |
| 4 | If the PC sent faster than the board answers (a 40-byte report takes about 3.5 ms, a tick about 1 ms), the CPU's latched tick was overwritten while the accelerator had already traded on it. Hardware and software silently drifted apart. | `hft_mmio.v`: while TICK_READY is set, a new packet is **dropped for the CPU and the accelerator alike**. OVERRUN counts the drops (cleared by CTRL), the firmware lights LED3, and hardware and software stay in step. | Stage 4 flow test: 14 packets back to back give 5 reports and 9 drops; every report matches the model; LED3 on, LED2 off. With the old `hft_mmio.v` it fails (HW position 130 vs 40, LED2 on). |
| 5 | The MA vote compared the price with the rounded-down average, so a price just below the true average got no vote. | Exact compare `4*price` vs the sum of 4 prices, in the RTL, firmware and Python model. | `test_no_borrow.py` (old model gives NONE, new gives SELL); unit test (fails on the old RTL). |
| 6 | A zero-volume tick could report BUY/SELL although nothing was traded. | Volume 0 never trades (RTL `vol_ok`, firmware, model; counted as `zero_vol`). | Unit, cash and system tests now include zero-volume ticks. |
| 7 | The CPU read the slide switches without a synchroniser. | 2-flip-flop synchroniser (`ASYNC_REG`) in `soc_top.v`; `ASYNC_REG` on the kill-switch synchroniser too. | Core regression (`run_tests.py`) still passes. |
| 8 | Dashboard: the status box was cut off at the right edge with large dollar amounts; cash was tracked in floating point; `int(cash*100/lot)` could lose a unit (for example `int(0.29*100) = 28`). | Wider layout and box, `-$` sign formatting, exact integer cash (same units as the hardware), exact decimal conversion of `--starting-cash`. | Snapshots checked by eye; `verify_run.py` check 6 compares every logged return with an exact model replay. |
| 9 | Docs out of date: README_VIVADO described the old LED demo image; README_core_and_tests used the old folder layout. | Updated. | - |

**New: returns graph.** The dashboard window and the `--save-png` snapshot have a separate graph
of the return on the starting cash: (cash + holdings at the bar close - starting cash) / starting cash,
per tick, with the final, best and worst return. The CSV log has new columns `cash_usd`, `equity_usd`
and `return_pct`, and `verify_run.py` checks them and draws the same graph.

**Tests (all pass):** `bash extras/tools/run_hft_tests.sh` runs stages 0-5:
model rules, unit (3000 ticks), cash interlock (3 x about 4,700 ticks), system (328 lines),
flow control, shipped board image. `python3 extras/tools/run_tests.py` runs the core regression
(muldiv, directed, soc, 5 C programs, random programs).

**Not checked here (needs Vivado and the board):** synthesis, timing and the bitstream. Re-run
them for these sources and check that WNS >= 0. The fixes remove a multiplier from the
accelerator's S4 path, but the core's EX-stage path had only +0.4 ns of slack in v4.

## v6: any company, and a comparison of several companies

* `--company NAME` picks the company: apple, nvidia, google, microsoft, amazon, walmart, meta, tesla,
  or any Yahoo ticker. `--company all` (or a comma list, or `--days N`) runs every company and session
  through the board, one after another, and writes per-run logs and pictures, `summary.csv`, `summary.md`
  and `comparison.png` (strategy return vs buy-and-hold). See extras/README_REAL_DATA.md.
* `extras/market_feed.py` holds the data code for any ticker (`apple_feed.py` and
  `download_apple_data.py` remain as compatibility wrappers); `download_market_data.py --company all`
  saves one CSV per company.
* The run's `.cfg` now records the ticker, so `verify_run.py` re-downloads the right company for its
  market check. It also accepts several logs at once. Logs from v5 have no ticker and are AAPL.
* `tools/check_hft.py fromlog` turns any dashboard log into a tb_hft tick file, so a real-data run can be
  replayed in the RTL simulation.
* No RTL or firmware change: all eight companies fit the accelerator's number widths (prices in 32-bit
  cents, 32-bit volume sum, 64-bit cash).
* Tests: `python3 extras/tools/test_companies.py` (offline: a stand-in for Yahoo serves synthetic bars in
  yfinance's format, checks names, single runs, the 8-company batch with its summary and chart, and that
  verify_run uses the right ticker). Each company's session was also replayed through the RTL
  simulation of the whole SoC + firmware: 8 x 390 ticks, HW = SW = model on every tick.
  `run_hft_tests.sh` and `run_tests.py` unchanged and passing.

## v7: profiling the trading workload on the processor

`bash extras/tools/profile_trading.sh` builds the firmware for RV32IM and for RV32I (no multiply/divide
hardware; the compiler calls libgcc routines instead), runs both on soc_top in simulation (tb/tb_prof.v)
and prints where the cycles of one software trading decision go. Measured over 310 ticks:

| | RV32I | RV32IM | hardware accelerator |
|---|---|---|---|
| cycles per decision | 415.7 | 101.6 | 5 |
| instructions retired | 326.5 | 73.2 | - |
| taken-branch flush cycles | 87.2 | 16.2 | - |
| MUL/DIV stall cycles | 0 | 12.0 | - |
| load-use stall cycles | 3.9 | 2.2 | - |
| operands forwarded | 82.9 | 19.3 | - |

Timeline after the last byte of a tick arrives (RV32IM): hardware decision at 5 cycles, CPU sees the tick
at about 7, software decision done at about 123, first report byte at about 159. Receiving the 12-byte tick
over the UART takes 104,160 cycles (1.04 ms), so at 115200 baud the link, not the processor, dominates.

Also fixed in v7: the testbenches kept file names in a 1024-bit register (128 characters), so a
project folder with a long path (deep Windows/WSL folders) silently loaded no firmware and every
test timed out. They now take paths up to 1024 characters (checked from a 198-character path).


## v10 (multi-company)

* Firmware flag race: TICK_READY was cleared as soon as a tick was read and HW_DONE only after the hardware result. A packet arriving in between (only when the PC does not wait for the reports) lost its HW_DONE and every later report was shifted by one tick. The firmware now clears both flags in one write after reading the result. Found by stage 4 (flow control); see CHANGES_MULTI_COMPANY.md for the multi-company extension itself.
