`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// imm_gen.v : RV32 immediate generator (I, S, B, U, J formats)
// -----------------------------------------------------------------------------
module imm_gen (
    input  wire [31:0] instr,
    output reg  [31:0] imm
);
    always @(*) begin
        case (instr[6:0])
            7'b0110111,                                         // LUI
            7'b0010111: imm = {instr[31:12], 12'b0};            // AUIPC
            7'b1101111: imm = {{12{instr[31]}}, instr[19:12],   // JAL
                               instr[20], instr[30:21], 1'b0};
            7'b1100011: imm = {{20{instr[31]}}, instr[7],       // BRANCH
                               instr[30:25], instr[11:8], 1'b0};
            7'b0100011: imm = {{20{instr[31]}}, instr[31:25],   // STORE
                               instr[11:7]};
            default:    imm = {{20{instr[31]}}, instr[31:20]};  // I-type (OP-IMM, LOAD, JALR)
        endcase
    end
endmodule
