> **v12 note:** parts of this file are superseded (shared-cash priority now serialises one engine per cycle, allocation latency, kill switch, STATUS bit 6, FRAME_ERR). See CHANGES_V12_BUGFIXES.md.

# Several companies at once, one shared cash account (v10)

Each company runs its own, fully independent strategy on its own FPGA engine (price history,
MA warm-up, VWAP sums, breakout levels, position limit, position, decision). The only shared
state is the 64-bit cash account (and the kill switch). With one company the design behaves
exactly as before.

**Design choice: one engine per company (`hft_accelerator` instantiated N_MAX times).**
- **Latency:** every company keeps a fixed 5-cycle latency, even when ticks for several companies arrive in the same cycle.
- **Reuse:** the verified engine is reused. Its only change is an external-cash mode, selected by a parameter.
- **Cost:** roughly 8 DSP blocks and about 1,300 LUTs per extra company (yosys estimate below).

## Run a 2-company demo

```
cd extras
python download_market_data.py --company apple,nvidia             (once, needs internet)
python hft_dashboard.py --source csv --file AAPL_ticks.csv,NVDA_ticks.csv --company apple,nvidia --port COM6
python hft_dashboard.py --company apple,nvidia --together --port COM6            (downloads, latest common day)
python hft_dashboard.py --company apple,nvidia --together --cap-pct 50 --port COM6   (each company <= 50 % of cash)
python verify_run.py run_AAPL-NVDA_<day>_<time>.csv --offline
```
- **Offline:** `--port none` uses the Python model instead of the board.
- **Batch mode is unchanged:** without `--together`, a comma list with `--source replay` still runs each company separately, as before.
- **More companies than engines:** the board image is built with **2 engines** (`HFT_N_MAX = 2` in `soc_top.v`). Asking for more companies than the bitstream has engines stops with a clear message.

**The window shows:**
- one price panel per company, with the hardware's BUY/SELL marks;
- shared cash and total equity (cash + every holding at its last close);
- portfolio return;
- latency.

Every report is checked live: echo, HW == SW, and HW == model.

## What changed, file by file

| File | Change |
|---|---|
| `src/rtl/hft_multi.v` (new) | N_MAX `hft_accelerator` engines + the shared cash unit (same-cycle fixed priority, per-company cap, invested amounts) |
| `src/rtl/hft_accelerator.v` | Parameter `EXT_CASH` (default 0 = original engine). With 1: S4 raises `s4_buy_req` / `s4_sell` with `s4_cost` and takes `ext_buy_grant` instead of its own cash check |
| `src/rtl/hft_mmio.v` | Routes a tick to engine `tick_id[30:28]`; per-company config selected by `SYMBOL_SEL`; `NUM_SYMBOLS`, caps, `BAD_SYMBOL` counter; register index widened to `addr[6:2]` |
| `src/rtl/soc_top.v` | Parameter `HFT_N_MAX` (default 2) |
| `extras/hft_firmware.c` | Strategy state as arrays per company, shared cash, caps, `CMD_CFG_NSYM` / `CMD_CFG_CAP`, per-company config commands; flag fix (below) |
| `extras/hft_model.py` | `MultiModel` (bit-exact with the RTL, incl. the same-cycle rule and caps); `HFTModel` unchanged |
| `extras/hft_portfolio.py` (new) | Together mode of the dashboard: feed merge, configuration, live checks, log, window, summary |
| `extras/hft_dashboard.py` | `--together`, `--cap-pct`; CSV with several companies goes to together mode |
| `extras/verify_run.py` | Together logs: per-company replay, shared cash == model on every tick and never negative, portfolio returns, market check per company |
| `extras/tb/tb_hft_multi.v` (new), `extras/tools/check_multi.py` (new) | Random + directed test of `hft_multi.v` |
| `extras/tools/check_hft.py` | Uses `MultiModel`; `genmulti` (2-company system stream); `fromlog` also takes together logs |
| `extras/tools/run_hft_tests.sh`, `run_tests.py`, `profile_trading.sh`, `create_project.tcl`, `rv32im.xpr` | Add `hft_multi.v`; stages 6 and 7 added |
| `src/mem/imem.mem` | Rebuilt from the new firmware (628 words of 1,024) |

## Packet and command format (12-byte packets unchanged)

`tick_id[31]` = command, `tick_id[30:28]` = company (0..7), `tick_id[27:0]` = tick number.

| Command | id (company in bits 30:28) | price field | vol field | Scope |
|---|---|---|---|---|
| RESET | 0x80000000 | - | - | all companies; cash = starting cash |
| CFG_BRK | 0x80000001 | BRK_HIGH | BRK_LOW | that company |
| CFG_LIMIT | 0x80000002 | POS_LIMIT | - | that company |
| CFG_CASH | 0x80000003 | starting cash low | high | shared |
| CFG_NSYM (new) | 0x80000004 | companies traded | - | global; the report's position field = companies actually enabled |
| CFG_CAP (new) | 0x80000005 | cap low | cap high (0 = no cap) | that company |

