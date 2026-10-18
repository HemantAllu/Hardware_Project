`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// soc_top.v : Nexys A7-100T top level
//
//   rv32im_core + instruction ROM + data RAM + a few memory-mapped peripherals
//
//   Memory map (Harvard):
//     0x0000_0000  instruction memory  (fetch only, IMEM_WORDS words)
//     0x1000_0000  data memory         (DMEM_WORDS words)
//     0x2000_0000  LED       (W)  bits [15:0] drive led[15:0]  (led[15] also lights when halted)
//     0x2000_0004  SEG       (W)  32-bit value shown as 8 hex digits
//     0x2000_0008  SWITCH    (R)  sw[15:0]  (2-flip-flop synchronised)
//     0x2000_0010  CYCLE     (R)  free-running 32-bit clock-cycle counter
//     0x3000_0000  HFT       trading accelerator + UART (see hft_mmio.v)
//   UART: 115200 8N1 on the USB-UART (uart_rx C4, uart_tx D4)
//   MMIO registers are word-wide (use sw/lw).
//
//   Reset: CPU RESET button (active low). Program/data images come from
//   IMEM_INIT / DMEM_INIT (imem.mem / dmem.mem, see README).
// -----------------------------------------------------------------------------
module soc_top #(
    parameter IMEM_INIT         = "imem.mem",
    parameter DMEM_INIT         = "dmem.mem",
    parameter IMEM_WORDS        = 2048,   // 8 KB: the portfolio firmware is about 1750 words
    parameter DMEM_WORDS        = 1024,
    parameter SEG_REFRESH_BITS  = 17,
    parameter UART_CLKS_PER_BIT = 868,    // 100 MHz / 115200
    parameter HFT_N_MAX         = 2       // trading engines = companies traded at once (1..8)
)(
    input  wire        clk,            // 100 MHz
    input  wire        cpu_resetn,     // active low push button
    input  wire [15:0] sw,
    output wire [15:0] led,
    output wire [6:0]  seg,
    output wire        dp,
    output wire [7:0]  an,
    input  wire        uart_rx,
    output wire        uart_tx
);
    // ----------------------------------------------------------- reset sync
    // The button is asynchronous: 3-flip-flop synchroniser (ASYNC_REG keeps the flops
    // together for MTBF).  Every block uses a synchronous active-high reset from here;
    // the clock always runs on this board, so a synchronous reset is safe.
    (* ASYNC_REG = "TRUE" *) reg [2:0] rst_sync = 3'b111;
    always @(posedge clk) rst_sync <= {rst_sync[1:0], ~cpu_resetn};
    wire rst = rst_sync[2];

    // ----------------------------------------------------------------- core
    wire [31:0] imem_addr, imem_rdata;
    wire [31:0] dmem_addr, dmem_wdata, dmem_rdata_core;
    wire [3:0]  dmem_we;
    wire        dmem_re;
    wire        halted, retire, st_lu, st_md, st_fl;

    rv32im_core u_core (
        .clk(clk), .rst(rst),
        .imem_addr(imem_addr), .imem_rdata(imem_rdata),
        .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata), .dmem_we(dmem_we),
        .dmem_re(dmem_re), .dmem_rdata(dmem_rdata_core),
        .halted(halted), .retire(retire),
        .stat_load_use(st_lu), .stat_md_stall(st_md), .stat_flush(st_fl)
    );

    imem #(.WORDS(IMEM_WORDS), .INIT_FILE(IMEM_INIT)) u_imem (
        .addr(imem_addr), .rdata(imem_rdata)
    );

    // ------------------------------------------------------ address decoding
    wire sel_dmem = (dmem_addr[31:28] == 4'h1);
    wire sel_mmio = (dmem_addr[31:28] == 4'h2);
    wire sel_hft  = (dmem_addr[31:28] == 4'h3);

    wire [31:0] dmem_rdata_raw;
    dmem #(.WORDS(DMEM_WORDS), .INIT_FILE(DMEM_INIT)) u_dmem (
        .clk(clk),
        .addr(dmem_addr),
        .wdata(dmem_wdata),
        .we(sel_dmem ? dmem_we : 4'b0000),
        .rdata(dmem_rdata_raw)
    );

    // ------------------------------------------------------------------ MMIO
    reg [15:0] led_reg;
    reg [31:0] seg_reg;
    reg [31:0] cycle_cnt;

    // The slide switches are asynchronous board inputs: pass them through a 2-flip-flop
    // synchroniser before the CPU can read them (SW0 for the trading peripheral is synchronised
    // once inside hft_mmio, and the firmware reads the per-packet value from STATUS bit6).
    (* ASYNC_REG = "TRUE" *) reg [15:0] sw_q1 = 16'b0;
    (* ASYNC_REG = "TRUE" *) reg [15:0] sw_q2 = 16'b0;
    always @(posedge clk) begin
        sw_q1 <= sw;
        sw_q2 <= sw_q1;
    end

    always @(posedge clk) begin
        if (rst) begin
            led_reg   <= 16'b0;
            seg_reg   <= 32'b0;
            cycle_cnt <= 32'b0;
        end else begin
            cycle_cnt <= cycle_cnt + 32'd1;
            if (sel_mmio && (dmem_we == 4'b1111)) begin
                case (dmem_addr[4:2])
                    3'd0: led_reg <= dmem_wdata[15:0];
                    3'd1: seg_reg <= dmem_wdata;
                    default: ;
                endcase
            end
        end
    end

    reg [31:0] mmio_rdata;
    always @(*) begin
        case (dmem_addr[4:2])
            3'd2:    mmio_rdata = {16'b0, sw_q2};
            3'd4:    mmio_rdata = cycle_cnt;
            default: mmio_rdata = 32'b0;
        endcase
    end

    wire [31:0] hft_rdata;
    hft_mmio #(.CLKS_PER_BIT(UART_CLKS_PER_BIT), .N_MAX(HFT_N_MAX)) u_hft_mmio (
        .clk(clk),
        .rst(rst),
        .uart_rx(uart_rx),
        .uart_tx(uart_tx),
        .kill_switch(sw[0]),           // raw switch: synchronised once inside hft_mmio
        .addr(dmem_addr),
        .wdata(dmem_wdata),
        .we(sel_hft & (dmem_we == 4'b1111)),
        .rdata(hft_rdata)
    );

    assign dmem_rdata_core = sel_mmio ? mmio_rdata :
                             sel_hft  ? hft_rdata  : dmem_rdata_raw;

    // ---------------------------------------------------------------- outputs
    assign led = {led_reg[15] | halted, led_reg[14:0]};

    seg7_driver #(.REFRESH_BITS(SEG_REFRESH_BITS)) u_seg (
        .clk(clk), .value(seg_reg), .seg(seg), .an(an), .dp(dp)
    );
endmodule
