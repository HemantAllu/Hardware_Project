# MMIO Register Map (hft_mmio, Base Address 0x3000_0000)

Offset = register_index * 4. Unmapped reads return 0; reads have no destructive side effects.

| Offset | Name | Index | Access | Reset / Description |
|---|---|---|---|---|
| 0x00 | `POS_LIMIT` | 0 | RW(sel) | 1,000 lots per-company position limit |
| 0x04 | `BRK_HIGH` | 1 | RW(sel) | Breakout upper threshold (cents) |
| 0x08 | `BRK_LOW` | 2 | RW(sel) | Breakout lower threshold (cents) |
| 0x0C | `TICK_ID` | 3 | R | Last received tick sequence identifier |
| 0x10 | `TICK_PRICE` | 4 | R | Ingress tick price in cents (e.g. $150.25 -> 15025) |
| 0x14 | `TICK_VOL` | 5 | R | Ingress tick volume in lots (1 lot = 1,000 shares) |
| 0x18 | `HW_DECISION` | 6 | R(sel) | Hardware trading decision (0: NONE, 1: BUY, 2: SELL) |
| 0x1C | `HW_LATENCY` | 7 | R(sel) | Hardware compute latency (5 clock cycles = 50 ns) |
| 0x20 | `HW_POSITION` | 8 | R(sel) | Company current inventory / position in lots |
| 0x24 | `STATUS` | 9 | Mixed | bit 0: `tick_ready` (W1C)<br>bit 1: `hw_done` (W1C)<br>bit 2: `tx_ready` (R)<br>bit 3: `alloc_done` (W1C)<br>bit 4: `alloc_busy` (R)<br>bit 5: `scores_ready` (R)<br>bit 6: `kill_tick` (R)<br>bit 7: `active_strategy` (R: 0=Original 2-of-3, 1=MA-Only) |
| 0x28 | `UART_TX` | 10 | W | Write data byte to UART TX buffer |
| 0x2C | `OVERRUN` | 11 | R | Ingress tick buffer overrun counter |
| 0x30 | `CTRL` | 12 | W | Control register: bit 0 clears diagnostic counters |
| 0x34 | `CASH_LO` | 13 | RW | Shared portfolio cash balance [31:0] (cents) |
| 0x38 | `CASH_HI` | 14 | RW | Shared portfolio cash balance [63:32] |
| 0x3C | `HW_CASH_LO` | 15 | R | Accelerator current committed cash [31:0] |
| 0x40 | `SYMBOL_SEL` | 16 | RW | Active company selector index [2:0] (0..7) |
| 0x44 | `NUM_SYMBOLS` | 17 | RW | Active companies count $N$ (1..8) |
| 0x48 | `CASH_CAP_LO` | 18 | RW(sel) | Per-company allocated cash ceiling [31:0] |
| 0x4C | `CASH_CAP_HI` | 19 | RW(sel) | Per-company allocated cash ceiling [63:32] |
| 0x50 | `HW_CASH_HI` | 20 | R | Accelerator current committed cash [63:32] |
| 0x54 | `BAD_SYMBOL` | 21 | R | Count of ticks received with symbol $\ge N$ |
| 0x58 | `N_MAX` | 22 | R | Hardware-synthesized max companies parameter |
| 0x5C | `INVESTED_LO` | 23 | R(sel) | Total capital invested in company [31:0] |
| 0x60 | `INVESTED_HI` | 24 | R(sel) | Total capital invested in company [63:32] |
| 0x64 | `PORT_MODE` | 25 | RW | 0: Independent engines, 1: Shared portfolio allocator |
| 0x68 | `MAX_LOTS` | 26 | RW | Max lots per buy allocation (0 = full volume) |
| 0x6C | `MARGIN` | 27 | RW | Minimum momentum rotation threshold margin |
| 0x70 | `ALLOC_PARAM` | 28 | RW | [7:0] `min_hold` (default 5)<br>[12:8] `wshift` (default 3)<br>[20:16] `capshift` (default 14) |
| 0x74 | `W_FLOOR` | 29 | RW | Minimum portfolio weight floor (default 4096 = 12.5%) |
| 0x78 | `ALLOC_CODES` | 30 | R | 2-bit allocation action codes per company [15:0] |
| 0x7C | `ALLOC_LAT` | 31 | R | Allocator execution latency in clock cycles |
| 0x80 | `ALLOC_COUNT` | 32 | R | Total number of portfolio allocation rounds executed |
| 0x84 | `SCORE` | 33 | R(sel) | Momentum ranking score of selected company |
| 0x88 | `WEIGHT` | 34 | R(sel) | [15:0] Weight [15] Hold lock flag |
| 0x8C | `FRAME_ERR` | 35 | R | UART receiver framing errors encountered |
| 0x90 | `ENG_DROP` | 36 | R | Engine busy dropped tick events |
| 0x94 | `VWAP_OFF` | 37 | R | VWAP overflow/saturation protection count |
| 0x98 | `PKT_ABORT` | 38 | R | UART framing error packet abort counter |
| 0x9C | `PKT_TIMEOUT` | 39 | R | UART inter-byte parser timeout counter |
| 0xA0 | `STRATEGY_CFG` | 40 | RW | **P0-D**: Strategy configuration & override register<br>bit 0: `force_strategy` mode<br>bit 1: `use_sw_override` (0: hardware SW0 switch controls strategy, 1: bit 0 controls strategy) |
| 0xA4 | `STRAT_ORIG_DEC` | 41 | R | **P0-D**: Baseline 2-of-3 voting decision (0: NONE, 1: BUY, 2: SELL) |
| 0xA8 | `STRAT_MA_DEC` | 42 | R | **P0-D**: Moving Average only decision (0: NONE, 1: BUY, 2: SELL) |
| 0xAC | `AUDIT_TX_ID` | 43 | R | **P0-C**: Monotonically increasing 32-bit transaction audit sequence ID |
