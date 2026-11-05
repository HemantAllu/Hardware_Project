# -----------------------------------------------------------------------------
# demo_board.S : FPGA demo for the RV32IM core (uses MUL / MULHU / DIV / REM)
#
# Part 1 (automatic, each result held on the 7-segment display for DELAY cycles,
#         LEDs show the step number):
#   1  0x1234 * 0x100            MUL    -> 00123400
#   2  0xFFFFFFFF * 0xFFFFFFFF   MULHU  -> FFFFFFFE
#   3  1000000 / 7               DIV    -> 00022E09
#   4  1000000 % 7               REM    -> 00000001
#   5  -100 / 7                  DIV    -> FFFFFFF2   (rounds toward zero)
#   6  5 / 0                     DIV    -> FFFFFFFF   (divide by zero)
#   7  clock cycles taken by one DIVU (measured with the CYCLE counter)
#
# Part 2 (interactive, forever): A = sw[7:0], B = sw[15:8]
#   display = [ A*B (16 bit) | (A/B)&0xFF | (A%B)&0xFF ]       LEDs = switches
#
# MMIO: 0x20000000 LED, +4 SEG, +8 SWITCH (read), +16 CYCLE (read)
# Build with a shorter delay for simulation:  -Wa,--defsym,DELAY=200
# -----------------------------------------------------------------------------
    .ifndef DELAY
    .equ DELAY, 50000000                  # 0.5 s at 100 MHz
    .endif

    .macro SHOW step, reg
    sw   \reg, 4(x30)                     # 7-segment value
    li   x29, \step
    sw   x29, 0(x30)                      # LEDs = step number
    jal  x1, wait
    .endm

    .section .text.start
    .globl _start
_start:
    lui  x30, 0x20000                     # x30 = MMIO base

    li   x10, 0x1234
    li   x11, 0x100
    mul  x5, x10, x11
    SHOW 1, x5

    li   x10, -1
    mulhu x5, x10, x10
    SHOW 2, x5

    li   x10, 1000000
    li   x11, 7
    div  x5, x10, x11
    SHOW 3, x5

    rem  x5, x10, x11
    SHOW 4, x5

    li   x10, -100
    div  x5, x10, x11
    SHOW 5, x5

    li   x10, 5
    div  x5, x10, x0
    SHOW 6, x5

    li   x10, 123456789
    lw   x6, 16(x30)                      # cycle counter before
    divu x5, x10, x11
    lw   x7, 16(x30)                      # cycle counter after
    sub  x5, x7, x6                       # includes the two MMIO loads
    SHOW 7, x5

interactive:
    lw   x1, 8(x30)                       # switches
    andi x2, x1, 0xFF                     # A
    srli x3, x1, 8                        # B
    mul  x4, x2, x3                       # A*B
    divu x5, x2, x3                       # A/B   (B = 0 -> 0xFFFFFFFF)
    remu x6, x2, x3                       # A%B   (B = 0 -> A)
    slli x4, x4, 16
    andi x5, x5, 0xFF
    slli x5, x5, 8
    andi x6, x6, 0xFF
    or   x4, x4, x5
    or   x4, x4, x6
    sw   x4, 4(x30)
    sw   x1, 0(x30)
    j    interactive

# ---- wait DELAY clock cycles (uses the CYCLE counter); link register x1 ------
wait:
    lw   x27, 16(x30)
    li   x26, DELAY
wait_loop:
    lw   x25, 16(x30)
    sub  x25, x25, x27
    bltu x25, x26, wait_loop
    jr   x1
