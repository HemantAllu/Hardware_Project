`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// forwarding_unit.v : operand forwarding for the EX stage
//
//   fwd = 2'b10 : take the value from the EX/MEM register  (producer 1 ahead)
//   fwd = 2'b01 : take the value from the MEM/WB register  (producer 2 ahead)
//   fwd = 2'b00 : use the register-file value read in ID
//
// EX/MEM has priority (it holds the youngest producer).
// A load in EX/MEM is never forwarded from: the hazard unit stalls the
// dependent instruction one cycle so it picks the data up from MEM/WB instead.
// -----------------------------------------------------------------------------
module forwarding_unit (
    input  wire [4:0] ex_rs1,
    input  wire [4:0] ex_rs2,
    input  wire [4:0] mem_rd,
    input  wire       mem_reg_write,
    input  wire [4:0] wb_rd,
    input  wire       wb_reg_write,
    output reg  [1:0] fwd_a,
    output reg  [1:0] fwd_b
);
    always @(*) begin
        fwd_a = 2'b00;
        if (mem_reg_write && (mem_rd != 5'd0) && (mem_rd == ex_rs1))
            fwd_a = 2'b10;
        else if (wb_reg_write && (wb_rd != 5'd0) && (wb_rd == ex_rs1))
            fwd_a = 2'b01;

        fwd_b = 2'b00;
        if (mem_reg_write && (mem_rd != 5'd0) && (mem_rd == ex_rs2))
            fwd_b = 2'b10;
        else if (wb_reg_write && (wb_rd != 5'd0) && (wb_rd == ex_rs2))
            fwd_b = 2'b01;
    end
endmodule
