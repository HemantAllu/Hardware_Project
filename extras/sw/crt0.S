# crt0.S : minimal C startup for the RV32IM core (stack at the top of the 4 KB data RAM)
    .section .text.start
    .globl _start
_start:
    lui   sp, 0x10001            # sp = 0x10001000
    la    t0, __bss_start        # zero .bss: globals start at 0 after every reset,
    la    t1, __bss_end          # not only after the FPGA is configured
1:  bgeu  t0, t1, 2f
    sw    zero, 0(t0)
    addi  t0, t0, 4
    j     1b
2:  jal   ra, main
    ebreak                       # stop the core when main() returns
