# Dashboard V2.0 Hardware Interface Specification

This document details the hardware telemetry interfaces, MMIO register memory map, UART packet framing, and physical translation rules connecting the **RV32IM SoC & FPGA Trading Accelerator** to the **Professional Trading Dashboard V2.0**.

---

## 1. System Memory Architecture

The SoC (`src/rtl/soc_top.v`) defines four primary memory address spaces:

| Address Range | Memory / Peripheral | Bus Interface | Description |
|---|---|---|---|
| `0x0000_0000 – 0x0000_FFFF` | Instruction Memory (IMEM) | Fetch Bus | Harvard architecture instruction cache/ROM |
| `0x1000_0000 – 0x1000_FFFF` | Data Memory (DMEM) | Load/Store Bus | Primary scratchpad & execution stack |
| `0x2000_0000 – 0x2000_0010` | Board Peripherals | MMIO | Digilent Nexys A7 LEDs, 7-Segment, Switches, Cycle Counter |
| `0x3000_0000 – 0x3000_00AC` | HFT Accelerator & UART | MMIO | Hardware trading accelerator, portfolio allocator & UART |

---

## 2. Full 44-Register MMIO Map (`0x3000_0000` Base)

Registers are word-addressed (`addr[7:2]`), accessible by the RV32IM CPU via standard load (`lw`) and store (`sw`) instructions. Reads have no destructive side effects.

| Offset | Index | Name | Access | Reset Value | Physical Unit / Description |
|---|---|---|---|---|---|
| `0x00` | 0 | `POS_LIMIT` | RW(sel) | `1,000` | Position limit per company (lots) |
| `0x04` | 1 | `BRK_HIGH` | RW(sel) | `15,000` | Breakout high threshold in cents ($150.00) |
| `0x08` | 2 | `BRK_LOW` | RW(sel) | `5,000` | Breakout low threshold in cents ($50.00) |
| `0x0C` | 3 | `TICK_ID` | R | `0` | Bit [31]: Cmd flag, [30:28]: Symbol ID, [27:0]: Sequence ID |
| `0x10` | 4 | `TICK_PRICE` | R | `0` | Ingress price in cents (1 cent = $0.01) |
| `0x14` | 5 | `TICK_VOL` | R | `0` | Ingress volume in lots (1 lot = 1,000 shares) |
| `0x18` | 6 | `HW_DECISION` | R(sel) | `0` | Accelerator decision: `0: NONE`, `1: BUY`, `2: SELL` |
| `0x1C` | 7 | `HW_LATENCY` | R(sel) | `5` | Core decision latency in clock cycles (5 cycles = 50 ns) |
| `0x20` | 8 | `HW_POSITION` | R(sel) | `0` | Cumulative company inventory in lots |
| `0x24` | 9 | `STATUS` | Mixed | `0` | Bit 0: tick_rdy, Bit 1: hw_done, Bit 2: tx_rdy, Bit 3: alloc_done, Bit 4: alloc_busy, Bit 5: scores_rdy, Bit 6: kill_tick, Bit 7: active_strategy |
| `0x28` | 10 | `UART_TX` | W | `0` | Transmit byte to UART transmitter FIFO |
| `0x2C` | 11 | `OVERRUN` | R | `0` | Ingress tick FIFO overflow drop counter |
| `0x30` | 12 | `CTRL` | W | `0` | Control: Write bit 0 to clear engines and diagnostic counters |
| `0x34` | 13 | `CASH_LO` | RW | `100,000,000` | Shared portfolio cash balance [31:0] (cents) |
| `0x38` | 14 | `CASH_HI` | RW | `0` | Shared portfolio cash balance [63:32] |
| `0x3C` | 15 | `HW_CASH_LO` | R | `100,000,000` | Live committed shared cash balance [31:0] |
| `0x40` | 16 | `SYMBOL_SEL` | RW | `0` | Selected company index [2:0] (0 to 7) |
| `0x44` | 17 | `NUM_SYMBOLS` | RW | `8` | Number of active traded companies $N$ (1 to 8) |
| `0x48` | 18 | `CASH_CAP_LO` | RW(sel) | `0` | Per-company allocated cash ceiling [31:0] (0 = uncapped) |
| `0x4C` | 19 | `CASH_CAP_HI` | RW(sel) | `0` | Per-company allocated cash ceiling [63:32] |
| `0x50` | 20 | `HW_CASH_HI` | R | `0` | Live committed shared cash balance [63:32] |
| `0x54` | 21 | `BAD_SYMBOL` | R | `0` | Count of rejected packets with symbol $\ge N$ |
| `0x58` | 22 | `N_MAX` | R | `8` | Hardware synthesis maximum engine count parameter |
| `0x5C` | 23 | `INVESTED_LO` | R(sel) | `0` | Capital invested in selected company [31:0] (cents) |
| `0x60` | 24 | `INVESTED_HI` | R(sel) | `0` | Capital invested in selected company [63:32] |
| `0x64` | 25 | `PORT_MODE` | RW | `0x0F` | Mode flags: [0]=port, [1]=rank, [2]=rotate, [3]=reweight |
| `0x68` | 26 | `MAX_LOTS` | RW | `0` | Maximum lots per BUY (0 = full tick bar volume) |
| `0x6C` | 27 | `MARGIN` | RW | `1,049` | Minimum momentum rotation threshold margin ($Q_{20}$ units) |
| `0x70` | 28 | `ALLOC_PARAM` | RW | `0x000E0305` | Packed parameters: `min_hold=5`, `wshift=3`, `capshift=14` |
| `0x74` | 29 | `W_FLOOR` | RW | `4,096` | Minimum weight floor ($4096 = 12.5\%$ of 32,768) |
| `0x78` | 30 | `ALLOC_CODES` | R | `0` | 2-bit allocation action codes per company [15:0] |
| `0x7C` | 31 | `ALLOC_LAT` | R | `32` | Allocator execution latency in clock cycles (13–64 cycles) |
| `0x80` | 32 | `ALLOC_COUNT` | R | `0` | Total portfolio allocation rounds completed |
| `0x84` | 33 | `SCORE` | R(sel) | `0` | Signed momentum score in $2^{-20}$ fractional units |
| `0x88` | 34 | `WEIGHT` | R(sel) | `4,096` | [15:0]: Weight of 32,768 ($Q_{15}$), [23:16]: Minutes held |
| `0x8C` | 35 | `FRAME_ERR` | R | `0` | UART framing errors detected (stop-bit corruptions) |
| `0x90` | 36 | `ENG_DROP` | R | `0` | Engine busy dropped tick events |
| `0x94` | 37 | `VWAP_OFF` | R | `0` | VWAP overflow saturation protection bitmask |
| `0x98` | 38 | `PKT_ABORT` | R | `0` | Incomplete packet aborts due to framing error |
| `0x9C` | 39 | `PKT_TIMEOUT` | R | `0` | Parser inter-byte gap timeout events (5 ms threshold) |
| `0xA0` | 40 | `STRATEGY_CFG` | RW | `0` | [0]: Active strategy, [1]: Switch override, [31:8]: Switch count |
| `0xA4` | 41 | `STRAT_ORIG_DEC`| R | `0` | Total decisions evaluated under Original 2-of-3 strategy |
| `0xA8` | 42 | `STRAT_MA_DEC` | R | `0` | Total decisions evaluated under MA-Only strategy |
| `0xAC` | 43 | `AUDIT_TX_ID` | R | `0` | Monotonically increasing 32-bit transaction audit ID |

