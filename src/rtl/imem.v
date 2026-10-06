`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// imem.v : instruction memory, asynchronous (combinational) read.
//   Infers distributed RAM / ROM in Vivado. Initialised from INIT_FILE
//   (one 32-bit hex word per line, as $readmemh expects); unused words are NOPs.
//   If you later move to block RAM (registered read), fetch gets one more cycle
//   of latency and the PC logic in rv32im_core must be adapted.
// -----------------------------------------------------------------------------
module imem #(
    parameter WORDS     = 1024,
    parameter INIT_FILE = "imem.mem"
)(
    input  wire [31:0] addr,       // byte address
    output wire [31:0] rdata
);
    localparam AW = $clog2(WORDS);
    reg [31:0] mem [0:WORDS-1];
    integer i;

    initial begin
        for (i = 0; i < WORDS; i = i + 1) mem[i] = 32'h0000_0013;   // NOP (addi x0,x0,0)
        if (INIT_FILE != "") $readmemh(INIT_FILE, mem);
    end

    assign rdata = mem[addr[AW+1:2]];
endmodule
