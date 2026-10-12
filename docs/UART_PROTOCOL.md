# UART Communication Protocol Specification

**Physical Layer**: RS-232 / USB-UART Bridge (Digilent Nexys A7-100T FTDI FT2232HQ)  
**Baud Rate**: 115,200 baud  
**Data Format**: 8 data bits, no parity, 1 stop bit (8-N-1)  
**Bit Period**: 8.68 $\mu$s  
**Byte Period**: 86.8 $\mu$s (10 bits including start and stop)  

---

## 1. Packet Formats

### 1.1 Ingress Tick Packet (PC $\to$ FPGA, 12 Bytes)

Every market tick or host configuration command is transmitted as a 12-byte little-endian binary sequence:

```
+---------------+---------------+---------------+
| Byte 0 - 3    | Byte 4 - 7    | Byte 8 - 11   |
| Tick ID / Cmd | Price (cents) | Volume (lots) |
+---------------+---------------+---------------+
```

- **`TICK_ID` [31:0]**:
  - `[27:0]`: Monotonically increasing tick sequence number.
  - `[30:28]`: Target company symbol index $S \in \{0, \dots, 7\}$.
  - `[31]`: Command flag:
    - `0`: Normal market tick update.
    - `1`: Configuration command (e.g. `CMD_RESET`, `CMD_CFG_BRK`, `CMD_CFG_LIMIT`, `CMD_CFG_CASH`, `CMD_ALLOCATE`).
- **`PRICE` [31:0]**: Ingress price scaled in integer cents (e.g., $185.50 = `18550`).
- **`VOLUME` [31:0]**: Ingress trade volume in whole lots (1 lot = 1,000 shares; 0 volume updates moving averages without trading).

### 1.2 Egress Report Packet (FPGA $\to$ PC, 40 Bytes)

For every accepted tick and allocation decision, the FPGA emits a 40-byte report:

```
+-----------+---------+-----------+----------+--------+--------+--------+--------+----------+-----------+
| Offset    | 0..3    | 4..7      | 8..11    | 12..15 | 16..19 | 20..23 | 24..27 | 28..31   | 32..35    | 36..39    |
| Field     | Header  | Echo TID  | Echo P   | Echo V | HW Dec | HW Lat | SW Dec | SW Lat   | Position  | Footer    |
| Value/Hex | AA55AA55| [31:0]    | [31:0]   | [31:0] | 0/1/2  | 5 Cyc  | 0/1/2  | ~82 Cyc  | Lots      | 55AA55AA  |
+-----------+---------+-----------+----------+--------+--------+--------+--------+----------+-----------+
```

- **`Header`**: Fixed sync word `0xAA55AA55`.
- **`Echo TID`**: Ingress sequence ID echoed back for end-to-end receipt verification.
- **`Echo Price`**: Echoed price to verify communication fidelity.
- **`Echo Volume`**: Echoed volume.
- **`HW Decision`**: Hardware accelerator decision:
  - `0`: NONE (Hold / Inactive)
  - `1`: BUY
  - `2`: SELL
- **`HW Latency`**: Hardware core calculation latency (constant 5 clock cycles = 50 ns).
- **`SW Decision`**: RV32IM software model decision computed concurrently by CPU firmware.
- **`SW Latency`**: CPU firmware calculation latency (typically 80–85 clock cycles = 800–850 ns).
- **`HW Position`**: Post-execution inventory of the company in lots.
- **`Footer`**: Fixed sync word `0x55AA55AA`.

---

## 2. Framing Error and Overrun Protection

1. **Framing Error Recovery**:
   If a stop bit is missing (`rx_frame_err = 1`), `tick_parser.v` immediately discards the partial packet, increments the `FRAME_ERR` (`0x8C`) and `PKT_ABORT` (`0x98`) counters, and enters a 3-cycle gap state before re-arming.
2. **Inter-Byte Timeout**:
   If fewer than 12 bytes arrive within 100,000 clock cycles (1 ms), `PKT_TIMEOUT` (`0x9C`) increments, the internal state resets to `IDLE`, and subsequent bytes are treated as the start of a fresh packet.
3. **Hardware Flow Control & Drops**:
   The hardware accelerator does not silently drop packets. If the ingress FIFO overflows during intense bursts, the `OVERRUN` (`0x2C`) counter increments; if an engine is still busy when a tick arrives, `ENG_DROP` (`0x90`) increments. Both are readable via MMIO and monitored continuously by the dashboard.

