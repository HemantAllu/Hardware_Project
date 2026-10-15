`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// hft_accelerator.v : tick-based trading decision engine (MA, VWAP, breakout,
//                     2-of-3 vote, risk interlock).  Latency: 5 clock cycles
//                     from tick_valid (data_valid) to decision_valid.
//
//   cycle T   (S0) accept tick; MA sum; shift price history
//   cycle T+1 (S1) price*vol; volume sum; MA and breakout votes
//   cycle T+2 (S2) PV sum; price*volume_sum            (multiplier only)
//   cycle T+3 (S3) VWAP compare; commit the running sums
//   cycle T+4 (S4) vote, risk interlock, position + cash update -> decision_valid at T+5
//
//   decision: 0 = NO ACTION, 1 = BUY, 2 = SELL
//   latency_cycles is measured by a counter, not a constant.
//   Notes
//   * MA votes only after 3 earlier ticks (no false signals while warming up).
//   * The MA vote compares 4*price with the exact sum of the last four prices
//     (no rounding of the average), so BUY = price above the true average.
//   * The running volume sum is 32 bits (4.29e9 lots), the price*volume sum 64 bits.  If
//     either would overflow, the VWAP rule is switched off (vwap_sat, sticky until clear):
//     from that tick on it votes neither BUY nor SELL and the sums stop changing, so a
//     wrapped sum can never produce a wrong vote (v11 wrapped silently).  The firmware and
//     hft_model.py do exactly the same.
//   * A tick that arrives while the engine is busy is held in a 1-entry buffer.
//     If yet another tick arrives while that buffer is full, the NEW tick is dropped
//     (the waiting one is kept, so ticks are never processed out of order) and
//     tick_dropped pulses; hft_mmio counts the drops (ENG_DROP).  v11 overwrote the
//     waiting tick silently.  On the board this cannot happen: hft_mmio forwards a
//     tick only after the CPU has read the previous result.
//   * kill_switch is an asynchronous board input: it is synchronised here.
//   * clear (from the CTRL register) restarts the strategy without a board reset.
//   * Risk interlock (no borrowing): a BUY needs position+volume <= POS_LIMIT and
//     cash >= price*volume; a SELL needs position >= volume; a tick with volume 0
//     never trades.  The trade value price*volume is the registered product l_pv
//     computed in S1 (no second multiplier in the S4 timing path).
//   * EXT_CASH = 1 (multi-company build, hft_multi.v): the cash account is NOT kept
//     here but in a shared cash unit.  In S4 the engine raises s4_buy_req (the vote
//     is BUY and every local check passed: kill switch, volume, position limit) or
//     s4_sell (a SELL that will happen), with s4_cost = price*volume, and takes the
//     shared unit's ext_buy_grant (enough shared cash, within this company's cap) in
//     place of its own cash check.  Everything else, including the 5-cycle latency,
//     is identical.  EXT_CASH = 0 (default) is the original single-company engine.
//   * ext_hold (EXT_CASH = 1 only): the shared cash unit serves ONE cash request per
//     cycle.  While ext_hold is high the engine stays in S4 without committing (no
//     decision, no position change); it commits in the first cycle ext_hold is low.
//     latency_cycles then includes the wait (5 + cycles held).  With one tick per UART
//     packet two engines are never in S4 together, so on the board ext_hold is never
//     set and the latency is always 5.
// -----------------------------------------------------------------------------
module hft_accelerator #(
    parameter EXT_CASH = 0
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        clear,          // one-cycle pulse: back to the reset state (new run)

    input  wire        tick_valid,
    input  wire [31:0] tick_id,
    input  wire [31:0] tick_price,
    input  wire [31:0] tick_vol,

    input  wire        kill_switch,
    input  wire [31:0] config_pos_limit,
    input  wire [31:0] config_breakout_high,
    input  wire [31:0] config_breakout_low,
    // Cash is denominated in price-times-lot units.  It is reset on clear.
    input  wire [63:0] config_starting_cash,

    output reg  [31:0] decision,
    output reg  [31:0] latency_cycles,
    output reg         decision_valid,
    output reg         tick_dropped,   // one-cycle pulse: a tick was lost (buffer full)
    output reg         vwap_sat,       // VWAP sums would have overflowed: VWAP rule off until clear
    output reg  [31:0] current_position,
    output reg  [63:0] current_cash,

    // shared-cash interface (used only when EXT_CASH = 1)
    input  wire        ext_buy_grant,
    input  wire        ext_hold,       // shared cash unit busy with another engine: wait in S4
    output wire        s4_buy_req,
    output wire        s4_sell,
    output wire [63:0] s4_cost,

    // portfolio mode (hft_alloc.v): the raw 2-of-3 vote and the inputs of the momentum score,
    // valid with decision_valid and stable until the next tick starts
    output reg  [1:0]  vote_out,
    output wire [31:0] tick_price_out,
    output wire [31:0] tick_vol_out,
    output wire [33:0] ma_sum_out,
    output wire        ma_ok_out
);
    localparam S0 = 3'd0, S1 = 3'd1, S2 = 3'd2, S3 = 3'd3, S4 = 3'd4;
    reg [2:0] state;

    // free-running cycle counter used to time each tick
    reg [31:0] cyc;
    reg [31:0] t_start;

    // 1-entry input buffer for a tick that arrives while busy
    reg        pend_v;
    reg [31:0] pend_price, pend_vol, pend_t;

    // kill switch synchroniser (2 flip-flops; ASYNC_REG keeps them together in Vivado)
    (* ASYNC_REG = "TRUE" *) reg kill_s1;
    (* ASYNC_REG = "TRUE" *) reg kill_s2;

    // price history (previous three prices) and warm-up count
    reg [31:0] p0, p1, p2;
    reg [1:0]  warm;                 // earlier ticks seen, saturates at 3

    // running VWAP sums
    reg [63:0] acc_pv;
    reg [31:0] acc_v;

    // pipeline latches
    reg [31:0] l_price, l_vol;
    reg [33:0] l_ma_sum;
    reg        l_ma_ok;
    reg [63:0] l_pv;
    reg [32:0] l_acc_v_next;           // bit 32 = the 32-bit volume sum would overflow
    reg [64:0] l_acc_pv_next;          // bit 64 = the 64-bit price*volume sum would overflow
    reg [63:0] l_p_x_v;
    reg        ma_buy, ma_sell, brk_buy, brk_sell, vwap_buy, vwap_sell;

    wire        start      = (state == S0) && (pend_v || tick_valid);
    wire [31:0] in_price   = pend_v ? pend_price : tick_price;
    wire [31:0] in_vol     = pend_v ? pend_vol   : tick_vol;
    wire [31:0] in_t       = pend_v ? pend_t     : cyc;
    wire [33:0] l_price4   = {l_price, 2'b00};          // 4 * price, exact (compared with the sum of 4 prices)

    // decision logic for S4
    wire [1:0]  buy_votes  = ma_buy  + vwap_buy  + brk_buy;
    wire [1:0]  sell_votes = ma_sell + vwap_sell + brk_sell;
    wire [1:0]  vote       = (buy_votes >= 2) ? 2'd1 : (sell_votes >= 2) ? 2'd2 : 2'd0;
    wire [32:0] pos_after_buy = {1'b0, current_position} + {1'b0, l_vol};
    wire [63:0] trade_cost = l_pv;
    // a SELL credit saturates at 2^64 - 1 instead of wrapping to a small balance (v12)
    wire [64:0] cash_plus  = {1'b0, current_cash} + {1'b0, l_pv};                       // = l_price * l_vol, registered in S1, stable until the next S0
    wire        vol_ok     = (l_vol != 32'd0);           // a zero-volume tick never trades
    wire        pos_ok     = (pos_after_buy <= {1'b0, config_pos_limit});
    wire        cash_ok    = EXT_CASH ? ext_buy_grant : (current_cash >= trade_cost);
    wire        buy_ok     = vol_ok && pos_ok && cash_ok;
    wire        sell_ok    = vol_ok && (current_position >= l_vol);

    // S4 requests to the shared cash unit (EXT_CASH = 1)
    assign s4_buy_req = (state == S4) && !kill_s2 && (vote == 2'd1) && vol_ok && pos_ok;
    assign s4_sell    = (state == S4) && !kill_s2 && (vote == 2'd2) && sell_ok;
    assign s4_cost    = trade_cost;
    assign tick_price_out = l_price;
    assign tick_vol_out   = l_vol;
    assign ma_sum_out     = l_ma_sum;
    assign ma_ok_out      = l_ma_ok;
    wire [1:0]  final_dec  = kill_s2               ? 2'd0 :
                             (vote == 2'd1 && buy_ok)  ? 2'd1 :
                             (vote == 2'd2 && sell_ok) ? 2'd2 : 2'd0;

    always @(posedge clk) begin
        if (rst || clear) begin
            state <= S0;
            cyc <= 0; t_start <= 0;
            pend_v <= 1'b0; pend_price <= 0; pend_vol <= 0; pend_t <= 0;
            kill_s1 <= 1'b0; kill_s2 <= 1'b0;
            p0 <= 0; p1 <= 0; p2 <= 0; warm <= 0;
            acc_pv <= 0; acc_v <= 0;
            l_price <= 0; l_vol <= 0; l_ma_sum <= 0; l_ma_ok <= 1'b0;
            l_pv <= 0; l_acc_v_next <= 0; l_acc_pv_next <= 0; l_p_x_v <= 0;
            ma_buy <= 0; ma_sell <= 0; brk_buy <= 0; brk_sell <= 0; vwap_buy <= 0; vwap_sell <= 0;
            decision <= 0; latency_cycles <= 0; decision_valid <= 1'b0; current_position <= 0; vote_out <= 2'd0;
            tick_dropped <= 1'b0;
            vwap_sat <= 1'b0;
            current_cash <= EXT_CASH ? 64'd0 : config_starting_cash;
        end else begin
            cyc            <= cyc + 32'd1;
            kill_s1        <= kill_switch;
            kill_s2        <= kill_s1;
            decision_valid <= 1'b0;
            tick_dropped   <= 1'b0;

            // hold a tick that cannot start this cycle; if the buffer is full and is not
            // being emptied this cycle, drop the NEW tick and report it
            if (tick_valid && pend_v && !start) begin
                tick_dropped <= 1'b1;
            end else if (tick_valid && !(start && !pend_v)) begin
                pend_v     <= 1'b1;
                pend_price <= tick_price;
                pend_vol   <= tick_vol;
                pend_t     <= cyc;
            end else if (start && pend_v) begin
                pend_v     <= 1'b0;
            end

            case (state)
                S0: if (start) begin
                    l_price  <= in_price;
                    l_vol    <= in_vol;
                    l_ma_sum <= {2'b0, in_price} + {2'b0, p0} + {2'b0, p1} + {2'b0, p2};
                    l_ma_ok  <= (warm == 2'd3);
                    p0 <= in_price; p1 <= p0; p2 <= p1;
                    if (warm != 2'd3) warm <= warm + 2'd1;
                    t_start  <= in_t;
                    state    <= S1;
                end
                S1: begin
                    l_pv         <= l_price * l_vol;
                    l_acc_v_next <= {1'b0, acc_v} + {1'b0, l_vol};
                    ma_buy       <= l_ma_ok && (l_price4 > l_ma_sum);
                    ma_sell      <= l_ma_ok && (l_price4 < l_ma_sum);
                    brk_buy      <= (l_price > config_breakout_high);
                    brk_sell     <= (l_price < config_breakout_low);
                    state        <= S2;
                end
                S2: begin
                    l_acc_pv_next <= {1'b0, acc_pv} + {1'b0, l_pv};
                    l_p_x_v       <= l_price * l_acc_v_next[31:0];
                    state         <= S3;
                end
                S3: begin
                    if (vwap_sat || l_acc_v_next[32] || l_acc_pv_next[64]) begin
                        vwap_sat  <= 1'b1;                    // overflow: VWAP rule off
                        vwap_buy  <= 1'b0;
                        vwap_sell <= 1'b0;
                    end else begin
                        vwap_buy  <= (l_p_x_v > l_acc_pv_next[63:0]);
                        vwap_sell <= (l_p_x_v < l_acc_pv_next[63:0]);
                        acc_pv    <= l_acc_pv_next[63:0];
                        acc_v     <= l_acc_v_next[31:0];
                    end
                    state     <= S4;
                end
                S4: if (!(EXT_CASH && ext_hold)) begin   // held: stay in S4, commit nothing
                    decision       <= {30'b0, final_dec};
                    vote_out       <= vote;
                    if (final_dec == 2'd1) begin
                        current_position <= current_position + l_vol;
                        if (!EXT_CASH) current_cash <= current_cash - trade_cost;
                    end else if (final_dec == 2'd2) begin
                        current_position <= current_position - l_vol;
                        if (!EXT_CASH) current_cash <= cash_plus[64] ? {64{1'b1}} : cash_plus[63:0];
                    end
                    latency_cycles <= cyc - t_start + 32'd1;   // cycles from data_valid to decision_valid
                    decision_valid <= 1'b1;
                    state          <= S0;
                end
                default: state <= S0;
            endcase
        end
    end
endmodule
