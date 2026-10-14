`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// tb_muldiv.v : self-checking unit test for muldiv_unit
//   * all 8 RV32M operations
//   * every pair from an edge-value table (0, 1, -1, INT_MIN, INT_MAX, ...)
//   * N_RANDOM random operand pairs per operation
//   * checks result and latency (MUL: 4 cycles in EX, DIV/REM: 36)
// -----------------------------------------------------------------------------
module tb_muldiv;
    parameter N_RANDOM = 3000;

    reg         clk = 0;
    reg         rst = 1;
    reg         start = 0;
    reg  [2:0]  funct3 = 0;
    reg  [31:0] a = 0, b = 0;
    wire        done;
    wire [31:0] result;

    muldiv_unit dut (.clk(clk), .rst(rst), .start(start), .funct3(funct3),
                     .a(a), .b(b), .done(done), .result(result));

    always #5 clk = ~clk;

    // ------------------------------------------------------------ reference
    function [31:0] ref_md;
        input [2:0]  f3;
        input [31:0] x;
        input [31:0] y;
        reg signed [63:0] sx, sy, sp;
        reg        [63:0] ux, uy, up;
        reg signed [31:0] qx, qy;
        begin
            sx = {{32{x[31]}}, x};
            sy = {{32{y[31]}}, y};
            ux = {32'b0, x};
            uy = {32'b0, y};
            qx = x;
            qy = y;
            case (f3)
                3'b000: begin sp = sx * sy; ref_md = sp[31:0];  end         // MUL
                3'b001: begin sp = sx * sy; ref_md = sp[63:32]; end         // MULH
                3'b010: begin sp = sx * $signed(uy); ref_md = sp[63:32]; end // MULHSU
                3'b011: begin up = ux * uy; ref_md = up[63:32]; end         // MULHU
                3'b100: begin                                               // DIV
                    if (y == 32'b0)                          ref_md = 32'hFFFF_FFFF;
                    else if (x == 32'h8000_0000 && y == 32'hFFFF_FFFF) ref_md = 32'h8000_0000;
                    else                                     ref_md = qx / qy;
                end
                3'b101: begin                                               // DIVU
                    if (y == 32'b0) ref_md = 32'hFFFF_FFFF;
                    else            ref_md = x / y;
                end
                3'b110: begin                                               // REM
                    if (y == 32'b0)                          ref_md = x;
                    else if (x == 32'h8000_0000 && y == 32'hFFFF_FFFF) ref_md = 32'h0;
                    else                                     ref_md = qx % qy;
                end
                default: begin                                              // REMU
                    if (y == 32'b0) ref_md = x;
                    else            ref_md = x % y;
                end
            endcase
        end
    endfunction

    // ------------------------------------------------------------ driver
    integer errors = 0;
    integer checks = 0;
    integer cyc;
    integer exp_lat;

    task run_op;
        input [2:0]  f3;
        input [31:0] x;
        input [31:0] y;
        reg   [31:0] expected;
        begin
            expected = ref_md(f3, x, y);
            exp_lat  = f3[2] ? 36 : 4;
            @(negedge clk);
            a = x; b = y; funct3 = f3; start = 1;
            cyc = 0;
            // count cycles from the start cycle until (and including) the done cycle
            @(posedge clk);
            cyc = 1;
            while (!done) begin
                @(posedge clk);
                cyc = cyc + 1;
                if (cyc > 100) begin
                    $display("FAIL: timeout f3=%0d a=%08x b=%08x", f3, x, y);
                    errors = errors + 1;
                    disable run_op;
                end
            end
            // `done` is now high (sampled just after the posedge): result is valid
            #1;
            checks = checks + 1;
            if (result !== expected) begin
                errors = errors + 1;
                if (errors < 20)
                    $display("FAIL: f3=%0d a=%08x b=%08x got=%08x exp=%08x", f3, x, y, result, expected);
            end
            if (cyc != exp_lat) begin
                errors = errors + 1;
                if (errors < 20)
                    $display("FAIL: latency f3=%0d got=%0d exp=%0d", f3, cyc, exp_lat);
            end
            // keep start high through the done cycle, drop it after
            @(negedge clk);
            start = 0;
            @(posedge clk);   // unit returns to IDLE
        end
    endtask

    reg [31:0] edge_v [0:11];
    integer i, j, k;
    reg [31:0] ra, rb;

    initial begin
        edge_v[0]  = 32'h0000_0000;
        edge_v[1]  = 32'h0000_0001;
        edge_v[2]  = 32'hFFFF_FFFF;
        edge_v[3]  = 32'h8000_0000;
        edge_v[4]  = 32'h7FFF_FFFF;
        edge_v[5]  = 32'h8000_0001;
        edge_v[6]  = 32'h0000_0002;
        edge_v[7]  = 32'hFFFF_FFFE;
        edge_v[8]  = 32'h0001_0000;
        edge_v[9]  = 32'h0000_FFFF;
        edge_v[10] = 32'h1234_5678;
        edge_v[11] = 32'hDEAD_BEEF;

        repeat (4) @(posedge clk);
        rst = 0;
        repeat (2) @(posedge clk);

        // edge-value cross product, all operations
        for (k = 0; k < 8; k = k + 1)
            for (i = 0; i < 12; i = i + 1)
                for (j = 0; j < 12; j = j + 1)
                    run_op(k[2:0], edge_v[i], edge_v[j]);

        // random operands (mix of full-range, small and sparse values)
        for (k = 0; k < 8; k = k + 1)
            for (i = 0; i < N_RANDOM; i = i + 1) begin
                ra = $random;
                rb = $random;
                case ($random & 3)
                    0: rb = rb >> ($random & 31);      // small divisor / multiplier
                    1: ra = ra >> ($random & 31);
                    2: begin ra = ra & 32'hFF00FF00; rb = rb | 32'h8000_0000; end
                    default: ;
                endcase
                run_op(k[2:0], ra, rb);
            end

        $display("tb_muldiv: %0d checks, %0d errors", checks, errors);
        if (errors == 0) $display("TB_MULDIV PASS");
        else             $display("TB_MULDIV FAIL");
        $finish;
    end
endmodule
