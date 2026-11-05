# Known Limitations and Engineering Constraints

**System**: RV32IM Multi-Company FPGA Trading System  
**Release**: v12-complete-upgrade  
**Status**: Simulation Verified & Toolchain Elaborated  

---

## 1. Interface & Communication Constraints

1. **Ingress Protocol Framing**:
   - The ingress tick packet from PC to FPGA consists of 12 raw binary bytes without an explicit header sync word or CRC/checksum. Egress packets do incorporate full 32-bit sync words (`0xAA55AA55` header, `0x55AA55AA` footer).
   - If a transmission glitch corrupts byte alignment, the parser relies on the 100,000-cycle watchdog timeout or framing error detection to re-arm. A valid packet arriving within the parser's 3-cycle recovery gap after a framing abort can be lost.
2. **Serial Interconnect Throughput Bottleneck**:
   - The physical link operates at 115,200 baud. Transmitting 12 bytes ingress and receiving 40 bytes egress requires approximately 4.51 ms per tick.
   - While the FPGA internal compute core completes in 50 ns (5 clock cycles), sustained real-world streaming throughput through the USB-UART bridge cannot exceed ~220 ticks/sec without hardware FIFO drop risk.
3. **Overload Drop Policy**:
   - Under burst conditions exceeding ingress FIFO capacity or during an active engine processing cycle, incoming ticks are dropped rather than stalled with hardware flow control.
   - Drops are accounted for via diagnostic counters (`OVERRUN` at `0x2C` and `ENG_DROP` at `0x90`), ensuring transparency rather than silent loss.

---

## 2. Hardware Architecture & Algorithmic Bounds

1. **Allocator Upper-Bound Latency**:
   - The maximum observed allocator latency across all simulation runs is 64 clock cycles (640 ns). While this is sufficient for 1-minute bar cadences, it represents an empirical upper bound rather than a mathematically or formally proven worst-case upper bound under arbitrary $N$-company permutations.
2. **Non-Borrowing Margin Boundaries**:
   - In rare pathological scenarios where cash is insufficient to buy a single lot, the allocator enters an idle state. Liquidations take precedence, but trading halts for that company until cash is replenished.

---

## 3. Physical Verification & Deployment Status

1. **Physical Board Verification**:
   - All regression suites (10/10 stages, 16 full-day market replays, M-extension randomized vector suites, and RTL elaboration via Xilinx Vivado `xvlog`) have completed with 100% PASS marks.
   - However, in this containerized build environment, physical attachment of a physical Digilent Nexys A7-100T board over USB JTAG/UART was not present. Full bitstream programming and physical oscilloscope probing must be validated on bench hardware before live financial production deployment.
