# Module dependency map

soc_top -> rv32im_core (alu, control, imm_gen, regfile, forwarding_unit, hazard_unit, muldiv_unit), imem, dmem, seg7_driver, hft_mmio.
hft_mmio -> uart (rx/tx), tick_parser, hft_accelerator -> hft_multi, hft_alloc.
