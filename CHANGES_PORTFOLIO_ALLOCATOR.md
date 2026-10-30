> **v12 note:** parts of this file are superseded (shared-cash priority now serialises one engine per cycle, allocation latency, kill switch, STATUS bit 6, FRAME_ERR). See CHANGES_V12_BUGFIXES.md.

# Hardware portfolio allocator: rank + rotate + reweight (v11)

v10 traded several companies from one cash account, but every engine decided on its own: whichever
company's BUY arrived first took the cash. v11 adds **`hft_alloc.v`**, a hardware block that
decides for the **whole portfolio once per minute**:

| Step | What it does |
|---|---|
| 1 SELL | A company whose signal is SELL (volume > 0) sells its **whole** position |
| 2 RANK | The BUY candidates are served **strongest momentum first** (ties: lower company number) |
| 3 BUY | If the shared cash covers price x lots and the company stays under its cap |
| 4 ROTATE | At most once per minute: a BUY refused only for cash may sell the **weakest** holding (no BUY signal, held >= MIN_HOLD minutes, score more than MARGIN below the buyer) if that makes the BUY affordable |
| 5 HOLD | Every held position counts one more minute (saturates at 255) |
| 6 REWEIGHT | Every closed position moves the weights (sum always 2^15): a **win** takes w_j/2^k from every other company, a **loss** gives w_i/2^k away; nobody goes below FLOOR. Each company's cap = starting cash x weight / 2^CAPSHIFT |

- **Kill switch:** blocks every trade of that minute.
- **Codes reported per company:** 0 none, 1 BUY, 2 SELL, 3 ROT (sold to fund a stronger company).

**Momentum score.** Score = (4 x price - S) / S, where S is this price plus the 3 before it (the MA(4) sum the engine already has). It is computed in units of 2^-20, signed and truncated toward zero.
- **How:** a bit-serial divider, one quotient bit per cycle, about 55 cycles per company. It runs in the background after the engine has decided.
- **Effect on the signal:** none. The 5-cycle signal latency is unchanged.

**One rule, four places.** The Python model `PortfolioModel` (`extras/hft_model.py`) is the bit-exact specification. The RTL, the firmware's C copy (`port_allocate`) and the dashboard checks are all compared against it.

## How the board is used now

```
cd extras
python download_market_data.py --company apple,nvidia                  (once, needs internet)
python hft_dashboard.py --source csv --file AAPL_ticks.csv,NVDA_ticks.csv --company apple,nvidia --port COM6
python hft_dashboard.py --company apple,nvidia --together --port COM6   (downloads, latest common day)
python verify_run.py run_AAPL-NVDA_<day>_<time>.csv --offline
python tools/ablation.py --company apple,nvidia --file AAPL_ticks.csv,NVDA_ticks.csv
```
- **Default:** `--together` (and a CSV list) now runs the hybrid allocator.
- **Older strategy:** `--strategy independent` gives the v10 behaviour.
- **Switching parts off for comparison (ablation):** `--no-rank`, `--no-rotate`, `--no-reweight`.
- **Settings:** `--max-lots`, `--margin-pct` (0.1), `--min-hold` (5), `--weight-step` (k = 3), `--floor-pct` (half of an equal share), `--capshift` (14 = caps add up to 200 % of the cash).
- **Offline:** `--port none` runs the Python model instead of the board.
- **Engines in the bitstream:** the board image has 2 engines. For 3 or more companies, set `HFT_N_MAX` in `soc_top.v` and rebuild.
- **`--speed`:** in this mode it counts minutes per second.

**Per minute the PC sends every company's bar, then `ALLOCATE`.**
- **Tick report:** hardware vote, software vote, hardware score.
- **ALLOCATE report:** hardware codes, the firmware's codes, shared cash, and a state checksum (positions + weights).
- **Checks:** the dashboard checks every report against the model as it arrives. The firmware also compares every hardware register with its C copy, and LED2 lights on any difference.

### The window (one screen, any number of companies, no scrolling)

- **Overview (default):** every company's price over the **last 60 minutes**, with the hardware's BUY / SELL / ROT marks, position, weight, score and closed P&L. Next to them, over the same hour: portfolio return and cash, the weights, allocation latency (hardware vs RISC-V), a status box and the latest trades.
- **Click a company (or press 1-8):** that company's **whole day so far**:
  - price with every trade and the breakout levels;
  - momentum score coloured by signal;
  - position;
  - weight;
  - a box with trades, invested amount, value, open and closed P&L, and buy & hold.
- **Going back:** click again, or press Esc, to return to all companies.

## Registers added (0x3000_0000)

The register index widened to `addr[7:2]`. Everything from v10 is unchanged; the reset value of PORT_MODE is 0, which is the v10 behaviour.

