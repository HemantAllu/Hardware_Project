# -----------------------------------------------------------------------------
# timing_demo.S : short program that exercises every hazard mechanism once, for
#                 pipeline timing diagrams (see tools/pipeline_trace.py).
#   1. EX/MEM and MEM/WB forwarding          (addi chain)
#   2. load-use stall                        (lw -> add)
#   3. taken branch -> 2 flushed slots       (beq)
#   4. MUL stall (3 cycles) + forwarded result to the next instruction
#   5. DIV stall (35 cycles)
#   6. JAL
# -----------------------------------------------------------------------------
    .section .text.start
    .globl _start
_start:
    lui  x31, 0x10000
    addi x1, x0, 7              # 1: forwarding
    addi x2, x1, 3              #    EX/MEM -> EX
    add  x3, x2, x1             #    EX/MEM + MEM/WB
    sw   x3, 0(x31)
    lw   x4, 0(x31)             # 2: load-use
    add  x5, x4, x1             #    stalls one cycle
    beq  x5, x5, skip           # 3: taken, wrong-path instructions flushed
    addi x20, x0, 1
    addi x20, x0, 2
skip:
    mul  x6, x5, x2             # 4: multi-cycle multiply
    addi x7, x6, 1              #    result forwarded after the stall
    div  x8, x6, x2             # 5: multi-cycle divide
    add  x9, x8, x7
    jal  x10, done              # 6: jump
    addi x20, x0, 3
done:
    ebreak
