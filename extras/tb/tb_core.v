`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_core.v : runs a program on rv32im_core + imem + dmem until EBREAK/ECALL,
//             then prints statistics, all registers and the first DUMP_WORDS
//             words of data memory in a machine-readable format.
//
// Plusargs (all optional):
//   +IMEM=<file>   instruction hex file   (default imem.hex in the sim dir)
//   +DMEM=<file>   data hex file          (default dmem.hex in the sim dir)
//   +VCD=<file>    write a VCD waveform
//
// Data memory is addressed by word index only, so the 0x1000_0000 data base used
// by the software maps straight onto word 0 of dmem.
// -----------------------------------------------------------------------------
module tb_core;
    parameter IMEM_WORDS = 4096;
    parameter DMEM_WORDS = 1024;
    parameter DUMP_WORDS = 64;
    parameter MAX_CYCLES = 3000000;

    reg clk = 0;
    reg rst = 1;
    always #5 clk = ~clk;

    wire [31:0] imem_addr, imem_rdata;
    wire [31:0] dmem_addr, dmem_wdata, dmem_rdata;
    wire [3:0]  dmem_we;
    wire        dmem_re;
    wire        halted, retire, st_lu, st_md, st_fl;

    rv32im_core u_core (
        .clk(clk), .rst(rst),
        .imem_addr(imem_addr), .imem_rdata(imem_rdata),
        .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata), .dmem_we(dmem_we),
        .dmem_re(dmem_re), .dmem_rdata(dmem_rdata),
        .halted(halted), .retire(retire),
        .stat_load_use(st_lu), .stat_md_stall(st_md), .stat_flush(st_fl)
    );

    imem #(.WORDS(IMEM_WORDS), .INIT_FILE("")) u_imem (.addr(imem_addr), .rdata(imem_rdata));
    dmem #(.WORDS(DMEM_WORDS), .INIT_FILE("")) u_dmem (.clk(clk), .addr(dmem_addr),
                                                       .wdata(dmem_wdata), .we(dmem_we),
                                                       .rdata(dmem_rdata));

    // ------------------------------------------------------------- statistics
    integer cycles = 0, retired = 0, n_lu = 0, n_md = 0, n_fl = 0;
    always @(posedge clk) if (!rst) begin
        cycles <= cycles + 1;
        if (retire) retired <= retired + 1;
        if (st_lu)  n_lu    <= n_lu + 1;
        if (st_md)  n_md    <= n_md + 1;
        if (st_fl)  n_fl    <= n_fl + 1;
    end

    // ------------------------------------------------------------- pipeline trace
    // +TRACE prints one line per cycle (see tools/pipeline_trace.py):
    //   TRACE cycle if_pc id_valid id_pc ex_valid ex_pc md_busy load_use_stall taken
    reg trace_en = 0;
    always @(posedge clk) if (trace_en && !rst && cycles < MAX_CYCLES)
        $display("TRACE %0d %08x %0d %08x %0d %08x %0d %0d %0d",
                 cycles, u_core.pc,
                 u_core.if_id_valid, u_core.if_id_pc,
                 u_core.id_ex_valid, u_core.id_ex_pc,
                 st_md, st_lu, st_fl);

    // ------------------------------------------------------------- run control
    reg [8*1024-1:0] fname;            // room for paths up to 1024 characters
    integer i;

    initial begin
        #1;
        if ($value$plusargs("IMEM=%s", fname)) $readmemh(fname, u_imem.mem);
        else                                   $readmemh("imem.hex", u_imem.mem);
        if ($value$plusargs("DMEM=%s", fname)) $readmemh(fname, u_dmem.mem);
        else                                   $readmemh("dmem.hex", u_dmem.mem);
        if ($test$plusargs("TRACE")) trace_en = 1;
        if ($value$plusargs("VCD=%s", fname)) begin
            $dumpfile(fname);
            $dumpvars(0, tb_core);
        end

        repeat (4) @(posedge clk);
        #1 rst = 0;

        while (!halted && cycles < MAX_CYCLES) @(posedge clk);
        repeat (8) @(posedge clk);          // let older instructions drain through WB

        if (!halted) $display("TIMEOUT");
        $display("CYCLES %0d", cycles);
        $display("RETIRED %0d", retired);
        $display("LOADUSE_STALLS %0d", n_lu);
        $display("MD_STALLS %0d", n_md);
        $display("TAKEN_CTRL %0d", n_fl);
        for (i = 0; i < 32; i = i + 1)
            $display("REG %0d %08x", i, u_core.u_rf.regs[i]);
        for (i = 0; i < DUMP_WORDS; i = i + 1)
            $display("MEM %0d %08x", i, u_dmem.mem[i]);
        $display("DONE");
        $finish;
    end
endmodule
