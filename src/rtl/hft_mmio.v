`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// hft_mmio.v : trading accelerator peripheral at 0x3000_0000 (word access only)
//
//   Multi-company build: N_MAX independent engines (hft_multi.v) share one cash
//   account.  A tick's company is tick_id[30:28]; bit 31 still marks a command.
//   With NUM_SYMBOLS = 1 (the reset value) and SYMBOL_SEL = 0 the register map and
//   the behaviour are exactly those of the original single-company design.
//
//   Registers marked (sel) belong to the company chosen by SYMBOL_SEL.
//   +0x00 POS_LIMIT   RW (sel)  +0x04 BRK_HIGH  RW (sel)  +0x08 BRK_LOW  RW (sel)
//   +0x0C TICK_ID     R    +0x10 TICK_PRICE R   +0x14 TICK_VOL R   (last UART packet)
//   +0x18 HW_DECISION R (sel)   +0x1C HW_LATENCY R (sel)   +0x20 HW_POSITION R (sel)
//   +0x24 STATUS      R: bit0 tick ready, bit1 hw done, bit2 uart tx ready,
//                        bit3 allocation done, bit4 allocator busy, bit5 every score computed,
//                        bit6 kill switch as applied to the latched packet (see KILL below)
//                     W: write 1 to bit0 / bit1 / bit3 to clear that flag
//   +0x28 UART_TX     W: send one byte (check STATUS bit2 first)
//   +0x2C OVERRUN     R: packets DROPPED because the CPU had not consumed the previous
//                        one (cleared by a CTRL write)
//   +0x30 CTRL        W: bit0 = clear every engine (MA, VWAP, positions), reload the
//                        shared cash from CASH_LO/HI, zero the invested amounts and the
//                        OVERRUN / BAD_SYMBOL counters (start of a new run)
//   +0x34 CASH_LO     RW   starting cash low 32 bits (shared; takes effect on CTRL clear)
//   +0x38 CASH_HI     RW   starting cash high 32 bits
//   +0x3C HW_CASH_LO  R    shared cash, low 32 bits
//   ---- multi-company registers ----
//   +0x40 SYMBOL_SEL  RW   company (0..N_MAX-1) addressed by the (sel) registers
//   +0x44 NUM_SYMBOLS RW   companies traded (1..N_MAX; 0 is stored as 1, > N_MAX as N_MAX)
//   +0x48 CASH_CAP_LO RW (sel)  per-company cap on invested cash, low 32 bits (0 = no cap)
//   +0x4C CASH_CAP_HI RW (sel)  high 32 bits
//   +0x50 HW_CASH_HI  R    shared cash, high 32 bits
//   +0x54 BAD_SYMBOL  R    ticks whose company >= NUM_SYMBOLS (not traded; cleared by CTRL)
//   +0x58 N_MAX       R    number of engines built into this bitstream
//   +0x5C INVESTED_LO R (sel)  BUY cost minus SELL proceeds of that company (signed)
//   +0x60 INVESTED_HI R (sel)
//   ---- portfolio allocator (hft_alloc.v) ----
//   +0x64 PORT_MODE   RW   W: bit0 portfolio, bit1 rank, bit2 rotate, bit3 reweight (takes
//                        effect on CTRL clear; reset 0 = independent engines as before)
//                        R: [3:0] written value, [7:4] mode in force since the last clear
//   +0x68 MAX_LOTS    RW   lots per BUY = min(bar volume, MAX_LOTS); 0 = whole volume
//   +0x6C MARGIN      RW   rotation needs score(buyer) - score(holder) > MARGIN (2^-20 units)
//   +0x70 ALLOC_PARAM RW   [7:0] MIN_HOLD minutes, [12:8] K (reweight shift),
//                        [20:16] CAPSHIFT (cap = start*weight >> CAPSHIFT; on CTRL clear)
//   +0x74 W_FLOOR     RW   [15:0] lowest weight (of 32768) a company can drop to
//   +0x78 ALLOC_CODES R    [15:0] codes of the last ALLOCATE, 2 bits per company
//                        (0 none, 1 BUY, 2 SELL, 3 ROT); bit16 kill switch was on
//   +0x7C ALLOC_LAT   R    cycles from the ALLOCATE packet to the end of the allocation
//   +0x80 ALLOC_COUNT R    allocations since the last clear
//   +0x84 SCORE       R (sel)  momentum score of the last tick (signed, 2^-20 units)
//   +0x88 WEIGHT      R (sel)  [15:0] weight, [23:16] minutes held
//   +0x8C FRAME_ERR   R    UART bytes dropped for a bad stop bit (cleared by a CTRL clear)
//   +0x90 ENG_DROP    R    ticks an engine had to drop because its 1-entry buffer was full
//                        (cannot happen with the CPU's flow control; cleared by a CTRL clear)
//   +0x94 VWAP_OFF    R    bit i: company i's VWAP sums would have overflowed, so its VWAP rule
//                        no longer votes (until the next CTRL clear)
//
//   KILL (v12): SW0 goes through ONE 2-flip-flop synchroniser here.  Its value is latched
//   with every accepted packet (kill_tick) and that latched value is what the engines use
//   for this tick AND what the firmware reads (STATUS bit6), so hardware and software
//   always apply the same kill state to a tick even if SW0 is flipped (or bounces) while
//   the tick is being processed.  The allocator samples the synchronised switch when the
//   ALLOCATE packet arrives and reports the value it used (ALLOC_CODES bit16).
//   STATUS bit3 = allocation done (write 1 to bit3 to clear), bit4 = allocator busy.
//   In portfolio mode HW_DECISION is the engine's 2-of-3 vote (the signal), HW_POSITION,
//   INVESTED and HW_CASH come from the allocator, and the ALLOCATE packet (0x80000006)
//   starts the allocation in hardware the cycle it is accepted.  A tick that arrives while
//   the allocator is busy is not traded (counted in OVERRUN; the PC never does this).
//
//   Packets whose id has bit 31 set are commands for the firmware: they are
//   latched for the CPU like ticks but are NOT sent to the accelerator.  A tick for a
//   company >= NUM_SYMBOLS is latched for the CPU (so the firmware can answer it) but
//   is not sent to any engine and counts in BAD_SYMBOL.
//
//   Flow control: the PC must wait for the report of one tick before it sends the
//   next (the dashboard does).  If a packet arrives while TICK_READY is still set
//   (the CPU has not consumed the previous packet) the NEW packet is dropped and
//   OVERRUN is incremented.  A dropped packet is dropped for the accelerator too,
//   so hardware and software always process exactly the same ticks and can never
//   drift apart; the loss shows up as OVERRUN > 0 (firmware lights LED3) and as a
//   missing report on the PC.
// -----------------------------------------------------------------------------
module hft_mmio #(
    parameter CLKS_PER_BIT = 868,           // 100 MHz / 115200 baud
    parameter N_MAX        = 2              // engines (companies) in this build, 1..8
)(
    input  wire        clk,
    input  wire        rst,

    input  wire        uart_rx,
    output wire        uart_tx,

    input  wire        kill_switch,

    input  wire [31:0] addr,
    input  wire [31:0] wdata,
    input  wire        we,
    output reg  [31:0] rdata
);

    wire [7:0] rx_data;
    wire       rx_valid;
    wire       rx_ferr;

    uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
        .clk(clk),
        .rst(rst),
        .rx(uart_rx),
        .data(rx_data),
        .valid(rx_valid),
        .frame_err(rx_ferr)
    );

    // kill switch: one synchroniser for the whole peripheral, one value per packet
    (* ASYNC_REG = "TRUE" *) reg kill_q1 = 1'b0;
    (* ASYNC_REG = "TRUE" *) reg kill_q2 = 1'b0;
    always @(posedge clk) begin
        kill_q1 <= kill_switch;
        kill_q2 <= kill_q1;
    end
    reg kill_tick;                       // kill state applied to the latched packet

    wire [31:0] tick_id;
    wire [31:0] tick_price;
    wire [31:0] tick_vol;
    wire        tick_valid;

    tick_parser #(.GAP_CLKS(CLKS_PER_BIT * 576)) u_parser (
        .clk(clk),
        .rst(rst),
        .rx_data(rx_data),
        .rx_valid(rx_valid),
        .tick_id(tick_id),
        .tick_price(tick_price),
        .tick_vol(tick_vol),
        .tick_valid(tick_valid)
    );

    localparam [3:0] NMAX4 = N_MAX;
    wire [5:0] reg_idx = addr[7:2];

    reg        acc_clear;
    reg [31:0] cfg_pos_limit [0:N_MAX-1];
    reg [31:0] cfg_brk_high  [0:N_MAX-1];
    reg [31:0] cfg_brk_low   [0:N_MAX-1];
    reg [63:0] cfg_cash_cap  [0:N_MAX-1];
    reg [63:0] config_starting_cash;
    reg [2:0]  symbol_sel;
    reg [3:0]  num_symbols;
    reg [3:0]  mode_cfg, mode_act;          // portfolio mode: written / in force since clear
    reg [31:0] max_lots, margin;
    reg [7:0]  min_hold;
    reg [4:0]  wshift, capshift;
    reg [15:0] wfloor;
    reg        alloc_done_flag;
    wire       port_act = mode_act[0];

    reg tick_ready_flag;
    reg hw_done_flag;

    // A packet is accepted only if the CPU has consumed the previous one (flag clear,
    // or being cleared by the CPU write in this very cycle).  Otherwise the NEW packet
    // is dropped: it reaches neither the CPU nor the accelerator (see header).
    wire cpu_clears_tick = we && (reg_idx == 6'd9) && wdata[0];
    wire tick_accept     = tick_valid && (!tick_ready_flag || cpu_clears_tick);
    wire tick_drop       = tick_valid && !tick_accept;

    wire [2:0] tick_sym  = tick_id[30:28];
    wire       is_tick   = tick_accept && !tick_id[31];
    wire       sym_ok    = ({1'b0, tick_sym} < num_symbols);
    wire       alloc_busy;
    wire       tick_lost = is_tick && sym_ok && port_act && alloc_busy;   // never with the PC's flow control
    wire       alloc_go  = tick_accept && (tick_id == 32'h80000006) && port_act;

    // ---------------------------------------------------------------- engines
    wire [N_MAX-1:0]    eng_tv;
    wire [32*N_MAX-1:0] f_price, f_vol, f_lim, f_bh, f_bl;
    wire [64*N_MAX-1:0] f_cap, f_inv;
    wire [32*N_MAX-1:0] f_dec, f_lat, f_pos;
    wire [N_MAX-1:0]    f_dv, f_drop, f_vsat;
    wire [63:0]         hw_cash;
    wire [2*N_MAX-1:0]  f_vote, f_codes;
    wire [32*N_MAX-1:0] f_score;
    wire [16*N_MAX-1:0] f_w;
    wire [8*N_MAX-1:0]  f_hold;
    wire                a_done, a_sready, a_kill;
    wire [31:0]         a_lat, a_count;
    wire [15:0]         codes16 = f_codes;

    genvar g;
    generate
        for (g = 0; g < N_MAX; g = g + 1) begin : pack
            assign eng_tv[g]            = is_tick && sym_ok && (tick_sym == g) && !tick_lost;
            assign f_price[32*g +: 32]  = tick_price;
            assign f_vol[32*g +: 32]    = tick_vol;
            assign f_lim[32*g +: 32]    = cfg_pos_limit[g];
            assign f_bh[32*g +: 32]     = cfg_brk_high[g];
            assign f_bl[32*g +: 32]     = cfg_brk_low[g];
            assign f_cap[64*g +: 64]    = cfg_cash_cap[g];
        end
    endgenerate

    hft_multi #(.N_MAX(N_MAX)) u_hft (
        .clk(clk),
        .rst(rst),
        .clear(acc_clear),
        .kill_switch(kill_tick),
        .alloc_kill_sw(kill_q2),
        .tick_valid(eng_tv),
        .tick_price(f_price),
        .tick_vol(f_vol),
        .cfg_pos_limit(f_lim),
        .cfg_brk_high(f_bh),
        .cfg_brk_low(f_bl),
        .cfg_cash_cap(f_cap),
        .cfg_starting_cash(config_starting_cash),
        .port_mode(port_act),
        .rank_en(mode_act[1]),
        .rot_en(mode_act[2]),
        .rw_en(mode_act[3]),
        .nsym(num_symbols),
        .max_lots(max_lots),
        .min_hold(min_hold),
        .margin(margin),
        .wshift(wshift),
        .wfloor(wfloor),
        .capshift(capshift),
        .alloc_start(alloc_go),
        .decision(f_dec),
        .latency_cycles(f_lat),
        .decision_valid(f_dv),
        .tick_dropped(f_drop),
        .vwap_sat(f_vsat),
        .position(f_pos),
        .invested(f_inv),
        .cash(hw_cash),
        .vote(f_vote),
        .alloc_codes(f_codes),
        .alloc_done(a_done),
        .alloc_latency(a_lat),
        .alloc_count(a_count),
        .score(f_score),
        .weight(f_w),
        .hold(f_hold),
        .scores_ready(a_sready),
        .alloc_busy(alloc_busy),
        .alloc_kill(a_kill)
    );

    reg [7:0] tx_data;
    reg       tx_start;
    wire      tx_ready;

    uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
        .clk(clk),
        .rst(rst),
        .data(tx_data),
        .start(tx_start),
        .tx(uart_tx),
        .ready(tx_ready)
    );

    reg [31:0] latched_tick_id;
    reg [31:0] latched_tick_price;
    reg [31:0] latched_tick_vol;

    reg [31:0] latched_hw_decision [0:N_MAX-1];
    reg [31:0] latched_hw_latency  [0:N_MAX-1];
    reg [31:0] overrun_cnt;
    reg [31:0] bad_sym_cnt;
    reg [31:0] frame_err_cnt;
    reg [31:0] eng_drop_cnt;

    wire       sel_ok = (symbol_sel < N_MAX);
    integer    k;

    always @(posedge clk) begin
        if (rst) begin
            for (k = 0; k < N_MAX; k = k + 1) begin
                cfg_pos_limit[k]       <= 32'd1000;
                cfg_brk_high[k]        <= 32'd150;
                cfg_brk_low[k]         <= 32'd50;
                cfg_cash_cap[k]        <= 64'd0;
                latched_hw_decision[k] <= 0;
                latched_hw_latency[k]  <= 0;
            end
            config_starting_cash <= 64'd1000000;
            symbol_sel  <= 0;
            num_symbols <= 4'd1;
            mode_cfg <= 4'd0;
            mode_act <= 4'd0;
            max_lots <= 32'd0;
            margin   <= 32'd1049;
            min_hold <= 8'd5;
            wshift   <= 5'd3;
            capshift <= 5'd14;
            wfloor   <= 16'd4096;
            alloc_done_flag <= 1'b0;

            tick_ready_flag <= 0;
            hw_done_flag <= 0;
            tx_start <= 0;
            tx_data <= 0;
            latched_tick_id <= 0;
            latched_tick_price <= 0;
            latched_tick_vol <= 0;
            overrun_cnt <= 0;
            bad_sym_cnt <= 0;
            frame_err_cnt <= 0;
            eng_drop_cnt <= 0;
            kill_tick <= 0;
            acc_clear <= 0;
        end else begin
            tx_start <= 0;
            acc_clear <= 0;

            // CPU writes first, so a flag set by hardware in the same cycle wins
            if (we) begin
                case (reg_idx)
                    6'd0:  if (sel_ok) cfg_pos_limit[symbol_sel] <= wdata;
                    6'd1:  if (sel_ok) cfg_brk_high[symbol_sel] <= wdata;
                    6'd2:  if (sel_ok) cfg_brk_low[symbol_sel] <= wdata;
                    6'd9: begin
                        if (wdata[0]) tick_ready_flag <= 0;
                        if (wdata[1]) hw_done_flag <= 0;
                        if (wdata[3]) alloc_done_flag <= 0;
                    end
                    6'd10: begin
                        tx_data <= wdata[7:0];
                        tx_start <= 1;
                    end
                    6'd12: begin
                        acc_clear <= wdata[0];
                        if (wdata[0]) mode_act <= mode_cfg;     // the new run's mode
                    end
                    6'd13: config_starting_cash[31:0] <= wdata;
                    6'd14: config_starting_cash[63:32] <= wdata;
                    6'd16: symbol_sel <= wdata[2:0];
                    6'd17: num_symbols <= (wdata == 32'd0)    ? 4'd1 :
                                          (wdata > N_MAX)      ? NMAX4 : wdata[3:0];
                    6'd18: if (sel_ok) cfg_cash_cap[symbol_sel][31:0]  <= wdata;
                    6'd19: if (sel_ok) cfg_cash_cap[symbol_sel][63:32] <= wdata;
                    6'd25: mode_cfg <= wdata[3:0];
                    6'd26: max_lots <= wdata;
                    6'd27: margin   <= wdata;
                    6'd28: begin
                        min_hold <= wdata[7:0];
                        wshift   <= wdata[12:8];
                        capshift <= wdata[20:16];
                    end
                    6'd29: wfloor   <= wdata[15:0];
                    default: ;
                endcase
            end

            if (tick_accept) begin
                tick_ready_flag <= 1;
                kill_tick <= kill_q2;
                latched_tick_id <= tick_id;
                latched_tick_price <= tick_price;
                latched_tick_vol <= tick_vol;
            end

            // a packet that arrives before the CPU consumed the previous one is dropped
            if (tick_drop || tick_lost)
                overrun_cnt <= overrun_cnt + 1;
            if (is_tick && !sym_ok)
                bad_sym_cnt <= bad_sym_cnt + 1;
            if (rx_ferr)
                frame_err_cnt <= frame_err_cnt + 1;
            if (|f_drop)
                eng_drop_cnt <= eng_drop_cnt + 1;    // engines get one tick per packet: at most one drop per cycle

            for (k = 0; k < N_MAX; k = k + 1) begin
                if (f_dv[k]) begin
                    latched_hw_decision[k] <= port_act ? {30'd0, f_vote[2*k +: 2]} : f_dec[32*k +: 32];
                    latched_hw_latency[k]  <= f_lat[32*k +: 32];
                end
            end
            if (|f_dv)
                hw_done_flag <= 1;
            if (a_done)
                alloc_done_flag <= 1;

            // a CTRL write starts a new run: forget earlier drops (placed last so it wins)
            if (we && reg_idx == 6'd12 && wdata[0]) begin
                overrun_cnt <= 0;
                bad_sym_cnt <= 0;
                frame_err_cnt <= 0;
                eng_drop_cnt <= 0;
                alloc_done_flag <= 0;
            end
        end
    end

    wire [2:0]  s     = sel_ok ? symbol_sel : 3'd0;
    wire [63:0] inv_s = f_inv[64*s +: 64];

    always @(*) begin
        case (reg_idx)
            6'd0:  rdata = sel_ok ? cfg_pos_limit[s] : 32'b0;
            6'd1:  rdata = sel_ok ? cfg_brk_high[s]  : 32'b0;
            6'd2:  rdata = sel_ok ? cfg_brk_low[s]   : 32'b0;
            6'd3:  rdata = latched_tick_id;
            6'd4:  rdata = latched_tick_price;
            6'd5:  rdata = latched_tick_vol;
            6'd6:  rdata = sel_ok ? latched_hw_decision[s] : 32'b0;
            6'd7:  rdata = sel_ok ? latched_hw_latency[s]  : 32'b0;
            6'd8:  rdata = sel_ok ? f_pos[32*s +: 32]       : 32'b0;
            // tx_start is checked too: the UART only drops 'ready' one cycle after
            // the write, and a poll right after the store must not see it as free
            6'd9:  rdata = {25'b0, kill_tick, a_sready, alloc_busy, alloc_done_flag, tx_ready & ~tx_start, hw_done_flag, tick_ready_flag};
            6'd11: rdata = overrun_cnt;
            6'd13: rdata = config_starting_cash[31:0];
            6'd14: rdata = config_starting_cash[63:32];
            6'd15: rdata = hw_cash[31:0];
            6'd16: rdata = {29'b0, symbol_sel};
            6'd17: rdata = {28'b0, num_symbols};
            6'd18: rdata = sel_ok ? cfg_cash_cap[s][31:0]  : 32'b0;
            6'd19: rdata = sel_ok ? cfg_cash_cap[s][63:32] : 32'b0;
            6'd20: rdata = hw_cash[63:32];
            6'd21: rdata = bad_sym_cnt;
            6'd22: rdata = N_MAX;
            6'd23: rdata = sel_ok ? inv_s[31:0]  : 32'b0;
            6'd24: rdata = sel_ok ? inv_s[63:32] : 32'b0;
            6'd25: rdata = {24'b0, mode_act, mode_cfg};
            6'd26: rdata = max_lots;
            6'd27: rdata = margin;
            6'd28: rdata = {11'b0, capshift, 3'b0, wshift, min_hold};
            6'd29: rdata = {16'b0, wfloor};
            6'd30: rdata = {15'b0, a_kill, codes16};
            6'd31: rdata = a_lat;
            6'd32: rdata = a_count;
            6'd33: rdata = sel_ok ? f_score[32*s +: 32] : 32'b0;
            6'd34: rdata = sel_ok ? {8'b0, f_hold[8*s +: 8], f_w[16*s +: 16]} : 32'b0;
            6'd35: rdata = frame_err_cnt;
            6'd36: rdata = eng_drop_cnt;
            6'd37: rdata = {{(32-N_MAX){1'b0}}, f_vsat};
            default: rdata = 32'b0;
        endcase
    end
endmodule
