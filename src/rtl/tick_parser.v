`timescale 1ns / 1ps

// -----------------------------------------------------------------------------
// tick_parser.v : assembles 12 UART bytes (id, price, vol; 32-bit little endian)
//   into one tick and pulses tick_valid for one cycle.
//   Resync: if the line is idle for GAP_CLKS cycles in the middle of a packet
//   (a lost byte, or the board was reset while the PC was sending), the partial
//   packet is dropped and the next byte is taken as byte 0 again.
// -----------------------------------------------------------------------------
module tick_parser #(
    parameter GAP_CLKS = 500000          // 5 ms at 100 MHz (a byte takes 87 us)
)(
    input  wire        clk,
    input  wire        rst,
    input  wire  [7:0] rx_data,
    input  wire        rx_valid,
    output reg  [31:0] tick_id,
    output reg  [31:0] tick_price,
    output reg  [31:0] tick_vol,
    output reg         tick_valid
);
    reg [3:0] byte_count;
    reg [31:0] id_reg, price_reg, vol_reg;
    reg [31:0] idle_cnt;

    always @(posedge clk) begin
        if (rst) begin
            byte_count <= 0;
            idle_cnt <= 0;
            tick_valid <= 0;
            id_reg <= 0;
            price_reg <= 0;
            vol_reg <= 0;
            tick_id <= 0;
            tick_price <= 0;
            tick_vol <= 0;
        end else begin
            tick_valid <= 0;
            if (rx_valid) idle_cnt <= 0;
            else if (byte_count != 0) begin
                if (idle_cnt >= GAP_CLKS - 1) begin
                    byte_count <= 0;
                    idle_cnt   <= 0;
                end else idle_cnt <= idle_cnt + 1;
            end
            if (rx_valid) begin
                case (byte_count)
                    4'd0:  id_reg[7:0]   <= rx_data;
                    4'd1:  id_reg[15:8]  <= rx_data;
                    4'd2:  id_reg[23:16] <= rx_data;
                    4'd3:  id_reg[31:24] <= rx_data;
                    4'd4:  price_reg[7:0]   <= rx_data;
                    4'd5:  price_reg[15:8]  <= rx_data;
                    4'd6:  price_reg[23:16] <= rx_data;
                    4'd7:  price_reg[31:24] <= rx_data;
                    4'd8:  vol_reg[7:0]   <= rx_data;
                    4'd9:  vol_reg[15:8]  <= rx_data;
                    4'd10: vol_reg[23:16] <= rx_data;
                    4'd11: begin
                        vol_reg[31:24] <= rx_data;
                        tick_id <= id_reg;
                        tick_price <= price_reg;
                        tick_vol <= {rx_data, vol_reg[23:0]};
                        tick_valid <= 1'b1;
                    end
                    default: ;
                endcase
                
                if (byte_count == 4'd11) byte_count <= 0;
                else byte_count <= byte_count + 1;
            end
        end
    end
endmodule
