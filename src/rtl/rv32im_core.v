`timescale 1ns/1ps
// -----------------------------------------------------------------------------
// rv32im_core.v : 5-stage RV32IM pipeline  (IF / ID / EX / MEM / WB)
//
//   IF  : PC register, instruction fetch (async instruction memory)
//   ID  : decode, immediate, register-file read (write-through), load-use check
//   EX  : operand forwarding, ALU, branch/jump resolution, RV32M unit
//   MEM : data-memory access (byte enables, load align / sign extend)
//   WB  : register-file write (data comes from the MEM/WB register)
//
// Hazard handling
//   * RAW data hazards     : forwarding from EX/MEM and MEM/WB into EX
//                            (+ register-file write-through for the 3rd case).
//                            The forwarding selects are computed one cycle early, when
//                            the instruction enters ID/EX (v12), so the rd/rs compares
//                            are no longer on the EX -> branch -> PC/flush path (the
//                            worst path in the v4 Vivado timing report).
//   * Load-use             : 1-cycle stall in ID (then forwarded from MEM/WB)
//   * Multi-cycle MUL/DIV  : pipeline front end is frozen while the M unit works
//   * Control hazards      : branches/JAL/JALR resolve in EX, predict-not-taken,
//                            taken => redirect PC + flush IF/ID and ID/EX
//                            (2-cycle penalty)
//
// Memory interface: instruction read is combinational; data read is
// combinational in MEM, data write happens at the clock edge ending MEM.
// Only naturally aligned loads/stores are supported.
// -----------------------------------------------------------------------------
module rv32im_core #(
    parameter [31:0] RESET_PC = 32'h0000_0000
)(
    input  wire        clk,
    input  wire        rst,            // synchronous, active high

    // instruction memory
    output wire [31:0] imem_addr,
    input  wire [31:0] imem_rdata,

    // data memory
    output wire [31:0] dmem_addr,
    output wire [31:0] dmem_wdata,
    output wire [3:0]  dmem_we,
    output wire        dmem_re,
    input  wire [31:0] dmem_rdata,

    // status / statistics (handy for the report and for testbenches)
    output wire        halted,         // EBREAK/ECALL reached EX
    output wire        retire,         // a real instruction leaves WB this cycle
    output wire        stat_load_use,  // load-use stall cycle
    output wire        stat_md_stall,  // M-unit stall cycle
    output wire        stat_flush      // taken branch/jump (2 bubbles follow)
);

    // =========================================================================
    // Global pipeline-control wires
    // =========================================================================
    wire        branch_taken;
    wire [31:0] branch_target;
    wire        ebreak_ex;
    wire        md_busy;
    wire        load_use;
    wire        stall_pc, stall_ifid, stall_idex;
    wire        bubble_idex, bubble_exmem;
    wire        flush_ifid, flush_idex;
    reg         halted_r;

    assign halted = halted_r;

    // =========================================================================
    // IF stage
    // =========================================================================
    reg  [31:0] pc;
    wire [31:0] pc_plus4 = pc + 32'd4;
    assign imem_addr = pc;

    always @(posedge clk) begin
        if (rst)                         pc <= RESET_PC;
        else if (branch_taken)           pc <= branch_target;
        else if (halted_r | ebreak_ex)   pc <= pc;
        else if (!stall_pc)              pc <= pc_plus4;
    end

    always @(posedge clk) begin
        if (rst)             halted_r <= 1'b0;
        else if (ebreak_ex)  halted_r <= 1'b1;
    end

    // ---- IF/ID register ------------------------------------------------------
    reg         if_id_valid;
    reg  [31:0] if_id_pc;
    reg  [31:0] if_id_instr;

    always @(posedge clk) begin
        if (rst || flush_ifid) begin
            if_id_valid <= 1'b0;
            if_id_pc    <= 32'b0;
            if_id_instr <= 32'h0000_0013;
        end else if (!stall_ifid) begin
            if_id_valid <= 1'b1;
            if_id_pc    <= pc;
            if_id_instr <= imem_rdata;
        end
    end

    // =========================================================================
    // ID stage
    // =========================================================================
    wire [4:0] id_rs1 = if_id_instr[19:15];
    wire [4:0] id_rs2 = if_id_instr[24:20];
    wire [4:0] id_rd  = if_id_instr[11:7];

    wire        id_reg_write, id_mem_read, id_mem_write;
    wire        id_is_branch, id_is_jal, id_is_jalr, id_is_muldiv, id_is_halt;
    wire [1:0]  id_a_sel;
    wire        id_b_sel;
    wire [3:0]  id_alu_op;
    wire        id_uses_rs1, id_uses_rs2;
    wire [31:0] id_imm;
    wire [31:0] id_rs1_data, id_rs2_data;

    control u_ctrl (
        .instr     (if_id_instr),
        .reg_write (id_reg_write),
        .mem_read  (id_mem_read),
        .mem_write (id_mem_write),
        .is_branch (id_is_branch),
        .is_jal    (id_is_jal),
        .is_jalr   (id_is_jalr),
        .is_muldiv (id_is_muldiv),
        .is_halt   (id_is_halt),
        .a_sel     (id_a_sel),
        .b_sel     (id_b_sel),
        .alu_op    (id_alu_op),
        .uses_rs1  (id_uses_rs1),
        .uses_rs2  (id_uses_rs2)
    );

    imm_gen u_imm (.instr(if_id_instr), .imm(id_imm));

    // write-back wires (declared here, driven in WB stage)
    reg         mem_wb_reg_write;
    reg  [4:0]  mem_wb_rd;
    reg  [31:0] mem_wb_data;
    reg         mem_wb_valid;
    wire        wb_we = mem_wb_reg_write & (mem_wb_rd != 5'd0);

    regfile u_rf (
        .clk    (clk),
        .raddr1 (id_rs1),
        .raddr2 (id_rs2),
        .rdata1 (id_rs1_data),
        .rdata2 (id_rs2_data),
        .we     (wb_we),
        .waddr  (mem_wb_rd),
        .wdata  (mem_wb_data)
    );

    // ---- ID/EX register ------------------------------------------------------
    reg         id_ex_valid;
    reg  [31:0] id_ex_pc;
    reg  [31:0] id_ex_rs1_data, id_ex_rs2_data, id_ex_imm;
    reg  [4:0]  id_ex_rs1, id_ex_rs2, id_ex_rd;
    reg  [3:0]  id_ex_alu_op;
    reg  [1:0]  id_ex_a_sel;
    reg         id_ex_b_sel;
    reg  [2:0]  id_ex_funct3;
    reg         id_ex_reg_write, id_ex_mem_read, id_ex_mem_write;
    reg         id_ex_is_branch, id_ex_is_jal, id_ex_is_jalr;
    reg         id_ex_is_muldiv, id_ex_is_halt;
    reg  [1:0]  id_ex_fwd_a, id_ex_fwd_b;     // forwarding selects for the instruction in EX

    // EX/MEM register outputs needed for forwarding (declared early)
    reg         ex_mem_valid;
    reg  [31:0] ex_mem_result;
    reg  [31:0] ex_mem_store_data;
    reg  [4:0]  ex_mem_rd;
    reg  [2:0]  ex_mem_funct3;
    reg         ex_mem_reg_write, ex_mem_mem_read, ex_mem_mem_write;

    // Forwarding selects for the instruction now in ID, as they will be when it is in EX:
    // what is in ID/EX now will be in EX/MEM then, and what is in EX/MEM now in MEM/WB.
    // (ID/EX only advances when the M unit is idle, so EX/MEM gets no bubble in that cycle.)
    // EX/MEM has priority: it holds the younger producer.  x0 is never forwarded.
    wire [1:0] id_fwd_a = (id_ex_reg_write  && (id_ex_rd  != 5'd0) && (id_ex_rd  == id_rs1)) ? 2'b10 :
                          (ex_mem_reg_write && (ex_mem_rd != 5'd0) && (ex_mem_rd == id_rs1)) ? 2'b01 : 2'b00;
    wire [1:0] id_fwd_b = (id_ex_reg_write  && (id_ex_rd  != 5'd0) && (id_ex_rd  == id_rs2)) ? 2'b10 :
                          (ex_mem_reg_write && (ex_mem_rd != 5'd0) && (ex_mem_rd == id_rs2)) ? 2'b01 : 2'b00;


    // Priority: reset/flush > hold (M unit busy) > load-use bubble > normal advance.
    // bubble_idex is never active together with stall_idex, so both "clear"
    // cases share one branch.
    always @(posedge clk) begin
        if (rst || flush_idex || bubble_idex) begin
            id_ex_valid     <= 1'b0;
            id_ex_pc        <= 32'b0;
            id_ex_rs1_data  <= 32'b0;
            id_ex_rs2_data  <= 32'b0;
            id_ex_imm       <= 32'b0;
            id_ex_rs1       <= 5'b0;
            id_ex_rs2       <= 5'b0;
            id_ex_rd        <= 5'b0;
            id_ex_alu_op    <= 4'b0;
            id_ex_a_sel     <= 2'b0;
            id_ex_b_sel     <= 1'b0;
            id_ex_funct3    <= 3'b0;
            id_ex_reg_write <= 1'b0;
            id_ex_mem_read  <= 1'b0;
            id_ex_mem_write <= 1'b0;
            id_ex_is_branch <= 1'b0;
            id_ex_is_jal    <= 1'b0;
            id_ex_is_jalr   <= 1'b0;
            id_ex_is_muldiv <= 1'b0;
            id_ex_is_halt   <= 1'b0;
            id_ex_fwd_a     <= 2'b00;
            id_ex_fwd_b     <= 2'b00;
        end else if (stall_idex) begin
            // hold (multi-cycle M instruction occupying EX)
        end else begin
            id_ex_valid     <= if_id_valid;
            id_ex_pc        <= if_id_pc;
            id_ex_rs1_data  <= id_rs1_data;
            id_ex_rs2_data  <= id_rs2_data;
            id_ex_imm       <= id_imm;
            id_ex_rs1       <= id_rs1;
            id_ex_rs2       <= id_rs2;
            id_ex_rd        <= id_rd;
            id_ex_alu_op    <= id_alu_op;
            id_ex_a_sel     <= id_a_sel;
            id_ex_b_sel     <= id_b_sel;
            id_ex_funct3    <= if_id_instr[14:12];
            id_ex_reg_write <= id_reg_write & if_id_valid;
            id_ex_mem_read  <= id_mem_read  & if_id_valid;
            id_ex_mem_write <= id_mem_write & if_id_valid;
            id_ex_is_branch <= id_is_branch & if_id_valid;
            id_ex_is_jal    <= id_is_jal    & if_id_valid;
            id_ex_is_jalr   <= id_is_jalr   & if_id_valid;
            id_ex_is_muldiv <= id_is_muldiv & if_id_valid;
            id_ex_is_halt   <= id_is_halt   & if_id_valid;
            id_ex_fwd_a     <= id_fwd_a;
            id_ex_fwd_b     <= id_fwd_b;
        end
    end

    // =========================================================================
    // EX stage
    // =========================================================================
    wire [1:0] fwd_a = id_ex_fwd_a;
    wire [1:0] fwd_b = id_ex_fwd_b;

`ifndef SYNTHESIS
    // Reference: the v11 combinational forwarding unit.  In the first cycle an instruction is
    // in EX (the only cycle its operands are used: an M instruction latches them then) the
    // registered selects must agree with it.
    wire [1:0] ref_fwd_a, ref_fwd_b;
    forwarding_unit u_fwd_ref (
        .ex_rs1        (id_ex_rs1),
        .ex_rs2        (id_ex_rs2),
        .mem_rd        (ex_mem_rd),
        .mem_reg_write (ex_mem_reg_write),
        .wb_rd         (mem_wb_rd),
        .wb_reg_write  (mem_wb_reg_write),
        .fwd_a         (ref_fwd_a),
        .fwd_b         (ref_fwd_b)
    );
    reg ex_first = 1'b0;                 // ID/EX was loaded with a new instruction last edge
    always @(posedge clk) ex_first <= !rst && !flush_idex && !bubble_idex && !stall_idex;
    always @(posedge clk)
        if (ex_first && id_ex_valid && ((fwd_a != ref_fwd_a) || (fwd_b != ref_fwd_b)))
            $display("ERROR rv32im_core: forwarding select mismatch at pc %08x (%b/%b vs %b/%b)",
                     id_ex_pc, fwd_a, fwd_b, ref_fwd_a, ref_fwd_b);
