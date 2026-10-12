`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// muldiv_unit.v : multi-cycle RV32M execution unit
//
//   funct3 : 000 MUL   001 MULH   010 MULHSU   011 MULHU
//            100 DIV   101 DIVU   110 REM      111 REMU
//
// Handshake (matches how the core's EX stage uses it):
//   * The core asserts `start` while an M instruction sits in EX. The unit
//     only accepts it in S_IDLE; operands a/b/funct3 are latched on that first
//     cycle, so later changes on a/b (forwarding sources moving on) are harmless.
//   * `done` is high for exactly one cycle (S_DONE) with `result` valid. The
//     core releases the instruction from EX at the end of that cycle, and the
//     unit goes back to S_IDLE by itself.
//
// Latency (cycles the instruction occupies EX, counting the start and done cycle)
//   MUL/MULH*  : 4   (IDLE, MUL1, MUL2, DONE)  -> 3 stall cycles
//   DIV/REM*   : 36  (IDLE, PREP, 32 x RUN, FIN, DONE) -> 35 stall cycles
// Latency is data independent (deterministic), including divide-by-zero.
//
// RISC-V corner cases implemented:
//   x / 0   = all ones (-1)         x % 0   = x            (signed and unsigned)
//   INT_MIN / -1 = INT_MIN          INT_MIN % -1 = 0
//   quotient truncates toward zero, remainder takes the sign of the dividend.
// -----------------------------------------------------------------------------
module muldiv_unit (
    input  wire        clk,
    input  wire        rst,
    input  wire        start,
    input  wire [2:0]  funct3,
    input  wire [31:0] a,
    input  wire [31:0] b,
    output wire        done,
    output wire [31:0] result
);
    localparam [2:0] S_IDLE = 3'd0,
                     S_MUL1 = 3'd1,
                     S_MUL2 = 3'd2,
                     S_PREP = 3'd3,
                     S_RUN  = 3'd4,
                     S_FIN  = 3'd5,
                     S_DONE = 3'd6;

    reg [2:0]  state;
    reg [2:0]  f3_r;
    reg [31:0] a_r, b_r;
    reg [31:0] result_r;

    assign done   = (state == S_DONE);
    assign result = result_r;

    // ------------------------------------------------------------ multiplier
    // One 33x33 signed multiplier handles all four variants by choosing how
    // each operand is extended to 33 bits.
    wire a_signed = (f3_r == 3'b001) | (f3_r == 3'b010);   // MULH, MULHSU
    wire b_signed = (f3_r == 3'b001);                      // MULH
    wire signed [32:0] a_ext = {a_signed & a_r[31], a_r};
    wire signed [32:0] b_ext = {b_signed & b_r[31], b_r};
    reg  signed [65:0] prod_r;

    // ---------------------------------------------------------------- divider
    // Restoring divider on magnitudes, sign fixed up at the end.
    wire        div_signed = ~f3_r[0];                     // DIV, REM are signed
    wire        neg_a      = div_signed & a_r[31];
    wire        neg_b      = div_signed & b_r[31];
    reg  [31:0] dvs;                                       // |divisor|
    reg  [31:0] quo;                                       // |dividend| shifts out, quotient shifts in
    reg  [31:0] rem;
    reg  [5:0]  cnt;
    wire [32:0] rem_sh = {rem, quo[31]};
    wire        ge     = (rem_sh >= {1'b0, dvs});

    always @(posedge clk) begin
        if (rst) begin
            state    <= S_IDLE;
            f3_r     <= 3'b000;
            a_r      <= 32'b0;
            b_r      <= 32'b0;
            result_r <= 32'b0;
            prod_r   <= 66'sd0;
            dvs      <= 32'b0;
            quo      <= 32'b0;
            rem      <= 32'b0;
            cnt      <= 6'd0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (start) begin
                        a_r   <= a;
                        b_r   <= b;
                        f3_r  <= funct3;
                        state <= funct3[2] ? S_PREP : S_MUL1;
                    end
                end

                S_MUL1: begin
                    prod_r <= a_ext * b_ext;
                    state  <= S_MUL2;
                end

                S_MUL2: begin
                    result_r <= (f3_r == 3'b000) ? prod_r[31:0] : prod_r[63:32];
                    state    <= S_DONE;
                end

                S_PREP: begin
                    quo   <= neg_a ? (32'b0 - a_r) : a_r;
                    dvs   <= neg_b ? (32'b0 - b_r) : b_r;
                    rem   <= 32'b0;
                    cnt   <= 6'd0;
                    state <= S_RUN;
                end

                S_RUN: begin
                    if (ge) begin
                        rem <= rem_sh[31:0] - dvs;
                        quo <= {quo[30:0], 1'b1};
                    end else begin
                        rem <= rem_sh[31:0];
                        quo <= {quo[30:0], 1'b0};
                    end
                    cnt <= cnt + 6'd1;
                    if (cnt == 6'd31) state <= S_FIN;
                end

                S_FIN: begin
                    if (b_r == 32'b0)
                        result_r <= f3_r[1] ? a_r : 32'hFFFF_FFFF;          // divide by zero
                    else if (f3_r[1])                                       // REM / REMU
                        result_r <= neg_a ? (32'b0 - rem) : rem;
                    else                                                    // DIV / DIVU
                        result_r <= (neg_a ^ neg_b) ? (32'b0 - quo) : quo;
                    state <= S_DONE;
                end

                S_DONE: begin
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