| Offset | Name | Access |
|---|---|---|
| 0x24 STATUS | bit3 allocation done (write 1 to clear), bit4 allocator busy, bit5 every score computed | R/W1C |
| 0x64 | PORT_MODE: bit0 portfolio, bit1 rank, bit2 rotate, bit3 reweight (takes effect on CTRL clear); read: [3:0] written, [7:4] in force | RW |
| 0x68 | MAX_LOTS (0 = whole bar volume) | RW |
| 0x6C | MARGIN (score units, 2^-20) | RW |
| 0x70 | ALLOC_PARAM: [7:0] MIN_HOLD, [12:8] k, [20:16] CAPSHIFT (on clear) | RW |
| 0x74 | W_FLOOR [15:0] | RW |
| 0x78 | ALLOC_CODES [15:0] (2 bits per company), bit16 = kill switch was on | R |
| 0x7C | ALLOC_LAT (cycles from the ALLOCATE packet to done) | R |
| 0x80 | ALLOC_COUNT | R |
| 0x84 | SCORE (sel), signed | R |
| 0x88 | WEIGHT (sel): [15:0] weight, [23:16] minutes held | R |

**What changes in portfolio mode:**
- **HW_DECISION:** reads the vote.
- **HW_POSITION / INVESTED / HW_CASH:** come from the allocator.
- **ALLOCATE packet:** starts the hardware the cycle it is accepted.
- **Ticks during an allocation:** a tick that arrives while the allocator is busy is not traded and is counted in OVERRUN. This cannot happen with the PC's flow control.

## New commands

| Command | id | price field | vol field |
|---|---|---|---|
| ALLOCATE | 0x80000006 | minute number | - |
| CFG_MODE | 0x80000007 | mode bits (on the next RESET) | MAX_LOTS |
| CFG_ROT | 0x80000008 | MARGIN | MIN_HOLD |
| CFG_W | 0x80000009 | k \| CAPSHIFT << 8 (CAPSHIFT on RESET) | FLOOR |

**Feedback from the board:**
- **CFG_MODE report:** the position field echoes the mode, read as active << 4 | written value.
- **Old board image:** a board without the allocator answers 0, and the dashboard stops with a clear message.

## Files

| File | Change |
|---|---|
| `src/rtl/hft_alloc.v` (new) | The allocator: score divider, FSM, 32x32 and 64x16 multipliers (pipelined), weights, holding times |
| `src/rtl/hft_accelerator.v` | Exports the vote and the MA inputs (`vote_out`, `ma_sum_out`, `ma_ok_out`, `tick_price_out`, `tick_vol_out`); behaviour unchanged |
| `src/rtl/hft_multi.v` | Instantiates `hft_alloc`; in portfolio mode the engines do not trade and positions / cash come from the allocator; ticks of a company >= NUM_SYMBOLS are ignored |
| `src/rtl/hft_mmio.v` | Registers above, ALLOCATE trigger, vote in HW_DECISION |
| `src/rtl/soc_top.v` | `IMEM_WORDS` 1024 -> 2048 (the firmware is 1,739 words) |
| `extras/hft_firmware.c` | Signal / score / C copy of the allocator, CFG_MODE / ROT / W, ALLOCATE report, 64-bit division and shifts without libgcc |
| `extras/hft_model.py` | `PortfolioModel` (the specification), command constants |
| `extras/hft_hybrid.py` (new) | Dashboard mode: protocol, live checks, log, one-screen window with click-to-expand |
| `extras/hft_dashboard.py` | `--strategy` and the allocator options; `--save-png-focus` |
| `extras/verify_run.py` | Replays hybrid logs through `PortfolioModel` (signals, scores, codes, cash, checksum, returns, market check) |
| `extras/tb/tb_hft_port.v`, `extras/tools/check_port.py`, `extras/tools/mutate_port.py` (new) | Allocator unit test, boundary stimulus, mutation test |
| `extras/tools/check_hft.py` | `genport` / `checkport` (whole system in portfolio mode); `fromlog` takes hybrid logs |
| `extras/tools/ablation.py` (new) | Independent vs rank vs rank+rotate vs rank+reweight vs hybrid on the same sessions |
| `extras/tools/run_hft_tests.sh` | Stages 8 (allocator, N = 2 and 4) and 9 (portfolio system test); stage 5 also replays it with the shipped image |
| `extras/tools/test_companies.py` | Hybrid runs with 2 and 4 companies, ablation run, v10-board refusal |
| `create_project.tcl`, `rv32im.xpr`, `run_tests.py`, `profile_trading.sh` | `hft_alloc.v` added |
| `src/mem/imem.mem` | Rebuilt (1,739 words of 2,048) |

## Design decisions found while building (and why)

