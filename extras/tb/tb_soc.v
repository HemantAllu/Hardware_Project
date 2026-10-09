`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_soc.v : smoke test of soc_top running sw/demo_board.S (built with a short
//            DELAY).  Checks the sequence written to the 7-segment register.
//   run:  vvp build/tb_soc.vvp +IMEM=<imem.hex> +DMEM=<dmem.hex>
// -----------------------------------------------------------------------------
module tb_soc;
    reg         clk = 0;
    reg         cpu_resetn = 0;
    reg  [15:0] sw = 16'h030A;          // A = 10, B = 3
    wire [15:0] led;
    wire [6:0]  seg;
    wire        dp;
    wire [7:0]  an;

    always #5 clk = ~clk;

    soc_top #(.IMEM_INIT(""), .DMEM_INIT(""), .SEG_REFRESH_BITS(4)) u_soc (
        .clk(clk), .cpu_resetn(cpu_resetn), .sw(sw),
        .led(led), .seg(seg), .dp(dp), .an(an),
        .uart_rx(1'b1), .uart_tx()
    );

    reg [8*1024-1:0] fname;            // room for paths up to 1024 characters
    reg [31:0] expected [0:7];
    integer ptr = 0;
    integer errors = 0;

    initial begin
        expected[0] = 32'h00123400;
        expected[1] = 32'hFFFFFFFE;
        expected[2] = 32'h00022E09;
        expected[3] = 32'h00000001;
        expected[4] = 32'hFFFFFFF2;
        expected[5] = 32'hFFFFFFFF;
        expected[6] = 32'h00000000;     // wildcard: measured cycle count
        expected[7] = 32'h001E0301;     // A*B=0x1E, A/B=3, A%B=1
        #1;
        if ($value$plusargs("IMEM=%s", fname)) $readmemh(fname, u_soc.u_imem.mem);
        if ($value$plusargs("DMEM=%s", fname)) $readmemh(fname, u_soc.u_dmem.mem);
        #40 cpu_resetn = 1;
    end

    always @(u_soc.seg_reg) if (cpu_resetn && u_soc.seg_reg !== 32'bx) begin
        $display("t=%0t  SEG=%08x  LED=%04x", $time, u_soc.seg_reg, led);
        if (ptr < 8) begin
            if (ptr == 6) begin
                $display("   measured DIVU cycles (incl. 2 MMIO loads) = %0d", u_soc.seg_reg);
            end else if (u_soc.seg_reg !== expected[ptr]) begin
                $display("   MISMATCH: expected %08x", expected[ptr]);
                errors = errors + 1;
            end
            ptr = ptr + 1;
        end
    end

    initial begin
        #2000000;
        if (ptr == 8 && errors == 0) $display("TB_SOC PASS");
        else                         $display("TB_SOC FAIL (ptr=%0d errors=%0d)", ptr, errors);
        $finish;
    end
endmodule
