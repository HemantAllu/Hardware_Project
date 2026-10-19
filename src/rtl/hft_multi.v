`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// hft_multi.v : N_MAX independent trading engines (one hft_accelerator per company)
//               that share ONE cash account.
//
//   * Engine i trades company i.  It has its own price history, MA warm-up, VWAP
//     sums, breakout levels, position limit, position and decision; it never sees
//     another company's ticks.  Latency stays 5 cycles per engine, also when ticks
//     for several companies arrive in the same cycle (each engine has its own FSM).
//   * The only shared state is the 64-bit cash register (and the kill switch).
//     In its S4 cycle an engine asks the cash unit for a BUY (s4_buy_req, cost =
//     price*volume) or reports a SELL (s4_sell).  The cash unit serves ONE such request
//     per clock cycle: if several engines want the cash in the same cycle, the lowest
//     index is served and the others wait in S4 (ext_hold) and are served in the next
//     cycles, lowest index first.  Each engine therefore sees the balance left by every
//     engine served before it -- the same result as processing those ticks one at a
//     time in index order (hft_model.py), but with ONE 64-bit compare and ONE 64-bit
//     add/subtract per cycle instead of a chain of N of them (v11 had an N-stage chain
//     that could not meet 100 MHz for N >= 4).  An engine whose vote needs no cash (no
//     action, or blocked by a local check) never waits.  On the board one UART packet
//     carries one tick, so two engines are never in S4 together and no engine ever waits.
//   * Optional per-company cap: invested_i = cost of company i's BUYs minus the
//     proceeds of its SELLs (signed).  With cash_cap_i != 0 a BUY also needs
//     invested_i + cost <= cash_cap_i.  cash_cap_i = 0 means no cap.
//   * rst / clear: every engine restarts, cash <= starting cash, invested <= 0.
//   * Portfolio mode (port_mode = 1, hft_alloc.v): the engines only produce signals; no engine
//     trades by itself (grant = 0, so a BUY never happens and, with position 0, no SELL either).
//     Trades, positions and the shared cash come from the allocator at the end of each minute.
//   * Timing: per cycle one lowest-set-bit select over N requests, an N:1 mux of the
//     64-bit cost, one 64-bit compare and one 64-bit add/subtract, independent of N.
//     invested + cost (for the cap check) is registered one cycle before S4 (cost and
//     invested cannot change in that cycle), so the cap compare starts from registers.
// -----------------------------------------------------------------------------
module hft_multi #(
    parameter N_MAX = 4
)(
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  clear,
    input  wire                  kill_switch,       // engines (hft_mmio: the per-packet kill value)
    input  wire                  alloc_kill_sw,     // allocator (sampled when ALLOCATE starts)

    // one tick input per engine (flattened: engine i uses bits [32*i +: 32])
    input  wire [N_MAX-1:0]      tick_valid,
    input  wire [32*N_MAX-1:0]   tick_price,
    input  wire [32*N_MAX-1:0]   tick_vol,

    // per-company configuration
    input  wire [32*N_MAX-1:0]   cfg_pos_limit,
    input  wire [32*N_MAX-1:0]   cfg_brk_high,
    input  wire [32*N_MAX-1:0]   cfg_brk_low,
    input  wire [64*N_MAX-1:0]   cfg_cash_cap,      // 0 = no cap
    input  wire [63:0]           cfg_starting_cash, // shared, loaded on clear

    // portfolio mode (latched by hft_mmio on clear) and the allocator's settings
    input  wire                  port_mode,
    input  wire                  rank_en,
    input  wire                  rot_en,
    input  wire                  rw_en,
    input  wire [3:0]            nsym,
    input  wire [31:0]           max_lots,
    input  wire [7:0]            min_hold,
    input  wire [31:0]           margin,
    input  wire [4:0]            wshift,
    input  wire [15:0]           wfloor,
    input  wire [4:0]            capshift,
    input  wire                  alloc_start,

    // per-company results
    output wire [32*N_MAX-1:0]   decision,
    output wire [32*N_MAX-1:0]   latency_cycles,
    output wire [N_MAX-1:0]      decision_valid,
    output wire [N_MAX-1:0]      tick_dropped,      // engine i lost a tick (its 1-entry buffer was full)
    output wire [N_MAX-1:0]      vwap_sat,          // engine i: VWAP sums overflowed, VWAP rule off
    output wire [32*N_MAX-1:0]   position,
    output wire [64*N_MAX-1:0]   invested,
    // shared cash
    output wire [63:0]           cash,

    // portfolio mode results
    output wire [2*N_MAX-1:0]    vote,
    output wire [2*N_MAX-1:0]    alloc_codes,
    output wire                  alloc_done,
    output wire [31:0]           alloc_latency,
    output wire [31:0]           alloc_count,
    output wire [32*N_MAX-1:0]   score,
    output wire [16*N_MAX-1:0]   weight,
    output wire [8*N_MAX-1:0]    hold,
    output wire                  scores_ready,
    output wire                  alloc_busy,
    output wire                  alloc_kill
);
    reg  [63:0]         ind_cash;           // independent-mode shared cash
    wire [63:0]         port_cash;
    wire [32*N_MAX-1:0] eng_pos, port_pos, e_price, e_vol;
    wire [34*N_MAX-1:0] e_msum;
    wire [N_MAX-1:0]    e_mok;
    wire [64*N_MAX-1:0] ind_inv, port_inv;
    wire [N_MAX-1:0]    buy_req, sell;
    wire [64*N_MAX-1:0] cost;
    reg  [N_MAX-1:0]    grant;
    reg  [63:0]         inv [0:N_MAX-1];

    genvar g;
    generate
        for (g = 0; g < N_MAX; g = g + 1) begin : eng
            hft_accelerator #(.EXT_CASH(1)) u_eng (
                .clk(clk), .rst(rst), .clear(clear),
                // portfolio mode: a company >= NUM_SYMBOLS is not traded, its ticks are ignored
                .tick_valid(tick_valid[g] & (~port_mode | (g < nsym))), .tick_id(32'd0),
                .tick_price(tick_price[32*g +: 32]), .tick_vol(tick_vol[32*g +: 32]),
                .kill_switch(kill_switch),
                .config_pos_limit(cfg_pos_limit[32*g +: 32]),
                .config_breakout_high(cfg_brk_high[32*g +: 32]),
                .config_breakout_low(cfg_brk_low[32*g +: 32]),
                .config_starting_cash(64'd0),
                .decision(decision[32*g +: 32]),
                .latency_cycles(latency_cycles[32*g +: 32]),
                .decision_valid(decision_valid[g]),
                .tick_dropped(tick_dropped[g]),
                .vwap_sat(vwap_sat[g]),
                .current_position(eng_pos[32*g +: 32]),
                .current_cash(),
                .ext_buy_grant(grant[g]),
                .ext_hold(hold_req[g]),
                .s4_buy_req(buy_req[g]),
                .s4_sell(sell[g]),
                .s4_cost(cost[64*g +: 64]),
                .vote_out(vote[2*g +: 2]),
                .tick_price_out(e_price[32*g +: 32]),
                .tick_vol_out(e_vol[32*g +: 32]),
                .ma_sum_out(e_msum[34*g +: 34]),
                .ma_ok_out(e_mok[g]));
            assign ind_inv[64*g +: 64] = inv[g];
        end
    endgenerate

    // ---------------------------------------------------- cash unit: one request per cycle
    // req   : engines in S4 that need the shared cash (a BUY to check, or a SELL to credit);
    //         none in portfolio mode (the allocator owns the cash there)
    // win   : the lowest-index request (one-hot); every other request waits (hold_req)
    // inv_after_r[i] = invested_i + cost_i, registered every cycle.  In the cycle an engine
    //         is in S4 its cost (registered in S1) and its invested amount (changed only by
    //         its own commit, at least 5 cycles earlier) were already stable one cycle
    //         before, so the register holds exactly invested_i + cost_i.
    wire [N_MAX-1:0] req      = (buy_req | sell) & {N_MAX{~port_mode}};
    wire [N_MAX-1:0] win      = req & (~req + 1'b1);          // lowest set bit
    wire [N_MAX-1:0] hold_req = req & ~win;
    reg  [65:0]      inv_after_r [0:N_MAX-1];
    reg  [N_MAX-1:0] cap_ok_v;
    reg  [63:0]      sel_cost;
    reg              sel_buy, sel_sell, sel_cap_ok;
    integer          i;
    always @(*) begin
        sel_cost = 64'd0; sel_buy = 1'b0; sel_sell = 1'b0; sel_cap_ok = 1'b0;
        for (i = 0; i < N_MAX; i = i + 1) begin
            cap_ok_v[i] = (cfg_cash_cap[64*i +: 64] == 64'd0) ||
                          ($signed(inv_after_r[i]) <= $signed({2'b00, cfg_cash_cap[64*i +: 64]}));
            if (win[i]) begin                                   // one-hot: an AND-OR mux
                sel_cost   = sel_cost | cost[64*i +: 64];
                sel_buy    = sel_buy  | buy_req[i];
                sel_sell   = sel_sell | sell[i];
                sel_cap_ok = sel_cap_ok | cap_ok_v[i];
            end
        end
    end
    wire        afford   = (ind_cash >= sel_cost);
    wire        buy_ok   = sel_buy & afford & sel_cap_ok;
    // a SELL credit saturates at 2^64 - 1 instead of wrapping to a small balance (v12)
    wire [64:0] cash_plus = {1'b0, ind_cash} + {1'b0, sel_cost};
    always @(*) grant = win & buy_req & {N_MAX{afford & sel_cap_ok}};

`ifndef SYNTHESIS
    // the cash unit serves exactly one engine per cycle
    always @(posedge clk) if (!rst && !clear && ((win & (win - 1'b1)) != 0))
        $display("ERROR hft_multi: more than one engine served in one cycle (%b)", win);
`endif

    // ---------------------------------------------------- shared registers
    integer k;
    always @(posedge clk) begin
        for (k = 0; k < N_MAX; k = k + 1)
            inv_after_r[k] <= {{2{inv[k][63]}}, inv[k]} + {2'b00, cost[64*k +: 64]};
        if (rst || clear) begin
            ind_cash <= cfg_starting_cash;
            for (k = 0; k < N_MAX; k = k + 1) inv[k] <= 64'd0;
        end else begin
            if (buy_ok)        ind_cash <= ind_cash - sel_cost;
            else if (sel_sell) ind_cash <= cash_plus[64] ? {64{1'b1}} : cash_plus[63:0];   // saturates
            for (k = 0; k < N_MAX; k = k + 1) begin
                if (grant[k])               inv[k] <= inv[k] + cost[64*k +: 64];
                else if (win[k] && sell[k]) inv[k] <= inv[k] - cost[64*k +: 64];
            end
        end
    end

    // ---------------------------------------------------- portfolio allocator
    hft_alloc #(.N(N_MAX)) u_alloc (
        .clk(clk), .rst(rst), .clear(clear),
        .nsym(nsym), .rank_en(rank_en), .rot_en(rot_en), .rw_en(rw_en),
        .max_lots(max_lots), .min_hold(min_hold), .margin(margin), .wshift(wshift), .wfloor(wfloor),
        .capshift(capshift), .start_cash(cfg_starting_cash), .pos_limit(cfg_pos_limit),
        .kill_switch(alloc_kill_sw),
        .dv(decision_valid), .vote(vote), .price(e_price), .vol(e_vol), .ma_sum(e_msum), .ma_ok(e_mok),
        .start(alloc_start & port_mode),
        .codes(alloc_codes), .done(alloc_done), .latency(alloc_latency), .count(alloc_count),
        .pos_o(port_pos), .inv_o(port_inv), .score_o(score), .weight_o(weight), .hold_o(hold),
        .cash(port_cash), .scores_ready(scores_ready), .busy(alloc_busy),
        .kill_used(alloc_kill));

    assign position = port_mode ? port_pos  : eng_pos;
    assign invested = port_mode ? port_inv  : ind_inv;
    assign cash     = port_mode ? port_cash : ind_cash;
endmodule
