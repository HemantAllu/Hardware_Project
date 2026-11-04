#!/bin/bash
# tools/check_tools.sh : `make check` - shows which tools the Makefile will use
. "$(dirname "$0")/toolenv.sh"
ok=1
have() { command -v "$1" >/dev/null 2>&1 || command -v "$1.bat" >/dev/null 2>&1; }
for t in make "$RISCV_PREFIX-gcc" "$RISCV_PREFIX-objcopy" "$RISCV_PREFIX-objdump" "$RISCV_PREFIX-nm"; do
    if command -v "$t" >/dev/null 2>&1; then echo "  found    $t"; else echo "  MISSING  $t"; ok=0; fi
done
if _py_ok $PYTHON; then echo "  found    $PYTHON ($($PYTHON --version 2>&1))"; else echo "  MISSING  Python 3"; ok=0; fi
# one Verilog simulator is enough: Icarus (iverilog + vvp) or Vivado (xvlog + xelab + xsim)
ic=0; vv=0
command -v iverilog >/dev/null 2>&1 && command -v vvp >/dev/null 2>&1 && ic=1
have xvlog && have xelab && have xsim && vv=1
[ $ic = 1 ] && echo "  found    Icarus Verilog (iverilog, vvp)"
[ $vv = 1 ] && echo "  found    Vivado simulator (xvlog, xelab, xsim)"
if [ $ic = 0 ] && [ $vv = 0 ]; then
    echo "  MISSING  a Verilog simulator: Vivado's bin folder on the PATH (xvlog/xelab/xsim) or Icarus Verilog"
    ok=0
fi
sim=${SIM:-auto}
if [ "$sim" = auto ]; then
    if [ $ic = 1 ]; then sim=icarus; elif [ $vv = 1 ]; then sim=xsim; fi
fi
if [ $ok = 1 ]; then
    echo "everything found (simulator: $sim): try  make add"
else
    echo "install the missing tools (see README_MAKE.md) and run  make check  again"
    exit 1
fi
