# v12: bug review and fixes

Everything below was found in a full review of the v11 upload (RTL, firmware, linker script, Python
model, PC tools, testbenches and the abstract), fixed, and re-verified in simulation.
**Nothing has been run in Vivado or on the board.** Timing numbers are Yosys logic-depth estimates;
run implementation and check WNS >= 0 before relying on them (see "Still to do").

## How to check

```
bash extras/tools/run_hft_tests.sh              # all trading stages (0, 0b, 1-9, 3b, 5); ~20 min
MUTATION=1 bash extras/tools/run_hft_tests.sh   # + stage 10: 17 allocator bugs planted, all must be caught
python3 extras/tools/run_tests.py               # RV32IM core regression
```

Both scripts now also fail if any simulation prints an RTL self-check line (`ERROR <module>: ...`).

## Summary

| # | Severity | Where | Problem | Fix |
|---|---|---|---|---|
| 1 | Critical | `hft_multi.v` | Shared-cash fixed-priority chain: N cascaded 64-bit compare + add/subtract stages in one cycle. Logic depth 23 / 41 / 69 / 131 levels for N = 1 / 2 / 4 / 8: cannot meet 100 MHz with 4 or 8 engines (the stretch goal) | Cash unit serves **one** request per cycle (lowest index first); other engines wait in S4. Depth now 24-29 levels for any N |
| 2 | Major | `hft_alloc.v` | Allocation latency claim "at most 128 cycles for 8 companies" was false: 136 cycles measured for 8 buys or 8 sells; loops always ran over all N slots (the 2-company example took 31 cycles on a 2-engine build, 67 on an 8-engine build) | Loops end at NUM_SYMBOLS; buyer and rotation victim chosen in **one** cycle; win/loss reweight in parallel. Proven bound 8 + 12n (104 for n = 8); measured 24 / 64 / 64 |
| 3 | Major | `hft_mmio.v`, firmware | Kill switch SW0 went into N + 2 separate synchronisers and the firmware read it again ~20 cycles later: flipping SW0 while a tick was in flight made hardware and software disagree (new test: **47 of 310 ticks** wrong in v11) | One synchroniser; the kill state is latched with each packet and used by the engines **and** read by the firmware (STATUS bit 6) |
| 4 | Major | `hft_dashboard.py` (shared by hybrid / portfolio modes) | A report that arrived late was taken as the answer to the next tick: every later tick stayed shifted by one; the hybrid mode also stepped the model for a tick the board may not have processed | A report is accepted only if its id matches the packet just sent; stale reports are dropped; a missing report stops the run with a clear message. Linux: FTDI latency timer lowered to 2 ms |
| 5 | Major | `extras/sw/link.ld` | IMEM declared 16 KB, hardware has 8 KB (2048 words): an oversized program linked without error and wrapped around in IMEM. No stack check | IMEM 8K; `ASSERT`s for IMEM size and >= 512 bytes of stack |
| 6 | Major | firmware | Initialised globals (`p_margin = 1049`, ...) are loaded only by the bitstream: after the CPU RESET button they kept the PC's last values while the hardware was back at its defaults | No initialised `.data` any more (dmem image is empty); `main()` sets the defaults |
| 7 | Major | firmware | Busy-waits on HW_DONE / SCORES_RDY had no timeout: a lost hardware result hung the board | `wait_status()` with a limit; on timeout the report carries hw decision 0xFFFFFFFF and LED2 lights |
| 8 | Major | `rv32im_core.v` | v4 Vivado report: worst path EX/MEM rd -> forwarding compare -> branch -> ID/EX flush, only +0.40 ns slack | Forwarding selects computed one cycle early (registered when the instruction enters ID/EX). Simulation keeps the old unit as a reference and prints `ERROR rv32im_core` on any difference (shown to catch a planted bug) |
| 9 | Major (test bug) | `tools/check_port.py` | Generator wrote MARGIN = -1: hardware sees 0xFFFFFFFF, the model -1. Every seed except the one in the script (3) failed, on v11 too | Generator never produces it; checker masks PARAM values to the register widths. Regression now runs 2 seeds; extra sweep passed seeds 1-10 for N = 2 and 4, seeds 1, 2, 3, 7 for N = 8 |
| 10 | Minor | `uart.v` | No stop-bit check (a corrupted byte was delivered), single-sample input, case statements without `default` | 3-sample majority filter, stop bit checked (bad byte dropped, `frame_err`), wait for idle line after an error, `default` branches; new FRAME_ERR counter (0x3000_008C) |
| 11 | Minor | `soc_top.v` | Reset synchroniser without `ASYNC_REG` | Added |
| 12 | Minor | `hft_model.py` | `PortfolioModel` allocated on an ALLOCATE id with company bits; hardware and firmware ignore it | Only the exact id 0x80000006 allocates |
| 13 | Minor | `market_feed.py` | `max(1, round(volume / 1000))`: a bar with no volume was sent as 1 lot (1000 traded shares), defeating "zero volume never trades" and skewing VWAP | Rounded to the nearest lot, 0 allowed |
| 14 | Docs | abstract, README_REAL_DATA | Throughput stated as 1.04 ms per tick (packet only); same-bar fill, 100 % participation, synthetic-data profitability and Yahoo 1-minute limits not stated; "every tick exactly 5"; GitHub link placeholder | Corrected (see below) |

