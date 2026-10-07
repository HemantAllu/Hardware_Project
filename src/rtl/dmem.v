`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// dmem.v : data memory, byte-write-enable, synchronous write, async read.
//   we[i] enables byte lane i (little endian). Address is a byte address; only
//   the word index bits are used (accesses are assumed naturally aligned).
// -----------------------------------------------------------------------------
module dmem #(
    parameter WORDS     = 1024,
    parameter INIT_FILE = "dmem.mem"
)(
    input  wire        clk,
    input  wire [31:0] addr,
    input  wire [31:0] wdata,
    input  wire [3:0]  we,
    output wire [31:0] rdata
);
    localparam AW = $clog2(WORDS);
    reg [31:0] mem [0:WORDS-1];
    integer i;

    initial begin
        for (i = 0; i < WORDS; i = i + 1) mem[i] = 32'h0000_0000;
        if (INIT_FILE != "") $readmemh(INIT_FILE, mem);
    end

    wire [AW-1:0] idx = addr[AW+1:2];

    // one write enable per byte lane: the coding style Vivado maps onto RAM
    always @(posedge clk) begin
        if (we[0]) mem[idx][7:0]   <= wdata[7:0];
        if (we[1]) mem[idx][15:8]  <= wdata[15:8];
        if (we[2]) mem[idx][23:16] <= wdata[23:16];
        if (we[3]) mem[idx][31:24] <= wdata[31:24];
    end

    assign rdata = mem[idx];
endmodule
