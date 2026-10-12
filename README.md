# RV32IM Core + Trading Co-processor

A five-stage RV32IM processor written in Verilog, paired with a memory-mapped trading co-processor. The system runs on a Nexys A7-100T FPGA at 100 MHz and compares trading decisions from hardware with decisions computed by C firmware running on the processor.

## Features

- Five-stage RV32IM pipeline: IF, ID, EX, MEM, and WB
- Forwarding, load-use stalls, and branch flushing
- Support for all eight RV32M multiply and divide instructions
- Memory-mapped instruction memory, data memory, board I/O, and trading co-processor
- Trading engine that makes a decision in five clock cycles
- UART input and output for market ticks and reports
- Firmware that compares hardware and software decisions on every tick
- PC dashboard for viewing prices, decisions, positions, returns, and latency
- FPGA implementation targeting the Nexys A7-100T

## System Overview

A PC sends market ticks to the FPGA over UART. Each tick contains a company ID, price, and volume. The trading co-processor evaluates the tick and produces a decision. At the same time, the RV32IM processor runs the corresponding strategy in C.

The firmware compares the hardware and software results, then sends a report back to the PC. The dashboard checks each report and displays the results.

## Processor

The processor implements the RV32I base instruction set and the M extension. Its five pipeline stages are:

| Stage | Function |
| --- | --- |
| IF | Fetch an instruction |
| ID | Decode the instruction and read registers |
| EX | Perform arithmetic, comparisons, branches, and multiply/divide operations |
| MEM | Access data memory or memory-mapped devices |
| WB | Write a result to the register file |

The core includes forwarding for data hazards, a one-cycle stall for load-use hazards, and a two-instruction flush when a branch is taken.

The multi-cycle MUL/DIV unit supports `MUL`, `MULH`, `MULHSU`, `MULHU`, `DIV`, `DIVU`, `REM`, and `REMU`.

## Trading Co-processor

The trading engine accepts a price and volume, updates its recent-price history and running sums, and makes a decision in five cycles. It uses moving-average and VWAP comparisons, breakout votes, and risk checks.


