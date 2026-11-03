# Arithmetic

Widths were reviewed in the original v12 audit (cash saturates at 2^64-1, 64-bit products, 34-bit MA sum). In this pass: Verilator `-Wall` gives 0 errors and WIDTHTRUNC/WIDTHEXPAND warnings only (80 at N=2, 70 at N=8). Reviewed: array-index warnings (a 3/4-bit index into an array of N_MAX entries; the FSM keeps the index < N) and `hft_alloc.v:511` (`wi - share*(ns_eff-1)`; operands are context-extended to 16 bits and `share = ti >> share_shift(nsym)` keeps the product below `ti`). Behaviour is covered by the allocator and SoC tests; no formal proof.
