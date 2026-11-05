RV32IM 5-stage core - Vivado project for the Nexys A7-100T (xc7a100tcsg324-1)
=============================================================================

Open it  (3 steps - do them in this order)
------------------------------------------
1. EXTRACT THE WHOLE ZIP first (right-click -> Extract All...) to a SHORT path without spaces,
   e.g.  C:\rv32im_vivado.   Do NOT double-click files while the zip is still open in
   Explorer/WinRAR: only that one file is unpacked to a temp folder, the src\ folder is
   missing, and Vivado reports "files not found".  Also do not move rv32im.xpr out of the folder.
2. EITHER double-click  open_in_vivado.bat   (starts Vivado, builds the project, leaves it open)
   OR open Vivado yourself ->  Tools -> Run Tcl Script... -> create_project.tcl
   Both make Vivado write its own project into  vivado_proj\rv32im.xpr  from the files in src\.
   This is the reliable route and works with any Vivado version.
3. (Alternative) rv32im.xpr in this folder is a ready-made project file that I wrote by hand
   without Vivado, in 2018.3 format.  It only loads if src\ sits right beside it.  If Vivado
   says anything about missing files or a bad project file, use step 2 instead.

If Vivado says "files not found" - checklist
  * Is there a  src\rtl\soc_top.v  next to the file you opened?  If not, extract the whole zip.
  * Is the path short and free of spaces / non-ASCII characters?
  * Did you open  vivado_proj\rv32im.xpr  from an OLD run after moving or renaming the folder?
    Delete vivado_proj\ and run step 2 again.
  * Tell me the exact paths Vivado lists as missing (Tcl console / Messages window) and which
    Vivado version you have (Help -> About).

Check that it works - in this order
-----------------------------------
A. Simulation (about a minute):  Flow Navigator -> Run Simulation -> Run Behavioral Simulation.
   In the Tcl console type:  run all
   Expected final lines:   tb_muldiv: 25152 checks, 0 errors
                           TB_MULDIV PASS
   (this exercises every MUL/MULH/MULHSU/MULHU/DIV/DIVU/REM/REMU case incl. divide by zero)

B. Synthesis:        Run Synthesis.
   Expected: completes without errors. Warnings about unused signals are fine.
   If the log says "Cannot open file imem.mem": the two .mem files are not in the
   project (Sources -> Design Sources should list src/mem/imem.mem and dmem.mem).

C. Implementation + bitstream:  Run Implementation, then Generate Bitstream.
   Open "Report Timing Summary": WNS must be >= 0 (clock is 100 MHz). The v5 sources have not
   been through Vivado yet: check this after every change (the v4 margin was +0.4 ns).
   If WNS is negative, tell me the failing path - the likely fixes are an extra pipeline
   register in the multiplier (rtl/muldiv_unit.v) or running the core at 50 MHz.

D. On the board:  Open Hardware Manager -> Auto Connect -> Program Device.
   src/mem/imem.mem is the TRADING firmware (extras/hft_firmware.c). After programming, the
   7-segment display shows 00000000 (the hardware position in decimal lots) and waits for ticks
   from the PC. Run the dashboard (extras/README_REAL_DATA.md), e.g.
      python hft_dashboard.py --company apple --port COM6        (or nvidia, tesla, ... or all)
   LED0 BUY, LED1 SELL, LED2 hardware/software mismatch (must stay off), LED3 packets dropped,
   LED14 kill switch (SW0), LED15 core halted. CPU RESET (the red button) restarts the firmware.
   Old LED/7-segment demo instead: copy extras/sw/demo_board_imem.mem over src/mem/imem.mem and
   extras/sw/demo_board_dmem.mem over src/mem/dmem.mem, then re-run synthesis. It shows, half a
   second each:  00123400  FFFFFFFE  00022E09  00000001  FFFFFFF2  FFFFFFFF  (cycle count), then
   interactive mode (A = switches 0-7, B = switches 8-15, display = [A*B][A/B][A mod B]).

Alternatively (batch):  with the project open, Tcl console:  source build_bitstream.tcl
After synthesis search the log for "readmem": a warning ("could not open $readmem data file") means imem.mem/dmem.mem were not found.

Folder contents
---------------
  open_in_vivado.bat / .sh   one-click: builds the project from src/ and opens it in Vivado
  create_project.tcl         same thing from inside Vivado (Tools -> Run Tcl Script)
  rv32im.xpr                 hand-written project file (relative paths into src/), alternative
  src/rtl/                   all Verilog (top module: soc_top)
  src/constraints/           nexys_a7_100t.xdc (clock, switches, LEDs, 7-seg, reset)
  src/sim/tb_muldiv.v        self-checking testbench (simulation top)
  src/mem/imem.mem dmem.mem  board image: the trading firmware built from extras/hft_firmware.c
                             (rebuild with extras/tools/make_board_image.sh after any firmware change;
                             extras/tools/run_hft_tests.sh checks that the shipped image is current)
  build_bitstream.tcl        optional batch build
  extras/                    software (C/asm, build script), other testbenches (tb_core, tb_soc),
                             golden-model test tools and README_core_and_tests.md
                             (full regression needs iverilog + a RISC-V GCC; see that README)

Notes
-----
* v12 (CHANGES_V12_BUGFIXES.md): the shared-cash unit no longer grows with the number of engines and
  the core's forwarding selects are registered, both to add timing margin.  Neither has been through
  Vivado yet: run implementation for each HFT_N_MAX you use and check WNS >= 0.  The Yosys numbers
  below are from an older version.
* Independent synthesis sanity check (Yosys targeting Xilinx 7-series, NOT Vivado): the whole SoC
  synthesizes with no errors and no latches, about 1.5k LUTs, 750 flip-flops, 4 DSP48E1; the data
  memory maps to distributed RAM and the register file to RAM32M. Vivado's numbers will differ
  somewhat, but this is a tiny design for an XC7A100T. Timing at 100 MHz is not checked by Yosys.
* Nothing in this project has been run in Vivado by me. The Verilog itself was verified with
  Icarus Verilog against a golden model (see extras/README_core_and_tests.md).
* Check the pin numbers in src/constraints/nexys_a7_100t.xdc against Digilent's
  Nexys-A7-100T-Master.xdc if anything on the board misbehaves.
* To run a different program, build it with extras/sw/build.sh and overwrite
  src/mem/imem.mem and dmem.mem with the generated imem.hex / dmem.hex, then re-run synthesis.
* Tests (Linux/WSL with iverilog + riscv64-unknown-elf-gcc):
     bash extras/tools/run_hft_tests.sh      trading accelerator, firmware, flow control, shipped image
     python3 extras/tools/run_tests.py       RV32IM core regression
