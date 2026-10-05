`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// alu.v : RV32I integer ALU (combinational)
//   ADD/SUB/AND/OR/XOR/SLL/SRL/SRA/SLT/SLTU
// -----------------------------------------------------------------------------
module alu (
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [3:0]  op,
    output reg  [31:0] y
);
    localparam ALU_ADD  = 4'd0;
    localparam ALU_SUB  = 4'd1;
    localparam ALU_AND  = 4'd2;
    localparam ALU_OR   = 4'd3;
    localparam ALU_XOR  = 4'd4;
    localparam ALU_SLL  = 4'd5;
    localparam ALU_SRL  = 4'd6;
    localparam ALU_SRA  = 4'd7;
    localparam ALU_SLT  = 4'd8;
    localparam ALU_SLTU = 4'd9;

    wire signed [31:0] sa = a;
    wire signed [31:0] sb = b;

    always @(*) begin
        case (op)
            ALU_ADD:  y = a + b;
            ALU_SUB:  y = a - b;
            ALU_AND:  y = a & b;
            ALU_OR:   y = a | b;
            ALU_XOR:  y = a ^ b;
            ALU_SLL:  y = a << b[4:0];
            ALU_SRL:  y = a >> b[4:0];
            ALU_SRA:  y = sa >>> b[4:0];
            ALU_SLT:  y = {31'b0, (sa < sb)};
            ALU_SLTU: y = {31'b0, (a < b)};
            default:  y = 32'b0;
        endcase
    end
endmodule
