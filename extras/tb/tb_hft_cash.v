`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_hft_cash.v : random test of hft_accelerator's risk interlock (no CPU, no UART).
//   Covers what the other tests do not: starting cash (incl. 64-bit values), the
//   position limit, SELL without holdings, zero-volume ticks, the kill switch, the
//   `clear` pulse that starts a new run, breakout levels, and back-to-back ticks.
//   ops file lines: "<op> a b c d"
//     0 price vol kill burst   one tick; burst=1: the next tick follows on the very next cycle
//     1 cash_hi cash_lo limit 0   set starting cash + position limit, then pulse `clear`
//     2 brk_high brk_low 0 0      set the breakout levels
//   Prints "DEC <n> <decision> <latency> <position> <cash>" for tools/check_cash.py.
//   run: vvp tb_hft_cash.vvp +OPS=ops.txt
// -----------------------------------------------------------------------------
module tb_hft_cash;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1, clear = 0, tv = 0, kill = 0;
    reg [31:0] price = 0, vol = 0, lim = 1000, bh = 150, bl = 50;
    reg [63:0] cash0 = 64'd1000000;
    wire [31:0] dec, lat, pos; wire dv; wire [63:0] cash;

    hft_accelerator u (.clk(clk), .rst(rst), .clear(clear), .tick_valid(tv), .tick_id(32'd0),
        .tick_price(price), .tick_vol(vol), .kill_switch(kill),
        .config_pos_limit(lim), .config_breakout_high(bh), .config_breakout_low(bl),
        .config_starting_cash(cash0),
        .decision(dec), .latency_cycles(lat), .decision_valid(dv), .current_position(pos), .current_cash(cash));

    integer seq = 0;
    always @(posedge clk) if (dv) begin
        $display("DEC %0d %0d %0d %0d %0d", seq, dec, lat, pos, cash);
        seq = seq + 1;
    end

    reg [8*1024-1:0] fname;            // room for paths up to 1024 characters
    integer fd, n, op, a, b, c, d;

    task tick(input [31:0] p, input [31:0] v, input k, input burst);
        begin
            kill <= k; price <= p; vol <= v; tv <= 1; @(posedge clk); tv <= 0;
            if (!burst) repeat (9) @(posedge clk);
        end
    endtask

    initial begin
        if (!$value$plusargs("OPS=%s", fname)) begin $display("need +OPS="); $finish; end
        fd = $fopen(fname, "r");
        repeat (4) @(posedge clk); rst <= 0; repeat (3) @(posedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%d %d %d %d %d\n", op, a, b, c, d);
            if (n == 5) begin
                case (op)
                    0: tick(a, b, c[0], d[0]);
                    1: begin
                        cash0 = {a[31:0], b[31:0]}; lim = c;
                        @(posedge clk); clear <= 1; @(posedge clk); clear <= 0; repeat (3) @(posedge clk);
                    end
                    2: begin bh = a; bl = b; repeat (2) @(posedge clk); end
                    default: ;
                endcase
            end
        end
        repeat (20) @(posedge clk);
        $display("DONE decided=%0d", seq);
        $finish;
    end
endmodule
