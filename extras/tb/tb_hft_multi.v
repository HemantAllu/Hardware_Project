`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_hft_multi.v : random test of hft_multi.v (N_MAX engines + one shared cash account),
//                  no CPU, no UART.  Checked by tools/check_multi.py against MultiModel.
//   ops file, 5 integers per line "<op> a b c d":
//     0 sym price vol kill      stage one tick for company `sym` in the current group
//     3 wait 0 0 0              fire every staged tick in the SAME clock cycle, then wait
//                               `wait` cycles (the generator never sends a tick to a busy engine)
//     1 cash_hi cash_lo 0 0     set the shared starting cash and pulse `clear`
//     2 sym limit brk_high brk_low   configure one company
//     4 sym cap_hi cap_lo 0     cash cap of one company (0 = no cap)
//   log lines (in time order): TICK sym price vol kill | OP ... | DEC sym dec lat pos inv held |
//                              CASH value   (CASH once per cycle in which any engine decided)
//   held = cycles that engine waited in S4 for the shared cash unit (one request per cycle);
//   the checker requires lat == 5 + held.
//   run: vvp tb_hft_multi.vvp +OPS=ops.txt          (N_MAX set with iverilog -P tb_hft_multi.N=..)
// -----------------------------------------------------------------------------
module tb_hft_multi;
    parameter N = 2;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, clear = 0, kill = 0;

    reg  [N-1:0]    tv = 0;
    reg  [32*N-1:0] price = 0, vol = 0;
    reg  [32*N-1:0] lim, bh, bl;
    reg  [64*N-1:0] cap = 0;
    reg  [63:0]     cash0 = 64'd1000000;

    wire [32*N-1:0] dec, lat, pos;
    wire [64*N-1:0] inv;
    wire [N-1:0]    dv;
    wire [63:0]     cash;

    hft_multi #(.N_MAX(N)) u (
        .clk(clk), .rst(rst), .clear(clear), .kill_switch(kill), .alloc_kill_sw(kill),
        .tick_valid(tv), .tick_price(price), .tick_vol(vol),
        .cfg_pos_limit(lim), .cfg_brk_high(bh), .cfg_brk_low(bl), .cfg_cash_cap(cap),
        .cfg_starting_cash(cash0),
        .port_mode(1'b0), .rank_en(1'b0), .rot_en(1'b0), .rw_en(1'b0), .nsym(4'd1), .max_lots(32'd0),
        .min_hold(8'd0), .margin(32'd0), .wshift(5'd0), .wfloor(16'd0), .capshift(5'd0), .alloc_start(1'b0),
        .decision(dec), .latency_cycles(lat), .decision_valid(dv), .position(pos),
        .invested(inv), .cash(cash));

    integer e, ndec = 0, same_cycle = 0, held_cycles = 0;
    integer held [0:N-1];
    initial for (e = 0; e < N; e = e + 1) held[e] = 0;
    // count, per engine, the cycles it waits in S4 for the cash unit (sampled mid-cycle)
    integer h;
    always @(negedge clk)
        for (h = 0; h < N; h = h + 1)
            if (u.hold_req[h]) begin held[h] = held[h] + 1; held_cycles = held_cycles + 1; end
    always @(posedge clk) begin
        #1;
        if (|dv) begin
            for (e = 0; e < N; e = e + 1)
                if (dv[e]) begin
                    $display("DEC %0d %0d %0d %0d %0d %0d", e, dec[32*e +: 32], lat[32*e +: 32], pos[32*e +: 32],
                             $signed(inv[64*e +: 64]), held[e]);
                    held[e] = 0;
                    ndec = ndec + 1;
                end
            if (dv & (dv - 1)) same_cycle = same_cycle + 1;     // two or more engines decided together
            $display("CASH %0d", cash);
        end
    end

    reg [8*1024-1:0] fname;
    integer fd, n, op, a, b, c, d, s;
    reg [N-1:0] staged = 0;

    initial begin
        for (s = 0; s < N; s = s + 1) begin
            lim[32*s +: 32] = 1000; bh[32*s +: 32] = 150; bl[32*s +: 32] = 50;
        end
        if (!$value$plusargs("OPS=%s", fname)) begin $display("need +OPS="); $finish; end
        fd = $fopen(fname, "r");
        repeat (4) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%d %d %d %d %d\n", op, a, b, c, d);
            if (n == 5) begin
                case (op)
                    0: begin
                        price[32*a +: 32] = b; vol[32*a +: 32] = c; kill = d[0];
                        staged[a] = 1'b1;
                        $display("TICK %0d %0d %0d %0d", a, b, c, d);
                    end
                    3: begin
                        tv <= staged; @(posedge clk); tv <= 0; staged = 0;
                        repeat (a) @(posedge clk);
                    end
                    1: begin
                        cash0 = {a[31:0], b[31:0]};
                        $display("OP CASH %0d", cash0);
                        @(posedge clk); clear <= 1; @(posedge clk); clear <= 0; repeat (3) @(posedge clk);
                    end
                    2: begin
                        lim[32*a +: 32] = b; bh[32*a +: 32] = c; bl[32*a +: 32] = d;
                        $display("OP CFG %0d %0d %0d %0d", a, b, c, d);
                        repeat (2) @(posedge clk);
                    end
                    4: begin
                        cap[64*a +: 64] = {b[31:0], c[31:0]};
                        $display("OP CAP %0d %0d", a, {b[31:0], c[31:0]});
                        repeat (2) @(posedge clk);
                    end
                    default: ;
                endcase
            end
        end
        repeat (20) @(posedge clk);
        $display("DONE decided=%0d same_cycle_groups=%0d held_cycles=%0d", ndec, same_cycle, held_cycles);
        $finish;
    end
endmodule
