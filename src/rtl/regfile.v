`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// regfile.v : 32 x 32 register file, 2 async read ports, 1 sync write port.
//   * x0 is hard-wired to zero.
//   * Write-through: a read of the register being written in the same cycle
//     returns the new value. This covers the "3 instructions apart" RAW case
//     (producer in WB, consumer in ID) without an extra forwarding path.
// -----------------------------------------------------------------------------
module regfile (
    input  wire        clk,
    input  wire [4:0]  raddr1,
    input  wire [4:0]  raddr2,
    output wire [31:0] rdata1,
    output wire [31:0] rdata2,
    input  wire        we,
    input  wire [4:0]  waddr,
    input  wire [31:0] wdata
);
    reg [31:0] regs [0:31];
    integer i;

    initial begin
        for (i = 0; i < 32; i = i + 1) regs[i] = 32'b0;
    end

    always @(posedge clk) begin
        if (we && (waddr != 5'd0))
            regs[waddr] <= wdata;
    end

    assign rdata1 = (raddr1 == 5'd0)              ? 32'b0 :
                    (we && (waddr == raddr1))      ? wdata :
                                                     regs[raddr1];
    assign rdata2 = (raddr2 == 5'd0)              ? 32'b0 :
                    (we && (waddr == raddr2))      ? wdata :
                                                     regs[raddr2];
endmodule