- **Untraded company:** a tick for a company >= NUM_SYMBOLS is not traded. The firmware answers it with a zero report, and the hardware counts it in `BAD_SYMBOL`.
- **Configuring a missing engine:** a configuration command for a company the bitstream does not have is ignored.

## New register map (0x3000_0000; "sel" = the company chosen by SYMBOL_SEL)

The original offsets are unchanged. With `SYMBOL_SEL = 0` they behave exactly as before.

| Offset | Name | Access |
|---|---|---|
| 0x00 / 0x04 / 0x08 | POS_LIMIT / BRK_HIGH / BRK_LOW | RW (sel) |
| 0x18 / 0x1C / 0x20 | HW_DECISION / HW_LATENCY / HW_POSITION | R (sel) |
| 0x34 / 0x38 | starting cash low / high | RW (shared, loaded on CTRL clear) |
| 0x3C | shared cash low | R |
| 0x40 | SYMBOL_SEL | RW |
| 0x44 | NUM_SYMBOLS (0 -> 1, > N_MAX -> N_MAX) | RW |
| 0x48 / 0x4C | CASH_CAP low / high (0 = no cap) | RW (sel) |
| 0x50 | shared cash high | R |
| 0x54 | BAD_SYMBOL (ticks for a company >= NUM_SYMBOLS) | R, cleared by CTRL |
| 0x58 | N_MAX (engines in this bitstream) | R |
| 0x5C / 0x60 | INVESTED low / high (BUY cost - SELL proceeds, signed) | R (sel) |

## Shared-cash rule

- **Each engine's BUY condition:** shared cash >= price x volume **and** (cap = 0 **or** invested + price x volume <= cap).
- **Engines finishing in the same cycle** are served in fixed order, lower company first. Each sees the balance left by the ones before it, so a SELL of company 0 can fund a BUY of company 1 in the same cycle.
- **Same order everywhere:** the dashboard sends the companies of one minute in the order given on the command line. The model, the firmware and the hardware apply them in that order.

## Bug fixed on the way (also present in v9)

- **Old behaviour:** the firmware cleared TICK_READY as soon as it read a tick, and HW_DONE only after reading the hardware result.
- **The problem:** a packet arriving between the two clears (only possible when the PC does not wait for the reports) had its HW_DONE wiped. Every later report was then shifted by one tick.
- **The fix:** the firmware now clears both flags in one write after the result is read.
- **How it was found:** stage 4 (flow control) caught it once the firmware became slightly slower.

## Test results (all from runs in this version)

| Test | Result |
|---|---|
| `extras/tools/run_hft_tests.sh` | ALL HFT TESTS PASS: the original stages 0-5 unchanged (single company), plus stage 6 (`hft_multi.v`, 2 and 4 engines, 3 seeds each: about 2,400 / 4,500 decisions per run, about 950 / 1,240 cycles with several engines deciding together, 0 mismatches, latency 5 on every tick, plus two directed priority cases) and stage 7 (2 companies through CPU, firmware and UART: 165 reports, all match) |
| Deliberate bug check | With the priority chain broken (engines see the cycle-start cash), stage 6 FAILS |
| Real-data style run | A 780-tick AAPL + NVDA dashboard log replayed through the full RTL system with the shipped image: 790/790 reports match, 39 BUYs refused for shared cash |
| `extras/tools/test_companies.py` | PASS, incl. `--together` with and without `--cap-pct` and the market re-download of each company |
| `make test` / `make muldiv` | ALL PASS / 25,152 checks, 0 errors |

**Software decision, re-measured (`profile_trading.sh`, 310 ticks):** the array indexing for several companies adds about 11-14 cycles in software.

| Firmware | Before (v9) | Now |
|---|---|---|
| RV32I | 415.7 cycles | 426.8 cycles |
| RV32IM | 101.6 cycles | 115.4 cycles |
| Hardware | 5 cycles | 5 cycles |

## Resource estimate (yosys synth_xilinx, whole soc_top; Vivado numbers will differ)

| Engines (HFT_N_MAX) | LUTs | FF | DSP |
|---|---|---|---|
| 1 | 3,371 (5.3 %) | 2,399 (1.9 %) | 12 (5.0 %) |
| 2 (board image) | 4,703 (7.4 %) | 3,381 (2.7 %) | 20 (8.3 %) |
| 4 | 7,593 (12.0 %) | 5,345 (4.2 %) | 36 (15.0 %) |

**Timing:** not run here (no Vivado).
- **2 engines:** the shared-cash priority chain is one 64-bit compare plus one add/subtract per engine in the S4 cycle. Re-run implementation and check WNS >= 0.
- **4 engines:** the chain is twice as long and may not meet 100 MHz. If it does not, keep `HFT_N_MAX = 2`.