- **The cap formula.** It is `(start x weight) >> CAPSHIFT`, not `(start >> CAPSHIFT) x weight`. The second form rounds the cap down to 0 when the starting cash is below 2^14 units, and the boundary test exposed this. The multiplier is 64x16 in both forms, so the exact version costs only an 80-bit shift.
- **CAPSHIFT default 14 (caps add up to 200 %).** With 15 (100 %), each company can never use more than its share, so cash is never the binding limit and rotation never fires. 200 % keeps the companies competing for the cash.
- **A tick during a division.** If the same company ticks again while its score is being divided, the old result is dropped and the new tick is divided. This is the `d_stale` flag, and a mutation test proves the check catches its removal.
- **Default FLOOR is half of an equal share.** With 8 companies, a fixed 12.5 % floor equals the equal share, and the weights could never move.
- **Timing.** The 32x32 product is pipelined twice. A sum that feeds a compare is registered one state before the compare, so no cycle has two long carry chains. This costs 2 cycles per BUY and per rotation.

## Verification (all run in this version)

| Test | Result |
|---|---|
| Stage 8: `hft_alloc` vs `PortfolioModel` | N = 2 and N = 4, about 3,080 minutes each. Every minute compares codes, cash, and every company's position, invested amount, weight, hold and score. Every tick compares signal and latency 5. Stimulus: 10 directed cases, model-guided boundary runs (MARGIN, MIN_HOLD and FLOOR set to the exact flip value, equal scores, BUY cost = cap), random runs with every setting varied, duplicate ticks during a division, kill minutes. 0 mismatches |
| Mutation test (`mutate_port.py`) | 13 single bugs (tie order, off-by-one MIN_HOLD / MARGIN / cap, cap shift, victim choice, two rotations, divider guard, floor, loss split, MAX_LOTS, hold saturation, score sign): **all 13 caught with N = 4**. With N = 2, 11 caught; the other 2 cannot occur with two companies (two rotations need 4 companies; the loss split shift is 0) |
| Stage 9: whole system in portfolio mode | CPU + firmware + UART + RTL, 431 packets: 130 allocations (BUY, SELL, ROT, wins and losses reweighted, refusals for cash and cap, kill minutes, an untraded company, cash above 2^32, a mode change back to independent). HW = firmware C copy = model on every report |
| Fault injection, system level | MAX_LOTS bug put into the RTL: the firmware flags 36 allocations (bit 31), the checker fails |
| Dashboard run replayed in RTL | A 300-tick AAPL + NVDA hybrid log (`fromlog`) through the full system with the shipped image: 461/461 reports PASS |
| Stages 0-7 and 5 (v10 and earlier) | Unchanged, PASS (`ALL HFT TESTS PASS`) |
| `test_companies.py` | PASS: hybrid with 2 and 4 companies, `--no-rotate`, `verify_run` (model + market), every picture drawn, v10 board refused |
| Click / Esc / number keys | Tested headless: overview -> company 2 -> overview -> company 3 -> overview |

## Measured latency

| | Hardware | RISC-V software (same algorithm, in the firmware) |
|---|---|---|
| Signal per tick | 5 cycles (unchanged) | 117 - 1,723 cycles (signal + 64-bit score division) |
| Allocation per minute (2 companies) | 7 - 31 cycles | 326 - 1,284 cycles |

**About these numbers:**
- **Hardware allocation:** counted from the ALLOCATE packet to done. Typically 10-40 x faster than the software.
- **Score timing:** the score finishes within about 55 cycles per company after the tick, long before the ALLOCATE packet arrives over the UART.
- **Independent mode got slower in software:** the RISC-V decision now takes 122-181 cycles (v10: 88-149) in the system test. The firmware's main loop checks the mode and calls the shared signal function. The hardware is unchanged at 5 cycles.

## Resources (yosys `synth_xilinx`; Vivado numbers will differ)

| Block | LUTs | FF | DSP |
|---|---|---|---|
| `hft_alloc`, N = 2 | 3,148 | 1,432 | 8 |
| `hft_alloc`, N = 4 | 3,842 | 2,031 | 8 |
| whole `soc_top`, 2 engines, v10 | 4,703 (7.4 %) | 3,381 (2.7 %) | 20 (8.3 %) |
| whole `soc_top`, 2 engines + allocator, v11 | 8,214 (13.0 %) | 4,924 (3.9 %) | 28 (11.7 %) |

On the XC7A100T (63,400 LUTs, 240 DSP), the allocator with 2 companies is about **5 % of the LUTs and 3 % of the DSPs**. Most of it is the 64-bit arithmetic and the per-company multiplexers. The v11 whole-SoC figure also includes the larger instruction memory (2,048 words).

**Timing:** not run here (no Vivado). After implementation, check WNS >= 0 at 100 MHz. These are the paths to look at first:
- the 80-bit cap compare in `S_BUY_U`;
- the score-difference compare in `S_VSCAN`.

## Honest limits

- **Synthetic data shows no edge.** On synthetic random-walk data (`tools/ablation.py`), no variant makes money, and none can, because a random walk has nothing to predict. Run `ablation.py` on real CSVs to see whether rank / rotate / reweight help on real sessions.
- **No costs in the returns:** they ignore fees and slippage.
- **Whole positions.** Portfolio mode SELLs the whole position (v10 sold the bar volume). Trade counts are therefore not directly comparable with v10.