## New: arithmetic example programs
`make add`, `make sub`, `make xor`, `make mul`, `make div` (and `sort`, `fib`, ...), from the project
folder or `extras/`. Aliases: `addition`, `subtract`, `multiply`, `divide`, `sorting`, `fibonacci`;
`make list` shows them; any `extras/sw/examples/<name>.c` runs with `make <name>`. The new programs
use volatile inputs (so the core really executes ADD/SUB/XOR/XORI/MUL/MULH/MULHU/MULHSU/DIV/DIVU/REM/REMU),
cover overflow, divide by zero and INT_MIN / -1, and count wrong results in `errors` (FAIL if not 0).

## Second review: the 13 points from another AI review (ChatGPT), checked one by one

| # | Point | Verdict | What was done |
|---|---|---|---|
| 1 | Engine's 1-entry tick buffer can be overwritten | **Real bug** (unreachable on the board, but silent) | A tick that finds the buffer full is now dropped instead of overwriting the waiting one (order kept, same policy as the UART OVERRUN) and counted: ENG_DROP 0x3000_0090. New test `tb_hft_drop.v` (stage 1b); v11 overwrote tick 101 with 102 and counted nothing |
| 2 | 32-bit cumulative volume overflow | **Real bug** (needs 4.29e9 lots; reachable with raw-share data or test data) | Hardware, firmware and Python model all detect an overflow of the volume sum or the 64-bit price*volume sum; the VWAP rule then stops voting until RESET (VWAP_OFF 0x3000_0094). Widening to 64 bits would need 96-bit products and more DSPs. Unit test (stage 1) and system test (stage 3) now overflow it; v11 hardware: 120 wrong decisions on the new unit stimulus |
| 3 | Accumulator overflow in general | Audited every width; **one more real case fixed** | Exact by construction: price*vol, price*volume-sum (64), MA sum (34), score (< 2^22), positions (checked against the limit first), allocator invested (< 2^64), cap compares (65/80 bit). Fixed: a SELL credit could wrap the 64-bit cash to a small number; it now saturates at 2^64-1 in the engine, the shared cash unit, the allocator (sell and rotation), the firmware and the models. Tests hit it in stages 2, 6 and 8 (v11 engine: 2,007 mismatches on the new stage-2 stimulus) |
| 4 | Variable allocation latency | Already fixed in v12 | Proven bound 8 + 12n, checked on every allocation in stage 9 |
| 5 | Sequential score divider | Not a bug | ~55 cycles per company in the background; on the board one company ticks per packet and the next packet is >= 4.5 ms later, so a division never waits for another. Parallel dividers would add ~1,000 LUTs for no measurable gain |
| 6 | Score divider needs more tests | **Tests added** | Directed case J in check_port: MA sum 0 (score 0), largest positive score (+3145727), most negative (-1048575), a second tick during a running division. Plus thousands of random scores compared every tick |
| 7 | Multicycle (MUL/DIV) hazards | Already tested; **gaps closed** | gen_directed.py section F: branch on a DIV result (taken and not taken), store data from DIV, load-use into branch and JALR, JALR to a MUL result, wrong-path DIV behind a stalled MUL, DIV as jump target, chained MUL->DIV->MUL. Passes; a wrong expectation is caught (checked) |
| 8 | Branch / multicycle interaction | Same as 7 | Same as 7, plus 200 random programs against the ISA simulator |
| 9 | Incomplete packets | Already handled | tick_parser drops a partial packet after 5 ms of silence (stage 1 tests it); bad stop bits are now dropped too (v12 UART); the PC stops on a missing report |
| 10 | No backpressure | Already handled + counters | Stop-and-wait flow control; OVERRUN (dropped packets), FRAME_ERR, ENG_DROP |
| 11 | 100 MHz not verified | Still open (needs Vivado) | Timing paths shortened in v12; run implementation |
| 12 | HFT_N_MAX = 2 by default | Design choice | 16 is impossible (company id is 3 bits: max 8). 2, 4, 8 are tested in simulation; set HFT_N_MAX and check timing |
| 13 | Combinational memories | Not a bug | Correct as built; a block-RAM version needs fetch changes (only if Vivado needs it) |

