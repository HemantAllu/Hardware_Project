#!/bin/bash
# Build a program for the RV32IM core and produce the memory images.
#   usage: sw/build.sh <prog.S | prog.c> [outdir]
#   output: outdir/imem.hex  outdir/dmem.hex  outdir/prog.elf  outdir/prog.dis
# Needs a RISC-V GNU toolchain (riscv64-unknown-elf-gcc works for rv32im too).
set -euo pipefail
SRC=$1; OUT=${2:-build_sw}
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../tools/toolenv.sh"         # finds the RISC-V GCC (riscv64-unknown-elf / riscv-none-elf ...) and Python
PFX=$RISCV_PREFIX
mkdir -p "$OUT"
FILES=("$SRC")
FLAGS=(-march=rv32im -mabi=ilp32 -nostdlib -nostartfiles -ffreestanding)
if [[ "$SRC" == *.c ]]; then
    FILES=("$HERE/crt0.S" "$SRC")
    FLAGS+=(-O2 -fno-asynchronous-unwind-tables)
fi
${PFX}-gcc "${FLAGS[@]}" -T "$HERE/link.ld" "${FILES[@]}" -o "$OUT/prog.elf"
${PFX}-objdump -d -M no-aliases,numeric "$OUT/prog.elf" > "$OUT/prog.dis"
${PFX}-objcopy -O binary -j .text "$OUT/prog.elf" "$OUT/imem.bin"
${PFX}-objcopy -O binary -j .rodata -j .data "$OUT/prog.elf" "$OUT/dmem.bin"
$PYTHON "$HERE/../tools/bin2hex.py" "$OUT/imem.bin" "$OUT/imem.hex"
$PYTHON "$HERE/../tools/bin2hex.py" "$OUT/dmem.bin" "$OUT/dmem.hex"
[ -s "$OUT/dmem.hex" ] || echo 00000000 > "$OUT/dmem.hex"   # no data: one zero word (readmemh needs a word)
echo "built $OUT/imem.hex ($(wc -l < "$OUT/imem.hex") words) and $OUT/dmem.hex ($(wc -l < "$OUT/dmem.hex") words)"
