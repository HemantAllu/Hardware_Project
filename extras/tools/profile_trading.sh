#!/bin/bash
# profile_trading.sh : where do the cycles of one trading decision go on our RV32IM core?
#   Builds hft_firmware.c twice - for RV32IM (multiply/divide hardware) and for RV32I (the compiler
#   calls libgcc software routines instead) - runs both on soc_top in simulation with the system-test
#   ticks, and prints the per-tick cycle budget (tools/profile_report.py).  Needs iverilog + RISC-V GCC.
set -euo pipefail
X=$(cd "$(dirname "$0")/.." && pwd); R=$X/../src/rtl; B=$X/build_prof; mkdir -p "$B"
PFX=${RISCV_PREFIX:-riscv64-unknown-elf}
CORE="$R/rv32im_core.v $R/alu.v $R/control.v $R/imm_gen.v $R/regfile.v $R/forwarding_unit.v $R/hazard_unit.v $R/muldiv_unit.v $R/imem.v $R/dmem.v $R/seg7_driver.v"
HFT="$R/hft_mmio.v $R/hft_multi.v $R/hft_alloc.v $R/hft_accelerator.v $R/tick_parser.v $R/uart.v"
iverilog -g2012 -o "$B/prof.vvp" "$X/tb/tb_prof.v" "$R/soc_top.v" $CORE $HFT
python3 "$X/tools/check_hft.py" gen "$B/ticks.txt" > /dev/null
for ARCH in rv32im rv32i; do
    mkdir -p "$B/$ARCH"
    ${PFX}-gcc -march=$ARCH -mabi=ilp32 -nostdlib -nostartfiles -ffreestanding -O2 -fno-asynchronous-unwind-tables \
        -T "$X/sw/link.ld" "$X/sw/crt0.S" "$X/hft_firmware.c" -lgcc -o "$B/$ARCH/prog.elf"
    ${PFX}-objcopy -O binary -j .text "$B/$ARCH/prog.elf" "$B/$ARCH/imem.bin"
    ${PFX}-objcopy -O binary -j .rodata -j .data "$B/$ARCH/prog.elf" "$B/$ARCH/dmem.bin"
    python3 "$X/tools/bin2hex.py" "$B/$ARCH/imem.bin" "$B/$ARCH/imem.hex"
    python3 "$X/tools/bin2hex.py" "$B/$ARCH/dmem.bin" "$B/$ARCH/dmem.hex"
    [ -s "$B/$ARCH/dmem.hex" ] || echo 00000000 > "$B/$ARCH/dmem.hex"
    vvp -n "$B/prof.vvp" +IMEM="$B/$ARCH/imem.hex" +DMEM="$B/$ARCH/dmem.hex" +TICKS="$B/ticks.txt" > "$B/$ARCH.log"
    python3 "$X/tools/check_hft.py" check "$B/ticks.txt" "$B/$ARCH.log" | grep RESULT | sed "s/^/$ARCH decisions vs model: /"
done
python3 "$X/tools/profile_report.py" "$B/rv32im.log" "$B/rv32i.log"
