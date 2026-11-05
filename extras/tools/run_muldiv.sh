#!/bin/bash
# tools/run_muldiv.sh : `make muldiv` - the MUL/DIV unit testbench on Icarus or Vivado (see run_prog.sh)
set -e
X=$(cd "$(dirname "$0")/.." && pwd); cd "$X"
B=build_make; mkdir -p $B
have() { command -v "$1" >/dev/null 2>&1 || command -v "$1.bat" >/dev/null 2>&1; }
vtool() { local t=$1; shift; if command -v "$t" >/dev/null 2>&1; then "$t" "$@"; else "$t.bat" "$@"; fi; }
SIM=${SIM:-auto}
if [ "$SIM" = auto ]; then
    if command -v iverilog >/dev/null 2>&1; then SIM=icarus; elif have xvlog; then SIM=xsim
    else echo "ERROR: no Verilog simulator found (see README_MAKE.md)"; exit 1; fi
fi
if [ $SIM = icarus ]; then
    iverilog -g2005 -o $B/tb_muldiv.vvp tb/tb_muldiv.v ../src/rtl/muldiv_unit.v
    vvp -n $B/tb_muldiv.vvp | grep -E 'checks|PASS|FAIL'
else
    mkdir -p $B/xsim_muldiv
    (cd $B/xsim_muldiv && vtool xvlog ../../tb/tb_muldiv.v ../../../src/rtl/muldiv_unit.v > xvlog.out 2>&1 &&
        vtool xelab tb_muldiv -s tb_muldiv_sim -debug off > xelab.out 2>&1 &&
        vtool xsim tb_muldiv_sim -runall -log sim.txt > xsim.out 2>&1) || true
    tr -d '\r' < $B/xsim_muldiv/sim.txt | grep -E 'checks|PASS|FAIL' || { echo "ERROR: xsim run failed"; tail -20 $B/xsim_muldiv/*.out; exit 1; }
fi
