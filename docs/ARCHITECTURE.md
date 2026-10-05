# Architecture

uart_rx -> tick_parser (12-byte packets, abort/timeout) -> hft_mmio (one latched packet, counters, register file) -> CPU/firmware and hft_accelerator -> hft_multi (N engines, shared 64-bit cash unit) -> hft_alloc (portfolio allocator FSM). soc_top glues a 5-stage RV32IM core (async-read IMEM/DMEM), seg7, UART TX. Default HFT_N_MAX=2, maximum 8 (3-bit company id).