`endif

    wire [31:0] rs1_fwd = (fwd_a == 2'b10) ? ex_mem_result :
                          (fwd_a == 2'b01) ? mem_wb_data    : id_ex_rs1_data;
    wire [31:0] rs2_fwd = (fwd_b == 2'b10) ? ex_mem_result :
                          (fwd_b == 2'b01) ? mem_wb_data    : id_ex_rs2_data;

    // ---- ALU -----------------------------------------------------------------
    wire [31:0] alu_a = (id_ex_a_sel == 2'd0) ? rs1_fwd :
                        (id_ex_a_sel == 2'd1) ? id_ex_pc : 32'b0;
    wire [31:0] alu_b = id_ex_b_sel ? id_ex_imm : rs2_fwd;
    wire [31:0] alu_y;

    alu u_alu (.a(alu_a), .b(alu_b), .op(id_ex_alu_op), .y(alu_y));

    // ---- RV32M unit ----------------------------------------------------------
    wire        md_start = id_ex_valid & id_ex_is_muldiv;
    wire        md_done;
    wire [31:0] md_result;

    muldiv_unit u_md (
        .clk    (clk),
        .rst    (rst),
        .start  (md_start),
        .funct3 (id_ex_funct3),
        .a      (rs1_fwd),
        .b      (rs2_fwd),
        .done   (md_done),
        .result (md_result)
    );

    assign md_busy = md_start & ~md_done;

    // ---- branch / jump resolution -------------------------------------------
    wire br_eq  = (rs1_fwd == rs2_fwd);
    wire br_lt  = ($signed(rs1_fwd) < $signed(rs2_fwd));
    wire br_ltu = (rs1_fwd < rs2_fwd);
    reg  br_cond;
    always @(*) begin
        case (id_ex_funct3)
            3'b000:  br_cond =  br_eq;     // BEQ
            3'b001:  br_cond = ~br_eq;     // BNE
            3'b100:  br_cond =  br_lt;     // BLT
            3'b101:  br_cond = ~br_lt;     // BGE
            3'b110:  br_cond =  br_ltu;    // BLTU
            3'b111:  br_cond = ~br_ltu;    // BGEU
            default: br_cond = 1'b0;
        endcase
    end

    wire [31:0] pc_plus_imm  = id_ex_pc + id_ex_imm;
    wire [31:0] jalr_target  = (rs1_fwd + id_ex_imm) & 32'hFFFF_FFFE;

    assign branch_taken  = id_ex_valid & ((id_ex_is_branch & br_cond) | id_ex_is_jal | id_ex_is_jalr);
    assign branch_target = id_ex_is_jalr ? jalr_target : pc_plus_imm;
    assign ebreak_ex     = id_ex_valid & id_ex_is_halt;

    // ---- EX result mux -------------------------------------------------------
    wire [31:0] ex_result = (id_ex_is_jal | id_ex_is_jalr) ? (id_ex_pc + 32'd4) :
                             id_ex_is_muldiv               ? md_result          : alu_y;

    // ---- hazard unit ---------------------------------------------------------
    hazard_unit u_haz (
        .id_valid     (if_id_valid),
        .id_rs1       (id_rs1),
        .id_rs2       (id_rs2),
        .id_uses_rs1  (id_uses_rs1),
        .id_uses_rs2  (id_uses_rs2),
        .ex_valid     (id_ex_valid),
        .ex_mem_read  (id_ex_mem_read),
        .ex_rd        (id_ex_rd),
        .ex_md_busy   (md_busy),
        .ex_redirect  (branch_taken),
        .ex_halt      (ebreak_ex),
        .halted       (halted_r),
        .load_use     (load_use),
        .stall_pc     (stall_pc),
        .stall_ifid   (stall_ifid),
        .stall_idex   (stall_idex),
        .bubble_idex  (bubble_idex),
        .bubble_exmem (bubble_exmem),
        .flush_ifid   (flush_ifid),
        .flush_idex   (flush_idex)
    );

    // statistics (a stall that is overridden by a flush is not counted)
    assign stat_load_use = load_use & ~md_busy & ~branch_taken & ~ebreak_ex & ~halted_r;
    assign stat_md_stall = md_busy;
    assign stat_flush    = branch_taken;

    // ---- EX/MEM register -----------------------------------------------------
    always @(posedge clk) begin
        if (rst || bubble_exmem) begin
            ex_mem_valid      <= 1'b0;
            ex_mem_result     <= 32'b0;
            ex_mem_store_data <= 32'b0;
            ex_mem_rd         <= 5'b0;
            ex_mem_funct3     <= 3'b0;
            ex_mem_reg_write  <= 1'b0;
            ex_mem_mem_read   <= 1'b0;
            ex_mem_mem_write  <= 1'b0;
        end else begin
            ex_mem_valid      <= id_ex_valid;
            ex_mem_result     <= ex_result;
            ex_mem_store_data <= rs2_fwd;
            ex_mem_rd         <= id_ex_rd;
            ex_mem_funct3     <= id_ex_funct3;
            ex_mem_reg_write  <= id_ex_reg_write;
            ex_mem_mem_read   <= id_ex_mem_read;
            ex_mem_mem_write  <= id_ex_mem_write;
        end
    end

    // =========================================================================
    // MEM stage
    // =========================================================================
    wire [1:0] boff = ex_mem_result[1:0];

    assign dmem_addr = ex_mem_result;
    assign dmem_re   = ex_mem_valid & ex_mem_mem_read;

    reg [31:0] st_data;
    reg [3:0]  st_we;
    always @(*) begin
        case (ex_mem_funct3[1:0])
            2'b00: begin                                   // SB
                st_data = {4{ex_mem_store_data[7:0]}};
                st_we   = 4'b0001 << boff;
            end
            2'b01: begin                                   // SH
                st_data = {2{ex_mem_store_data[15:0]}};
                st_we   = 4'b0011 << {boff[1], 1'b0};
            end
            default: begin                                 // SW
                st_data = ex_mem_store_data;
                st_we   = 4'b1111;
            end
        endcase
    end
    assign dmem_wdata = st_data;
    assign dmem_we    = (ex_mem_valid & ex_mem_mem_write) ? st_we : 4'b0000;

    wire [7:0]  ld_byte = dmem_rdata[{boff, 3'b000} +: 8];
    wire [15:0] ld_half = dmem_rdata[{boff[1], 4'b0000} +: 16];
    reg  [31:0] load_data;
    always @(*) begin
        case (ex_mem_funct3)
            3'b000:  load_data = {{24{ld_byte[7]}},  ld_byte};   // LB
            3'b001:  load_data = {{16{ld_half[15]}}, ld_half};   // LH
            3'b010:  load_data = dmem_rdata;                     // LW
            3'b100:  load_data = {24'b0, ld_byte};               // LBU
            3'b101:  load_data = {16'b0, ld_half};               // LHU
            default: load_data = dmem_rdata;
        endcase
    end

    // ---- MEM/WB register -----------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            mem_wb_valid     <= 1'b0;
            mem_wb_reg_write <= 1'b0;
            mem_wb_rd        <= 5'b0;
            mem_wb_data      <= 32'b0;
        end else begin
            mem_wb_valid     <= ex_mem_valid;
            mem_wb_reg_write <= ex_mem_reg_write;
            mem_wb_rd        <= ex_mem_rd;
            mem_wb_data      <= ex_mem_mem_read ? load_data : ex_mem_result;
        end
    end

    // =========================================================================
    // WB stage: register-file write is wired in the ID section (u_rf)
    // =========================================================================
    assign retire = mem_wb_valid;

endmodule
