`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_uart.v : self-checking test of uart_rx (v12: majority filter + stop-bit check) and a
//             uart_tx -> uart_rx loop-back.
//   1. 200 random bytes back to back (no idle time between frames)  -> all received
//   2. one-clock and two-clock glitches on the idle line              -> ignored
//   3. a byte whose stop bit is 0 (framing error)                     -> dropped, frame_err pulses
//   4. the line held low (break) for 3 byte times, then released      -> one frame_err, no byte
//   5. good bytes right after the error                               -> received again
//   6. uart_tx -> uart_rx loop-back of 64 random bytes                -> all received
//   run: iverilog -g2012 -o tb_uart.vvp tb_uart.v uart.v && vvp -n tb_uart.vvp
//   last line: "TB_UART PASS" or "TB_UART FAIL ..."
// -----------------------------------------------------------------------------
module tb_uart;
    localparam BIT = 16;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1;
    reg line = 1'b1;
    wire [7:0] data;  wire valid, ferr;
    uart_rx #(.CLKS_PER_BIT(BIT)) u_rx (.clk(clk), .rst(rst), .rx(line), .data(data), .valid(valid), .frame_err(ferr));

    // loop-back pair
    reg  [7:0] tdata = 0; reg tstart = 0;
    wire tx, tready, lvalid, lferr; wire [7:0] ldata;
    uart_tx #(.CLKS_PER_BIT(BIT)) u_tx (.clk(clk), .rst(rst), .data(tdata), .start(tstart), .tx(tx), .ready(tready));
    uart_rx #(.CLKS_PER_BIT(BIT)) u_rx2 (.clk(clk), .rst(rst), .rx(tx), .data(ldata), .valid(lvalid), .frame_err(lferr));

    reg [7:0] expq [0:1023]; integer qh = 0, qt = 0;
    reg [7:0] lexp [0:255];  integer lh = 0, lt = 0;
    integer errs = 0, nferr = 0, nrx = 0, nlb = 0, i, k, seed = 7;

    always @(posedge clk) begin
        if (valid) begin
            nrx = nrx + 1;
            if (qh == qt) begin errs = errs + 1; $display("unexpected byte %02x", data); end
            else begin
                if (data !== expq[qh]) begin errs = errs + 1; $display("byte %02x, expected %02x", data, expq[qh]); end
                qh = qh + 1;
            end
        end
        if (ferr) nferr = nferr + 1;
        if (lvalid) begin
            nlb = nlb + 1;
            if (ldata !== lexp[lh]) begin errs = errs + 1; $display("loop-back %02x, expected %02x", ldata, lexp[lh]); end
            lh = lh + 1;
        end
        if (lferr) begin errs = errs + 1; $display("loop-back framing error"); end
    end

    task send(input [7:0] b, input stop_ok, input expect_it);
        integer j;
        begin
            if (expect_it) begin expq[qt] = b; qt = qt + 1; end
            line = 1'b0; repeat (BIT) @(posedge clk);
            for (j = 0; j < 8; j = j + 1) begin line = b[j]; repeat (BIT) @(posedge clk); end
            line = stop_ok; repeat (BIT) @(posedge clk);
            line = 1'b1;
        end
    endtask

    initial begin
        repeat (5) @(posedge clk); rst = 0; repeat (5) @(posedge clk);
        // 1. back to back
        for (i = 0; i < 200; i = i + 1) send($random(seed), 1'b1, 1'b1);
        repeat (3 * BIT) @(posedge clk);
        if (nrx != 200) begin errs = errs + 1; $display("1: received %0d of 200", nrx); end
        // 2. glitches on the idle line
        line = 1'b0; @(posedge clk); line = 1'b1; repeat (3 * BIT) @(posedge clk);
        line = 1'b0; repeat (2) @(posedge clk); line = 1'b1; repeat (3 * BIT) @(posedge clk);
        if (nrx != 200 || nferr != 0) begin errs = errs + 1; $display("2: glitch produced a byte or an error"); end
        // 3. bad stop bit
        send(8'hA5, 1'b0, 1'b0);
        repeat (3 * BIT) @(posedge clk);
        if (nferr != 1 || nrx != 200) begin errs = errs + 1; $display("3: frame_err %0d, bytes %0d", nferr, nrx); end
        // 4. break: line low for 3 byte times
        line = 1'b0; repeat (30 * BIT) @(posedge clk); line = 1'b1; repeat (3 * BIT) @(posedge clk);
        if (nferr != 2 || nrx != 200) begin errs = errs + 1; $display("4: frame_err %0d, bytes %0d", nferr, nrx); end
        // 5. recovery
        for (i = 0; i < 20; i = i + 1) send($random(seed), 1'b1, 1'b1);
        repeat (3 * BIT) @(posedge clk);
        if (nrx != 220 || qh != qt) begin errs = errs + 1; $display("5: received %0d of 220", nrx); end
        // 6. loop-back
        for (k = 0; k < 64; k = k + 1) begin
            while (!tready) @(posedge clk);
            tdata = $random(seed); lexp[lt] = tdata; lt = lt + 1;
            tstart <= 1'b1; @(posedge clk); tstart <= 1'b0; @(posedge clk);   // NBA: no race with the UART
        end
        repeat (12 * BIT) @(posedge clk);
        if (nlb != 64) begin errs = errs + 1; $display("6: loop-back received %0d of 64", nlb); end
        if (errs == 0) $display("TB_UART PASS (%0d bytes, %0d framing errors as expected, %0d loop-back)", nrx, nferr, nlb);
        else           $display("TB_UART FAIL %0d errors", errs);
        $finish;
    end
endmodule
