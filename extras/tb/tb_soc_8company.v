`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_soc_8company.v : full-system test of soc_top with N engines (default 8 companies).
//
//   Chain under test (all real RTL, real firmware on the RV32IM core):
//     uart_rx -> tick_parser -> hft_mmio -> {CPU/firmware, N trading engines, hft_alloc} -> uart_tx report
//
//   Differences to tb_hft.v (which instantiates soc_top with its default HFT_N_MAX = 2):
//     * HFT_N_MAX is a parameter of this testbench (-P tb_soc_8company.N=8) and is passed to soc_top,
//     * every stimulus line carries a FAULT column that injects serial-line faults,
//     * a CPU reset can be applied in the middle of a packet or while a packet is processed,
//     * the hft_mmio error counters are printed (COUNTERS lines).
//
//   +TICKS=<file>: lines "<id hex> <price> <vol> <kill> <fault>"
//     fault 0        normal packet; the testbench waits for the 40-byte report
//     fault 1..12    byte (fault-1) of the packet gets a stop-bit glitch (framing error); the testbench
//                    does NOT wait (no report exists) and the next line follows immediately
//     fault 13..23   packet truncated after (fault-12) bytes, then an idle gap longer than the parser's
//     fault 30       CPU reset in the middle of the packet (after 6 bytes)
//     fault 31       CPU reset while the packet is being processed (firmware busy)
//     fault 40       no packet: print the hft_mmio error counters now (COUNTERS line)
//   +NOWAIT=k: from line k on packets are streamed back to back without waiting (flow-control stress)
//   +IMEM= / +DMEM=: firmware images (hex)
//
//   Output lines (parsed by tools/check_soc8.py):
//     REPORT id price vol hwdec hwlat swdec swlat hwpos      one per 40-byte report
//     COUNTERS ferr abort timeout overrun bad engdrop         before every reset and at the end
//     RESET n                                                   a CPU reset was applied (fault 30/31)
//     OVERRUN n LED hex SENT n / DONE ...
// -----------------------------------------------------------------------------
module tb_soc_8company #(parameter N = 8, parameter BIT = 16);
    reg         clk = 0;
    reg         cpu_resetn = 0;
    reg  [15:0] sw = 16'h0000;
    reg         rx_line = 1'b1;
    wire        tx_line;
    wire [15:0] led;
    wire [6:0]  seg;
    wire        dp;
    wire [7:0]  an;

    always #5 clk = ~clk;

    soc_top #(.IMEM_INIT(""), .DMEM_INIT(""), .SEG_REFRESH_BITS(4), .UART_CLKS_PER_BIT(BIT),
              .HFT_N_MAX(N)) u_soc (
        .clk(clk), .cpu_resetn(cpu_resetn), .sw(sw),
        .led(led), .seg(seg), .dp(dp), .an(an),
        .uart_rx(rx_line), .uart_tx(tx_line)
    );

    // ------------------------------------------------------------ PC -> FPGA
    task send_byte(input [7:0] b, input glitch);
        integer i;
        begin
            rx_line = 1'b0; repeat (BIT) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin rx_line = b[i]; repeat (BIT) @(posedge clk); end
            if (!glitch) begin
                rx_line = 1'b1; repeat (BIT) @(posedge clk);
            end else begin                               // stop bit pulled low around the sampling point
                rx_line = 1'b1; repeat (BIT / 4) @(posedge clk);
                rx_line = 1'b0; repeat (BIT / 2) @(posedge clk);
                rx_line = 1'b1; repeat (BIT - BIT / 4 - BIT / 2) @(posedge clk);
            end
        end
    endtask

    reg [7:0] pk [0:11];
    task send_packet(input [31:0] id, input [31:0] price, input [31:0] vol, input integer nbytes, input integer bad_byte);
        integer i;
        begin
            {pk[3], pk[2], pk[1], pk[0]}     = id;
            {pk[7], pk[6], pk[5], pk[4]}     = price;
            {pk[11], pk[10], pk[9], pk[8]}   = vol;
            for (i = 0; i < nbytes; i = i + 1) send_byte(pk[i], i == bad_byte);
        end
    endtask

    // ------------------------------------------------------------ FPGA -> PC
    reg [7:0] rbuf [0:39];
    reg [7:0] bbuf [0:32767];
    integer   rcount = 0;
    integer   total_bytes = 0;
    time      t_sent = 0, t_first = 0, t_last = 0;       // ns: end of the packet's last stop bit; first / last report byte
    always begin : uart_monitor
        integer i;
        reg [7:0] b;
        @(negedge tx_line);
        if (rcount == 0) t_first = $time;
        repeat (BIT / 2) @(posedge clk);
        if (tx_line == 1'b0) begin
            for (i = 0; i < 8; i = i + 1) begin repeat (BIT) @(posedge clk); b[i] = tx_line; end
            repeat (BIT) @(posedge clk);
            if (rcount < 40) rbuf[rcount] = b;
            if (total_bytes < 32768) bbuf[total_bytes] = b;
            rcount = rcount + 1;
            total_bytes = total_bytes + 1;
            t_last = $time;
        end
    end
    function [31:0] word(input integer k);
        word = {rbuf[4*k+3], rbuf[4*k+2], rbuf[4*k+1], rbuf[4*k]};
    endfunction
    function [31:0] bword(input integer base, input integer k);
        bword = {bbuf[base+4*k+3], bbuf[base+4*k+2], bbuf[base+4*k+1], bbuf[base+4*k]};
    endfunction

    task counters(input integer dummy);
        begin
            $display("COUNTERS %0d %0d %0d %0d %0d %0d", u_soc.u_hft_mmio.frame_err_cnt, u_soc.u_hft_mmio.pkt_abort_cnt,
                     u_soc.u_hft_mmio.pkt_timeout_cnt, u_soc.u_hft_mmio.overrun_cnt, u_soc.u_hft_mmio.bad_sym_cnt,
                     u_soc.u_hft_mmio.eng_drop_cnt);
        end
    endtask

    task board_reset(input integer id);
        begin
            counters(0);
            cpu_resetn = 0; repeat (20) @(posedge clk); cpu_resetn = 1;
            repeat (30000) @(posedge clk);                // the firmware restarts and configures itself
            rcount = 0;
            $display("RESET %0d", id);
        end
    endtask

    // ------------------------------------------------------------ stimulus
    reg [8*1024-1:0] fname;
    integer fd, n, price, vol, kill, fault, t, ntick = 0, bad = 0, nresets = 0;
    integer nowait = 1000000, bstart = 0, nburst = 0, f, base;
    reg [31:0] id;
    initial begin
        #1;
        if ($value$plusargs("IMEM=%s", fname)) $readmemh(fname, u_soc.u_imem.mem);
        if ($value$plusargs("DMEM=%s", fname)) $readmemh(fname, u_soc.u_dmem.mem);
        if (!$value$plusargs("TICKS=%s", fname)) begin $display("need +TICKS="); $finish; end
        if (!$value$plusargs("NOWAIT=%d", nowait)) nowait = 1000000;
        fd = $fopen(fname, "r");
        #40 cpu_resetn = 1;
        repeat (30000) @(posedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %d %d %d %d\n", id, price, vol, kill, fault);
            if (n == 5) begin
                sw[0] = kill[0];
                if (ntick >= nowait) begin
                    if (nburst == 0) bstart = total_bytes;
                    send_packet(id, price, vol, 12, -1);
                    nburst = nburst + 1;
                end else if (fault >= 1 && fault <= 12) begin
                    send_packet(id, price, vol, 12, fault - 1);          // framing error, no report
                end else if (fault >= 13 && fault <= 23) begin
                    send_packet(id, price, vol, fault - 12, -1);         // truncated
                    repeat (700 * BIT) @(posedge clk);                    // idle gap > parser gap (576 bit times)
                end else if (fault == 40) begin
                    counters(0);                                          // no packet: print the error counters now
                end else if (fault == 30) begin
                    send_packet(id, price, vol, 6, -1);
                    nresets = nresets + 1; board_reset(nresets);
                end else if (fault == 31) begin
                    send_packet(id, price, vol, 12, -1);
                    repeat (300) @(posedge clk);
                    nresets = nresets + 1; board_reset(nresets);
                end else begin
                    rcount = 0;
                    send_packet(id, price, vol, 12, -1);
                    t_sent = $time;
                    t = 0;
                    while (rcount < 40 && t < 400000) begin @(posedge clk); t = t + 1; end
                    repeat (4 * BIT) @(posedge clk);
                    if (rcount != 40) begin
                        $display("TICK %h NOREPORT bytes=%0d", id, rcount); bad = bad + 1;
                    end else if (word(0) != 32'hAA55AA55 || word(9) != 32'h55AA55AA) begin
                        $display("TICK %h BADFRAME %h %h", id, word(0), word(9)); bad = bad + 1;
                    end else begin
                        $display("REPORT %h %0d %0d %0d %0d %0d %0d %0d", word(1), word(2), word(3), word(4), word(5), word(6), word(7), word(8));
                        // cycles from the end of the packet's last stop bit to the first / last byte of its report
                        $display("E2E %h %0d %0d", word(1), (t_first - t_sent) / 10, (t_last - t_sent) / 10);
                    end
                end
                ntick = ntick + 1;
            end
        end
        if (nburst > 0) begin
            repeat (600000) @(posedge clk);
            for (f = 0; f < (total_bytes - bstart) / 40; f = f + 1) begin
                base = bstart + 40 * f;
                if (bword(base, 0) != 32'hAA55AA55 || bword(base, 9) != 32'h55AA55AA) begin
                    $display("TICK BURST%0d BADFRAME %h %h", f, bword(base, 0), bword(base, 9)); bad = bad + 1;
                end else begin
                    $display("BREPORT %h %0d %0d %0d %0d %0d %0d %0d", bword(base, 1), bword(base, 2), bword(base, 3),
                             bword(base, 4), bword(base, 5), bword(base, 6), bword(base, 7), bword(base, 8));
                end
            end
            if ((total_bytes - bstart) % 40 != 0) begin
                $display("TICK BURST PARTIAL bytes=%0d", (total_bytes - bstart) % 40); bad = bad + 1;
            end
        end
        repeat (2000) @(posedge clk);
        counters(0);
        $display("NMAX %0d", N);
        $display("OVERRUN %0d LED %h SENT %0d", u_soc.u_hft_mmio.overrun_cnt, led, ntick);
        $display("DONE ticks=%0d bad_frames=%0d total_tx_bytes=%0d resets=%0d", ntick, bad, total_bytes, nresets);
        $finish;
    end
endmodule