New registers: 0x3000_0090 ENG_DROP, 0x3000_0094 VWAP_OFF (bit per company). New ports:
`hft_accelerator.tick_dropped`, `.vwap_sat`; `hft_multi.tick_dropped`, `.vwap_sat`.

## Details

### 1. Shared cash unit (`hft_multi.v`, `hft_accelerator.v`)
* `req = (buy_req | sell) & ~port_mode`, `win = req & -req` (lowest index), `hold_req = req & ~win`.
  One N:1 mux of the cost, one 64-bit compare with the cash, one 64-bit add/subtract.
* New engine input `ext_hold` (only with EXT_CASH = 1): the engine stays in S4 and commits in the first
  cycle it is not held. `latency_cycles` then reads 5 + cycles held.
* `invested + cost` for the cap check is registered every cycle (`inv_after_r`): in an engine's S4
  cycle its cost (set in S1) and its invested amount (changed only by its own commit, >= 5 cycles
  earlier) were already stable one cycle before.
* Results are identical to processing the ticks one at a time in index order (what the model does).
  On the board one packet carries one tick, so no engine ever waits and the latency is always 5.
* Simulation check: `ERROR hft_multi` if more than one engine is served in a cycle.
* Test (stage 6): N = 2, 4 **and 8** (8 was never tested before), 3 seeds; the checker now requires
  latency == 5 + cycles held for every decision and at most one cash change per cycle.

### 2. Allocator (`hft_alloc.v`)
* `ns_eff = min(NUM_SYMBOLS, N)` ends the SELL and reweight loops.
* `beat_r` / `lbeat_r`: registered pairwise score comparisons (ties to the lower index); the next
  buyer / the rotation victim is a one-hot AND over that matrix. `elig_r` (victim eligibility) is
  registered in S_BUY_U, when cur / cand / pos / hold are final.
* Win: S_WIN computes every company's `take()` into `t_r`, S_WIN2 applies them and credits the sum.
  Loss: every other company gets `share`, the loser pays `share * (n - 1)`. Identical to the serial
  loop (each weight is touched once, sums are mod 2^16).
* `cycles = 8 + 2n + 3s + 5b + 2c + 5v + f` (header of hft_alloc.v), `<= 8 + 12n`.

