`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_hft_unit.v : unit tests for tick_parser + hft_accelerator (no CPU, no UART)
//   1. random tick stream fed byte-by-byte into the parser, some ticks sent
//      back-to-back into the accelerator (tests the 1-entry buffer)
//   2. a broken packet (5 bytes, then silence) followed by a good one: the
//      parser must resync and decode the good packet
//   Prints "DEC <id> <decision> <latency>" for tools/check_hft.py unit.
//   run: vvp tb_hft_unit.vvp +TICKS=ticks.txt
// -----------------------------------------------------------------------------
module tb_hft_unit;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;

    // parser
    reg  [7:0]  rx_data = 0;
    reg         rx_valid = 0;
    wire [31:0] p_id, p_price, p_vol;
    wire        p_valid;
    tick_parser #(.GAP_CLKS(200)) u_p (
        .clk(clk), .rst(rst), .rx_data(rx_data), .rx_valid(rx_valid),
        .tick_id(p_id), .tick_price(p_price), .tick_vol(p_vol), .tick_valid(p_valid));

    // accelerator, fed either by the parser or directly (burst mode)
    reg         d_valid = 0;
    reg  [31:0] d_id = 0, d_price = 0, d_vol = 0;
    reg         kill = 0;
    wire        a_valid = p_valid | d_valid;
    wire [31:0] a_price = p_valid ? p_price : d_price;
    wire [31:0] a_vol   = p_valid ? p_vol   : d_vol;
    wire [31:0] dec, lat, pos;
    wire        dv;
    hft_accelerator u_a (
        .clk(clk), .rst(rst), .clear(1'b0), .tick_valid(a_valid), .tick_id(32'd0), .tick_price(a_price), .tick_vol(a_vol),
        .kill_switch(kill), .config_pos_limit(32'd1000), .config_breakout_high(32'd150), .config_breakout_low(32'd50),
        .config_starting_cash(64'd1000000),
        .decision(dec), .latency_cycles(lat), .decision_valid(dv), .current_position(pos), .current_cash());

    // decisions come out in tick order; ids are kept in a queue
    reg [31:0] q [0:8191];
    integer qh = 0, qt = 0;
    always @(posedge clk) if (dv) begin
        $display("DEC %0d %0d %0d", q[qh], dec, lat);
        qh = qh + 1;
    end

    task send_byte(input [7:0] b);
        begin rx_data <= b; rx_valid <= 1; @(posedge clk); rx_valid <= 0; repeat (3) @(posedge clk); end
    endtask
    task send_packet(input [31:0] id, input [31:0] pr, input [31:0] vo);
        integer i;
        begin
            for (i = 0; i < 4; i = i + 1) send_byte(id >> (8 * i));
            for (i = 0; i < 4; i = i + 1) send_byte(pr >> (8 * i));
            for (i = 0; i < 4; i = i + 1) send_byte(vo >> (8 * i));
        end
    endtask

    reg [8*1024-1:0] fname;            // room for paths up to 1024 characters
    integer fd, n, id, price, vol, k, cnt = 0, seen_resync = 0;
    initial begin
        if (!$value$plusargs("TICKS=%s", fname)) begin $display("need +TICKS="); $finish; end
        fd = $fopen(fname, "r");
        repeat (5) @(posedge clk); rst <= 0; repeat (5) @(posedge clk);
        // test 2 first: a broken packet, then silence; must not shift later packets
        send_byte(8'hDE); send_byte(8'hAD); send_byte(8'hBE); send_byte(8'hEF); send_byte(8'h01);
        repeat (400) @(posedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%d %d %d %d\n", id, price, vol, k);
            if (n == 4) begin
                kill <= k[0];
                @(posedge clk);
                q[qt] = id; qt = qt + 1;
                if (cnt % 7 == 3) begin
                    // burst: drive the accelerator directly on the very next cycle after the previous tick
                    d_valid <= 1; d_price <= price; d_vol <= vol; @(posedge clk); d_valid <= 0;
                end else begin
                    send_packet(id, price, vol);
                end
                if (cnt % 7 != 2) repeat (12) @(posedge clk);   // after %7==2 the next tick comes right away
                cnt = cnt + 1;
            end
        end
        repeat (50) @(posedge clk);
        $display("UNIT DONE sent=%0d decided=%0d", qt, qh);
        $finish;
    end
endmodule
