`timescale 1ns / 1ps
// -----------------------------------------------------------------------------
// uart.v : 8N1 UART receiver and transmitter.
//   uart_rx: 2-flip-flop synchroniser, then a 3-sample majority filter (rejects a one-
//            or two-cycle glitch on the line), start bit re-checked at mid-bit, data
//            sampled at mid-bit, and the STOP bit is checked: a byte whose stop bit is 0
//            (framing error: wrong baud rate, a break, noise) is NOT delivered; frame_err
//            pulses instead and the receiver waits for the line to go idle (high) before
//            it looks for the next start bit.
// -----------------------------------------------------------------------------
module uart_rx #(
    parameter CLKS_PER_BIT = 868
)(
    input  wire       clk,
    input  wire       rst,
    input  wire       rx,
    output reg  [7:0] data,
    output reg        valid,
    output reg        frame_err      // one-cycle pulse: byte dropped, stop bit was 0
);
    localparam s_IDLE    = 3'd0;
    localparam s_START   = 3'd1;
    localparam s_DATA    = 3'd2;
    localparam s_STOP    = 3'd3;
    localparam s_RECOVER = 3'd4;     // after a framing error: wait for the idle (high) line

    reg [2:0] state;
    reg [31:0] clk_count;
    reg [2:0] bit_index;

    // synchronizer (idle-high init avoids a false start bit after configuration)
    (* ASYNC_REG = "TRUE" *) reg rx_r1 = 1'b1;
    (* ASYNC_REG = "TRUE" *) reg rx_r2 = 1'b1;
    reg rx_r3 = 1'b1, rx_r4 = 1'b1;
    always @(posedge clk) begin
        rx_r1 <= rx;
        rx_r2 <= rx_r1;
        rx_r3 <= rx_r2;
        rx_r4 <= rx_r3;
    end
    // majority of the last three synchronised samples
    wire rx_f = (rx_r2 & rx_r3) | (rx_r2 & rx_r4) | (rx_r3 & rx_r4);

    always @(posedge clk) begin
        if (rst) begin
            state <= s_IDLE;
            clk_count <= 0;
            bit_index <= 0;
            data <= 0;
            valid <= 0;
            frame_err <= 0;
        end else begin
            valid <= 0;
            frame_err <= 0;
            case (state)
                s_IDLE: begin
                    if (rx_f == 1'b0) begin
                        state <= s_START;
                        clk_count <= CLKS_PER_BIT / 2;
                    end
                end
                s_START: begin
                    if (clk_count == 0) begin
                        if (rx_f == 1'b0) begin
                            state <= s_DATA;
                            clk_count <= CLKS_PER_BIT - 1;
                            bit_index <= 0;
                        end else begin
                            state <= s_IDLE;
                        end
                    end else begin
                        clk_count <= clk_count - 1;
                    end
                end
                s_DATA: begin
                    if (clk_count == 0) begin
                        data[bit_index] <= rx_f;
                        if (bit_index == 7) begin
                            state <= s_STOP;
                        end else begin
                            bit_index <= bit_index + 1;
                        end
                        clk_count <= CLKS_PER_BIT - 1;
                    end else begin
                        clk_count <= clk_count - 1;
                    end
                end
                s_STOP: begin
                    if (clk_count == 0) begin
                        if (rx_f == 1'b1) begin          // good stop bit: deliver the byte
                            valid <= 1'b1;
                            state <= s_IDLE;
                        end else begin                   // framing error: drop it
                            frame_err <= 1'b1;
                            state <= s_RECOVER;
                        end
                    end else begin
                        clk_count <= clk_count - 1;
                    end
                end
                s_RECOVER: begin
                    if (rx_f == 1'b1) state <= s_IDLE;
                end
                default: state <= s_IDLE;
            endcase
        end
    end
endmodule

module uart_tx #(
    parameter CLKS_PER_BIT = 868
)(
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] data,
    input  wire       start,
    output reg        tx,
    output reg        ready
);
    localparam s_IDLE  = 3'd0;
    localparam s_START = 3'd1;
    localparam s_DATA  = 3'd2;
    localparam s_STOP  = 3'd3;

    reg [2:0] state;
    reg [31:0] clk_count;
    reg [2:0] bit_index;
    reg [7:0] tx_data;

    always @(posedge clk) begin
        if (rst) begin
            state <= s_IDLE;
            tx <= 1'b1;
            ready <= 1'b1;
            clk_count <= 0;
            bit_index <= 0;
            tx_data <= 0;
        end else begin
            case (state)
                s_IDLE: begin
                    ready <= 1'b1;
                    tx <= 1'b1;
                    if (start) begin
                        ready <= 1'b0;
                        tx_data <= data;
                        state <= s_START;
                        clk_count <= CLKS_PER_BIT - 1;
                        tx <= 1'b0; // start bit
                    end
                end
                s_START: begin
                    if (clk_count == 0) begin
                        state <= s_DATA;
                        bit_index <= 0;
                        clk_count <= CLKS_PER_BIT - 1;
                        tx <= tx_data[0];
                    end else begin
                        clk_count <= clk_count - 1;
                    end
                end
                s_DATA: begin
                    if (clk_count == 0) begin
                        if (bit_index == 7) begin
                            state <= s_STOP;
                            tx <= 1'b1; // stop bit
                        end else begin
                            bit_index <= bit_index + 1;
                            tx <= tx_data[bit_index + 1];
                        end
                        clk_count <= CLKS_PER_BIT - 1;
                    end else begin
                        clk_count <= clk_count - 1;
                    end
                end
                s_STOP: begin
                    if (clk_count == 0) begin
                        state <= s_IDLE;
                        ready <= 1'b1;
                    end else begin
                        clk_count <= clk_count - 1;
                    end
                end
                default: begin
                    state <= s_IDLE;
                    tx    <= 1'b1;
                    ready <= 1'b1;
                end
            endcase
        end
    end
endmodule
