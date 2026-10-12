#!/bin/sh
# Linux/macOS helper: build the project from ./src and open it in the Vivado GUI.
cd "$(dirname "$0")" || exit 1
if [ ! -f src/rtl/soc_top.v ]; then
    echo "ERROR: src/rtl/soc_top.v not found - extract the whole zip first." >&2
    exit 1
fi
if ! command -v vivado >/dev/null 2>&1; then
    echo "vivado is not on PATH. Source the Vivado settings64.sh first, or open Vivado and use" >&2
    echo "Tools -> Run Tcl Script -> create_project.tcl" >&2
    exit 1
fi
exec vivado -mode gui -log vivado_launch.log -journal vivado_launch.jou -source create_project.tcl