---

## 3. Communication Protocols

### Ingress Tick Frame (PC -> FPGA, 12 Bytes)
Sent over 115200 8N1 serial:
```
[Byte 0..3]  : tick_id (32-bit little-endian)
               - Bit 31     : Command flag (1 = MMIO Config / Allocate, 0 = Market Tick)
               - Bits 30:28 : Symbol index (0 to 7)
               - Bits 27:0  : Monotonic packet sequence counter
[Byte 4..7]  : tick_price (32-bit unsigned cents, e.g. $255.40 = 25540)
[Byte 8..11] : tick_volume (32-bit unsigned lots, 1 lot = 1,000 shares)
```

### Egress Report Frame (FPGA -> PC, 40 Bytes)
Returned by the RV32IM firmware per tick/command:
```
[Word 0] : 0xAA55AA55 (Header sync word)
[Word 1] : Echoed tick_id
[Word 2] : Echoed price (or HW_CASH_LO for ALLOCATE)
[Word 3] : Echoed volume (or HW_CASH_HI for ALLOCATE)
[Word 4] : Hardware decision (0: NONE, 1: BUY, 2: SELL) / ALLOC_CODES
[Word 5] : Hardware compute latency (deterministic 5 cycles / ALLOC_LAT)
[Word 6] : Software baseline decision (RV32IM firmware)
[Word 7] : Software compute latency (74 to 92 cycles)
[Word 8] : Hardware cumulative position / Momentum score / State checksum
[Word 9] : 0x55AA55AA (Footer sync word)
```

---

## 4. Latency Disaggregation

| Component | Target Clock | Typical Latency | P99 Latency | Determinism |
|---|---|---|---|---|
| **FPGA Accelerator Core** | 100 MHz (10 ns) | 5 cycles (50 ns) | 5 cycles (50 ns) | **100% Deterministic** |
| **Hardware Portfolio Allocator** | 100 MHz (10 ns) | 32 cycles (320 ns) | 59 cycles (590 ns) | Bounded (13–64 cyc) |
| **MMIO / Bus Interconnect** | 100 MHz (10 ns) | 82 cycles (820 ns) | 94 cycles (940 ns) | Low Jitter |
| **RV32IM CPU Software Core** | 100 MHz (10 ns) | 820 cycles (8.21 µs) | 958 cycles (9.58 µs) | Data Dependent |
| **UART Communication (115200)** | Line Baud | 4,514 µs | 4,553 µs | Serial Limited |

