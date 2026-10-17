# report_timing.S : the 13-instruction sequence used for Figure 2 / Table 2.1 of the
# Block Diagram Report (load-use stall, forwarding, 4-cycle MUL, taken-branch flush).
# Trace it with tools/pipeline_trace.py.
    .section .text.start
    .globl _start
_start:
    lui   x10, 0x10000
    addi  x5, x0, 7
    sw    x5, 0(x10)
    lw    x6, 0(x10)
    add   x7, x6, x6
    mul   x8, x7, x5
    addi  x9, x8, 1
    beq   x9, x9, done
    addi  x1, x0, 1
    addi  x2, x0, 2
done:
    sub   x11, x9, x7
    sw    x11, 4(x10)
    ebreak
