# tools/toolenv.sh : sourced by the build scripts.  Finds the RISC-V GCC and Python 3 and exports
#   RISCV_PREFIX and PYTHON.  Values given by the user (make add RISCV_PREFIX=... PYTHON=...) are kept
#   when they work.  Done in bash, not in the Makefile, because the native Windows build of make
#   ("Built for Windows32", e.g. under Git Bash) does not run the Makefile's $(shell ...) through bash.
if [ -z "${RISCV_PREFIX:-}" ] || ! command -v "${RISCV_PREFIX}-gcc" >/dev/null 2>&1; then
    for _p in riscv64-unknown-elf riscv32-unknown-elf riscv-none-elf riscv64-elf riscv-none-embed; do
        if command -v "${_p}-gcc" >/dev/null 2>&1; then RISCV_PREFIX=$_p; break; fi
    done
fi
RISCV_PREFIX=${RISCV_PREFIX:-riscv64-unknown-elf}
_py_ok() { "$@" -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1; }
# on Windows "python3" is often only the Microsoft Store shortcut (it fails), so it is tested, not trusted
if [ -z "${PYTHON:-}" ] || ! _py_ok $PYTHON; then
    PYTHON=
    for _p in python3 python py; do
        if _py_ok $_p; then PYTHON=$_p; break; fi
    done
fi
PYTHON=${PYTHON:-python3}
export RISCV_PREFIX PYTHON
