/* Linker script for the RV32IM 5-stage core (Harvard: separate IMEM / DMEM).
 *   IMEM : 0x0000_0000  (program, .text)                        8 KB = IMEM_WORDS 2048 in soc_top.v
 *   DMEM : 0x1000_0000  (.rodata / .data / .bss, stack at top)  4 KB = DMEM_WORDS 1024 in soc_top.v
 * MMIO (soc_top) : 0x2000_0000 (see README)
 *
 * The lengths MUST match the memories in soc_top.v: the core only decodes the low address bits
 * (imem.v uses addr[AW+1:2]), so code past the end would silently wrap onto the start.
 * (v11 said 16K here, so an oversized program linked without any error.)
 *
 * .rodata lives in DMEM because the core can only LOAD from the data memory (Harvard).
 * Initialised .data is loaded only by the bitstream ($readmemh of dmem.mem): crt0 cannot
 * re-copy it after the CPU RESET button (there is no data-readable copy in IMEM), so a
 * variable that the program modifies must not rely on an initialiser - set it in code.
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

STACK_MIN = 512;    /* bytes kept free between the end of .bss and the top of DMEM */

MEMORY
{
    IMEM (rx)  : ORIGIN = 0x00000000, LENGTH = 8K
    DMEM (rw)  : ORIGIN = 0x10000000, LENGTH = 4K
}

SECTIONS
{
    .text   : { *(.text.start) *(.text*) } > IMEM
    .rodata : { *(.rodata*) *(.srodata*) } > DMEM
    .data   : { *(.data*) *(.sdata*) } > DMEM
    .bss    : { . = ALIGN(4); __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); __bss_end = .; } > DMEM
    /DISCARD/ : { *(.eh_frame*) *(.comment) *(.note*) *(.riscv.attributes) }

    ASSERT(SIZEOF(.text) <= LENGTH(IMEM), "IMEM overflow: program larger than 2048 words")
    ASSERT(__bss_end + STACK_MIN <= ORIGIN(DMEM) + LENGTH(DMEM), "DMEM overflow: less than 512 bytes left for the stack")
}
