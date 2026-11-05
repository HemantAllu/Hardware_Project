# V12 complete audit

Scope: RV32IM Vivado v12 project, audited with simulation (Icarus 13, Verilator 5.031), Python models, host-C reference vectors, Verilator lint, Yosys estimates. Vivado was not available.

## Findings

| ID | Class | Severity | File | Issue | Root cause | Fix | Verification |
|---|---|---|---|---|---|---|---|
| P0 | Confirmed bug | High | tick_parser.v / hft_mmio.v | Framing error never reaches the parser; later packets misaligned | `rx_ferr` only counted | `abort` input, skip + idle resync | chain N=1..8, SoC N=2/4/8 |
| V12-FIX-01 | Confirmed bug | Medium (build) | hft_multi.v, hft_alloc.v | Use before declaration, Icarus 13 fails to elaborate | declaration order | moved declarations | whole suite |
| D-01 | Doc inconsistency | Low | CHANGES_V12_BUGFIXES.md | claimed bad stop bits dropped | see P0 | correction appended | n/a |
| L-01 | Limitation | Medium | hft_mmio / accelerator | Data can be dropped (one-entry latch/buffer) | by design | counters OVERRUN, ENG_DROP; not claimed lossless | burst test |
| L-02 | Limitation | Medium | protocol | No sync byte or checksum | by design | not changed | documented |
| L-03 | Limitation | Medium | whole design | 100 MHz timing unverified | no Vivado | commands in VIVADO_TIMING_REPORT | none |
| L-04 | Lint | Info | many | 80 / 70 WIDTH warnings (N=2 / N=8) | array indexes narrower than index type; constant extension | reviewed, not rewritten | simulation |

Suspected/not proven: allocator latency bound (observed max 64 at N=8), CPU correctness beyond the project-written reference, behaviour of a framing error exactly during an allocation.

Not done: backtesting extras (fees, Sharpe, train/test), dashboard GUI test, allocator divider alternatives, Vivado runs, board test.

Modification log: see docs/BUG_FIXES.md and git history. Original archive kept untouched.
