`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_hft.v : full-system test of the trading accelerator.
//   soc_top runs the real firmware (extras/hft_firmware.c). The testbench acts
//   as the PC: it sends 12-byte tick packets on uart_rx (id, price, vol, little
//   endian), waits for the 40-byte report on uart_tx, and prints one line per
//   tick for tools/check_hft.py to compare with the reference model.
//
//   The UART is sped up to BIT clocks per bit so the run takes seconds.
//   run: vvp tb_hft.vvp +IMEM=imem.hex +DMEM=dmem.hex +TICKS=ticks.txt [+NOWAIT=k]
//   ticks.txt: one tick per line: "<id hex> <price> <vol> <kill_switch>"
//              ids with bit 31 set are commands (reset / config) for the firmware
//
//   +NOWAIT=k : from line k on, the testbench streams the packets back to back at the
//               full UART rate WITHOUT waiting for the reports (a misbehaving PC).
//               The board must then drop whole packets (OVERRUN, LED3) but keep the
//               hardware and the software in step; the reports that do arrive are
//               printed at the end (tools/check_hft.py checkburst).
//   +KILLFLIP : after each packet, flip SW0 at a random moment 2..60 cycles later (while the
//               firmware is still working on that packet) and keep it flipped until the next
//               packet.  The tick's kill state is the one in ticks.txt (SW0 when the packet
//               arrived), so hardware, firmware and model must still agree on every tick.
//   The last lines printed are  "OVERRUN <n> LED <hex> SENT <lines>"  and  "DONE ...".
// -----------------------------------------------------------------------------
module tb_hft;
    localparam BIT = 16;                 // clocks per UART bit in simulation
    reg         clk = 0;
    reg         cpu_resetn = 0;
    reg  [15:0] sw = 16'h0000;
    reg         rx_line = 1'b1;          // PC -> FPGA
    wire        tx_line;                 // FPGA -> PC
    wire [15:0] led;
    wire [6:0]  seg;
    wire        dp;
    wire [7:0]  an;

    always #5 clk = ~clk;

    soc_top #(.IMEM_INIT(""), .DMEM_INIT(""), .SEG_REFRESH_BITS(4), .UART_CLKS_PER_BIT(BIT)) u_soc (
        .clk(clk), .cpu_resetn(cpu_resetn), .sw(sw),
        .led(led), .seg(seg), .dp(dp), .an(an),
        .uart_rx(rx_line), .uart_tx(tx_line)
    );

    // ------------------------------------------------------------ PC -> FPGA
    task send_byte(input [7:0] b);
        integer i;
        begin
            rx_line = 1'b0; repeat (BIT) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin rx_line = b[i]; repeat (BIT) @(posedge clk); end
            rx_line = 1'b1; repeat (BIT) @(posedge clk);
        end
    endtask
    task send_u32(input [31:0] v);
        begin send_byte(v[7:0]); send_byte(v[15:8]); send_byte(v[23:16]); send_byte(v[31:24]); end
    endtask

    // ------------------------------------------------------------ FPGA -> PC
    reg [7:0] rbuf [0:39];              // the report currently being waited for
    reg [7:0] bbuf [0:16383];           // every byte received (for the NOWAIT burst)
    integer   rcount = 0;
    integer   total_bytes = 0;
    always begin : uart_monitor
        integer i;
        reg [7:0] b;
        @(negedge tx_line);
        repeat (BIT / 2) @(posedge clk);
        if (tx_line == 1'b0) begin
            for (i = 0; i < 8; i = i + 1) begin repeat (BIT) @(posedge clk); b[i] = tx_line; end
            repeat (BIT) @(posedge clk);            // stop bit
            if (rcount < 40) rbuf[rcount] = b;
            if (total_bytes < 16384) bbuf[total_bytes] = b;
            rcount = rcount + 1;
            total_bytes = total_bytes + 1;
        end
    end

    function [31:0] word(input integer k);
        word = {rbuf[4*k+3], rbuf[4*k+2], rbuf[4*k+1], rbuf[4*k]};
    endfunction
    function [31:0] bword(input integer base, input integer k);
        bword = {bbuf[base+4*k+3], bbuf[base+4*k+2], bbuf[base+4*k+1], bbuf[base+4*k]};
    endfunction

    // ------------------------------------------------------------ stimulus
    reg [8*1024-1:0] fname;            // room for paths up to 1024 characters
    integer fd, n, price, vol, kill, t, ntick = 0, bad = 0;
    integer nowait = 1000000, bstart = 0, nburst = 0, f, base;
    integer killflip = 0, flip_at = -1, seed = 12345;
    reg [31:0] id;
    initial begin
        #1;
        if ($value$plusargs("IMEM=%s", fname)) $readmemh(fname, u_soc.u_imem.mem);
        if ($value$plusargs("DMEM=%s", fname)) $readmemh(fname, u_soc.u_dmem.mem);
        if (!$value$plusargs("TICKS=%s", fname)) begin $display("need +TICKS="); $finish; end
        if (!$value$plusargs("NOWAIT=%d", nowait)) nowait = 1000000;
        if ($test$plusargs("KILLFLIP")) killflip = 1;
        fd = $fopen(fname, "r");
        #40 cpu_resetn = 1;
        repeat (200) @(posedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %d %d %d\n", id, price, vol, kill);
            if (n == 4) begin
                sw[0] = kill[0];
                if (ntick < nowait) begin
                    rcount = 0;
                    send_u32(id); send_u32(price); send_u32(vol);
                    // wait for the full report (or time out)
                    t = 0;
                    // 2..60 cycles after the last stop bit: the packet was accepted a few cycles
                    // before, so its kill state is already latched, while the firmware has not
                    // finished reading the packet yet (v11 read SW0 itself about 20 cycles in)
                    flip_at = killflip ? 2 + ({$random(seed)} % 59) : -1;
                    while (rcount < 40 && t < 200000) begin
                        @(posedge clk); t = t + 1;
                        if (t == flip_at) sw[0] = ~sw[0];
                    end
                    repeat (4 * BIT) @(posedge clk);    // let any extra byte show up
                    if (rcount != 40) begin
                        $display("TICK %h NOREPORT bytes=%0d", id, rcount); bad = bad + 1;
                    end else if (word(0) != 32'hAA55AA55 || word(9) != 32'h55AA55AA) begin
                        $display("TICK %h BADFRAME %h %h", id, word(0), word(9)); bad = bad + 1;
                    end else begin
                        $display("REPORT %h %0d %0d %0d %0d %0d %0d %0d", word(1), word(2), word(3), word(4), word(5), word(6), word(7), word(8));
                    end
                end else begin
                    // burst: no waiting, the "PC" streams at the full UART rate
                    if (nburst == 0) bstart = total_bytes;
                    send_u32(id); send_u32(price); send_u32(vol);
                    nburst = nburst + 1;
                end
                ntick = ntick + 1;
            end
        end
        if (nburst > 0) begin
            repeat (400000) @(posedge clk);             // let the board finish every report it still owes
            for (f = 0; f < (total_bytes - bstart) / 40; f = f + 1) begin
                base = bstart + 40 * f;
                if (bword(base, 0) != 32'hAA55AA55 || bword(base, 9) != 32'h55AA55AA) begin
                    $display("TICK BURST%0d BADFRAME %h %h", f, bword(base, 0), bword(base, 9)); bad = bad + 1;
                end else begin
                    $display("REPORT %h %0d %0d %0d %0d %0d %0d %0d", bword(base, 1), bword(base, 2), bword(base, 3),
                             bword(base, 4), bword(base, 5), bword(base, 6), bword(base, 7), bword(base, 8));
                end
            end
            if ((total_bytes - bstart) % 40 != 0) begin
                $display("TICK BURST PARTIAL bytes=%0d", (total_bytes - bstart) % 40); bad = bad + 1;
            end
        end
        $display("OVERRUN %0d LED %h SENT %0d", u_soc.u_hft_mmio.overrun_cnt, led, ntick);
        $display("DONE ticks=%0d bad_frames=%0d total_tx_bytes=%0d", ntick, bad, total_bytes);
        $finish;
    end
endmodule