| 8 companies | v11 | v12 |
|---|---|---|
| minute without trades | 32 | 24 |
| eight BUYs | 136 | 64 |
| eight losing SELLs | 136 | 64 |
| abstract example (2 companies, cash 1,500), 2-engine build | 31 | 23 |
| same example, 8-engine build | 67 | 23 |

* Tests: stage 8 with N = 2, 4, 8 and seeds 3 and 7; the system test (stage 9) now also fails if an
  allocation exceeds 8 + 12n cycles; mutation test (stage 10) updated to the new code plus four new
  mutants: **17 of 17 caught** (N = 4).

### 3. Kill switch (`hft_mmio.v`, `hft_multi.v`, firmware)
* `kill_q1/kill_q2` (ASYNC_REG) is the only synchroniser; `kill_tick` is latched on every accepted
  packet and drives the engines. STATUS bit 6 = `kill_tick`; the firmware uses it instead of reading
  SW0 itself. The allocator gets the synchronised switch on its own port (`alloc_kill_sw`) and, as
  before, reports the value it used (ALLOC_CODES bit 16).
* New stage 3b: the system test with SW0 flipped 2-60 cycles after every packet (`+KILLFLIP`).
  v11: 47 of 310 ticks with HW != SW. v12: all agree.
* Debouncing is not needed for correctness: whatever SW0 does, a tick uses one latched value everywhere.

### 8. Core forwarding (`rv32im_core.v`)
`id_ex_fwd_a/b` are computed in ID from `id_ex_rd` (next cycle in EX/MEM) and `ex_mem_rd` (next cycle
in MEM/WB). ID/EX only advances when the M unit is idle, so EX/MEM gets no bubble in that cycle, which
makes the registered select equal to the old combinational one in the instruction's first EX cycle
(the only cycle its operands are used). Cycle counts of every core test are unchanged.

### Register map additions
| Address | Register | |
|---|---|---|
| 0x3000_0024 STATUS bit 6 | kill switch as latched with the current packet | R |
| 0x3000_008C | FRAME_ERR: UART bytes dropped for a bad stop bit (cleared by a CTRL clear) | R |

Port changes: `hft_accelerator.ext_hold` (input), `hft_multi.alloc_kill_sw` (input), `uart_rx.frame_err` (output).

## Deliberately not changed (and why)
* **Block-RAM instruction memory, registered MMIO read data, extra multiplier pipeline stage.** Not on
  the worst path of the last Vivado report; each changes fetch or load timing (and the measured
  software cycle counts). Do them only if the new Vivado timing report shows those paths failing.
* **Sync word + CRC in the packets, windowed flow control.** A protocol change across hardware,
  firmware and three PC tools. In stop-and-wait, the id echo, header/footer, the new stop-bit check
  and the parser's idle-gap resync already detect every lost or corrupted packet, and the PC now stops
  instead of drifting.
* **Next-bar fills / participation limit in the strategy.** That changes the strategy in Verilog, C and
  Python. It is documented as a limitation instead; portfolio mode already has MAX_LOTS.
* **32-bit VWAP volume sum.** With 1000-share lots it wraps after 4.3e12 shares; changing it would
  only break bit-exactness of the three implementations.

## Still to do (needs Vivado / the board)
1. Build with `HFT_N_MAX` = 2, 4 and 8, run implementation, and record WNS and utilisation for each.
   Yosys (synth_xilinx) estimate for the v12 8-engine SoC: about 21,450 LUTs, 13,400 flip-flops,
   77 DSP48E1, no latches, close to the abstract's 20,600 / 12,600 / 76. Replace them with the Vivado numbers.
2. The software allocation figure for 8 companies in the abstract (830-4,190 cycles) was not re-measured
   here (v12 only measured the 2-company system test).
3. Replace the GitHub link placeholder in the abstract (highlighted).
4. On the board: run a session with SW0 toggled during the run and check LED2 stays off.
