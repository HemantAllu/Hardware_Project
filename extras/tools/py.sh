#!/bin/bash
# tools/py.sh <script.py> [args] : run a Python tool with the Python 3 and RISC-V GCC that
# tools/toolenv.sh finds (Linux, WSL, macOS, Windows Git Bash / MSYS2)
. "$(dirname "$0")/toolenv.sh"
exec $PYTHON "$@"
