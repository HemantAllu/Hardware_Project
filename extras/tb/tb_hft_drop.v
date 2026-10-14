`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_hft_drop.v : the engine's 1-entry input buffer (v12).
//   Three ticks in three consecutive cycles: the first starts at once, the second waits in
//   the buffer, the third finds the buffer full and must be DROPPED (tick_dropped pulses);
//   the waiting second tick must NOT be overwritten.  Then two more ticks one cycle apart
//   (buffer used, nothing dropped), and a burst of 5 (3 dropped).
//   Checks: decisions come out in order with the right prices, latency 5 or 5 + wait,
//   number of drops.  Last line "TB_HFT_DROP PASS" or "TB_HFT_DROP FAIL ...".
// -----------------------------------------------------------------------------
module tb_hft_drop;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, tv = 0;
    reg [31:0] price = 0, vol = 0;
    wire [31:0] dec, lat, pos; wire dv, drop;
    wire [63:0] cash;
    wire [1:0] vote; wire [31:0] p_out, v_out; wire [33:0] ms; wire mok;
    hft_accelerator u (
        .clk(clk), .rst(rst), .clear(1'b0), .tick_valid(tv), .tick_id(32'd0),
        .tick_price(price), .tick_vol(vol), .kill_switch(1'b0),
        .config_pos_limit(32'd1000), .config_breakout_high(32'd150), .config_breakout_low(32'd50),
        .config_starting_cash(64'd1000000),
        .decision(dec), .latency_cycles(lat), .decision_valid(dv), .tick_dropped(drop),
        .current_position(pos), .current_cash(cash),
        .ext_buy_grant(1'b0), .ext_hold(1'b0), .s4_buy_req(), .s4_sell(), .s4_cost(),
        .vote_out(vote), .tick_price_out(p_out), .tick_vol_out(v_out), .ma_sum_out(ms), .ma_ok_out(mok));

    integer ndec = 0, ndrop = 0, errs = 0, k;
    reg [31:0] expect_price [0:15];
    integer    expect_lat   [0:15];
    always @(posedge clk) begin
        #1;
        if (drop) ndrop = ndrop + 1;
        if (dv) begin
            if (p_out !== expect_price[ndec] || lat !== expect_lat[ndec]) begin
                errs = errs + 1;
                $display("decision %0d: price %0d lat %0d, expected price %0d lat %0d",
                         ndec, p_out, lat, expect_price[ndec], expect_lat[ndec]);
            end
            ndec = ndec + 1;
        end
    end

    task burst(input integer n, input [31:0] p0);     // n ticks in n consecutive cycles
        integer j;
        begin
            for (j = 0; j < n; j = j + 1) begin
                price <= p0 + j; vol <= 10; tv <= 1; @(posedge clk);
            end
            tv <= 0; repeat (20) @(posedge clk);
        end
    endtask

    initial begin
        // expected decisions (in order): price and latency
        expect_price[0] = 100; expect_lat[0] = 5;      // burst of 3: 100 starts
        expect_price[1] = 101; expect_lat[1] = 9;      //   101 waits 4 cycles in the buffer; 102 dropped
        expect_price[2] = 200; expect_lat[2] = 5;      // burst of 2: both decided
        expect_price[3] = 201; expect_lat[3] = 9;
        expect_price[4] = 300; expect_lat[4] = 5;      // burst of 5: 302, 303, 304 dropped
        expect_price[5] = 301; expect_lat[5] = 9;
        repeat (3) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        burst(3, 100);
        if (ndrop != 1) begin errs = errs + 1; $display("burst 3: %0d drops, expected 1", ndrop); end
        burst(2, 200);
        if (ndrop != 1) begin errs = errs + 1; $display("burst 2: %0d drops in total, expected 1", ndrop); end
        burst(5, 300);
        if (ndrop != 4) begin errs = errs + 1; $display("burst 5: %0d drops in total, expected 4", ndrop); end
        if (ndec != 6) begin errs = errs + 1; $display("%0d decisions, expected 6", ndec); end
        if (errs == 0) $display("TB_HFT_DROP PASS (6 decisions in order, 4 ticks dropped and counted)");
        else           $display("TB_HFT_DROP FAIL %0d errors", errs);
        $finish;
    end
endmodule
