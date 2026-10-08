`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// seg7_driver.v : multiplexed 8-digit hex display (Nexys A7, common-anode,
//                 segments and digit enables are ACTIVE LOW).
//   seg = {CG, CF, CE, CD, CC, CB, CA}
//   Each digit is lit for 2^REFRESH_BITS clocks (17 -> ~1.3 ms at 100 MHz,
//   i.e. the whole display refreshes at ~95 Hz).
// -----------------------------------------------------------------------------
module seg7_driver #(
    parameter REFRESH_BITS = 17
)(
    input  wire        clk,
    input  wire [31:0] value,
    output reg  [6:0]  seg,
    output reg  [7:0]  an,
    output wire        dp
);
    reg [REFRESH_BITS+2:0] cnt = 0;
    always @(posedge clk) cnt <= cnt + 1'b1;

    wire [2:0] sel = cnt[REFRESH_BITS+2:REFRESH_BITS];
    reg  [3:0] nib;

    assign dp = 1'b1;                          // decimal points off

    always @(*) begin
        an  = ~(8'b0000_0001 << sel);
        nib = value[{sel, 2'b00} +: 4];
        case (nib)
            4'h0: seg = 7'b1000000;
            4'h1: seg = 7'b1111001;
            4'h2: seg = 7'b0100100;
            4'h3: seg = 7'b0110000;
            4'h4: seg = 7'b0011001;
            4'h5: seg = 7'b0010010;
            4'h6: seg = 7'b0000010;
            4'h7: seg = 7'b1111000;
            4'h8: seg = 7'b0000000;
            4'h9: seg = 7'b0010000;
            4'hA: seg = 7'b0001000;
            4'hB: seg = 7'b0000011;
            4'hC: seg = 7'b1000110;
            4'hD: seg = 7'b0100001;
            4'hE: seg = 7'b0000110;
            default: seg = 7'b0001110;         // F
        endcase
    end
endmodule
