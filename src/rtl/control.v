`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// control.v : main instruction decoder for RV32IM
//
//   a_sel : 0 = rs1, 1 = PC, 2 = zero         (ALU operand A)
//   b_sel : 0 = rs2, 1 = immediate            (ALU operand B)
//   alu_op: see alu.v
//   is_muldiv : OP opcode with funct7 = 0000001 (RV32M)
//   is_halt   : ECALL / EBREAK -> stops the core (used by testbenches)
//   uses_rs1 / uses_rs2 : whether the instruction really reads that source
//                         (keeps the load-use detector from stalling needlessly)
//
// Unknown / unsupported opcodes decode as NOPs (no side effects).
// -----------------------------------------------------------------------------
module control (
    input  wire [31:0] instr,
    output reg         reg_write,
    output reg         mem_read,
    output reg         mem_write,
    output reg         is_branch,
    output reg         is_jal,
    output reg         is_jalr,
    output reg         is_muldiv,
    output reg         is_halt,
    output reg  [1:0]  a_sel,
    output reg         b_sel,
    output reg  [3:0]  alu_op,
    output reg         uses_rs1,
    output reg         uses_rs2
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

    wire [6:0] opcode = instr[6:0];
    wire [2:0] funct3 = instr[14:12];
    wire [6:0] funct7 = instr[31:25];

    always @(*) begin
        // defaults: NOP
        reg_write = 1'b0;
        mem_read  = 1'b0;
        mem_write = 1'b0;
        is_branch = 1'b0;
        is_jal    = 1'b0;
        is_jalr   = 1'b0;
        is_muldiv = 1'b0;
        is_halt   = 1'b0;
        a_sel     = 2'd0;
        b_sel     = 1'b0;
        alu_op    = ALU_ADD;
        uses_rs1  = 1'b0;
        uses_rs2  = 1'b0;

        case (opcode)
            7'b0110111: begin                       // LUI
                reg_write = 1'b1;
                a_sel     = 2'd2;
                b_sel     = 1'b1;
            end
            7'b0010111: begin                       // AUIPC
                reg_write = 1'b1;
                a_sel     = 2'd1;
                b_sel     = 1'b1;
            end
            7'b1101111: begin                       // JAL
                reg_write = 1'b1;
                is_jal    = 1'b1;
            end
            7'b1100111: begin                       // JALR
                reg_write = 1'b1;
                is_jalr   = 1'b1;
                uses_rs1  = 1'b1;
                b_sel     = 1'b1;
            end
            7'b1100011: begin                       // BRANCH
                is_branch = 1'b1;
                uses_rs1  = 1'b1;
                uses_rs2  = 1'b1;
            end
            7'b0000011: begin                       // LOAD
                reg_write = 1'b1;
                mem_read  = 1'b1;
                b_sel     = 1'b1;
                uses_rs1  = 1'b1;
            end
            7'b0100011: begin                       // STORE
                mem_write = 1'b1;
                b_sel     = 1'b1;
                uses_rs1  = 1'b1;
                uses_rs2  = 1'b1;
            end
            7'b0010011: begin                       // OP-IMM
                reg_write = 1'b1;
                b_sel     = 1'b1;
                uses_rs1  = 1'b1;
                case (funct3)
                    3'b000: alu_op = ALU_ADD;
                    3'b010: alu_op = ALU_SLT;
                    3'b011: alu_op = ALU_SLTU;
                    3'b100: alu_op = ALU_XOR;
                    3'b110: alu_op = ALU_OR;
                    3'b111: alu_op = ALU_AND;
                    3'b001: alu_op = ALU_SLL;
                    3'b101: alu_op = instr[30] ? ALU_SRA : ALU_SRL;
                endcase
            end
            7'b0110011: begin                       // OP (R-type)
                reg_write = 1'b1;
                uses_rs1  = 1'b1;
                uses_rs2  = 1'b1;
                if (funct7 == 7'b0000001) begin
                    is_muldiv = 1'b1;               // RV32M
                end else begin
                    case (funct3)
                        3'b000: alu_op = funct7[5] ? ALU_SUB : ALU_ADD;
                        3'b001: alu_op = ALU_SLL;
                        3'b010: alu_op = ALU_SLT;
                        3'b011: alu_op = ALU_SLTU;
                        3'b100: alu_op = ALU_XOR;
                        3'b101: alu_op = funct7[5] ? ALU_SRA : ALU_SRL;
                        3'b110: alu_op = ALU_OR;
                        3'b111: alu_op = ALU_AND;
                    endcase
                end
            end
            7'b1110011: begin                       // SYSTEM
                if (instr == 32'h00000073 || instr == 32'h00100073)
                    is_halt = 1'b1;                 // ECALL / EBREAK
            end
            default: ;                              // FENCE and unknown -> NOP
        endcase
    end
endmodule
