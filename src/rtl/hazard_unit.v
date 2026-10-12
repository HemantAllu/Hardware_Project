`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// hazard_unit.v : stall / flush control for the 5-stage pipeline
//
//  1. Load-use hazard   : instruction in ID needs the result of a load that is
//                         currently in EX.  -> hold PC and IF/ID one cycle and
//                         insert a bubble into ID/EX.
//  2. Multi-cycle MUL/DIV: M instruction in EX that is not finished yet.
//                         -> hold PC, IF/ID and ID/EX; insert bubbles into
//                         EX/MEM (older instructions in MEM/WB keep draining).
//  3. Control hazard    : taken branch / JAL / JALR resolved in EX.
//                         -> redirect PC and flush IF/ID and ID/EX
//                         (2-cycle penalty; static predict-not-taken).
//  4. Halt (EBREAK/ECALL): flush younger instructions and stop fetching.
//
// Priority in the pipeline registers: flush/redirect > stall > bubble.
// -----------------------------------------------------------------------------
module hazard_unit (
    // ID stage
    input  wire       id_valid,
    input  wire [4:0] id_rs1,
    input  wire [4:0] id_rs2,
    input  wire       id_uses_rs1,
    input  wire       id_uses_rs2,
    // EX stage
    input  wire       ex_valid,
    input  wire       ex_mem_read,     // instruction in EX is a load
    input  wire [4:0] ex_rd,
    input  wire       ex_md_busy,      // M instruction in EX, result not ready
    input  wire       ex_redirect,     // taken branch / jump in EX
    input  wire       ex_halt,         // EBREAK / ECALL in EX
    input  wire       halted,
    // outputs
    output wire       load_use,
    output wire       stall_pc,
    output wire       stall_ifid,
    output wire       stall_idex,
    output wire       bubble_idex,
    output wire       bubble_exmem,
    output wire       flush_ifid,
    output wire       flush_idex
);
    wire flush = ex_redirect | ex_halt | halted;

    assign load_use = id_valid & ex_valid & ex_mem_read & (ex_rd != 5'd0) &
                      ((id_uses_rs1 & (ex_rd == id_rs1)) |
                       (id_uses_rs2 & (ex_rd == id_rs2)));

    assign stall_pc     = ex_md_busy | load_use;
    assign stall_ifid   = ex_md_busy | load_use;
    assign stall_idex   = ex_md_busy;
    assign bubble_idex  = load_use & ~ex_md_busy;
    assign bubble_exmem = ex_md_busy;
    assign flush_ifid   = flush;
    assign flush_idex   = flush;
endmodule
