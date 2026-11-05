`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_prof.v : cycle profiler for the trading workload on the RV32IM core.
//   Same set-up as tb_hft.v (soc_top running hft_firmware.c, ticks over the UART), plus
//   counters that attribute every cycle of the software decision (the window between the
//   two reads of the CYCLE register around sw_decide()) to: retired instructions, load-use
//   stalls, MUL/DIV stalls, taken-branch flushes; and count forwarded operands, M ops,
//   loads and stores.  It also time-stamps each tick: accepted -> hardware decision ->
//   CPU sees the tick -> software decision done -> first report byte.
//   Prints "PROF ..." and "TIMELINE ..." (totals) for tools/profile_report.py.
//   run: tools/profile_trading.sh
// -----------------------------------------------------------------------------
module tb_prof;
    localparam BIT = 16;                 // clocks per UART bit in simulation
    reg         clk = 0;
    reg         cpu_resetn = 0;
    reg  [15:0] sw = 16'h0000;
    reg         rx_line = 1'b1;          // PC -> FPGA
    wire        tx_line;                 // FPGA -> PC
    wire [15:0] led;
    wire [6:0]  seg;
    wire        dp;
    wire [7:0]  an;

    always #5 clk = ~clk;

    soc_top #(.IMEM_INIT(""), .DMEM_INIT(""), .SEG_REFRESH_BITS(4), .UART_CLKS_PER_BIT(BIT)) u_soc (
        .clk(clk), .cpu_resetn(cpu_resetn), .sw(sw),
        .led(led), .seg(seg), .dp(dp), .an(an),
        .uart_rx(rx_line), .uart_tx(tx_line)
    );

    // ------------------------------------------------------------ PC -> FPGA
    task send_byte(input [7:0] b);
        integer i;
        begin
            rx_line = 1'b0; repeat (BIT) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin rx_line = b[i]; repeat (BIT) @(posedge clk); end
            rx_line = 1'b1; repeat (BIT) @(posedge clk);
        end
    endtask
    task send_u32(input [31:0] v);
        begin send_byte(v[7:0]); send_byte(v[15:8]); send_byte(v[23:16]); send_byte(v[31:24]); end
    endtask

    // ------------------------------------------------------------ FPGA -> PC
    reg [7:0] rbuf [0:39];              // the report currently being waited for
    reg [7:0] bbuf [0:16383];           // every byte received (for the NOWAIT burst)
    integer   rcount = 0;
    integer   total_bytes = 0;
    always begin : uart_monitor
        integer i;
        reg [7:0] b;
        @(negedge tx_line);
        repeat (BIT / 2) @(posedge clk);
        if (tx_line == 1'b0) begin
            for (i = 0; i < 8; i = i + 1) begin repeat (BIT) @(posedge clk); b[i] = tx_line; end
            repeat (BIT) @(posedge clk);            // stop bit
            if (rcount < 40) rbuf[rcount] = b;
            if (total_bytes < 16384) bbuf[total_bytes] = b;
            rcount = rcount + 1;
            total_bytes = total_bytes + 1;
        end
    end

    function [31:0] word(input integer k);
        word = {rbuf[4*k+3], rbuf[4*k+2], rbuf[4*k+1], rbuf[4*k]};
    endfunction
    function [31:0] bword(input integer base, input integer k);
        bword = {bbuf[base+4*k+3], bbuf[base+4*k+2], bbuf[base+4*k+1], bbuf[base+4*k]};
    endfunction


    // ---------------- profiler: the firmware reads CYCLE (0x2000_0010) just before and just after sw_decide()
    integer in_win = 0, nwin = 0, w_cyc = 0, w_ret = 0, w_lu = 0, w_md = 0, w_fl = 0, w_fwd = 0, w_mops = 0, w_ld = 0, w_st = 0;
    integer t_tick = -1, t_now = 0, n_tk = 0, sum_hw = 0, sum_seen = 0, sum_swdone = 0, sum_tx = 0, waiting_tx = 0;
    always @(posedge clk) begin
        t_now = t_now + 1;
        if (u_soc.dmem_re && u_soc.dmem_addr == 32'h2000_0010) begin
            if (in_win) begin in_win = 0; nwin = nwin + 1; if (t_tick >= 0) sum_swdone = sum_swdone + (t_now - t_tick); end
            else in_win = 1;
        end else if (in_win) begin
            w_cyc = w_cyc + 1;
            if (u_soc.retire) w_ret = w_ret + 1;
            if (u_soc.st_lu) w_lu = w_lu + 1;
            if (u_soc.st_md) w_md = w_md + 1;
            if (u_soc.st_fl) w_fl = w_fl + 1;
            if (u_soc.u_core.id_ex_valid && (u_soc.u_core.fwd_a != 0 || u_soc.u_core.fwd_b != 0)) w_fwd = w_fwd + 1;
            if (u_soc.u_core.md_start && u_soc.u_core.u_md.state == 0) w_mops = w_mops + 1;
            if (u_soc.dmem_re) w_ld = w_ld + 1;
            if (u_soc.dmem_we != 0) w_st = w_st + 1;
        end
        // tick timeline (data ticks only)
        if (u_soc.u_hft_mmio.tick_accept && !u_soc.u_hft_mmio.tick_id[31]) begin t_tick = t_now; n_tk = n_tk + 1; waiting_tx = 1; end
        if (t_tick >= 0 && (|u_soc.u_hft_mmio.f_dv)) sum_hw = sum_hw + (t_now - t_tick);
        if (t_tick >= 0 && u_soc.dmem_re && u_soc.dmem_addr == 32'h3000_000C && u_soc.u_hft_mmio.tick_ready_flag && !u_soc.u_hft_mmio.latched_tick_id[31])
            sum_seen = sum_seen + (t_now - t_tick);
        if (waiting_tx && u_soc.u_hft_mmio.tx_start) begin sum_tx = sum_tx + (t_now - t_tick); waiting_tx = 0; end
    end

    // ------------------------------------------------------------ stimulus
    reg [8*1024-1:0] fname;            // room for paths up to 1024 characters
    integer fd, n, price, vol, kill, t, ntick = 0, bad = 0;
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
        repeat (200) @(posedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %d %d %d\n", id, price, vol, kill);
            if (n == 4) begin
                sw[0] = kill[0];
                if (ntick < nowait) begin
                    rcount = 0;
                    send_u32(id); send_u32(price); send_u32(vol);
                    // wait for the full report (or time out)
                    t = 0;
                    while (rcount < 40 && t < 200000) begin @(posedge clk); t = t + 1; end
                    repeat (4 * BIT) @(posedge clk);    // let any extra byte show up
                    if (rcount != 40) begin
                        $display("TICK %h NOREPORT bytes=%0d", id, rcount); bad = bad + 1;
                    end else if (word(0) != 32'hAA55AA55 || word(9) != 32'h55AA55AA) begin
                        $display("TICK %h BADFRAME %h %h", id, word(0), word(9)); bad = bad + 1;
                    end else begin
                        $display("REPORT %h %0d %0d %0d %0d %0d %0d %0d", word(1), word(2), word(3), word(4), word(5), word(6), word(7), word(8));
                    end
                end else begin
                    // burst: no waiting, the "PC" streams at the full UART rate
                    if (nburst == 0) bstart = total_bytes;
                    send_u32(id); send_u32(price); send_u32(vol);
                    nburst = nburst + 1;
                end
                ntick = ntick + 1;
            end
        end
        if (nburst > 0) begin
            repeat (400000) @(posedge clk);             // let the board finish every report it still owes
            for (f = 0; f < (total_bytes - bstart) / 40; f = f + 1) begin
                base = bstart + 40 * f;
                if (bword(base, 0) != 32'hAA55AA55 || bword(base, 9) != 32'h55AA55AA) begin
                    $display("TICK BURST%0d BADFRAME %h %h", f, bword(base, 0), bword(base, 9)); bad = bad + 1;
                end else begin
                    $display("REPORT %h %0d %0d %0d %0d %0d %0d %0d", bword(base, 1), bword(base, 2), bword(base, 3),
                             bword(base, 4), bword(base, 5), bword(base, 6), bword(base, 7), bword(base, 8));
                end
            end
            if ((total_bytes - bstart) % 40 != 0) begin
                $display("TICK BURST PARTIAL bytes=%0d", (total_bytes - bstart) % 40); bad = bad + 1;
            end
        end
        $display("PROF windows=%0d cycles=%0d retired=%0d loaduse=%0d mdstall=%0d flush=%0d fwd=%0d mops=%0d loads=%0d stores=%0d", nwin, w_cyc, w_ret, w_lu, w_md, w_fl, w_fwd, w_mops, w_ld, w_st);
        $display("TIMELINE ticks=%0d hw_decision=%0d cpu_sees_tick=%0d sw_decision_done=%0d first_report_byte=%0d", n_tk, sum_hw, sum_seen, sum_swdone, sum_tx);
        $display("OVERRUN %0d LED %h SENT %0d", u_soc.u_hft_mmio.overrun_cnt, led, ntick);
        $display("DONE ticks=%0d bad_frames=%0d total_tx_bytes=%0d", ntick, bad, total_bytes);
        $finish;
    end
endmodule
