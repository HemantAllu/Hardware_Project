`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// hft_alloc.v : portfolio allocator (rank + rotate + reweight) for N trading engines that
//               share ONE cash account.  Bit-exact reference: extras/hft_model.py PortfolioModel.
//
//   Per minute (bar):
//     * every company's tick runs through its engine (5 cycles) and leaves here a SIGNAL (the
//       2-of-3 vote), the tick price and volume, and the inputs of its momentum SCORE;
//     * a background divider turns those into the score (4*price - S) / S, S = this price + the
//       3 before it, in units of 2^-20 (signed, truncated toward zero; 0 during MA warm-up).
//       It runs after the engine has decided, so the 5-cycle signal latency is untouched;
//     * the ALLOCATE command (end of the minute) starts the allocation FSM:
//         1 SELL    a company with a SELL signal (volume > 0) sells its whole position
//         2 RANK    BUY candidates (BUY signal, qty = min(volume, MAX_LOTS) > 0, pos + qty <=
//                   limit) are served strongest score first, ties to the lower company number
//                   (mode bit RANK = 0: company order)
//         3 BUY     if shared cash >= price*qty and (REWEIGHT off or invested + cost <= cap,
//                   cap = (starting cash * weight) >> CAPSHIFT)
//         4 ROTATE  (once per minute) a BUY refused only for cash sells the held company with the
//                   lowest score among those without a BUY signal, held >= MIN_HOLD minutes and
//                   scoring more than MARGIN below the buyer, if that makes the BUY affordable
//         5 HOLD    every held position counts one more minute (saturating at 255)
//         6 WEIGHTS each position closed this minute, in company order: a win (proceeds >
//                   invested) takes w_j >> k from every other company, a loss gives (w_i >> k)
//                   >> SHARE_SHIFT[n] to every other company; nobody below FLOOR; the weights
//                   always add up to 2^15
//       codes (2 bits per company): 0 none, 1 BUY, 2 SELL, 3 ROT (sold to fund another company).
//     * The kill switch (sampled when ALLOCATE arrives) blocks every trade of that minute.
//   Ticks must not arrive while an allocation runs (the PC waits for every report; hft_mmio.v
//   does not pass a tick to the engines while the allocator is busy).
//   Timing (100 MHz): one 32x32 multiplier with two pipeline registers, one 64x16 multiplier
//   followed by a registered barrel shift, a bit-serial divider (one 35-bit subtract per cycle);
//   a sum that feeds a compare is registered one state earlier, so no cycle has more than one
//   65/80-bit carry chain.  Allocation latency is measured (ALLOC_LAT).
//   Latency (v12): every loop ends at NUM_SYMBOLS (not at N), picking the next buyer or the
//   rotation victim takes ONE cycle (a registered pairwise score-comparison matrix), and a
//   win/loss reweight updates all weights at once.  With n = NUM_SYMBOLS, s sells, b BUY
//   candidates served, c positions closed with a win or a loss, v rotation searches that
//   found a victim and f searches that found none:
//       cycles = 8 + 2n + 3s + 5b + 2c + 5v + f   (REWEIGHT on; 7 + n + 3s + 5b + 5v + f off)
//              + cycles spent in S_WAIT for scores still being divided (1 on the board: the
//                firmware only answers a tick after its score is done)
//   Per company at most 10 (a BUY refused for cash plus a rotation search with a victim) or 5
//   (a sell that closes a position), so cycles <= 8 + 12n  (= 104 for n = 8; 32 for n = 2).
//   Measured, n = 8: 24 with no trade, 64 with eight BUYs, 64 with eight losing SELLs
//   (v11 looped over all N slots with sequential scans: 32 / 136 / 136 cycles).
//   S_WAIT is 1 cycle on the board (the firmware only answers a tick once its score is done).
// -----------------------------------------------------------------------------
module hft_alloc #(
    parameter N = 2
)(
    input  wire              clk,
    input  wire              rst,
    input  wire              clear,
    input  wire [3:0]        nsym,          // companies traded (1..N)
    input  wire              rank_en,
    input  wire              rot_en,
    input  wire              rw_en,
    input  wire [31:0]       max_lots,      // 0 = whole bar volume
    input  wire [7:0]        min_hold,
    input  wire [31:0]       margin,
    input  wire [4:0]        wshift,
    input  wire [15:0]       wfloor,
    input  wire [4:0]        capshift,      // loaded on clear
    input  wire [63:0]       start_cash,    // loaded on clear
    input  wire [32*N-1:0]   pos_limit,
    input  wire              kill_switch,

    input  wire [N-1:0]      dv,            // engine decision_valid
    input  wire [2*N-1:0]    vote,
    input  wire [32*N-1:0]   price,
    input  wire [32*N-1:0]   vol,
    input  wire [34*N-1:0]   ma_sum,
    input  wire [N-1:0]      ma_ok,

    input  wire              start,         // ALLOCATE
    output reg  [2*N-1:0]    codes,
    output reg               done,
    output reg  [31:0]       latency,
    output reg  [31:0]       count,         // allocations since clear

    output wire [32*N-1:0]   pos_o,
    output wire [64*N-1:0]   inv_o,
    output wire [32*N-1:0]   score_o,
    output wire [16*N-1:0]   weight_o,
    output wire [8*N-1:0]    hold_o,
    output reg  [63:0]       cash,
    output wire              scores_ready,
    output wire              busy,
    output wire              kill_used      // kill switch as sampled by the last ALLOCATE
);
    localparam [1:0] C_NONE = 2'd0, C_BUY = 2'd1, C_SELL = 2'd2, C_ROT = 2'd3;
    localparam [1:0] O_NONE = 2'd0, O_WIN = 2'd1, O_LOSS = 2'd2;

    // ------------------------------------------------------------ per-company state
    reg [31:0] pos   [0:N-1];
    reg [63:0] inv   [0:N-1];
    reg [15:0] w     [0:N-1];
    reg [7:0]  hold  [0:N-1];
    reg [31:0] lastp [0:N-1];
    reg [31:0] lvol  [0:N-1];
    reg [1:0]  sig   [0:N-1];
    reg        fresh [0:N-1];
    reg [33:0] msum  [0:N-1];
    reg        mok   [0:N-1];
    reg        req   [0:N-1];
    reg signed [31:0] score [0:N-1];
    reg        cand  [0:N-1];
    reg        used  [0:N-1];
    reg [31:0] qty   [0:N-1];
    reg [1:0]  code  [0:N-1];
    reg [1:0]  outc  [0:N-1];

    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : outs
            assign pos_o[32*g +: 32]   = pos[g];
            assign inv_o[64*g +: 64]   = inv[g];
            assign score_o[32*g +: 32] = score[g];
            assign weight_o[16*g +: 16] = w[g];
            assign hold_o[8*g +: 8]    = hold[g];
        end
    endgenerate

    // equal starting weights for nsym companies (exact sum 2^15, remainder to company 0)
    function [15:0] w_base(input [3:0] n);
        case (n)
            4'd1: w_base = 16'd32768;  4'd2: w_base = 16'd16384;  4'd3: w_base = 16'd10922;
            4'd4: w_base = 16'd8192;   4'd5: w_base = 16'd6553;   4'd6: w_base = 16'd5461;
            4'd7: w_base = 16'd4681;   default: w_base = 16'd4096;
        endcase
    endfunction
    function [15:0] w_rem(input [3:0] n);
        case (n)
            4'd3: w_rem = 16'd2;  4'd5: w_rem = 16'd3;  4'd6: w_rem = 16'd2;  4'd7: w_rem = 16'd1;
            default: w_rem = 16'd0;
        endcase
    endfunction
    function [1:0] share_shift(input [3:0] n);     // ceil(log2(n-1))
        case (n)
            4'd3: share_shift = 2'd1;  4'd4: share_shift = 2'd2;  4'd5: share_shift = 2'd2;
            4'd6, 4'd7, 4'd8: share_shift = 2'd3;
            default: share_shift = 2'd0;
        endcase
    endfunction

    // ------------------------------------------------------------ multipliers
    reg  [31:0] m_a, m_b;
    reg  [63:0] m_p1;           // m_a * m_b, pipelined twice (DSP48 MREG/PREG) for 100 MHz:
    reg  [63:0] m_p;            //   valid two cycles after the operands are written
    reg  [64:0] inv_plus_r;     // invested + cost of the BUY being checked (registered, S_BUY_W3)
    reg  [64:0] rot_sum;        // cash + proceeds of the rotation victim  (registered, S_ROT_W3)
    reg  [63:0] c_a;            // starting cash (latched on clear)
    reg  [4:0]  c_sh;           // CAPSHIFT (latched on clear)
    reg  [15:0] c_b;            // weight of the company being bought
    reg  [79:0] c_m;            // c_a * c_b                      (one cycle after c_b; DSP48 cascade)
    reg  [79:0] c_p;            // cap = (start * weight) >> CAPSHIFT (two cycles after c_b)
    reg  [63:0] start_l;

    // ------------------------------------------------------------ score divider
    reg         d_busy;
    reg  [3:0]  d_idx;
    reg  [34:0] d_rem;
    reg  [53:0] d_q;            // dividend shifts out at the top, quotient shifts in at the bottom
    reg  [33:0] d_div;
    reg         d_neg;
    reg  [5:0]  d_cnt;
    reg         d_stale;      // a new tick of the same company arrived during the division
    reg         any_req;
    reg  [3:0]  first_req;
    integer     r;
    always @(*) begin
        any_req = 1'b0;
        first_req = 4'd0;
        for (r = N - 1; r >= 0; r = r - 1)
            if (req[r]) begin any_req = 1'b1; first_req = r; end
    end
    assign scores_ready = !d_busy && !any_req;
    wire [34:0] d_shift = {d_rem[33:0], d_q[53]};
    wire        d_ge    = (d_shift >= {1'b0, d_div});
    wire [35:0] num_f   = {2'b00, lastp[first_req], 2'b00} - {2'b00, msum[first_req]};   // 4*price - S
    wire [33:0] num_mag = num_f[35] ? (~num_f[33:0] + 34'd1) : num_f[33:0];

    // ------------------------------------------------------------ FSM
    localparam S_IDLE = 5'd0, S_WAIT = 5'd1, S_SELL = 5'd2, S_SELL_W = 5'd3, S_SELL_U = 5'd4,
               S_CAND = 5'd5, S_SCAN = 5'd6, S_BUY_W = 5'd7, S_BUY_U = 5'd8, S_VSCAN = 5'd9,
               S_ROT_W = 5'd10, S_ROT_U = 5'd11, S_HOLD = 5'd12, S_WSEL = 5'd13, S_WIN = 5'd14,
               S_LOSS0 = 5'd15, S_LOSS = 5'd16, S_DONE = 5'd17, S_BUY_W2 = 5'd18, S_SELL_W2 = 5'd19,
               S_ROT_W2 = 5'd20, S_BUY_W3 = 5'd21, S_ROT_W3 = 5'd22, S_WIN2 = 5'd23;
    reg  [4:0]  st;
    assign busy = (st != S_IDLE);
    assign kill_used = kill_l;
    reg  [3:0]  i, cur, vbest;
    reg         rotated, kill_l;
    reg  [63:0] cost_r;
    reg  [15:0] share;
    reg  [31:0] cyc, t0;
    (* ASYNC_REG = "TRUE" *) reg kill_s1;
    (* ASYNC_REG = "TRUE" *) reg kill_s2;

    // loops run over the traded companies only: 0 .. ns_eff-1
    localparam [3:0] N4 = N;
    wire [3:0]  ns_eff  = (nsym > N4) ? N4 : nsym;

    // weight a company gives away: w >> K, but it never drops below FLOOR
    function [15:0] take(input [15:0] wv, input [4:0] sh, input [15:0] fl);
        reg [15:0] t0v;
        begin
            t0v  = wv >> sh;
            take = (wv - t0v < fl) ? ((wv > fl) ? wv - fl : 16'd0) : t0v;
        end
    endfunction

    // helpers for the current indices
    wire [15:0] wi      = w[i];
    wire [15:0] ti      = take(wi, wshift, wfloor);
    wire [32:0] pos_after = {1'b0, pos[cur]} + {1'b0, qty[cur]};
    // one carry chain per cycle: the sums are registered one state before they are compared
    wire        cap_ok  = !rw_en || ({15'd0, inv_plus_r} <= c_p);
    // cash credits saturate at 2^64 - 1 instead of wrapping (v12; the model does the same)
    wire [64:0] sell_sum = {1'b0, cash} + {1'b0, m_p};
    wire [64:0] rot_left = rot_sum - {1'b0, cost_r};        // used only when rot_sum >= cost_r

    // ---- one-cycle selection of the next buyer and of the rotation victim
    // beat_r[N*k+j]  : k ranks before j as a BUYER  (higher score; equal score -> lower index)
    // lbeat_r[N*k+j] : k ranks before j as a VICTIM (lower score;  equal score -> lower index)
    // Both are registered every cycle from the scores, which do not change during an allocation
    // (S_WAIT waits for the divider and no tick arrives while the allocator is busy).
    // elig_c[j] : j may be sold to fund `cur` (registered as elig_r; in S_BUY_U, the cycle before
    //             S_VSCAN, cur / cand / pos / hold / scores are already final).
    reg  [N*N-1:0] beat_r, lbeat_r;
    reg  [N-1:0]   elig_r;
    wire [N-1:0]   elig_c;
    genvar ge;
    generate
        for (ge = 0; ge < N; ge = ge + 1) begin : vic
            wire signed [33:0] sdiff = $signed({{2{score[cur][31]}}, score[cur]}) -
                                       $signed({{2{score[ge][31]}}, score[ge]});
            assign elig_c[ge] = (ge < nsym) && (pos[ge] != 32'd0) && !cand[ge] &&
                                (hold[ge] >= min_hold) && (sdiff > $signed({2'b00, margin}));
        end
    endgenerate

    // buyer: among cand & !used, the first in rank order (company order when RANK is off)
    reg  [N-1:0] avail_v, best_oh, vic_oh;
    reg  [3:0]   best_i, vic_i;
    reg          best_any, vic_any, okb, okv;
    integer      ka, ja;
    always @(*) begin
        for (ka = 0; ka < N; ka = ka + 1) avail_v[ka] = cand[ka] && !used[ka];
        best_i = 4'd0; vic_i = 4'd0;
        for (ka = 0; ka < N; ka = ka + 1) begin
            okb = avail_v[ka];
            okv = elig_r[ka];
            for (ja = 0; ja < N; ja = ja + 1) if (ja != ka) begin
                if (rank_en) okb = okb && (!avail_v[ja] || beat_r[N*ka + ja]);
                else         okb = okb && (!avail_v[ja] || (ka < ja));
                okv = okv && (!elig_r[ja] || lbeat_r[N*ka + ja]);
            end
            best_oh[ka] = okb;
            vic_oh[ka]  = okv;
            if (okb) best_i = ka;
            if (okv) vic_i  = ka;
        end
        best_any = |avail_v;
        vic_any  = |elig_r;
    end

    // reweight after a win: what every other traded company gives (all at once)
    reg  [15:0] t_r [0:N-1];
    reg  [15:0] t_sum;
    integer     ks;
    always @(*) begin
        t_sum = 16'd0;
        for (ks = 0; ks < N; ks = ks + 1) t_sum = t_sum + t_r[ks];
    end

    integer k, kk;
    always @(posedge clk) begin
        m_p1 <= m_a * m_b;
        m_p  <= m_p1;
        c_m <= c_a * c_b;
        c_p <= c_m >> c_sh;
        kill_s1 <= kill_switch;
        kill_s2 <= kill_s1;
        elig_r  <= elig_c;
        for (k = 0; k < N; k = k + 1)
            for (kk = 0; kk < N; kk = kk + 1) begin
                beat_r[N*k + kk]  <= (score[k] > score[kk]) || ((score[k] == score[kk]) && (k < kk));
                lbeat_r[N*k + kk] <= (score[k] < score[kk]) || ((score[k] == score[kk]) && (k < kk));
            end
        if (rst || clear) begin
            st <= S_IDLE;
            cash <= start_cash;
            start_l <= start_cash;
            c_a <= start_cash;
            c_sh <= capshift;
            c_b <= 16'd0;
            m_a <= 32'd0; m_b <= 32'd0;
            for (k = 0; k < N; k = k + 1) begin
                pos[k] <= 0; inv[k] <= 0; hold[k] <= 0; lastp[k] <= 0; lvol[k] <= 0; sig[k] <= 0;
                fresh[k] <= 0; msum[k] <= 0; mok[k] <= 0; req[k] <= 0; score[k] <= 0;
                cand[k] <= 0; used[k] <= 0; qty[k] <= 0; code[k] <= 0; outc[k] <= 0; t_r[k] <= 0;
                w[k] <= (k < nsym) ? (w_base(nsym) + ((k == 0) ? w_rem(nsym) : 16'd0)) : 16'd0;
            end
            d_busy <= 1'b0; d_idx <= 0; d_rem <= 0; d_q <= 0; d_div <= 0; d_neg <= 0; d_cnt <= 0; d_stale <= 0;
            codes <= 0; done <= 1'b0; latency <= 0; count <= 0;
            i <= 0; cur <= 0; vbest <= 0; rotated <= 0;
            kill_l <= 0; cost_r <= 0; share <= 0; cyc <= 0; t0 <= 0; inv_plus_r <= 0; rot_sum <= 0;
        end else begin
            cyc  <= cyc + 32'd1;
            done <= 1'b0;

            // ---- capture each engine's result (ticks never overlap an allocation)
            for (k = 0; k < N; k = k + 1)
                if (dv[k]) begin
                    sig[k]   <= vote[2*k +: 2];
                    lastp[k] <= price[32*k +: 32];
                    lvol[k]  <= vol[32*k +: 32];
                    msum[k]  <= ma_sum[34*k +: 34];
                    mok[k]   <= ma_ok[k];
                    fresh[k] <= 1'b1;
                    req[k]   <= 1'b1;
                end

            // ---- background score divider: one company at a time, lowest index first
            if (!d_busy) begin
                if (any_req && !dv[first_req]) begin
                    if (!mok[first_req] || msum[first_req] == 34'd0) begin
                        score[first_req] <= 32'sd0;
                        req[first_req]   <= 1'b0;
                    end else begin
                        d_busy <= 1'b1;
                        d_idx  <= first_req;
                        d_rem  <= 35'd0;
                        d_q    <= {num_mag, 20'd0};
                        d_div  <= msum[first_req];
                        d_neg  <= num_f[35];
                        d_cnt  <= 6'd53;
                        d_stale <= 1'b0;
                    end
                end
            end else begin
                d_rem <= d_ge ? (d_shift - {1'b0, d_div}) : d_shift;
                d_q   <= {d_q[52:0], d_ge};
                d_cnt <= d_cnt - 6'd1;
                if (dv[d_idx]) d_stale <= 1'b1;
                if (d_cnt == 6'd0) begin
                    // d_q after this step = {d_q[52:0], d_ge}: the 54-bit quotient (< 2^23).
                    // If the company ticked again meanwhile, drop this result: its request stays
                    // set and the new tick is divided next.
                    if (!d_stale && !dv[d_idx]) begin
                        score[d_idx] <= d_neg ? -$signed({1'b0, d_q[29:0], d_ge}) : $signed({1'b0, d_q[29:0], d_ge});
                        req[d_idx]   <= 1'b0;
                    end
                    d_busy <= 1'b0;
                end
            end

            // ---- allocation FSM
            case (st)
                S_IDLE: if (start) begin
                    t0 <= cyc;
                    kill_l <= kill_s2;
                    for (k = 0; k < N; k = k + 1) begin code[k] <= C_NONE; outc[k] <= O_NONE; end
                    st <= S_WAIT;
                end
                S_WAIT: if (scores_ready) begin
                    i  <= 0;
                    st <= kill_l ? S_HOLD : S_SELL;
                end
                // 1. SELL whole positions
                S_SELL: begin
                    if (i == ns_eff) begin
                        st <= S_CAND;
                    end else if (({1'b0, i} < {1'b0, nsym}) && fresh[i] && sig[i] == 2'd2 && lvol[i] != 32'd0 &&
                                 pos[i] != 32'd0) begin
                        m_a <= pos[i]; m_b <= lastp[i];
                        st <= S_SELL_W;
                    end else begin
                        i <= i + 4'd1;
                    end
                end
                S_SELL_W:  st <= S_SELL_W2;
                S_SELL_W2: st <= S_SELL_U;
                S_SELL_U: begin
                    cash    <= sell_sum[64] ? {64{1'b1}} : sell_sum[63:0];   // saturates (v12)
                    outc[i] <= (m_p > inv[i]) ? O_WIN : (m_p < inv[i]) ? O_LOSS : O_NONE;
                    code[i] <= C_SELL;
                    pos[i]  <= 0; inv[i] <= 0; hold[i] <= 0;
                    i  <= i + 4'd1;
                    st <= S_SELL;
                end
                // 2. BUY candidates
                S_CAND: begin
                    for (k = 0; k < N; k = k + 1) begin
                        qty[k]  <= (max_lots == 32'd0 || lvol[k] < max_lots) ? lvol[k] : max_lots;
                        cand[k] <= (k < nsym) && fresh[k] && sig[k] == 2'd1 &&
                                   (((max_lots == 32'd0 || lvol[k] < max_lots) ? lvol[k] : max_lots) != 32'd0) &&
                                   (({1'b0, pos[k]} + {1'b0, ((max_lots == 32'd0 || lvol[k] < max_lots) ? lvol[k] : max_lots)})
                                    <= {1'b0, pos_limit[32*k +: 32]});
                        used[k] <= 1'b0;
                    end
                    rotated <= 1'b0;
                    st <= S_SCAN;
                end
                // 3. pick the strongest unused candidate in ONE cycle (equal scores: lower index;
                //    RANK off: company order)
                S_SCAN: begin
                    if (!best_any) begin
                        st <= S_HOLD;
                    end else begin
                        used[best_i] <= 1'b1;
                        cur <= best_i;
                        m_a <= lastp[best_i]; m_b <= qty[best_i];
                        c_b <= w[best_i];
                        st <= S_BUY_W;
                    end
                end
                S_BUY_W:  st <= S_BUY_W2;
                S_BUY_W2: st <= S_BUY_W3;
                S_BUY_W3: begin
                    inv_plus_r <= {1'b0, inv[cur]} + {1'b0, m_p};
                    st <= S_BUY_U;
                end
                S_BUY_U: begin
                    cost_r <= m_p;
                    if (cash >= m_p && cap_ok) begin
                        cash <= cash - m_p;
                        if (pos[cur] == 32'd0) hold[cur] <= 0;
                        pos[cur]  <= pos_after[31:0];
                        inv[cur]  <= inv_plus_r[63:0];
                        code[cur] <= C_BUY;
                        st <= S_SCAN;
                    end else if (rot_en && !rotated && cap_ok) begin
                        st <= S_VSCAN;
                    end else begin
                        st <= S_SCAN;
                    end
                end
                // 4. rotation: lowest-score eligible holding, in ONE cycle (equal scores: lower index)
                S_VSCAN: begin
                    if (!vic_any) begin
                        st <= S_SCAN;
                    end else begin
                        vbest <= vic_i;
                        m_a <= pos[vic_i]; m_b <= lastp[vic_i];
                        st <= S_ROT_W;
                    end
                end
                S_ROT_W:  st <= S_ROT_W2;
                S_ROT_W2: st <= S_ROT_W3;
                S_ROT_W3: begin
                    rot_sum <= {1'b0, cash} + {1'b0, m_p};
                    st <= S_ROT_U;
                end
                S_ROT_U: begin
                    if (rot_sum >= {1'b0, cost_r}) begin
                        outc[vbest] <= (m_p > inv[vbest]) ? O_WIN : (m_p < inv[vbest]) ? O_LOSS : O_NONE;
                        code[vbest] <= C_ROT;
                        pos[vbest]  <= 0; inv[vbest] <= 0; hold[vbest] <= 0;
                        rotated     <= 1'b1;
                        cash        <= rot_left[64] ? {64{1'b1}} : rot_left[63:0];  // saturates (v12)
                        if (pos[cur] == 32'd0) hold[cur] <= 0;
                        pos[cur]    <= pos_after[31:0];
                        inv[cur]    <= inv[cur] + cost_r;
                        code[cur]   <= C_BUY;
                    end
                    st <= S_SCAN;
                end
                // 5. holding time
                S_HOLD: begin
                    for (k = 0; k < N; k = k + 1)
                        if (pos[k] != 32'd0 && hold[k] != 8'd255) hold[k] <= hold[k] + 8'd1;
                    i  <= 0;
                    st <= rw_en ? S_WSEL : S_DONE;
                end
                // 6. reweight: closed positions in company order
                S_WSEL: begin
                    if (i == ns_eff) begin
                        st <= S_DONE;
                    end else if (({1'b0, i} < {1'b0, nsym}) && outc[i] == O_WIN) begin
                        st <= S_WIN;
                    end else if (({1'b0, i} < {1'b0, nsym}) && outc[i] == O_LOSS) begin
                        st <= S_LOSS0;
                    end else begin
                        i <= i + 4'd1;
                    end
                end
                // a win: every other traded company j gives take(w[j]) to company i, all at once
                S_WIN: begin
                    for (k = 0; k < N; k = k + 1)
                        t_r[k] <= ((k < nsym) && (k != i)) ? take(w[k], wshift, wfloor) : 16'd0;
                    st <= S_WIN2;
                end
                S_WIN2: begin
                    for (k = 0; k < N; k = k + 1)
                        if (k != i) w[k] <= w[k] - t_r[k];
                    w[i] <= wi + t_sum;
                    i  <= i + 4'd1;
                    st <= S_WSEL;
                end
                S_LOSS0: begin
                    share <= ti >> share_shift(nsym);
                    st <= S_LOSS;
                end
                // a loss: company i gives `share` to every other traded company, all at once
                S_LOSS: begin
                    for (k = 0; k < N; k = k + 1)
                        if ((k < nsym) && (k != i)) w[k] <= w[k] + share;
                    w[i] <= wi - share * (ns_eff - 4'd1);
                    i  <= i + 4'd1;
                    st <= S_WSEL;
                end
                S_DONE: begin
                    for (k = 0; k < N; k = k + 1) begin
                        fresh[k] <= 1'b0;
                        codes[2*k +: 2] <= code[k];
                    end
                    latency <= cyc - t0 + 32'd1;
                    count   <= count + 32'd1;
                    done    <= 1'b1;
                    st      <= S_IDLE;
                end
                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
