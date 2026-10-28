`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_hft_port.v : random + directed test of the portfolio allocator (hft_multi.v in portfolio
//                 mode: engines + hft_alloc.v), no CPU, no UART.  Checked by
//                 tools/check_port.py against hft_model.PortfolioModel after EVERY minute:
//                 codes, shared cash, and each company's position, invested amount, weight,
//                 holding time and score.
//   ops file, 5 integers per line "<op> a b c d":
//     0 sym price vol 0          stage a tick for company sym
//     3 wait 0 0 0               fire the staged ticks in the SAME cycle, then wait `wait` cycles
//     6 kill 0 0 0               ALLOCATE (end of minute) with the kill switch at `kill`
//     4 nsym mode max_lots capshift   settings that apply at the next clear
//     1 cash_hi cash_lo 0 0      starting cash, then pulse `clear`
//     2 sym limit brk_high brk_low    one company's configuration
//     5 margin min_hold wshift wfloor allocator parameters (live)
//   log: CLEAR / CFG / PARAM / TICK / SIG sym vote latency / ALLOC kill codes cash latency /
//        ST sym pos invested weight hold score / DONE
//   run: vvp tb_hft_port.vvp +OPS=ops.txt          (N set with iverilog -P tb_hft_port.N=..)
// -----------------------------------------------------------------------------
module tb_hft_port;
    parameter N = 2;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, clear = 0, kill = 0, astart = 0;
    reg  [N-1:0]    tv = 0;
    reg  [32*N-1:0] price = 0, vol = 0;
    reg  [32*N-1:0] lim, bh, bl;
    reg  [63:0]     cash0 = 64'd1000000;
    reg  [3:0]      nsym = N;
    reg             rank_en = 1, rot_en = 1, rw_en = 1;
    reg  [31:0]     max_lots = 0, margin = 1049;
    reg  [7:0]      min_hold = 5;
    reg  [4:0]      wshift = 3, capshift = 14;
    reg  [15:0]     wfloor = 4096;

    wire [32*N-1:0] dec, lat, pos, score;
    wire [64*N-1:0] inv;
    wire [N-1:0]    dv;
    wire [63:0]     cash;
    wire [2*N-1:0]  vote, codes;
    wire [16*N-1:0] weight;
    wire [8*N-1:0]  hold;
    wire            adone, sready, abusy;
    wire [31:0]     alat, acount;

    hft_multi #(.N_MAX(N)) u (
        .clk(clk), .rst(rst), .clear(clear), .kill_switch(kill), .alloc_kill_sw(kill),
        .tick_valid(tv), .tick_price(price), .tick_vol(vol),
        .cfg_pos_limit(lim), .cfg_brk_high(bh), .cfg_brk_low(bl), .cfg_cash_cap({64*N{1'b0}}),
        .cfg_starting_cash(cash0),
        .port_mode(1'b1), .rank_en(rank_en), .rot_en(rot_en), .rw_en(rw_en), .nsym(nsym),
        .max_lots(max_lots), .min_hold(min_hold), .margin(margin), .wshift(wshift), .wfloor(wfloor),
        .capshift(capshift), .alloc_start(astart),
        .decision(dec), .latency_cycles(lat), .decision_valid(dv), .position(pos), .invested(inv), .cash(cash),
        .vote(vote), .alloc_codes(codes), .alloc_done(adone), .alloc_latency(alat), .alloc_count(acount),
        .score(score), .weight(weight), .hold(hold), .scores_ready(sready), .alloc_busy(abusy), .alloc_kill());

    integer e;
    always @(posedge clk) begin
        #1;
        for (e = 0; e < N; e = e + 1)
            if (dv[e]) $display("SIG %0d %0d %0d", e, vote[2*e +: 2], lat[32*e +: 32]);
    end

    reg [8*1024-1:0] fname;
    integer fd, n, op, a, b, c, d, s, t;
    reg [N-1:0] staged = 0;
    reg [3:0] nsym_next = N;
    reg [3:0] mode_next = 4'hE;
    reg [31:0] ml_next = 0;
    reg [4:0] cs_next = 14;

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
                        price[32*a +: 32] = b; vol[32*a +: 32] = c; staged[a] = 1'b1;
                        $display("TICK %0d %0d %0d", a, b, c);
                    end
                    3: begin
                        tv <= staged; @(posedge clk); tv <= 0; staged = 0;
                        repeat (a) @(posedge clk);
                    end
                    6: begin
                        kill <= a[0]; repeat (4) @(posedge clk);
                        astart <= 1; @(posedge clk); astart <= 0;
                        t = 0;
                        while (!adone && t < 5000) begin @(posedge clk); t = t + 1; end
                        #1;
                        $display("ALLOC %0d %0d %0d %0d", a, codes, cash, alat);
                        for (s = 0; s < N; s = s + 1)
                            $display("ST %0d %0d %0d %0d %0d %0d", s, pos[32*s +: 32], inv[64*s +: 64],
                                     weight[16*s +: 16], hold[8*s +: 8], $signed(score[32*s +: 32]));
                        kill <= 0; repeat (4) @(posedge clk);
                    end
                    4: begin nsym_next = a; mode_next = b; ml_next = c; cs_next = d; end
                    1: begin
                        cash0 = {a[31:0], b[31:0]};
                        nsym = nsym_next; {rw_en, rot_en, rank_en} = mode_next[3:1]; max_lots = ml_next; capshift = cs_next;
                        $display("CLEAR %0d %0d %0d %0d %0d", cash0, nsym, mode_next, max_lots, capshift);
                        @(posedge clk); clear <= 1; @(posedge clk); clear <= 0; repeat (3) @(posedge clk);
                    end
                    2: begin
                        lim[32*a +: 32] = b; bh[32*a +: 32] = c; bl[32*a +: 32] = d;
                        $display("CFG %0d %0d %0d %0d", a, b, c, d);
                        repeat (2) @(posedge clk);
                    end
                    5: begin
                        margin = a; min_hold = b; wshift = c; wfloor = d;
                        $display("PARAM %0d %0d %0d %0d", a, b, c, d);
                        repeat (2) @(posedge clk);
                    end
                    default: ;
                endcase
            end
        end
        repeat (20) @(posedge clk);
        $display("DONE");
        $finish;
    end
endmodule
