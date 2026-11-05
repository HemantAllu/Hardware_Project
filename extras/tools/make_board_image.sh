#!/bin/bash
# make_board_image.sh : build extras/hft_firmware.c and install it as the board image
#   (src/mem/imem.mem + src/mem/dmem.mem).  Run this after EVERY change to hft_firmware.c or
#   crt0.S / link.ld, then re-run synthesis + bitstream, and check with run_hft_tests.sh
#   (stage 5 fails if the shipped image no longer matches the firmware's behaviour).
#   Needs a RISC-V GCC (riscv64-unknown-elf-gcc; override with RISCV_PREFIX).
set -euo pipefail
X=$(cd "$(dirname "$0")/.." && pwd)          # extras/
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
bash "$X/sw/build.sh" "$X/hft_firmware.c" "$OUT"
[ -s "$OUT/dmem.hex" ] || echo 00000000 > "$OUT/dmem.hex"
words=$(wc -l < "$OUT/imem.hex")
if [ "$words" -gt 2048 ]; then
    echo "ERROR: the firmware is $words words but the instruction memory has 2048 (IMEM_WORDS in soc_top.v)" >&2
    exit 1
fi
cp "$OUT/imem.hex" "$X/../src/mem/imem.mem"
cp "$OUT/dmem.hex" "$X/../src/mem/dmem.mem"
echo "installed $words instruction words into src/mem/imem.mem (and src/mem/dmem.mem)"
