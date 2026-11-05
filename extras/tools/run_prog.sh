#!/bin/bash
# tools/run_prog.sh <name> [--trace] : run build_make/<name>/{imem,dmem}.hex on the RV32IM core
# (testbench tb/tb_core.v) and print the result.  Used by the Makefile (make add, make sort, ...).
#
# Simulator: SIM=icarus (iverilog + vvp) or SIM=xsim (Vivado: xvlog + xelab + xsim, the same
# commands as a Vivado "make" flow, works in Windows Git Bash with only Vivado installed).
# SIM=auto (default): Icarus if it is installed, otherwise Vivado.
#   make add SIM=xsim      force Vivado's simulator
#
# The compiled testbench is kept (build_make/tb_core.vvp or build_make/xsim/) and only rebuilt
# when a Verilog file changed, so the second program runs much faster with xsim.
set -e
X=$(cd "$(dirname "$0")/.." && pwd)          # extras/
. "$X/tools/toolenv.sh"
NAME=$1
TRACE=0
[ "${2:-}" = "--trace" ] && TRACE=1
B=$X/build_make
D=$B/$NAME
RTL="../src/rtl"
FILES="tb/tb_core.v $RTL/alu.v $RTL/imm_gen.v $RTL/regfile.v $RTL/control.v $RTL/forwarding_unit.v \
       $RTL/hazard_unit.v $RTL/muldiv_unit.v $RTL/imem.v $RTL/dmem.v $RTL/rv32im_core.v"

# run a Vivado tool: `xvlog` (as in a Vivado make flow) or, if only the Windows launcher is
# visible, `xvlog.bat`
vtool() {
    local t=$1; shift
    if command -v "$t" >/dev/null 2>&1; then "$t" "$@"
    elif command -v "$t.bat" >/dev/null 2>&1; then "$t.bat" "$@"
    else echo "ERROR: $t not found (Vivado's bin folder is not on the PATH)"; return 127; fi
}
have() { command -v "$1" >/dev/null 2>&1 || command -v "$1.bat" >/dev/null 2>&1; }

SIM=${SIM:-auto}
if [ "$SIM" = auto ]; then
    if command -v iverilog >/dev/null 2>&1 && command -v vvp >/dev/null 2>&1; then SIM=icarus
    elif have xvlog && have xelab && have xsim; then SIM=xsim
    else
        echo "ERROR: no Verilog simulator found: install Icarus Verilog, or put Vivado's bin folder"
        echo "       (e.g. C:/Xilinx/Vivado/2024.2/bin) on the PATH - see README_MAKE.md.  make check  shows what is found."
        exit 1
    fi
fi

cd "$X"
case $SIM in
icarus)
    if [ ! -f "$B/tb_core.vvp" ] || [ -n "$(find $FILES -newer "$B/tb_core.vvp" 2>/dev/null)" ]; then
        mkdir -p "$B"
        iverilog -g2005 -o "$B/tb_core.vvp" $FILES
    fi
    PLUS=""
    [ $TRACE = 1 ] && PLUS="+TRACE"
    (cd "$D" && vvp -n ../tb_core.vvp $PLUS) 2>&1 | grep -v readmemh > "$D/sim.txt" || true
    ;;
xsim)
    S=$B/xsim                                   # compiled testbench (snapshot tb_core_sim)
    mkdir -p "$S"
    if [ ! -f "$S/.built" ] || [ -n "$(find $FILES -newer "$S/.built" 2>/dev/null)" ]; then
        echo "compiling the core with Vivado (xvlog + xelab), once ..."
        REL=""                                  # paths relative to build_make/xsim
        for f in $FILES; do REL="$REL ../../$f"; done
        if ! (cd "$S" && vtool xvlog $REL > xvlog.out 2>&1 && \
                         vtool xelab tb_core -s tb_core_sim -debug off > xelab.out 2>&1); then
            echo "ERROR: Vivado compile failed:"; tail -20 "$S/xvlog.out" "$S/xelab.out" 2>/dev/null; exit 1
        fi
        touch "$S/.built"
    fi
    # the testbench reads imem.hex / dmem.hex from the folder the simulation runs in
    cp "$D/imem.hex" "$S/imem.hex"
    cp "$D/dmem.hex" "$S/dmem.hex"
    rm -f "$S/sim.txt"
    if [ $TRACE = 1 ]; then
        (cd "$S" && vtool xsim tb_core_sim -testplusarg TRACE -runall -log sim.txt > xsim.out 2>&1) || true
    else
        (cd "$S" && vtool xsim tb_core_sim -runall -log sim.txt > xsim.out 2>&1) || true
    fi
    if [ ! -s "$S/sim.txt" ]; then echo "ERROR: xsim did not run:"; tail -20 "$S/xsim.out"; exit 1; fi
    tr -d '\r' < "$S/sim.txt" > "$D/sim.txt"   # Windows line endings -> plain lines
    ;;
*)
    echo "ERROR: SIM must be auto, icarus or xsim (got '$SIM')"; exit 1 ;;
esac

if [ $TRACE = 1 ]; then
    cp "$D/sim.txt" "$D/trace.txt"
else
    $PYTHON tools/show_result.py "$D/prog.elf" "$D/sim.txt" "$D/imem.hex" "$D/dmem.hex"
    echo " (simulator: $SIM)"
fi
